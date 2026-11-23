import json

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
    path = make_session(tmp_path / "projects" / "a", "s1")
    main(["record", "--transcript", str(path)])
    capsys.readouterr()
    monkeypatch.setattr(cli, "RUNNER", lambda argv, stdin=None: (1, ""))
    assert main(["score", "--pending"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.split() == ["s1", "-", "weak", "none", "unavailable"]


def test_report_and_refresh_on_empty_store(home, capsys):
    assert main(["report"]) == 0
    assert "kaizen import" in capsys.readouterr().out
    assert main(["refresh"]) == 0


def test_calibrate_saves_blind_grades(home, tmp_path, capsys, monkeypatch, make_session):
    store = Store()
    for sid in ("a", "b", "c"):
        path = make_session(tmp_path / "projects" / "x", sid, prompts=[f"task {sid}"])
        main(["record", "--transcript", str(path)])
        verdict = {"quality": 7.3, "reasons": ["did_what_was_asked: matched the ask"], "backend": "haiku"}
        store.save_score(sid, {"score": {"quality": 7.3}, "signals": {"test_runs": []}, "verdict": verdict, "corrections_known": False})
    capsys.readouterr()
    answers = iter(["8", "s", "q"])
    monkeypatch.setattr(cli, "read_line", lambda prompt: next(answers))
    assert main(["calibrate", "--n", "3"]) == 0
    out = capsys.readouterr().out
    assert "7.3" not in out
    assert "matched the ask" in out
    assert len(store.human_grades()) == 1
    assert store.human_grades()[0][1] == 8.0
    assert "Judge agrees with you on 1 of 1 runs" in out
