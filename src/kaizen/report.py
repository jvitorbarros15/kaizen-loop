from collections import Counter
from statistics import mean, median

from kaizen.pipeline import scored_runs
from kaizen.score import MIN_RUNS
from kaizen.store import Store

AGREE_WITHIN = 2.0
LOWEST_MAX = 5
FILES_MAX = 5
NO_PROJECT = "(no project)"


def agreement(pairs: list[tuple[float, float]]) -> tuple[int, int]:
    return sum(abs(judge - human) <= AGREE_WITHIN for judge, human in pairs), len(pairs)


def calibration_summary(pairs: list[tuple[float, float]], abstained: int) -> str:
    if not pairs:
        return f"There is nothing to compare yet: no run has a judge score and your grade. Abstentions: {abstained}."
    agreeing, total = agreement(pairs)
    constant = median(human for _, human in pairs)
    constant_agreeing = sum(abs(constant - human) <= AGREE_WITHIN for _, human in pairs)
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
        composite = "composite: none, the judge was unavailable"
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


def render_report(store: Store, last: int = 20) -> str:
    pending = len(store.pending_scores())
    runs = [score for _, score in scored_runs(store)[:last]]
    if not runs:
        if pending:
            return f"{_plural(pending, 'run')} recorded, none scored yet. Run `kaizen score --pending`."
        return "Nothing recorded yet. Run `kaizen import` then `kaizen score --pending`."

    head = f"kaizen report - last {len(runs)} scored runs"
    if pending:
        head += f" ({pending} more recorded, not scored yet)"
    out = [head, "", "By project"]

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

    counts = Counter(c.strip().lower() for r in runs for c in _signals(r).get("corrections") or [] if c.strip())
    out += ["", "Repeated corrections (all runs, weak ones included)"]
    repeated = sorted(((c, n) for c, n in counts.items() if n >= 2), key=lambda kv: (-kv[1], kv[0]))
    out += [f'  "{c}"  x{n}' for c, n in repeated] or ["  No correction was repeated in these runs."]
    return "\n".join(out)
