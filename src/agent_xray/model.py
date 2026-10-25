"""Unified event model shared by all format adapters.

Every adapter (ZCode sqlite, Claude Code JSONL, …) flattens its native format
into this tree; the renderer and CLI only ever see these dataclasses. All
timestamps are epoch milliseconds (int); all free-text fields are truncated at
parse time unless the caller passes ``trunc=0``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_TRUNC = 2000

# Tool status values
TOOL_OK = "ok"
TOOL_ERROR = "error"
TOOL_RUNNING = "running"
TOOL_CANCELLED = "cancelled"
TOOL_UNKNOWN = "unknown"

# Failure kinds
F_TOOL_ERROR = "tool_error"
F_MODEL_ERROR = "model_error"
F_RETRY = "retry"
F_CONTEXT = "context_exceeded"
F_PERMISSION = "permission_denied"
F_INTERRUPTED = "interrupted"
F_LONG_TURN = "long_turn"

_CATEGORY_NAMES: dict[str, set[str]] = {
    "bash": {"bash", "shell", "zsh"},
    "read": {"read", "readfile", "view"},
    "write": {"write", "writefile"},
    "edit": {"edit", "multiedit", "notebookedit", "apply-patch", "patch"},
    "search": {"glob", "grep", "search", "ls", "find", "list", "code-search"},
    "web": {"webfetch", "websearch", "fetch", "browser", "browse"},
    "agent": {"agent", "task", "sendmessage", "spawn", "delegate"},
    "todo": {"todowrite", "todoread", "todo"},
    "skill": {"skill"},
}


def categorize(tool_name: str) -> str:
    n = (tool_name or "").lower()
    if n.startswith("mcp__") or n.startswith("mcp-"):
        return "mcp"
    for cat, names in _CATEGORY_NAMES.items():
        if n in names:
            return cat
    return "other"


def truncate(text: Any, limit: int) -> str:
    """Best-effort stringification with a tail marker when cut."""
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(text)
    if limit and len(text) > limit:
        return text[:limit] + f" …[{len(text) - limit} more chars]"
    return text


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    def add(self, other: Usage) -> None:
        self.input += other.input
        self.output += other.output
        self.reasoning += other.reasoning
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write


@dataclass
class Cost:
    """Per-MTok USD cost estimate (ccusage convention: cache_read=0.1x, cache_write=1.25x)."""

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0

    def add(self, other: Cost) -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.total += other.total


@dataclass
class ToolUse:
    id: str
    name: str
    category: str
    status: str = TOOL_UNKNOWN
    started_at: int | None = None
    input: str = ""
    output: str = ""
    error: str = ""
    duration_ms: int | None = None
    exit_code: int | None = None


@dataclass
class ModelCall:
    id: str
    model: str
    provider: str = ""
    agent: str = ""
    query_source: str = "main_turn"
    started_at: int | None = None
    duration_ms: int | None = None
    attempt: int = 1
    finish_reason: str = ""
    status: str = "completed"
    usage: Usage = field(default_factory=Usage)
    cost: Cost | None = None
    reasoning_text: str = ""
    text: str = ""
    tool_uses: list[ToolUse] = field(default_factory=list)
    error: str = ""


@dataclass
class Annotation:
    kind: str  # model_change | compaction
    message: str
    at: int | None = None


@dataclass
class Turn:
    id: str
    index: int
    started_at: int | None = None
    duration_ms: int | None = None
    user_text: str = ""
    status: str = "ok"  # ok | error | interrupted
    model_calls: list[ModelCall] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Failure:
    kind: str
    turn_index: int
    at: int | None
    message: str
    ref: str = ""


@dataclass
class ToolStat:
    name: str
    category: str
    count: int = 0
    errors: int = 0
    total_ms: int = 0


@dataclass
class SessionStats:
    turn_count: int = 0
    model_call_count: int = 0
    tool_count: int = 0
    tool_error_count: int = 0
    retry_count: int = 0
    aux_call_count: int = 0  # compact / title / … background model calls
    hidden_message_count: int = 0
    parse_error_count: int = 0
    usage: Usage = field(default_factory=Usage)
    cost: Cost = field(default_factory=Cost)
    failures: list[Failure] = field(default_factory=list)
    tool_top: list[ToolStat] = field(default_factory=list)


@dataclass
class Session:
    id: str
    source: str  # zcode_db | claude_code | codex
    title: str = ""
    app_version: str = ""
    cwd: str = ""
    created_at: int | None = None
    updated_at: int | None = None
    duration_ms: int | None = None
    models: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    child_sessions: list[Session] = field(default_factory=list)
    stats: SessionStats = field(default_factory=SessionStats)
    warnings: list[str] = field(default_factory=list)


def _assign_indexes(session: Session) -> None:
    for i, turn in enumerate(session.turns):
        turn.index = i


def finalize(session: Session, prices: Any = None, long_turn_floor_ms: int = 300_000) -> Session:
    """Recompute indexes, stats, costs and failure list in place. Called by adapters."""

    from .cost import estimate_cost  # local import to avoid cycle

    _assign_indexes(session)
    stats = session.stats
    stats.turn_count = len(session.turns)
    tool_agg: dict[str, ToolStat] = {}
    durations: list[int] = []
    ctx_exceeded = False

    for turn in session.turns:
        for call in turn.model_calls:
            stats.model_call_count += 1
            stats.usage.add(call.usage)
            if prices is not None and call.cost is None:
                call.cost = estimate_cost(prices, call.model, call.usage)
            if call.cost is not None:
                stats.cost.add(call.cost)
            if call.attempt > 1:
                stats.retry_count += call.attempt - 1
            for tool in call.tool_uses:
                stats.tool_count += 1
                agg = tool_agg.setdefault(tool.name, ToolStat(tool.name, tool.category))
                agg.count += 1
                if tool.duration_ms:
                    agg.total_ms += tool.duration_ms
                if tool.status == TOOL_ERROR:
                    agg.errors += 1
                    stats.tool_error_count += 1
            if call.duration_ms:
                durations.append(call.duration_ms)
        for ann in turn.annotations:
            if ann.kind == "compaction" and "context_limit" in ann.message:
                ctx_exceeded = True

    stats.tool_top = sorted(tool_agg.values(), key=lambda s: (-s.count, s.name))[:12]

    # Failures, in chronological order
    failures: list[Failure] = []
    for turn in session.turns:
        for call in turn.model_calls:
            if call.error:
                failures.append(
                    Failure(F_MODEL_ERROR, turn.index, call.started_at, truncate(call.error, 300), call.id)
                )
            elif call.finish_reason == "failed" or call.status == "error":
                failures.append(
                    Failure(F_MODEL_ERROR, turn.index, call.started_at, "model call failed", call.id)
                )
            if call.attempt > 1:
                failures.append(
                    Failure(
                        F_RETRY,
                        turn.index,
                        call.started_at,
                        f"{call.model} needed {call.attempt} attempts",
                        call.id,
                    )
                )
            for tool in call.tool_uses:
                if tool.status == TOOL_ERROR:
                    failures.append(
                        Failure(
                            F_TOOL_ERROR,
                            turn.index,
                            call.started_at,
                            f"{tool.name}: {tool.error or 'error'}",
                            tool.id,
                        )
                    )
                elif tool.error and "permission" in (tool.error or "").lower():
                    failures.append(
                        Failure(F_PERMISSION, turn.index, call.started_at, tool.error, tool.id)
                    )
    long_threshold = long_turn_floor_ms
    if durations:
        srt = sorted(durations)
        p95 = srt[min(len(srt) - 1, int(len(srt) * 0.95))]
        long_threshold = max(long_threshold, p95)
    for turn in session.turns:
        if turn.duration_ms and turn.duration_ms > long_threshold:
            failures.append(
                Failure(
                    F_LONG_TURN,
                    turn.index,
                    turn.started_at,
                    f"turn took {turn.duration_ms / 1000:.0f}s (> {long_threshold / 1000:.0f}s threshold)",
                    turn.id,
                )
            )
        if turn.status == "error":
            # surfaced via call failures; keep turn status for the renderer
            pass
    if ctx_exceeded:
        last = session.turns[-1] if session.turns else None
        failures.append(
            Failure(F_CONTEXT, last.index if last else 0, last.started_at if last else None,
                    "context window exceeded (auto-compaction triggered)", "")
        )
    stats.failures = failures

    session.models = sorted({c.model for t in session.turns for c in t.model_calls if c.model})
    return session


def to_dict(session: Session) -> dict[str, Any]:
    """JSON-safe dict for embedding into the HTML payload."""
    d = asdict(session)
    d["stats"]["usage"]["total"] = session.stats.usage.total
    d["stats"]["cost"]["total"] = session.stats.cost.total
    for i, turn in enumerate(session.turns):
        for j, call in enumerate(turn.model_calls):
            d["turns"][i]["model_calls"][j]["usage"]["total"] = call.usage.total
            if call.cost:
                d["turns"][i]["model_calls"][j]["cost"]["total"] = call.cost.total
    return d
