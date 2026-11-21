import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from kaizen.redact import redact

Runner = Callable[[list[str], str | None], tuple[int, str]]

PROMPT = (
    "The input is a numbered list of messages that one user sent to a coding agent in one session. "
    "Return ONLY a JSON array of short strings (15 words at most each), one per place where the user "
    "corrected or redirected the agent: told it that it was wrong, asked it to redo something, pointed "
    "out something it forgot or skipped, or expressed doubt that it had done what it claimed. "
    "A new unrelated request is not a correction. Return [] when there are none."
)

_PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+")
_FENCE = re.compile(r"```[A-Za-z]*\s*(.*?)```", re.DOTALL)
_STATES = {"MERGED": "merged", "CLOSED": "closed", "OPEN": "open"}


def run_subprocess(argv: list[str], stdin: str | None = None) -> tuple[int, str]:
    try:
        exe = shutil.which(argv[0])
        if exe is None:
            return 1, ""
        proc = subprocess.run(
            [exe, *argv[1:]],
            input=stdin or "",
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env={**os.environ, "KAIZEN_INTERNAL": "1"},
        )
        return proc.returncode, proc.stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return 1, ""


def _loads(text: str) -> Any | None:
    try:
        return json.loads(text)
    except ValueError:
        return None


def parse_model_json(stdout: str) -> Any | None:
    env = _loads(stdout)
    if not isinstance(env, dict) or env.get("is_error"):
        return None
    result = env.get("result")
    if not isinstance(result, str):
        return None
    candidates = [result.strip()]
    candidates += [m.strip() for m in _FENCE.findall(result)]
    for text in candidates:
        parsed = _loads(text)
        if parsed is not None:
            return parsed
        starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
        if not starts:
            continue
        start = min(starts)
        end = text.rfind("]" if text[start] == "[" else "}")
        if end > start:
            parsed = _loads(text[start : end + 1])
            if parsed is not None:
                return parsed
    return None


def extract_corrections(user_messages: list[str], runner: Runner = run_subprocess) -> list[str]:
    if len(user_messages) < 2:
        return []
    stdin = "\n".join(f"[{i}] {redact(m)[:2000]}" for i, m in enumerate(user_messages[:60], 1))
    code, out = runner(["claude", "-p", "--model", "haiku", "--output-format", "json", PROMPT], stdin)
    if code != 0:
        return []
    parsed = parse_model_json(out)
    if not isinstance(parsed, list):
        return []
    items = [s.strip()[:200] for s in parsed if isinstance(s, str) and s.strip()]
    return items[:20]


def fetch_pr_outcome(pr_url: str, runner: Runner = run_subprocess) -> str | None:
    if not _PR_URL.fullmatch(pr_url):
        return None
    code, out = runner(["gh", "pr", "view", pr_url, "--json", "state,mergedAt"], None)
    if code != 0:
        return None
    data = _loads(out)
    if not isinstance(data, dict):
        return None
    state = data.get("state")
    return _STATES.get(state) if isinstance(state, str) else None
