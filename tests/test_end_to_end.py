import json

from kaizen.record.parse import parse_session
from kaizen.signals import extract_signals
from kaizen.store import Store

GHP = "ghp_0123456789abcdefghijABCDEFGHIJ012345"
SECRETS = [
    "Hunter2Hunter2",
    "ghp_0123456789",
    "hunter2hunter2",
    "sk-ant-FAKEFAKEFAKEFAKEFAKE1234",
    "abcd1234efgh",
    "dev123",
    "plainpw1",
    "sk_live_FAKE0123456789abcdefFAKE",
    "s3cr3tvalue",
]
SESSION = "00000000-0000-4000-8000-0000000000e2"


def line(kind, content, n, **extra):
    return {
        "type": kind,
        "sessionId": SESSION,
        "cwd": "/home/dev/project",
        "timestamp": f"2026-01-01T10:00:{n:02d}.000Z",
        "message": {"role": kind, "id": f"msg_{n}", "model": "claude-test", "content": content},
        **extra,
    }


def use(n, name, tool_input):
    block = {"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": tool_input}
    return line("assistant", [block], n)


def result(n, text, is_error=False):
    block = {"type": "tool_result", "tool_use_id": f"toolu_{n - 1}", "content": text, "is_error": is_error}
    return line("user", [block], n)


def write_session(tmp_path):
    straddle_head = "x" * 990 + " " + GHP + " " + "y" * 3000
    straddle_tail = "y" * 3000 + " " + GHP + " " + "x" * 990
    lines = [
        line("user", "Deploy it. The db uses DB_PASSWORD=dev123 for now", 1),
        use(2, "Bash", {"command": 'curl -u "admin:Hunter2Hunter2" https://example.com'}),
        result(3, straddle_head),
        use(4, "Bash", {"command": "cat .env"}),
        result(5, straddle_tail),
        use(6, "mcp__db__query", {"password": "hunter2hunter2", "sql": "select s3cr3tvalue"}),
        result(7, "connected with hunter2hunter2"),
        use(
            8,
            "Edit",
            {
                "file_path": "/home/dev/project/app.py",
                "old_string": "KEY = None",
                "new_string": 'API_KEY = "sk-ant-FAKEFAKEFAKEFAKEFAKE1234"',
            },
        ),
        result(9, "The file has been updated."),
        use(10, "Agent", {"description": "deploy", "prompt": "run deploy --token=abcd1234efgh now"}),
        result(11, "started"),
        use(12, "Write", {"file_path": "/home/dev/project/c.json", "content": '{"password": "plainpw1"}'}),
        result(13, "Exit code 1\nwrite failed: password=plainpw1 rejected", is_error=True),
        line("assistant", [{"type": "text", "text": "Done. Stripe key is sk_live_FAKE0123456789abcdefFAKE"}], 14),
    ]
    path = tmp_path / "projects" / f"{SESSION}.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def test_no_secret_survives_from_transcript_to_store(tmp_path):
    record = parse_session(write_session(tmp_path))
    store = Store(tmp_path / "store")
    store.save_run(record)
    store.save_score(record.session_id, {"signals": extract_signals(record).to_dict()})

    blob = b"".join(p.read_bytes() for p in (tmp_path / "store").rglob("*") if p.is_file())
    leaked = [s for s in SECRETS if s.encode() in blob]
    assert leaked == []
    assert store.audit() == []
    assert len(store.get_run(SESSION).tool_calls) == 6
