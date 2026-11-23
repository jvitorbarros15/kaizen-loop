import contextlib
import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from kaizen.record.model import RunRecord, Usage
from kaizen.redact import find_secrets, redact_obj
from kaizen.tasks import TaskSummary, summarise

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_SUSPECT = re.compile(r"\[REDACTED:[^\]]*\]|[A-Za-z0-9+_=-]{24,}")
_SKIP_PREFIXES = ("toolu_", "srvtoolu_", "msg_", "req_")
_HEX = re.compile(r"[0-9a-fA-F]+")
_INSERT_TASK = "INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    session_id TEXT PRIMARY KEY, repo TEXT, started_at TEXT, ended_at TEXT,
    total_tokens INTEGER, cost_usd REAL
);
CREATE TABLE IF NOT EXISTS scores (
    session_id TEXT PRIMARY KEY, json TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS human_grades (
    session_id TEXT PRIMARY KEY, grade REAL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    session_id TEXT, idx INTEGER, repo TEXT, started_at TEXT, ended_at TEXT, title TEXT,
    prompts INTEGER, tool_calls INTEGER, files_edited INTEGER, kind TEXT, last_test TEXT,
    PRIMARY KEY (session_id, idx)
);
"""


def kaizen_home() -> Path:
    env = os.environ.get("KAIZEN_HOME")
    home = Path(env) if env else Path.home() / ".kaizen"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(data: dict) -> tuple:
    total = sum(Usage.from_dict(u).total for u in data["usage_by_model"].values())
    return (data["session_id"], data["repo"], data["started_at"], data["ended_at"], total, data["cost_usd"])


def _task_rows(data: dict) -> list[tuple]:
    return [
        (t.session_id, t.index, t.repo, t.started_at, t.ended_at, t.title, t.prompts, t.tool_calls,
         t.files_edited, t.kind, t.last_test)
        for t in summarise(RunRecord.from_dict(data))
    ]


def _suspect_previews(text: str, seen: list[str]) -> list[str]:
    previews = []
    for m in _SUSPECT.finditer(text):
        token = m.group()
        if token.startswith(("[", *_SKIP_PREFIXES)) or _HEX.fullmatch(token):
            continue
        if not (re.search(r"[a-z]", token) and re.search(r"[A-Z]", token) and re.search(r"[0-9]", token)):
            continue
        if token not in seen:
            seen.append(token)
            previews.append(f"{token[:4]}…({len(token)} chars)")
    return previews


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else kaizen_home()
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "ledger.db"
        with contextlib.closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
        with contextlib.closing(self._connect()) as db, db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    def _run_path(self, session_id: str) -> Path:
        return self.runs_dir / f"{_UNSAFE.sub('_', session_id) or 'unknown'}.json"

    def _run_files(self) -> list[Path]:
        return sorted(p for p in self.runs_dir.iterdir() if p.is_file())

    def save_run(self, record: RunRecord) -> None:
        data = redact_obj(record.to_dict())
        text = json.dumps(data, ensure_ascii=False, indent=2)
        path = self._run_path(data["session_id"])
        changed = path.exists() and path.read_text(encoding="utf-8") != text
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        with contextlib.closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)", _row(data))
            db.execute("DELETE FROM tasks WHERE session_id = ?", (data["session_id"],))
            db.executemany(_INSERT_TASK, _task_rows(data))
            if changed:
                db.execute("DELETE FROM scores WHERE session_id = ?", (data["session_id"],))

    def rebuild_index(self) -> int:
        rows = []
        task_rows = []
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                row = _row(data)
                found = _task_rows(data)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            rows.append(row)
            task_rows.extend(found)
        with contextlib.closing(self._connect()) as db, db:
            db.execute("DELETE FROM runs")
            db.execute("DELETE FROM tasks")
            db.executemany(_INSERT_TASK, task_rows)
            db.executemany("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def pending_scores(self) -> list[str]:
        sql = (
            "SELECT session_id FROM runs WHERE session_id NOT IN (SELECT session_id FROM scores) "
            "ORDER BY started_at DESC, session_id"
        )
        with contextlib.closing(self._connect()) as db, db:
            return [row[0] for row in db.execute(sql)]

    def get_run(self, session_id: str) -> RunRecord | None:
        path = self._run_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return RunRecord.from_dict(data) if isinstance(data, dict) else None

    def list_runs(self, repo: str | None = None, limit: int | None = None) -> list[RunRecord]:
        sql = "SELECT session_id FROM runs"
        params: list[str] = []
        if repo is not None:
            sql += " WHERE repo = ?"
            params.append(repo)
        sql += " ORDER BY started_at DESC, session_id"
        with contextlib.closing(self._connect()) as db, db:
            ids = [row[0] for row in db.execute(sql, params)]
        runs = []
        for session_id in ids:
            if limit is not None and len(runs) >= limit:
                break
            record = self.get_run(session_id)
            if record is not None:
                runs.append(record)
        return runs

    def list_tasks(self, repo: str | None = None, limit: int | None = None) -> list[TaskSummary]:
        sql = (
            "SELECT session_id, idx, repo, started_at, ended_at, title, prompts, tool_calls, files_edited, kind, "
            "last_test FROM tasks"
        )
        params: list = []
        if repo is not None:
            sql += " WHERE repo = ?"
            params.append(repo)
        sql += " ORDER BY started_at DESC, session_id, idx DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with contextlib.closing(self._connect()) as db, db:
            return [TaskSummary(*row) for row in db.execute(sql, params)]

    def save_score(self, session_id: str, score: dict) -> None:
        with contextlib.closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO scores VALUES (?, ?, ?)",
                (session_id, json.dumps(redact_obj(score)), _now()),
            )

    def get_score(self, session_id: str) -> dict | None:
        with contextlib.closing(self._connect()) as db, db:
            row = db.execute("SELECT json FROM scores WHERE session_id = ?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_human_grade(self, session_id: str, grade: float) -> None:
        with contextlib.closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO human_grades VALUES (?, ?, ?)",
                (session_id, grade, _now()),
            )

    def human_grades(self) -> list[tuple[str, float]]:
        with contextlib.closing(self._connect()) as db, db:
            return [
                (sid, grade)
                for sid, grade in db.execute(
                    "SELECT session_id, grade FROM human_grades ORDER BY created_at, rowid"
                )
            ]

    def audit(self) -> list[tuple[str, str]]:
        hits = []
        for path in self._run_files():
            kinds = find_secrets(path.read_text(encoding="utf-8"))
            hits.extend((path.name, kind) for kind in dict.fromkeys(kinds))
        kinds: set[str] = set()
        with contextlib.closing(self._connect()) as db, db:
            for table in ("runs", "scores", "human_grades", "tasks"):
                for row in db.execute(f"SELECT * FROM {table}"):
                    for value in row:
                        if isinstance(value, str):
                            kinds.update(find_secrets(value))
        hits.extend(("ledger.db", kind) for kind in sorted(kinds))
        return hits

    def audit_suspects(self) -> list[tuple[str, str]]:
        suspects = []
        for path in self._run_files():
            suspects.extend((path.name, p) for p in _suspect_previews(path.read_text(encoding="utf-8"), []))
        seen: list[str] = []
        with contextlib.closing(self._connect()) as db, db:
            for table in ("runs", "scores", "human_grades", "tasks"):
                for row in db.execute(f"SELECT * FROM {table}"):
                    for value in row:
                        if isinstance(value, str):
                            suspects.extend(("ledger.db", p) for p in _suspect_previews(value, seen))
        return suspects

    def file_count(self) -> int:
        return len(list(self.runs_dir.glob("*.json"))) + 1
