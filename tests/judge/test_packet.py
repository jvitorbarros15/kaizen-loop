import json

import pytest

from kaizen.judge.packet import build_packet
from kaizen.record.model import RunRecord, ToolCall, Usage
from kaizen.signals import Signals, TestRun

SECRET = "ghp_0123456789abcdefghijABCDEFGHIJ012345"
CWD = "/home/someone/secretproj"

KEYS = {
    "task",
    "later_requests",
    "changed_files",
    "edits",
    "edits_truncated",
    "shell_edits_suspected",
    "test_runs",
    "check_runs",
    "verified_after_last_edit",
    "counts",
    "corrections",
}


def call(name, **inp):
    return ToolCall(id="t", name=name, input=inp)


def edit(path, old="a", new="b"):
    return call("Edit", file_path=path, old_string=old, new_string=new)


def shell(command, name="Bash"):
    return call(name, command=command)


def make(calls=(), messages=("do the thing",), cwd=CWD):
    return RunRecord(session_id="sess-0001", cwd=cwd, tool_calls=list(calls), user_messages=list(messages))


def packet(record=None, signals=None, **kw):
    return build_packet(record or make(), signals or Signals(), **kw)


def test_packet_is_blind():
    rec = RunRecord(
        session_id="3f2a9c1e-session",
        cwd="/home/jv/my-private-project",
        repo="my-private-repo",
        git_branch="feature/branchy",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T01:00:00Z",
        usage_by_model={"claude-sonnet-5-5": Usage(input=1, output=2)},
        user_messages=["fix the parser", "also handle empty input"],
        skills_used=["brainstorming"],
        cost_usd=1.25,
        final_message="All done, everything works perfectly.",
        tool_calls=[
            edit("/home/jv/my-private-project/src/parser.py"),
            shell("pytest -q"),
        ],
    )
    sig = Signals(test_runs=[TestRun("pytest -q", True)], total_tokens=999, cost_usd=1.25)
    p = json.dumps(build_packet(rec, sig))
    for leak in (
        rec.session_id,
        "claude-",
        "haiku",
        "sonnet",
        rec.repo,
        rec.cwd,
        rec.final_message,
        "brainstorming",
        "feature/branchy",
        "2026-01-01",
        "1.25",
    ):
        assert leak not in p


def test_every_key_on_empty_record():
    p = build_packet(RunRecord(session_id=""), Signals())
    assert set(p) == KEYS
    assert p["task"] == ""
    assert p["later_requests"] == []
    assert p["changed_files"] == []
    assert p["edits"] == []
    assert p["edits_truncated"] is False
    assert p["shell_edits_suspected"] is False
    assert p["test_runs"] == []
    assert p["check_runs"] == []
    assert p["verified_after_last_edit"] is False
    assert p["counts"] == {"tool_calls": 0, "tool_errors": 0, "rereads": 0, "retries": 0, "interruptions": 0}
    assert p["corrections"] == []


def test_task_is_cut():
    assert len(packet(make(messages=["x" * 5000]))["task"]) == 1500


def test_later_requests_cut_and_capped():
    msgs = ["first"] + [f"{i}-" + "y" * 400 for i in range(15)]
    p = packet(make(messages=msgs))
    assert len(p["later_requests"]) == 10
    assert all(len(m) == 300 for m in p["later_requests"])
    assert p["later_requests"][0].startswith("5-")
    assert p["later_requests"][-1].startswith("14-")


def test_relative_paths_and_outside_cwd_reduced_to_name():
    calls = [
        edit(f"{CWD}/src/a.py"),
        call("Write", file_path="/etc/other/b.py", content="x"),
        edit(f"{CWD}/src/a.py"),
        call("NotebookEdit", notebook_path=f"{CWD}/nb/c.ipynb", new_source="x"),
    ]
    p = packet(make(calls))
    assert p["changed_files"] == ["src/a.py", "b.py", "nb/c.ipynb"]
    assert [e["file"] for e in p["edits"]] == ["src/a.py", "b.py", "src/a.py", "nb/c.ipynb"]


def test_windows_paths():
    rec = make([edit("C:\\dev\\proj\\src\\a.py"), edit("D:\\elsewhere\\z.py")], cwd="C:\\dev\\proj")
    assert packet(rec)["changed_files"] == ["src/a.py", "z.py"]


def test_edit_shapes():
    calls = [
        edit(f"{CWD}/a.py", "o1", "n1"),
        call("Write", file_path=f"{CWD}/b.py", content="body"),
        call(
            "MultiEdit",
            file_path=f"{CWD}/c.py",
            edits=[{"old_string": "o2", "new_string": "n2"}, {"old_string": "o3", "new_string": "n3"}],
        ),
    ]
    assert packet(make(calls))["edits"] == [
        {"file": "a.py", "old": "o1", "new": "n1"},
        {"file": "b.py", "new": "body"},
        {"file": "c.py", "old": "o2", "new": "n2"},
        {"file": "c.py", "old": "o3", "new": "n3"},
    ]


def test_edit_limit_truncates_and_drops():
    calls = [
        edit(f"{CWD}/a.py", "o" * 2000, "n" * 2000),
        edit(f"{CWD}/b.py", "p" * 2000, "q" * 2000),
        edit(f"{CWD}/c.py", "r" * 10, "s" * 10),
    ]
    p = packet(make(calls))
    assert p["edits_truncated"] is True
    assert [e["file"] for e in p["edits"]] == ["a.py", "b.py"]
    assert sum(len(e.get("old", "")) + len(e["new"]) for e in p["edits"]) == 6000
    assert len(p["edits"][1]["old"]) == 2000
    assert p["edits"][1]["new"] == ""
    assert p["changed_files"] == ["a.py", "b.py", "c.py"]


def test_edit_limit_cuts_crossing_entry():
    p = packet(make([edit(f"{CWD}/a.py", "o" * 4000, "n" * 4000)]))
    assert p["edits_truncated"] is True
    e = p["edits"][0]
    assert len(e["old"]) + len(e["new"]) == 6000


def test_within_limit_not_truncated():
    p = packet(make([edit(f"{CWD}/a.py", "o" * 3000, "n" * 3000)]))
    assert p["edits_truncated"] is False


def test_include_code_false():
    p = packet(make([edit(f"{CWD}/a.py")]), include_code=False)
    assert p["edits"] == []
    assert p["edits_truncated"] is False
    assert p["changed_files"] == ["a.py"]


@pytest.mark.parametrize(
    "command,expected",
    [
        ("sed -i 's/a/b/' f.txt", True),
        ("sed -n -i.bak 's/a/b/' f.txt", True),
        ("echo hi > out.txt", True),
        ("echo hi >> out.txt", True),
        ("echo hi>out.txt", True),
        ("ls | tee files.txt", True),
        ("mv a b", True),
        ("rm -rf build", True),
        ("cp a b", True),
        ("git apply fix.patch", True),
        ("git checkout -- src/a.py", True),
        ("git restore src/a.py", True),
        ("patch -p1 < fix.diff", True),
        ("Set-Content -Path a.txt -Value hi", True),
        ("'x' | Out-File a.txt", True),
        ("Add-Content a.txt hi", True),
        ("python -c 'print(1)' 2> err.log", True),
        ("pytest -q", False),
        ("uv run pytest 2>&1 | tail -20", False),
        ("pytest > /dev/null", False),
        ("pytest 2>/dev/null", False),
        ("cmd >$null", False),
        ("cmd 2>&1", False),
        ("git status", False),
        ("git diff", False),
        ("git checkout main", False),
        ("python -m pytest tests/test_mv.py", False),
        ("ls -la", False),
        ("cat a.txt | grep x", False),
    ],
)
def test_shell_edits_suspected(command, expected):
    for name in ("Bash", "PowerShell"):
        assert packet(make([shell(command, name)]))["shell_edits_suspected"] is expected


def test_shell_edits_not_from_other_tools():
    assert packet(make([call("Read", file_path="a > b")]))["shell_edits_suspected"] is False


def test_verified_after_last_edit_true():
    rec = make([edit(f"{CWD}/a.py"), shell("pytest -q")])
    assert packet(rec, Signals(test_runs=[TestRun("pytest -q", True)]))["verified_after_last_edit"] is True


def test_verified_after_last_edit_check_run():
    rec = make([edit(f"{CWD}/a.py"), shell("ruff check .")])
    assert packet(rec, Signals(check_runs=[TestRun("ruff check .", True)]))["verified_after_last_edit"] is True


def test_verified_after_last_edit_false_when_run_before_edit():
    rec = make([shell("pytest -q"), edit(f"{CWD}/a.py")])
    assert packet(rec, Signals(test_runs=[TestRun("pytest -q", True)]))["verified_after_last_edit"] is False


def test_verified_after_last_edit_false_without_runs():
    rec = make([edit(f"{CWD}/a.py"), shell("ls")])
    assert packet(rec)["verified_after_last_edit"] is False


def test_verified_with_runs_and_no_edits():
    rec = make([shell("pytest -q")])
    assert packet(rec, Signals(test_runs=[TestRun("pytest -q", True)]))["verified_after_last_edit"] is True


def test_runs_shape_cut_and_capped():
    runs = [TestRun(f"{i} " + "c" * 300, True if i % 3 == 0 else None if i % 3 == 1 else False) for i in range(14)]
    p = packet(signals=Signals(test_runs=runs, check_runs=runs[:2]))
    assert len(p["test_runs"]) == 10
    assert p["test_runs"][0]["command"].startswith("4 ")
    assert all(len(r["command"]) == 120 for r in p["test_runs"])
    assert len(p["check_runs"]) == 2
    assert {r["passed"] for r in p["test_runs"]} == {True, False, None}


def test_passed_none_survives():
    p = packet(signals=Signals(test_runs=[TestRun("pytest", None)]))
    assert p["test_runs"] == [{"command": "pytest", "passed": None}]
    assert json.loads(json.dumps(p))["test_runs"][0]["passed"] is None


def test_corrections_none_survives():
    assert packet(signals=Signals(corrections=None))["corrections"] is None
    assert packet(signals=Signals(corrections=["use tabs"]))["corrections"] == ["use tabs"]


def test_counts():
    rec = make([shell("ls"), shell("ls")])
    sig = Signals(tool_error_count=3, reread_count=4, retry_count=5, interruptions=2)
    assert packet(rec, sig)["counts"] == {
        "tool_calls": 2,
        "tool_errors": 3,
        "rereads": 4,
        "retries": 5,
        "interruptions": 2,
    }


def test_secret_in_edit_input_never_appears():
    calls = [
        edit(f"{CWD}/a.py", f"token = '{SECRET}'", f"token = '{SECRET}'"),
        call("Write", file_path=f"{CWD}/b.py", content=f"KEY={SECRET}"),
    ]
    assert SECRET not in json.dumps(packet(make(calls, messages=[f"use {SECRET}"])))


def test_secret_straddling_cut_never_leaves_prefix():
    calls = [edit(f"{CWD}/a.py", "x" * 5990, f"token {SECRET}")]
    assert SECRET[:10] not in json.dumps(packet(make(calls)))


def test_final_message_never_appears():
    rec = make([edit(f"{CWD}/a.py")])
    rec.final_message = "Everything is verified and perfect."
    assert "verified and perfect" not in json.dumps(packet(rec))


def test_notebook_edit_entry_shape():
    p = packet(make([call("NotebookEdit", notebook_path=f"{CWD}/nb/c.ipynb", new_source="print(1)")]))
    assert p["edits"] == [{"file": "nb/c.ipynb", "new": "print(1)"}]


def test_notebook_edit_shares_edit_budget():
    p = packet(make([call("NotebookEdit", notebook_path=f"{CWD}/c.ipynb", new_source="n" * 7000)]))
    assert len(p["edits"][0]["new"]) == 6000
    assert p["edits_truncated"] is True


def test_notebook_edit_without_source_is_empty_text():
    p = packet(make([call("NotebookEdit", notebook_path=f"{CWD}/c.ipynb")]))
    assert p["edits"] == [{"file": "c.ipynb", "new": ""}]


def test_secret_straddling_task_cut_never_leaves_prefix():
    task = "x" * (1500 - 10) + SECRET
    assert SECRET[:6] not in json.dumps(packet(make(messages=[task])))


def test_secret_straddling_later_request_cut_never_leaves_prefix():
    later = "y" * (300 - 10) + SECRET
    assert SECRET[:6] not in json.dumps(packet(make(messages=["first", later])))


def pasted(text, tag_id="p1"):
    return f'<pasted_content id="{tag_id}">{text}</pasted_content>'


def test_pasted_block_in_task_becomes_a_marker():
    packet = build_packet(make(messages=(f"fix this {pasted('x' * 1204)} please",)), Signals())
    assert packet["task"] == "fix this [pasted text, 1,204 characters] please"


def test_pasted_block_in_later_requests_and_several_blocks():
    later = f"{pasted('abc')} and {pasted('y' * 12345, 'p2')}"
    packet = build_packet(make(messages=("task", later)), Signals())
    assert packet["later_requests"] == ["[pasted text, 3 characters] and [pasted text, 12,345 characters]"]


def test_message_that_is_only_pasted_text_is_just_the_marker():
    packet = build_packet(make(messages=(f"\n{pasted('git status output' * 50)}\n", pasted("npm ERR!"))), Signals())
    assert packet["task"] == "[pasted text, 850 characters]"
    assert packet["later_requests"] == ["[pasted text, 8 characters]"]


def test_unclosed_pasted_tag_runs_to_the_end_of_the_message():
    packet = build_packet(make(messages=('look <pasted_content id="p">' + "z" * 2000,)), Signals())
    assert packet["task"] == "look [pasted text, 2,000 characters]"


def test_pasted_text_is_replaced_before_the_cut_and_never_reaches_the_packet():
    long = pasted(f"npm ERR! {SECRET} " * 400)
    packet = build_packet(make(messages=(f"{long} then fix it", f"{long} and more")), Signals())
    assert packet["task"].endswith("then fix it")
    assert packet["later_requests"][0].endswith("and more")
    text = json.dumps(packet)
    assert "npm ERR" not in text and SECRET not in text


def test_message_without_pasted_tags_is_unchanged():
    packet = build_packet(make(messages=("plain <b>html</b> request",)), Signals())
    assert packet["task"] == "plain <b>html</b> request"
