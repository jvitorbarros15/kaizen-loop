import re
from pathlib import PurePosixPath, PureWindowsPath

from kaizen.record.model import RunRecord
from kaizen.redact import redact, redact_obj
from kaizen.signals import SHELL_TOOLS, WRITE_TOOLS, Signals, TestRun, analyse_command

TASK_LIMIT = 1500
LATER_LIMIT = 300
LATER_MAX = 10
EDIT_BUDGET = 6000
RUNS_MAX = 10
COMMAND_LIMIT = 120

_PASTED = re.compile(r"<pasted_content\b[^>]*>(.*?)(?:</pasted_content>|\Z)", re.DOTALL)
_WINDOWS = re.compile(r"^[A-Za-z]:|^\\\\")
_REDIRECT = re.compile(r">>?")
_QUIET_TARGETS = ("&", "/dev/null", "$null", "nul")
_SED_IN_PLACE = re.compile(r"\bsed\b[^|;&\n]*?\s(?:-[A-Za-z]*i\b|--in-place)")
_MUTATING_WORDS = re.compile(r"(?<![\w.\-])(?:tee|mv|rm|cp|patch)(?![\w.\-])")
_GIT_MUTATING = re.compile(r"\bgit\s+(?:apply\b|restore\b|checkout\b[^|;&\n]*\s--(?:\s|$))")
_POWERSHELL_WRITERS = re.compile(r"\b(?:Set-Content|Out-File|Add-Content)\b", re.IGNORECASE)


def without_pasted(message: str) -> str:
    return _PASTED.sub(lambda m: f"[pasted text, {len(m.group(1)):,} characters]", message).strip()


def _relative(path: str, cwd: str) -> str:
    windows = bool(_WINDOWS.match(path) or _WINDOWS.match(cwd) or "\\" in path)
    pure = PureWindowsPath if windows else PurePosixPath
    p = pure(path)
    if p.is_absolute() and cwd:
        try:
            rel = p.relative_to(pure(cwd))
        except ValueError:
            return p.name
        if rel.parts:
            return rel.as_posix()
        return p.name
    if p.is_absolute() or ".." in p.parts:
        return p.name
    return p.as_posix()


def _writes_files(command: str) -> bool:
    for m in _REDIRECT.finditer(command):
        before = command[: m.start()][-1:]
        if before in ("-", "="):
            continue
        target = command[m.end() :].lstrip().lower()
        if target and not target.startswith(_QUIET_TARGETS):
            return True
    return bool(
        _SED_IN_PLACE.search(command)
        or _MUTATING_WORDS.search(command)
        or _GIT_MUTATING.search(command)
        or _POWERSHELL_WRITERS.search(command)
    )


def _text(value: object) -> str:
    return redact(value) if isinstance(value, str) else ""


def _raw_edits(record: RunRecord) -> list[tuple[str, str | None, str]]:
    found: list[tuple[str, str | None, str]] = []
    for tc in record.tool_calls:
        inp = tc.input if isinstance(tc.input, dict) else {}
        path = inp.get("notebook_path") if tc.name == "NotebookEdit" else inp.get("file_path")
        if not isinstance(path, str) or not path:
            continue
        rel = _relative(path, record.cwd)
        if tc.name == "NotebookEdit":
            found.append((rel, None, _text(inp.get("new_source"))))
        elif tc.name == "Edit":
            found.append((rel, _text(inp.get("old_string")), _text(inp.get("new_string"))))
        elif tc.name == "Write":
            found.append((rel, None, _text(inp.get("content"))))
        elif tc.name == "MultiEdit":
            for sub in inp.get("edits") or []:
                if isinstance(sub, dict):
                    found.append((rel, _text(sub.get("old_string")), _text(sub.get("new_string"))))
    return found


def _limited_edits(raw: list[tuple[str, str | None, str]]) -> tuple[list[dict], bool]:
    out: list[dict] = []
    remaining = EDIT_BUDGET
    truncated = False
    for file, old, new in raw:
        if remaining <= 0:
            truncated = True
            break
        old_text = old
        new_text = new
        if old_text is not None and len(old_text) > remaining:
            old_text, new_text = old_text[:remaining], ""
            truncated = True
        elif len(new_text) > remaining - len(old_text or ""):
            new_text = new_text[: remaining - len(old_text or "")]
            truncated = True
        remaining -= len(old_text or "") + len(new_text)
        entry = {"file": file, "new": new_text}
        if old_text is not None:
            entry = {"file": file, "old": old_text, "new": new_text}
        out.append(entry)
    return out, truncated


def _runs(runs: list[TestRun]) -> list[dict]:
    return [{"command": r.command[:COMMAND_LIMIT], "passed": r.passed} for r in runs[-RUNS_MAX:]]


def _verified_after_last_edit(record: RunRecord, signals: Signals) -> bool:
    known = {r.command for r in [*signals.test_runs, *signals.check_runs]}
    last_edit = -1
    for i, tc in enumerate(record.tool_calls):
        if tc.name in WRITE_TOOLS:
            last_edit = i
    if last_edit == -1:
        return bool(known)
    for tc in record.tool_calls[last_edit + 1 :]:
        if tc.name not in SHELL_TOOLS or not isinstance(tc.input, dict):
            continue
        command = tc.input.get("command")
        if isinstance(command, str) and (analyse_command(command) or command[:200] in known):
            return True
    return False


def build_packet(record: RunRecord, signals: Signals, include_code: bool = True) -> dict:
    messages = record.user_messages
    changed: list[str] = []
    for tc in record.tool_calls:
        if tc.name not in WRITE_TOOLS or not isinstance(tc.input, dict):
            continue
        path = tc.input.get("file_path", tc.input.get("notebook_path"))
        if isinstance(path, str) and path:
            rel = _relative(path, record.cwd)
            if rel not in changed:
                changed.append(rel)
    edits, truncated = _limited_edits(_raw_edits(record)) if include_code else ([], False)
    shell_edits = any(
        tc.name in SHELL_TOOLS
        and isinstance(tc.input, dict)
        and isinstance(tc.input.get("command"), str)
        and _writes_files(tc.input["command"])
        for tc in record.tool_calls
    )
    packet = {
        "task": redact(without_pasted(messages[0]))[:TASK_LIMIT] if messages else "",
        "later_requests": [redact(without_pasted(m))[:LATER_LIMIT] for m in messages[1:][-LATER_MAX:]],
        "changed_files": changed,
        "edits": edits,
        "edits_truncated": truncated,
        "shell_edits_suspected": shell_edits,
        "test_runs": _runs(signals.test_runs),
        "check_runs": _runs(signals.check_runs),
        "verified_after_last_edit": _verified_after_last_edit(record, signals),
        "counts": {
            "tool_calls": len(record.tool_calls),
            "tool_errors": signals.tool_error_count,
            "rereads": signals.reread_count,
            "retries": signals.retry_count,
            "interruptions": signals.interruptions,
        },
        "corrections": signals.corrections,
    }
    return redact_obj(packet)
