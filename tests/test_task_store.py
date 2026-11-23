import contextlib
import sqlite3
from datetime import UTC, datetime

from kaizen.store import Store
from kaizen.tasks import TaskSummary, summarise, task_key

ASK = "please fix the navbar spacing on mobile screens"
ASK2 = "now migrate the session table to the new schema"
ASK3 = "then update the docs for the migration changes"
FAKE_GH = "ghp_0123456789abcdefghijABCDEFGHIJ012345"


def two(make_tasks, **kw):
    return make_tasks(
        tasks=[
            {"prompts": [ASK], "files": ["nav.py"], "test": True},
            {"prompts": [ASK2], "files": ["session.py"]},
        ],
        **kw,
    )


def keys(store):
    return {(t.session_id, t.index): t.key for t in store.list_tasks()}


def test_task_key_is_16_hex_and_depends_on_content(make_tasks):
    summary = summarise(two(make_tasks))[0]
    key = task_key(summary)
    assert len(key) == 16 and int(key, 16) >= 0
    assert task_key(summary) == key
    grown = TaskSummary(**{**summary.to_dict(), "tool_calls": summary.tool_calls + 1})
    assert task_key(grown) != key


def test_key_stable_when_a_later_task_is_appended_and_changes_for_a_grown_task(tmp_path, make_tasks):
    store = Store(tmp_path)
    store.save_run(two(make_tasks))
    before = keys(store)
    store.save_run(
        make_tasks(
            tasks=[
                {"prompts": [ASK], "files": ["nav.py"], "test": True},
                {"prompts": [ASK2], "files": ["session.py", "extra.py"]},
                {"prompts": [ASK3], "files": ["docs.py"]},
            ]
        )
    )
    after = keys(store)
    assert after[("s1", 0)] == before[("s1", 0)]
    assert after[("s1", 1)] != before[("s1", 1)]
    assert ("s1", 2) in after
    assert all(len(k) == 16 for k in after.values())


def test_old_database_without_key_column_is_rebuilt(tmp_path, make_tasks):
    store = Store(tmp_path)
    store.save_run(two(make_tasks))
    store.save_run(two(make_tasks, session_id="s2"))
    expected = keys(store)
    with contextlib.closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("DROP TABLE tasks")
        db.execute(
            "CREATE TABLE tasks (session_id TEXT, idx INTEGER, repo TEXT, started_at TEXT, ended_at TEXT, "
            "title TEXT, prompts INTEGER, tool_calls INTEGER, files_edited INTEGER, kind TEXT, last_test TEXT, "
            "PRIMARY KEY (session_id, idx))"
        )
        db.execute("INSERT INTO tasks (session_id, idx) VALUES ('ghost', 0)")
    reopened = Store(tmp_path)
    assert keys(reopened) == expected
    with contextlib.closing(sqlite3.connect(store.db_path)) as db:
        assert "key" in [row[1] for row in db.execute("PRAGMA table_info(tasks)")]


def test_task_score_round_trip_is_redacted_and_newest_first(tmp_path):
    store = Store(tmp_path)
    assert store.get_task_score("k1") is None
    store.save_task_score("k1", "s1", 0, {"verdict": {"quality": 5.0}, "note": FAKE_GH})
    store.save_task_score("k2", "s1", 1, {"verdict": {"quality": 6.0}})
    got = store.get_task_score("k1")
    assert got["verdict"]["quality"] == 5.0 and "ghp_0123" not in got["note"]
    assert [k for k, _ in store.list_task_scores()] == ["k2", "k1"]
    assert store.audit() == []


def test_pending_excludes_no_edits_and_graded_newest_first_with_limit(tmp_path, make_tasks):
    store = Store(tmp_path)
    store.save_run(
        make_tasks(
            session_id="a",
            tasks=[
                {"prompts": [ASK], "files": ["a.py"]},
                {"prompts": [ASK2]},
                {"prompts": [ASK3], "files": ["b.py"], "test": True},
            ],
        )
    )
    later = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
    store.save_run(make_tasks(session_id="b", tasks=[{"prompts": [ASK], "files": ["c.py"]}], base=later))
    pending = store.pending_task_scores()
    assert [(t.session_id, t.index, t.kind) for t in pending] == [
        ("b", 0, "edited_unchecked"),
        ("a", 2, "edited_checked"),
        ("a", 0, "edited_unchecked"),
    ]
    assert all(t.key for t in pending)
    assert [(t.session_id, t.index) for t in store.pending_task_scores(limit=2)] == [("b", 0), ("a", 2)]
    store.save_task_score(pending[0].key, "b", 0, {})
    assert [(t.session_id, t.index) for t in store.pending_task_scores()] == [("a", 2), ("a", 0)]


def test_grown_task_is_pending_again_and_old_grade_remains(tmp_path, make_tasks):
    store = Store(tmp_path)
    store.save_run(two(make_tasks))
    old = next(t for t in store.pending_task_scores() if t.index == 1)
    store.save_task_score(old.key, "s1", 1, {"verdict": {"quality": 4.0}})
    assert [t.index for t in store.pending_task_scores()] == [0]
    store.save_run(
        make_tasks(
            tasks=[
                {"prompts": [ASK], "files": ["nav.py"], "test": True},
                {"prompts": [ASK2], "files": ["session.py", "extra.py"]},
            ]
        )
    )
    pending = store.pending_task_scores()
    assert sorted(t.index for t in pending) == [0, 1]
    assert next(t for t in pending if t.index == 1).key != old.key
    assert store.get_task_score(old.key)["verdict"]["quality"] == 4.0


def test_audit_covers_task_scores(tmp_path):
    store = Store(tmp_path)
    store.save_task_score("k1", "s1", 0, {"x": "plain"})
    with contextlib.closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("UPDATE task_scores SET json = ?", ('{"x": "' + FAKE_GH + '"}',))
    assert ("ledger.db", "github_token") in store.audit()
    with contextlib.closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("UPDATE task_scores SET json = ?", ('{"x": "id Zx9kQ2mP7vLr4TnW8bYc3HdJ end"}',))
    assert ("ledger.db", "Zx9k…(24 chars)") in store.audit_suspects()


def test_old_rubric_grade_is_pending_again_only_when_a_version_is_given(tmp_path, make_tasks):
    store = Store(tmp_path)
    store.save_run(two(make_tasks))
    first, second = store.pending_task_scores()
    store.save_task_score(first.key, first.session_id, first.index, {"verdict": {"quality": 5.0, "rubric_version": 1}})
    store.save_task_score(second.key, second.session_id, second.index, {"verdict": {"quality": 6.0, "rubric_version": 2}})
    assert store.pending_task_scores() == []
    assert [t.key for t in store.pending_task_scores(rubric_version=2)] == [first.key]
    assert [t.key for t in store.pending_task_scores(rubric_version=1)] == []


def test_grade_without_a_rubric_version_counts_as_old(tmp_path, make_tasks):
    store = Store(tmp_path)
    store.save_run(two(make_tasks))
    first = store.pending_task_scores()[0]
    store.save_task_score(first.key, first.session_id, first.index, {"verdict": {"quality": 5.0}})
    assert first.key in [t.key for t in store.pending_task_scores(rubric_version=2)]
