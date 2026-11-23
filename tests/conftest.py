import json

import pytest


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
