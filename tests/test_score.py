from kaizen.record.model import RunRecord, ToolCall
from kaizen.score import (
    Baseline,
    RunStats,
    Score,
    baseline_for,
    compute_score,
    size_bucket,
    stats_of,
)
from kaizen.signals import Signals, TestRun

W = {"quality": 0.4, "efficiency": 0.3, "cost": 0.3}


def sig(tests_passed_last=None, test_runs=None, check_runs=None, **kw):
    if test_runs is None:
        test_runs = [TestRun("pytest", tests_passed_last)] if tests_passed_last is not None else []
    return Signals(
        test_runs=test_runs,
        check_runs=check_runs or [],
        tests_passed_last=tests_passed_last,
        strength="strong",
        **kw,
    )


def stats(repo="r", bucket="1-2", total_tokens=1000, waste_rate=4.0):
    return RunStats(repo=repo, bucket=bucket, total_tokens=total_tokens, waste_rate=waste_rate)


def edit(path, name="Edit"):
    return ToolCall(id="x", name=name, input={"file_path": path})


def rec(tool_calls=(), repo="r"):
    return RunRecord(session_id="s", repo=repo, tool_calls=list(tool_calls))


def test_no_baseline_gives_no_total():
    s = compute_score(sig(tests_passed_last=True), stats(), 8.0, "haiku", None, W)
    assert (s.total, s.efficiency, s.cost, s.baseline) == (None, None, None, "insufficient")
    assert s.quality == 8.0 and s.eligible_as_evidence is False


def test_equal_to_median_scores_five():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(sig(tests_passed_last=True), stats(total_tokens=1000, waste_rate=4.0), 8.0, "haiku", b, W)
    assert (s.cost, s.efficiency, s.total) == (5.0, 5.0, 6.2)


def test_failed_tests_cap_total_at_4():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(sig(tests_passed_last=False), stats(total_tokens=10, waste_rate=0.0), 10.0, "haiku", b, W)
    assert s.total == 4.0 and s.correctness_ok is False


def test_half_median_tokens_scores_seven_and_a_half():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(sig(tests_passed_last=True), stats(total_tokens=500, waste_rate=4.0), 8.0, "haiku", b, W)
    assert s.cost == 7.5


def test_double_median_tokens_clamps_to_zero():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(sig(tests_passed_last=True), stats(total_tokens=2000, waste_rate=4.0), 8.0, "haiku", b, W)
    assert s.cost == 0.0


def test_zero_median_waste_rate_uses_floor():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=0.0)

    def eff(rate):
        s = compute_score(sig(tests_passed_last=True), stats(total_tokens=1000, waste_rate=rate), 8.0, "haiku", b, W)
        return s.efficiency

    assert (eff(0.0), eff(1.0), eff(2.0)) == (10.0, 5.0, 0.0)


def test_no_judge_gives_no_total_but_sub_scores():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(sig(tests_passed_last=True), stats(total_tokens=1000, waste_rate=4.0), None, None, b, W)
    assert s.total is None
    assert (s.strength, s.eligible_as_evidence) == ("weak", False)
    assert (s.efficiency, s.cost) == (5.0, 5.0)


def test_no_tests_and_no_checks_is_no_evidence():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(Signals(), stats(), 9.0, "haiku", b, W)
    assert s.evidence == "none"
    assert (s.strength, s.eligible_as_evidence) == ("weak", False)


def test_checks_only_last_failed_caps_at_6():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    checks = [TestRun("ruff check .", True), TestRun("mypy src", False)]
    s = compute_score(sig(check_runs=checks), stats(total_tokens=1000, waste_rate=4.0), 8.0, "haiku", b, W)
    assert (s.evidence, s.total) == ("checks", 6.0)


def test_checks_only_passed_is_evidence():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    checks = [TestRun("ruff check .", True)]
    s = compute_score(sig(check_runs=checks), stats(total_tokens=1000, waste_rate=4.0), 8.0, "haiku", b, W)
    assert (s.evidence, s.total, s.eligible_as_evidence) == ("checks", 6.2, True)


def test_tests_with_unknown_result_and_no_checks_is_no_evidence():
    b = Baseline("repo", median_tokens=1000, median_waste_rate=4.0)
    s = compute_score(sig(test_runs=[TestRun("pytest", None)]), stats(), 9.0, "haiku", b, W)
    assert s.evidence == "none"
    assert (s.correctness_ok, s.eligible_as_evidence) == (None, False)


def test_size_bucket_thresholds():
    expected = {0: "0", 1: "1-2", 2: "1-2", 3: "3-9", 9: "3-9", 10: "10+"}
    for n, bucket in expected.items():
        assert size_bucket(rec(edit(f"f{i}.py") for i in range(n))) == bucket, n


def test_size_bucket_counts_same_file_once():
    assert size_bucket(rec([edit("x.py"), edit("x.py"), edit("x.py")])) == "1-2"


def test_size_bucket_normalises_backslashes():
    calls = [edit("a\\b.py"), edit("a/b.py"), edit("c.py")]
    assert size_bucket(rec(calls)) == "1-2"


def test_size_bucket_treats_windows_paths_case_insensitively():
    calls = [edit("C:\\Dev\\A.py"), edit("c:/dev/a.py"), edit("c.py")]
    assert size_bucket(rec(calls)) == "1-2"


def test_size_bucket_keeps_posix_case_distinct():
    assert size_bucket(rec([edit("/a/A.py"), edit("/a/a.py")])) == "1-2"
    assert size_bucket(rec([edit("/a/A.py"), edit("/a/a.py"), edit("/b.py")])) == "3-9"


def test_size_bucket_counts_write_multiedit_and_notebook():
    calls = [
        edit("a.py", "Write"),
        edit("b.py", "MultiEdit"),
        ToolCall(id="n", name="NotebookEdit", input={"notebook_path": "c.ipynb"}),
        ToolCall(id="r", name="Read", input={"file_path": "d.py"}),
    ]
    assert size_bucket(rec(calls)) == "3-9"


def test_stats_of_with_zero_tool_calls():
    s = stats_of(rec([]), Signals(total_tokens=42))
    assert (s.repo, s.bucket, s.total_tokens, s.waste_rate) == ("r", "0", 42, 0.0)


def test_stats_of_waste_rate_per_100_calls():
    calls = [ToolCall(id=str(i), name="Read", input={}) for i in range(20)]
    signals = Signals(reread_count=2, retry_count=1, tool_error_count=1, total_tokens=7)
    s = stats_of(rec(calls), signals)
    assert (s.waste_rate, s.total_tokens) == (20.0, 7)


def hist(n, repo="r", bucket="3-9", tokens=100, waste=1.0):
    return [RunStats(repo=repo, bucket=bucket, total_tokens=tokens + i, waste_rate=waste + i) for i in range(n)]


def test_baseline_needs_min_runs():
    assert baseline_for(stats(bucket="1-2"), hist(4, bucket="1-2")) is None


def test_baseline_falls_back_to_repo():
    assert baseline_for(stats(bucket="1-2"), hist(5, bucket="3-9")).kind == "repo"


def test_baseline_prefers_bucket():
    b = baseline_for(stats(bucket="1-2"), hist(5, bucket="1-2"))
    assert b.kind == "bucket"


def test_baseline_ignores_other_repos():
    history = hist(5, repo="other", bucket="1-2") + hist(4, bucket="1-2")
    assert baseline_for(stats(bucket="1-2"), history) is None


def test_baseline_none_when_repo_is_unknown():
    history = hist(10, repo=None, bucket="1-2")
    assert baseline_for(stats(repo=None, bucket="1-2"), history) is None


def test_baseline_medians():
    history = [
        RunStats(repo="r", bucket="1-2", total_tokens=t, waste_rate=w)
        for t, w in [(100, 1.0), (200, 2.0), (300, 3.0), (400, 4.0), (500, 10.0)]
    ]
    b = baseline_for(stats(bucket="1-2"), history)
    assert (b.median_tokens, b.median_waste_rate) == (300, 3.0)


def test_score_round_trip():
    s = Score(total=6.2, correctness_ok=True, quality=8.0, efficiency=5.0, cost=5.0, strength="strong",
              judge_backend="haiku", baseline="repo", evidence="tests", eligible_as_evidence=True)
    assert Score.from_dict(s.to_dict()) == s


def test_score_from_empty_dict_uses_defaults():
    s = Score.from_dict({})
    assert (s.total, s.strength, s.baseline, s.evidence, s.eligible_as_evidence) == (
        None,
        "weak",
        "insufficient",
        "none",
        False,
    )
    assert (s.correctness_ok, s.quality, s.efficiency, s.cost, s.judge_backend) == (None, None, None, None, None)


def test_score_from_dict_ignores_unknown_keys():
    assert Score.from_dict({"total": 3.0, "unknown": 1}).total == 3.0
