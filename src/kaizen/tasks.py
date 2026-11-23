import re
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime

from kaizen.judge.packet import without_pasted
from kaizen.record.model import RunRecord, ToolCall
from kaizen.signals import SHELL_TOOLS, WRITE_TOOLS, extract_signals, normalise_path

GAP_MINUTES = 45
GLUE_MAX_WORDS = 4
GLUE_CONFIRMATION_MAX_WORDS = 12
TITLE_MAX = 120
TITLE_MIN_WORDS = 6
NO_TITLE = "(no request text)"

GLUE = re.compile(
    r"^(sim|s|yes|y|ok|okay|pode|pode sim|pode seguir|segue|continua|continue|keep going|go|go ahead|vai|isso|"
    r"certo|beleza|blz|fechado|aprovado|approved|merge|pode fazer|faz|do it|sure|yep|yeah|claro|perfeito|"
    r"[0-9]|[a-d])\b",
    re.IGNORECASE,
)
PASTED_ONLY = re.compile(r"^(\[pasted text, [\d,]+ characters\]\s*)+$")
SHIPPING = re.compile(r"\bgit\s+(commit|merge|push)\b|\bgh\s+pr\s+(create|merge)\b")
SLASH_BOUNDARY = re.compile(r"^/(clear|compact)\b")


@dataclass
class Task:
    index: int
    started_at: str
    ended_at: str
    title: str
    prompts: list[str]
    tool_calls: list[ToolCall]


@dataclass
class TaskSummary:
    session_id: str = ""
    index: int = 0
    repo: str | None = None
    started_at: str = ""
    ended_at: str = ""
    title: str = ""
    prompts: int = 0
    tool_calls: int = 0
    files_edited: int = 0
    kind: str = "no_edits"
    last_test: str = "none"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TaskSummary":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class _Open:
    task: Task
    last: float | None
    ended: float | None
    shipped: bool = False


def _time(value) -> float | None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _keys(times: list[str]) -> list[tuple[float, float | None]]:
    prev = float("-inf")
    out = []
    for value in times:
        real = _time(value)
        if real is not None:
            prev = real
        out.append((prev, real))
    return out


def _is_glue(clean: str) -> bool:
    if not clean or PASTED_ONLY.match(clean):
        return True
    words = clean.split()
    return len(words) <= GLUE_MAX_WORDS or (len(words) <= GLUE_CONFIRMATION_MAX_WORDS and bool(GLUE.match(clean)))


def _title(prompts: list[str]) -> str:
    cleaned = [without_pasted(p) for p in prompts]
    chosen = next((c for c in cleaned if len(c.split()) >= TITLE_MIN_WORDS), cleaned[0] if cleaned else "")
    return " ".join(chosen.split())[:TITLE_MAX] or NO_TITLE


def _later(open_task: _Open, raw: str, real: float | None) -> None:
    if real is None:
        return
    if open_task.ended is None or real >= open_task.ended:
        open_task.ended = real
        open_task.task.ended_at = raw


def _whole(record: RunRecord) -> Task:
    return Task(
        index=0,
        started_at=record.started_at,
        ended_at=record.ended_at,
        title=_title(record.user_messages),
        prompts=list(record.user_messages),
        tool_calls=list(record.tool_calls),
    )


def split_tasks(record: RunRecord) -> list[Task]:
    prompts = record.user_messages
    times = record.user_message_times
    if not prompts or len(times) != len(prompts):
        return [_whole(record)]

    pkeys = _keys(times)
    porder = sorted(range(len(prompts)), key=lambda i: pkeys[i][0])
    calls = record.tool_calls
    ckeys = _keys([c.timestamp for c in calls])
    corder = sorted(range(len(calls)), key=lambda i: ckeys[i][0])

    opened: list[_Open] = []
    agent_home: dict[str, _Open] = {}
    lead: list[int] = []

    def add_call(i: int, current: _Open, counts_as_shipping: bool) -> None:
        call = calls[i]
        real = ckeys[i][1]
        if call.agent_id is not None:
            home = agent_home.setdefault(call.agent_id, current)
            home.task.tool_calls.append(call)
            _later(home, call.timestamp, real)
            return
        current.task.tool_calls.append(call)
        _later(current, call.timestamp, real)
        if real is not None and (current.last is None or real > current.last):
            current.last = real
        if counts_as_shipping and call.name in SHELL_TOOLS:
            command = call.input.get("command") if isinstance(call.input, dict) else None
            if isinstance(command, str) and SHIPPING.search(command):
                current.shipped = True

    def open_task(i: int) -> _Open:
        task = Task(
            index=len(opened),
            started_at=times[i],
            ended_at=times[i],
            title="",
            prompts=[prompts[i]],
            tool_calls=[],
        )
        fresh = _Open(task, pkeys[i][1], pkeys[i][1])
        opened.append(fresh)
        return fresh

    ci = 0
    current: _Open | None = None
    for i in porder:
        key, real = pkeys[i]
        while ci < len(corder) and ckeys[corder[ci]][0] < key:
            if current is None:
                lead.append(corder[ci])
            else:
                add_call(corder[ci], current, True)
            ci += 1
        text = prompts[i]
        if current is None:
            current = open_task(i)
            for j in lead:
                add_call(j, current, False)
            continue
        gap = real is not None and current.last is not None and (real - current.last) / 60 >= GAP_MINUTES
        if SLASH_BOUNDARY.match(text.lstrip()) or (
            not _is_glue(without_pasted(text)) and (gap or current.shipped)
        ):
            current = open_task(i)
            continue
        current.task.prompts.append(text)
        _later(current, times[i], real)
        if real is not None and (current.last is None or real > current.last):
            current.last = real
    while ci < len(corder):
        add_call(corder[ci], current, True)
        ci += 1

    for o in opened:
        o.task.title = _title(o.task.prompts)
    return [o.task for o in opened]


def task_view(record: RunRecord, task: Task) -> RunRecord:
    return RunRecord(
        session_id=record.session_id,
        source=record.source,
        cwd=record.cwd,
        repo=record.repo,
        git_branch=record.git_branch,
        agent_version=record.agent_version,
        schema_version=record.schema_version,
        started_at=task.started_at,
        ended_at=task.ended_at,
        user_messages=list(task.prompts),
        tool_calls=list(task.tool_calls),
    )


def _files_edited(task: Task) -> int:
    files = set()
    for call in task.tool_calls:
        if call.name in WRITE_TOOLS and isinstance(call.input, dict):
            path = call.input.get("file_path", call.input.get("notebook_path"))
            if isinstance(path, str):
                files.add(normalise_path(path))
    return len(files)


def summarise(record: RunRecord) -> list[TaskSummary]:
    out = []
    for task in split_tasks(record):
        signals = extract_signals(task_view(record, task))
        edited = _files_edited(task)
        if not edited:
            kind = "no_edits"
        elif signals.test_runs or signals.check_runs:
            kind = "edited_checked"
        else:
            kind = "edited_unchecked"
        if not signals.test_runs:
            last_test = "none"
        else:
            last_test = {True: "passed", False: "failed", None: "unknown"}[signals.tests_passed_last]
        out.append(
            TaskSummary(
                session_id=record.session_id,
                index=task.index,
                repo=record.repo,
                started_at=task.started_at,
                ended_at=task.ended_at,
                title=task.title,
                prompts=len(task.prompts),
                tool_calls=len(task.tool_calls),
                files_edited=edited,
                kind=kind,
                last_test=last_test,
            )
        )
    return out
