import json
from pathlib import Path

import pytest

from kaizen.record.model import RunRecord
from kaizen.record.parse import parse_session, parse_transcript

FIX = Path(__file__).parent.parent / "fixtures"
SUB = FIX / "session_sub"


def write(tmp_path, lines, name="s.jsonl"):
    p = tmp_path / name
    p.write_text(
        "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n",
        encoding="utf-8",
    )
    return p


def assistant(msg_id, blocks, usage=None, model="m1", **extra):
    msg = {"id": msg_id, "model": model, "role": "assistant", "content": blocks}
    if usage is not None:
        msg["usage"] = usage
    return {"type": "assistant", "message": msg, **extra}


def tool_use(tid, name="Bash", inp=None):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp or {}}


def result(tid, content, is_error=False):
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": is_error}
            ],
        },
    }


def test_basic_record():
    r = parse_transcript(FIX / "session_basic.jsonl")
    assert r.source == "claude-code"
    assert [c.name for c in r.tool_calls] == ["Read", "Read", "Bash", "Edit", "Bash"]
    assert r.tool_calls[2].is_error is True and r.tool_calls[4].is_error is False
    assert r.tool_calls[2].exit_code == 1 and r.tool_calls[4].exit_code == 0
    assert len(r.user_messages) == 1
    assert sum(u.total for u in r.usage_by_model.values()) == 7115
    assert r.cost_usd == 0.0421
    assert r.pr_urls == ["https://github.com/example/repo/pull/1"]
    assert r.repo == "project"
    assert r.skipped_lines == 0


def test_basic_metadata():
    r = parse_transcript(FIX / "session_basic.jsonl")
    assert r.session_id == "00000000-0000-4000-8000-000000000001"
    assert r.cwd == "/home/dev/project"
    assert r.git_branch == "main"
    assert r.agent_version == "2.1.328"
    assert r.started_at == "2026-01-01T10:00:00.000Z"
    assert r.ended_at == "2026-01-01T10:00:20.000Z"
    assert r.skills_used == []
    assert r.parent_session_id is None
    assert r.user_messages == ["Fix the failing test in src/app.py"]
    assert r.tool_calls[3].output_excerpt == ""
    assert r.tool_calls[0].agent_id is None


def test_truncated_line_is_counted_not_fatal():
    r = parse_transcript(FIX / "session_broken.jsonl")
    assert r.skipped_lines == 1 and r.session_id


def test_round_trip():
    r = parse_transcript(FIX / "session_basic.jsonl")
    assert RunRecord.from_dict(r.to_dict()) == r


def test_round_trip_survives_json():
    r = parse_session(SUB / "00000000-0000-4000-8000-0000000000aa.jsonl")
    assert RunRecord.from_dict(json.loads(json.dumps(r.to_dict()))) == r


def test_list_form_tool_result_joins_text(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1")]),
        result("t1", [{"type": "text", "text": "one"}, {"type": "image"}, {"type": "text", "text": "two"}]),
    ])
    c = parse_transcript(p).tool_calls[0]
    assert c.output_excerpt == "one\ntwo"
    assert c.exit_code == 0


def test_long_output_and_input_are_cut(tmp_path):
    long = "x" * 5000
    p = write(tmp_path, [
        assistant("a", [tool_use("t1", inp={"command": long, "timeout": 3, "description": {"deep": [long, 7]}})]),
        result("t1", long),
    ])
    c = parse_transcript(p).tool_calls[0]
    assert c.output_excerpt == "x" * 1000 + "\n[... 3000 characters omitted ...]\n" + "x" * 1000
    assert len(c.input["command"]) == 2000
    assert c.input["timeout"] == 3
    assert len(c.input["description"]["deep"][0]) == 2000
    assert c.input["description"]["deep"][1] == 7


def test_tool_use_without_result(tmp_path):
    p = write(tmp_path, [assistant("a", [tool_use("t1")], timestamp="2026-01-01T00:00:00Z")])
    c = parse_transcript(p).tool_calls[0]
    assert (c.is_error, c.output_excerpt, c.exit_code) == (False, "", None)
    assert c.timestamp == "2026-01-01T00:00:00Z"


def test_tool_calls_follow_tool_use_order_not_result_order(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1", "Bash"), tool_use("t2", "PowerShell")]),
        result("t2", "r2"),
        result("t1", "r1"),
    ])
    calls = parse_transcript(p).tool_calls
    assert [(c.name, c.output_excerpt) for c in calls] == [("Bash", "r1"), ("PowerShell", "r2")]


@pytest.mark.parametrize(
    "text,expected",
    [("Exit code 127\nnot found", 127), ("Error: boom", None), ("  Exit code 2", None)],
)
def test_exit_code_on_error(tmp_path, text, expected):
    p = write(tmp_path, [assistant("a", [tool_use("t1")]), result("t1", text, is_error=True)])
    c = parse_transcript(p).tool_calls[0]
    assert c.is_error is True and c.exit_code == expected


def test_same_message_id_counts_once_last_wins(tmp_path):
    u1 = {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 5}
    u2 = {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 50}
    p = write(tmp_path, [
        assistant("same", [{"type": "text", "text": "a"}], u1),
        assistant("same", [tool_use("t1")], u2),
        assistant("other", [], u1, model="m2"),
    ])
    r = parse_transcript(p)
    assert r.usage_by_model["m1"].output == 50 and r.usage_by_model["m1"].total == 51
    assert r.usage_by_model["m2"].total == 6
    assert len(r.tool_calls) == 1


def test_usage_sums_per_model(tmp_path):
    u = {"input_tokens": 1, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3, "output_tokens": 4}
    p = write(tmp_path, [assistant("a", [], u), assistant("b", [], u)])
    us = parse_transcript(p).usage_by_model["m1"]
    assert (us.input, us.cache_write, us.cache_read, us.output) == (2, 4, 6, 8)


def test_cost_is_last_cost_state_and_none_without(tmp_path):
    p = write(tmp_path, [
        {"type": "cost-state", "totalCostUSD": 0.5},
        {"type": "cost-state", "totalCostUSD": 0.7},
    ])
    assert parse_transcript(p).cost_usd == 0.7
    assert parse_transcript(write(tmp_path, [{"type": "user"}], "n.jsonl")).cost_usd is None


def test_user_message_filters(tmp_path):
    def user(content, **extra):
        return {"type": "user", "message": {"role": "user", "content": content}, **extra}

    p = write(tmp_path, [
        user("typed"),
        user([{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]),
        user("meta", isMeta=True),
        user("<system-reminder>x</system-reminder>"),
        user("<task-notification>x</task-notification>"),
        result("nope", "tool output"),
    ])
    assert parse_transcript(p).user_messages == ["typed", "part1\npart2"]


def test_skills_and_prs_deduped_in_order(tmp_path):
    p = write(tmp_path, [
        {"type": "assistant", "attributionSkill": "b"},
        {"type": "assistant", "attributionSkill": "a"},
        {"type": "assistant", "attributionSkill": "b"},
        {"type": "pr-link", "prUrl": "u2"},
        {"type": "pr-link", "prUrl": "u1"},
        {"type": "pr-link", "prUrl": "u2"},
    ])
    r = parse_transcript(p)
    assert r.skills_used == ["b", "a"]
    assert r.pr_urls == ["u2", "u1"]


@pytest.mark.parametrize(
    "cwd,repo",
    [
        ("/home/dev/project", "project"),
        ("/home/dev/project/", "project"),
        ("C:\\work\\project", "project"),
        ("C:/work/project", "project"),
        ("C:\\", None),
        ("", None),
    ],
)
def test_repo_from_cwd(tmp_path, cwd, repo):
    p = write(tmp_path, [{"type": "user", "cwd": cwd}])
    assert parse_transcript(p).repo == repo


def test_session_id_falls_back_to_file_stem(tmp_path):
    p = write(tmp_path, [{"type": "user"}], "abc-123.jsonl")
    assert parse_transcript(p).session_id == "abc-123"


def test_empty_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    r = parse_transcript(p)
    assert r.tool_calls == [] and r.user_messages == [] and r.usage_by_model == {}
    assert r.skipped_lines == 0 and r.session_id == "empty"
    assert r.started_at == "" and r.ended_at == ""


def test_non_object_json_line_is_skipped(tmp_path):
    p = write(tmp_path, ["[1, 2]", "42", "null", '{"type": "mystery"}', "{bad"])
    assert parse_transcript(p).skipped_lines == 4


def test_odd_shapes_do_not_crash(tmp_path):
    p = write(tmp_path, [
        {"type": "assistant", "message": "oops"},
        {"type": "assistant", "message": {"content": "str", "usage": {"input_tokens": None}}},
        {"type": "user", "message": {"content": [1, "x", None]}},
        {"type": "user", "message": None},
        {"type": "cost-state", "totalCostUSD": "free"},
        {"type": "pr-link"},
    ])
    r = parse_transcript(p)
    assert r.skipped_lines == 0 and r.cost_usd is None and r.pr_urls == []


def test_session_without_subagents_equals_transcript():
    p = FIX / "session_basic.jsonl"
    assert parse_session(p) == parse_transcript(p)


def test_session_folds_subagent():
    p = SUB / "00000000-0000-4000-8000-0000000000aa.jsonl"
    parent = parse_transcript(p)
    r = parse_session(p)
    assert [(c.name, c.agent_id) for c in parent.tool_calls] == [("Agent", None)]
    assert [(c.name, c.agent_id) for c in r.tool_calls] == [
        ("Agent", None),
        ("Bash", "a1b2c3d4e5f607182"),
    ]
    assert r.tool_calls[1].exit_code == 0
    assert r.usage_by_model["claude-sonnet-5-5"] == parent.usage_by_model["claude-sonnet-5-5"]
    assert r.usage_by_model["claude-haiku-4-5"].total == 4 + 200 + 30 + 2 + 200 + 6
    assert r.user_messages == parent.user_messages == ["Check the build in the background"]
    assert r.session_id == "00000000-0000-4000-8000-0000000000aa"
    assert r.parent_session_id is None


def user_line(content, **extra):
    return {"type": "user", "message": {"role": "user", "content": content}, **extra}


def prompts_of(tmp_path, *contents):
    return parse_transcript(write(tmp_path, [user_line(c) for c in contents])).user_messages


def test_leading_harness_sections_stripped_from_string(tmp_path):
    text = (
        "<ide_opened_file>The user opened a.py</ide_opened_file>\n"
        '<browser_instruction kind="x">\nlots\n</browser_instruction>\n\n'
        "<ide_selection>sel</ide_selection>real task <b>kept</b>"
    )
    assert prompts_of(tmp_path, text) == ["real task <b>kept</b>"]


def test_leading_harness_blocks_stripped_from_list(tmp_path):
    blocks = [
        {"type": "text", "text": "<ide_opened_file>x</ide_opened_file>"},
        {"type": "text", "text": "<local-command-caveat>c</local-command-caveat>\nask"},
        {"type": "text", "text": "more"},
    ]
    assert prompts_of(tmp_path, blocks) == ["ask\nmore"]


def test_only_harness_text_is_not_a_prompt(tmp_path):
    assert prompts_of(
        tmp_path,
        "<ide_opened_file>x</ide_opened_file>\n<system-reminder>y</system-reminder>",
        "<local-command-stdout>out</local-command-stdout>",
        [{"type": "text", "text": "<task-notification>t</task-notification>"}],
    ) == []


def test_unclosed_harness_tag_means_all_harness(tmp_path):
    assert prompts_of(tmp_path, "<browser_instruction>never closed and real-looking text") == []


def test_tags_not_in_list_or_mid_prompt_are_kept(tmp_path):
    pasted = '<pasted_content id="1">data</pasted_content> why?'
    mid = "look at this <system-reminder>x</system-reminder> please"
    assert prompts_of(tmp_path, pasted, mid, "<ide_opened_fileX>a</ide_opened_fileX>") == [
        pasted,
        mid,
        "<ide_opened_fileX>a</ide_opened_fileX>",
    ]


def test_slash_command_made_readable(tmp_path):
    cmd = (
        "<command-message>foo</command-message>\n<command-name>/foo</command-name>\n"
        "<command-args>bar baz</command-args>"
    )
    bare = "<command-message>foo</command-message>\n<command-name>/foo</command-name>"
    name_first = (
        "<command-name>/compact</command-name>\n<command-message>compact</command-message>\n"
        "<command-args></command-args>"
    )
    with_args = (
        "<command-name>/foo</command-name>\n<command-message>foo</command-message>\n"
        "<command-args>bar</command-args>"
    )
    assert prompts_of(tmp_path, cmd, bare, name_first, with_args) == [
        "/foo bar baz",
        "/foo",
        "/compact",
        "/foo bar",
    ]


def test_interruptions_counted_not_prompts(tmp_path):
    p = write(tmp_path, [
        user_line("[Request interrupted by user]"),
        user_line("[Request interrupted by user for tool use]"),
        user_line([{"type": "text", "text": "[Request interrupted by user]"}]),
        user_line("real"),
    ])
    r = parse_transcript(p)
    assert r.user_messages == ["real"] and r.interruptions == 3
    assert RunRecord.from_dict(r.to_dict()) == r


def test_huge_pasted_prompt_is_fast(tmp_path):
    big = "<" * 2_000_000
    assert prompts_of(tmp_path, big) == [big]


def test_synthetic_model_usage_skipped_but_tool_calls_kept(tmp_path):
    u0 = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}
    p = write(tmp_path, [
        assistant("s", [tool_use("t1")], u0, model="<synthetic>"),
        assistant("r", [], {**u0, "output_tokens": 3}),
    ])
    r = parse_transcript(p)
    assert list(r.usage_by_model) == ["m1"]
    assert [c.id for c in r.tool_calls] == ["t1"]


TOKEN = "ghp_0123456789abcdefghijABCDEFGHIJ012345"


def straddle():
    return "a" * 1990 + TOKEN + "b" * 3000


def test_output_token_across_head_cut_is_redacted(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1")]),
        result("t1", "a" * 990 + TOKEN + "b" * 5000),
    ])
    out = parse_transcript(p).tool_calls[0].output_excerpt
    assert "ghp_" not in out and "0123456789" not in out


def test_output_token_across_tail_cut_is_redacted(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1")]),
        result("t1", "a" * 5000 + TOKEN + " " + "b" * 984),
    ])
    out = parse_transcript(p).tool_calls[0].output_excerpt
    assert "ABCDEFGHIJ012345" not in out and "ghp_" not in out
    assert out.endswith("b" * 984) and "omitted" in out


def test_top_level_input_token_across_cut_is_redacted(tmp_path):
    p = write(tmp_path, [assistant("a", [tool_use("t1", inp={"command": straddle()})])])
    cmd = parse_transcript(p).tool_calls[0].input["command"]
    assert len(cmd) <= 2000 and "ghp_" not in cmd and "0123456789" not in cmd


def test_nested_input_token_across_cut_is_redacted(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1", "MultiEdit", inp={"file_path": "f", "edits": [{"old_string": straddle(), "new_string": "x"}]})])
    ])
    old = parse_transcript(p).tool_calls[0].input["edits"][0]["old_string"]
    assert len(old) <= 2000 and "ghp_" not in old and "0123456789" not in old


def test_short_output_kept_whole_and_long_is_head_and_tail(tmp_path):
    whole = "y" * 2000
    long = "H" * 1000 + "m" * 3000 + "T" * 1000
    p = write(tmp_path, [
        assistant("a", [tool_use("t1"), tool_use("t2")]),
        result("t1", whole),
        result("t2", long),
    ])
    c1, c2 = parse_transcript(p).tool_calls
    assert c1.output_excerpt == whole
    assert c2.output_excerpt == "H" * 1000 + "\n[... 3000 characters omitted ...]\n" + "T" * 1000


def test_summary_at_end_of_long_output_survives(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1")]),
        result("t1", "." * 9000 + "\n3 failed, 12 passed"),
    ])
    assert parse_transcript(p).tool_calls[0].output_excerpt.endswith("3 failed, 12 passed")


def test_excerpt_only_for_shell_or_errors(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("r", "Read"), tool_use("b", "Bash"), tool_use("ps", "PowerShell"),
                        tool_use("e", "Read"), tool_use("m", "mcp__x__y")]),
        result("r", "file content"),
        result("b", "out"),
        result("ps", "out2"),
        result("e", "Error: nope", is_error=True),
        result("m", "mcp out"),
    ])
    calls = {c.id: c for c in parse_transcript(p).tool_calls}
    assert calls["r"].output_excerpt == ""
    assert calls["b"].output_excerpt == "out"
    assert calls["ps"].output_excerpt == "out2"
    assert calls["e"].output_excerpt == "Error: nope"
    assert calls["m"].output_excerpt == ""
    assert calls["r"].exit_code is None


def test_exit_code_computed_from_full_text_even_when_excerpt_empty(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1", "Read")]),
        result("t1", "Exit code 4\n" + "z" * 9000, is_error=True),
    ])
    assert parse_transcript(p).tool_calls[0].exit_code is None


def test_input_allowlist_drops_unknown_keys(tmp_path):
    p = write(tmp_path, [
        assistant("a", [
            tool_use("t1", "Bash", {"command": "ls", "env": {"K": "v"}, "timeout": 5}),
            tool_use("t2", "Read", {"file_path": "f", "offset": 1, "extra": "x"}),
            tool_use("t3", "Skill", {"skill": "s", "args": "a", "other": 1}),
        ])
    ])
    c1, c2, c3 = parse_transcript(p).tool_calls
    assert c1.input == {"command": "ls", "timeout": 5}
    assert c2.input == {"file_path": "f", "offset": 1}
    assert c3.input == {"skill": "s", "args": "a"}


def test_unknown_tool_keeps_key_names_only(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1", "mcp__srv__do", {"token": "secret", "n": 3, "o": {"a": 1}})])
    ])
    assert parse_transcript(p).tool_calls[0].input == {"token": "[OMITTED]", "n": "[OMITTED]", "o": "[OMITTED]"}


def sub_session(tmp_path, parent_lines, sub_lines):
    parent = write(tmp_path, parent_lines, "sess.jsonl")
    d = tmp_path / "sess" / "subagents"
    d.mkdir(parents=True)
    (d / "agent-abc.jsonl").write_text(
        "\n".join(json.dumps(x) for x in sub_lines) + "\n", encoding="utf-8"
    )
    return parent


def test_subagent_calls_merge_in_time_order(tmp_path):
    p = sub_session(
        tmp_path,
        [
            assistant("p1", [tool_use("tp", "Bash", {"command": "pytest"})], timestamp="2026-01-01T10:05:00Z"),
            result("tp", "ok"),
        ],
        [
            assistant("s1", [tool_use("ts", "Bash", {"command": "pytest"})], timestamp="2026-01-01T10:01:00Z"),
            result("ts", "Exit code 1\nfail", is_error=True),
        ],
    )
    calls = parse_session(p).tool_calls
    assert [c.id for c in calls] == ["ts", "tp"]
    assert calls[-1].exit_code == 0


def test_empty_timestamp_sorts_with_previous_call_in_own_file(tmp_path):
    p = sub_session(
        tmp_path,
        [assistant("p1", [tool_use("tp")], timestamp="2026-01-01T10:05:00Z")],
        [
            assistant("s1", [tool_use("s_a")], timestamp="2026-01-01T10:01:00Z"),
            assistant("s2", [tool_use("s_b")]),
            assistant("s3", [tool_use("s_c")], timestamp="2026-01-01T10:09:00Z"),
        ],
    )
    assert [c.id for c in parse_session(p).tool_calls] == ["s_a", "s_b", "tp", "s_c"]


def test_subagent_metadata_folds_into_parent(tmp_path):
    p = sub_session(
        tmp_path,
        [
            {"type": "pr-link", "prUrl": "u1", "timestamp": "2026-01-01T10:05:00Z"},
            {"type": "assistant", "attributionSkill": "s1", "message": {}, "timestamp": "2026-01-01T10:06:00Z"},
            {"type": "cost-state", "totalCostUSD": 1.5},
            {"type": "user", "message": {"content": "hi"}},
        ],
        [
            {"type": "pr-link", "prUrl": "u1", "timestamp": "2026-01-01T10:00:00Z"},
            {"type": "pr-link", "prUrl": "u2", "timestamp": "2026-01-01T10:00:01Z"},
            {"type": "assistant", "attributionSkill": "s2", "message": {}, "timestamp": "2026-01-01T10:09:00Z"},
            {"type": "assistant", "attributionSkill": "s1", "message": {}},
            {"type": "user", "message": {"content": "[Request interrupted by user]"}},
            {"type": "user", "message": {"content": "sub prompt"}},
        ],
    )
    r = parse_session(p)
    assert r.pr_urls == ["u1", "u2"]
    assert r.skills_used == ["s1", "s2"]
    assert r.interruptions == 1
    assert r.started_at == "2026-01-01T10:00:00Z" and r.ended_at == "2026-01-01T10:09:00Z"
    assert r.cost_usd == 1.5
    assert r.user_messages == ["hi"]


def test_from_dict_tolerates_missing_and_unknown_fields():
    r = RunRecord.from_dict({})
    assert r.session_id == "" and r.schema_version == 1 and r.tool_calls == []
    full = parse_transcript(FIX / "session_basic.jsonl").to_dict()
    old = {k: v for k, v in full.items() if k not in ("schema_version", "final_message", "usage_by_model")}
    old["future_field"] = 1
    old["tool_calls"] = [{"id": "x", "name": "Bash", "new": 1}]
    got = RunRecord.from_dict(old)
    assert got.tool_calls[0].input == {} and got.usage_by_model == {}


def test_schema_version_in_dict():
    assert parse_transcript(FIX / "session_basic.jsonl").to_dict()["schema_version"] == 2


def test_user_message_times_parallel_to_messages():
    r = parse_transcript(FIX / "session_basic.jsonl")
    assert r.user_message_times == ["2026-01-01T10:00:00.000Z"]
    assert len(r.user_message_times) == len(r.user_messages)


def test_user_message_time_empty_when_line_has_none(tmp_path):
    p = write(tmp_path, [
        user_line("first", timestamp="2026-01-01T10:00:00Z"),
        user_line("second"),
    ])
    r = parse_transcript(p)
    assert r.user_messages == ["first", "second"]
    assert r.user_message_times == ["2026-01-01T10:00:00Z", ""]


def test_subagent_files_add_no_prompt_times():
    r = parse_session(SUB / "00000000-0000-4000-8000-0000000000aa.jsonl")
    assert len(r.user_message_times) == len(r.user_messages) == 1


def test_from_dict_tolerates_missing_times():
    r = RunRecord.from_dict({"user_messages": ["a"]})
    assert r.user_message_times == []


SUMMARY = "This session is being continued from a previous conversation that ran out of context. Summary: ..."


def test_continuation_summary_skipped_by_flag(tmp_path):
    p = write(tmp_path, [
        user_line("real request", timestamp="t1"),
        user_line("anything at all", isCompactSummary=True, timestamp="t2"),
        user_line("next request", timestamp="t3"),
    ])
    r = parse_transcript(p)
    assert r.user_messages == ["real request", "next request"]
    assert r.user_message_times == ["t1", "t3"]


def test_continuation_summary_skipped_by_text(tmp_path):
    p = write(tmp_path, [
        user_line("real request"),
        user_line("<system-reminder>x</system-reminder>" + SUMMARY),
        user_line([{"type": "text", "text": SUMMARY}]),
    ])
    assert parse_transcript(p).user_messages == ["real request"]


def text_block(t):
    return {"type": "text", "text": t}


def test_final_message_is_last_assistant_text(tmp_path):
    p = write(tmp_path, [
        assistant("a", [text_block("first")]),
        assistant("b", [text_block("part one"), tool_use("t1"), text_block("part two")]),
        assistant("c", [tool_use("t2")]),
        assistant("d", [text_block("")]),
    ])
    assert parse_transcript(p).final_message == "part one\npart two"


def test_final_message_empty_without_text(tmp_path):
    p = write(tmp_path, [assistant("a", [tool_use("t1")])])
    assert parse_transcript(p).final_message == ""


def test_final_message_head_and_tail_and_redacted(tmp_path):
    p = write(tmp_path, [assistant("a", [text_block("a" * 995 + TOKEN + " " + "b" * 3000 + "END")])])
    m = parse_transcript(p).final_message
    assert "omitted" in m and m.endswith("END") and "ghp_" not in m


def test_subagent_final_message_does_not_contribute(tmp_path):
    p = sub_session(
        tmp_path,
        [assistant("p", [text_block("parent done")], timestamp="2026-01-01T10:00:00Z")],
        [assistant("s", [text_block("sub done")], timestamp="2026-01-01T10:09:00Z")],
    )
    assert parse_session(p).final_message == "parent done"


@pytest.mark.parametrize("name,expected", [("Bash", 0), ("PowerShell", 0), ("Read", None), ("Edit", None), ("Write", None), ("Agent", None)])
def test_exit_code_only_for_shell_tools(tmp_path, name, expected):
    p = write(tmp_path, [assistant("a", [tool_use("t1", name)]), result("t1", "ok")])
    assert parse_transcript(p).tool_calls[0].exit_code == expected


def test_same_message_id_keeps_largest_value_per_field(tmp_path):
    u1 = {"input_tokens": 100, "cache_creation_input_tokens": 7, "cache_read_input_tokens": 0, "output_tokens": 5}
    u2 = {"input_tokens": 10, "output_tokens": 50}
    p = write(tmp_path, [
        assistant("same", [], u1, model="m1"),
        assistant("same", [], u2, model=""),
    ])
    u = parse_transcript(p).usage_by_model["m1"]
    assert (u.input, u.cache_write, u.cache_read, u.output) == (100, 7, 0, 50)


def test_timestamps_compare_as_times_not_strings(tmp_path):
    early = "2026-01-01T12:00:00+02:00"
    late = "2026-01-01T10:30:00Z"
    p = write(tmp_path, [
        assistant("a", [tool_use("t1")], timestamp=late),
        assistant("b", [tool_use("t2")], timestamp=early),
    ])
    r = parse_transcript(p)
    assert (r.started_at, r.ended_at) == (early, late)


def test_subagent_merge_order_compares_times(tmp_path):
    p = sub_session(
        tmp_path,
        [assistant("p1", [tool_use("tp")], timestamp="2026-01-01T10:30:00Z")],
        [assistant("s1", [tool_use("ts")], timestamp="2026-01-01T12:00:00+02:00")],
    )
    r = parse_session(p)
    assert [c.id for c in r.tool_calls] == ["ts", "tp"]
    assert (r.started_at, r.ended_at) == ("2026-01-01T12:00:00+02:00", "2026-01-01T10:30:00Z")


def test_unparseable_timestamp_sorts_after_parseable_and_never_raises(tmp_path):
    p = write(tmp_path, [
        assistant("a", [tool_use("t1")], timestamp="garbage"),
        assistant("b", [tool_use("t2")], timestamp="2026-01-01T10:00:00"),
        assistant("c", [tool_use("t3")], timestamp="2026-01-01T09:00:00Z"),
    ])
    r = parse_transcript(p)
    assert (r.started_at, r.ended_at) == ("2026-01-01T09:00:00Z", "garbage")
