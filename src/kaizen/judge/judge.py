import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from kaizen.external import CLAUDE_ARGV, POSITIONAL_PROMPT, Runner, parse_model_json, run_subprocess
from kaizen.judge.rubric import RUBRIC, RUBRIC_ITEMS, RUBRIC_VERSION

MIN_SCORED = 3


@dataclass
class Verdict:
    quality: float | None = None
    reasons: list[str] = field(default_factory=list)
    backend: str | None = None
    items: dict[str, dict] = field(default_factory=dict)
    abstained: bool = False
    rubric_version: int = RUBRIC_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Verdict":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def _schema() -> dict:
    item = {
        "type": "object",
        "properties": {"score": {"type": ["number", "null"]}, "reason": {"type": "string"}},
        "required": ["score", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "object",
                "properties": dict.fromkeys(RUBRIC_ITEMS, item),
                "required": list(RUBRIC_ITEMS),
                "additionalProperties": False,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def _is_score(score: Any) -> bool:
    return isinstance(score, int | float) and not isinstance(score, bool) and 0 <= score <= 10


def _valid_items(parsed: Any) -> dict[str, dict] | None:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), dict):
        return None
    raw = parsed["items"]
    if set(raw) != set(RUBRIC_ITEMS):
        return None
    items = {}
    for name in RUBRIC_ITEMS:
        entry = raw[name]
        if not isinstance(entry, dict) or "score" not in entry:
            return None
        score = entry["score"]
        if score is not None and not _is_score(score):
            return None
        reason = entry.get("reason")
        items[name] = {"score": score, "reason": reason.strip() if isinstance(reason, str) else ""}
    return items


def _verdict(items: dict[str, dict], backend: str) -> Verdict:
    scores = [e["score"] for e in items.values() if e["score"] is not None]
    reasons = [f"{name}: {e['reason']}" for name, e in items.items() if e["reason"]]
    if len(scores) < MIN_SCORED:
        return Verdict(reasons=reasons, backend=backend, items=items, abstained=True)
    return Verdict(quality=round(sum(scores) / len(scores), 1), reasons=reasons, backend=backend, items=items)


def _packet_block(packet: dict) -> str:
    return "<packet>\n" + json.dumps(packet) + "\n</packet>"


def _ask_haiku(packet: dict, runner: Runner) -> Any | None:
    code, out = runner([*CLAUDE_ARGV, "--system-prompt", RUBRIC, POSITIONAL_PROMPT], _packet_block(packet))
    return parse_model_json(out) if code == 0 else None


def _ask_codex(packet: dict, runner: Runner) -> Any | None:
    workdir = tempfile.mkdtemp(prefix="kaizen-judge-")
    try:
        schema_path = os.path.join(workdir, "schema.json")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(_schema(), f)
        argv = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
            "--output-schema",
            schema_path,
            "-o",
            os.path.join(workdir, "out.json"),
            "-",
        ]
        code, out = runner(argv, RUBRIC + "\n\n" + _packet_block(packet))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if code != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


_ASKERS = {"haiku": _ask_haiku, "codex": _ask_codex}


def judge(packet: dict, backends: list[str], runner: Runner = run_subprocess) -> Verdict:
    for backend in backends:
        ask = _ASKERS.get(backend)
        if ask is None:
            continue
        items = _valid_items(ask(packet, runner))
        if items is not None:
            return _verdict(items, backend)
    return Verdict()


def backends_for(repo: str | None, config: dict) -> tuple[list[str], bool]:
    cfg = config["judge"]
    allowed = repo is not None and repo in cfg["codex_repos"]
    return [b for b in cfg["backends"] if b != "codex" or allowed], True
