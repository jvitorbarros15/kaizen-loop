import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from kaizen.record.model import RunRecord, ToolCall, Usage

MAX_TEXT = 2000
EXIT_CODE = re.compile(r"^Exit code (\d+)")
NOT_PROMPTS = ("<task-notification>", "<system-reminder>")


def _cut(value):
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, dict):
        return {k: _cut(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cut(v) for v in value]
    return value


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


def _repo(cwd: str) -> str | None:
    windows = "\\" in cwd or re.match(r"^[A-Za-z]:", cwd) is not None
    name = (PureWindowsPath(cwd) if windows else PurePosixPath(cwd)).name
    return name or None


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
    cost = None
    usage_by_msg: dict[str, tuple[str, Usage]] = {}
    calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    prompts: list[str] = []
    skills: list[str] = []
    prs: list[str] = []

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            line = line.strip()
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
                if not started or ts < started:
                    started = ts
                ended = max(ended, ts)
            skill = obj.get("attributionSkill")
            if isinstance(skill, str) and skill and skill not in skills:
                skills.append(skill)

            kind = obj.get("type")
            msg = obj.get("message")
            msg = msg if isinstance(msg, dict) else {}
            content = msg.get("content")

            if kind == "assistant":
                u = msg.get("usage")
                if isinstance(u, dict):
                    key = msg.get("id")
                    if not isinstance(key, str):
                        key = f"line-{n}"
                    usage_by_msg[key] = (
                        str(msg.get("model") or "unknown"),
                        Usage(
                            input=_int(u.get("input_tokens")),
                            cache_write=_int(u.get("cache_creation_input_tokens")),
                            cache_read=_int(u.get("cache_read_input_tokens")),
                            output=_int(u.get("output_tokens")),
                        ),
                    )
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        tid = block.get("id")
                        if not isinstance(tid, str) or tid in by_id:
                            continue
                        tool_input = block.get("input")
                        call = ToolCall(
                            id=tid,
                            name=str(block.get("name") or ""),
                            input=_cut(tool_input) if isinstance(tool_input, dict) else {},
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
                        call.output_excerpt = text[:MAX_TEXT]
                        if call.is_error:
                            m = EXIT_CODE.match(text)
                            call.exit_code = int(m.group(1)) if m else None
                        else:
                            call.exit_code = 0
                if not has_result and obj.get("isMeta") is not True:
                    text = _text(content)
                    if text and not text.lstrip().startswith(NOT_PROMPTS):
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
        _add(usage.setdefault(model, Usage()), u)

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
    )


def parse_transcript(path: Path) -> RunRecord:
    return _parse(Path(path), None)


def parse_session(path: Path) -> RunRecord:
    path = Path(path)
    record = _parse(path, None)
    sub_dir = path.parent / path.stem / "subagents"
    if not sub_dir.is_dir():
        return record
    for sub in sorted(sub_dir.glob("agent-*.jsonl")):
        child = _parse(sub, sub.stem[len("agent-"):])
        for model, u in child.usage_by_model.items():
            _add(record.usage_by_model.setdefault(model, Usage()), u)
        record.tool_calls.extend(child.tool_calls)
        record.skipped_lines += child.skipped_lines
    return record
