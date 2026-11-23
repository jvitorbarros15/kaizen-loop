from kaizen.record.model import RunRecord, ToolCall, Usage
from kaizen.redact import redact_obj
from kaizen.store import Store, kaizen_home

FAKE_GH = "ghp_0123456789abcdefghijABCDEFGHIJ012345"
FAKE_ANT = "sk-ant-FAKEFAKEFAKE123456"


def make_record(output_excerpt="", **overrides):
    fields = {
        "session_id": "s1",
        "repo": "acme/app",
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:10:00Z",
        "usage_by_model": {"claude-test": Usage(input=10, cache_write=2, cache_read=3, output=5)},
        "tool_calls": [
            ToolCall(
                id="toolu_01AbCdEfGhIjKlMnOpQrStUv",
                name="Bash",
                input={"command": "ls"},
                output_excerpt=output_excerpt,
                timestamp="2026-01-01T00:01:00Z",
                exit_code=0,
            )
        ],
        "user_messages": ["hello"],
    }
    fields.update(overrides)
    return RunRecord(**fields)


def blob(root):
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_no_secret_reaches_disk(tmp_path):
    rec = make_record(output_excerpt="token ghp_0123456789abcdefghijABCDEFGHIJ012345")
    s = Store(tmp_path)
    s.save_run(rec)
    blob = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    assert b"ghp_0123456789" not in blob
    assert s.audit() == []

def test_save_twice_is_one_run(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record())
    s.save_run(make_record())
    assert len(s.list_runs()) == 1


def test_secret_in_repo_never_reaches_disk(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record(repo=FAKE_GH))
    assert FAKE_GH.encode() not in blob(tmp_path)
    assert s.audit() == []


def test_secret_in_user_message_never_reaches_disk(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record(user_messages=[f"use this key {FAKE_ANT} please"]))
    assert FAKE_ANT.encode() not in blob(tmp_path)
    assert s.audit() == []


def test_secret_in_score_reasons_never_reaches_disk(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record())
    s.save_score("s1", {"quality": 0.9, "reasons": [f"agent echoed {FAKE_GH}"]})
    assert FAKE_GH.encode() not in blob(tmp_path)
    assert s.audit() == []


def test_second_save_replaces_first(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record(repo="acme/old"))
    s.save_run(make_record(repo="acme/new"))
    runs = s.list_runs()
    assert [r.repo for r in runs] == ["acme/new"]
    assert s.get_run("s1").repo == "acme/new"


def test_get_run_round_trip_equals_redacted_record(tmp_path):
    rec = make_record(output_excerpt=f"key {FAKE_GH}", user_messages=["hi", FAKE_ANT])
    s = Store(tmp_path)
    s.save_run(rec)
    assert s.get_run("s1") == RunRecord.from_dict(redact_obj(rec.to_dict()))


def test_missing_run_returns_none(tmp_path):
    assert Store(tmp_path).get_run("nope") is None


def test_missing_score_returns_none(tmp_path):
    assert Store(tmp_path).get_score("nope") is None


def test_score_upsert(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record())
    s.save_score("s1", {"quality": 0.2})
    s.save_score("s1", {"quality": 0.8})
    assert s.get_score("s1") == {"quality": 0.8}


def test_list_runs_order_repo_filter_and_limit(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record(session_id="a", started_at="2026-01-01T00:00:00Z"))
    s.save_run(make_record(session_id="b", started_at="2026-01-03T00:00:00Z"))
    s.save_run(make_record(session_id="c", started_at="2026-01-02T00:00:00Z", repo="other/repo"))
    assert [r.session_id for r in s.list_runs()] == ["b", "c", "a"]
    assert [r.session_id for r in s.list_runs(repo="acme/app")] == ["b", "a"]
    assert [r.session_id for r in s.list_runs(limit=1)] == ["b"]


def test_hostile_session_id_stays_inside_runs(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record(session_id="../../evil"))
    runs = tmp_path / "runs"
    assert [p.name for p in runs.iterdir()] == ["______evil.json"]
    assert not (tmp_path.parent / "evil.json").exists()
    assert s.get_run("../../evil").session_id == "../../evil"


def test_audit_reports_secret_written_into_run_file(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record())
    run_file = tmp_path / "runs" / "s1.json"
    run_file.write_text(
        run_file.read_text(encoding="utf-8") + f'\n"leak": "{FAKE_GH}"',
        encoding="utf-8",
    )
    assert ("s1.json", "github_token") in s.audit()


def test_audit_suspects_flags_random_token(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record(output_excerpt="id Zx9kQ2mP7vLr4TnW8bYc3HdJ end"))
    tokens = [t for _, t in s.audit_suspects()]
    assert tokens == ["Zx9k…(24 chars)"]


def test_corrupt_run_file_is_skipped_not_fatal(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record())
    next(s.runs_dir.glob("*.json")).write_text("{not json", encoding="utf-8")
    assert s.list_runs() == []


def test_file_count_ignores_leftover_temp_files(tmp_path):
    s = Store(tmp_path)
    s.save_run(make_record())
    (s.runs_dir / "x.json.123.tmp").write_text("{}", encoding="utf-8")
    assert s.file_count() == 2
    assert list(s.runs_dir.glob("*.tmp")) != []


def test_audit_suspects_ignores_known_shapes(tmp_path):
    s = Store(tmp_path)
    s.save_run(
        make_record(
            output_excerpt=(
                "sha 0123456789abcdef0123456789abcdef01234567 "
                "tag [REDACTED:github_token]"
            )
        )
    )
    tokens = [t for _, t in s.audit_suspects()]
    assert not any(t.startswith("toolu_") for t in tokens)
    assert not any(t.startswith("0123456789ab") for t in tokens)
    assert not any("REDACTED" in t for t in tokens)


def test_human_grades_upsert_and_order(tmp_path):
    s = Store(tmp_path)
    s.save_human_grade("a", 0.5)
    s.save_human_grade("b", 0.9)
    s.save_human_grade("a", 0.7)
    assert s.human_grades() == [("b", 0.9), ("a", 0.7)]


def test_kaizen_home_honours_env(tmp_path, monkeypatch):
    target = tmp_path / "kh"
    monkeypatch.setenv("KAIZEN_HOME", str(target))
    assert kaizen_home() == target
    assert target.is_dir()


def test_file_count_and_clean_audit_on_empty_store(tmp_path):
    s = Store(tmp_path)
    assert s.file_count() == 1
    assert s.audit() == []
    assert s.audit_suspects() == []
