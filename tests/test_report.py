import re

from kaizen.pipeline import record_session
from kaizen.report import agreement, calibration_summary, render_report
from kaizen.store import Store


def make_score(
    repo,
    day,
    total=None,
    quality=None,
    tests="none",
    checks=0,
    rereads=None,
    retries=0,
    errors=0,
    interruptions=0,
    corrections=(),
    tokens=61000,
    waste=4.0,
    known=True,
):
    rereads = rereads or {}
    passed = {"passed": True, "failed": False}.get(tests)
    return {
        "score": {
            "total": total,
            "quality": quality,
            "evidence": "tests" if tests in ("passed", "failed") else "none",
            "baseline": "repo" if total is not None else "insufficient",
        },
        "signals": {
            "test_runs": [] if tests == "none" else [{"command": "pytest", "passed": passed}],
            "check_runs": [{"command": "ruff check", "passed": True}] * checks,
            "tests_passed_last": passed,
            "reread_count": sum(rereads.values()),
            "reread_files": rereads,
            "retry_count": retries,
            "tool_error_count": errors,
            "interruptions": interruptions,
            "total_tokens": tokens,
            "corrections": list(corrections),
        },
        "verdict": {"quality": quality},
        "stats": {"repo": repo, "bucket": "1-2", "total_tokens": tokens, "waste_rate": waste},
        "corrections_known": known,
        "repo": repo,
        "started_at": f"{day}T10:00:00Z",
    }


def hand_built_store(tmp_path):
    store = Store(tmp_path / "store")
    n = 0

    def add(**kw):
        nonlocal n
        n += 1
        store.save_score(f"s{n}", make_score(**kw))

    for i in range(5):
        add(
            repo="api-server",
            day=f"2026-11-{10 + i}",
            total=7.0 - i,
            quality=7.0,
            tests="passed",
            checks=1,
            rereads={"src/app.py": 2},
            retries=1,
            errors=1,
            corrections=["Run the tests before saying done "] if i == 0 else [],
        )
    add(repo="api-server", day="2026-11-15", total=4.0, quality=5.0, tests="failed", rereads={"README.md": 4})
    add(repo="api-server", day="2026-11-16", corrections=["run the tests before saying done"])
    add(repo="api-server", day="2026-11-17", quality=6.0, tests="unknown", interruptions=1, corrections=["x"])
    add(repo="web-client", day="2026-11-18", quality=4.0, tests="failed", corrections=["a", "b", "c", "d"])
    add(repo="web-client", day="2026-11-19")
    add(repo=None, day="2026-11-20")
    return store


def test_agreement():
    assert agreement([(7, 8), (3, 9), (5, 5)]) == (2, 3)
    assert agreement([]) == (0, 0)


def test_calibration_summary_constant_judge_line():
    text = calibration_summary([(7, 8), (3, 9), (5, 5), (6, 8)], abstained=1)
    assert "Judge agrees with you on 3 of 4 runs" in text
    assert "A constant judge answering 8 would agree on 3 of 4" in text
    assert "Abstentions: 1" in text
    assert "clearly above" in text


def test_calibration_summary_without_pairs():
    assert "nothing to compare yet" in calibration_summary([], 0)


def test_empty_store(tmp_path):
    text = render_report(Store(tmp_path / "store"))
    assert "kaizen import" in text and "kaizen score --pending" in text
    assert len(text.splitlines()) == 1


def test_report_on_hand_built_store(tmp_path):
    text = render_report(hand_built_store(tmp_path))
    print(text)
    assert text.startswith("kaizen report - last 11 scored runs\n")
    assert re.search(r"api-server\s+8 runs\s+tests: 5 passed, 1 failed, 1 unknown, 1 none\s+checks: 5 runs", text)
    assert "waste 4.0 per 100 calls (re-reads 14, retries 5, tool errors 5)" in text
    assert "tokens 61,000 per run   corrections 3   interruptions 1" in text
    assert "judge quality 6.6 avg (7 graded, 1 unavailable)   composite 4.8 avg (6 runs with a baseline)" in text
    assert re.search(r"web-client\s+2 runs", text)
    assert re.search(r"\(no project\)\s+1 run\b", text)
    web = text.split("web-client")[1].split("\n\n")[0]
    assert "composite: not enough runs for a baseline yet (needs 5)" in web
    assert "7 of 11 runs had a test or check result. 4 had none" in text
    assert "src/app.py x10, README.md x4" in text
    lowest = text.split("Lowest runs\n")[1].split("\n\n")[0].splitlines()
    assert len(lowest) == 5
    assert re.match(r"3\.0  2026-11-14  api-server\s+waste 4\.0 per 100 calls", lowest[0].strip())
    assert any("tests failed at end" in line for line in lowest)
    assert '"run the tests before saying done"  x2' in text


def test_composite_never_printed_without_baseline(tmp_path):
    store = Store(tmp_path / "store")
    store.save_score("a", make_score("solo", "2026-11-10", tests="passed", quality=7.0))
    text = render_report(store)
    assert "composite: not enough runs for a baseline yet (needs 5)" in text
    assert "avg (" not in text.split("composite")[1]
    assert "Lowest runs\n  No run has a composite score yet" in text


def test_last_limits_runs_and_counts_pending(tmp_path, make_session):
    store = hand_built_store(tmp_path)
    record_session(make_session(tmp_path / "t", "pend"), store)
    text = render_report(store, last=3)
    assert "last 3 scored runs (1 more recorded, not scored yet)" in text
    by_project = text.split("By project")[1].split("Evidence")[0]
    assert "web-client" in by_project and "api-server" not in by_project


def test_no_repeated_corrections(tmp_path):
    store = Store(tmp_path / "store")
    store.save_score("a", make_score("p", "2026-11-10", tests="passed", corrections=["only once"]))
    assert "No correction was repeated" in render_report(store)
