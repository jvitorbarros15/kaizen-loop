from dataclasses import asdict, dataclass, fields
from statistics import median

from kaizen.record.model import RunRecord
from kaizen.signals import Signals, normalise_path

BUCKETS = ("0", "1-2", "3-9", "10+")
MIN_RUNS = 5
FILE_KEYS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}


@dataclass
class RunStats:
    repo: str | None
    bucket: str
    total_tokens: int
    waste_rate: float


@dataclass
class Baseline:
    kind: str
    median_tokens: float
    median_waste_rate: float


@dataclass
class Score:
    total: float | None = None
    correctness_ok: bool | None = None
    quality: float | None = None
    efficiency: float | None = None
    cost: float | None = None
    strength: str = "weak"
    judge_backend: str | None = None
    baseline: str = "insufficient"
    evidence: str = "none"
    eligible_as_evidence: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Score":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def size_bucket(record: RunRecord) -> str:
    paths = set()
    for tc in record.tool_calls:
        key = FILE_KEYS.get(tc.name)
        if key is None:
            continue
        path = tc.input.get(key)
        if isinstance(path, str):
            paths.add(normalise_path(path))
    n = len(paths)
    if n == 0:
        return "0"
    if n <= 2:
        return "1-2"
    if n <= 9:
        return "3-9"
    return "10+"


def stats_of(record: RunRecord, signals: Signals) -> RunStats:
    calls = len(record.tool_calls)
    waste = signals.reread_count + signals.retry_count + signals.tool_error_count
    return RunStats(
        repo=record.repo,
        bucket=size_bucket(record),
        total_tokens=signals.total_tokens,
        waste_rate=100 * waste / calls if calls else 0.0,
    )


def _baseline(kind: str, runs: list[RunStats]) -> Baseline:
    return Baseline(
        kind,
        median_tokens=median([r.total_tokens for r in runs]),
        median_waste_rate=median([r.waste_rate for r in runs]),
    )


def baseline_for(stats: RunStats, history: list[RunStats]) -> Baseline | None:
    if stats.repo is None:
        return None
    same_repo = [h for h in history if h.repo == stats.repo]
    same_bucket = [h for h in same_repo if h.bucket == stats.bucket]
    if len(same_bucket) >= MIN_RUNS:
        return _baseline("bucket", same_bucket)
    if len(same_repo) >= MIN_RUNS:
        return _baseline("repo", same_repo)
    return None


def _sub(value: float, med: float, floor: float) -> float:
    m = max(med, floor)
    return min(10.0, max(0.0, 10 - 5 * value / m))


def compute_score(
    signals: Signals,
    stats: RunStats,
    quality: float | None,
    judge_backend: str | None,
    baseline: Baseline | None,
    weights: dict,
) -> Score:
    correctness_ok = signals.tests_passed_last
    known_checks = [c for c in signals.check_runs if c.passed is not None]
    if signals.test_runs and signals.tests_passed_last is not None:
        evidence = "tests"
    elif known_checks:
        evidence = "checks"
    else:
        evidence = "none"

    total = efficiency = cost = None
    kind = "insufficient"
    if baseline is not None:
        kind = baseline.kind
        cost = round(_sub(stats.total_tokens, baseline.median_tokens, 1.0), 1)
        efficiency = round(_sub(stats.waste_rate, baseline.median_waste_rate, 1.0), 1)
        if quality is not None:
            total = round(
                quality * weights["quality"] + efficiency * weights["efficiency"] + cost * weights["cost"], 1
            )
            if correctness_ok is False:
                total = min(total, 4.0)
            elif evidence == "checks" and known_checks[-1].passed is False:
                total = min(total, 6.0)

    strength = "weak" if evidence == "none" or quality is None else signals.strength
    return Score(
        total=total,
        correctness_ok=correctness_ok,
        quality=quality,
        efficiency=efficiency,
        cost=cost,
        strength=strength,
        judge_backend=judge_backend,
        baseline=kind,
        evidence=evidence,
        eligible_as_evidence=evidence != "none" and total is not None and strength == "strong",
    )
