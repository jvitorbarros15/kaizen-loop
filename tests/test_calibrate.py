import contextlib
import re
from datetime import UTC, datetime, timedelta

import pytest

from kaizen import cli
from kaizen.cli import main, paint
from kaizen.record.model import RunRecord, ToolCall
from kaizen.store import Store

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
ESC = "\x1b["


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIZEN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cli, "now", lambda: NOW)
    monkeypatch.setattr(cli, "use_colour", lambda: False)
    return tmp_path / "home"


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def clock(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).astimezone().strftime("%H:%M")


def seed(store, sid, hours_ago=1.0, quality=4.4, messages=("Fix the login redirect",), calls=(), corrections=None, reasons=None):
    record = RunRecord(
        session_id=sid,
        cwd="/home/dev/api-server",
        repo="api-server",
        started_at=iso(hours_ago + 1),
        ended_at=iso(hours_ago),
        user_messages=list(messages),
        tool_calls=list(calls),
    )
    store.save_run(record)
    verdict = {"quality": quality, "reasons": reasons or [], "backend": "haiku", "abstained": quality is None}
    saved = {
        "score": {"total": 5.0},
        "signals": {"corrections": corrections or []},
        "verdict": verdict,
        "corrections_known": corrections is not None,
        "repo": "api-server",
        "started_at": record.started_at,
    }
    store.save_score(sid, saved)


def edit(path):
    return ToolCall(id="e", name="Edit", input={"file_path": path, "old_string": "a", "new_string": "b"})


def bash(command, exit_code=0):
    return ToolCall(id="b", name="Bash", input={"command": command}, exit_code=exit_code)


def grade_with(monkeypatch, answers):
    items = iter(answers)
    prompts = []

    def read_line(prompt):
        prompts.append(prompt)
        return next(items)

    monkeypatch.setattr(cli, "read_line", read_line)
    return prompts


def test_offers_only_recent_ungraded_scored_runs_newest_first(home, monkeypatch, capsys):
    store = Store()
    seed(store, "old", hours_ago=72, messages=("task old",))
    seed(store, "older", hours_ago=5, messages=("task older",))
    seed(store, "newer", hours_ago=1, messages=("task newer",))
    seed(store, "graded", hours_ago=2, messages=("task graded",))
    seed(store, "abstained", hours_ago=2, quality=None, messages=("task abstained",))
    store.save_human_grade("graded", 5.0)
    seen = []

    def read_line(prompt):
        seen.append(capsys.readouterr().out)
        return "s"

    monkeypatch.setattr(cli, "read_line", read_line)
    assert main(["calibrate"]) == 0
    assert len(seen) == 2
    assert "task newer" in seen[0] and "[1/2]" in seen[0]
    assert "task older" in seen[1] and "[2/2]" in seen[1]
    assert all("task old\n" not in s and "task graded" not in s and "task abstained" not in s for s in seen)


def test_hours_option_widens_the_window(home, monkeypatch, capsys):
    store = Store()
    seed(store, "old", hours_ago=72, messages=("task old",))
    grade_with(monkeypatch, ["s"])
    assert main(["calibrate", "--hours", "100"]) == 0
    assert "task old" in capsys.readouterr().out


def test_window_uses_end_time_not_start_time(home, monkeypatch, capsys):
    store = Store()
    seed(store, "long", hours_ago=1, messages=("task long",))
    record = store.get_run("long")
    record.started_at = iso(200)
    store.save_run(record)
    store.save_score("long", {"verdict": {"quality": 4.0}, "signals": {}, "started_at": iso(200)})
    grade_with(monkeypatch, ["s"])
    main(["calibrate"])
    assert "task long" in capsys.readouterr().out


def test_n_limits_the_count(home, monkeypatch, capsys):
    store = Store()
    for i in range(4):
        seed(store, f"s{i}", hours_ago=1 + i)
    prompts = grade_with(monkeypatch, ["s", "s", "s", "s"])
    main(["calibrate", "--n", "2"])
    assert len(prompts) == 2


def test_nothing_recent_says_so_then_summary(home, monkeypatch, capsys):
    store = Store()
    seed(store, "old", hours_ago=72)

    def boom(prompt):
        raise AssertionError("asked for a grade")

    monkeypatch.setattr(cli, "read_line", boom)
    assert main(["calibrate", "--hours", "24"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "last 24 hours" in lines[0]
    assert "kaizen score --pending" in lines[0]
    assert lines[1] == ""
    assert "nothing to compare yet" in lines[2]


def test_empty_store_says_nothing_recent(home, monkeypatch, capsys):
    assert main(["calibrate"]) == 0
    assert "kaizen score --pending" in capsys.readouterr().out


FULL_SCREEN = """\
------------------------------------------------------------
[1/1]  api-server  ·  ended {ended}  ·  5 tool calls
Task      Fix the login redirect so it keeps the query string
Files     redirect.py, test_redirect.py
Tests     3 runs: 2 passed, 1 failed  (last: passed)
Checks    none
Asked later
          - also handle the logout page
          - [pasted text, 1,204 characters]
Corrected - told the agent the test file was in the wrong folder
Your grade 0-10 (Enter skips, q stops): """


def full_session(store):
    pasted = '<pasted_content id="1">' + "x" * 1204 + "</pasted_content>"
    seed(
        store,
        "s1",
        hours_ago=2,
        messages=("Fix the login redirect so it keeps the query string", "also handle the logout page", pasted),
        calls=[
            edit("/home/dev/api-server/auth/redirect.py"),
            edit("/home/dev/api-server/tests/test_redirect.py"),
            bash("pytest tests", 1),
            bash("pytest tests", 0),
            bash("pytest tests -q", 0),
        ],
        corrections=["told the agent the test file was in the wrong folder"],
        reasons=[
            "did_what_was_asked: edits match the requested order, but merge and publish are unverified",
            "verified_before_done: no test or check runs were recorded",
        ],
    )
    return store


def test_grading_screen_exact_plain_text(home, monkeypatch, capsys):
    full_session(Store())
    shown = []

    def read_line(prompt):
        shown.append(capsys.readouterr().out + prompt)
        return "s"

    monkeypatch.setattr(cli, "read_line", read_line)
    main(["calibrate"])
    assert shown[0].strip("\n") == FULL_SCREEN.format(ended=clock(2))
    assert "\x1b" not in shown[0]
    assert all(len(line) <= 100 for line in shown[0].splitlines())


def test_comparison_line_and_compact_reasons_after_grade(home, monkeypatch, capsys):
    full_session(Store())
    grade_with(monkeypatch, ["8"])
    main(["calibrate"])
    out = capsys.readouterr().out
    lines = out[out.index("You 8.0") :].splitlines()
    assert lines[0] == "You 8.0   Judge 4.4   difference 3.6"
    assert lines[1] == "  did_what_was_asked    edits match the requested order, but merge and publish are unverified"
    assert lines[2] == "  verified_before_done  no test or check runs were recorded"
    assert Store().human_grades()[0][1] == 8.0


def test_long_reason_cut_to_90(home, monkeypatch, capsys):
    store = Store()
    seed(store, "s1", reasons=["did_what_was_asked: " + "word " * 60])
    grade_with(monkeypatch, ["8"])
    main(["calibrate"])
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("  did_what"))
    assert len(line.removeprefix("  did_what_was_asked").strip()) <= 90


def test_judge_grade_never_shown_before_the_user_grades(home, monkeypatch, capsys):
    store = Store()
    seed(store, "s1", quality=4.4, reasons=["did_what_was_asked: matched the ask"])
    seed(store, "s2", hours_ago=2, quality=4.4, reasons=["did_what_was_asked: matched the ask"])
    shown = []
    answers = iter(["", "8"])

    def read_line(prompt):
        shown.append(capsys.readouterr().out)
        return next(answers)

    monkeypatch.setattr(cli, "read_line", read_line)
    main(["calibrate"])
    assert "4.4" not in shown[0] and "matched the ask" not in shown[0]
    assert "4.4" not in shown[1] and "matched the ask" not in shown[1]


def test_invalid_then_valid_grade(home, monkeypatch, capsys):
    seed(Store(), "s1")
    prompts = grade_with(monkeypatch, ["11", "abc", "7.5"])
    main(["calibrate"])
    out = capsys.readouterr().out
    assert out.count("Enter a number from 0 to 10.") == 2
    assert len(prompts) == 3
    assert Store().human_grades()[0][1] == 7.5


def test_q_stops(home, monkeypatch, capsys):
    store = Store()
    seed(store, "a")
    seed(store, "b", hours_ago=2)
    prompts = grade_with(monkeypatch, ["q"])
    main(["calibrate"])
    assert len(prompts) == 1


def test_screen_limits(home, monkeypatch, capsys):
    store = Store()
    files = [edit(f"/home/dev/api-server/pkg/deep/f{i}.py") for i in range(60)]
    commands = [bash(f"echo secret-command-{i}") for i in range(20)]
    long = "word " * 200
    seed(
        store,
        "s1",
        messages=(long, *[f"later request number {i} " + "y" * 200 for i in range(6)]),
        calls=[*files, *commands],
        corrections=[f"correction {i} " + "z" * 200 for i in range(5)],
    )
    shown = []

    def read_line(prompt):
        shown.append(capsys.readouterr().out)
        return "s"

    monkeypatch.setattr(cli, "read_line", read_line)
    main(["calibrate"])
    screen = shown[0]
    lines = screen.splitlines()
    assert all(len(line) <= 100 for line in lines)
    assert "secret-command" not in screen
    files_line = next(ln for ln in lines if ln.startswith("Files"))
    assert files_line == "Files     f0.py, f1.py, f2.py, f3.py, f4.py, +55 more"
    task_at = next(i for i, ln in enumerate(lines) if ln.startswith("Task"))
    task_lines = [lines[task_at]]
    for ln in lines[task_at + 1 :]:
        if not ln.startswith(" " * 10):
            break
        task_lines.append(ln)
    assert len(task_lines) == 2
    assert task_lines[1].endswith("...")
    later = [ln for ln in lines if ln.startswith("          - later request")]
    assert len(later) == 3
    assert "          +3 more" in lines
    corrections = [ln for ln in lines if "correction " in ln]
    assert len(corrections) == 3
    assert "          +2 more" in lines
    assert next(ln for ln in lines if ln.startswith("Tests")) == "Tests     none"


def test_checks_line_counts_outcomes(home, monkeypatch, capsys):
    store = Store()
    seed(store, "s1", calls=[edit("/home/dev/api-server/a.py"), bash("ruff check .", 1)])
    shown = []

    def read_line(prompt):
        shown.append(capsys.readouterr().out)
        return "s"

    monkeypatch.setattr(cli, "read_line", read_line)
    main(["calibrate"])
    assert "Checks    1 run: 1 failed  (last: failed)" in shown[0]
    assert "ruff" not in shown[0]


def test_empty_sections_say_none_on_same_line(home, monkeypatch, capsys):
    seed(Store(), "s1", calls=[edit("/home/dev/api-server/a.py")])
    shown = []

    def read_line(prompt):
        shown.append(capsys.readouterr().out)
        return "s"

    monkeypatch.setattr(cli, "read_line", read_line)
    main(["calibrate"])
    lines = shown[0].splitlines()
    assert "Asked later none" in lines
    assert "Corrected none" in lines
    assert "Files     a.py" in lines


def test_pasted_text_is_not_shown_as_a_request(home, monkeypatch, capsys):
    pasted = '<pasted_content id="p">' + "npm ERR! secret output\n" * 50 + "</pasted_content>"
    seed(Store(), "s1", messages=("do it", pasted))
    shown = []

    def read_line(prompt):
        shown.append(capsys.readouterr().out)
        return "s"

    monkeypatch.setattr(cli, "read_line", read_line)
    main(["calibrate"])
    assert "npm ERR" not in shown[0]
    assert "- [pasted text, 1,150 characters]" in shown[0]


def test_paint_plain_when_colour_off(home):
    assert paint("x", "green") == "x"


def test_paint_codes_when_colour_on(home, monkeypatch):
    monkeypatch.setattr(cli, "use_colour", lambda: True)
    assert paint("x", "green") == "\x1b[32mx\x1b[0m"
    assert paint("x", "yellow") == "\x1b[33mx\x1b[0m"
    assert paint("x", "red") == "\x1b[31mx\x1b[0m"
    assert paint("x", "dim") == "\x1b[2mx\x1b[0m"
    assert paint("x", "bold") == "\x1b[1mx\x1b[0m"


class FakeOut:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


def test_use_colour_needs_terminal_and_no_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cli.sys, "stdout", FakeOut(True))
    assert cli.use_colour() is True
    monkeypatch.setattr(cli.sys, "stdout", FakeOut(False))
    assert cli.use_colour() is False
    monkeypatch.setattr(cli.sys, "stdout", FakeOut(True))
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli.use_colour() is False


def test_colour_mode_same_words_codes_around_grades(home, monkeypatch, capsys):
    full_session(Store())
    prompts = grade_with(monkeypatch, ["8"])
    main(["calibrate"])
    plain = capsys.readouterr().out
    assert ESC not in plain

    with contextlib.closing(Store()._connect()) as db, db:
        db.execute("DELETE FROM human_grades")
    monkeypatch.setattr(cli, "use_colour", lambda: True)
    grade_with(monkeypatch, ["8"])
    main(["calibrate"])
    coloured = capsys.readouterr().out
    assert "\x1b[32m8.0\x1b[0m" in coloured
    assert "\x1b[33m4.4\x1b[0m" in coloured
    assert "\x1b[31m3.6\x1b[0m" in coloured
    assert "\x1b[2mTask\x1b[0m" in coloured
    assert re.sub(r"\x1b\[\d+m", "", coloured) == plain
    assert prompts


def test_small_difference_is_not_red(home, monkeypatch, capsys):
    seed(Store(), "s1", quality=7.0)
    monkeypatch.setattr(cli, "use_colour", lambda: True)
    grade_with(monkeypatch, ["8"])
    main(["calibrate"])
    out = capsys.readouterr().out
    assert "\x1b[31m" not in out
    assert "difference 1.0" in out
