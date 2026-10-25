"""Codex CLI rollout adapter.

Parses ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`` files written by the
Codex CLI / desktop app (verified against rollouts from CLI 0.160.1). The
format is append-only JSONL; every record carries ``type`` + ``payload``.

Handled structures:
- ``session_meta`` (first line): session id, cwd, cli version, start time;
- ``turn_context``: one per turn — ``turn_id`` / ``root_turn_id`` / ``model`` /
  ``collaboration_mode``. ``root_turn_id != turn_id`` marks a nested
  collaboration turn; nested turns are grouped by root turn into child
  sessions (the 子代理 tab);
- ``response_item``: ``message`` (role user/assistant/developer), ``reasoning``
  (readable ``summary[].text``; ``encrypted_content`` is ignored),
  ``custom_tool_call`` / ``function_call`` paired to their ``*_output`` by
  ``call_id``. Every item knows its turn via
  ``internal_chat_message_metadata_passthrough.turn_id``;
- ``token_usage_record``: one per API response with per-response usage; each is
  attributed to the response segment that precedes it in the file;
- ``event_msg`` task_started / task_complete (turn timing) and ``turn_aborted``
  (interruption — finalize() never emits those, so this adapter appends them);
- ``compacted``: history-compaction annotations.

Tool outputs carry no error flag; failures are inferred from
``custom_tool_call.status`` plus a conservative output-text heuristic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..model import (
    F_INTERRUPTED,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_UNKNOWN,
    Annotation,
    Failure,
    ModelCall,
    Session,
    SessionStats,
    ToolUse,
    Turn,
    Usage,
    categorize,
    finalize,
    truncate,
)

source_label = "codex"

_MAX_CHILDREN = 100

# Tool outputs have no error marker in the rollout format; these output-text
# prefixes are the failure signals the Codex exec tool actually emits.
_FAILED_OUTPUT_MARKERS = ("Script failed", "command failed", "command not found")


def list_rollouts(directory: str | Path) -> list[Path]:
    """All rollout .jsonl files under a (date-nested) sessions directory."""
    d = Path(directory).expanduser()
    return sorted(p for p in d.glob("**/*.jsonl") if p.is_file() and p.stat().st_size > 0)


def read_meta(path: str | Path) -> dict[str, Any] | None:
    """Payload of the session_meta header, or None if this is not a rollout."""
    p = Path(path)
    try:
        with p.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(5):
                line = fh.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    return None
                if isinstance(rec, dict) and rec.get("type") == "session_meta":
                    payload = rec.get("payload")
                    return payload if isinstance(payload, dict) else {}
                return {}
    except OSError:
        return None
    return None


def _iso_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def meta_ts_ms(meta: dict[str, Any] | None) -> int | None:
    """Session start time (epoch ms) from a session_meta payload."""
    return _iso_ms((meta or {}).get("timestamp"))


def _unix_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v <= 0:
        return None
    return int(v * 1000 if v < 1e12 else v)


def _rec_ts(rec: dict[str, Any]) -> int | None:
    ts = _iso_ms(rec.get("timestamp"))
    if ts is not None:
        return ts
    meta = rec.get("internal_chat_message_metadata_passthrough")
    if isinstance(meta, dict):
        return _unix_ms(meta.get("create_time"))
    return None


def _join_blocks(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = [str(b.get("text", "")) for b in output if isinstance(b, dict)]
        if any(parts):
            return "\n".join(parts)
    try:
        return json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(output)


def _looks_failed(text: str) -> bool:
    head = text.lstrip()[:120]
    return head.startswith(_FAILED_OUTPUT_MARKERS)


class _Seg:
    """One API response inside a turn: reasoning + text and/or tool calls."""

    def __init__(self, ts: int | None, line_no: int):
        self.ts = ts
        self.line_no = line_no
        self.reasoning: list[str] = []
        self.texts: list[str] = []
        self.tools: list[ToolUse] = []
        self.usage = Usage()
        self.closed = False

    def has_content(self) -> bool:
        return bool(self.reasoning or self.texts or self.tools)

    def billed(self) -> bool:
        u = self.usage
        return bool(u.input or u.output or u.cache_read or u.cache_write)


class _TurnAcc:
    """Accumulates one turn's items (a turn = one turn_context record)."""

    def __init__(self, turn_id: str):
        self.id = turn_id
        self.root = turn_id
        self.model = ""
        self.mode = ""
        self.effort = ""
        self.cwd = ""
        self.context_ts: int | None = None
        self.first_ts: int | None = None
        self.last_ts: int | None = None
        self.user_texts: list[str] = []
        self.segments: list[_Seg] = []

    def touch(self, ts: int | None, line_no: int) -> None:
        if ts is not None:
            self.first_ts = ts if self.first_ts is None else min(self.first_ts, ts)
            self.last_ts = ts if self.last_ts is None else max(self.last_ts, ts)
        if not self.segments or self.segments[-1].closed:
            self.segments.append(_Seg(ts, line_no))

    def add_reasoning(self, text: str, ts: int | None, line_no: int) -> None:
        # a reasoning item always opens a new response, unless the current
        # segment is still empty
        if self.segments and self.segments[-1].has_content():
            self.segments.append(_Seg(ts, line_no))
        if not self.segments:
            self.segments.append(_Seg(ts, line_no))
        self.touch(ts, line_no)
        self.segments[-1].reasoning.append(text)

    def add_text(self, text: str, ts: int | None, line_no: int) -> None:
        self.touch(ts, line_no)
        seg = self.segments[-1]
        seg.texts.append(text)
        seg.closed = True  # an assistant message usually ends the response

    def add_tool(self, tool: ToolUse, ts: int | None, line_no: int) -> None:
        self.touch(ts, line_no)
        self.segments[-1].tools.append(tool)

    def add_user(self, text: str) -> None:
        if text:
            self.user_texts.append(text)


def parse_file(path: str | Path, trunc: int = 2000, prices: Any = None) -> Session:
    """Parse one Codex rollout file into a Session."""
    p = Path(path)
    meta: dict[str, Any] | None = None
    turns: dict[str, _TurnAcc] = {}
    order: list[str] = []
    ctx_ids: set[str] = set()
    current_turn: str | None = None
    tools: dict[str, ToolUse] = {}
    usage_records: list[tuple[int, str | None, dict[str, Any]]] = []
    usage_fallback: list[tuple[int, str | None, dict[str, Any]]] = []
    last_fallback_sig: tuple | None = None
    task_events: dict[str, dict[str, int | None]] = {}
    aborts: list[dict[str, Any]] = []
    compactions: list[tuple[int | None, str]] = []
    bad_lines = 0
    hidden = 0
    first_ts: int | None = None
    last_ts: int | None = None

    def acc_for(tid: str | None) -> _TurnAcc | None:
        if tid is None:
            return None
        acc = turns.get(tid)
        if acc is None:
            acc = turns[tid] = _TurnAcc(tid)
            order.append(tid)
        return acc

    with p.open(encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                bad_lines += 1
                continue
            if not isinstance(rec, dict):
                bad_lines += 1
                continue
            ts = _rec_ts(rec)
            if ts is not None:
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)

            rtype = rec.get("type")
            payload = rec.get("payload")
            payload = payload if isinstance(payload, dict) else {}

            if rtype == "session_meta":
                if meta is None:
                    meta = payload
                continue
            if rtype == "turn_context":
                tid = str(payload.get("turn_id") or "") or None
                if tid is None:
                    continue
                acc = acc_for(tid)
                acc.root = str(payload.get("root_turn_id") or tid)
                acc.model = str(payload.get("model") or acc.model)
                acc.mode = str(payload.get("collaboration_mode") or acc.mode)
                acc.effort = str(payload.get("effort") or acc.effort)
                acc.cwd = str(payload.get("cwd") or acc.cwd)
                acc.context_ts = ts if ts is not None else acc.context_ts
                ctx_ids.add(tid)
                current_turn = tid
                continue
            if rtype == "token_usage_record":
                usage_records.append((line_no, payload.get("turn_id"), payload))
                continue
            if rtype == "event_msg":
                et = payload.get("type")
                tid = payload.get("turn_id")
                if et == "task_started" and tid:
                    ev = task_events.setdefault(str(tid), {})
                    ev["started"] = _unix_ms(payload.get("started_at")) or ev.get("started")
                elif et == "task_complete" and tid:
                    ev = task_events.setdefault(str(tid), {})
                    ev["completed"] = _unix_ms(payload.get("completed_at")) or ev.get("completed")
                    if payload.get("duration_ms") is not None:
                        ev["duration"] = int(payload["duration_ms"])
                elif et == "turn_aborted":
                    aborts.append(payload)
                elif et == "token_count":
                    # pre-0.15 rollouts have no token_usage_record; the last
                    # token_count of a response carries the same usage shape.
                    # The event repeats (heartbeats), so consecutive identical
                    # readings within a turn are deduped.
                    info = payload.get("info")
                    last = info.get("last_token_usage") if isinstance(info, dict) else None
                    if isinstance(last, dict) and last.get("input_tokens"):
                        sig = (
                            current_turn,
                            last.get("input_tokens"),
                            last.get("output_tokens"),
                            last.get("cached_input_tokens"),
                            last.get("cache_write_input_tokens"),
                            last.get("reasoning_output_tokens"),
                        )
                        if sig != last_fallback_sig:
                            usage_fallback.append((line_no, current_turn, {"usage": last}))
                            last_fallback_sig = sig
                continue
            if rtype == "compacted":
                win = payload.get("window_number")
                compactions.append((ts, f"history compacted (window {win})"))
                continue
            if rtype == "response_item":
                pt = payload.get("type")
                passthrough = rec.get("internal_chat_message_metadata_passthrough")
                if not isinstance(passthrough, dict):
                    passthrough = payload.get("internal_chat_message_metadata_passthrough")
                passthrough = passthrough if isinstance(passthrough, dict) else {}
                raw_tid = str(passthrough.get("turn_id") or "") or None
                # The passthrough turn id is only trusted when it names a known
                # turn_context: older rollouts carry a different id space there,
                # so fall back to the enclosing turn_context.
                if raw_tid is not None and raw_tid in ctx_ids:
                    tid = raw_tid
                else:
                    tid = current_turn
                acc = acc_for(tid) if tid is not None else None
                if acc is None:  # item before any turn_context
                    hidden += 1
                    continue
                if pt == "message":
                    role = payload.get("role")
                    text = _join_blocks(payload.get("content"))
                    if role == "developer":
                        hidden += 1
                    elif role == "user":
                        if not text.lstrip().startswith(("<environment", "<user_instructions")):
                            acc.add_user(text)
                        else:
                            hidden += 1
                        acc.touch(ts, line_no)
                    else:
                        if text:
                            acc.add_text(text, ts, line_no)
                elif pt == "reasoning":
                    summary = payload.get("summary")
                    text = " / ".join(
                        str(s.get("text", "")) for s in (summary or []) if isinstance(s, dict)
                    )
                    if text:
                        acc.add_reasoning(text, ts, line_no)
                elif pt in ("custom_tool_call", "function_call"):
                    call_id = str(payload.get("call_id") or payload.get("id") or "")
                    name = str(payload.get("name") or "?")
                    raw_input = (
                        payload.get("input") if pt == "custom_tool_call" else payload.get("arguments")
                    )
                    status = str(payload.get("status") or "")
                    tool = ToolUse(
                        id=call_id,
                        name=name,
                        category=categorize(name),
                        status=TOOL_ERROR if status in ("failed", "error") else TOOL_UNKNOWN,
                        started_at=ts,
                        input=truncate(raw_input, trunc),
                    )
                    if call_id:
                        tools[call_id] = tool
                    acc.add_tool(tool, ts, line_no)
                elif pt in ("custom_tool_call_output", "function_call_output"):
                    tool = tools.get(str(payload.get("call_id") or ""))
                    if tool is None:
                        continue
                    out = _join_blocks(payload.get("output"))
                    tool.output = truncate(out, trunc)
                    if tool.status == TOOL_ERROR:
                        if not tool.error:
                            tool.error = truncate(out, 300)
                    elif _looks_failed(out):
                        tool.status = TOOL_ERROR
                        tool.error = truncate(out, 300)
                    else:
                        tool.status = TOOL_OK
                continue
            # world_state / retained_context / … are ignored

    # ---- attribute usage records to response segments -----------------------
    # a usage record follows the response it bills, so it belongs to the last
    # segment whose first line precedes it. token_count events are only used
    # when the rollout predates token_usage_record entirely (both present would
    # double-count).
    if not usage_records:
        usage_records = usage_fallback
    pending_warnings: list[str] = []
    if usage_records and usage_fallback:
        # both sources present: token_count saw responses whose usage record
        # was never written — flag likely under-reporting
        rec_in = sum(int((r[2].get("usage") or {}).get("input_tokens") or 0) for r in usage_records)
        fb_in = sum(int((r[2].get("usage") or {}).get("input_tokens") or 0) for r in usage_fallback)
        if fb_in > rec_in * 1.1:
            pending_warnings.append(
                f"usage records incomplete: token_count saw ~{fb_in} input tokens but "
                f"token_usage_record only covers {rec_in}; totals may be under-reported"
            )
    unmatched = 0
    aux_usage = Usage()
    for line_no, tid, payload in usage_records:
        u = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        acc = turns.get(str(tid)) if tid is not None else None
        if acc is None or not acc.segments:
            unmatched += 1
            aux_usage.input += int(u.get("input_tokens") or 0)
            aux_usage.output += int(u.get("output_tokens") or 0)
            aux_usage.reasoning += int(u.get("reasoning_output_tokens") or 0)
            aux_usage.cache_read += int(u.get("cached_input_tokens") or 0)
            aux_usage.cache_write += int(u.get("cache_write_input_tokens") or 0)
            continue
        target = acc.segments[0]
        for seg in acc.segments:
            if seg.line_no < line_no:
                target = seg
        target.usage.input += int(u.get("input_tokens") or 0)
        target.usage.output += int(u.get("output_tokens") or 0)
        target.usage.reasoning += int(u.get("reasoning_output_tokens") or 0)
        target.usage.cache_read += int(u.get("cached_input_tokens") or 0)
        target.usage.cache_write += int(u.get("cache_write_input_tokens") or 0)

    # ---- split turns into main (root) and nested (child candidates) --------
    root_accs = [turns[t] for t in order if turns[t].root == turns[t].id]
    nested_accs = [turns[t] for t in order if turns[t].root != turns[t].id]
    # A rollout whose every turn is nested continues a turn whose root lives in
    # another file of the same thread — its content is this file's main session,
    # not a subagent run.
    if not root_accs and nested_accs:
        for acc in nested_accs:
            acc.root = acc.id
        root_accs, nested_accs = nested_accs, []

    def build_turn(acc: _TurnAcc) -> Turn:
        ev = task_events.get(acc.id, {})
        started = ev.get("started") or acc.first_ts or acc.context_ts
        duration = ev.get("duration")
        if duration is None and ev.get("completed") and started:
            duration = max(0, int(ev["completed"]) - int(started))
        if duration is None and acc.last_ts is not None and started:
            duration = max(0, acc.last_ts - started)
        user_text = truncate(acc.user_texts[0], trunc) if acc.user_texts else ""
        turn = Turn(
            id=acc.id,
            index=0,
            started_at=started,
            duration_ms=duration,
            user_text=user_text,
        )
        for i, seg in enumerate(acc.segments):
            if not seg.has_content() and not seg.billed():
                continue  # context-only segment, unless usage landed on it
            turn.model_calls.append(
                ModelCall(
                    id=f"{acc.id}-seg{i}",
                    model=acc.model,
                    started_at=seg.ts,
                    finish_reason="tool-calls" if seg.tools else ("stop" if seg.texts else ""),
                    usage=Usage(
                        input=seg.usage.input,
                        output=seg.usage.output,
                        reasoning=seg.usage.reasoning,
                        cache_read=seg.usage.cache_read,
                        cache_write=seg.usage.cache_write,
                    ),
                    reasoning_text=truncate("\n\n".join(seg.reasoning), trunc),
                    text=truncate("\n\n".join(seg.texts), trunc),
                    tool_uses=seg.tools,
                )
            )
        return turn

    main_turns = [build_turn(a) for a in root_accs]
    # drop turns with neither user text nor model calls (context-only noise)
    main_turns = [t for t in main_turns if t.user_text or t.model_calls]

    # ---- child sessions: nested turns grouped by their root turn -----------
    groups: dict[str, list[_TurnAcc]] = {}
    for acc in nested_accs:
        groups.setdefault(acc.root, []).append(acc)
    children: list[Session] = []
    for root, accs in groups.items():
        if len(children) >= _MAX_CHILDREN:
            break
        child_turns = [build_turn(a) for a in accs]
        child_turns = [t for t in child_turns if t.user_text or t.model_calls]
        if not child_turns:
            continue
        label = accs[0].mode or "collab"
        model = accs[0].model or "?"
        child = Session(
            id=f"{(meta or {}).get('session_id') or p.stem}#collab-{root[:8]}",
            source=source_label,
            title=truncate(f"subagent run ({label} · {model})", 80),
            turns=child_turns,
            stats=SessionStats(),
        )
        finalize(child, prices)
        children.append(child)

    session = Session(
        id=str((meta or {}).get("session_id") or p.stem),
        source=source_label,
        app_version=str((meta or {}).get("cli_version") or ""),
        cwd=str((meta or {}).get("cwd") or (root_accs[0].cwd if root_accs else "")),
        created_at=_iso_ms((meta or {}).get("timestamp")) or first_ts,
        updated_at=last_ts,
        duration_ms=(last_ts - first_ts) if first_ts is not None and last_ts is not None else None,
        turns=main_turns,
        child_sessions=children,
        stats=SessionStats(
            aux_call_count=unmatched,
            hidden_message_count=hidden,
            parse_error_count=bad_lines,
            usage=Usage(
                input=aux_usage.input,
                output=aux_usage.output,
                reasoning=aux_usage.reasoning,
                cache_read=aux_usage.cache_read,
                cache_write=aux_usage.cache_write,
            ),
        ),
    )
    session.title = truncate(main_turns[0].user_text, 80) if main_turns else ""
    session.warnings = list(pending_warnings)
    if bad_lines:
        session.warnings.append(f"{bad_lines} unparseable line(s) skipped")

    # compaction annotations attach to the main turn covering their timestamp
    for ts, msg in compactions:
        target = None
        for t in main_turns:
            if ts is None or (t.started_at is not None and t.started_at <= ts):
                target = t
        if target is None and main_turns:
            target = main_turns[0]
        if target is not None:
            target.annotations.append(Annotation("compaction", msg, ts))

    finalize(session, prices)

    # interruptions: finalize() never emits them, so append post-hoc
    turn_owner: dict[str, tuple[Session, Turn]] = {
        t.id: (session, t) for t in session.turns
    }
    for child in session.child_sessions:
        for t in child.turns:
            turn_owner[t.id] = (child, t)
    for payload in aborts:
        tid = str(payload.get("turn_id") or "")
        found = turn_owner.get(tid)
        if found is None:
            continue
        owner, turn = found
        turn.status = "interrupted"
        reason = payload.get("reason") or "aborted"
        owner.stats.failures.append(
            Failure(
                F_INTERRUPTED,
                turn.index,
                _unix_ms(payload.get("started_at")) or turn.started_at,
                f"turn aborted ({reason})",
                tid,
            )
        )
    for owner in [session, *session.child_sessions]:
        owner.stats.failures.sort(key=lambda f: (f.at or 0, f.kind))

    if not session.turns and not session.child_sessions:
        session.warnings.append("no turns recognized — unsupported rollout format?")
        if meta is None:
            session.warnings.append("missing session_meta header (not a Codex rollout?)")
    return session
