from collections import Counter
from datetime import UTC, datetime, timedelta
from statistics import mean, median

from kaizen.corrections import Group
from kaizen.judge.rubric import RUBRIC_VERSION
from kaizen.pipeline import scored_runs, task_for_rating
from kaizen.score import MIN_RUNS
from kaizen.store import Store
from kaizen.tasks import TaskSummary

AGREE_WITHIN = 2.0
LOWEST_MAX = 5
FILES_MAX = 5
NO_PROJECT = "(no project)"
TASK_LINE_MAX = 110
UNCHECKED_SHOWN = 8
FAILED_SHOWN = 5
EXACT_NOTES = {
    "exact": "the model was not used",
    "exact (model call failed)": "the model call failed",
}
LINE_MAX = 110
GROUPS_MAX = 8
CHECK_NOTE = (
    "This counts tests, type checks, linters and builds the tool recognises; "
    "checking by eye in a browser is not seen."
)


def agreement(pairs: list[tuple[float, float]]) -> tuple[int, int]:
    return sum(abs(judge - human) <= AGREE_WITHIN for judge, human in pairs), len(pairs)


def constant_agreement(pairs: list[tuple[float, float]]) -> tuple[float, int]:
    constant = median(human for _, human in pairs)
    return constant, sum(abs(constant - human) <= AGREE_WITHIN for _, human in pairs)


def calibration_summary(pairs: list[tuple[float, float]], abstained: int) -> str:
    if not pairs:
        return f"There is nothing to compare yet: no run has a judge score and your grade. Abstentions: {abstained}."
    agreeing, total = agreement(pairs)
    constant, constant_agreeing = constant_agreement(pairs)
    return "\n".join(
        [
            f"Judge agrees with you on {agreeing} of {total} runs (within {AGREE_WITHIN:g} points).",
            f"A constant judge answering {constant:g} would agree on {constant_agreeing} of {total}.",
            f"Abstentions: {abstained}.",
            "The judge adds information only if its agreement is clearly above the constant judge's.",
        ]
    )


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _signals(run: dict) -> dict:
    return run.get("signals") or {}


def _total(run: dict) -> float | None:
    score = run.get("score") or {}
    if score.get("baseline") == "insufficient":
        return None
    return score.get("total")


def _quality(run: dict) -> float | None:
    return (run.get("verdict") or {}).get("quality")


def _test_state(run: dict) -> str:
    signals = _signals(run)
    if not signals.get("test_runs"):
        return "none"
    passed = signals.get("tests_passed_last")
    return "unknown" if passed is None else "passed" if passed else "failed"


def _sum(runs: list[dict], key: str) -> int:
    return sum(_signals(r).get(key, 0) for r in runs)


def _project_block(name: str, runs: list[dict], width: int) -> list[str]:
    states = Counter(_test_state(r) for r in runs)
    tests = ", ".join(f"{states[s]} {s}" for s in ("passed", "failed", "unknown", "none") if states[s])
    checks = sum(bool(_signals(r).get("check_runs")) for r in runs)
    indent = " " * (2 + width)
    rates = [r["stats"]["waste_rate"] for r in runs if (r.get("stats") or {}).get("waste_rate") is not None]
    tokens = mean(_signals(r).get("total_tokens", 0) for r in runs)
    corrections = sum(len(_signals(r).get("corrections") or []) for r in runs if r.get("corrections_known", True))
    lines = [
        f"  {name:<{width}}{_plural(len(runs), 'run')}   tests: {tests}   checks: {_plural(checks, 'run')}",
        f"{indent}waste {mean(rates) if rates else 0:.1f} per 100 calls "
        f"(re-reads {_sum(runs, 'reread_count'):,}, retries {_sum(runs, 'retry_count'):,}, "
        f"tool errors {_sum(runs, 'tool_error_count'):,})",
        f"{indent}tokens {tokens:,.0f} per run   corrections {corrections}   "
        f"interruptions {_sum(runs, 'interruptions'):,}",
    ]
    prs = Counter(_signals(r).get("pr_outcome") for r in runs if _signals(r).get("pr_outcome"))
    if prs:
        outcomes = ", ".join(f"{prs[s]} {s}" for s in ("merged", "open", "closed") if prs[s])
        lines.append(f"{indent}pull requests: {outcomes}")
    qualities = [q for q in map(_quality, runs) if q is not None]
    abstained = sum(bool((r.get("verdict") or {}).get("abstained")) for r in runs)
    missing = len(runs) - len(qualities) - abstained
    judged = (
        f"judge quality {mean(qualities):.1f} avg "
        f"({len(qualities)} graded, {abstained} abstained, {missing} unavailable)"
        if qualities
        else f"judge quality: none ({abstained} abstained, {missing} unavailable)"
    )
    totals = [t for t in map(_total, runs) if t is not None]
    if totals:
        composite = f"composite {mean(totals):.1f} avg ({_plural(len(totals), 'run')} with a baseline)"
    elif any((r.get("score") or {}).get("baseline", "insufficient") != "insufficient" for r in runs):
        composite = "composite: none, no judge score"
    else:
        composite = f"composite: not enough runs for a baseline yet (needs {MIN_RUNS})"
    lines.append(f"{indent}{judged}   {composite}")
    return lines


def _reason(run: dict) -> str:
    signals = _signals(run)
    corrections = len(signals.get("corrections") or []) if run.get("corrections_known", True) else 0
    if signals.get("tests_passed_last") is False:
        return "tests failed at end"
    if corrections:
        return f"{_plural(corrections, 'correction')} from user"
    if signals.get("interruptions"):
        return _plural(signals["interruptions"], "interruption")
    waste = (run.get("stats") or {}).get("waste_rate")
    return f"waste {waste:.1f} per 100 calls" if waste else "no single cause stands out"


def _paint(text: str, style: str) -> str:
    from kaizen.cli import paint

    return paint(text, style)


def _moment(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _heading(text: str, number: int | None = None, after: str = "") -> str:
    if number is None:
        return _paint(text, "bold")
    count = _paint(str(number), "yellow") if number else str(number)
    return _paint(text, "bold") + count + _paint(after, "bold")


def _project_lines(by_project: dict[str, list[TaskSummary]]) -> list[str]:
    order = sorted(by_project, key=lambda n: (-len(by_project[n]), n))
    width = max(len(n) for n in order) + 3
    counts = {n: _plural(len(by_project[n]), "task") for n in order}
    count_width = max(len(c) for c in counts.values()) + 3
    kinds = {n: Counter(t.kind for t in by_project[n]) for n in order}
    plain = {
        n: f"edited {k['edited_checked'] + k['edited_unchecked']}:  {k['edited_checked']} ran a test or check,  "
        f"{k['edited_unchecked']} ran none"
        for n, k in kinds.items()
    }
    edited_width = max(len(p) for p in plain.values()) + 6
    lines = []
    for n in order:
        k = kinds[n]
        none = k["edited_unchecked"]
        shown = plain[n].replace(f"{none} ran none", f"{_paint(str(none), 'yellow') if none else none} ran none")
        pad = " " * (edited_width - len(plain[n]))
        lines.append(f"  {n:<{width}}{counts[n]:<{count_width}}{shown}{pad}no edits {k['no_edits']}")
        states = Counter(t.last_test for t in by_project[n])
        if states["passed"] + states["failed"] + states["unknown"]:
            failed = states["failed"]
            failed_text = _paint(str(failed), "yellow") if failed else str(failed)
            lines.append(
                f"{' ' * (2 + width)}last test in tasks that ran one:  "
                f"{states['passed']} passed, {failed_text} failed, {states['unknown']} unknown"
            )
    return lines


def _task_lines(items: list[TaskSummary], moments: dict[tuple[str, int], datetime], limit: int) -> list[str]:
    shown = items[:limit]
    dates = [moments[(t.session_id, t.index)].astimezone().strftime("%Y-%m-%d %H:%M") for t in shown]
    projects = [t.repo or NO_PROJECT for t in shown]
    files = [_plural(t.files_edited, "file") for t in shown]
    calls = [_plural(t.tool_calls, "call") for t in shown]
    pw, fw, cw = (max(len(x) for x in col) for col in (projects, files, calls))
    lines = []
    for date, project, f, c, t in zip(dates, projects, files, calls, shown, strict=True):
        prefix = f"  {date}  {project:<{pw}}  {f:>{fw}}  {c:>{cw}}   "
        title = " ".join(t.title.split())
        room = TASK_LINE_MAX - len(prefix)
        if len(title) > room:
            title = title[: room - 3].rstrip() + "..."
        lines.append(prefix + title)
    if len(items) > limit:
        lines.append(f"  ... {len(items) - limit} more")
    return lines


def _old_style(store: Store, window: list[TaskSummary]) -> bool:
    sessions = {t.session_id for t in window}
    if len(window) != len(sessions):
        return False
    for session_id in sessions:
        record = store.get_run(session_id)
        if record is None or record.user_message_times:
            return False
    return True


def _task_sections(store: Store, days: int, now: datetime) -> list[str]:
    everything = store.list_tasks()
    cutoff = now - timedelta(days=days)
    moments: dict[tuple[str, int], datetime] = {}
    window = []
    for t in everything:
        moment = _moment(t.started_at)
        if moment is not None and moment >= cutoff:
            moments[(t.session_id, t.index)] = moment
            window.append(t)
    window.sort(key=lambda t: (moments[(t.session_id, t.index)], t.session_id, t.index), reverse=True)
    if everything and not window:
        return [f"No task started in the last {days} days. Use --days to look further back."]
    if not window or _old_style(store, window):
        return ["No task data yet for these sessions. Run kaizen import --all once to rebuild them."]

    sessions = len({t.session_id for t in window})
    counted = f"{_plural(len(window), 'task')} in {_plural(sessions, 'session')}"
    out = [f"kaizen report - tasks from the last {days} days ({counted})"]
    by_project: dict[str, list[TaskSummary]] = {}
    for t in window:
        by_project.setdefault(t.repo or NO_PROJECT, []).append(t)
    out += ["", _heading("Tasks by project"), *_project_lines(by_project)]

    editing = [t for t in window if t.kind != "no_edits"]
    unchecked = [t for t in window if t.kind == "edited_unchecked"]
    out.append("")
    if not editing:
        out += [_heading("Edited files and ran no test or check"), "  No task edited any file in this period."]
    elif not unchecked:
        out += [
            _heading("Edited files and ran no test or check"),
            "  Every task that edited files also ran a test or check. Good.",
        ]
    else:
        tail = f" of {len(editing)} editing tasks, most recent first)"
        out += [
            _heading("Edited files and ran no test or check (", len(unchecked), tail),
            *_task_lines(unchecked, moments, UNCHECKED_SHOWN),
            "  " + CHECK_NOTE,
        ]

    failed = [t for t in window if t.last_test == "failed"]
    out += ["", _heading("Tasks whose last test failed")]
    out += _task_lines(failed, moments, FAILED_SHOWN) if failed else ["  No task ended on a failing test."]
    return out


def _graded_sections(runs: list[dict], pending: int) -> list[str]:
    out = [_heading(f"Graded sessions (last {len(runs)})")]
    if pending:
        out.append(f"  {_plural(pending, 'more session')} recorded, not scored yet. Run kaizen score --pending.")
    out += ["", "By project"]

    projects: dict[str, list[dict]] = {}
    for run in runs:
        projects.setdefault(run.get("repo") or NO_PROJECT, []).append(run)
    order = sorted(projects, key=lambda n: (-len(projects[n]), n))
    width = max(len(n) for n in order) + 3
    for name in order:
        out += _project_block(name, projects[name], width)

    with_evidence = sum((r.get("score") or {}).get("evidence", "none") != "none" for r in runs)
    out += ["", "Evidence"]
    line = f"  {with_evidence} of {len(runs)} runs had a test or check result."
    if with_evidence < len(runs):
        line += f" {len(runs) - with_evidence} had none and cannot count as evidence of quality."
    out.append(line)

    rereads: Counter[str] = Counter()
    for run in runs:
        for path, n in (_signals(run).get("reread_files") or {}).items():
            rereads["/".join(path.replace(chr(92), "/").split("/")[-2:])] += n
    out += ["", "Most re-read files"]
    top = [f"{path} x{n}" for path, n in sorted(rereads.items(), key=lambda kv: (-kv[1], kv[0])) if n > 1]
    out.append("  " + ", ".join(top[:FILES_MAX]) if top else "  No file was re-read more than once.")

    out += ["", "Lowest runs"]
    ranked = sorted((r for r in runs if _total(r) is not None), key=lambda r: (_total(r), r.get("started_at") or ""))
    for run in ranked[:LOWEST_MAX]:
        name = run.get("repo") or NO_PROJECT
        date = (run.get("started_at") or "")[:10]
        out.append(f"  {_total(run):.1f}  {date}  {name:<{width}}{_reason(run)}")
    if not ranked:
        out.append("  No run has a composite score yet.")

    return out


def _correction_lines(groups: tuple[list[Group], str], graded: int) -> list[str]:
    found, path = groups
    out = [_heading(f"What you keep correcting (grouped by meaning, from {_plural(graded, 'graded session')})")]
    rows = [f"  {g.count:>2}x in {_plural(g.sessions, 'session')}" for g in found]
    width = max((len(r) for r in rows), default=0) + 3
    room = LINE_MAX - width - len('e.g. ""')
    for row, g in list(zip(rows, found, strict=True))[:GROUPS_MAX]:
        out.append(f"{row:<{width}}{g.label}")
        for e in g.examples:
            out.append(" " * width + f'e.g. "{e if len(e) <= room else e[: room - 3].rstrip() + "..."}"')
    if len(found) > GROUPS_MAX:
        out.append(f"  ... {len(found) - GROUPS_MAX} more")
    if not found:
        out.append("  No correction repeats yet.")
    if path in EXACT_NOTES:
        out.append(
            f"  Matched on exact wording only ({EXACT_NOTES[path]}), so corrections worded differently "
            "are not grouped together."
        )
    return out


def _fit(text: str, room: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= room else text[: room - 3].rstrip() + "..."


def _lowest_item(verdict: dict) -> str:
    scored = [
        (entry["score"], name, entry.get("reason") or "")
        for name, entry in (verdict.get("items") or {}).items()
        if isinstance(entry, dict) and entry.get("score") is not None
    ]
    if not scored:
        return ""
    _, name, reason = min(scored, key=lambda item: item[0])
    return f"{name}: {reason}" if reason.strip() else name


def _graded_task_lines(store: Store, days: int, now: datetime) -> list[str]:
    cutoff = now - timedelta(days=days)
    seen: set = set()
    everything = []
    window: list[tuple[datetime, dict]] = []
    for key, saved in store.list_task_scores():
        ident = (saved.get("session_id"), saved.get("idx")) if saved.get("session_id") else key
        if ident in seen:
            continue
        seen.add(ident)
        everything.append(saved)
        moment = _moment(saved.get("started_at"))
        if moment is not None and moment >= cutoff:
            window.append((moment, saved))
    if not everything:
        return ["No task has been graded yet. Run kaizen score --tasks."]
    if not window:
        return [f"No task was graded in the last {days} days. Use --days to look further back."]

    graded = [(m, t) for m, t in window if _quality(t) is not None]
    abstained = sum(bool((t.get("verdict") or {}).get("abstained")) for _, t in window)
    out = [_heading(f"Graded tasks ({len(graded)} graded, {abstained} abstained, last {days} days)")]
    if not graded:
        return out + ["  No task has a judge quality in this period."]

    by_project: dict[str, list[float]] = {}
    for _, t in graded:
        by_project.setdefault(t.get("repo") or NO_PROJECT, []).append(_quality(t))
    order = sorted(by_project, key=lambda n: (-len(by_project[n]), n))
    width = max(len(n) for n in order)
    cells = [
        f"{n:<{width}}   {mean(by_project[n]):.1f} avg over {_plural(len(by_project[n]), 'task')}" for n in order
    ]
    joined = "  " + "     ".join(cells)
    out += [joined] if len(joined) <= LINE_MAX else [f"  {c}" for c in cells]

    out.append("Lowest graded tasks")
    lowest = sorted(graded, key=lambda pair: _quality(pair[1]))[:LOWEST_MAX]
    project_width = max(len(t.get("repo") or NO_PROJECT) for _, t in lowest)
    for moment, t in lowest:
        date = moment.astimezone().strftime("%Y-%m-%d")
        prefix = f"  {_quality(t):.1f}  {date}  {(t.get('repo') or NO_PROJECT):<{project_width}}   "
        out.append(prefix + _fit(t.get("title") or "", LINE_MAX - len(prefix)))
        reason = _lowest_item(t.get("verdict") or {})
        if reason:
            out.append("       " + _fit(reason, LINE_MAX - 7))
    return out


def render_report(
    store: Store,
    last: int = 20,
    days: int = 14,
    groups: tuple[list[Group], str] | None = None,
    now: datetime | None = None,
) -> str:
    pending = len(store.pending_scores())
    scored = scored_runs(store)
    if not scored and not pending:
        return "Nothing recorded yet. Run `kaizen import` then `kaizen score --pending`."
    now = now or datetime.now(UTC)
    out = _task_sections(store, days, now)
    runs = [score for _, score in scored[:last]]
    out.append("")
    if runs:
        out += _correction_lines(groups or ([], "model"), len(runs)) + [""]
        out += _graded_task_lines(store, days, now) + [""] + _graded_sections(runs, pending)
    else:
        out += [
            "Corrections are extracted when sessions are graded. Run kaizen score --pending.",
            "",
            *_graded_task_lines(store, days, now),
            "",
            "No session has been graded yet. Run kaizen score --pending.",
        ]
    return "\n".join(out)


CHECK_SIDE_MIN = 5
CHECK_LISTED = 5
HIGH_JUDGE = 7.0
LOW_JUDGE = 3.0
CHECK_NOTE_LAST = (
    "This checks that the judge is consistent with facts it could see. It does not show the judge is right."
)


def _version(saved: dict) -> int:
    version = (saved.get("verdict") or {}).get("rubric_version")
    return version if isinstance(version, int) and not isinstance(version, bool) else 1


def _noun(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _day(saved: dict) -> str:
    started = _moment(saved.get("started_at"))
    return started.astimezone().strftime("%Y-%m-%d") if started else "unknown"


def _where(saved: dict, repo_width: int) -> str:
    title = " ".join(str(saved.get("title") or "").split())
    return f"{_day(saved)}  {(saved.get('repo') or NO_PROJECT).ljust(repo_width)}   {title}"


def _cut_line(text: str) -> str:
    return text if len(text) <= LINE_MAX else text[: LINE_MAX - 3].rstrip() + "..."


def _rated(store: Store, keys: set[str]) -> tuple[dict[str, float], int]:
    rated = {key: grade for key, grade in store.human_grades() if key in keys}
    from_kz: dict[str, float] = {}
    unbound = 0
    for rating in store.list_ratings():
        task = task_for_rating(store, rating)
        if task is None:
            unbound += 1
        elif task.key not in from_kz:
            from_kz[task.key] = rating["grade"]
    return {**rated, **from_kz}, unbound


def _ratings_section(rated: dict[str, float], unbound: int, graded: dict[str, dict]) -> list[str]:
    out = [_paint("Against your ratings (kz and calibrate)", "bold")]
    pairs = [(graded[key]["verdict"]["quality"], grade, graded[key]) for key, grade in rated.items() if key in graded]
    waiting = len(rated) - len(pairs)
    if not rated:
        out.append("  No rated tasks yet. Rate one with kz 7 inside Claude Code, kaizen rate 7, or kaizen calibrate.")
    if pairs:
        numbers = [(judge, human) for judge, human, _ in pairs]
        agreeing, total = agreement(numbers)
        constant, constant_agreeing = constant_agreement(numbers)
        out += [
            f"  Judge agrees with you on {agreeing} of {total} rated tasks (within {AGREE_WITHIN:g} points).",
            f"  A constant judge answering {constant:g} would agree on {constant_agreeing} of {total}.",
        ]
        gaps = sorted(
            (p for p in pairs if abs(p[0] - p[1]) > AGREE_WITHIN),
            key=lambda p: (-abs(p[0] - p[1]), p[2].get("started_at") or ""),
        )[:CHECK_LISTED]
        if gaps:
            width = max(len(g[2].get("repo") or NO_PROJECT) for g in gaps)
            out.append("  Largest gaps")
            out += [
                _cut_line(f"    You {human:.1f}   Judge {judge:.1f}   {_where(saved, width)}")
                for judge, human, saved in gaps
            ]
    if waiting:
        verb = "has" if waiting == 1 else "have"
        out.append(f"  {_noun(waiting, 'rated task', 'rated tasks')} {verb} no judge grade yet.")
    if unbound:
        out.append(f"  {_noun(unbound, 'rating', 'ratings')} could not be tied to a task.")
    return out


def _is_trouble(saved: dict) -> bool:
    signals = saved.get("signals") or {}
    return (
        bool(signals.get("corrections"))
        or saved.get("last_test") == "failed"
        or bool(signals.get("interruptions"))
    )


def _inversion_note(saved: dict) -> str:
    corrections = len((saved.get("signals") or {}).get("corrections") or [])
    reasons = []
    if corrections >= 2:
        reasons.append(f"{corrections} corrections")
    if saved.get("last_test") == "failed":
        reasons.append("a failed last test")
    return " and ".join(reasons)


def _quality_of(saved: dict) -> float:
    return saved["verdict"]["quality"]


def _evidence_section(graded: dict[str, dict]) -> list[str]:
    out = [_paint("Against the evidence the judge was shown", "bold")]
    known = [s for s in graded.values() if s.get("corrections_known")]
    clean = [s for s in known if not _is_trouble(s)]
    trouble = [s for s in known if _is_trouble(s)]
    labels = [
        ("Tasks that went cleanly (no correction, no failed test, no interruption)", clean),
        ("Tasks with trouble (a correction, a failed last test, or an interruption)", trouble),
    ]
    enough = len(clean) >= CHECK_SIDE_MIN and len(trouble) >= CHECK_SIDE_MIN
    wide = max(len(label) for label, _ in labels) + 3
    counts = [_noun(len(group), "task", "tasks") for _, group in labels]
    for (label, group), count in zip(labels, counts, strict=True):
        line = f"  {label.ljust(wide)}{count.rjust(max(map(len, counts)))}"
        if enough:
            line += f"   judge {mean(map(_quality_of, group)):.1f} avg"
        out.append(line)
    left_out = len(graded) - len(known)
    if left_out:
        noun = _noun(left_out, "graded task was", "graded tasks were")
        out.append(f"  {noun} left out because their corrections are unknown.")
    if not enough:
        out.append(f"  Too few tasks on one side to compare; at least {CHECK_SIDE_MIN} are needed on each.")
    else:
        separation = mean(map(_quality_of, clean)) - mean(map(_quality_of, trouble))
        out.append(f"  Separation: {separation:.1f} points.")
        high = sorted(
            (s for s in trouble if _quality_of(s) >= HIGH_JUDGE and _inversion_note(s)),
            key=lambda s: -_quality_of(s),
        )[:CHECK_LISTED]
        low = sorted((s for s in clean if _quality_of(s) <= LOW_JUDGE), key=_quality_of)[:CHECK_LISTED]
        rows = [(f"Judge {_quality_of(s):.1f} with {_inversion_note(s)}", s) for s in high]
        rows += [(f"Judge {_quality_of(s):.1f} on a clean task", s) for s in low]
        if not rows:
            out.append("  Inversions: none.")
        else:
            width = max(len(text) for text, _ in rows)
            repo_width = max(len(s.get("repo") or NO_PROJECT) for _, s in rows)
            out.append("  Inversions")
            out += [_cut_line(f"    {text.ljust(width)}   {_where(s, repo_width)}") for text, s in rows]
    out.append(f"  {CHECK_NOTE_LAST}")
    return out


def render_check(store: Store) -> str:
    saved_rows = store.list_task_scores()
    has_quality = [(key, saved) for key, saved in saved_rows if (saved.get("verdict") or {}).get("quality") is not None]
    graded = {key: saved for key, saved in has_quality if _version(saved) >= RUBRIC_VERSION}
    older = sum(_version(saved) < RUBRIC_VERSION for _, saved in has_quality)
    keys = {key for key, _ in saved_rows} | {t.key for t in store.list_tasks()}
    rated, unbound = _rated(store, keys)
    out = [f"kaizen check-judge - {_noun(len(graded), 'graded task', 'graded tasks')} (rubric {RUBRIC_VERSION})"]
    if older:
        which = "grade from an earlier rubric was" if older == 1 else "grades from an earlier rubric were"
        out.append(f"{older} older {which} left out.")
    out += ["", *_ratings_section(rated, unbound, graded), "", *_evidence_section(graded)]
    return "\n".join(out)
