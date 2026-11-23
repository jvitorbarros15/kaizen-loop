import contextlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from kaizen import cli
from kaizen.cli import main
from kaizen.store import Store

GHP = "ghp_0123456789abcdefghijABCDEFGHIJ012345"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIZEN_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "kaizen 0.1.0"


def test_no_command_prints_help_and_returns_2(capsys):
    assert main([]) == 2


def test_import_records_then_skips(home, tmp_path, make_session, capsys):
    projects = tmp_path / "projects"
    make_session(projects / "a", "s1")
    make_session(projects / "b", "s2")
    assert main(["import", "--projects-dir", str(projects)]) == 0
    assert "Recorded 2 sessions (0 already in the store)" in capsys.readouterr().out
    assert main(["import", "--projects-dir", str(projects)]) == 0
    assert "Recorded 0 sessions (2 already in the store)" in capsys.readouterr().out


def test_import_all_rerecords(home, tmp_path, make_session, capsys):
    projects = tmp_path / "projects"
    make_session(projects / "a", "s1")
    make_session(projects / "b", "s2")
    main(["import", "--projects-dir", str(projects)])
    capsys.readouterr()
    store = Store()
    with contextlib.closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute("DELETE FROM tasks")
    assert main(["import", "--all", "--projects-dir", str(projects)]) == 0
    assert "Re-recorded 2 sessions" in capsys.readouterr().out
    assert len(store.list_tasks()) == 2


def test_import_all_still_skips_temporary_folder_sessions(home, tmp_path, make_session, capsys):
    projects = tmp_path / "projects"
    make_session(projects / "a", "s1")
    make_session(projects / "b", "s2", cwd=str(tmp_path / "scratch"))
    assert main(["import", "--all", "--projects-dir", str(projects)]) == 0
    out = capsys.readouterr().out
    assert "Re-recorded 1 sessions" in out and "temporary folders" in out
    assert Store().get_run("s2") is None


def test_import_limit(home, tmp_path, make_session, capsys):
    projects = tmp_path / "projects"
    for i in range(3):
        make_session(projects / "a", f"s{i}")
    main(["import", "--projects-dir", str(projects), "--limit", "1"])
    assert "Recorded 1 sessions" in capsys.readouterr().out


def test_record(home, tmp_path, make_session, capsys):
    path = make_session(tmp_path / "projects" / "a", "s1")
    assert main(["record", "--transcript", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "s1 recorded"


def test_audit_clean_and_dirty(home, tmp_path, make_session, capsys):
    path = make_session(tmp_path / "projects" / "a", "s1")
    main(["record", "--transcript", str(path)])
    capsys.readouterr()
    assert main(["audit"]) == 0
    assert "No known secret patterns in" in capsys.readouterr().out
    run_file = next((home / "runs").glob("*.json"))
    run_file.write_text(run_file.read_text(encoding="utf-8").replace("Fix the parser bug", GHP), encoding="utf-8")
    assert main(["audit"]) == 1
    assert "s1.json" in capsys.readouterr().out


def test_show_packet_prints_json_and_calls_nothing(home, tmp_path, make_session, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess used")

    monkeypatch.setattr("kaizen.external.subprocess.run", boom)
    path = make_session(tmp_path / "projects" / "a", "s1")
    main(["record", "--transcript", str(path)])
    capsys.readouterr()
    assert main(["score", "s1", "--show-packet"]) == 0
    out = capsys.readouterr().out
    assert "haiku" in out.split("{")[0]
    packet = json.loads(out[out.index("{") :])
    assert packet["task"] == "Fix the parser bug"
    assert Store().pending_scores() == ["s1"]


def test_show_packet_needs_session(home, capsys):
    assert main(["score", "--show-packet"]) == 2


def test_score_prints_line_per_session(home, tmp_path, make_session, capsys, monkeypatch):
    path = make_session(tmp_path / "projects" / "a", "s1", edits=True)
    main(["record", "--transcript", str(path)])
    capsys.readouterr()
    monkeypatch.setattr(cli, "RUNNER", lambda argv, stdin=None: (1, ""))
    assert main(["score", "--pending"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.split() == ["s1", "-", "weak", "none", "unavailable"]


def test_score_of_empty_session_abstains_without_a_model_call(home, tmp_path, make_session, capsys, monkeypatch):
    path = make_session(tmp_path / "projects" / "a", "s1")
    main(["record", "--transcript", str(path)])
    capsys.readouterr()

    def boom(argv, stdin=None):
        raise AssertionError("model called")

    monkeypatch.setattr(cli, "RUNNER", boom)
    assert main(["score", "--pending"]) == 0
    assert Store().get_score("s1")["verdict"]["abstained"] is True


def test_report_and_refresh_on_empty_store(home, capsys):
    assert main(["report"]) == 0
    assert "kaizen import" in capsys.readouterr().out
    assert main(["refresh"]) == 0


def test_report_leads_with_tasks_inside_the_day_window(home, tmp_path, make_session, capsys):
    started = datetime.now(UTC).strftime("%Y-%m-%d")
    for sid, day in (("new", started), ("old", "2020-01-01")):
        main(["record", "--transcript", str(make_session(tmp_path / "p", sid, started=day, edits=True))])
    capsys.readouterr()
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("kaizen report - tasks from the last 14 days (1 task in 1 session)")
    assert main(["report", "--days", "100000"]) == 0
    assert "(2 tasks in 2 sessions)" in capsys.readouterr().out


def save_corrected_scores(wording):
    store = Store()
    for i, text in enumerate(wording):
        store.save_score(
            f"s{i}",
            {
                "score": {"baseline": "insufficient", "evidence": "none", "total": None},
                "signals": {"corrections": [text]},
                "verdict": {},
                "stats": {},
                "corrections_known": True,
                "repo": "app",
                "started_at": f"2026-11-0{i + 1}T10:00:00Z",
            },
        )


def refuse(argv, stdin=None):
    raise AssertionError("model called")


def test_report_no_model_calls_no_runner_and_matches_exactly(home, capsys, monkeypatch):
    save_corrected_scores(["Run the tests first", "run the tests first "])
    monkeypatch.setattr(cli, "RUNNER", refuse)
    assert main(["report", "--no-model"]) == 0
    out = capsys.readouterr().out
    assert "2x in 2 sessions   run the tests first" in out and "exact wording" in out


def test_report_with_corrections_disabled_calls_no_runner(home, capsys, monkeypatch):
    save_corrected_scores(["Run the tests first", "run the tests first"])
    (home / "config.toml").write_text("[corrections]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setattr(cli, "RUNNER", refuse)
    assert main(["report"]) == 0
    assert "What you keep correcting" in capsys.readouterr().out


def test_report_groups_corrections_with_one_model_call(home, capsys, monkeypatch):
    save_corrected_scores(["run the tests first", "you did not run the tests", "use tabs"])
    calls = []
    answer = json.dumps([{"label": "skips the tests", "members": [1, 2]}])

    def runner(argv, stdin=None):
        calls.append(stdin)
        return 0, json.dumps({"result": answer})

    monkeypatch.setattr(cli, "RUNNER", runner)
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "2x in 2 sessions   skips the tests" in out and "exact wording" not in out
    assert main(["report"]) == 0
    assert len(calls) == 1


def test_calibrate_saves_blind_grades(home, tmp_path, capsys, monkeypatch, make_session):
    store = Store()
    monkeypatch.setattr(cli, "now", lambda: datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    for sid in ("a", "b", "c"):
        path = make_session(tmp_path / "projects" / "x", sid, prompts=[f"task {sid}"], started="2026-11-23")
        main(["record", "--transcript", str(path)])
        verdict = {"quality": 7.3, "reasons": ["did_what_was_asked: matched the ask"], "backend": "haiku"}
        summary = next(t for t in store.list_tasks() if t.session_id == sid)
        saved = {
            "verdict": verdict, "signals": {"test_runs": []}, "corrections_known": False, "session_id": sid,
            "idx": 0, "repo": "x", "title": summary.title, "started_at": summary.started_at,
            "ended_at": summary.ended_at, "tool_calls": summary.tool_calls, "files_edited": 0,
        }
        store.save_task_score(summary.key, sid, 0, saved)
    capsys.readouterr()
    answers = iter(["8", "s", "q"])
    shown_before_grading = []

    def read_line(prompt):
        shown_before_grading.append(capsys.readouterr().out)
        return next(answers)

    monkeypatch.setattr(cli, "read_line", read_line)
    assert main(["calibrate", "--n", "3"]) == 0
    out = capsys.readouterr().out
    first, second, third = shown_before_grading
    assert "7.3" not in first and "matched the ask" not in first
    assert "You 8.0   Judge 7.3" in second and "matched the ask" in second
    assert "Judge 7.3" not in third and "matched the ask" not in third
    assert len(store.human_grades()) == 1
    assert store.human_grades()[0][1] == 8.0
    assert "Judge agrees with you on 1 of 1 runs" in out


def test_score_line_tells_abstained_from_unavailable():
    from kaizen.cli import _score_line

    score = {"total": None, "strength": "weak", "evidence": "none"}
    abstained = {"score": score, "verdict": {"backend": "haiku", "quality": None, "abstained": True}}
    missing = {"score": score, "verdict": {"backend": None, "quality": None, "abstained": False}}
    assert _score_line("s1", abstained).endswith("haiku (abstained)")
    assert _score_line("s1", missing).endswith("unavailable")


class FakeStdin:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text


class RaisingStdin:
    def read(self):
        raise AssertionError("stdin was read")


class Spawner:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error


def hook_log_lines(home):
    path = home / "hook.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def run_hook(text, spawn):
    return cli.hook_session_end(FakeStdin(text), spawn)


@pytest.fixture
def transcript(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_hook_spawns_detached_record(home, transcript, capsys, monkeypatch):
    monkeypatch.delenv("KAIZEN_INTERNAL", raising=False)
    spawn = Spawner()
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "x", "extra": [1]})
    assert run_hook(payload, spawn) == 0
    assert len(spawn.calls) == 1
    argv, kwargs = spawn.calls[0]
    assert argv[0] == sys.executable
    assert argv[1:] == ["-m", "kaizen.cli", "record", "--transcript", str(transcript), "--skip-temp"]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    if sys.platform == "win32":
        assert kwargs["creationflags"] == (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
        assert "start_new_session" not in kwargs
    else:
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs
    assert capsys.readouterr() == ("", "")
    assert hook_log_lines(home) == []


def test_hook_internal_guard_does_not_read_stdin(home, monkeypatch, capsys):
    monkeypatch.setenv("KAIZEN_INTERNAL", "1")
    spawn = Spawner()
    assert cli.hook_session_end(RaisingStdin(), spawn) == 0
    assert spawn.calls == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "text",
    ["not json", "[1, 2]", "{}", '{"transcript_path": 5}', '{"transcript_path": "/no/such/file.jsonl"}'],
)
def test_hook_bad_input_logs_one_line(home, text, capsys, monkeypatch):
    monkeypatch.delenv("KAIZEN_INTERNAL", raising=False)
    spawn = Spawner()
    assert run_hook(text, spawn) == 0
    assert spawn.calls == []
    assert capsys.readouterr() == ("", "")
    assert len(hook_log_lines(home)) == 1


def test_hook_spawn_failure_logs_one_line(home, transcript, capsys, monkeypatch):
    monkeypatch.delenv("KAIZEN_INTERNAL", raising=False)
    spawn = Spawner(OSError("cannot start"))
    assert run_hook(json.dumps({"transcript_path": str(transcript)}), spawn) == 0
    assert capsys.readouterr() == ("", "")
    lines = hook_log_lines(home)
    assert len(lines) == 1
    assert "OSError" in lines[0]


def test_hook_log_message_is_cut(home, monkeypatch):
    monkeypatch.delenv("KAIZEN_INTERNAL", raising=False)
    assert run_hook("x" * 1000, Spawner()) == 0
    assert len(hook_log_lines(home)[0]) < 300


def test_hook_command_never_prints_or_fails(home, monkeypatch, capsys):
    monkeypatch.delenv("KAIZEN_INTERNAL", raising=False)
    monkeypatch.setattr(sys, "stdin", RaisingStdin())
    assert main(["hook", "session-end"]) == 0
    assert capsys.readouterr() == ("", "")
    assert len(hook_log_lines(home)) == 1


def test_record_failure_logs_and_returns_1(home, tmp_path, capsys):
    assert main(["record", "--transcript", str(tmp_path / "missing.jsonl")]) == 1
    assert capsys.readouterr() == ("", "")
    assert len(hook_log_lines(home)) == 1


def test_hook_log_message_is_redacted(home):
    cli.log_hook("RuntimeError", f"record failed: token {GHP} in path")
    text = (home / "hook.log").read_text(encoding="utf-8")
    assert GHP not in text
    assert "record failed" in text


def test_record_skip_temp_ignores_scratch_sessions(home, tmp_path, make_session, capsys):
    path = make_session(tmp_path / "projects" / "a", "s1", cwd=str(tmp_path / "scratch"))
    assert main(["record", "--transcript", str(path), "--skip-temp"]) == 0
    assert capsys.readouterr() == ("", "")
    assert Store().get_run("s1") is None


def test_record_without_flag_records_temp_sessions(home, tmp_path, make_session, capsys):
    path = make_session(tmp_path / "projects" / "a", "s1", cwd=str(tmp_path / "scratch"))
    assert main(["record", "--transcript", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "s1 recorded"
    assert Store().get_run("s1") is not None


def test_record_skip_temp_still_records_normal_sessions(home, tmp_path, make_session, capsys):
    path = make_session(tmp_path / "projects" / "a", "s1")
    assert main(["record", "--transcript", str(path), "--skip-temp"]) == 0
    assert capsys.readouterr().out.strip() == "s1 recorded"
