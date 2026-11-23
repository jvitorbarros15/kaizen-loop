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
            input=d.get("input", 0),
            cache_write=d.get("cache_write", 0),
            cache_read=d.get("cache_read", 0),
            output=d.get("output", 0),
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
            id=d.get("id", ""),
            name=d.get("name", ""),
            input=d.get("input") or {},
            is_error=d.get("is_error", False),
            output_excerpt=d.get("output_excerpt", ""),
            timestamp=d.get("timestamp", ""),
            exit_code=d.get("exit_code"),
            agent_id=d.get("agent_id"),
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
    user_message_times: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    pr_urls: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    parent_session_id: str | None = None
    skipped_lines: int = 0
    interruptions: int = 0
    final_message: str = ""
    schema_version: int = 2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        return cls(
            session_id=d.get("session_id", ""),
            source=d.get("source", "claude-code"),
            cwd=d.get("cwd", ""),
            repo=d.get("repo"),
            git_branch=d.get("git_branch"),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at", ""),
            agent_version=d.get("agent_version"),
            usage_by_model={k: Usage.from_dict(v) for k, v in (d.get("usage_by_model") or {}).items()},
            tool_calls=[ToolCall.from_dict(c) for c in d.get("tool_calls") or []],
            user_messages=list(d.get("user_messages") or []),
            user_message_times=list(d.get("user_message_times") or []),
            skills_used=list(d.get("skills_used") or []),
            pr_urls=list(d.get("pr_urls") or []),
            cost_usd=d.get("cost_usd"),
            parent_session_id=d.get("parent_session_id"),
            skipped_lines=d.get("skipped_lines", 0),
            interruptions=d.get("interruptions", 0),
            final_message=d.get("final_message", ""),
            schema_version=d.get("schema_version", 1),
        )
