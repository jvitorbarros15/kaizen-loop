import contextlib
import sqlite3
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from kaizen.config import load_config
from kaizen.external import Runner, extract_corrections, fetch_pr_outcome, run_subprocess
from kaizen.judge.judge import Verdict, backends_for, judge
from kaizen.judge.packet import build_packet
from kaizen.record.parse import parse_session
from kaizen.score import RunStats, baseline_for, compute_score, stats_of
from kaizen.signals import Signals, extract_signals, strength_of
from kaizen.store import Store


def find_transcripts(projects_dir: Path) -> list[Path]:
    files = [p for p in Path(projects_dir).glob("*/*.jsonl") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _in_temp_dir(cwd: str) -> bool:
    def norm(p: str) -> str:
        return p.replace(chr(92), "/").lower().rstrip("/")

    return bool(cwd) and (norm(cwd) + "/").startswith(norm(tempfile.gettempdir()) + "/")


def record_session(transcript: Path, store: Store, skip_temp: bool = False) -> str | None:
    record = parse_session(transcript)
    if skip_temp and _in_temp_dir(record.cwd):
        return None
    store.save_run(record)
    return record.session_id


def scored_ids(store: Store) -> list[str]:
    with contextlib.closing(sqlite3.connect(store.db_path, timeout=30)) as db, db:
        return [row[0] for row in db.execute("SELECT session_id FROM scores")]


def run_end_times(store: Store) -> dict[str, str]:
    with contextlib.closing(sqlite3.connect(store.db_path, timeout=30)) as db, db:
        return {row[0]: row[1] for row in db.execute("SELECT session_id, ended_at FROM runs")}


def scored_runs(store: Store) -> list[tuple[str, dict]]:
    pairs = [(sid, score) for sid in scored_ids(store) if (score := store.get_score(sid)) is not None]
    return sorted(pairs, key=lambda p: (p[1].get("started_at") or "", p[0]), reverse=True)


def _history(store: Store, exclude: str) -> list[RunStats]:
    names = {f.name for f in fields(RunStats)}
    history = []
    for sid, saved in scored_runs(store):
        stats = saved.get("stats")
        if sid != exclude and isinstance(stats, dict) and names <= set(stats):
            history.append(RunStats(**{k: stats[k] for k in names}))
    return history


def build_run_packet(session_id: str, store: Store, config: dict) -> tuple[dict, list[str]] | None:
    record = store.get_run(session_id)
    if record is None:
        return None
    signals = extract_signals(record)
    backends, include_code = backends_for(record.repo, config)
    packet = build_packet(record, signals, include_code)
    packet["corrections"] = None
    return packet, backends


def score_run(session_id: str, store: Store, config: dict, runner: Runner = run_subprocess) -> dict | None:
    record = store.get_run(session_id)
    if record is None:
        return None
    signals = extract_signals(record)
    corrections_known = False
    if config["corrections"]["enabled"]:
        found = extract_corrections(record.user_messages, runner)
        if found is not None:
            signals.corrections = found
            corrections_known = True
    if record.pr_urls:
        signals.pr_outcome = fetch_pr_outcome(record.pr_urls[0], runner)
    signals.strength = strength_of(signals)
    backends, include_code = backends_for(record.repo, config)
    packet = build_packet(record, signals, include_code)
    if not corrections_known:
        packet["corrections"] = None
    verdict = judge(packet, backends, runner)
    stats = stats_of(record, signals)
    baseline = baseline_for(stats, _history(store, session_id))
    score = compute_score(signals, stats, verdict.quality, verdict.backend, baseline, config["score"])
    saved = {
        "score": score.to_dict(),
        "signals": signals.to_dict(),
        "verdict": verdict.to_dict(),
        "stats": asdict(stats),
        "corrections_known": corrections_known,
        "repo": record.repo,
        "started_at": record.started_at,
    }
    store.save_score(session_id, saved)
    return saved


def refresh_pr_outcomes(store: Store, runner: Runner = run_subprocess) -> int:
    config = load_config(store.root)
    changed = 0
    for sid, saved in scored_runs(store):
        signals = Signals.from_dict(saved.get("signals") or {})
        if signals.pr_outcome not in (None, "open") or not isinstance(saved.get("stats"), dict):
            continue
        record = store.get_run(sid)
        if record is None or not record.pr_urls:
            continue
        outcome = fetch_pr_outcome(record.pr_urls[0], runner)
        if outcome is None or outcome == signals.pr_outcome:
            continue
        signals.pr_outcome = outcome
        signals.strength = strength_of(signals)
        stats = RunStats(**saved["stats"])
        verdict = Verdict.from_dict(saved.get("verdict") or {})
        baseline = baseline_for(stats, _history(store, sid))
        score = compute_score(signals, stats, verdict.quality, verdict.backend, baseline, config["score"])
        saved.update(score=score.to_dict(), signals=signals.to_dict())
        store.save_score(sid, saved)
        changed += 1
    return changed
