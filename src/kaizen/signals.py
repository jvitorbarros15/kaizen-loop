import re
from dataclasses import asdict, dataclass, field, fields

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
OPTION_LAUNCHERS = {("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("pnpm", "exec"), ("npx",)}
VALUE_OPTIONS = {
    "--python",
    "-p",
    "--with",
    "--project",
    "--directory",
    "--group",
    "--extra",
    "--env-file",
    "--package",
}
TIMEOUT_VALUE_OPTIONS = {"-k", "-s", "--kill-after", "--signal"}
DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
PACKAGE_MANAGERS = {"npm", "pnpm", "yarn"}
SHELL_KEYWORDS = {"do", "then", "else", "!", "time"}
SHELL_CLOSERS = {"done", "fi", "esac"}
TEST_RUNNERS = [
    ("pytest",),
    ("unittest",),
    ("npm", "test"),
    ("pnpm", "test"),
    ("yarn", "test"),
    ("bun", "test"),
    ("make", "test"),
    ("vitest",),
    ("jest",),
    ("go", "test"),
    ("cargo", "test"),
    ("dotnet", "test"),
    ("mvn", "test"),
    ("gradle", "test"),
    ("./gradlew", "test"),
]
CHECK_RUNNERS = [
    ("tsc",),
    ("mypy",),
    ("pyright",),
    ("ruff", "check"),
    ("eslint",),
    ("cargo", "check"),
    ("cargo", "clippy"),
    ("cargo", "build"),
    ("go", "build"),
    ("go", "vet"),
]
TEST_SCRIPT = re.compile(r"^test($|[:_.-])")
CHECK_SCRIPT = re.compile(r"^(typecheck|type-check|lint|build|check)")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WINDOWS_PATH = re.compile(r"^([A-Za-z]:[\\/]|\\\\)")

FAIL_PATTERNS = (
    r"(?<![\w.])[1-9]\d* failed\b",
    r"(?<![\w.])[1-9]\d* errors?\b",
    r"\bFAILED \(",
    r"^\s*(?:Tests|Test Files|Test Suites):?\s.*\bfailed\b",
    r"^\s*FAIL\b",
    r"^\s*(?:#|ℹ)\s*fail\s+[1-9]\d*",
    r"^\s*✖ failing tests",
    r"--- FAIL",
    r"test result: FAILED",
    r"\bFailed!",
)
PASS_PATTERNS = (
    r"(?<![\w.])[1-9]\d* passed\b",
    r"^OK \(",
    r"^\s*OK\s*$",
    r"^\s*Tests:?\s.*\bpassed\b",
    r"^\s*(?:#|ℹ)\s*fail\s+0\b",
    r"^ok ",
    r"test result: ok",
    r"\bPassed!",
)
FAIL_RE = re.compile("|".join(f"(?:{p})" for p in FAIL_PATTERNS), re.MULTILINE)
PASS_RE = re.compile("|".join(f"(?:{p})" for p in PASS_PATTERNS), re.MULTILINE)


def _known(cls, d: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in names}


@dataclass
class TestRun:
    __test__ = False
    command: str = ""
    passed: bool | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "TestRun":
        return cls(**_known(cls, d))


@dataclass
class Signals:
    test_runs: list[TestRun] = field(default_factory=list)
    check_runs: list[TestRun] = field(default_factory=list)
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
        kwargs = _known(cls, d)
        for key in ("test_runs", "check_runs"):
            if key in kwargs:
                kwargs[key] = [TestRun.from_dict(t) for t in kwargs[key]]
        return cls(**kwargs)


def strength_of(signals: Signals) -> str:
    if (
        signals.test_runs
        or signals.check_runs
        or signals.pr_outcome is not None
        or signals.corrections
        or signals.interruptions > 0
    ):
        return "strong"
    return "weak"


def split_segments(command: str) -> list[tuple[str, str]]:
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
            sep = c
            if c == "|" and command[i + 1 : i + 2] == "|":
                sep = "||"
                i += 1
            segments.append(("".join(cur), sep))
            cur = []
        elif c == "&" and command[i + 1 : i + 2] == "&":
            segments.append(("".join(cur), "&&"))
            cur = []
            i += 1
        else:
            cur.append(c)
        i += 1
    segments.append(("".join(cur), ""))
    return segments


def starts_with(tokens: list[str], prefix: tuple[str, ...]) -> bool:
    return tuple(tokens[: len(prefix)]) == prefix


def segment_tokens(segment: str) -> list[str]:
    tokens = segment.split()
    while tokens:
        head = tokens[0].lstrip("({")
        if not head:
            tokens.pop(0)
            continue
        tokens[0] = head
        if head in SHELL_KEYWORDS:
            tokens.pop(0)
            continue
        break
    while tokens:
        tail = tokens[-1].rstrip(")}")
        if not tail:
            tokens.pop()
            continue
        tokens[-1] = tail
        break
    while tokens and ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    if len(tokens) == 1 and tokens[0] in SHELL_CLOSERS:
        return []
    return tokens


def skip_options(tokens: list[str], value_options: set[str]) -> list[str]:
    i = 0
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in value_options else 1
    return tokens[i:]


def classify_tokens(tokens: list[str]) -> str | None:
    while tokens:
        if tokens[0] in PACKAGE_MANAGERS:
            rest = skip_options(tokens[1:], set())
            if rest[:1] == ["run"]:
                rest = ["run"] + skip_options(rest[1:], set())
            tokens = [tokens[0]] + rest
        if any(starts_with(tokens, r) for r in TEST_RUNNERS):
            return "test"
        if any(starts_with(tokens, r) for r in CHECK_RUNNERS):
            return "check"
        if tokens[0] in PACKAGE_MANAGERS and len(tokens) > 2 and tokens[1] == "run":
            if TEST_SCRIPT.match(tokens[2]):
                return "test"
            return "check" if CHECK_SCRIPT.match(tokens[2]) else None
        if tokens[0] == "yarn" and len(tokens) > 1 and CHECK_SCRIPT.match(tokens[1]):
            return "check"
        if tokens[0] == "timeout":
            rest = skip_options(tokens[1:], TIMEOUT_VALUE_OPTIONS)
            if not rest or not DURATION.match(rest[0]):
                return None
            tokens = rest[1:]
            continue
        for launcher in LAUNCHERS:
            if starts_with(tokens, launcher):
                tokens = tokens[len(launcher) :]
                if launcher in OPTION_LAUNCHERS:
                    tokens = skip_options(tokens, VALUE_OPTIONS)
                break
        else:
            return None
    return None


def analyse_command(command: str) -> tuple[str, str] | None:
    live = []
    for text, sep in split_segments(command):
        tokens = segment_tokens(text)
        if tokens:
            live.append((classify_tokens(tokens), sep))
    kinds = [k for k, _ in live]
    if "test" in kinds:
        kind = "test"
    elif "check" in kinds:
        kind = "check"
    else:
        return None
    idx = len(kinds) - 1 - kinds[::-1].index(kind)
    if idx == len(live) - 1:
        return kind, "other" if live[idx][1] == "|" else "last"
    if all(sep == "&&" for _, sep in live[idx:-1]):
        return kind, "and"
    return kind, "other"


def is_test_command(command: str) -> bool:
    found = analyse_command(command)
    return found is not None and found[0] == "test"


def read_output(output: str) -> bool | None:
    if FAIL_RE.search(output):
        return False
    if PASS_RE.search(output):
        return True
    return None


def run_result(kind: str, position: str, exit_code: int | None, is_error: bool, output: str) -> bool | None:
    if position == "last":
        return exit_code == 0 if exit_code is not None else not is_error
    if position == "and" and exit_code == 0:
        return True
    return read_output(output) if kind == "test" else None


def normalise_path(path: str) -> str:
    p = path.replace("\\", "/")
    return p.lower() if WINDOWS_PATH.match(path) else p


def extract_signals(record: RunRecord) -> Signals:
    test_runs: list[TestRun] = []
    check_runs: list[TestRun] = []
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
            else:
                failed.pop(key, None)
            found = analyse_command(command)
            if found:
                kind, position = found
                output = tc.output_excerpt if isinstance(tc.output_excerpt, str) else ""
                passed = run_result(kind, position, tc.exit_code, tc.is_error, output)
                (test_runs if kind == "test" else check_runs).append(TestRun(command[:200], passed))
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
        check_runs=check_runs,
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
