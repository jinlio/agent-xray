"""Test fixtures: synthetic ZCode sqlite databases and Claude Code transcripts.

The synthetic sqlite schema mirrors the real ~/.zcode/cli/db/db.sqlite layout
(column names the adapter relies on); it is generated deterministically so the
golden snapshots are stable. Every statement is a parameterized literal.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

BASE = 1_760_000_000_000  # fixed epoch ms

SCHEMA = """
CREATE TABLE session (
  id text primary key, project_id text, parent_id text, slug text, directory text,
  title text, version text, task_type text default 'interactive', last_outcome text,
  time_created integer, time_updated integer
);
CREATE TABLE message (
  id text primary key, session_id text, time_created integer, time_updated integer,
  sequence integer, data text
);
CREATE TABLE part (
  id text primary key, message_id text, session_id text, time_created integer,
  time_updated integer, sequence integer, data text
);
CREATE TABLE turn_usage (
  session_id text, turn_id text, user_message_id text, status text,
  started_at integer, completed_at integer, duration_ms integer,
  model_request_count integer default 0, model_retry_count integer default 0,
  tool_call_count integer default 0, tool_error_count integer default 0,
  input_tokens integer default 0, output_tokens integer default 0,
  reasoning_tokens integer default 0, cache_creation_input_tokens integer default 0,
  cache_read_input_tokens integer default 0, context_exceeded integer default 0,
  error_type text, error_code text, cancelled_by_user integer default 0,
  PRIMARY KEY (session_id, turn_id)
);
CREATE TABLE model_usage (
  id text primary key, assistant_message_id text, session_id text, turn_id text,
  query_source text, provider_id text, model_id text, agent text, status text,
  started_at integer, completed_at integer, duration_ms integer, finish_reason text,
  tool_call_count integer default 0, input_tokens integer default 0,
  output_tokens integer default 0, reasoning_tokens integer default 0,
  cache_creation_input_tokens integer default 0, cache_read_input_tokens integer default 0,
  retry_count integer default 0, error_type text, error_message text
);
CREATE TABLE tool_usage (
  id text primary key, session_id text, turn_id text, tool_call_id text,
  tool_name text, approval_status text, status text, started_at integer,
  completed_at integer, duration_ms integer, exit_code integer,
  error_message text, cancelled_by_user integer default 0
);
"""


class ZcodeDbBuilder:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self._seq = 0

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def session(self, sid: str, *, title: str = "测试会话", parent_id: str | None = None,
                task_type: str = "interactive", last_outcome: str | None = None,
                time_created: int = BASE, time_updated: int = BASE + 60_000,
                directory: str = "/tmp/proj") -> str:
        row = (sid, "proj_test", parent_id, sid, directory, title, "0.17.0",
               task_type, last_outcome, time_created, time_updated)
        self.conn.execute("INSERT INTO session (id, project_id, parent_id, slug, directory, title, version, task_type, last_outcome, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
        return sid

    def message(self, sid: str, mid: str, ts: int, data: dict) -> str:
        self._seq += 1
        payload = json.dumps(data, ensure_ascii=False)
        self.conn.execute("INSERT INTO message (id, session_id, time_created, time_updated, sequence, data) VALUES (?, ?, ?, ?, ?, ?)", (mid, sid, ts, ts, self._seq, payload))
        return mid

    def part(self, mid: str, sid: str, pid: str, ts: int, data: dict) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        self.conn.execute("INSERT INTO part (id, message_id, session_id, time_created, time_updated, sequence, data) VALUES (?, ?, ?, ?, ?, ?, ?)", (pid, mid, sid, ts, ts, self._seq, payload))
        return pid

    def turn_usage(self, sid: str, turn_id: str, status: str = "completed",
                   started_at: int | None = None, completed_at: int | None = None,
                   duration_ms: int | None = None, model_request_count: int = 0,
                   model_retry_count: int = 0, tool_call_count: int = 0,
                   tool_error_count: int = 0, input_tokens: int = 0, output_tokens: int = 0,
                   reasoning_tokens: int = 0, cache_creation_input_tokens: int = 0,
                   cache_read_input_tokens: int = 0, context_exceeded: int = 0,
                   error_type: str | None = None, error_code: str | None = None,
                   cancelled_by_user: int = 0) -> None:
        row = (sid, turn_id, status, started_at, completed_at, duration_ms,
               model_request_count, model_retry_count, tool_call_count, tool_error_count,
               input_tokens, output_tokens, reasoning_tokens, cache_creation_input_tokens,
               cache_read_input_tokens, context_exceeded, error_type, error_code,
               cancelled_by_user)
        self.conn.execute("INSERT INTO turn_usage (session_id, turn_id, status, started_at, completed_at, duration_ms, model_request_count, model_retry_count, tool_call_count, tool_error_count, input_tokens, output_tokens, reasoning_tokens, cache_creation_input_tokens, cache_read_input_tokens, context_exceeded, error_type, error_code, cancelled_by_user) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)

    def model_usage(self, mid: str, sid: str, assistant_message_id: str | None = None,
                    turn_id: str | None = None, query_source: str = "main_turn",
                    provider_id: str | None = None, model_id: str | None = None,
                    agent: str | None = None, status: str = "completed",
                    started_at: int | None = None, completed_at: int | None = None,
                    duration_ms: int | None = None, finish_reason: str | None = None,
                    tool_call_count: int = 0, input_tokens: int = 0, output_tokens: int = 0,
                    reasoning_tokens: int = 0, cache_creation_input_tokens: int = 0,
                    cache_read_input_tokens: int = 0, retry_count: int = 0,
                    error_type: str | None = None, error_message: str | None = None) -> None:
        row = (mid, sid, assistant_message_id, turn_id, query_source, provider_id, model_id,
               agent, status, started_at, completed_at, duration_ms, finish_reason,
               tool_call_count, input_tokens, output_tokens, reasoning_tokens,
               cache_creation_input_tokens, cache_read_input_tokens, retry_count,
               error_type, error_message)
        self.conn.execute("INSERT INTO model_usage (id, session_id, assistant_message_id, turn_id, query_source, provider_id, model_id, agent, status, started_at, completed_at, duration_ms, finish_reason, tool_call_count, input_tokens, output_tokens, reasoning_tokens, cache_creation_input_tokens, cache_read_input_tokens, retry_count, error_type, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)

    def tool_usage(self, sid: str, call_id: str, turn_id: str | None = None,
                   tool_name: str = "", approval_status: str | None = None,
                   status: str = "completed", started_at: int | None = None,
                   completed_at: int | None = None, duration_ms: int | None = None,
                   exit_code: int | None = None, error_message: str | None = None,
                   cancelled_by_user: int = 0) -> None:
        row = (f"tu-{call_id}", sid, turn_id, call_id, tool_name, approval_status, status,
               started_at, completed_at, duration_ms, exit_code, error_message,
               cancelled_by_user)
        self.conn.execute("INSERT INTO tool_usage (id, session_id, turn_id, tool_call_id, tool_name, approval_status, status, started_at, completed_at, duration_ms, exit_code, error_message, cancelled_by_user) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)


def build_zcode_fixture(path: Path) -> Path:
    """Two real turns + hidden noise + aux title call + one subagent child."""
    b = ZcodeDbBuilder(path)
    main = "session_testmain"
    child = "sess_subagent_agent_11111111"
    b.session(main, title="修复登录 bug", last_outcome="completed")
    b.session(child, parent_id=main, task_type="subagent_child", title="子代理",
              time_created=BASE + 5000, time_updated=BASE + 9000)
    # a second interactive session so batch mode has >1 entry
    second = "session_second"
    b.session(second, title="第二个会话", time_created=BASE + 100_000,
              time_updated=BASE + 110_000)
    b.message(second, "s_u1", BASE + 100_000, {
        "role": "user", "semantics": {"origin": "real_user", "kind": "user_prompt",
                                      "uiVisibility": "visible"},
        "anchor": {"turnId": "turn_s1"},
    })
    b.part("s_u1", second, "sp_u1", BASE + 100_000, {"type": "text", "text": "第二个会话"})

    # ---- turn A ----
    b.message(main, "m_u1", BASE, {
        "role": "user", "semantics": {"origin": "real_user", "kind": "user_prompt",
                                      "uiVisibility": "visible"},
        "anchor": {"turnId": "turn_a"},
    })
    b.part("m_u1", main, "p_u1", BASE, {"type": "text", "text": "帮我修复登录 bug"})

    b.message(main, "m_a1", BASE + 2000, {
        "role": "assistant", "agent": "zcode-agent", "modelId": "GLM-5.3",
        "providerId": "prov-1", "finish": "tool-calls",
        "time": {"created": BASE + 2000, "completed": BASE + 7000},
        "tokens": {"input": 1000, "output": 200, "reasoning": 50,
                   "cache": {"read": 800, "write": 100}},
        "semantics": {"origin": "agent_runtime", "kind": "assistant_response",
                      "uiVisibility": "visible"},
        "anchor": {"turnId": "turn_a"},
    })
    b.part("m_a1", main, "p_a1_r", BASE + 2100, {"type": "reasoning", "text": "让我看看代码"})
    b.part("m_a1", main, "p_a1_t", BASE + 2200, {"type": "text", "text": "好的，我先查看"})
    b.part("m_a1", main, "p_a1_tool1", BASE + 3000, {
        "type": "tool", "tool": "Bash", "callID": "call_1",
        "state": {"status": "completed", "input": {"command": "ls"},
                  "output": "a.py\nb.py", "time": {"start": BASE + 3000, "end": BASE + 3400}},
    })
    b.part("m_a1", main, "p_a1_tool2", BASE + 3500, {
        "type": "tool", "tool": "Edit", "callID": "call_2",
        "state": {"status": "error", "input": {"file_path": "a.py"},
                  "error": "File has not been read yet. Read it first before writing to it.",
                  "time": {"start": BASE + 3500, "end": BASE + 3600}},
    })
    b.model_usage("mu1", main, assistant_message_id="m_a1", turn_id="turn_a",
                  query_source="main_turn", model_id="GLM-5.3", agent="zcode-agent",
                  status="completed", started_at=BASE + 2000, completed_at=BASE + 7000,
                  duration_ms=4800, finish_reason="tool-calls",
                  input_tokens=1000, output_tokens=200, reasoning_tokens=50,
                  cache_read_input_tokens=800, cache_creation_input_tokens=100)
    b.tool_usage(main, "call_1", turn_id="turn_a", tool_name="Bash", status="completed",
                 started_at=BASE + 3000, completed_at=BASE + 3400, duration_ms=400, exit_code=0)
    b.tool_usage(main, "call_2", turn_id="turn_a", tool_name="Edit", status="error",
                 started_at=BASE + 3500, completed_at=BASE + 3600, duration_ms=100,
                 error_message="File has not been read yet. Read it first before writing to it.")
    b.turn_usage(main, "turn_a", status="completed", started_at=BASE,
                 completed_at=BASE + 7000, duration_ms=7000, model_request_count=1,
                 tool_call_count=2, tool_error_count=1, input_tokens=1000,
                 output_tokens=200, cache_read_input_tokens=800,
                 cache_creation_input_tokens=100)

    # hidden synthetic noise
    b.message(main, "m_hidden", BASE + 7500, {
        "role": "user", "synthetic": True,
        "semantics": {"origin": "agent_runtime", "kind": "todo_reminder",
                      "uiVisibility": "hidden"},
    })

    # ---- turn B ----
    b.message(main, "m_u2", BASE + 10_000, {
        "role": "user", "semantics": {"origin": "real_user", "kind": "user_prompt",
                                      "uiVisibility": "visible"},
        "anchor": {"turnId": "turn_b"},
    })
    b.part("m_u2", main, "p_u2", BASE + 10_000, {"type": "text", "text": "再跑一下测试"})
    b.message(main, "m_a2", BASE + 12_000, {
        "role": "assistant", "agent": "zcode-agent", "modelId": "qwen3.8-flash",
        "finish": "stop",
        "time": {"created": BASE + 12_000, "completed": BASE + 16_000},
        "tokens": {"input": 2000, "output": 500, "reasoning": 0,
                   "cache": {"read": 1500, "write": 0}},
        "semantics": {"origin": "agent_runtime", "kind": "assistant_response",
                      "uiVisibility": "visible"},
        "anchor": {"turnId": "turn_b"},
    })
    b.part("m_a2", main, "p_a2_t", BASE + 15_000, {"type": "text", "text": "测试通过 ✅"})
    b.part("m_a2", main, "p_a2_tl", BASE + 15_500, {
        "type": "timeline", "timelineType": "model_change",
        "fromModel": "qwen3.8-flash", "toModel": "GLM-5.3",
    })
    b.part("m_a2", main, "p_a2_cmp", BASE + 15_800, {
        "type": "compaction", "auto": True, "trigger": "auto", "phase": "mid_turn",
        "compactReason": "context_limit", "preCompactTokenCount": 100_000,
        "postCompactTokenCount": 50_000,
    })
    b.model_usage("mu2", main, assistant_message_id="m_a2", turn_id="turn_b",
                  query_source="main_turn", model_id="qwen3.8-flash", agent="zcode-agent",
                  status="completed", started_at=BASE + 12_000, completed_at=BASE + 16_000,
                  duration_ms=4000, finish_reason="stop",
                  input_tokens=2000, output_tokens=500,
                  cache_read_input_tokens=1500, retry_count=1)
    b.turn_usage(main, "turn_b", status="error", started_at=BASE + 10_000,
                 completed_at=BASE + 16_000, duration_ms=6000, model_request_count=1,
                 model_retry_count=1, context_exceeded=1, error_type="ApiError",
                 error_code="CONTEXT")

    # ---- aux background call (title generation, no message row) ----
    b.model_usage("mu_title", main, turn_id="turn_title_x", query_source="session_title",
                  model_id="qwen3.8-flash", status="completed", started_at=BASE + 17_000,
                  duration_ms=900, finish_reason="stop", input_tokens=300, output_tokens=10)

    # ---- child subagent session ----
    b.message(child, "c_u1", BASE + 5000, {
        "role": "user", "semantics": {"origin": "agent_runtime", "kind": "user_prompt",
                                      "uiVisibility": "visible"},
        "anchor": {"turnId": "cturn_a"},
    })
    b.part("c_u1", child, "cp_u1", BASE + 5000, {"type": "text", "text": "探索这个目录"})
    b.message(child, "c_a1", BASE + 6000, {
        "role": "assistant", "agent": "zcode-Explore", "modelId": "GLM-5.3-Flash",
        "finish": "stop", "time": {"created": BASE + 6000, "completed": BASE + 8000},
        "tokens": {"input": 500, "output": 100, "reasoning": 0,
                   "cache": {"read": 0, "write": 0}},
        "semantics": {"origin": "agent_runtime", "kind": "assistant_response",
                      "uiVisibility": "visible"},
        "anchor": {"turnId": "cturn_a"},
    })
    b.part("c_a1", child, "cp_a1", BASE + 7000, {"type": "text", "text": "目录里有 3 个文件"})

    b.close()
    return path


# ---------------------------------------------------------------------------
# Claude Code transcript factory


def build_cc_fixture(path: Path) -> Path:
    lines = [
        json.dumps({"type": "summary", "summary": "修复 OAuth 登录", "leafUuid": "u9"}),
        '{"this is": "not valid json but broken on purpose"',  # bad line → skipped
        json.dumps({"type": "user", "uuid": "u1", "timestamp": "2026-10-20T10:00:00Z",
                    "sessionId": "cc1", "cwd": "/tmp/cc", "version": "1.2.3",
                    "message": {"role": "user", "content": "修复 OAuth 登录"}}),
        # assistant response split across two lines, same message.id, duplicate usage
        json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                    "timestamp": "2026-10-20T10:00:30Z", "sessionId": "cc1",
                    "costUSD": 0.01,
                    "message": {"id": "msg_01", "model": "claude-sonnet-4-5", "role": "assistant",
                                "content": [{"type": "thinking", "thinking": "分析问题"},
                                            {"type": "text", "text": "我先看下"},
                                            {"type": "tool_use", "id": "toolu_01", "name": "Read",
                                             "input": {"file_path": "a.py"}}],
                                "usage": {"input_tokens": 100, "output_tokens": 50,
                                          "cache_read_input_tokens": 200,
                                          "cache_creation_input_tokens": 10}}}),
        json.dumps({"type": "assistant", "uuid": "u2b", "parentUuid": "u1",
                    "timestamp": "2026-10-20T10:00:35Z", "sessionId": "cc1",
                    "costUSD": 0.01,
                    "message": {"id": "msg_01", "model": "claude-sonnet-4-5", "role": "assistant",
                                "content": [{"type": "text", "text": "我先看下代码"}],
                                "usage": {"input_tokens": 100, "output_tokens": 50,
                                          "cache_read_input_tokens": 200,
                                          "cache_creation_input_tokens": 10}}}),
        json.dumps({"type": "user", "uuid": "u3", "timestamp": "2026-10-20T10:01:00Z",
                    "sessionId": "cc1",
                    "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_01",
                         "content": "file contents", "is_error": False}]}}),
        json.dumps({"type": "user", "uuid": "u3m", "timestamp": "2026-10-20T10:01:05Z",
                    "isMeta": True, "sessionId": "cc1",
                    "message": {"role": "user", "content": "meta line should be skipped"}}),
        json.dumps({"type": "assistant", "uuid": "u4", "timestamp": "2026-10-20T10:02:00Z",
                    "sessionId": "cc1",
                    "message": {"id": "msg_02", "model": "claude-sonnet-4-5", "role": "assistant",
                                "content": [{"type": "tool_use", "id": "toolu_02", "name": "Bash",
                                             "input": {"command": "pytest"}}],
                                "usage": {"input_tokens": 300, "output_tokens": 80}}}),
        json.dumps({"type": "user", "uuid": "u5", "timestamp": "2026-10-20T10:02:30Z",
                    "sessionId": "cc1",
                    "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_02",
                         "content": "1 failed", "is_error": True}]}}),
        json.dumps({"type": "assistant", "uuid": "u6", "timestamp": "2026-10-20T10:03:00Z",
                    "sessionId": "cc1",
                    "message": {"id": "msg_03", "model": "claude-sonnet-4-5", "role": "assistant",
                                "content": [{"type": "text", "text": "测试失败原因是..."}],
                                "usage": {"input_tokens": 400, "output_tokens": 120}}}),
        # legacy string content
        json.dumps({"type": "user", "uuid": "u7", "timestamp": "2026-10-20T10:04:00Z",
                    "sessionId": "cc1",
                    "message": {"role": "user", "content": "旧版字符串消息"}}),
        # sidechain (subagent) records
        json.dumps({"type": "assistant", "uuid": "s1", "isSidechain": True,
                    "timestamp": "2026-10-20T10:02:10Z", "sessionId": "cc1",
                    "message": {"id": "msg_s1", "model": "claude-haiku-4-5", "role": "assistant",
                                "content": [{"type": "tool_use", "id": "toolu_s1", "name": "Grep",
                                             "input": {"pattern": "x"}}],
                                "usage": {"input_tokens": 50, "output_tokens": 20}}}),
        json.dumps({"type": "user", "uuid": "s2", "isSidechain": True, "parentUuid": "s1",
                    "timestamp": "2026-10-20T10:02:20Z", "sessionId": "cc1",
                    "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_s1",
                         "content": "no matches", "is_error": False}]}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# pytest fixtures


@pytest.fixture
def zcode_db(tmp_path) -> Path:
    return build_zcode_fixture(tmp_path / "db.sqlite")


@pytest.fixture
def cc_transcript(tmp_path) -> Path:
    return build_cc_fixture(tmp_path / "transcript.jsonl")
