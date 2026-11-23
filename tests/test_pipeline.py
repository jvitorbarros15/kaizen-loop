import json

import pytest

from kaizen.config import load_config
from kaizen.judge.rubric import RUBRIC_ITEMS
from kaizen.pipeline import (
    build_run_packet,
    find_transcripts,
    record_session,
    refresh_pr_outcomes,
    score_run,
)
from kaizen.store import Store

PR = "https://github.com/acme/api/pull/7"


def judge_output(score=8):
    items = {name: {"score": score, "reason": f"{name} ok"} for name in RUBRIC_ITEMS}
    return json.dumps({"result": json.dumps({"items": items})})


class FakeRunner:
    def __init__(self, corrections=("run the tests",), judge=True, pr_state="MERGED"):
        self.corrections = corrections
        self.judge = judge
        self.pr_state = pr_state
        self.calls = []

    def __call__(self, argv, stdin=None):
        self.calls.append(argv[0])
        if argv[0] == "gh":
            return 0, json.dumps({"state": self.pr_state})
        if (stdin or "").startswith("<messages>"):
            if self.corrections is None:
                return 1, ""
            return 0, json.dumps({"result": json.dumps(list(self.corrections))})
        if not self.judge:
            return 1, ""
        return 0, judge_output()


def never(argv, stdin=None):
    raise AssertionError(f"runner called: {argv[0]}")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store")


@pytest.fixture
def config(tmp_path):
    return load_config(tmp_path / "cfg")


def record(make_session, store, tmp_path, sid, **kw):
    return record_session(make_session(tmp_path / "projects" / "p", sid, **kw), store)


def test_record_session_twice_leaves_one_run(make_session, store, tmp_path):
    path = make_session(tmp_path / "projects" / "p", "s1")
    assert record_session(path, store) == "s1"
    record_session(path, store)
    assert len(store.list_runs()) == 1


def test_find_transcripts_one_level_newest_first_and_ignores_deeper(make_session, store, tmp_path):
    import os

    old = make_session(tmp_path / "projects" / "a", "old")
    new = make_session(tmp_path / "projects" / "b", "new")
    make_session(tmp_path / "projects" / "b" / "deep", "deeper")
    (tmp_path / "projects" / "top.jsonl").write_text("{}", encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert find_transcripts(tmp_path / "projects") == [new, old]


def test_pending_cycle(make_session, store, tmp_path, config):
    path = make_session(tmp_path / "projects" / "p", "s1")
    record_session(path, store)
    assert store.pending_scores() == ["s1"]
    score_run("s1", store, config, FakeRunner())
    assert store.pending_scores() == []
    make_session(tmp_path / "projects" / "p", "s1", calls=3)
    record_session(path, store)
    assert store.pending_scores() == ["s1"]


def test_score_run_missing_session(store, config):
    assert score_run("nope", store, config, never) is None


def test_score_run_all_backends_failing_saves_unavailable_score(make_session, store, tmp_path, config):
    record(make_session, store, tmp_path, "s1")
    result = score_run("s1", store, config, FakeRunner(judge=False))
    assert result["verdict"]["quality"] is None
    assert result["score"]["total"] is None
    assert store.get_score("s1")["score"]["total"] is None


def test_score_run_with_baseline_produces_composite(make_session, store, tmp_path, config):
    for i in range(5):
        record(make_session, store, tmp_path, f"old{i}")
        score_run(f"old{i}", store, config, FakeRunner())
    record(make_session, store, tmp_path, "new")
    result = score_run("new", store, config, FakeRunner())
    assert result["score"]["baseline"] != "insufficient"
    assert result["score"]["total"] is not None
    assert result["stats"]["repo"] == "api-server"
    assert result["corrections_known"] is True


def test_corrections_failure_is_null_in_packet_and_unknown_in_score(make_session, store, tmp_path, config):
    seen = []

    def runner(argv, stdin=None):
        if (stdin or "").startswith("<packet>"):
            seen.append(stdin)
        return FakeRunner(corrections=None)(argv, stdin)

    record(make_session, store, tmp_path, "s1", prompts=["do it", "no, that is wrong"])
    result = score_run("s1", store, config, runner)
    assert result["corrections_known"] is False
    assert result["signals"]["corrections"] == []
    assert '"corrections": null' in seen[0]


def test_corrections_disabled_makes_no_corrections_call(make_session, store, tmp_path, config):
    config["corrections"]["enabled"] = False
    record(make_session, store, tmp_path, "s1", prompts=["do it", "no, that is wrong"])
    runner = FakeRunner()
    result = score_run("s1", store, config, runner)
    assert result["corrections_known"] is False
    assert runner.calls == ["claude"]


def test_corrections_reach_signals(make_session, store, tmp_path, config):
    record(make_session, store, tmp_path, "s1", prompts=["do it", "no, that is wrong"])
    result = score_run("s1", store, config, FakeRunner(corrections=("run the tests",)))
    assert result["signals"]["corrections"] == ["run the tests"]
    assert result["signals"]["strength"] == "strong"


def test_build_run_packet_calls_no_runner(make_session, store, tmp_path, config):
    record(make_session, store, tmp_path, "s1", prompts=["do it", "again"])
    packet, backends = build_run_packet("s1", store, config)
    assert packet["corrections"] is None
    assert backends == ["haiku"]
    assert packet["task"] == "do it"
    assert build_run_packet("nope", store, config) is None


def test_refresh_updates_open_pr_without_judge(make_session, store, tmp_path, config):
    record(make_session, store, tmp_path, "s1", pr_url=PR)
    score_run("s1", store, config, FakeRunner(pr_state="OPEN"))
    assert store.get_score("s1")["signals"]["pr_outcome"] == "open"
    runner = FakeRunner(pr_state="MERGED")
    assert refresh_pr_outcomes(store, runner) == 1
    assert runner.calls == ["gh"]
    saved = store.get_score("s1")
    assert saved["signals"]["pr_outcome"] == "merged"
    assert saved["verdict"]["quality"] == 8.0
    assert refresh_pr_outcomes(store, runner) == 0
