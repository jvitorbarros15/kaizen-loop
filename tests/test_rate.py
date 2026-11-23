import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kaizen import cli
from kaizen.cli import main
from kaizen.pipeline import task_for_rating
from kaizen.store import Store

NOW = datetime(2026, 11, 23, 14, 32, tzinfo=UTC)
FAKE_GH = "ghp_0123456789abcdefghijABCDEFGHIJ012345"
ASK = "please fix the navbar spacing on mobile screens"
ASK2 = "now migrate the session table to the new schema"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIZEN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("KAIZEN_INTERNAL", raising=False)
    monkeypatch.setattr(cli, "now", lambda: NOW)
    return tmp_path / "home"


def clock(moment):
    return moment.astimezone().strftime("%H:%M")


def test_save_rating_and_list_newest_first(tmp_path):
    store = Store(tmp_path)
    store.save_rating("s1", 7.5, "clean diff", created_at="2026-11-23T10:00:00+00:00")
    store.save_rating("s2", 3.0, created_at="2026-11-23T11:00:00+00:00")
    rows = store.list_ratings()
    assert [(r["session_id"], r["grade"], r["note"]) for r in rows] == [("s2", 3.0, ""), ("s1", 7.5, "clean diff")]
    assert rows[0]["created_at"] == "2026-11-23T11:00:00+00:00"
    assert isinstance(rows[0]["id"], int)


def test_save_rating_defaults_the_time_and_redacts_the_note(tmp_path):
    store = Store(tmp_path)
    store.save_rating("s1", 6, f"token {FAKE_GH} leaked")
    row = store.list_ratings()[0]
    assert FAKE_GH not in row["note"]
    assert datetime.fromisoformat(row["created_at"]).tzinfo is not None


def test_ratings_table_is_covered_by_audit(tmp_path):
    store = Store(tmp_path)
    store.save_rating("s1", 6, "plain")
    with contextlib.closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("UPDATE ratings SET note = ?", (FAKE_GH,))
    assert ("ledger.db", "github_token") in store.audit()


@pytest.fixture
def seeded(tmp_path, make_tasks):
    store = Store(tmp_path / "s")
    store.save_run(
        make_tasks(tasks=[{"prompts": [ASK], "files": ["nav.py"]}, {"prompts": [ASK2], "files": ["session.py"]}])
    )
    tasks = sorted(store.list_tasks(), key=lambda t: t.index)
    return store, tasks


def rating(moment, session="s1"):
    return {"session_id": session, "grade": 7.0, "note": "", "created_at": moment.isoformat()}


def at(text, minutes=0):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) + timedelta(minutes=minutes)


def test_task_for_rating_picks_the_task_that_was_active(seeded):
    store, (first, second) = seeded
    assert task_for_rating(store, rating(at(first.ended_at, 5))).index == 0
    assert task_for_rating(store, rating(at(second.started_at, 1))).index == 1
    assert task_for_rating(store, rating(at(second.ended_at, 5))).index == 1


def test_task_for_rating_binds_at_the_exact_start_time(seeded):
    store, (first, second) = seeded
    assert task_for_rating(store, rating(at(second.started_at))).index == 1


def test_task_for_rating_before_any_task_is_none(seeded):
    store, (first, _) = seeded
    assert task_for_rating(store, rating(at(first.started_at, -5))) is None


def test_task_for_rating_six_hour_limit(seeded):
    store, (_, second) = seeded
    assert task_for_rating(store, rating(at(second.ended_at, 6 * 60))).index == 1
    assert task_for_rating(store, rating(at(second.ended_at, 6 * 60 + 1))) is None


def test_task_for_rating_session_without_tasks(seeded):
    store, (first, _) = seeded
    assert task_for_rating(store, rating(at(first.ended_at, 5), session="nope")) is None


def run_rate(argv, capsys):
    code = main(["rate", *argv])
    return code, capsys.readouterr().out


def test_rate_with_session_prints_one_line_and_saves(home, make_tasks, capsys):
    Store().save_run(make_tasks(tasks=[{"prompts": [ASK], "files": ["a.py"]}]))
    code, out = run_rate(["7.5", "the", "diff", "was", "clean", "--session", "s1"], capsys)
    assert code == 0
    assert out == f"Rated 7.5 for api-server at {clock(NOW)}\n"
    row = Store().list_ratings()[0]
    assert (row["session_id"], row["grade"], row["note"], row["created_at"]) == (
        "s1",
        7.5,
        "the diff was clean",
        NOW.isoformat(),
    )


@pytest.mark.parametrize("text,value", [("7", 7.0), ("7.5", 7.5), ("7,5", 7.5), ("0", 0.0), ("10", 10.0)])
def test_rate_accepts_each_number_form(home, capsys, text, value):
    code, out = run_rate([text, "--session", "abc"], capsys)
    assert code == 0
    assert out == f"Rated {value:g} for abc at {clock(NOW)}\n"
    assert Store().list_ratings()[0]["grade"] == value


@pytest.mark.parametrize("text", ["11", "10.1", "-1", "abc", "nan", "inf", "7;5"])
def test_rate_rejects_bad_grades_with_exit_2_and_saves_nothing(home, capsys, text):
    code, out = run_rate([text, "--session", "abc"], capsys)
    assert code == 2
    assert len(out.splitlines()) == 1
    assert Store().list_ratings() == []


def test_rate_defaults_to_the_most_recent_transcript(home, tmp_path, make_session, capsys):
    projects = tmp_path / "projects"
    old = make_session(projects / "a", "older")
    new = make_session(projects / "b", "newer")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    code, out = run_rate(["8", "--projects-dir", str(projects)], capsys)
    assert code == 0
    assert out == f"Rated 8 for newer at {clock(NOW)}\n"
    assert Store().list_ratings()[0]["session_id"] == "newer"


def test_rate_without_any_transcript_saves_nothing(home, tmp_path, capsys):
    code, out = run_rate(["8", "--projects-dir", str(tmp_path / "empty")], capsys)
    assert code == 1
    assert len(out.splitlines()) == 1
    assert Store().list_ratings() == []


class FakeStdin:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text


class RaisingStdin:
    def read(self):
        raise AssertionError("stdin was read")


def payload(prompt, session="s9"):
    return json.dumps({"session_id": session, "prompt": prompt, "hook_event_name": "UserPromptSubmit"})


def hook_log(home):
    path = home / "hook.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.mark.parametrize(
    "prompt,grade,note",
    [
        ("kz 7", 7.0, ""),
        ("  kz 7.5  ", 7.5, ""),
        ("KZ 7,5 note text", 7.5, "note text"),
        ("Kz 9 the diff was clean\nand small", 9.0, "the diff was clean\nand small"),
    ],
)
def test_hook_prompt_saves_and_blocks_a_rating(home, capsys, prompt, grade, note):
    assert cli.hook_prompt(FakeStdin(payload(prompt))) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"decision": "block", "reason": f"kaizen: rated {grade:g}"}
    row = Store().list_ratings()[0]
    assert (row["session_id"], row["grade"], row["note"]) == ("s9", grade, note)
    assert hook_log(home) == []


@pytest.mark.parametrize(
    "prompt", ["kz", "kz later", "kzoo 7", "fix the bug", "please kz 7", "kz 7abc", "kz 11", "", "kz -1"]
)
def test_hook_prompt_lets_other_prompts_through_silently(home, capsys, prompt):
    assert cli.hook_prompt(FakeStdin(payload(prompt))) == 0
    assert capsys.readouterr() == ("", "")
    assert not (home / "ledger.db").exists() or Store().list_ratings() == []
    assert hook_log(home) == []


def test_hook_prompt_returns_at_once_under_internal_guard(home, monkeypatch, capsys):
    monkeypatch.setenv("KAIZEN_INTERNAL", "1")
    assert cli.hook_prompt(RaisingStdin()) == 0
    assert capsys.readouterr() == ("", "")
    assert not home.exists()


@pytest.mark.parametrize("text", ["not json", "[1]", '{"prompt": 5}', "{}", '{"prompt": "kz 7"}'])
def test_hook_prompt_bad_input_never_blocks(home, capsys, text):
    assert cli.hook_prompt(FakeStdin(text)) == 0
    assert capsys.readouterr() == ("", "")
    assert Store().list_ratings() == []


def test_hook_prompt_logs_exceptions_without_blocking(home, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Store, "save_rating", boom)
    assert cli.hook_prompt(FakeStdin(payload("kz 7"))) == 0
    assert capsys.readouterr() == ("", "")
    lines = hook_log(home)
    assert len(lines) == 1 and "RuntimeError" in lines[0]


def test_hook_prompt_command_never_fails(home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", RaisingStdin())
    assert main(["hook", "prompt"]) == 0
    assert capsys.readouterr() == ("", "")
    assert len(hook_log(home)) == 1


HOOKS = Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "hooks.json"


def prompt_filter_command():
    return json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]


def usable_bash():
    found = shutil.which("bash")
    if found is None or (sys.platform == "win32" and "git" not in found.lower()):
        pytest.skip("no POSIX bash to run the filter")
    return found


@pytest.fixture
def fake_kaizen(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "called"
    script = bin_dir / "kaizen"
    script.write_text(f'#!/bin/sh\ncat > "{marker.as_posix()}"\n', encoding="utf-8", newline="\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}")
    return marker


def run_filter(prompt):
    body = json.dumps({"session_id": "s", "prompt": prompt, "hook_event_name": "UserPromptSubmit"})
    done = subprocess.run(
        [usable_bash(), "-c", prompt_filter_command()], input=body, text=True, capture_output=True, check=False
    )
    return done


@pytest.mark.parametrize("prompt", ["kz 7", "KZ 7,5 note", "  kz 8", "\nkz 8", "kzoo"])
def test_prompt_filter_starts_kaizen_only_for_prompts_beginning_with_kz(fake_kaizen, prompt):
    done = run_filter(prompt)
    assert done.returncode == 0
    assert fake_kaizen.exists()
    assert json.loads(fake_kaizen.read_text(encoding="utf-8"))["prompt"] == prompt


@pytest.mark.parametrize("prompt", ["say hi", "please kz 7", "k z 7", "fix the kz parser"])
def test_prompt_filter_skips_kaizen_for_other_prompts(fake_kaizen, prompt):
    done = run_filter(prompt)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert not fake_kaizen.exists()


def test_hooks_json_keeps_the_session_end_hook():
    hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
    assert hooks["SessionEnd"][0]["hooks"][0]["command"] == "kaizen hook session-end"
