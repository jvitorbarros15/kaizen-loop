import argparse
import contextlib
import json
import sys
from pathlib import Path

from kaizen import __version__
from kaizen.config import load_config
from kaizen.external import run_subprocess
from kaizen.pipeline import (
    build_run_packet,
    find_transcripts,
    record_session,
    refresh_pr_outcomes,
    score_run,
    scored_runs,
)
from kaizen.report import calibration_summary, render_report
from kaizen.store import Store

RUNNER = run_subprocess
SUSPECTS_SHOWN = 20


def read_line(prompt: str) -> str:
    return input(prompt)


def say(text: str = "") -> None:
    with contextlib.suppress(AttributeError, ValueError, OSError):
        sys.stdout.reconfigure(errors="replace")
    print(text)


def cmd_record(args) -> int:
    say(f"{record_session(Path(args.transcript), Store())} recorded")
    return 0


def cmd_import(args) -> int:
    store = Store()
    transcripts = find_transcripts(Path(args.projects_dir))
    if args.limit is not None:
        transcripts = transcripts[: args.limit]
    recorded = skipped = scratch = 0
    for path in transcripts:
        if store.get_run(path.stem) is not None:
            skipped += 1
        elif record_session(path, store, skip_temp=True) is None:
            scratch += 1
        else:
            recorded += 1
    line = f"Recorded {recorded} sessions ({skipped} already in the store)"
    if scratch:
        line += f"; skipped {scratch} run from temporary folders"
    say(line)
    return 0


def _score_line(session_id: str, saved: dict) -> str:
    score = saved["score"]
    total = "-" if score["total"] is None else f"{score['total']:.1f}"
    verdict = saved["verdict"]
    backend = verdict["backend"] or "unavailable"
    if verdict.get("abstained"):
        backend += " (abstained)"
    return f"{session_id}  {total}  {score['strength']}  {score['evidence']}  {backend}"


def cmd_score(args) -> int:
    store = Store()
    config = load_config()
    if args.show_packet:
        if not args.session_id:
            say("--show-packet needs a SESSION_ID")
            return 2
        built = build_run_packet(args.session_id, store, config)
        if built is None:
            say(f"No run {args.session_id} in the store")
            return 1
        packet, backends = built
        say(f"Backends that would be used: {', '.join(backends) or 'none'}")
        say(json.dumps(packet, indent=2))
        return 0
    ids = [args.session_id] if args.session_id else store.pending_scores()[: args.limit]
    for session_id in ids:
        saved = score_run(session_id, store, config, RUNNER)
        if saved is None:
            say(f"No run {session_id} in the store")
            return 1
        say(_score_line(session_id, saved))
    return 0


def cmd_refresh(args) -> int:
    say(f"{refresh_pr_outcomes(Store(), RUNNER)} PR outcomes changed")
    return 0


def cmd_report(args) -> int:
    say(render_report(Store(), args.last))
    return 0


def _show_for_grading(index: int, total: int, session_id: str, packet: dict, verdict: dict) -> None:
    say(f"\n[{index}/{total}] {session_id}")
    say(f"Task: {packet['task']}")
    say(f"Changed files: {', '.join(packet['changed_files']) or 'none'}")
    outcome = {True: "passed", False: "failed", None: "unknown"}
    for label, key in (("Tests", "test_runs"), ("Checks", "check_runs")):
        runs = [f"{r['command']} -> {outcome[r['passed']]}" for r in packet[key]]
        say(f"{label}: {'; '.join(runs) or 'none'}")
    say("Judge reasons:")
    for reason in verdict.get("reasons") or []:
        say(f"  {reason}")


def cmd_calibrate(args) -> int:
    store = Store()
    config = load_config()
    graded = {sid for sid, _ in store.human_grades()}
    todo = [
        (sid, saved)
        for sid, saved in scored_runs(store)
        if sid not in graded and (saved.get("verdict") or {}).get("quality") is not None
    ][: args.n]
    for index, (sid, saved) in enumerate(todo, 1):
        built = build_run_packet(sid, store, config)
        if built is None:
            continue
        packet = built[0]
        if saved.get("corrections_known"):
            packet["corrections"] = saved["signals"].get("corrections") or []
        _show_for_grading(index, len(todo), sid, packet, saved["verdict"])
        while True:
            try:
                answer = read_line("Your grade 0-10 (blank or s skips, q stops): ").strip().lower()
            except EOFError:
                answer = "q"
            if answer in ("", "s", "q"):
                break
            try:
                grade = float(answer)
            except ValueError:
                grade = -1.0
            if 0 <= grade <= 10:
                store.save_human_grade(sid, grade)
                break
            say("Enter a number from 0 to 10.")
        if answer == "q":
            break
    scores = dict(scored_runs(store))
    pairs = []
    abstained = 0
    for sid, grade in store.human_grades():
        quality = (scores.get(sid, {}).get("verdict") or {}).get("quality")
        if quality is None:
            abstained += scores.get(sid) is not None
        else:
            pairs.append((quality, grade))
    say("")
    say(calibration_summary(pairs, abstained))
    return 0


def cmd_audit(args) -> int:
    store = Store()
    hits = store.audit()
    for name, kind in hits:
        say(f"{name}: {kind}")
    if not hits:
        say(f"No known secret patterns in {store.file_count()} files")
    suspects = store.audit_suspects()
    if suspects:
        say(f"Warning: {len(suspects)} strings look like secrets but match no known pattern")
        for name, preview in suspects[:SUSPECTS_SHOWN]:
            say(f"  {name}: {preview}")
    return 1 if hits else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kaizen")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("record", help="record one transcript")
    p.add_argument("--transcript", required=True)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("import", help="record every transcript under the projects directory")
    p.add_argument("--limit", type=int)
    p.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("score", help="score one session or every pending one")
    p.add_argument("session_id", nargs="?")
    p.add_argument("--pending", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--show-packet", action="store_true")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("refresh", help="refresh PR outcomes")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("report", help="print the report")
    p.add_argument("--last", type=int, default=20)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("calibrate", help="grade runs blind and compare with the judge")
    p.add_argument("--n", type=int, default=10)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("audit", help="look for secrets in the store")
    p.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"kaizen {__version__}")
        return 0
    if args.command is None:
        parser.print_help()
        return 2
    return args.func(args)
