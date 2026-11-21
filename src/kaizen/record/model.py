from dataclasses import asdict, dataclass, field


@dataclass
class Usage:
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        return self.input + self.cache_write + self.cache_read + self.output

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Usage":
        return cls(
            input=d["input"],
            cache_write=d["cache_write"],
            cache_read=d["cache_read"],
            output=d["output"],
        )


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    is_error: bool = False
    output_excerpt: str = ""
    timestamp: str = ""
    exit_code: int | None = None
    agent_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCall":
        return cls(
            id=d["id"],
            name=d["name"],
            input=d["input"],
            is_error=d["is_error"],
            output_excerpt=d["output_excerpt"],
            timestamp=d["timestamp"],
            exit_code=d["exit_code"],
            agent_id=d["agent_id"],
        )


@dataclass
class RunRecord:
    session_id: str
    source: str = "claude-code"
    cwd: str = ""
    repo: str | None = None
    git_branch: str | None = None
    started_at: str = ""
    ended_at: str = ""
    agent_version: str | None = None
    usage_by_model: dict[str, Usage] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    user_messages: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    pr_urls: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    parent_session_id: str | None = None
    skipped_lines: int = 0
    interruptions: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        return cls(
            session_id=d["session_id"],
            source=d["source"],
            cwd=d["cwd"],
            repo=d["repo"],
            git_branch=d["git_branch"],
            started_at=d["started_at"],
            ended_at=d["ended_at"],
            agent_version=d["agent_version"],
            usage_by_model={k: Usage.from_dict(v) for k, v in d["usage_by_model"].items()},
            tool_calls=[ToolCall.from_dict(c) for c in d["tool_calls"]],
            user_messages=list(d["user_messages"]),
            skills_used=list(d["skills_used"]),
            pr_urls=list(d["pr_urls"]),
            cost_usd=d["cost_usd"],
            parent_session_id=d["parent_session_id"],
            skipped_lines=d["skipped_lines"],
            interruptions=d["interruptions"],
        )
