from datetime import UTC, datetime

import pytest

from kaizen import cli
from kaizen.cli import main
from kaizen.judge.rubric import RUBRIC_VERSION
from kaizen.report import calibration_summary
from kaizen.store import Store

LAST = "This checks that the judge is consistent with facts it could see. It does not show the judge is right."
ASK = "please fix the navbar spacing on mobile screens"
ASK2 = "now migrate the session table to the new schema"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIZEN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cli, "use_colour", lambda: False)
    monkeypatch.setattr(cli, "RUNNER", never)
    return tmp_path / "home"


def never(argv, stdin=None):
    raise AssertionError("the model was called")


def day(n):
    return datetime(2026, 11, n, 12, 0, tzinfo=UTC).astimezone().strftime("%Y-%m-%d")


def put(store, key, quality, corrections=0, last_test="passed", interruptions=0, version=RUBRIC_VERSION,
        known=True, title="a task", repo="api-server", date=20):
    saved = {
        "verdict": {"quality": quality, "rubric_version": version, "backend": "haiku"},
        "signals": {"corrections": ["c"] * corrections, "interruptions": interruptions},
        "corrections_known": known,
        "session_id": f"sess-{key}",
        "idx": 0,
        "repo": repo,
        "title": title,
        "last_test": last_test,
        "started_at": f"2026-11-{date}T12:00:00+00:00",
        "ended_at": f"2026-11-{date}T12:30:00+00:00",
    }
    store.save_task_score(key, saved["session_id"], 0, saved)


def check(capsys):
    assert main(["check-judge"]) == 0
    return capsys.readouterr().out


def test_empty_store(home, capsys):
    out = check(capsys).splitlines()
    assert out[0] == f"kaizen check-judge - 0 graded tasks (rubric {RUBRIC_VERSION})"
    assert "Against your ratings (kz and calibrate)" in out
    assert any("No rated tasks yet" in line for line in out)
    assert any("Too few" in line for line in out)
    assert out[-1] == "  " + LAST


def test_command_never_calls_the_model_or_writes(home, capsys):
    store = Store()
    put(store, "k1", 5.0)
    before = store.list_task_scores()
    check(capsys)
    assert store.list_task_scores() == before


def full_store():
    store = Store()
    for i in range(6):
        put(store, f"clean{i}", 7.0 + (i % 2) * 0.2, title=f"clean task {i}")
    for i in range(5):
        put(store, f"bad{i}", 4.0, corrections=1, title=f"trouble task {i}")
    put(store, "hi", 8.4, corrections=3, title="migrate the session table", date=21)
    put(store, "low", 2.1, title="rename the env variables", date=20)
    put(store, "fail", 9.0, last_test="failed", title="failed test but loved", date=19)
    put(store, "intr", 4.0, interruptions=2, title="interrupted")
    return store


def test_both_sections_full(home, capsys):
    store = full_store()
    for key, grade in (("clean0", 9.0), ("clean1", 7.0), ("clean2", 7.0), ("bad0", 4.0), ("bad1", 9.0), ("hi", 2.0)):
        store.save_human_grade(key, grade)
    out = check(capsys)
    lines = out.splitlines()
    assert lines[0] == f"kaizen check-judge - 15 graded tasks (rubric {RUBRIC_VERSION})"
    assert "  Judge agrees with you on 4 of 6 rated tasks (within 2 points)." in lines
    assert "  A constant judge answering 7 would agree on 4 of 6." in lines
    gaps = lines[lines.index("  Largest gaps") + 1 : lines.index("Against the evidence the judge was shown") - 1]
    assert gaps == [
        f"    You 2.0   Judge 8.4   {day(21)}  api-server   migrate the session table",
        f"    You 9.0   Judge 4.0   {day(20)}  api-server   trouble task 1",
    ]
    assert lines[lines.index("  Separation: 1.2 points.") - 2].endswith("7 tasks   judge 6.4 avg")
    assert lines[lines.index("  Separation: 1.2 points.") - 1].endswith("8 tasks   judge 5.2 avg")
    assert lines[lines.index("  Tasks that went cleanly (no correction, no failed test, no interruption)    7 tasks   judge 6.4 avg") + 1].startswith("  Tasks with trouble")
    assert "  Inversions" in lines
    assert any(line.startswith("    Judge 8.4 with 3 corrections") for line in lines)
    assert any(line.startswith("    Judge 9.0 with a failed last test") for line in lines)
    assert any(line.startswith("    Judge 2.1 on a clean task") for line in lines)
    assert lines[-1] == "  " + LAST


def test_evidence_averages_and_separation(home, capsys):
    store = Store()
    for i in range(5):
        put(store, f"c{i}", 8.0)
    for i in range(5):
        put(store, f"t{i}", 4.0, corrections=1)
    lines = check(capsys).splitlines()
    clean = next(line for line in lines if line.startswith("  Tasks that went cleanly"))
    trouble = next(line for line in lines if line.startswith("  Tasks with trouble"))
    assert clean.endswith("5 tasks   judge 8.0 avg")
    assert trouble.endswith("5 tasks   judge 4.0 avg")
    assert "  Separation: 4.0 points." in lines
    assert "  Inversions: none." in lines


def test_too_few_on_either_side_prints_counts_only(home, capsys):
    store = Store()
    for i in range(6):
        put(store, f"c{i}", 8.0)
    for i in range(4):
        put(store, f"t{i}", 3.0, corrections=2)
    out = check(capsys)
    clean = next(line for line in out.splitlines() if line.startswith("  Tasks that went cleanly"))
    trouble = next(line for line in out.splitlines() if line.startswith("  Tasks with trouble"))
    assert clean.endswith("6 tasks") and trouble.endswith("4 tasks")
    assert "avg" not in clean + trouble
    assert "Separation" not in out and "Inversions" not in out
    assert "too few" in out.lower()


def test_inversions_are_capped_at_five_each(home, capsys):
    store = Store()
    for i in range(5):
        put(store, f"c{i}", 8.0)
    for i in range(7):
        put(store, f"h{i}", 7.0 + i * 0.1, corrections=2)
    for i in range(7):
        put(store, f"l{i}", 1.0 + i * 0.1)
    lines = check(capsys).splitlines()
    assert sum("with 2 corrections" in line for line in lines) == 5
    assert sum("on a clean task" in line for line in lines) == 5


def test_older_rubric_grades_are_left_out_and_counted(home, capsys):
    store = Store()
    for i in range(5):
        put(store, f"c{i}", 8.0)
    for i in range(5):
        put(store, f"t{i}", 4.0, corrections=1)
    for i in range(3):
        put(store, f"old{i}", 1.0, version=1)
    out = check(capsys)
    lines = out.splitlines()
    assert lines[0] == f"kaizen check-judge - 10 graded tasks (rubric {RUBRIC_VERSION})"
    assert lines[1] == "3 older grades from an earlier rubric were left out."
    assert "Judge 1.0" not in out and "  Separation: 4.0 points." in lines


def test_unknown_corrections_are_left_out_and_counted(home, capsys):
    store = Store()
    for i in range(5):
        put(store, f"c{i}", 8.0)
    for i in range(5):
        put(store, f"t{i}", 4.0, corrections=1)
    put(store, "u1", 9.0, known=False)
    put(store, "u2", 1.0, known=False)
    lines = check(capsys).splitlines()
    assert "  2 graded tasks were left out because their corrections are unknown." in lines
    assert "  Separation: 4.0 points." in lines


def test_abstained_tasks_are_not_graded(home, capsys):
    store = Store()
    put(store, "a1", None)
    assert check(capsys).splitlines()[0] == f"kaizen check-judge - 0 graded tasks (rubric {RUBRIC_VERSION})"


@pytest.fixture
def seeded(home, make_tasks):
    store = Store()
    store.save_run(
        make_tasks(tasks=[{"prompts": [ASK], "files": ["nav.py"]}, {"prompts": [ASK2], "files": ["s.py"]}])
    )
    tasks = sorted(store.list_tasks(), key=lambda t: t.index)
    return store, tasks


def rated_line(out):
    return next(line for line in out.splitlines() if "Judge agrees with you" in line)


def test_kz_rating_wins_over_calibrate_and_latest_rating_wins(seeded, capsys):
    store, (first, second) = seeded
    put(store, first.key, 8.0, title=first.title)
    put(store, second.key, 8.0, title=second.title)
    store.save_human_grade(first.key, 1.0)
    store.save_human_grade(second.key, 1.0)
    store.save_rating("s1", 9.0, created_at=first.ended_at)
    store.save_rating("s1", 3.0, created_at="2026-11-22T09:05:00+00:00")
    store.save_rating("s1", 8.0, created_at=second.ended_at)
    out = check(capsys)
    assert "Judge agrees with you on 2 of 2 rated tasks (within 2 points)." in rated_line(out)


def test_rated_but_not_graded_yet_has_its_own_line(seeded, capsys):
    store, (first, second) = seeded
    put(store, first.key, 8.0, title=first.title)
    store.save_rating("s1", 8.0, created_at=first.ended_at)
    store.save_rating("s1", 5.0, created_at=second.ended_at)
    out = check(capsys)
    assert "1 of 1 rated tasks" in rated_line(out)
    assert "  1 rated task has no judge grade yet." in out.splitlines()


def test_calibrate_only_grades_count_and_non_task_ids_are_ignored(home, capsys):
    store = Store()
    put(store, "k1", 5.0)
    store.save_human_grade("k1", 9.0)
    store.save_human_grade("some-session-id", 1.0)
    out = check(capsys)
    assert "Judge agrees with you on 0 of 1 rated tasks (within 2 points)." in out
    lines = out.splitlines()
    gap = lines[lines.index("  Largest gaps") + 1]
    assert gap == f"    You 9.0   Judge 5.0   {day(20)}  api-server   a task"


def test_largest_gaps_need_more_than_two_points_and_cap_at_five(home, capsys):
    store = Store()
    for i in range(8):
        put(store, f"g{i}", 2.0)
        store.save_human_grade(f"g{i}", 5.0 + i * 0.5)
    put(store, "near", 5.0)
    store.save_human_grade("near", 7.0)
    lines = check(capsys).splitlines()
    start = lines.index("  Largest gaps") + 1
    rows = [line for line in lines[start:] if line.startswith("    You ")]
    assert len(rows) == 5
    assert rows[0].startswith("    You 8.5   Judge 2.0")
    assert all("Judge 5.0" not in r for r in rows)


def test_no_gaps_prints_no_largest_gaps_heading(home, capsys):
    store = Store()
    put(store, "k1", 5.0)
    store.save_human_grade("k1", 6.0)
    assert "Largest gaps" not in check(capsys)


def test_constant_judge_line_matches_the_calibration_summary(home, capsys):
    store = Store()
    pairs = []
    for i, (judge, human) in enumerate([(5.0, 7.0), (6.0, 7.5), (2.0, 7.0), (8.0, 3.0)]):
        put(store, f"k{i}", judge)
        store.save_human_grade(f"k{i}", human)
        pairs.append((judge, human))
    summary = calibration_summary(pairs, 0).splitlines()
    lines = check(capsys).splitlines()
    constant = summary[1].replace("runs", "rated tasks")
    assert f"  {constant}" in lines


def test_only_two_headings_are_painted(home, capsys, monkeypatch):
    monkeypatch.setattr(cli, "use_colour", lambda: True)
    store = Store()
    put(store, "k1", 5.0)
    store.save_human_grade("k1", 9.0)
    out = check(capsys)
    assert out.count("\x1b[1m") == 2
    assert out.count("\x1b[") == 4
    assert "\x1b[1mAgainst your ratings (kz and calibrate)\x1b[0m" in out
    assert "\x1b[1mAgainst the evidence the judge was shown\x1b[0m" in out
