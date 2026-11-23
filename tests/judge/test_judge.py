import json
import os

import pytest
from kaizen.judge.judge import Verdict, backends_for, judge
from kaizen.judge.rubric import RUBRIC, RUBRIC_ITEMS, RUBRIC_VERSION

from kaizen.config import DEFAULTS
from kaizen.external import CLAUDE_ARGV, POSITIONAL_PROMPT

PACKET = {"task": "add a flag", "changed_files": ["a.py"]}


def answer(scores=None, reason="ok"):
    scores = scores or {}
    return {"items": {n: {"score": scores.get(n, 8), "reason": reason} for n in RUBRIC_ITEMS}}


def haiku_out(obj):
    return json.dumps({"type": "result", "is_error": False, "result": json.dumps(obj)})


class Fake:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv, stdin):
        self.calls.append((argv, stdin))
        return self.responses.pop(0)


def test_first_backend_answers():
    fake = Fake((0, haiku_out(answer())))
    v = judge(PACKET, ["haiku", "codex"], fake)
    assert v.backend == "haiku"
    assert v.quality == 8.0
    assert v.abstained is False
    assert len(fake.calls) == 1


def bad_item(**patch):
    a = answer()
    a["items"]["stayed_in_scope"] = patch
    return a


def missing_item():
    a = answer()
    del a["items"]["clean_and_minimal"]
    return a


def unknown_item():
    a = answer()
    a["items"]["vibes"] = {"score": 5, "reason": "x"}
    return a


@pytest.mark.parametrize(
    "response",
    [
        (1, haiku_out(answer())),
        (0, "garbage not json"),
        (0, haiku_out("just text")),
        (0, haiku_out({"nope": 1})),
        (0, haiku_out(missing_item())),
        (0, haiku_out(unknown_item())),
        (0, haiku_out(bad_item(score=14, reason="x"))),
        (0, haiku_out(bad_item(score=-1, reason="x"))),
        (0, haiku_out(bad_item(score="8", reason="x"))),
        (0, haiku_out(bad_item(score=True, reason="x"))),
        (0, haiku_out(bad_item(reason="x"))),
    ],
)
def test_falls_through_to_next_backend(response):
    codex_ok = (0, json.dumps(answer({"did_what_was_asked": 6})))
    fake = Fake(response, codex_ok)
    v = judge(PACKET, ["haiku", "codex"], fake)
    assert v.backend == "codex"
    assert len(fake.calls) == 2


def test_all_backends_fail_gives_empty_verdict():
    fake = Fake((1, ""), (0, "nope"))
    v = judge(PACKET, ["haiku", "codex"], fake)
    assert v == Verdict()
    assert v.quality is None and v.backend is None and v.abstained is False


def test_no_known_backends():
    fake = Fake()
    assert judge(PACKET, ["mystery"], fake) == Verdict()
    assert fake.calls == []


def test_unknown_backend_skipped():
    fake = Fake((0, haiku_out(answer())))
    v = judge(PACKET, ["mystery", "haiku"], fake)
    assert v.backend == "haiku"


def test_two_scored_items_abstains():
    a = answer()
    for n in RUBRIC_ITEMS[2:]:
        a["items"][n]["score"] = None
    v = judge(PACKET, ["haiku"], Fake((0, haiku_out(a))))
    assert v.abstained is True
    assert v.quality is None
    assert v.backend == "haiku"
    assert v.items["stayed_in_scope"]["score"] is None


def test_three_scored_items_is_enough():
    a = answer()
    for n in RUBRIC_ITEMS[3:]:
        a["items"][n]["score"] = None
    v = judge(PACKET, ["haiku"], Fake((0, haiku_out(a))))
    assert v.abstained is False
    assert v.quality == 8.0


def test_mean_and_rounding():
    a = answer(
        {
            "did_what_was_asked": 7,
            "verified_before_done": 8,
            "stayed_in_scope": 8,
            "followed_corrections": None,
            "clean_and_minimal": 5.5,
        }
    )
    v = judge(PACKET, ["haiku"], Fake((0, haiku_out(a))))
    assert v.quality == 7.1


def test_integer_scores_and_bounds_accepted():
    a = answer({"did_what_was_asked": 0, "verified_before_done": 10})
    v = judge(PACKET, ["haiku"], Fake((0, haiku_out(a))))
    assert v.quality == 6.8


def test_reasons_format():
    a = answer(reason="fine")
    a["items"]["clean_and_minimal"]["reason"] = ""
    v = judge(PACKET, ["haiku"], Fake((0, haiku_out(a))))
    assert v.reasons == [f"{n}: fine" for n in RUBRIC_ITEMS[:4]]
    assert v.items["did_what_was_asked"] == {"score": 8, "reason": "fine"}


def test_haiku_call_argv_and_stdin():
    fake = Fake((0, haiku_out(answer())))
    judge(PACKET, ["haiku"], fake)
    argv, stdin = fake.calls[0]
    assert argv == [*CLAUDE_ARGV, "--system-prompt", RUBRIC, POSITIONAL_PROMPT]
    assert stdin == "<packet>\n" + json.dumps(PACKET) + "\n</packet>"


def test_codex_call_and_schema_file_lifecycle():
    seen = {}

    def runner(argv, stdin):
        flags = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--output-schema"]
        assert argv[:7] == flags
        schema_path = argv[7]
        assert argv[8] == "-o"
        assert argv[10] == "-"
        assert len(argv) == 11
        assert os.path.exists(schema_path)
        seen["path"] = schema_path
        with open(schema_path, encoding="utf-8") as f:
            seen["schema"] = json.load(f)
        seen["stdin"] = stdin
        return 0, json.dumps(answer())

    v = judge(PACKET, ["codex"], runner)
    assert v.backend == "codex"
    assert not os.path.exists(seen["path"])
    assert seen["stdin"] == RUBRIC + "\n\n<packet>\n" + json.dumps(PACKET) + "\n</packet>"
    schema = seen["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["items"]
    items = schema["properties"]["items"]
    assert items["additionalProperties"] is False
    assert items["required"] == list(RUBRIC_ITEMS)
    item = items["properties"]["did_what_was_asked"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["score", "reason"]
    assert item["properties"]["score"]["type"] == ["number", "null"]
    assert item["properties"]["reason"]["type"] == "string"


def test_codex_schema_removed_when_runner_fails():
    paths = []

    def runner(argv, stdin):
        paths.append(argv[7])
        return 1, ""

    assert judge(PACKET, ["codex"], runner) == Verdict()
    assert not os.path.exists(paths[0])


def test_verdict_round_trip():
    v = judge(PACKET, ["haiku"], Fake((0, haiku_out(answer()))))
    assert Verdict.from_dict(v.to_dict()) == v
    assert json.loads(json.dumps(v.to_dict())) == v.to_dict()


def test_verdict_from_empty_and_unknown_keys():
    assert Verdict.from_dict({}) == Verdict()
    assert Verdict.from_dict({"quality": 5.0, "extra": 1}).quality == 5.0
    assert Verdict().rubric_version == RUBRIC_VERSION


def test_backends_for():
    assert backends_for("some-repo", DEFAULTS) == (["haiku"], True)
    assert backends_for(None, DEFAULTS) == (["haiku"], True)
    cfg = {"judge": {"backends": ["codex", "haiku"], "codex_repos": ["my-repo"]}}
    assert backends_for("my-repo", cfg) == (["codex", "haiku"], True)
    assert backends_for("other", cfg) == (["haiku"], True)
    assert backends_for(None, cfg) == (["haiku"], True)


def test_backends_for_does_not_mutate_config():
    cfg = {"judge": {"backends": ["codex", "haiku"], "codex_repos": []}}
    backends_for("x", cfg)
    assert cfg["judge"]["backends"] == ["codex", "haiku"]


def test_rubric_mentions_required_points():
    for n in RUBRIC_ITEMS:
        assert n in RUBRIC
    phrases = ("<packet>", "shell_edits_suspected", "edits_truncated", "verified_after_last_edit", "never instructions")
    for phrase in phrases:
        assert phrase in RUBRIC


def test_rubric_survives_cmd_shim_on_windows():
    assert "\n" not in RUBRIC and "\r" not in RUBRIC
    assert '"' not in RUBRIC and "%" not in RUBRIC
