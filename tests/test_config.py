from kaizen.config import DEFAULTS, load_config


def test_defaults_when_no_config(tmp_path):
    assert load_config(tmp_path)["score"] == {"quality": 0.4, "efficiency": 0.3, "cost": 0.3}


def test_file_overriding_one_key_keeps_the_rest(tmp_path):
    (tmp_path / "config.toml").write_text("[score]\nquality = 0.6\n", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg["score"] == {"quality": 0.6, "efficiency": 0.3, "cost": 0.3}
    assert cfg["budget"] == {"tokens_per_day": 2000000}


def test_top_level_scalar_in_file_is_ignored(tmp_path):
    (tmp_path / "config.toml").write_text("debug = true\n[score]\nquality = 0.6\n", encoding="utf-8")
    assert load_config(tmp_path)["score"]["quality"] == 0.6


def test_mutating_result_does_not_change_later_loads(tmp_path):
    cfg = load_config(tmp_path)
    cfg["score"]["quality"] = 9
    cfg["judge"]["backends"].append("other")
    assert load_config(tmp_path) == DEFAULTS
    assert DEFAULTS["judge"]["backends"] == ["codex", "haiku"]


def test_corrections_enabled_by_default(tmp_path):
    assert load_config(tmp_path)["corrections"] == {"enabled": True}
