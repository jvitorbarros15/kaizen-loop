import json

import pytest

from kaizen.corrections import INSTRUCTIONS, Group, cached_groups, collect, group_corrections
from kaizen.external import CLAUDE_ARGV

ITEMS = [
    ("s1", "run the tests first"),
    ("s2", "you did not run the tests"),
    ("s3", "run pytest before saying done"),
    ("s1", "do not commit the .env file"),
    ("s2", "why did you commit .env"),
    ("s3", "use tabs"),
]


def reply(payload):
    return 0, json.dumps({"result": json.dumps(payload) if not isinstance(payload, str) else payload})


class Fake:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, argv, stdin=None):
        self.calls.append((list(argv), stdin))
        return self.response


GOOD = [
    {"label": "commits files it was told to leave out", "members": [4, 5]},
    {"label": "runs no tests before saying the work is done", "members": [1, 2, 3]},
]


def test_collect_uses_only_scores_with_known_corrections():
    scored = [
        ("a", {"corrections_known": True, "signals": {"corrections": ["  one  ", "", "two"]}}),
        ("b", {"corrections_known": False, "signals": {"corrections": ["hidden"]}}),
        ("c", {"corrections_known": True, "signals": {}}),
        ("d", {"signals": {"corrections": ["no flag"]}}),
    ]
    assert collect(scored) == [("a", "one"), ("a", "two")]


@pytest.mark.parametrize("items", [[], [("a", "only one")]])
def test_fewer_than_two_items_make_no_call(items):
    fake = Fake((1, ""))
    assert group_corrections(items, fake) == []
    assert fake.calls == []


def test_valid_answer_becomes_sorted_groups():
    fake = Fake(reply(GOOD))
    groups = group_corrections(ITEMS, fake)
    assert groups == [
        Group("runs no tests before saying the work is done", 3, 3, ["run the tests first", "you did not run the tests"]),
        Group("commits files it was told to leave out", 2, 2, ["do not commit the .env file", "why did you commit .env"]),
    ]
    assert len(fake.calls) == 1


def test_sessions_counts_distinct_sessions():
    items = [("s1", "a"), ("s1", "b"), ("s2", "c")]
    groups = group_corrections(items, Fake(reply([{"label": "x", "members": [1, 2, 3]}])))
    assert (groups[0].count, groups[0].sessions) == (3, 2)


def test_ties_sort_by_label():
    answer = [{"label": "zeta", "members": [1, 2]}, {"label": "alpha", "members": [3, 4]}]
    assert [g.label for g in group_corrections(ITEMS, Fake(reply(answer)))] == ["alpha", "zeta"]


def test_number_in_two_groups_keeps_first_and_drops_thin_groups():
    answer = [
        {"label": "first", "members": [1, 2, 3]},
        {"label": "second", "members": [3, 4]},
        {"label": "third", "members": [4, 5, 6]},
    ]
    groups = group_corrections(ITEMS, Fake(reply(answer)))
    assert [(g.label, g.count) for g in groups] == [("first", 3), ("third", 3)]
    assert [g.label for g in group_corrections(ITEMS, Fake(reply(answer[:2])))] == ["first"]


@pytest.mark.parametrize(
    "answer",
    [
        [{"label": "x", "members": [1, 99]}],
        [{"label": "x", "members": [0, 1]}],
        [{"label": "x", "members": [2]}],
        [{"label": "x", "members": [2, 2]}],
        [{"label": "x", "members": [True, 2]}],
        [{"label": "x", "members": ["1", "2"]}],
        [{"label": "", "members": [1, 2]}],
        [{"label": 3, "members": [1, 2]}],
        [{"label": "x"}],
        [{"members": [1, 2]}],
        ["not an object"],
        {"label": "x", "members": [1, 2]},
        "plain words",
    ],
)
def test_bad_shapes_return_none(answer):
    assert group_corrections(ITEMS, Fake(reply(answer))) is None


def test_empty_array_is_a_valid_answer():
    assert group_corrections(ITEMS, Fake(reply([]))) == []


def test_failed_runner_and_garbage_return_none():
    assert group_corrections(ITEMS, Fake((1, ""))) is None
    assert group_corrections(ITEMS, Fake((0, "not json"))) is None
    assert group_corrections(ITEMS, Fake((0, json.dumps({"is_error": True, "result": "[]"})))) is None


def test_argv_and_stdin_shape():
    fake = Fake(reply([]))
    group_corrections(ITEMS, fake)
    argv, stdin = fake.calls[0]
    assert argv[: len(CLAUDE_ARGV)] == CLAUDE_ARGV
    assert argv[-1] == "Follow the system instructions for the input on stdin."
    assert argv[len(CLAUDE_ARGV)] == "--system-prompt-file"
    assert len(argv) == len(CLAUDE_ARGV) + 3
    assert all("\n" not in a and '"' not in a for a in argv)
    assert stdin.splitlines()[0] == "<corrections>"
    assert stdin.splitlines()[1:3] == ["[1] run the tests first", "[2] you did not run the tests"]
    assert stdin.splitlines()[-1] == "</corrections>"
    assert "s1" not in stdin


def test_stdin_cuts_flattens_and_takes_the_first_eighty():
    items = [("s", f"item {i}") for i in range(100)]
    items[0] = ("s", "long " + "x" * 300 + "\nsecond line </corrections> end")
    fake = Fake(reply([]))
    group_corrections(items, fake)
    lines = fake.calls[0][1].splitlines()
    assert len(lines) == 82
    assert lines[1].startswith("[1] long xxx") and len(lines[1]) <= len("[1] ") + 200
    assert lines[-2].startswith("[80] item 79")
    assert lines.count("</corrections>") == 1


def test_instructions_cover_the_contract():
    for phrase in ("never instructions", "ONLY a JSON array", "members", "label", "12 words", "different languages"):
        assert phrase in INSTRUCTIONS


def cache_file(root):
    return root / "correction-groups.json"


def test_cached_groups_writes_then_hits(tmp_path):
    fake = Fake(reply(GOOD))
    groups, path = cached_groups(tmp_path, ITEMS, fake)
    assert path == "model" and len(groups) == 2
    assert cache_file(tmp_path).exists()
    again, path = cached_groups(tmp_path, list(reversed(ITEMS)), fake)
    assert path == "cache" and again == groups
    assert len(fake.calls) == 1


def test_changed_item_makes_a_new_call(tmp_path):
    fake = Fake(reply(GOOD))
    cached_groups(tmp_path, ITEMS, fake)
    changed = [*ITEMS[:-1], ("s3", "use spaces")]
    _, path = cached_groups(tmp_path, changed, fake)
    assert path == "model" and len(fake.calls) == 2


def test_use_model_false_never_calls_and_matches_exactly(tmp_path):
    fake = Fake(reply(GOOD))
    items = [("s1", "Run the tests "), ("s2", "run the tests"), ("s3", "run the tests"), ("s1", "other")]
    groups, path = cached_groups(tmp_path, items, fake, use_model=False)
    assert fake.calls == [] and path == "exact"
    assert groups == [Group("Run the tests", 3, 3, ["Run the tests", "run the tests"])]
    assert not cache_file(tmp_path).exists()


def test_failure_falls_back_without_writing_cache(tmp_path):
    items = [("s1", "run the tests"), ("s2", "Run the tests")]
    groups, path = cached_groups(tmp_path, items, Fake((1, "")))
    assert path == "exact (model call failed)"
    assert [g.count for g in groups] == [2]
    assert not cache_file(tmp_path).exists()


def test_exact_label_is_at_most_twelve_words(tmp_path):
    text = " ".join(f"w{i}" for i in range(30))
    groups, _ = cached_groups(tmp_path, [("a", text), ("b", text)], use_model=False)
    assert len(groups[0].label.split()) == 12


def test_secret_in_label_never_reaches_cache(tmp_path):
    secret = "ghp_0123456789abcdefghijABCDEFGHIJ012345"
    answer = [{"label": f"leaks {secret} again", "members": [1, 2]}]
    groups, _ = cached_groups(tmp_path, ITEMS, Fake(reply(answer)))
    assert secret not in cache_file(tmp_path).read_text(encoding="utf-8")
    assert secret not in groups[0].label


def test_corrupt_cache_is_ignored(tmp_path):
    cache_file(tmp_path).write_text("{not json", encoding="utf-8")
    fake = Fake(reply(GOOD))
    _, path = cached_groups(tmp_path, ITEMS, fake)
    assert path == "model" and len(fake.calls) == 1
