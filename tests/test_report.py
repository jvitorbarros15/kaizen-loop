import contextlib
import re
import sqlite3
from datetime import UTC, datetime, timedelta

from kaizen import cli
from kaizen.pipeline import record_session
from kaizen.record.model import RunRecord, ToolCall
from kaizen.report import agreement, calibration_summary, render_report
from kaizen.store import Store

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


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
    text = render_report(hand_built_store(tmp_path), now=NOW)
    print(text)
    assert "Graded sessions (last 11)\n" in text
    assert re.search(r"api-server\s+8 runs\s+tests: 5 passed, 1 failed, 1 unknown, 1 none\s+checks: 5 runs", text)
    assert "waste 4.0 per 100 calls (re-reads 14, retries 5, tool errors 5)" in text
    assert "tokens 61,000 per run   corrections 3   interruptions 1" in text
    assert "judge quality 6.6 avg (7 graded, 0 abstained, 1 unavailable)   composite 4.8 avg (6 runs with a baseline)" in text
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


def test_composite_never_printed_without_baseline(tmp_path):
    store = Store(tmp_path / "store")
    store.save_score("a", make_score("solo", "2026-11-10", tests="passed", quality=7.0))
    text = render_report(store, now=NOW)
    assert "composite: not enough runs for a baseline yet (needs 5)" in text
    assert "avg (" not in text.split("composite")[1]
    assert "Lowest runs\n  No run has a composite score yet" in text


def test_last_limits_runs_and_counts_pending(tmp_path, make_session):
    store = hand_built_store(tmp_path)
    record_session(make_session(tmp_path / "t", "pend"), store)
    text = render_report(store, last=3, now=NOW)
    assert "Graded sessions (last 3)\n  1 more session recorded, not scored yet." in text
    by_project = text.split("By project")[1].split("Evidence")[0]
    assert "web-client" in by_project and "api-server" not in by_project


def test_project_block_shows_pull_request_outcomes():
    from kaizen.report import _project_block

    def run(outcome):
        return {"signals": {"pr_outcome": outcome}, "stats": {"waste_rate": 0.0}, "score": {}, "verdict": {}}

    text = "\n".join(_project_block("api", [run("merged"), run("merged"), run("open"), run(None)], 6))
    assert "pull requests: 2 merged, 1 open" in text
    assert "pull requests" not in "\n".join(_project_block("api", [run(None)], 6))


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def when(day, hour=7, minute=0, month=11):
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def local(moment):
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def spec(title, edits=0, test=None, check=False, reads=0):
    return {"title": title, "edits": edits, "test": test, "check": check, "reads": reads}


def add_session(store, sid, repo, begin, specs, timed=True):
    prompts, times, calls = [], [], []
    for n, t in enumerate(specs):
        start = begin + timedelta(hours=2 * n)
        prompts.append(t["title"])
        times.append(start.isoformat())
        at = start + timedelta(minutes=1)

        def call(name, input, n=n, at=at, **kw):
            calls.append(ToolCall(id=f"{sid}-{n}-{len(calls)}", name=name, input=input, timestamp=at.isoformat(), **kw))

        for k in range(t["reads"]):
            call("Read", {"file_path": f"/w/{sid}/{n}/r{k}.py"}, exit_code=0)
        for k in range(t["edits"]):
            call("Edit", {"file_path": f"/w/{sid}/{n}/f{k}.py", "old_string": "a", "new_string": "b"}, exit_code=0)
        if t["check"]:
            call("Bash", {"command": "ruff check ."}, exit_code=0)
        if t["test"] in ("passed", "failed"):
            call("Bash", {"command": "pytest -q"}, exit_code=0 if t["test"] == "passed" else 1)
        elif t["test"] == "unknown":
            call("Bash", {"command": "pytest -q | tail -3"}, exit_code=0)
    store.save_run(
        RunRecord(
            session_id=sid,
            repo=repo,
            started_at=times[0],
            ended_at=times[-1],
            user_messages=prompts,
            user_message_times=times if timed else [],
            tool_calls=calls,
        )
    )


def task_store(tmp_path):
    store = Store(tmp_path / "store")
    add_session(
        store,
        "a1",
        "api-server",
        when(20),
        [spec(f"unchecked change {i} in the upload client", edits=1 + i % 3, reads=i) for i in range(9)],
    )
    add_session(
        store,
        "a2",
        "api-server",
        when(21),
        [
            spec("tested change that passed in the api", edits=2, test="passed"),
            spec("tested change that failed in the api", edits=3, test="failed", reads=2),
            spec("tested change with unclear result", edits=1, test="unknown"),
            spec("read the settings module and explain it", reads=3),
            spec("read the router module and explain it", reads=1),
            spec("read the models module and explain it"),
        ],
    )
    add_session(
        store,
        "w1",
        "web-client",
        when(22),
        [
            spec("fix the navbar spacing on mobile devices", edits=2, reads=1),
            spec("tidy the footer markup and lint it", edits=1, check=True),
            spec("look into why the build is slow today", reads=2),
            spec("run the checkout tests and tell me more", test="failed"),
        ],
    )
    add_session(store, "n1", None, when(22, 16), [spec("explain how the cache layer is wired up")])
    add_session(
        store,
        "old",
        "api-server",
        when(1, month=10),
        [spec("an old change outside the window now", edits=1), spec("another old change outside the window", edits=1)],
    )
    return store


def test_task_sections_on_hand_built_store(tmp_path):
    text = render_report(task_store(tmp_path), now=NOW)
    print(text)
    assert text.splitlines()[0] == "kaizen report - tasks from the last 14 days (20 tasks in 4 sessions)"
    assert re.search(
        r"\n  api-server\s+15 tasks\s+edited 12:\s+3 ran a test or check,\s+9 ran none\s+no edits 3\n", text
    )
    assert re.search(r"\n\s+last test in tasks that ran one:\s+1 passed, 1 failed, 1 unknown\n", text)
    assert re.search(r"\n  web-client\s+4 tasks\s+edited 2:\s+1 ran a test or check,\s+1 ran none\s+no edits 2\n", text)
    assert re.search(r"\n  \(no project\)\s+1 task\b", text)
    names = re.findall(r"\n  (api-server|web-client|\(no project\)) ", text.split("Tasks by project")[1].split("\n\n")[0])
    assert names == ["api-server", "web-client", "(no project)"]
    assert "an old change" not in text


def test_ran_none_list_is_recent_first_and_capped(tmp_path):
    text = render_report(task_store(tmp_path), now=NOW)
    section = text.split("Edited files and ran no test or check")[1].split("\n\n")[0]
    assert section.startswith(" (10 of 14 editing tasks, most recent first)")
    rows = [line for line in section.splitlines() if re.match(r"  \d{4}-", line)]
    assert len(rows) == 8
    order = [re.search(r"(navbar|unchecked change \d)", r).group(1) for r in rows]
    assert order == ["navbar"] + [f"unchecked change {i}" for i in range(8, 1, -1)]
    assert rows[0].startswith(f"  {local(when(22))}  web-client")
    assert re.search(r"2 files\s+3 calls\s+fix the navbar", rows[0])
    assert re.search(r"3 files\s+11 calls\s+unchecked change 8 ", rows[1])
    assert re.search(r"2 files\s+9 calls\s+unchecked change 7 ", rows[2])
    assert section.splitlines()[-2].strip() == "... 2 more"
    assert "unchecked change 1 " not in section and "unchecked change 0 " not in section
    assert section.splitlines()[-1].strip() == (
        "This counts tests, type checks, linters and builds the tool recognises; "
        "checking by eye in a browser is not seen."
    )


def test_failed_last_test_list(tmp_path):
    text = render_report(task_store(tmp_path), now=NOW)
    section = text.split("Tasks whose last test failed")[1].split("\n\n")[0]
    rows = [line for line in section.splitlines() if re.match(r"  \d{4}-", line)]
    assert len(rows) == 2
    assert "run the checkout tests" in rows[0] and "web-client" in rows[0]
    assert "tested change that failed" in rows[1] and "3 files" in rows[1]
    assert "... " not in section


def test_failed_list_is_capped_at_five(tmp_path):
    store = Store(tmp_path / "store")
    add_session(
        store, "f", "app", when(15), [spec(f"failing change number {i} in the app", edits=1, test="failed") for i in range(7)]
    )
    section = render_report(store, now=NOW).split("Tasks whose last test failed")[1].split("\n\n")[0]
    assert len([line for line in section.splitlines() if re.match(r"  \d{4}-", line)]) == 5
    assert section.splitlines()[-1].strip() == "... 2 more"


def test_everything_checked_is_good_news(tmp_path):
    store = Store(tmp_path / "store")
    add_session(store, "g", "app", when(15), [spec("a change that was checked properly", edits=1, test="passed")])
    text = render_report(store, now=NOW)
    section = text.split("Edited files and ran no test or check")[1].split("\n\n")[0]
    assert "Every task that edited files also ran a test or check" in section
    assert "This counts tests" not in text
    assert "No task ended on a failing test." in text


def test_no_editing_tasks(tmp_path):
    store = Store(tmp_path / "store")
    add_session(store, "r", "app", when(15), [spec("read through the whole parser module", reads=2)])
    text = render_report(store, now=NOW)
    assert "No task edited any file in this period." in text


def test_long_titles_keep_lines_within_110(tmp_path):
    store = Store(tmp_path / "store")
    add_session(store, "l", "api-server", when(15), [spec("word " * 40, edits=1)])
    text = render_report(store, now=NOW)
    assert "..." in text
    rows = [line for line in text.splitlines() if re.match(r"  \d{4}-", line)]
    assert rows and max(len(line) for line in rows) <= 110


def test_day_window_follows_the_injected_now(tmp_path):
    store = task_store(tmp_path)
    wide = render_report(store, days=60, now=NOW)
    assert "(22 tasks in 5 sessions)" in wide and "tasks from the last 60 days" in wide
    assert re.search(r"api-server\s+17 tasks", wide)
    assert re.search(r"api-server\s+15 tasks", render_report(store, now=NOW))
    narrow = render_report(store, days=2, now=NOW)
    assert "(8 tasks in 3 sessions)" in narrow
    later = render_report(store, now=NOW + timedelta(days=30))
    assert "No task started in the last 14 days." in later
    assert "No task data yet" not in later


def test_rebuild_hint_when_task_rows_are_missing(tmp_path):
    store = task_store(tmp_path)
    with contextlib.closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("DELETE FROM tasks")
    text = render_report(store, now=NOW)
    assert "No task data yet for these sessions. Run kaizen import --all once to rebuild them." in text
    assert "Tasks by project" not in text


def test_rebuild_hint_for_runs_recorded_before_tasks(tmp_path):
    store = Store(tmp_path / "store")
    add_session(store, "o1", "app", when(20), [spec("an older session without prompt times", edits=1)], timed=False)
    add_session(store, "o2", "app", when(21), [spec("another older session without prompt times")], timed=False)
    text = render_report(store, now=NOW)
    assert "No task data yet for these sessions. Run kaizen import --all once to rebuild them." in text
    assert "Tasks by project" not in text


def test_one_timed_task_per_session_is_real_data(tmp_path):
    store = Store(tmp_path / "store")
    add_session(store, "t1", "app", when(20), [spec("a single timed request in this session", edits=1)])
    text = render_report(store, now=NOW)
    assert "No task data yet" not in text and "Tasks by project" in text


def test_task_sections_print_with_nothing_scored(tmp_path):
    text = render_report(task_store(tmp_path), now=NOW)
    assert "Tasks by project" in text
    assert "No session has been graded yet. Run kaizen score --pending." in text
    assert "Graded sessions" not in text
    assert "Corrections are extracted when sessions are graded. Run kaizen score --pending." in text


def test_graded_sessions_follow_the_task_sections(tmp_path):
    store = task_store(tmp_path)
    store.save_score("a1", make_score("api-server", "2026-11-20", tests="passed", total=6.0, quality=7.0))
    text = render_report(store, now=NOW)
    assert text.index("Tasks whose last test failed") < text.index("Graded sessions (last 1)") < text.index("By project")
    assert "No session has been graded yet" not in text
    for heading in ("Evidence", "Most re-read files", "Lowest runs"):
        assert heading in text


def group_text(tmp_path, groups):
    from kaizen.corrections import Group

    return render_report(
        hand_built_store(tmp_path),
        now=NOW,
        groups=groups if groups is None else ([Group(**g) for g in groups[0]], groups[1]),
    )


def test_corrections_section_with_groups(tmp_path):
    first = {
        "label": "runs no tests before saying the work is done",
        "count": 5,
        "sessions": 3,
        "examples": ["you did not run the tests", "run pytest first"],
    }
    second = {"label": "commits files it was told to leave out", "count": 3, "sessions": 2, "examples": []}
    text = group_text(tmp_path, ([first, second], "model"))
    section = text.split("What you keep correcting")[1].split("\n\n")[0]
    assert section.startswith(" (grouped by meaning, from 11 graded sessions)")
    lines = section.splitlines()
    assert lines[1] == "   5x in 3 sessions   runs no tests before saying the work is done"
    assert lines[2].strip() == 'e.g. "you did not run the tests"  /  "run pytest first"'
    assert lines[2].index("e.g.") == lines[1].index("runs no tests")
    assert lines[3] == "   3x in 2 sessions   commits files it was told to leave out"
    assert len(lines) == 4
    assert "exact wording" not in text


def test_corrections_section_without_groups(tmp_path):
    text = group_text(tmp_path, ([], "model"))
    section = text.split("What you keep correcting")[1].split("\n\n")[0]
    assert "No correction repeats yet." in section
    assert "exact wording" not in section


def test_corrections_section_flags_exact_matching(tmp_path):
    for path in ("exact", "exact (model call failed)"):
        section = group_text(tmp_path / path.split()[0], ([], path)).split("What you keep correcting")[1].split("\n\n")[0]
        assert "No correction repeats yet." in section
        assert "exact wording" in section
    grouped = {"label": "same words again", "count": 2, "sessions": 2, "examples": ["same words again"]}
    section = group_text(tmp_path / "g", ([grouped], "exact")).split("What you keep correcting")[1].split("\n\n")[0]
    assert "2x in 2 sessions   same words again" in section and "exact wording" in section


def test_corrections_section_when_nothing_is_scored(tmp_path):
    text = render_report(task_store(tmp_path), now=NOW, groups=([], "model"))
    assert "Corrections are extracted when sessions are graded. Run kaizen score --pending." in text
    assert "What you keep correcting" not in text


def test_colour_on_and_off(tmp_path, monkeypatch):
    store = task_store(tmp_path)
    store.save_score("a1", make_score("api-server", "2026-11-20", tests="passed", total=6.0, quality=7.0))
    monkeypatch.setattr(cli, "use_colour", lambda: False)
    plain = render_report(store, now=NOW)
    assert "\x1b" not in plain
    monkeypatch.setattr(cli, "use_colour", lambda: True)
    coloured = render_report(store, now=NOW)
    assert ANSI.sub("", coloured) == plain
    assert "\x1b[1mTasks by project\x1b[0m" in coloured
    assert "\x1b[1mGraded sessions (last 1)\x1b[0m" in coloured
    assert "\x1b[33m9\x1b[0m ran none" in coloured
    assert "\x1b[33m1\x1b[0m failed" in coloured
    assert "\x1b[33m0" not in coloured
    assert "\x1b[31m" not in coloured and "\x1b[32m" not in coloured and "\x1b[2m" not in coloured
