"""Claude Code JSONL transcript adapter (EXPERIMENTAL).

Parses ``~/.claude/projects/<project>/<session>.jsonl`` transcripts. Developed
against the publicly documented format (no local samples on this machine) —
expect rough edges; please file issues with (redacted) samples.

Handled quirks:
- one API response can be split across several lines sharing ``message.id``;
  usage/costUSD repeat per line, so we merge by message id (last usage wins,
  longest text block per signature wins, tool_use blocks dedupe by id);
- ``message.content`` is a block array in current versions but a plain string
  in old ones;
- tool_use / tool_result live in different lines and pair via
  ``id`` <-> ``tool_use_id``;
- ``isSidechain`` records (subagent runs) are pulled out into child sessions,
  grouped by parentUuid chain root.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..model import (
    TOOL_ERROR,
    TOOL_OK,
    TOOL_RUNNING,
    TOOL_UNKNOWN,
    Cost,
    ModelCall,
    Session,
    SessionStats,
    ToolUse,
    Turn,
    Usage,
    categorize,
    truncate,
)

source_label = "claude_code"

_TEXT_SIG_LEN = 120


def list_transcripts(directory: str | Path) -> list[Path]:
    d = Path(directory).expanduser()
    return sorted(p for p in d.glob("*.jsonl") if p.is_file() and p.stat().st_size > 0)


def _ts_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value if value > 1e12 else value * 1000)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def parse_file(path: str | Path, trunc: int = 2000, prices: Any = None) -> Session:
    """Parse one Claude Code transcript file into a Session."""
    p = Path(path)
    records: list[dict[str, Any]] = []
    bad_lines = 0
    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                bad_lines += 1
                continue
            if isinstance(rec, dict):
                records.append(rec)
            else:
                bad_lines += 1  # valid JSON but not a transcript record

    main = [r for r in records if not r.get("isSidechain")]
    side = [r for r in records if r.get("isSidechain")]

    session, bad = _build_session(p.stem, main, trunc)
    session.stats.parse_error_count = bad_lines
    if bad:
        session.warnings.append(f"{bad} unparseable line(s) skipped")
    session.title = _extract_title(main, session.title)

    if side:
        session.child_sessions = _build_sidechains(p.stem, side, trunc)

    from ..model import finalize

    finalize(session, prices)
    session.stats.failures.sort(key=lambda f: (f.at or 0, f.kind))
    for child in session.child_sessions:
        finalize(child, prices)
    return session


def _extract_title(records: list[dict[str, Any]], fallback: str) -> str:
    for r in records:
        if r.get("type") == "summary" and r.get("summary"):
            return truncate(r["summary"], 120)
    return fallback


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            else:
                try:
                    parts.append(json.dumps(b, ensure_ascii=False))
                except (TypeError, ValueError):
                    parts.append(str(b))
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


class _CallBucket:
    """Accumulates the split lines of one API response (same message.id)."""

    def __init__(self, model: Any, ts: int | None):
        self.model = str(model or "")
        self.ts = ts
        self.usage: dict[str, Any] | None = None
        self.cost: float | None = None
        self.tool_ids: list[str] = []
        self.text_order: list[tuple[str, str]] = []  # (kind, sig) in first-seen order
        self.texts: dict[tuple[str, str], str] = {}


def _build_session(
    session_id: str, records: list[dict[str, Any]], trunc: int
) -> tuple[Session, int]:
    turns: list[Turn] = []
    pending_tool: dict[str, ToolUse] = {}
    calls: dict[str, _CallBucket] = {}
    call_order: list[str] = []
    first_ts: int | None = None
    last_ts: int | None = None
    version = ""
    cwd = ""
    bad = 0

    def ensure_turn(ts: int | None) -> Turn:
        if turns and turns[-1].started_at is not None and ts is not None and ts < turns[-1].started_at:
            pass  # out-of-order; still append to last turn
        if not turns:
            t = Turn(id="turn-0", index=0, started_at=ts)
            turns.append(t)
        return turns[-1]

    for rec in records:
        rtype = rec.get("type")
        ts = _ts_ms(rec.get("timestamp"))
        if ts is not None:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        if rec.get("version") and not version:
            version = str(rec["version"])
        if rec.get("cwd") and not cwd:
            cwd = str(rec["cwd"])

        if rtype == "user":
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            blocks = _content_blocks((msg or {}).get("content"))
            for tr in blocks:
                if tr.get("type") != "tool_result":
                    continue
                tool = pending_tool.get(tr.get("tool_use_id"))
                if tool is None:
                    continue
                tool.output = truncate(_stringify_content(tr.get("content")), trunc)
                if tr.get("is_error"):
                    tool.status = TOOL_ERROR
                elif tool.status == TOOL_RUNNING:
                    tool.status = TOOL_OK
            user_texts = [b.get("text", "") for b in blocks if b.get("type") == "text" and b.get("text")]
            if rec.get("isMeta") or not user_texts:
                continue
            turn = Turn(
                id=f"turn-{len(turns)}",
                index=len(turns),
                started_at=ts,
                user_text=truncate("\n".join(user_texts), trunc),
            )
            turns.append(turn)

        elif rtype == "assistant":
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            msg = msg or {}
            mid = str(msg.get("id") or f"anon-{len(calls)}")
            blocks = _content_blocks(msg.get("content"))
            bucket = calls.get(mid)
            if bucket is None:
                bucket = calls[mid] = _CallBucket(msg.get("model"), ts)
                call_order.append(mid)
            if ts is not None and bucket.ts is None:
                bucket.ts = ts
            for b in blocks:
                btype = b.get("type")
                if btype == "tool_use":
                    tid = str(b.get("id") or "")
                    if any(x == tid for x in bucket.tool_ids):
                        continue
                    bucket.tool_ids.append(tid)
                    pending_tool[tid] = ToolUse(
                        id=tid,
                        name=str(b.get("name") or "?"),
                        category=categorize(str(b.get("name") or "")),
                        status=TOOL_RUNNING,
                        started_at=bucket.ts,
                        input=truncate(b.get("input"), trunc),
                    )
                elif btype in ("text", "thinking"):
                    body = str(b.get("text") or b.get("thinking") or "")
                    if not body:
                        continue
                    # streaming partials: same message streamed across lines yields
                    # texts where one is a prefix of the other — keep the longest
                    merged = False
                    for key in bucket.texts:
                        if key[0] == btype:
                            existing = bucket.texts[key]
                            if existing.startswith(body) or body.startswith(existing):
                                if len(body) > len(existing):
                                    bucket.texts[key] = body
                                merged = True
                                break
                    if merged:
                        continue
                    sig = (btype, body[:_TEXT_SIG_LEN])
                    if sig not in bucket.texts:
                        bucket.text_order.append(sig)
                    bucket.texts[sig] = body
            if msg.get("usage"):
                bucket.usage = msg["usage"]
            if rec.get("costUSD") is not None:
                bucket.cost = float(rec["costUSD"])
            bucket.model = bucket.model or str(msg.get("model") or "")

    # place calls into turns (a call belongs to the last turn started <= call ts)
    for mid in call_order:
        b = calls[mid]
        u = b.usage or {}
        reasoning, text = [], []
        for kind, prefix in b.text_order:
            body = b.texts[(kind, prefix)]
            (reasoning if kind == "thinking" else text).append(body)
        call = ModelCall(
            id=mid,
            model=b.model,
            started_at=b.ts,
            finish_reason="tool-calls" if b.tool_ids else ("stop" if text else ""),
            usage=Usage(
                input=u.get("input_tokens") or 0,
                output=u.get("output_tokens") or 0,
                cache_read=u.get("cache_read_input_tokens") or 0,
                cache_write=u.get("cache_creation_input_tokens") or 0,
            ),
            cost=Cost(total=b.cost) if b.cost is not None else None,
            reasoning_text=truncate("\n\n".join(reasoning), trunc),
            text=truncate("\n\n".join(text), trunc),
            tool_uses=[pending_tool[tid] for tid in b.tool_ids if tid in pending_tool],
        )
        target = None
        if turns:
            for turn in reversed(turns):
                if turn.started_at is None or (call.started_at is not None and call.started_at >= turn.started_at):
                    target = turn
                    break
            if target is None:
                target = turns[0]
        else:
            target = ensure_turn(call.started_at)
        target.model_calls.append(call)

    for tool in pending_tool.values():
        if tool.status == TOOL_RUNNING:
            tool.status = TOOL_UNKNOWN

    # turn end/duration: implicit — next turn's start, else session end
    for i, turn in enumerate(turns):
        turn.index = i
        turn.id = f"turn-{i}"
        next_start = turns[i + 1].started_at if i + 1 < len(turns) else last_ts
        if turn.started_at is not None and next_start is not None:
            turn.duration_ms = max(0, next_start - turn.started_at)

    session = Session(
        id=session_id,
        source=source_label,
        app_version=version,
        cwd=cwd,
        created_at=first_ts,
        updated_at=last_ts,
        duration_ms=(last_ts - first_ts) if first_ts is not None and last_ts is not None else None,
        stats=SessionStats(),
    )
    session.turns = turns
    session.warnings = []
    return session, bad


def _build_sidechains(base_id: str, side: list[dict[str, Any]], trunc: int) -> list[Session]:
    by_uuid = {r.get("uuid"): r for r in side if r.get("uuid")}

    def chain_root(uuid: Any) -> Any:
        cur = uuid
        seen: set[Any] = set()
        while cur in by_uuid and cur not in seen:
            seen.add(cur)
            parent = by_uuid[cur].get("parentUuid")
            if not parent or parent not in by_uuid:
                break
            cur = parent
        return cur

    groups: dict[Any, list[dict[str, Any]]] = {}
    for r in side:
        groups.setdefault(chain_root(r.get("uuid")), []).append(r)

    children = []
    for i, (_, recs) in enumerate(sorted(groups.items(), key=lambda kv: str(kv[0]))):
        child, _bad = _build_session(f"{base_id}#sidechain-{i + 1}", recs, trunc)
        child.title = f"subagent run #{i + 1}"
        children.append(child)
    return children
