import json
from datetime import datetime

import pytest

from kaizen import cli
from kaizen.cli import main
from kaizen.config import load_config
from kaizen.judge.rubric import RUBRIC_ITEMS
from kaizen.pipeline import build_task_packet, score_task
from kaizen.store import Store

ASK = "please fix the navbar spacing on mobile screens"
ASK2 = "now migrate the session table to the new schema"
FOLLOW = "the migration also needs to cover the audit table"


def judge_output(score=8):
    items = {name: {"score": score, "reason": f"{name} ok"} for name in RUBRIC_ITEMS}
    return json.dumps({"result": json.dumps({"items": items})})


class FakeRunner:
    def __init__(self, corrections=("covers the audit table",), judge=True):
        self.corrections = corrections
        self.judge = judge
        self.packets = []
        self.correction_calls = 0

    def __call__(self, argv, stdin=None):
        if (stdin or "").startswith("<messages>"):
            self.correction_calls += 1
            if self.corrections is None:
                return 1, ""
            return 0, json.dumps({"result": json.dumps(list(self.corrections))})
        self.packets.append(stdin)
        if not self.judge:
            return 1, ""
        return 0, judge_output()


def never(argv, stdin=None):
    raise AssertionError(f"runner called: {argv[0]}")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store")


@pytest.fixture
def config(tmp_path):
    return load_config(tmp_path / "cfg")


@pytest.fixture
def seeded(store, make_tasks):
    store.save_run(
        make_tasks(
            tasks=[
                {"prompts": [ASK], "files": ["nav.py"], "test": True},
                {"prompts": [ASK2, FOLLOW], "files": ["session.py"]},
                {"prompts": ["a third request about something else entirely"]},
            ]
        )
    )
    return store


def test_score_task_grades_only_that_tasks_edits(seeded, config):
    runner = FakeRunner()
    saved = score_task("s1", 1, seeded, config, runner)
    assert len(runner.packets) == 1
    sent = runner.packets[0]
    assert "session.py" in sent and "nav.py" not in sent
    assert ASK2 in sent and ASK not in sent
    assert saved["verdict"]["quality"] == 8.0
    assert saved["session_id"] == "s1" and saved["idx"] == 1
    assert saved["kind"] == "edited_unchecked" and saved["files_edited"] == 1
    assert saved["repo"] == "api-server" and saved["title"] == ASK2
    assert saved["tool_calls"] == 1 and saved["last_test"] == "none"
    assert saved["started_at"] and saved["ended_at"] and "score" not in saved
    key = next(t.key for t in seeded.list_tasks() if t.index == 1)
    assert seeded.get_task_score(key) == saved


def test_corrections_called_only_with_two_or_more_prompts(seeded, config):
    runner = FakeRunner()
    first = score_task("s1", 0, seeded, config, runner)
    assert runner.correction_calls == 0
    assert first["corrections_known"] is True and first["signals"]["corrections"] == []
    second = score_task("s1", 1, seeded, config, runner)
    assert runner.correction_calls == 1
    assert second["corrections_known"] is True
    assert second["signals"]["corrections"] == ["covers the audit table"]
    assert '"corrections": ["covers the audit table"]' in runner.packets[-1]


def test_unknown_corrections_reach_the_packet_as_null(seeded, config):
    runner = FakeRunner(corrections=None)
    saved = score_task("s1", 1, seeded, config, runner)
    assert saved["corrections_known"] is False
    assert '"corrections": null' in runner.packets[0]


def test_disabled_corrections_are_not_extracted(seeded, config):
    config["corrections"]["enabled"] = False
    runner = FakeRunner()
    saved = score_task("s1", 1, seeded, config, runner)
    assert runner.correction_calls == 0 and saved["corrections_known"] is False
    assert '"corrections": null' in runner.packets[0]


def test_missing_run_or_index_returns_none(seeded, config):
    assert score_task("nope", 0, seeded, config, never) is None
    assert score_task("s1", 3, seeded, config, never) is None
    assert score_task("s1", -1, seeded, config, never) is None
    assert build_task_packet("nope", 0, seeded, config) is None
    assert build_task_packet("s1", 3, seeded, config) is None


def test_model_failure_does_not_raise_and_is_saved(seeded, config):
    saved = score_task("s1", 0, seeded, config, FakeRunner(judge=False))
    assert saved["verdict"]["quality"] is None and saved["verdict"]["backend"] is None
    key = next(t.key for t in seeded.list_tasks() if t.index == 0)
    assert seeded.get_task_score(key) is not None


def test_task_without_edits_abstains_without_a_model_call(seeded, config):
    saved = score_task("s1", 2, seeded, config, never)
    assert saved["verdict"]["abstained"] is True


def test_build_task_packet_calls_no_runner(seeded, config, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess used")

    monkeypatch.setattr("kaizen.external.subprocess.run", boom)
    packet, backends = build_task_packet("s1", 1, seeded, config)
    assert packet["task"] == ASK2 and packet["changed_files"] == ["session.py"]
    assert packet["corrections"] is None and backends == ["haiku"]
    assert seeded.list_task_scores() == []


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIZEN_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def local_date(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")


def test_score_tasks_prints_a_line_per_task_and_the_pending_count(home, make_tasks, capsys, monkeypatch):
    store = Store()
    store.save_run(
        make_tasks(
            tasks=[
                {"prompts": [ASK], "files": ["nav.py"], "test": True},
                {"prompts": [ASK2], "files": ["session.py"]},
                {"prompts": ["a third request about something else entirely"], "files": ["x.py"]},
            ]
        )
    )
    monkeypatch.setattr(cli, "RUNNER", FakeRunner())
    assert main(["score", "--tasks", "--limit", "2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    third = next(t for t in store.list_tasks() if t.index == 2)
    assert lines[0] == f"{local_date(third.started_at)}  api-server  8.0  haiku  {third.title}"
    assert ASK2 in lines[1]
    assert lines[2] == "Graded 2 tasks (1 still pending)"
    assert main(["score", "--tasks"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Graded 1 tasks (0 still pending)"
    assert main(["score", "--tasks"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Graded 0 tasks (0 still pending)"]


def test_score_tasks_shows_dash_and_labels_and_cuts_titles(home, make_tasks, capsys, monkeypatch):
    long = "word " * 60
    Store().save_run(make_tasks(tasks=[{"prompts": [long], "files": ["a.py"]}]))
    monkeypatch.setattr(cli, "RUNNER", lambda argv, stdin=None: (1, ""))
    assert main(["score", "--tasks"]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert "  -  unavailable  " in line
    assert len(line) <= 110 and line.endswith("...")


def test_score_without_tasks_flag_is_unchanged(home, tmp_path, make_session, capsys, monkeypatch):
    path = make_session(tmp_path / "projects" / "a", "s1", edits=True)
    main(["record", "--transcript", str(path)])
    capsys.readouterr()
    monkeypatch.setattr(cli, "RUNNER", lambda argv, stdin=None: (1, ""))
    assert main(["score", "--pending"]) == 0
    assert capsys.readouterr().out.strip().split() == ["s1", "-", "weak", "none", "unavailable"]
    assert Store().list_task_scores() == []


def test_show_packet_with_task_prints_that_tasks_packet_and_calls_nothing(home, make_tasks, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess used")

    monkeypatch.setattr("kaizen.external.subprocess.run", boom)
    Store().save_run(
        make_tasks(
            tasks=[
                {"prompts": [ASK], "files": ["nav.py"]},
                {"prompts": [ASK2], "files": ["session.py"]},
            ]
        )
    )
    assert main(["score", "s1", "--show-packet", "--task", "1"]) == 0
    out = capsys.readouterr().out
    assert "haiku" in out.split("{")[0]
    packet = json.loads(out[out.index("{") :])
    assert packet["task"] == ASK2 and packet["changed_files"] == ["session.py"]
    assert main(["score", "s1", "--show-packet"]) == 0
    whole = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert whole["task"] == ASK and sorted(whole["changed_files"]) == ["nav.py", "session.py"]
    assert main(["score", "s1", "--show-packet", "--task", "9"]) == 1
    assert main(["score", "--show-packet", "--task", "0"]) == 2
    assert Store().list_task_scores() == []


def test_score_tasks_regrades_old_rubric_grades_and_counts_them(home, make_tasks, capsys, monkeypatch):
    store = Store()
    store.save_run(make_tasks(tasks=[{"prompts": [ASK], "files": ["nav.py"]}, {"prompts": [ASK2], "files": ["s.py"]}]))
    monkeypatch.setattr(cli, "RUNNER", FakeRunner())
    assert main(["score", "--tasks"]) == 0
    capsys.readouterr()
    old = next(t for t in store.list_tasks() if t.index == 0)
    saved = store.get_task_score(old.key)
    saved["verdict"]["rubric_version"] = 1
    saved["verdict"]["quality"] = 2.0
    store.save_task_score(old.key, old.session_id, old.index, saved)
    assert main(["score", "--tasks"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "Graded 1 tasks, 1 of them regrades (0 still pending)"
    assert store.get_task_score(old.key)["verdict"]["quality"] == 8.0
    assert store.get_task_score(old.key)["verdict"]["rubric_version"] == 2
    assert main(["score", "--tasks"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Graded 0 tasks (0 still pending)"]
