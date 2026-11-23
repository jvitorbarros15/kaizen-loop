import argparse
import contextlib
import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from kaizen import __version__
from kaizen.config import load_config
from kaizen.external import run_subprocess
from kaizen.pipeline import (
    build_run_packet,
    find_transcripts,
    record_session,
    refresh_pr_outcomes,
    run_end_times,
    score_run,
    scored_runs,
)
from kaizen.redact import redact
from kaizen.report import calibration_summary, render_report
from kaizen.store import Store, kaizen_home

RUNNER = run_subprocess
SUSPECTS_SHOWN = 20
SCREEN_WIDTH = 100
LABEL_WIDTH = 10
TASK_SHOWN = 200
FILES_SHOWN = 5
LIST_SHOWN = 3
REASON_SHOWN = 90
BIG_GAP = 2.0


def read_line(prompt: str) -> str:
    return input(prompt)


def say(text: str = "") -> None:
    with contextlib.suppress(AttributeError, ValueError, OSError):
        sys.stdout.reconfigure(errors="replace")
    print(text)


STYLES = {"dim": "2", "bold": "1", "red": "31", "green": "32", "yellow": "33"}


def now() -> datetime:
    return datetime.now(UTC)


def use_colour() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def paint(text: str, style: str) -> str:
    if not use_colour():
        return text
    return f"\x1b[{STYLES[style]}m{text}\x1b[0m"


def log_hook(error: str, message: str) -> None:
    with contextlib.suppress(Exception):
        text = " ".join(redact(str(message)).split())[:200]
        line = f"{datetime.now(UTC).isoformat()} {error} {text}\n"
        with open(kaizen_home() / "hook.log", "a", encoding="utf-8") as f:
            f.write(line)


def cmd_record(args) -> int:
    try:
        session_id = record_session(Path(args.transcript), Store(), skip_temp=args.skip_temp)
    except Exception as exc:
        log_hook(type(exc).__name__, f"record failed: {exc}")
        return 1
    if session_id is None:
        return 0
    say(f"{session_id} recorded")
    return 0


def detached_options() -> dict:
    devnull = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        return {**devnull, "creationflags": flags}
    return {**devnull, "start_new_session": True}


def hook_session_end(stdin, spawn: Callable[..., object] = subprocess.Popen) -> int:
    try:
        if os.environ.get("KAIZEN_INTERNAL"):
            return 0
        try:
            payload = json.loads(stdin.read())
        except ValueError as exc:
            log_hook(type(exc).__name__, f"hook input is not JSON: {exc}")
            return 0
        path = payload.get("transcript_path") if isinstance(payload, dict) else None
        if not isinstance(path, str) or not path:
            log_hook("BadPayload", "no transcript_path string in hook input")
            return 0
        if not Path(path).is_file():
            log_hook("MissingTranscript", "transcript file does not exist")
            return 0
        spawn(
            [sys.executable, "-m", "kaizen.cli", "record", "--transcript", path, "--skip-temp"],
            **detached_options(),
        )
    except Exception as exc:
        log_hook(type(exc).__name__, str(exc))
    return 0


def cmd_hook(args) -> int:
    return hook_session_end(sys.stdin)


def cmd_import(args) -> int:
    store = Store()
    transcripts = find_transcripts(Path(args.projects_dir))
    if args.limit is not None:
        transcripts = transcripts[: args.limit]
    recorded = skipped = scratch = 0
    for path in transcripts:
        if not args.all and store.get_run(path.stem) is not None:
            skipped += 1
        elif record_session(path, store, skip_temp=True) is None:
            scratch += 1
        else:
            recorded += 1
    if args.all:
        line = f"Re-recorded {recorded} sessions"
    else:
        line = f"Recorded {recorded} sessions ({skipped} already in the store)"
    if scratch:
        line += f"; skipped {scratch} run from temporary folders"
    say(line)
    return 0


def _score_line(session_id: str, saved: dict) -> str:
    score = saved["score"]
    total = "-" if score["total"] is None else f"{score['total']:.1f}"
    verdict = saved["verdict"]
    backend = verdict["backend"] or ("nothing to grade" if verdict.get("abstained") else "unavailable")
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


def _flat(text: str) -> str:
    return " ".join(str(text).split())


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _row(label: str, body: str) -> str:
    gap = " " * max(LABEL_WIDTH - len(label), 1)
    return paint(label, "dim") + gap + _cut(body, SCREEN_WIDTH - max(len(label) + 1, LABEL_WIDTH))


def _runs_line(runs: list[dict]) -> str:
    if not runs:
        return "none"
    names = {True: "passed", False: "failed", None: "unknown"}
    counts = [f"{sum(r['passed'] is key for r in runs)} {name}" for key, name in names.items()]
    parts = ", ".join(c for c in counts if not c.startswith("0 "))
    noun = "run" if len(runs) == 1 else "runs"
    return f"{len(runs)} {noun}: {parts}  (last: {names[runs[-1]['passed']]})"


def _list_rows(label: str, items: list[str]) -> list[str]:
    if not items:
        return [_row(label, "none")]
    shown = [f"- {_cut(_flat(item), SCREEN_WIDTH - LABEL_WIDTH - 2)}" for item in items[:LIST_SHOWN]]
    margin = " " * LABEL_WIDTH
    if len(label) < LABEL_WIDTH:
        rows = [_row(label, shown[0]), *(margin + line for line in shown[1:])]
    else:
        rows = [paint(label, "dim"), *(margin + line for line in shown)]
    if len(items) > LIST_SHOWN:
        rows.append(f"{margin}+{len(items) - LIST_SHOWN} more")
    return rows


def _files_line(changed: list[str]) -> str:
    names = list(dict.fromkeys(PurePosixPath(f).name or f for f in changed))
    if not names:
        return "none"
    line = ", ".join(names[:FILES_SHOWN])
    return line + f", +{len(names) - FILES_SHOWN} more" if len(names) > FILES_SHOWN else line


def _task_rows(task: str) -> list[str]:
    text = _flat(task[:TASK_SHOWN])
    lines = textwrap.wrap(text, SCREEN_WIDTH - LABEL_WIDTH, max_lines=2, placeholder="...")
    if not lines:
        return [_row("Task", "none")]
    return [_row("Task", lines[0]), *(" " * LABEL_WIDTH + line for line in lines[1:])]


def _clock(ended_at: datetime | None) -> str:
    return ended_at.astimezone().strftime("%H:%M") if ended_at else "unknown"


def _show_for_grading(index: int, total: int, project: str, ended_at: datetime | None, packet: dict) -> None:
    calls = packet["counts"]["tool_calls"]
    header = f"[{index}/{total}]  {project}  ·  ended {_clock(ended_at)}  ·  {calls} tool call{'s' * (calls != 1)}"
    say("-" * 60)
    say(paint(_cut(header, SCREEN_WIDTH), "bold"))
    for line in _task_rows(packet["task"]):
        say(line)
    say(_row("Files", _files_line(packet["changed_files"])))
    say(_row("Tests", _runs_line(packet["test_runs"])))
    say(_row("Checks", _runs_line(packet["check_runs"])))
    for line in _list_rows("Asked later", packet["later_requests"]):
        say(line)
    for line in _list_rows("Corrected", packet.get("corrections") or []):
        say(line)


def _show_comparison(grade: float, verdict: dict) -> None:
    quality = verdict["quality"]
    gap = round(abs(grade - quality), 1)
    gap_text = paint(f"{gap:.1f}", "red") if gap > BIG_GAP else f"{gap:.1f}"
    say(f"You {paint(f'{grade:.1f}', 'green')}   Judge {paint(f'{quality:.1f}', 'yellow')}   difference {gap_text}")
    split = [reason.partition(": ") for reason in verdict.get("reasons") or []]
    width = max((len(name) for name, sep, _ in split if sep), default=0)
    for name, sep, text in split:
        if sep:
            say(f"  {name.ljust(width)}  {_cut(_flat(text), REASON_SHOWN)}")
        else:
            say(f"  {_cut(_flat(name), REASON_SHOWN)}")


def _parse_time(text: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text or "")
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def cmd_calibrate(args) -> int:
    store = Store()
    config = load_config()
    graded = {sid for sid, _ in store.human_grades()}
    ends = run_end_times(store)
    cutoff = now() - timedelta(hours=args.hours)
    recent = []
    for sid, saved in scored_runs(store):
        ended = _parse_time(ends.get(sid))
        has_quality = (saved.get("verdict") or {}).get("quality") is not None
        if sid not in graded and has_quality and ended is not None and ended >= cutoff:
            recent.append((ended, sid, saved))
    recent.sort(key=lambda item: (item[0], item[1]), reverse=True)
    todo = recent[: args.n]
    if not todo:
        say(
            f"No scored session ended in the last {args.hours:g} hours and still waits for your grade; "
            "work in Claude Code, then run kaizen score --pending."
        )
    for index, (ended, sid, saved) in enumerate(todo, 1):
        built = build_run_packet(sid, store, config)
        if built is None:
            continue
        packet = built[0]
        if saved.get("corrections_known"):
            packet["corrections"] = saved["signals"].get("corrections") or []
        _show_for_grading(index, len(todo), saved.get("repo") or sid, ended, packet)
        while True:
            try:
                answer = read_line("Your grade 0-10 (Enter skips, q stops): ").strip().lower()
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
                _show_comparison(grade, saved["verdict"])
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
    p.add_argument("--skip-temp", action="store_true")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("hook", help="entry points for Claude Code hooks")
    p.add_argument("event", choices=["session-end"])
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("import", help="record every transcript under the projects directory")
    p.add_argument("--limit", type=int)
    p.add_argument("--all", action="store_true", help="re-record sessions already in the store")
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
    p.add_argument("--hours", type=float, default=24)
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


if __name__ == "__main__":
    raise SystemExit(main())
