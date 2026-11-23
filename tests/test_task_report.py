import re
from datetime import UTC, datetime

from kaizen import cli
from kaizen.report import render_report
from kaizen.store import Store

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
ASK = "please fix the navbar spacing on mobile screens"
ANSI = re.compile(r"\x1b\[\d+m")
NONE_YET = "No task has been graded yet. Run kaizen score --tasks."


def base_store(tmp_path, make_tasks):
    store = Store(tmp_path / "store")
    store.save_run(make_tasks(tasks=[{"prompts": [ASK], "files": ["nav.py"]}]))
    return store


def grade(store, n, repo, day, quality, title="a task", items=None, abstained=False, idx=0):
    items = items or {}
    verdict = {
        "quality": quality,
        "abstained": abstained,
        "backend": "haiku",
        "items": items,
        "reasons": [f"{name}: {e['reason']}" for name, e in items.items()],
    }
    saved = {
        "verdict": verdict,
        "repo": repo,
        "title": title,
        "session_id": f"g{n}",
        "idx": idx,
        "started_at": f"{day}T10:00:00+00:00",
        "ended_at": f"{day}T10:30:00+00:00",
    }
    store.save_task_score(f"key{n}", f"g{n}", idx, saved)


def section(text):
    return text.split("Graded tasks (")[1].split("\n\n")[0]


def test_graded_section_counts_projects_and_lowest(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    nav = {
        "did_what_was_asked": {"score": 6, "reason": "close enough"},
        "verified_before_done": {"score": 2, "reason": "no test or check ran after the last edit"},
    }
    mig = {
        "did_what_was_asked": {"score": 3, "reason": "the migration covers two of the three tables named"},
        "verified_before_done": {"score": 5, "reason": "ran the tests"},
    }
    grade(store, 1, "web-client", "2026-11-22", 2.8, "fix the navbar spacing on mobile", nav)
    grade(store, 2, "api-server", "2026-11-21", 3.4, "migrate the session table", mig)
    grade(store, 3, "api-server", "2026-11-20", 9.0, "add the health route")
    grade(store, 4, "api-server", "2026-11-20", None, "nothing", abstained=True)
    grade(store, 5, "api-server", "2026-11-20", None, "model was down")
    text = render_report(store, now=NOW)
    lines = section(text).splitlines()
    assert lines[0] == "3 graded, 1 abstained, last 14 days)"
    assert lines[1] == "  api-server   6.2 avg over 2 tasks     web-client   2.8 avg over 1 task"
    assert lines[2] == "Lowest graded tasks"
    assert lines[3] == "  2.8  2026-11-22  web-client   fix the navbar spacing on mobile"
    assert lines[4] == "       verified_before_done: no test or check ran after the last edit"
    assert lines[5] == "  3.4  2026-11-21  api-server   migrate the session table"
    assert lines[6] == "       did_what_was_asked: the migration covers two of the three tables named"
    assert lines[7] == "  9.0  2026-11-20  api-server   add the health route"
    assert len(lines) == 8
    print("\n".join(["Graded tasks (" + lines[0], *lines[1:]]))


def test_section_sits_between_corrections_and_graded_sessions(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    grade(store, 1, "api-server", "2026-11-22", 5.0)
    store.save_score("old", {"verdict": {"quality": 5.0}, "signals": {}, "stats": {}, "score": {}, "repo": "api-server",
                             "started_at": "2026-11-20T10:00:00Z", "corrections_known": True})
    text = render_report(store, now=NOW)
    assert text.index("What you keep correcting") < text.index("Graded tasks (") < text.index("Graded sessions")
    bare = render_report(base_store(tmp_path / "x", make_tasks), now=NOW)
    assert bare.index("Corrections are extracted") < bare.index(NONE_YET) < bare.index("No session has been graded yet")


def test_none_graded(tmp_path, make_tasks):
    text = render_report(base_store(tmp_path, make_tasks), now=NOW)
    assert NONE_YET in text and "Graded tasks (" not in text


def test_abstained_only_still_shows_the_counts(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    grade(store, 1, "api-server", "2026-11-22", None, abstained=True)
    out = section(render_report(store, now=NOW)).splitlines()
    assert out[0] == "0 graded, 1 abstained, last 14 days)"
    assert "Lowest graded tasks" not in "\n".join(out)
    assert NONE_YET not in "\n".join(out)


def test_day_window_follows_the_injected_now(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    grade(store, 1, "api-server", "2026-11-22", 8.0)
    grade(store, 2, "api-server", "2026-11-05", 2.0, "too old")
    text = render_report(store, days=14, now=NOW)
    assert section(text).startswith("1 graded, 0 abstained, last 14 days)")
    assert "too old" not in text
    wider = render_report(store, days=30, now=NOW)
    assert section(wider).startswith("2 graded, 0 abstained, last 30 days)")
    only_old = base_store(tmp_path / "o", make_tasks)
    grade(only_old, 1, "api-server", "2026-10-01", 2.0)
    out = render_report(only_old, days=14, now=NOW)
    assert "No task was graded in the last 14 days" in out and NONE_YET not in out


def test_lowest_lists_five_lowest_with_a_quality_and_cuts_to_110(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    for n in range(1, 8):
        grade(store, n, "api-server", f"2026-11-{10 + n}", float(n), f"task number {n} " + "x" * 200,
              {"did_what_was_asked": {"score": n, "reason": "word " * 60}})
    lines = section(render_report(store, now=NOW)).splitlines()
    lowest = lines[lines.index("Lowest graded tasks") + 1 :]
    assert len(lowest) == 10
    assert [ln.split()[0] for ln in lowest[0::2]] == ["1.0", "2.0", "3.0", "4.0", "5.0"]
    assert all(len(ln) <= 110 for ln in lowest)
    assert all(ln.endswith("...") for ln in lowest)


def test_lowest_item_without_a_reason_shows_its_name_and_missing_scores_are_skipped(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    items = {
        "a_item": {"score": None, "reason": "skipped"},
        "b_item": {"score": 4, "reason": ""},
        "c_item": {"score": 9, "reason": "fine"},
    }
    grade(store, 1, "api-server", "2026-11-22", 6.5, "x task", items)
    assert "       b_item\n" in section(render_report(store, now=NOW)) + "\n"


def test_projects_one_per_line_when_the_line_would_pass_110(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    names = [f"a-rather-long-project-name-{c}" for c in "abc"]
    for n, name in enumerate(names, 1):
        grade(store, n, name, "2026-11-22", 5.0 + n)
    lines = section(render_report(store, now=NOW)).splitlines()
    rows = [ln for ln in lines if "avg over" in ln]
    assert len(rows) == 3 and all(len(r) <= 110 for r in rows)
    assert [r.split()[0] for r in rows] == sorted(names, key=lambda n: n)


def test_projects_ordered_by_number_of_graded_tasks(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    grade(store, 1, "alpha", "2026-11-22", 9.0)
    grade(store, 2, "beta", "2026-11-22", 4.0)
    grade(store, 3, "beta", "2026-11-22", 6.0)
    row = section(render_report(store, now=NOW)).splitlines()[1]
    assert row.index("beta") < row.index("alpha")


def test_a_grown_task_counts_once_with_its_newest_grade(tmp_path, make_tasks):
    store = base_store(tmp_path, make_tasks)
    store.save_task_score("oldkey", "g1", 0, {"verdict": {"quality": 2.0}, "repo": "api-server", "title": "t", "session_id": "g1", "idx": 0,
                                              "started_at": "2026-11-22T10:00:00+00:00"})
    store.save_task_score("newkey", "g1", 0, {"verdict": {"quality": 8.0}, "repo": "api-server", "title": "t", "session_id": "g1", "idx": 0,
                                              "started_at": "2026-11-22T10:00:00+00:00"})
    out = section(render_report(store, now=NOW)).splitlines()
    assert out[0].startswith("1 graded")
    assert out[1] == "  api-server   8.0 avg over 1 task"


def test_only_the_heading_is_painted(tmp_path, make_tasks, monkeypatch):
    store = base_store(tmp_path, make_tasks)
    grade(store, 1, "api-server", "2026-11-22", 5.0)
    monkeypatch.setattr(cli, "use_colour", lambda: False)
    plain = render_report(store, now=NOW)
    monkeypatch.setattr(cli, "use_colour", lambda: True)
    coloured = render_report(store, now=NOW)
    assert ANSI.sub("", coloured) == plain
    assert "\x1b[1mGraded tasks (1 graded, 0 abstained, last 14 days)\x1b[0m" in coloured
