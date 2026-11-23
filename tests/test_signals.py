import time
from pathlib import Path

import pytest

from kaizen.record.model import RunRecord, ToolCall, Usage
from kaizen.record.parse import parse_transcript
from kaizen.signals import (
    Signals,
    TestRun,
    extract_signals,
    split_segments,
    strength_of,
)

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


def run_of(cmd, output="", **kw):
    c = call("Bash", command=cmd, **kw)
    c.output_excerpt = output
    return sig(c)


def test_split_segments_reports_separators():
    assert split_segments("a && b | c; d || e\nf") == [
        ("a ", "&&"),
        (" b ", "|"),
        (" c", ";"),
        (" d ", "||"),
        (" e", "\n"),
        ("f", ""),
    ]
    assert split_segments("echo 'a | b'") == [("echo 'a | b'", "")]


def test_piped_test_failure_read_from_output():
    s = run_of("pytest -q 2>&1 | tail -5", "FAILED tests/a.py::t\n1 failed, 3 passed in 0.2s", exit_code=0)
    assert [t.passed for t in s.test_runs] == [False]
    assert s.tests_passed_last is False


def test_piped_test_pass_read_from_output():
    assert run_of("pytest -q 2>&1 | tail -5", "4 passed in 0.2s", exit_code=0).tests_passed_last is True


def test_piped_test_unknown_gives_none():
    s = run_of("pytest -q | tail -5", "some output", exit_code=0)
    assert len(s.test_runs) == 1
    assert s.tests_passed_last is None


def test_piped_nonzero_exit_does_not_force_failure():
    assert run_of("pytest | tail", "3 passed", exit_code=1, is_error=True).tests_passed_last is True


def test_test_as_last_segment_after_pipe_trusts_exit_code():
    assert run_of("ls | pytest", "", exit_code=1, is_error=True).tests_passed_last is False


def test_trailing_newline_keeps_trust():
    assert run_of("pytest\n", exit_code=1, is_error=True).tests_passed_last is False


def test_and_chain_zero_exit_is_pass():
    assert run_of("pytest && echo done", "1 failed", exit_code=0).tests_passed_last is True


def test_and_chain_nonzero_falls_to_output():
    assert run_of("pytest && echo done", "1 failed", exit_code=1, is_error=True).tests_passed_last is False
    assert run_of("pytest && echo done", "5 passed", exit_code=1, is_error=True).tests_passed_last is True
    assert run_of("pytest && echo done", "", exit_code=1, is_error=True).tests_passed_last is None


def test_and_chain_with_or_tail_is_not_trusted():
    assert run_of("pytest && echo ok || true", "1 failed", exit_code=0).tests_passed_last is False


@pytest.mark.parametrize(
    "cmd", ["pytest; echo $?", "pytest || echo bad", "pytest\necho x", "(pytest > o.log 2>&1; echo $?)"]
)
def test_other_separators_read_output(cmd):
    assert run_of(cmd, "2 failed", exit_code=0).tests_passed_last is False
    assert run_of(cmd, "2 passed", exit_code=1, is_error=True).tests_passed_last is True
    assert run_of(cmd, "", exit_code=0).tests_passed_last is None


@pytest.mark.parametrize(
    "out",
    [
        "1 failed, 2 passed",
        "== 3 errors in 1s ==",
        "1 error in 0.1s",
        "FAILED (failures=1)",
        "Tests:       1 failed, 4 passed, 5 total",
        "      Tests  2 failed | 4 passed (6)",
        " Test Files  1 failed | 2 passed (3)",
        "FAIL src/a.test.js",
        " FAIL  src/a.test.ts > adds",
        "# tests 3\n# pass 2\n# fail 1",
        "ℹ tests 3\nℹ pass 2\nℹ fail 1",
        "✖ failing tests:\n\n✖ adds (1.2ms)",
        "--- FAIL: TestX (0.00s)",
        "FAIL\tgithub.com/x/y\t0.01s",
        "test result: FAILED. 1 passed; 1 failed",
        "Failed!  - Failed:     1, Passed:     2",
        "2 passed\n1 failed",
    ],
)
def test_failure_markers(out):
    assert run_of("pytest | tail", out).tests_passed_last is False


@pytest.mark.parametrize(
    "out",
    [
        "3 passed in 0.1s",
        "0 failed, 3 passed",
        "0 errors\n3 passed",
        "Ran 3 tests in 0.1s\n\nOK",
        "OK (skipped=1)",
        "Tests:       5 passed, 5 total",
        "# tests 3\n# pass 3\n# fail 0",
        "ℹ tests 3\nℹ pass 3\nℹ fail 0",
        "ℹ pass 3\nℹ fail 0\nℹ cancelled 0",
        "ok  \tgithub.com/x/y\t0.01s",
        "test result: ok. 3 passed; 0 failed",
        "Passed!  - Failed:     0, Passed:     2",
    ],
)
def test_pass_markers(out):
    assert run_of("pytest | tail", out).tests_passed_last is True


@pytest.mark.parametrize(
    "out",
    [
        "Tests:       0 failed, 5 passed, 5 total",
        "handled 2 errors as expected\n15 passed in 0.4s",
        "retried 1 failed request\n=== 250 passed in 2.1s ===",
        "FAIL\nprinted by a test of error formatting\n3 passed in 0.1s",
        "1 failed\n" + "x" * 990 + "\n[... 5000 characters omitted ...]\n" + "y" * 900 + "\n=== 9 passed in 2.1s ===",
    ],
)
def test_log_noise_does_not_turn_a_passing_run_into_a_failure(out):
    assert run_of("pytest | tail", out).tests_passed_last is True


@pytest.mark.parametrize(
    "out",
    [
        "ℹ tests 0\nℹ pass 0\nℹ fail 0",
        "ℹ fail 0",
    ],
)
def test_node_runner_with_nothing_passed_is_unknown(out):
    assert run_of("npm test | tail", out).tests_passed_last is None


def test_node_runner_cancelled_test_is_a_failure():
    assert run_of("npm test | tail", "ℹ pass 3\nℹ fail 0\nℹ cancelled 1").tests_passed_last is False


@pytest.mark.parametrize("out", ["", "collecting...", "0 passed", "0 failed"])
def test_no_markers_unknown(out):
    assert run_of("pytest | tail", out).tests_passed_last is None


@pytest.mark.parametrize(
    "cmd",
    [
        "(npm test 2>&1 | tail -20)",
        "(npm test > out.log 2>&1; echo $?)",
        "{ npm test; }",
        "for i in 1 2 3; do npm test 2>&1 | tail -3; done",
        "! npm test",
        "time npm test",
        "timeout 300 npm test",
        "timeout -k 5 300 pytest",
        "timeout 5m pytest",
        "uv run --no-project --python 3.11 --with pytest python -m pytest tests/",
        "uv run --with pytest pytest",
        "poetry run --directory x pytest",
        "npx -y vitest run",
        "pnpm exec --package foo vitest",
        "npm run -s test",
        "npm --silent test",
        "pnpm --silent run test:unit",
        "yarn --silent test",
        "bun test",
        "python -m unittest",
        "python -m unittest discover -s tests",
        "make test",
    ],
)
def test_more_test_shapes(cmd):
    s = run_of(cmd)
    assert len(s.test_runs) == 1
    assert s.check_runs == []


@pytest.mark.parametrize(
    "cmd",
    [
        "grep -v test",
        "ls test",
        "python -c 'import pytest'",
        "python - <<EOF\nimport pytest\nEOF",
        'echo "run pytest"',
        "test -x file",
        'gh pr create --title "add test"',
        "make build",
        "timeout 300 ls",
        "timeout pytest",
        "npm --silent install",
    ],
)
def test_still_not_test_shapes(cmd):
    assert run_of(cmd).test_runs == []


@pytest.mark.parametrize(
    "cmd",
    [
        "tsc",
        "npx tsc --noEmit",
        "mypy src",
        "uv run mypy .",
        "pyright",
        "ruff check .",
        "uv run ruff check --fix",
        "eslint .",
        "npx eslint src",
        "cargo check",
        "cargo clippy -- -D warnings",
        "cargo build --release",
        "go build ./...",
        "go vet ./...",
        "npm run typecheck",
        "npm run type-check",
        "pnpm run lint",
        "yarn run build:prod",
        "yarn lint",
        "npm run -s check",
        "cd web && npm run lint:fix",
    ],
)
def test_check_commands(cmd):
    s = run_of(cmd, exit_code=0)
    assert s.test_runs == []
    assert [c.passed for c in s.check_runs] == [True]


@pytest.mark.parametrize(
    "cmd", ["ruff format .", "cargo fmt", "npm run dev", "npm install", "echo tsc", "ls build", "yarn add eslint"]
)
def test_not_check_commands(cmd):
    assert run_of(cmd, exit_code=0).check_runs == []


def test_check_exit_code_and_trust():
    assert run_of("mypy .", exit_code=1, is_error=True).check_runs[0].passed is False
    assert run_of("mypy .", is_error=True).check_runs[0].passed is False
    assert run_of("mypy .").check_runs[0].passed is True
    assert run_of("mypy . | tail", "error: x", exit_code=0).check_runs[0].passed is None
    assert run_of("mypy . && echo x", exit_code=0).check_runs[0].passed is True
    assert run_of("mypy . && echo x", exit_code=1, is_error=True).check_runs[0].passed is None
    assert run_of("tsc; echo $?", exit_code=0).check_runs[0].passed is None


def test_test_and_check_counts_once_as_test():
    s = run_of("mypy . && pytest", exit_code=0)
    assert len(s.test_runs) == 1
    assert s.check_runs == []
    s = run_of("npm run lint && npm test", exit_code=0)
    assert len(s.test_runs) == 1 and s.check_runs == []


def test_tests_passed_last_ignores_checks():
    s = sig(call("Bash", command="pytest", exit_code=0), call("Bash", command="mypy .", exit_code=1, is_error=True))
    assert s.tests_passed_last is True
    assert [c.passed for c in s.check_runs] == [False]


def test_check_runs_make_strong():
    s = sig(call("Bash", command="ruff check ."))
    assert s.test_runs == []
    assert s.strength == "strong"
    s2 = Signals()
    s2.check_runs = [TestRun("tsc", True)]
    assert strength_of(s2) == "strong"


def test_success_clears_earlier_failure_for_retry():
    s = sig(
        call("Bash", is_error=True, command="make"),
        call("Bash", command="make"),
        call("Bash", command="make"),
    )
    assert s.retry_count == 1


def test_from_dict_old_and_unknown_fields():
    s = Signals.from_dict({"test_runs": [{"command": "pytest", "passed": True}], "reread_count": 2})
    assert s.test_runs == [TestRun("pytest", True)]
    assert s.check_runs == []
    assert s.reread_count == 2
    assert s.strength == "weak"
    s = Signals.from_dict({"future": 1, "check_runs": [{"command": "tsc", "passed": None, "extra": 1}]})
    assert s.check_runs == [TestRun("tsc", None)]
    assert Signals.from_dict({}) == Signals()
    assert TestRun.from_dict({}) == TestRun("", None)


def test_round_trip_with_checks_and_none():
    s = sig(
        call("Bash", command="pytest | tail", exit_code=0),
        call("Bash", command="tsc", exit_code=0),
    )
    assert s.tests_passed_last is None
    assert Signals.from_dict(s.to_dict()) == s
    assert Signals.from_dict(s.to_dict()).check_runs == [TestRun("tsc", True)]


@pytest.mark.parametrize("tool,key", [("Write", "file_path"), ("NotebookEdit", "notebook_path")])
def test_write_and_notebook_edit_reset_reread(tool, key):
    s = sig(call("Read", file_path="a.py"), call(tool, **{key: "a.py"}), call("Read", file_path="a.py"))
    assert s.reread_count == 0
