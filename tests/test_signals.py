import time
from pathlib import Path

import pytest

from kaizen.record.model import RunRecord, ToolCall, Usage
from kaizen.record.parse import parse_transcript
from kaizen.signals import Signals, TestRun, extract_signals, strength_of

FIX = Path(__file__).parent / "fixtures"


def call(name, is_error=False, exit_code=None, agent_id=None, **input):
    return ToolCall(
        id="t", name=name, input=input, is_error=is_error, exit_code=exit_code, agent_id=agent_id
    )


def sig(*calls, **rec):
    return extract_signals(RunRecord(session_id="s", tool_calls=list(calls), **rec))


def test_basic_fixture():
    s = extract_signals(parse_transcript(FIX / "session_basic.jsonl"))
    assert [t.passed for t in s.test_runs] == [False, True]
    assert s.tests_passed_last is True
    assert s.reread_count == 1
    assert s.tool_error_count == 1
    assert s.total_tokens == 7115
    assert s.strength == "strong"


def test_read_after_edit_not_reread():
    s = sig(call("Read", file_path="a.py"), call("Edit", file_path="a.py"), call("Read", file_path="a.py"))
    assert s.reread_count == 0


def test_plain_reread_counted():
    s = sig(call("Read", file_path="a.py"), call("Read", file_path="a.py"), call("Read", file_path="a.py"))
    assert s.reread_count == 2
    assert s.reread_files == {"a.py": 2}


def test_edit_other_file_does_not_reset():
    s = sig(call("Read", file_path="a.py"), call("Edit", file_path="b.py"), call("Read", file_path="a.py"))
    assert s.reread_count == 1


def test_different_offset_not_reread():
    s = sig(
        call("Read", file_path="a.py", offset=0, limit=10),
        call("Read", file_path="a.py", offset=10, limit=10),
        call("Read", file_path="a.py", offset=0, limit=10),
    )
    assert s.reread_count == 1


def test_subagent_read_not_reread():
    s = sig(call("Read", file_path="a.py"), call("Read", file_path="a.py", agent_id="x"))
    assert s.reread_count == 0


def test_windows_path_normalised():
    s = sig(call("Read", file_path="C:\\Dev\\A.py"), call("Read", file_path="c:/dev/a.py"))
    assert s.reread_count == 1


def test_posix_path_case_sensitive():
    s = sig(call("Read", file_path="/Dev/A.py"), call("Read", file_path="/dev/a.py"))
    assert s.reread_count == 0


def test_failed_read_ignored():
    s = sig(
        call("Read", is_error=True, file_path="a.py"),
        call("Read", file_path="a.py"),
        call("Read", file_path="a.py", is_error=True),
    )
    assert s.reread_count == 0


def test_retry_same_failing_command_twice():
    s = sig(call("Bash", is_error=True, command="make"), call("Bash", is_error=True, command="make"))
    assert s.retry_count == 1


def test_retry_counts_even_if_second_succeeds():
    s = sig(call("Bash", is_error=True, command="make"), call("Bash", command="make"))
    assert s.retry_count == 1


def test_success_then_repeat_not_retry():
    s = sig(call("Bash", command="make"), call("Bash", command="make"))
    assert s.retry_count == 0


def test_retry_after_edit_not_retry():
    s = sig(
        call("Bash", is_error=True, command="make"),
        call("Write", file_path="x"),
        call("Bash", command="make"),
    )
    assert s.retry_count == 0


def test_retry_different_agent_not_retry():
    s = sig(call("Bash", is_error=True, command="make"), call("Bash", command="make", agent_id="x"))
    assert s.retry_count == 0


def test_tool_error_count():
    s = sig(call("Read", is_error=True), call("Bash", command="ls"), call("Bash", is_error=True))
    assert s.tool_error_count == 2


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest",
        "uv run pytest -q",
        "cd api && python -m pytest tests/",
        "CI=1 npm test",
        "npm run test:unit",
        "npm run test",
        "poetry run pytest",
        "pipenv run pytest",
        "npx jest",
        "npx vitest run",
        "pnpm exec vitest",
        "pnpm test",
        "pnpm run test",
        "yarn test",
        "yarn jest",
        "python3 -m pytest",
        "py -m pytest",
        "go test ./...",
        "cargo test",
        "dotnet test",
        "mvn test",
        "gradle test",
        "./gradlew test",
        "echo hi; pytest",
        "ls | pytest",
        "ls\npytest",
        "false || pytest",
        "A=1 B=2 uv run python -m pytest",
        "echo 'a && b' && pytest",
    ],
)
def test_is_test_run(cmd):
    assert len(sig(call("Bash", command=cmd)).test_runs) == 1
    assert len(sig(call("PowerShell", command=cmd)).test_runs) == 1


@pytest.mark.parametrize(
    "cmd",
    [
        "cat docs/pytest-notes.md",
        "grep pytest pyproject.toml",
        "pip install pytest",
        "uv add pytest",
        'echo "run pytest later"',
        "echo 'a && pytest'",
        "echo done; echo 'x; pytest'",
        "npm install",
        "npm run build",
        "npm run testing-docs",
        "pytester",
        "yarn add jest",
        "go build",
        "ls",
        "",
    ],
)
def test_is_not_test_run(cmd):
    assert sig(call("Bash", command=cmd)).test_runs == []


def test_non_shell_tool_not_test_run():
    assert sig(call("Read", command="pytest")).test_runs == []


def test_missing_or_bad_command_does_not_crash():
    s = sig(call("Bash"), call("Bash", command=None), call("Bash", command=5), call("Bash", command=["pytest"]))
    assert s.test_runs == []
    assert s.retry_count == 0


def test_read_with_bad_path_does_not_crash():
    s = sig(call("Read"), call("Read", file_path=3), call("Edit"))
    assert s.reread_count == 0


def test_passed_uses_exit_code_then_error_flag():
    s = sig(
        call("Bash", command="pytest", is_error=True, exit_code=0),
        call("Bash", command="pytest", is_error=False, exit_code=1),
        call("Bash", command="pytest", is_error=True, exit_code=None),
        call("Bash", command="pytest", is_error=False, exit_code=None),
    )
    assert [t.passed for t in s.test_runs] == [True, False, False, True]
    assert s.tests_passed_last is True


def test_last_run_over_all_agents():
    s = sig(
        call("Bash", command="pytest", exit_code=0),
        call("Bash", command="pytest", is_error=True, exit_code=1, agent_id="x"),
    )
    assert s.tests_passed_last is False


def test_no_test_runs_gives_none():
    assert sig(call("Bash", command="ls")).tests_passed_last is None


def test_command_truncated():
    s = sig(call("Bash", command="pytest " + "x" * 500))
    assert len(s.test_runs[0].command) == 200


def test_two_test_segments_one_run():
    assert len(sig(call("Bash", command="pytest && pytest -x")).test_runs) == 1


def test_weak_when_nothing():
    s = sig(call("Bash", command="ls"))
    assert s.strength == "weak"
    assert s.interruptions == 0


def test_interruptions_alone_strong():
    assert sig(interruptions=1).strength == "strong"


def test_strength_of_pr_and_corrections():
    s = sig()
    assert strength_of(s) == "weak"
    s.pr_outcome = "merged"
    assert strength_of(s) == "strong"
    s.pr_outcome = None
    s.corrections = ["no, use X"]
    assert strength_of(s) == "strong"


def test_tokens_and_cost_and_placeholders():
    s = sig(
        usage_by_model={"a": Usage(1, 2, 3, 4), "b": Usage(10, 0, 0, 0)},
        cost_usd=1.5,
        interruptions=2,
    )
    assert s.total_tokens == 20
    assert s.cost_usd == 1.5
    assert s.interruptions == 2
    assert s.pr_outcome is None
    assert s.corrections == []


def test_round_trip():
    s = sig(
        call("Bash", command="pytest", exit_code=1, is_error=True),
        call("Read", file_path="a"),
        call("Read", file_path="a"),
        cost_usd=0.5,
    )
    s.corrections = ["x"]
    s.pr_outcome = "open"
    d = s.to_dict()
    assert d["test_runs"] == [{"command": "pytest", "passed": False}]
    assert Signals.from_dict(d) == s
    assert Signals.from_dict(d).test_runs[0] == TestRun("pytest", False)


def test_testrun_not_collected():
    assert TestRun.__test__ is False


def test_large_record_is_fast():
    calls = []
    for i in range(20000):
        k = i % 4
        if k == 0:
            calls.append(call("Read", file_path=f"f{i % 50}.py", agent_id=f"a{i % 7}"))
        elif k == 1:
            calls.append(call("Bash", command=f"pytest tests/t{i % 30}.py && echo 'a; b'", exit_code=i % 2))
        elif k == 2:
            calls.append(call("Bash", command="make", is_error=True, agent_id=f"a{i % 5}"))
        else:
            calls.append(call("Edit", file_path=f"f{i % 500}.py"))
    t = time.perf_counter()
    s = sig(*calls)
    assert time.perf_counter() - t < 1.0
    assert s.test_runs
