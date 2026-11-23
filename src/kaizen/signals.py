import re
from dataclasses import asdict, dataclass, field

from kaizen.record.model import RunRecord

SHELL_TOOLS = {"Bash", "PowerShell"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
LAUNCHERS = [
    ("uv", "run"),
    ("poetry", "run"),
    ("pipenv", "run"),
    ("pnpm", "exec"),
    ("python", "-m"),
    ("python3", "-m"),
    ("py", "-m"),
    ("npx",),
    ("yarn",),
]
RUNNERS = [
    ("pytest",),
    ("npm", "test"),
    ("pnpm", "test"),
    ("yarn", "test"),
    ("vitest",),
    ("jest",),
    ("go", "test"),
    ("cargo", "test"),
    ("dotnet", "test"),
    ("mvn", "test"),
    ("gradle", "test"),
    ("./gradlew", "test"),
]
SCRIPT_RUNNERS = [("npm", "run"), ("pnpm", "run")]
TEST_SCRIPT = re.compile(r"^test($|[:_.-])")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WINDOWS_PATH = re.compile(r"^([A-Za-z]:[\\/]|\\\\)")


@dataclass
class TestRun:
    __test__ = False
    command: str
    passed: bool


@dataclass
class Signals:
    test_runs: list[TestRun] = field(default_factory=list)
    tests_passed_last: bool | None = None
    reread_count: int = 0
    reread_files: dict[str, int] = field(default_factory=dict)
    retry_count: int = 0
    tool_error_count: int = 0
    interruptions: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    pr_outcome: str | None = None
    corrections: list[str] = field(default_factory=list)
    strength: str = "weak"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Signals":
        d = dict(d)
        d["test_runs"] = [TestRun(**t) for t in d["test_runs"]]
        return cls(**d)


def strength_of(signals: Signals) -> str:
    if (
        signals.test_runs
        or signals.pr_outcome is not None
        or signals.corrections
        or signals.interruptions > 0
    ):
        return "strong"
    return "weak"


def split_segments(command: str) -> list[str]:
    segments = []
    cur = []
    quote = None
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if quote:
            cur.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                cur.append(command[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in ";|\n":
            segments.append("".join(cur))
            cur = []
            if c == "|" and command[i + 1 : i + 2] == "|":
                i += 1
        elif c == "&" and command[i + 1 : i + 2] == "&":
            segments.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
        i += 1
    segments.append("".join(cur))
    return segments


def starts_with(tokens: list[str], prefix: tuple[str, ...]) -> bool:
    return tuple(tokens[: len(prefix)]) == prefix


def is_test_segment(segment: str) -> bool:
    tokens = segment.split()
    while tokens and ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    while tokens:
        if any(starts_with(tokens, r) for r in RUNNERS):
            return True
        if any(starts_with(tokens, r) for r in SCRIPT_RUNNERS):
            return len(tokens) > 2 and bool(TEST_SCRIPT.match(tokens[2]))
        for launcher in LAUNCHERS:
            if starts_with(tokens, launcher):
                tokens = tokens[len(launcher) :]
                break
        else:
            return False
    return False


def is_test_command(command: str) -> bool:
    return any(is_test_segment(s) for s in split_segments(command))


def normalise_path(path: str) -> str:
    p = path.replace("\\", "/")
    return p.lower() if WINDOWS_PATH.match(path) else p


def extract_signals(record: RunRecord) -> Signals:
    test_runs: list[TestRun] = []
    reread_files: dict[str, int] = {}
    original: dict[str, str] = {}
    reads: dict[str, set] = {}
    failed: dict[tuple, int] = {}
    epoch = 0
    retries = 0
    errors = 0

    for tc in record.tool_calls:
        if tc.is_error:
            errors += 1
        name = tc.name
        inp = tc.input if isinstance(tc.input, dict) else {}

        if name in SHELL_TOOLS:
            command = inp.get("command")
            if not isinstance(command, str):
                continue
            key = (tc.agent_id, command)
            if failed.get(key) == epoch:
                retries += 1
            if tc.is_error:
                failed[key] = epoch
            if is_test_command(command):
                passed = tc.exit_code == 0 if tc.exit_code is not None else not tc.is_error
                test_runs.append(TestRun(command[:200], passed))
        elif name == "Read":
            path = inp.get("file_path")
            if tc.is_error or not isinstance(path, str):
                continue
            norm = normalise_path(path)
            original.setdefault(norm, path)
            seen = reads.setdefault(norm, set())
            rkey = (tc.agent_id, repr(inp.get("offset")), repr(inp.get("limit")))
            if rkey in seen:
                reread_files[original[norm]] = reread_files.get(original[norm], 0) + 1
            else:
                seen.add(rkey)
        elif name in WRITE_TOOLS:
            epoch += 1
            path = inp.get("file_path", inp.get("notebook_path"))
            if isinstance(path, str):
                reads.pop(normalise_path(path), None)

    signals = Signals(
        test_runs=test_runs,
        tests_passed_last=test_runs[-1].passed if test_runs else None,
        reread_count=sum(reread_files.values()),
        reread_files=reread_files,
        retry_count=retries,
        tool_error_count=errors,
        interruptions=record.interruptions,
        total_tokens=sum(u.total for u in record.usage_by_model.values()),
        cost_usd=record.cost_usd,
    )
    signals.strength = strength_of(signals)
    return signals
