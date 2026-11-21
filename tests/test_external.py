import json
import sys

import pytest

from kaizen.external import (
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
    assert extract_corrections(["a", "b"], lambda argv, stdin: (1, "")) == []
    assert extract_corrections(["a", "b"], lambda argv, stdin: (1, envelope('["x"]'))) == []


def test_garbage_output():
    assert extract_corrections(["a", "b"], lambda argv, stdin: (0, "not json at all")) == []
    assert extract_corrections(["a", "b"], answering("I could not find any.")) == []


def test_is_error_envelope():
    def fake(argv, stdin):
        return 0, envelope('["x"]', is_error=True)

    assert extract_corrections(["a", "b"], fake) == []


def test_fenced_json():
    assert extract_corrections(["a", "b"], answering('```json\n["x"]\n```')) == ["x"]
    assert extract_corrections(["a", "b"], answering('```\n["y"]\n```')) == ["y"]


def test_prose_around_json():
    assert extract_corrections(["a", "b"], answering('Here you go: ["x", "y"] hope it helps')) == ["x", "y"]


def test_non_list_answer():
    assert extract_corrections(["a", "b"], answering('{"a": 1}')) == []
    assert extract_corrections(["a", "b"], answering('"just a string"')) == []


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
        return 0, envelope("[]")

    extract_corrections(["first request", f"use token {SECRET} please", "x" * 3000], fake)
    assert SECRET not in seen["stdin"]
    assert "[1] first request" in seen["stdin"]
    assert "[2] use token" in seen["stdin"]
    assert "[3] " + "x" * 2000 in seen["stdin"]
    assert "x" * 2001 not in seen["stdin"]
    argv = seen["argv"]
    assert argv[:6] == ["claude", "-p", "--model", "haiku", "--output-format", "json"]
    assert len(argv) == 7
    assert argv[6] == PROMPT


def test_stdin_limited_to_60_messages():
    seen = {}

    def fake(argv, stdin):
        seen["stdin"] = stdin
        return 0, envelope("[]")

    extract_corrections([f"m{i}" for i in range(80)], fake)
    assert "[60] m59" in seen["stdin"]
    assert "[61]" not in seen["stdin"]


def test_parse_model_json_rejects():
    assert parse_model_json("nope") is None
    assert parse_model_json("[1]") is None
    assert parse_model_json(json.dumps({"result": 5})) is None
    assert parse_model_json(json.dumps({"is_error": True, "result": "[1]"})) is None
    assert parse_model_json(json.dumps({"is_error": False})) is None
    assert parse_model_json(envelope("no json here")) is None


def test_parse_model_json_object():
    assert parse_model_json(envelope('Sure: {"a": 1} done')) == {"a": 1}


@pytest.mark.parametrize(
    "state,expected", [("MERGED", "merged"), ("CLOSED", "closed"), ("OPEN", "open")]
)
def test_pr_outcome(state, expected):
    calls = []

    def fake(argv, stdin):
        calls.append(argv)
        return 0, json.dumps({"state": state, "mergedAt": None})

    url = "https://github.com/acme/widgets/pull/12"
    assert fetch_pr_outcome(url, fake) == expected
    assert calls == [["gh", "pr", "view", url, "--json", "state,mergedAt"]]


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
