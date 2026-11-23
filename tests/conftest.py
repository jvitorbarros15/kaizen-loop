import json
from datetime import UTC, datetime, timedelta

import pytest

from kaizen.record.model import RunRecord, ToolCall


@pytest.fixture
def make_session():
    def make(directory, session_id, cwd="/home/dev/api-server", calls=2, started="2026-01-01", pr_url=None, prompts=None, edits=False):
        def entry(kind, content, n, **extra):
            return {
                "type": kind,
                "sessionId": session_id,
                "cwd": cwd,
                "timestamp": f"{started}T10:00:{n:02d}.000Z",
                "message": {"role": kind, "id": f"msg_{n}", "model": "claude-test", "content": content, **extra},
            }

        lines = [entry("user", (prompts or ["Fix the parser bug"])[0], 1)]
        for extra_prompt in (prompts or [])[1:]:
            lines.append(entry("user", extra_prompt, 2))
        n = 3
        for i in range(calls):
            block = {"type": "tool_use", "id": f"toolu_{n}", "name": "Read", "input": {"file_path": f"{cwd}/f{i}.py"}}
            lines.append(entry("assistant", [block], n, usage={"input_tokens": 100, "output_tokens": 10}))
            result = {"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": "ok"}
            lines.append(entry("user", [result], n + 1))
            n += 2
        if edits:
            edit = {"file_path": f"{cwd}/changed.py", "old_string": "a", "new_string": "b"}
            block = {"type": "tool_use", "id": f"toolu_{n}", "name": "Edit", "input": edit}
            lines.append(entry("assistant", [block], n, usage={"input_tokens": 100, "output_tokens": 10}))
            lines.append(entry("user", [{"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": "ok"}], n + 1))
        if pr_url:
            lines.append({"type": "pr-link", "sessionId": session_id, "prUrl": pr_url})
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{session_id}.jsonl"
        path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        return path

    return make


@pytest.fixture
def make_tasks():
    def make(session_id="s1", tasks=(), repo="api-server", base=None, cwd="/home/dev/api-server"):
        start = base or datetime(2026, 11, 22, 9, 0, tzinfo=UTC)

        def stamp(moment):
            return moment.isoformat().replace("+00:00", "Z")

        prompts, times, calls = [], [], []
        for i, spec in enumerate(tasks):
            opened = start + timedelta(hours=2 * i)
            for j, text in enumerate(spec["prompts"]):
                prompts.append(text)
                times.append(stamp(opened + timedelta(minutes=2 * j)))
            minute = 10
            for name in spec.get("files", ()):
                tool_input = {"file_path": f"{cwd}/{name}", "old_string": "a", "new_string": f"b-{name}"}
                calls.append(ToolCall(id=f"e{i}{minute}", name="Edit", input=tool_input,
                                      timestamp=stamp(opened + timedelta(minutes=minute)), exit_code=0))
                minute += 1
            if spec.get("test") is not None:
                calls.append(ToolCall(id=f"t{i}", name="Bash", input={"command": "pytest tests"},
                                      timestamp=stamp(opened + timedelta(minutes=minute)),
                                      exit_code=0 if spec["test"] else 1))
        return RunRecord(
            session_id=session_id,
            cwd=cwd,
            repo=repo,
            started_at=times[0] if times else "",
            ended_at=calls[-1].timestamp if calls else "",
            user_messages=prompts,
            user_message_times=times,
            tool_calls=calls,
        )

    return make
