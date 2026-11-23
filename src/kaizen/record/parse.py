import json
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from kaizen.record.model import RunRecord, ToolCall, Usage
from kaizen.redact import redact

MAX_TEXT = 2000
EXIT_CODE = re.compile(r"^Exit code (\d+)")
HARNESS_TAGS = (
    "system-reminder",
    "task-notification",
    "ide_opened_file",
    "ide_selection",
    "browser_instruction",
    "local-command-stdout",
    "local-command-stderr",
    "local-command-caveat",
    "command-message",
)
INTERRUPTED = "[Request interrupted by user"


WINDOW = 4096
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})
TOOL_INPUT_KEYS = {
    "Bash": ("command", "description", "run_in_background", "timeout"),
    "PowerShell": ("command", "description", "run_in_background", "timeout"),
    "Read": ("file_path", "offset", "limit"),
    "Edit": ("file_path", "old_string", "new_string", "replace_all"),
    "Write": ("file_path", "content"),
    "MultiEdit": ("file_path", "edits"),
    "NotebookEdit": ("notebook_path", "new_source", "cell_id", "edit_mode"),
    "Grep": ("pattern", "path", "glob", "type", "output_mode"),
    "Glob": ("pattern", "path"),
    "Agent": ("description", "prompt", "subagent_type", "model"),
    "Task": ("description", "prompt", "subagent_type", "model"),
    "Skill": ("skill", "args"),
    "WebFetch": ("url", "prompt"),
    "WebSearch": ("query",),
}


def _head(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return redact(text[: limit + WINDOW])[:limit]


def _tail(text: str, limit: int) -> str:
    return redact(text[-(limit + WINDOW):])[-limit:]


def _excerpt(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    half = MAX_TEXT // 2
    omitted = len(text) - MAX_TEXT
    return f"{_head(text, half)}\n[... {omitted} characters omitted ...]\n{_tail(text, half)}"


def _cut(value):
    if isinstance(value, str):
        return _head(value, MAX_TEXT)
    if isinstance(value, dict):
        return {k: _cut(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cut(v) for v in value]
    return value


def _minimise(name: str, tool_input: dict) -> dict:
    keep = TOOL_INPUT_KEYS.get(name)
    if keep is None:
        return dict.fromkeys(tool_input, "[OMITTED]")
    return {k: _cut(v) for k, v in tool_input.items() if k in keep}


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b["text"]
            for b in content
            if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    return ""


def _section(s: str, tag: str) -> tuple[str, str] | None:
    open_tag = "<" + tag
    nxt = s[len(open_tag):len(open_tag) + 1]
    if not s.startswith(open_tag) or not (nxt == ">" or nxt.isspace()):
        return None
    start = s.find(">")
    if start == -1:
        return "", ""
    end = s.find("</" + tag + ">", start)
    if end == -1:
        return "", ""
    return s[start + 1:end], s[end + len(tag) + 3:]


def _strip(text: str) -> str:
    s = text.lstrip()
    while s.startswith("<"):
        for tag in HARNESS_TAGS:
            hit = _section(s, tag)
            if hit is not None:
                s = hit[1].lstrip()
                break
        else:
            name = _section(s, "command-name")
            if name is None or not name[0]:
                return s
            command = name[0].strip()
            rest = name[1].lstrip()
            message = _section(rest, "command-message")
            if message is not None:
                rest = message[1].lstrip()
            args = _section(rest, "command-args")
            if args is not None:
                command = f"{command} {args[0].strip()}".strip()
                rest = args[1]
            rest = _strip(rest)
            return f"{command}\n{rest}" if rest else command
    return s


def _prompt(content) -> tuple[str, int]:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
    else:
        return "", 0
    kept = []
    interruptions = 0
    for part in parts:
        text = _strip(part)
        if text.startswith(INTERRUPTED):
            interruptions += 1
        elif text:
            kept.append(text)
    return _strip("\n".join(kept)), interruptions


def _repo(cwd: str) -> str | None:
    windows = "\\" in cwd or re.match(r"^[A-Za-z]:", cwd) is not None
    name = (PureWindowsPath(cwd) if windows else PurePosixPath(cwd)).name
    return name or None


def _when(ts: str) -> tuple[int, datetime | str]:
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return 1, ts
    return 0, parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _add(acc: Usage, u: Usage) -> None:
    acc.input += u.input
    acc.cache_write += u.cache_write
    acc.cache_read += u.cache_read
    acc.output += u.output


def _parse(path: Path, agent_id: str | None) -> RunRecord:
    session_id = ""
    cwd = ""
    git_branch = None
    version = None
    started = ""
    ended = ""
    skipped = 0
    interruptions = 0
    cost = None
    usage_by_msg: dict[str, tuple[str, Usage]] = {}
    calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    prompts: list[str] = []
    skills: list[str] = []
    prs: list[str] = []
    final_message = ""

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(obj, dict):
                skipped += 1
                continue

            if not session_id and isinstance(obj.get("sessionId"), str):
                session_id = obj["sessionId"]
            if not cwd and isinstance(obj.get("cwd"), str):
                cwd = obj["cwd"]
            if git_branch is None and isinstance(obj.get("gitBranch"), str):
                git_branch = obj["gitBranch"]
            if version is None and isinstance(obj.get("version"), str):
                version = obj["version"]
            ts = obj.get("timestamp")
            ts = ts if isinstance(ts, str) else ""
            if ts:
                if not started or _when(ts) < _when(started):
                    started = ts
                if not ended or _when(ts) > _when(ended):
                    ended = ts
            skill = obj.get("attributionSkill")
            if isinstance(skill, str) and skill and skill not in skills:
                skills.append(skill)

            kind = obj.get("type")
            msg = obj.get("message")
            msg = msg if isinstance(msg, dict) else {}
            content = msg.get("content")

            if kind == "assistant":
                u = msg.get("usage")
                if isinstance(u, dict) and not str(msg.get("model") or "").startswith("<"):
                    key = msg.get("id")
                    if not isinstance(key, str):
                        key = f"line-{n}"
                    seen_model, seen = usage_by_msg.get(key, ("", Usage()))
                    usage_by_msg[key] = (
                        str(msg.get("model") or "") or seen_model,
                        Usage(
                            input=max(seen.input, _int(u.get("input_tokens"))),
                            cache_write=max(seen.cache_write, _int(u.get("cache_creation_input_tokens"))),
                            cache_read=max(seen.cache_read, _int(u.get("cache_read_input_tokens"))),
                            output=max(seen.output, _int(u.get("output_tokens"))),
                        ),
                    )
                if isinstance(content, list):
                    said = "\n".join(
                        b["text"]
                        for b in content
                        if isinstance(b, dict)
                        and b.get("type") == "text"
                        and isinstance(b.get("text"), str)
                        and b["text"].strip()
                    )
                    if said:
                        final_message = said
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        tid = block.get("id")
                        if not isinstance(tid, str) or tid in by_id:
                            continue
                        tool_input = block.get("input")
                        name = str(block.get("name") or "")
                        call = ToolCall(
                            id=tid,
                            name=name,
                            input=_minimise(name, tool_input) if isinstance(tool_input, dict) else {},
                            timestamp=ts,
                            agent_id=agent_id,
                        )
                        calls.append(call)
                        by_id[tid] = call
            elif kind == "user":
                has_result = False
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        has_result = True
                        call = by_id.get(block.get("tool_use_id"))
                        if call is None:
                            continue
                        text = _text(block.get("content"))
                        call.is_error = block.get("is_error") is True
                        if call.is_error or call.name in SHELL_TOOLS:
                            call.output_excerpt = _excerpt(text)
                        if call.name in SHELL_TOOLS:
                            if call.is_error:
                                m = EXIT_CODE.match(text)
                                call.exit_code = int(m.group(1)) if m else None
                            else:
                                call.exit_code = 0
                if not has_result and obj.get("isMeta") is not True:
                    text, interrupted = _prompt(content)
                    interruptions += interrupted
                    if text:
                        prompts.append(text)
            elif kind == "cost-state":
                total = obj.get("totalCostUSD")
                if isinstance(total, (int, float)) and not isinstance(total, bool):
                    cost = float(total)
            elif kind == "pr-link":
                url = obj.get("prUrl")
                if isinstance(url, str) and url and url not in prs:
                    prs.append(url)

    usage: dict[str, Usage] = {}
    for model, u in usage_by_msg.values():
        _add(usage.setdefault(model or "unknown", Usage()), u)

    return RunRecord(
        session_id=session_id or path.stem,
        source="claude-code",
        cwd=cwd,
        repo=_repo(cwd) if cwd else None,
        git_branch=git_branch,
        started_at=started,
        ended_at=ended,
        agent_version=version,
        usage_by_model=usage,
        tool_calls=calls,
        user_messages=prompts,
        skills_used=skills,
        pr_urls=prs,
        cost_usd=cost,
        parent_session_id=None,
        skipped_lines=skipped,
        interruptions=interruptions,
        final_message=_excerpt(final_message),
    )


def parse_transcript(path: Path) -> RunRecord:
    return _parse(Path(path), None)


def parse_session(path: Path) -> RunRecord:
    path = Path(path)
    record = _parse(path, None)
    sub_dir = path.parent / path.stem / "subagents"
    if not sub_dir.is_dir():
        return record
    keyed = [(call.timestamp, call) for call in record.tool_calls]
    for sub in sorted(sub_dir.glob("agent-*.jsonl")):
        child = _parse(sub, sub.stem[len("agent-"):])
        for model, u in child.usage_by_model.items():
            _add(record.usage_by_model.setdefault(model, Usage()), u)
        prev = ""
        for call in child.tool_calls:
            prev = call.timestamp or prev
            keyed.append((prev, call))
        record.skipped_lines += child.skipped_lines
        record.interruptions += child.interruptions
        record.pr_urls += [u for u in child.pr_urls if u not in record.pr_urls]
        record.skills_used += [s for s in child.skills_used if s not in record.skills_used]
        if child.started_at and (not record.started_at or _when(child.started_at) < _when(record.started_at)):
            record.started_at = child.started_at
        if child.ended_at and (not record.ended_at or _when(child.ended_at) > _when(record.ended_at)):
            record.ended_at = child.ended_at
    keyed.sort(key=lambda pair: _when(pair[0]))
    record.tool_calls = [call for _, call in keyed]
    return record
