import time
from datetime import UTC, datetime, timedelta

from kaizen.record.model import RunRecord, ToolCall, Usage
from kaizen.tasks import GAP_MINUTES, Task, TaskSummary, split_tasks, summarise, task_view

BASE = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
LONG = "please change the parser so it handles empty files"
LONG2 = "now also update the docs for the parser change"


def at(minute):
    return (BASE + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")


def record(prompts, calls=(), **extra):
    texts = [t for _, t in prompts]
    times = [at(m) for m, _ in prompts]
    tool_calls = []
    for n, (minute, tool, inp, agent) in enumerate(calls):
        tool_calls.append(ToolCall(id=f"t{n}", name=tool, input=inp, timestamp=at(minute), agent_id=agent, exit_code=0))
    return RunRecord(
        session_id="s1",
        repo="app",
        cwd="/w/app",
        started_at=at(prompts[0][0]) if prompts else "",
        ended_at="",
        user_messages=texts,
        user_message_times=times,
        tool_calls=tool_calls,
        **extra,
    )


def sh(minute, command, agent=None):
    return (minute, "Bash", {"command": command}, agent)


def edit(minute, path="/w/app/a.py", agent=None):
    return (minute, "Edit", {"file_path": path, "old_string": "a", "new_string": "b"}, agent)


def read(minute, agent=None):
    return (minute, "Read", {"file_path": "/w/app/r.py"}, agent)


def test_one_prompt_one_task():
    tasks = split_tasks(record([(0, LONG)], [read(1)]))
    assert len(tasks) == 1
    t = tasks[0]
    assert t.index == 0 and t.prompts == [LONG] and len(t.tool_calls) == 1
    assert t.started_at == at(0) and t.ended_at == at(1)


def test_second_long_prompt_without_gap_or_ship_is_glued():
    tasks = split_tasks(record([(0, LONG), (5, LONG2)], [read(1), read(6)]))
    assert len(tasks) == 1 and tasks[0].prompts == [LONG, LONG2]
    assert len(tasks[0].tool_calls) == 2


def test_gap_of_45_opens_and_44_does_not():
    assert len(split_tasks(record([(0, LONG), (GAP_MINUTES, LONG2)]))) == 2
    assert len(split_tasks(record([(0, LONG), (GAP_MINUTES - 1, LONG2)]))) == 1


def test_gap_counts_from_last_main_agent_call():
    rec = record([(0, LONG), (100, LONG2)], [read(80)])
    assert len(split_tasks(rec)) == 1
    rec = record([(0, LONG), (125, LONG2)], [read(80)])
    assert len(split_tasks(rec)) == 2


def test_gap_ignores_subagent_calls():
    rec = record([(0, LONG), (60, LONG2)], [read(5), read(50, agent="a1")])
    assert len(split_tasks(rec)) == 2


def test_gap_counts_from_latest_prompt_too():
    rec = record([(0, LONG), (40, "yes go ahead"), (80, LONG2)])
    assert len(split_tasks(rec)) == 1


def test_main_commit_opens_at_next_real_prompt():
    rec = record([(0, LONG), (10, LONG2)], [edit(1), sh(2, "git commit -m x")])
    tasks = split_tasks(rec)
    assert len(tasks) == 2
    assert [len(t.tool_calls) for t in tasks] == [2, 0]


def test_subagent_commit_does_not_split():
    rec = record([(0, LONG), (10, LONG2)], [sh(2, "git commit -m x", agent="a1")])
    assert len(split_tasks(rec)) == 1


def test_other_shipping_commands_split():
    for command in ("git merge dev", "git push origin x", "gh pr create --fill", "gh pr merge 3"):
        rec = record([(0, LONG), (10, LONG2)], [sh(2, command)])
        assert len(split_tasks(rec)) == 2, command
    rec = record([(0, LONG), (10, LONG2)], [sh(2, "git status")])
    assert len(split_tasks(rec)) == 1


def test_short_confirmation_after_commit_is_glued_then_real_request_opens():
    rec = record(
        [(0, LONG), (10, "yes go ahead"), (11, "ok"), (20, LONG2)],
        [sh(2, "git commit -m x")],
    )
    tasks = split_tasks(rec)
    assert len(tasks) == 2
    assert tasks[0].prompts == [LONG, "yes go ahead", "ok"]
    assert tasks[1].prompts == [LONG2]


def test_confirmation_word_with_up_to_12_words_is_glue_but_13_is_not():
    twelve = "yes " + "word " * 11
    thirteen = "yes " + "word " * 12
    base = [sh(2, "git commit -m x")]
    assert len(split_tasks(record([(0, LONG), (10, twelve)], base))) == 1
    assert len(split_tasks(record([(0, LONG), (10, thirteen)], base))) == 2


def test_four_word_prompt_is_glue_five_is_not():
    base = [sh(2, "git push")]
    assert len(split_tasks(record([(0, LONG), (10, "fix the other file")], base))) == 1
    assert len(split_tasks(record([(0, LONG), (10, "fix the other file now")], base))) == 2


def test_shipping_before_a_task_opened_does_not_count_for_the_next_one():
    rec = record(
        [(0, LONG), (10, LONG2), (20, "and another long request to handle")],
        [sh(2, "git commit -m x")],
    )
    tasks = split_tasks(rec)
    assert len(tasks) == 2
    assert tasks[1].prompts == [LONG2, "and another long request to handle"]


def test_clear_opens_a_task_even_though_short():
    rec = record([(0, LONG), (5, "/clear"), (6, LONG2)])
    tasks = split_tasks(rec)
    assert len(tasks) == 2
    assert tasks[1].prompts == ["/clear", LONG2]
    assert tasks[1].title == LONG2


def test_compact_with_arguments_opens_a_task():
    assert len(split_tasks(record([(0, LONG), (5, "/compact keep the parser notes please")]))) == 2


def test_pasted_only_prompt_is_glue():
    pasted = "<pasted_content>" + "x" * 500 + "</pasted_content>"
    two = "[pasted text, 500 characters] [pasted text, 700 characters]"
    base = [sh(2, "git commit -m x")]
    assert len(split_tasks(record([(0, LONG), (10, pasted)], base))) == 1
    assert len(split_tasks(record([(0, LONG), (10, two)], base))) == 1


def test_pasted_block_does_not_make_a_short_prompt_long():
    pasted = "<pasted_content>" + "word " * 100 + "</pasted_content>"
    assert len(split_tasks(record([(0, LONG), (10, pasted)], [sh(2, "git push")]))) == 1


def test_calls_before_first_prompt_go_to_first_task():
    rec = record([(5, LONG), (100, LONG2)], [read(1), read(6)])
    tasks = split_tasks(rec)
    assert len(tasks) == 2
    assert [len(t.tool_calls) for t in tasks] == [2, 0]
    assert tasks[0].started_at == at(5)


def test_commit_before_first_prompt_does_not_split():
    rec = record([(5, LONG), (10, LONG2)], [sh(1, "git commit -m x")])
    assert len(split_tasks(rec)) == 1


def test_calls_belong_to_the_task_whose_prompt_preceded_them():
    rec = record([(0, LONG), (100, LONG2)], [read(1), read(101), read(102)])
    tasks = split_tasks(rec)
    assert [len(t.tool_calls) for t in tasks] == [1, 2]


def test_background_subagent_stays_whole_in_the_earlier_task():
    rec = record(
        [(0, LONG), (100, LONG2)],
        [read(1, agent="bg"), read(50, agent="bg"), read(101, agent="bg"), read(102)],
    )
    tasks = split_tasks(rec)
    assert len(tasks) == 2
    assert [len(t.tool_calls) for t in tasks] == [3, 1]
    assert tasks[0].ended_at == at(101)
    assert tasks[1].tool_calls[0].agent_id is None


def test_subagent_whose_first_call_is_in_second_task_stays_there():
    rec = record([(0, LONG), (100, LONG2)], [read(101, agent="late"), read(102, agent="late")])
    tasks = split_tasks(rec)
    assert [len(t.tool_calls) for t in tasks] == [0, 2]


def test_subagent_calls_before_first_prompt_go_to_first_task():
    rec = record([(5, LONG), (100, LONG2)], [read(1, agent="x"), read(110, agent="x")])
    assert [len(t.tool_calls) for t in split_tasks(rec)] == [2, 0]


def test_old_style_record_gives_one_task():
    rec = RunRecord(
        session_id="s",
        started_at=at(0),
        ended_at=at(9),
        user_messages=[LONG, LONG2],
        tool_calls=[ToolCall(id="1", name="Read", input={}, timestamp=at(1))],
    )
    tasks = split_tasks(rec)
    assert len(tasks) == 1
    assert tasks[0].prompts == [LONG, LONG2] and len(tasks[0].tool_calls) == 1
    assert tasks[0].started_at == at(0) and tasks[0].ended_at == at(9)


def test_mismatched_times_give_one_task():
    rec = record([(0, LONG), (100, LONG2)])
    rec.user_message_times = rec.user_message_times[:1]
    assert len(split_tasks(rec)) == 1


def test_no_prompts_gives_one_task_with_everything():
    rec = RunRecord(session_id="s", tool_calls=[ToolCall(id="1", name="Read", input={}), ToolCall(id="2", name="Read", input={})])
    tasks = split_tasks(rec)
    assert len(tasks) == 1 and len(tasks[0].tool_calls) == 2 and tasks[0].title == "(no request text)"
    assert len(split_tasks(RunRecord(session_id="s"))) == 1


def test_unparseable_times_do_not_raise():
    rec = record([(0, LONG), (100, LONG2), (200, "and yet another long request here")], [read(1), read(150)])
    rec.user_message_times[1] = "garbage"
    rec.tool_calls[0].timestamp = "nope"
    rec.tool_calls[1].timestamp = ""
    tasks = split_tasks(rec)
    assert sum(len(t.tool_calls) for t in tasks) == 2
    assert sum(len(t.prompts) for t in tasks) == 3


def test_all_times_unparseable():
    rec = record([(0, LONG), (1, LONG2)], [read(1)])
    rec.user_message_times = ["x", ""]
    rec.tool_calls[0].timestamp = "y"
    tasks = split_tasks(rec)
    assert len(tasks) == 1 and len(tasks[0].tool_calls) == 1


def test_time_without_offset_is_utc():
    rec = record([(0, LONG), (30, LONG2)])
    rec.user_message_times = ["2026-01-01T10:00:00", "2026-01-01T10:50:00Z"]
    assert len(split_tasks(rec)) == 2
    rec.user_message_times = ["2026-01-01T10:00:00Z", "2026-01-01T10:30:00"]
    assert len(split_tasks(rec)) == 1


def test_title_skips_short_opener_for_later_six_word_prompt():
    rec = record([(0, "fix the bug"), (1, "ok go"), (2, "rename the helper in the parser module")])
    assert split_tasks(rec)[0].title == "rename the helper in the parser module"


def test_title_falls_back_to_opening_prompt():
    assert split_tasks(record([(0, "fix the bug"), (1, "ok go")]))[0].title == "fix the bug"


def test_title_cut_at_120_and_one_line():
    long = ("word " * 60).strip()
    assert len(split_tasks(record([(0, long)]))[0].title) == 120
    rec = record([(0, "first line here\n\n  second   line goes on")])
    assert split_tasks(rec)[0].title == "first line here second line goes on"


def test_title_strips_pasted_blocks():
    text = "<pasted_content>" + "secret words " * 50 + "</pasted_content> explain what this error means please"
    assert split_tasks(record([(0, text)]))[0].title == "[pasted text, 650 characters] explain what this error means please"
    only = "<pasted_content>abc</pasted_content>"
    assert split_tasks(record([(0, only)]))[0].title == "[pasted text, 3 characters]"


def test_title_empty_prompt_text():
    rec = record([(0, "")])
    assert split_tasks(rec)[0].title == "(no request text)"


def test_ended_at_is_latest_of_prompts_and_calls():
    rec = record([(0, LONG), (5, LONG2)], [read(20)])
    t = split_tasks(rec)[0]
    assert t.ended_at == at(20)
    rec = record([(0, LONG), (30, "yes ok")], [read(20)])
    assert split_tasks(rec)[0].ended_at == at(30)


def test_prompts_are_walked_in_time_order():
    rec = record([(100, LONG2), (0, LONG)])
    tasks = split_tasks(rec)
    assert len(tasks) == 2 and tasks[0].prompts == [LONG] and tasks[1].prompts == [LONG2]


def test_task_view_fields():
    rec = record([(0, LONG), (100, LONG2)], [read(1), read(101)], git_branch="main", agent_version="2.1")
    rec.usage_by_model = {"m": Usage(input=5)}
    rec.cost_usd = 1.5
    rec.final_message = "bye"
    rec.pr_urls = ["u"]
    rec.skills_used = ["s"]
    rec.interruptions = 3
    task = split_tasks(rec)[1]
    view = task_view(rec, task)
    assert (view.session_id, view.source, view.cwd, view.repo) == ("s1", "claude-code", "/w/app", "app")
    assert (view.git_branch, view.agent_version, view.schema_version) == ("main", "2.1", rec.schema_version)
    assert (view.started_at, view.ended_at) == (at(100), at(101))
    assert view.user_messages == [LONG2] and view.tool_calls == task.tool_calls
    assert view.usage_by_model == {} and view.cost_usd is None and view.final_message == ""
    assert view.pr_urls == [] and view.skills_used == [] and view.interruptions == 0
    assert view.user_message_times == []


def test_summarise_no_edits():
    s = summarise(record([(0, LONG)], [read(1)]))[0]
    assert s.kind == "no_edits" and s.last_test == "none" and s.files_edited == 0
    assert (s.session_id, s.index, s.repo, s.prompts, s.tool_calls) == ("s1", 0, "app", 1, 1)
    assert s.title == LONG and s.started_at == at(0) and s.ended_at == at(1)


def test_summarise_edited_unchecked():
    s = summarise(record([(0, LONG)], [edit(1), edit(2, "/w/app/b.py")]))[0]
    assert s.kind == "edited_unchecked" and s.files_edited == 2 and s.last_test == "none"


def test_summarise_files_edited_distinct_and_normalised():
    calls = [
        edit(1, "C:\\Repo\\A.py"),
        edit(2, "c:/repo/a.py"),
        (3, "Write", {"file_path": "/w/app/n.py", "content": "x"}, None),
        (4, "NotebookEdit", {"notebook_path": "/w/app/n.ipynb"}, None),
        (5, "MultiEdit", {"file_path": "/w/app/n.py", "edits": []}, None),
    ]
    assert summarise(record([(0, LONG)], calls))[0].files_edited == 3


def test_summarise_edited_checked_by_check_run_has_last_test_none():
    s = summarise(record([(0, LONG)], [edit(1), sh(2, "ruff check .")]))[0]
    assert s.kind == "edited_checked" and s.last_test == "none"


def test_summarise_last_test_passed_failed_unknown():
    passed = summarise(record([(0, LONG)], [edit(1), sh(2, "pytest")]))[0]
    assert passed.kind == "edited_checked" and passed.last_test == "passed"

    rec = record([(0, LONG)], [edit(1), sh(2, "pytest")])
    rec.tool_calls[1].exit_code = 1
    rec.tool_calls[1].is_error = True
    assert summarise(rec)[0].last_test == "failed"

    rec = record([(0, LONG)], [edit(1), sh(2, "pytest | tail -3")])
    assert summarise(rec)[0].last_test == "unknown"


def test_summarise_runs_in_other_task_do_not_count():
    rec = record([(0, LONG), (100, LONG2)], [edit(1), sh(101, "pytest")])
    first, second = summarise(rec)
    assert first.kind == "edited_unchecked" and second.kind == "no_edits" and second.last_test == "passed"
    assert [s.index for s in (first, second)] == [0, 1]


def test_task_summary_round_trip_and_tolerance():
    s = summarise(record([(0, LONG)], [edit(1)]))[0]
    assert TaskSummary.from_dict(s.to_dict()) == s
    got = TaskSummary.from_dict({"session_id": "x", "title": "t", "future": 1})
    assert got.session_id == "x" and got.kind == "no_edits" and got.last_test == "none" and got.index == 0
    assert got.repo is None and got.prompts == 0


def test_task_dataclass_fields():
    t = Task(index=0, started_at="a", ended_at="b", title="t", prompts=[], tool_calls=[])
    assert t.title == "t"


def test_split_is_fast_on_a_huge_session():
    prompts = [(i * 10, f"request number {i} with enough words to count") for i in range(500)]
    calls = [(i * 0.25, "Read", {"file_path": f"/w/f{i % 50}.py"}, "a1" if i % 3 == 0 else None) for i in range(20000)]
    rec = record(prompts, calls)
    start = time.perf_counter()
    tasks = split_tasks(rec)
    assert time.perf_counter() - start < 1.0
    assert sum(len(t.tool_calls) for t in tasks) == 20000


def test_request_starting_with_a_single_letter_word_is_not_a_confirmation():
    from kaizen.tasks import GLUE

    assert GLUE.match("a new feature for the app please") is None
    assert GLUE.match("s3 bucket needs a lifecycle rule") is None
    assert GLUE.match("sim, pode seguir") is not None
