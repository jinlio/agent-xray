"""ZCode sqlite adapter — the primary, persistent data source.

Reads ``~/.zcode/cli/db/db.sqlite`` (schema reverse-engineered as of ZCode
0.17.x; this is an internal format and may drift — every join is guarded by a
capability probe and degrades gracefully instead of crashing).

The live database is WAL-mode and actively written by the ZCode process, so we
copy it (plus -wal/-shm) to a temp dir before reading.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from ..model import (
    F_CONTEXT,
    F_INTERRUPTED,
    TOOL_CANCELLED,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_RUNNING,
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
    truncate,
)

DEFAULT_DB = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"

_MAIN_SOURCES = {"main_turn", "subagent", ""}
_TOOL_STATUS = {
    "completed": TOOL_OK,
    "error": TOOL_ERROR,
    "running": TOOL_RUNNING,
    "cancelled": TOOL_CANCELLED,
}


# ---------------------------------------------------------------------------
# connection / discovery


def discover_db(explicit: str | Path | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"database not found: {p}")
        return p
    if DEFAULT_DB.exists():
        return DEFAULT_DB
    raise FileNotFoundError(
        "ZCode database not found at ~/.zcode/cli/db/db.sqlite — pass --db /path/to/db.sqlite"
    )


def open_snapshot(db_path: str | Path) -> tuple[sqlite3.Connection, Path]:
    """Copy the db (WAL included) to a temp dir and open it read-write there.

    Returns (connection, tempdir). Caller must eventually close() and clean up.
    """
    src = Path(db_path).expanduser()
    tmp = Path(tempfile.mkdtemp(prefix="agent-xray-db-"))
    dest = tmp / "db.sqlite"
    try:
        shutil.copy2(src, dest)
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(dest) + suffix))
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    conn = sqlite3.connect(str(dest))
    conn.row_factory = sqlite3.Row
    return conn, tmp


def close_snapshot(conn: sqlite3.Connection, tmp: Path) -> None:
    try:
        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _columns(conn: sqlite3.Connection) -> dict[str, set[str]]:
    cols: dict[str, set[str]] = {}
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    except sqlite3.Error:
        return cols
    for t in tables:
        try:
            cols[t] = {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')}
        except sqlite3.Error:
            continue
    return cols


# ---------------------------------------------------------------------------
# session listing (cheap, for --list)


def list_sessions(conn: sqlite3.Connection, project: str | None = None) -> list[dict[str, Any]]:
    cols = _columns(conn)
    has_deleted = "time_deleted" in cols.get("session", set())
    sql = """
        SELECT s.id, s.title, s.directory, s.time_created, s.time_updated,
               s.version, s.last_outcome, s.parent_id
        FROM session s
        WHERE s.task_type = 'interactive'
    """
    params: list[Any] = []
    if has_deleted:
        sql += " AND s.time_deleted IS NULL"
    if project:
        sql += " AND (s.project_id = ? OR s.directory = ?)"
        params += [project, project]
    sql += " ORDER BY s.time_created DESC"

    out: list[dict[str, Any]] = []
    for row in conn.execute(sql, params):
        item = dict(row)
        sid = item["id"]
        item["message_count"] = _scalar(conn, "SELECT COUNT(*) FROM message WHERE session_id=?", sid)
        item["turn_count"] = (
            _scalar(conn, "SELECT COUNT(*) FROM turn_usage WHERE session_id=?", sid)
            if "turn_usage" in cols
            else None
        )
        item["tool_error_count"] = (
            _scalar(
                conn,
                "SELECT COUNT(*) FROM tool_usage WHERE session_id=? AND status='error'",
                sid,
            )
            if "tool_usage" in cols
            else None
        )
        item["duration_ms"] = item["time_updated"] - item["time_created"]
        out.append(item)
    return out


def _scalar(conn: sqlite3.Connection, sql: str, *params: Any) -> Any:
    try:
        return conn.execute(sql, params).fetchone()[0]
    except sqlite3.Error:
        return None


# ---------------------------------------------------------------------------
# parsing


def parse_session(
    conn: sqlite3.Connection,
    session_id: str,
    trunc: int = 2000,
    prices: Any = None,
    child_depth: int = 1,
    _cols: dict[str, set[str]] | None = None,
) -> Session:
    cols = _cols or _columns(conn)
    has = cols.__contains__

    sess = conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
    if sess is None:
        raise ValueError(f"session not found: {session_id}")

    session = Session(
        id=sess["id"],
        source="zcode_db",
        title=sess["title"] or "",
        app_version=sess["version"] or "",
        cwd=sess["directory"] or "",
        created_at=sess["time_created"],
        updated_at=sess["time_updated"],
    )
    session.duration_ms = sess["time_updated"] - sess["time_created"]
    if sess["last_outcome"]:
        session.warnings.append(f"last_outcome={sess['last_outcome']}")

    warnings: list[str] = session.warnings
    parse_errors = 0
    hidden_count = 0

    # ---- preload usage tables ------------------------------------------------
    mu_by_msg: dict[str, dict[str, Any]] = {}
    aux_rows: list[dict[str, Any]] = []
    if has("model_usage"):
        try:
            for r in conn.execute(
                "SELECT * FROM model_usage WHERE session_id = ? ORDER BY started_at", (session_id,)
            ):
                d = dict(r)
                amid = d.get("assistant_message_id")
                if not amid:
                    aux_rows.append(d)
                    continue
                cur = mu_by_msg.get(amid)
                if cur is None:
                    mu_by_msg[amid] = d
                else:
                    # multiple rows per assistant message: keep the latest, merge retries
                    cur["retry_count"] = max(cur.get("retry_count") or 0, d.get("retry_count") or 0)
                    if (d.get("started_at") or 0) >= (cur.get("started_at") or 0):
                        d["retry_count"] = max(
                            d.get("retry_count") or 0, cur.get("retry_count") or 0
                        )
                        mu_by_msg[amid] = d
        except sqlite3.Error as e:
            warnings.append(f"model_usage unreadable: {e}")

    turn_usage: dict[str, dict[str, Any]] = {}
    if has("turn_usage"):
        try:
            for r in conn.execute("SELECT * FROM turn_usage WHERE session_id = ?", (session_id,)):
                turn_usage[r["turn_id"]] = dict(r)
        except sqlite3.Error as e:
            warnings.append(f"turn_usage unreadable: {e}")

    tool_usage: dict[str, dict[str, Any]] = {}
    if has("tool_usage"):
        try:
            for r in conn.execute("SELECT * FROM tool_usage WHERE session_id = ?", (session_id,)):
                tool_usage[r["tool_call_id"]] = dict(r)
        except sqlite3.Error as e:
            warnings.append(f"tool_usage unreadable: {e}")

    # ---- load messages & parts ----------------------------------------------
    try:
        msgs = conn.execute(
            """
            SELECT id, time_created, time_updated, data
            FROM message WHERE session_id = ?
            ORDER BY COALESCE(sequence, time_created), time_created, id
            """,
            (session_id,),
        ).fetchall()
    except sqlite3.Error as e:
        warnings.append(f"message table unreadable: {e}")
        msgs = []

    parts_by_msg: dict[str, list[sqlite3.Row]] = {}
    if has("part"):
        try:
            for p in conn.execute(
                """
                SELECT id, message_id, time_created, data
                FROM part WHERE session_id = ?
                ORDER BY message_id, COALESCE(sequence, 0), id
                """,
                (session_id,),
            ):
                parts_by_msg.setdefault(p["message_id"], []).append(p)
        except sqlite3.Error as e:
            warnings.append(f"part table unreadable: {e}")

    # ---- walk messages -------------------------------------------------------
    turns_by_id: dict[str, Turn] = {}
    turn_order: list[str] = []
    msg_min: int | None = None
    msg_max: int | None = None

    def get_turn(tid: str, at: int | None) -> Turn:
        t = turns_by_id.get(tid)
        if t is None:
            t = Turn(id=tid, index=len(turn_order), started_at=at)
            turns_by_id[tid] = t
            turn_order.append(tid)
        return t

    for m in msgs:
        ts = m["time_created"]
        msg_min = ts if msg_min is None else min(msg_min, ts)
        msg_max = m["time_updated"] if msg_max is None else max(msg_max, m["time_updated"])
        try:
            data = json.loads(m["data"])
        except (ValueError, TypeError):
            parse_errors += 1
            continue
        if not isinstance(data, dict):
            parse_errors += 1
            continue
        role = data.get("role")
        sem = data.get("semantics") or {}

        if role == "user":
            if sem.get("kind") != "user_prompt" or sem.get("uiVisibility") == "hidden":
                hidden_count += 1
                continue
            # real_user = 人类输入; agent_runtime = 子代理会话里父级注入的任务提示
            anchor = data.get("anchor") or {}
            tid = anchor.get("turnId") or f"turn-{m['id']}"
            turn = get_turn(tid, ts)
            if turn.started_at is None or (ts is not None and ts < turn.started_at):
                turn.started_at = ts
            text = _concat_parts(parts_by_msg.get(m["id"], []), "text", "text")
            if text:
                turn.user_text = f"{turn.user_text}\n---\n{text}" if turn.user_text else text

        elif role == "assistant":
            if sem.get("uiVisibility") == "hidden":
                hidden_count += 1
                continue
            anchor = data.get("anchor") or {}
            tid = anchor.get("turnId") or f"turn-{m['id']}"
            turn = get_turn(tid, ts)
            call = _build_call(m, data, mu_by_msg.get(m["id"]), parts_by_msg.get(m["id"], []),
                               tool_usage, trunc, warnings)
            turn.model_calls.append(call)

    # ---- aux model calls (compact / session_title / …) ----------------------
    aux_count = 0
    aux_usage = Usage()
    for r in aux_rows:
        aux_count += 1
        aux_usage.add(
            Usage(
                input=r.get("input_tokens") or 0,
                output=r.get("output_tokens") or 0,
                reasoning=r.get("reasoning_tokens") or 0,
                cache_read=r.get("cache_read_input_tokens") or 0,
                cache_write=r.get("cache_creation_input_tokens") or 0,
            )
        )

    # ---- order turns, drop aux-only pseudo turns ----------------------------
    turns: list[Turn] = []
    for tid in turn_order:
        t = turns_by_id[tid]
        sources = [c.query_source for c in t.model_calls]
        is_aux_only = bool(sources) and all(qs not in _MAIN_SOURCES for qs in sources)
        if not t.user_text and is_aux_only:
            # background model traffic (title generation, compaction) — not a user round
            aux_count += len(t.model_calls)
            for c in t.model_calls:
                aux_usage.add(c.usage)
            if turns:
                turns[-1].annotations.append(
                    Annotation("background", f"background model traffic ({', '.join(sorted(set(sources)))})", t.started_at)
                )
            continue
        _finalize_turn(t, turn_usage.get(tid))
        turns.append(t)
    session.turns = turns

    # ---- turn_usage failures (built after finalize assigns final indexes) ----
    tu_rows = list(turn_usage.items())

    # ---- children ------------------------------------------------------------
    if child_depth > 0:
        child_sql = "SELECT id FROM session WHERE parent_id = ?"
        if "time_deleted" in cols.get("session", set()):
            child_sql += " AND time_deleted IS NULL"
        try:
            child_ids = [r["id"] for r in conn.execute(child_sql, (session_id,))]
        except sqlite3.Error:
            child_ids = []
        for cid in child_ids[:20]:
            try:
                session.child_sessions.append(
                    parse_session(conn, cid, trunc, prices, child_depth - 1, _cols=cols)
                )
            except (ValueError, sqlite3.Error) as e:
                warnings.append(f"child session {cid} failed: {e}")

    # ---- stats ----------------------------------------------------------------
    session.stats = SessionStats(
        aux_call_count=aux_count,
        hidden_message_count=hidden_count,
        parse_error_count=parse_errors,
        usage=aux_usage,
    )
    if msg_min is not None and msg_max is not None:
        session.duration_ms = msg_max - msg_min
    session.created_at = msg_min or session.created_at
    session.updated_at = msg_max or session.updated_at

    from ..model import finalize

    finalize(session, prices)

    # turn-level failures, now that finalize has assigned final turn indexes
    tu_failures: list[Failure] = []
    for tid, tu in tu_rows:
        turn = next((t for t in session.turns if t.id == tid), None)
        idx = turn.index if turn else 0
        if tu.get("context_exceeded"):
            tu_failures.append(
                Failure(F_CONTEXT, idx, tu.get("started_at"), "context window exceeded on this turn", tid)
            )
        if tu.get("cancelled_by_user") or tu.get("status") == "cancelled":
            tu_failures.append(
                Failure(F_INTERRUPTED, idx, tu.get("started_at"), "turn cancelled by user", tid)
            )
            if turn is not None:
                turn.status = "interrupted"
        elif tu.get("status") == "error" or tu.get("error_type"):
            msg = tu.get("error_type") or "turn error"
            if tu.get("error_code"):
                msg += f" ({tu['error_code']})"
            tu_failures.append(
                Failure("model_error", idx, tu.get("started_at"), truncate(msg, 300), tid)
            )
            if turn is not None and turn.status == "ok":
                turn.status = "error"
    if sess["last_outcome"] == "interrupted" and session.turns:
        last = session.turns[-1]
        tu_failures.append(
            Failure(F_INTERRUPTED, last.index, last.started_at, "session ended interrupted", last.id)
        )
        if last.status == "ok":
            last.status = "interrupted"

    session.stats.failures = sorted(session.stats.failures, key=lambda f: (f.at or 0))
    session.stats.failures.extend(tu_failures)
    session.stats.failures.sort(key=lambda f: (f.at or 0, f.kind))
    return session


# ---------------------------------------------------------------------------


def _concat_parts(parts: list[sqlite3.Row], ptype: str, key: str) -> str:
    chunks: list[str] = []
    for p in parts:
        try:
            d = json.loads(p["data"])
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and d.get("type") == ptype and d.get(key):
            chunks.append(str(d[key]))
    return "\n\n".join(chunks)


def _build_call(
    m: sqlite3.Row,
    data: dict[str, Any],
    mu: dict[str, Any] | None,
    parts: list[sqlite3.Row],
    tool_usage: dict[str, dict[str, Any]],
    trunc: int,
    warnings: list[str],
) -> ModelCall:
    td = data.get("time") or {}
    mu = mu or {}
    started = mu.get("started_at") or td.get("created") or m["time_created"]
    duration = mu.get("duration_ms")
    if duration is None and td.get("created") and td.get("completed"):
        duration = td["completed"] - td["created"]

    tok = data.get("tokens") or {}
    cache = tok.get("cache") or {}

    def pick(mu_key: str, json_val: Any) -> int:
        v = mu.get(mu_key)
        return int(v) if v is not None else int(json_val or 0)

    usage = Usage(
        input=pick("input_tokens", tok.get("input")),
        output=pick("output_tokens", tok.get("output")),
        reasoning=pick("reasoning_tokens", tok.get("reasoning")),
        cache_read=pick("cache_read_input_tokens", cache.get("read")),
        cache_write=pick("cache_creation_input_tokens", cache.get("write")),
    )

    finish = mu.get("finish_reason") or data.get("finish") or ""
    status = mu.get("status") or "completed"
    attempt = int(mu.get("retry_count") or 0) + 1

    error = ""
    err_obj = data.get("error")
    if isinstance(err_obj, dict):
        name = err_obj.get("name") or "Error"
        detail = err_obj.get("data") or {}
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
        error = f"{name}: {msg}" if msg else name
    if not error and mu.get("error_message"):
        error = str(mu["error_message"])
    if not error and mu.get("error_type"):
        error = str(mu["error_type"])

    reasoning_chunks: list[str] = []
    text_chunks: list[str] = []
    tools: list[ToolUse] = []
    anns: list[Annotation] = []

    for p in parts:
        try:
            pd = json.loads(p["data"])
        except (ValueError, TypeError):
            continue
        if not isinstance(pd, dict):
            continue
        ptype = pd.get("type")
        if ptype == "reasoning" and pd.get("text"):
            reasoning_chunks.append(pd["text"])
        elif ptype == "text" and pd.get("text"):
            text_chunks.append(pd["text"])
        elif ptype == "tool":
            tools.append(_build_tool(p, pd, tool_usage, trunc))
        elif ptype == "timeline":
            tlt = pd.get("timelineType")
            if tlt == "model_change":
                anns.append(
                    Annotation(
                        "model_change",
                        f"model switched: {pd.get('fromModel') or '?'} → {pd.get('toModel') or '?'}",
                        p["time_created"],
                    )
                )
            elif tlt == "context_compaction":
                anns.append(Annotation("compaction", "context compaction", p["time_created"]))
        elif ptype == "compaction":
            reason = pd.get("compactReason") or "manual"
            pre = pd.get("preCompactTokenCount")
            post = pd.get("postCompactTokenCount")
            scale = f", tokens {pre}→{post}" if pre and post else ""
            anns.append(
                Annotation("compaction", f"context compaction ({reason}){scale}", p["time_created"])
            )
            if reason == "context_limit":
                anns[-1].message += " [context_limit]"

    return ModelCall(
        id=m["id"],
        model=str(data.get("modelId") or data.get("modelID") or mu.get("model_id") or ""),
        provider=str(data.get("providerId") or data.get("providerID") or mu.get("provider_id") or ""),
        agent=str(data.get("agent") or mu.get("agent") or ""),
        query_source=str(mu.get("query_source") or "main_turn"),
        started_at=started,
        duration_ms=duration,
        attempt=attempt,
        finish_reason=str(finish or ""),
        status=str(status or "completed"),
        usage=usage,
        reasoning_text=truncate("\n\n".join(reasoning_chunks), trunc),
        text=truncate("\n\n".join(text_chunks), trunc),
        tool_uses=tools,
        error=truncate(error, 500),
    )


def _build_tool(
    p: sqlite3.Row, pd: dict[str, Any], tool_usage: dict[str, dict[str, Any]], trunc: int
) -> ToolUse:
    name = str(pd.get("tool") or "?")
    st = pd.get("state") or {}
    status = _TOOL_STATUS.get(st.get("status"), TOOL_UNKNOWN)
    t = st.get("time") or {}
    dur = t.get("end") - t.get("start") if t.get("start") and t.get("end") else None

    tool = ToolUse(
        id=str(pd.get("callID") or p["id"]),
        name=name,
        category=categorize(name),
        status=status,
        started_at=t.get("start"),
        input=truncate(st.get("input"), trunc),
        output=truncate(st.get("output"), trunc),
        error=truncate(st.get("error"), trunc),
        duration_ms=dur,
    )
    row = tool_usage.get(tool.id)
    if row:
        if tool.duration_ms is None:
            tool.duration_ms = row.get("duration_ms")
        tool.exit_code = row.get("exit_code")
        approval = (row.get("approval_status") or "").lower()
        if approval in ("denied", "rejected"):
            tool.status = TOOL_ERROR
            tool.error = tool.error or f"permission {approval}"
        if row.get("error_message") and not tool.error:
            tool.error = truncate(row["error_message"], trunc)
        if row.get("cancelled_by_user"):
            tool.status = TOOL_CANCELLED
    return tool


def _finalize_turn(turn: Turn, tu: dict[str, Any] | None) -> None:
    starts = [c.started_at for c in turn.model_calls if c.started_at is not None]
    ends = []
    for c in turn.model_calls:
        if c.started_at is not None and c.duration_ms is not None:
            ends.append(c.started_at + c.duration_ms)
    if turn.started_at is None and starts:
        turn.started_at = min(starts)
    if tu:
        if tu.get("duration_ms") is not None:
            turn.duration_ms = tu["duration_ms"]
        elif tu.get("started_at") and tu.get("completed_at"):
            turn.duration_ms = tu["completed_at"] - tu["started_at"]
    if turn.duration_ms is None and turn.started_at is not None and ends:
        turn.duration_ms = max(ends) - turn.started_at
    if tu:
        if tu.get("status") == "error" or tu.get("error_type"):
            turn.status = "error"
        elif tu.get("status") == "cancelled" or tu.get("cancelled_by_user"):
            turn.status = "interrupted"
    if turn.status == "ok" and any(
        c.status == "error" or c.error for c in turn.model_calls
    ):
        turn.status = "error"
