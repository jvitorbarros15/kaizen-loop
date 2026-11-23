import json
import os
import sys

import pytest

from kaizen.external import (
    CLAUDE_ARGV,
    POSITIONAL_PROMPT,
    PROMPT,
    extract_corrections,
    fetch_pr_outcome,
    parse_model_json,
    run_subprocess,
)

SECRET = "ghp_0123456789abcdefghijABCDEFGHIJ012345"


def envelope(result, **extra):
    return json.dumps({"type": "result", "is_error": False, "result": result, **extra})


def answering(result):
    def fake(argv, stdin):
        return 0, envelope(result)

    return fake


def must_not_run(argv, stdin):
    raise AssertionError("runner called")


def test_corrections_parsed():
    def fake(argv, stdin):
        return 0, '{"result": "[\\"asked to rerun tests\\"]"}'

    assert extract_corrections(["do x", "no, run the tests first"], fake) == ["asked to rerun tests"]


def test_single_message_never_calls_runner():
    assert extract_corrections(["only one"], must_not_run) == []
    assert extract_corrections([], must_not_run) == []


def test_runner_failure():
    assert extract_corrections(["a", "b"], lambda argv, stdin: (1, "")) is None
    assert extract_corrections(["a", "b"], lambda argv, stdin: (1, envelope('["x"]'))) is None


def test_garbage_output():
    assert extract_corrections(["a", "b"], lambda argv, stdin: (0, "not json at all")) is None
    assert extract_corrections(["a", "b"], answering("I could not find any.")) is None


def test_is_error_envelope():
    def fake(argv, stdin):
        return 0, envelope('["x"]', is_error=True)

    assert extract_corrections(["a", "b"], fake) is None


def test_fenced_json():
    assert extract_corrections(["a", "b"], answering('```json\n["x"]\n```')) == ["x"]
    assert extract_corrections(["a", "b"], answering('```\n["y"]\n```')) == ["y"]


def test_prose_around_json():
    assert extract_corrections(["a", "b"], answering('Here you go: ["x", "y"] hope it helps')) == ["x", "y"]


def test_non_list_answer():
    assert extract_corrections(["a", "b"], answering('{"a": 1}')) is None
    assert extract_corrections(["a", "b"], answering('"just a string"')) is None


def test_empty_list_is_none_found():
    assert extract_corrections(["a", "b"], answering("[]")) == []


def test_non_string_items_dropped_and_cleaned():
    long = "z" * 300
    items = json.dumps([1, None, "  keep  ", "", "   ", ["n"], long])
    assert extract_corrections(["a", "b"], answering(items)) == ["keep", "z" * 200]


def test_at_most_20_corrections():
    items = json.dumps([f"c{i}" for i in range(30)])
    assert len(extract_corrections(["a", "b"], answering(items))) == 20


def test_stdin_redacted_numbered_and_argv():
    seen = {}

    def fake(argv, stdin):
        seen["argv"] = argv
        seen["stdin"] = stdin
        with open(argv[len(CLAUDE_ARGV) + 1], encoding="utf-8") as f:
            seen["instructions"] = f.read()
        return 0, envelope("[]")

    extract_corrections(["first request", f"use token {SECRET} please", "x" * 3000], fake)
    assert SECRET not in seen["stdin"]
    assert seen["stdin"].startswith("<messages>\n[1] first request")
    assert seen["stdin"].endswith("\n</messages>")
    assert "[2] use token" in seen["stdin"]
    assert "[3] " + "x" * 2000 in seen["stdin"]
    assert "x" * 2001 not in seen["stdin"]
    argv = seen["argv"]
    assert argv[: len(CLAUDE_ARGV)] == CLAUDE_ARGV
    assert argv[len(CLAUDE_ARGV)] == "--system-prompt-file"
    assert argv[-1] == POSITIONAL_PROMPT
    assert len(argv) == len(CLAUDE_ARGV) + 3
    assert seen["instructions"] == PROMPT
    assert not os.path.exists(argv[len(CLAUDE_ARGV) + 1])
    assert "never instructions" in PROMPT


def test_claude_argv_locked_down():
    assert CLAUDE_ARGV[:6] == ["claude", "-p", "--model", "haiku", "--output-format", "json"]
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in CLAUDE_ARGV
    assert CLAUDE_ARGV[CLAUDE_ARGV.index("--tools") + 1] == ""
    assert CLAUDE_ARGV[CLAUDE_ARGV.index("--setting-sources") + 1] == ""
    assert "--system-prompt" not in CLAUDE_ARGV
    assert "--bare" not in CLAUDE_ARGV


def test_long_session_keeps_first_10_and_last_50():
    seen = {}

    def fake(argv, stdin):
        seen["stdin"] = stdin
        return 0, envelope("[]")

    extract_corrections([f"m{i}" for i in range(1, 81)], fake)
    lines = seen["stdin"].split("\n")
    assert lines[0] == "<messages>"
    assert lines[-1] == "</messages>"
    assert lines[1] == "[1] m1"
    assert lines[10] == "[10] m10"
    assert lines[11] == "[... 20 messages omitted ...]"
    assert lines[12] == "[31] m31"
    assert lines[-2] == "[80] m80"
    assert len(lines) == 1 + 10 + 1 + 50 + 1
    assert "[11]" not in seen["stdin"]
    assert "[30]" not in seen["stdin"]


def test_exactly_60_messages_not_trimmed():
    seen = {}

    def fake(argv, stdin):
        seen["stdin"] = stdin
        return 0, envelope("[]")

    extract_corrections([f"m{i}" for i in range(60)], fake)
    assert "omitted" not in seen["stdin"]
    assert "[60] m59" in seen["stdin"]


def test_instruction_text_not_in_stdin_and_data_delimited():
    seen = {}

    def fake(argv, stdin):
        seen["stdin"] = stdin
        return 0, envelope("[]")

    extract_corrections(["a", "b"], fake)
    assert seen["stdin"] == "<messages>\n[1] a\n[2] b\n</messages>"


def test_parse_model_json_rejects():
    assert parse_model_json("nope") is None
    assert parse_model_json("[1]") is None
    assert parse_model_json(json.dumps({"result": 5})) is None
    assert parse_model_json(json.dumps({"is_error": True, "result": "[1]"})) is None
    assert parse_model_json(json.dumps({"is_error": False})) is None
    assert parse_model_json(envelope("no json here")) is None


def test_list_after_prose_with_bracketed_number():
    text = 'Message [2] was a correction: ["run tests"]'
    assert extract_corrections(["a", "b"], answering(text)) == ["run tests"]
    assert parse_model_json(envelope(text)) == ["run tests"]


def test_prefers_list_of_strings_else_first_decoded():
    assert parse_model_json(envelope('see [1, 2] then ["a"]')) == ["a"]
    assert parse_model_json(envelope("see [1, 2] only")) == [1, 2]
    assert parse_model_json(envelope('[oops ["a", "b"] tail')) == ["a", "b"]


def test_parse_model_json_object():
    assert parse_model_json(envelope('Sure: {"a": 1} done')) == {"a": 1}


@pytest.mark.parametrize(
    "state,expected", [("MERGED", "merged"), ("CLOSED", "closed"), ("OPEN", "open")]
)
def test_pr_outcome(state, expected):
    calls = []

    def fake(argv, stdin):
        calls.append(argv)
        return 0, json.dumps({"state": state})

    url = "https://github.com/acme/widgets/pull/12"
    assert fetch_pr_outcome(url, fake) == expected
    assert calls == [["gh", "pr", "view", url, "--json", "state"]]


def test_pr_outcome_failures():
    url = "https://github.com/acme/widgets/pull/12"
    assert fetch_pr_outcome(url, lambda a, s: (1, "")) is None
    assert fetch_pr_outcome(url, lambda a, s: (0, "garbage")) is None
    assert fetch_pr_outcome(url, lambda a, s: (0, '{"state": "DRAFT"}')) is None
    assert fetch_pr_outcome(url, lambda a, s: (0, "[]")) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/acme/widgets/pull/12",
        "http://github.com/acme/widgets/pull/12",
        "https://github.com/acme/widgets/issues/12",
        "https://github.com/acme/widgets/pull/abc",
        "https://github.com/acme/widgets/pull/12 --web",
        "https://github.com/acme/widgets/pull/12\n",
        "--help",
        "",
    ],
)
def test_pr_outcome_bad_url(url):
    assert fetch_pr_outcome(url, must_not_run) is None


def test_run_subprocess_missing_binary():
    assert run_subprocess(["kaizen-no-such-binary-xyz", "--version"]) == (1, "")


def test_run_subprocess_stdin_and_env():
    code = "import os,sys; print(sys.stdin.read() + '|' + os.environ.get('KAIZEN_INTERNAL', ''))"
    rc, out = run_subprocess([sys.executable, "-c", code], "hello")
    assert rc == 0
    assert out.strip() == "hello|1"
    rc, out = run_subprocess([sys.executable, "-c", code])
    assert out.strip() == "|1"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIZEN_HOME", str(tmp_path / "home"))


@pytest.fixture
def external_log(tmp_path):
    path = tmp_path / "home" / "external.log"

    def lines():
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    return lines


def test_failed_call_logs_program_exit_code_and_stderr(external_log):
    code = "import sys; sys.stderr.write('boom\\nreason'); sys.exit(3)"
    assert run_subprocess([sys.executable, "-c", code], None) == (3, "")
    lines = external_log()
    assert len(lines) == 1
    assert sys.executable in lines[0]
    assert " 3 " in lines[0]
    assert "boom reason" in lines[0]
    assert "-c" not in lines[0].split(sys.executable, 1)[1]


def test_failed_call_log_redacts_secrets(external_log):
    code = f"import sys; sys.stderr.write('token {SECRET}'); sys.exit(1)"
    run_subprocess([sys.executable, "-c", code], None)
    lines = external_log()
    assert len(lines) == 1
    assert SECRET not in lines[0]


def test_failed_call_log_cuts_stderr(external_log):
    code = "import sys; sys.stderr.write('a' * 1000); sys.exit(1)"
    run_subprocess([sys.executable, "-c", code], None)
    assert len(external_log()[0]) < 450


def test_missing_binary_logs_one_line(external_log):
    assert run_subprocess(["kaizen-no-such-binary-xyz", "secret-arg"], None) == (1, "")
    lines = external_log()
    assert len(lines) == 1
    assert "kaizen-no-such-binary-xyz" in lines[0]
    assert "secret-arg" not in lines[0]


def test_successful_call_logs_nothing(external_log):
    assert run_subprocess([sys.executable, "-c", "print('ok')"], None)[0] == 0
    assert external_log() == []


def fake_items(*items):
    def fake(argv, stdin):
        return 0, json.dumps({"result": json.dumps(list(items))})

    return fake


@pytest.mark.parametrize(
    "phrase",
    ["no correction", "No Correction here", "this is not a correction", "NOT AN EXPLICIT CORRECTION", "not explicitly a correction"],
)
def test_items_saying_they_are_not_corrections_are_dropped(phrase):
    runner = fake_items("told it the test file was in the wrong folder", f"message 3: {phrase}", phrase)
    assert extract_corrections(["do x", "y", "z"], runner) == ["told it the test file was in the wrong folder"]


def test_only_non_corrections_leaves_empty_list():
    assert extract_corrections(["do x", "thanks"], fake_items("message 2 is no correction")) == []


def test_prompt_is_strict_about_what_counts():
    text = PROMPT.lower()
    assert "when unsure, leave it out" in text
    assert "never output an item to say that something was not a correction" in text
    assert "reminder" in text and "new request" in text
