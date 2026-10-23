"""Adapter + renderer + CLI test suite."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from agent_xray.adapters import claude_code as cc_adapter
from agent_xray.adapters import zcode_db as zcode_adapter
from agent_xray.cli import main
from agent_xray.cost import PriceTable, estimate_cost, load_price_table
from agent_xray.model import Usage, to_dict
from agent_xray.render import render_index, render_session
from conftest import BASE, build_zcode_fixture

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE_GOLDEN = os.environ.get("UPDATE_GOLDEN") == "1"


# ---------------------------------------------------------------------------
# helpers


def normalized(session) -> dict:
    """Full JSON-safe dump with sorted keys for golden comparison."""
    return to_dict(session)


def load_golden(name: str) -> dict:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


def save_golden(name: str, data: dict) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def assert_golden(name: str, data: dict) -> None:
    if UPDATE_GOLDEN:
        save_golden(name, data)
        pytest.skip(f"golden {name} regenerated")
    actual = json.dumps(data, ensure_ascii=False, sort_keys=True)
    expected = json.dumps(load_golden(name), ensure_ascii=False, sort_keys=True)
    assert actual == expected, f"golden mismatch for {name}; run UPDATE_GOLDEN=1 to regenerate"


@pytest.fixture
def prices():
    return load_price_table()


# ---------------------------------------------------------------------------
# zcode adapter


def test_zcode_parse_golden(zcode_db, prices):
    conn = sqlite3.connect(str(zcode_db))
    conn.row_factory = sqlite3.Row
    session = zcode_adapter.parse_session(conn, "session_testmain", prices=prices)
    conn.close()

    st = session.stats
    assert st.turn_count == 2
    assert st.model_call_count == 2
    assert st.tool_count == 2
    assert st.tool_error_count == 1
    assert st.retry_count == 1
    assert st.aux_call_count == 1
    assert st.hidden_message_count == 1
    assert len(session.turns) == 2
    assert session.turns[0].user_text == "帮我修复登录 bug"
    assert session.turns[1].user_text == "再跑一下测试"
    assert session.turns[0].status == "ok"
    assert session.turns[1].status == "error"
    # tokens roll up: calls + aux (1000+2000+300 input, aux included)
    assert st.usage.input == 3300
    assert st.usage.output == 710
    # failures: tool error, retry, context (deduped to one), model error (turn_usage)
    kinds = sorted(f.kind for f in st.failures)
    assert kinds.count("tool_error") == 1
    assert kinds.count("retry") == 1
    assert kinds.count("context_exceeded") == 1
    assert "model_error" in kinds
    # child session attached
    assert len(session.child_sessions) == 1
    child = session.child_sessions[0]
    assert child.turns[0].user_text == "探索这个目录"
    assert child.models == ["GLM-5.3-Flash"]
    assert_golden("zcode_golden.json", normalized(session))


def test_zcode_drops_aux_only_turns(zcode_db, prices):
    conn = sqlite3.connect(str(zcode_db))
    conn.row_factory = sqlite3.Row
    session = zcode_adapter.parse_session(conn, "session_testmain", prices=prices)
    conn.close()
    # the session_title aux call must not appear as a user-visible turn
    assert all(t.user_text for t in session.turns)
    assert session.stats.aux_call_count == 1


def test_zcode_missing_usage_tables(tmp_path, prices):
    """Graceful degradation when usage tables are absent (schema drift)."""
    path = build_zcode_fixture(tmp_path / "bare.sqlite")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("DROP TABLE model_usage")
    conn.execute("DROP TABLE tool_usage")
    conn.execute("DROP TABLE turn_usage")
    session = zcode_adapter.parse_session(conn, "session_testmain", prices=prices)
    conn.close()
    assert session.stats.turn_count == 2
    assert session.stats.tool_count == 2  # from message parts, not tool_usage
    assert session.stats.tool_error_count == 1
    assert session.turns[0].model_calls[0].duration_ms == 5000  # from message time
    assert session.warnings  # degradations reported


def test_zcode_garbage_message_rows(zcode_db, prices):
    conn = sqlite3.connect(str(zcode_db))
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO message (id, session_id, time_created, time_updated, sequence, data) VALUES (?, ?, ?, ?, ?, ?)",
                 ("m_bad", "session_testmain", BASE + 99_000, BASE + 99_000, 999, "{not json"))
    conn.commit()
    session = zcode_adapter.parse_session(conn, "session_testmain", prices=prices)
    conn.close()
    assert session.stats.parse_error_count == 1


def test_zcode_list_sessions(zcode_db):
    conn = sqlite3.connect(str(zcode_db))
    conn.row_factory = sqlite3.Row
    rows = zcode_adapter.list_sessions(conn)
    conn.close()
    ids = [r["id"] for r in rows]
    assert "session_testmain" in ids
    row = next(r for r in rows if r["id"] == "session_testmain")
    assert row["message_count"] >= 4
    assert row["turn_count"] == 2
    assert row["tool_error_count"] == 1


def test_zcode_scale_20k_messages(tmp_path, prices):
    """A 20k-message session must parse in seconds."""
    path = tmp_path / "big.sqlite"
    build_zcode_fixture(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    base = BASE + 100_000
    for i in range(10_000):
        ts = base + i * 1000
        turn = f"turn_scale_{i // 2}"
        cur.execute("INSERT INTO message (id, session_id, time_created, time_updated, sequence, data) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"sm_u{i}", "session_testmain", ts, ts, i * 2,
                     json.dumps({"role": "user", "semantics": {"origin": "real_user", "kind": "user_prompt", "uiVisibility": "visible"}, "anchor": {"turnId": turn}})))
        cur.execute("INSERT INTO message (id, session_id, time_created, time_updated, sequence, data) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"sm_a{i}", "session_testmain", ts + 500, ts + 900, i * 2 + 1,
                     json.dumps({"role": "assistant", "modelId": "qwen3.8-flash", "finish": "stop", "time": {"created": ts + 500, "completed": ts + 900}, "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 0}}, "semantics": {"origin": "agent_runtime", "kind": "assistant_response", "uiVisibility": "visible"}, "anchor": {"turnId": turn}})))
    conn.commit()
    start = time.monotonic()
    session = zcode_adapter.parse_session(conn, "session_testmain", prices=prices)
    elapsed = time.monotonic() - start
    conn.close()
    assert session.stats.turn_count >= 5_000
    assert elapsed < 30, f"parsing 20k messages took {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# claude code adapter


def test_cc_parse_golden(cc_transcript, prices):
    session = cc_adapter.parse_file(cc_transcript, prices=prices)
    st = session.stats
    assert session.title == "修复 OAuth 登录"
    assert st.turn_count == 2  # real user prompt + legacy string content
    assert st.model_call_count == 3  # msg_01 (merged), msg_02, msg_03
    assert st.tool_count == 2
    assert st.tool_error_count == 1
    assert st.parse_error_count == 1  # the broken line
    # split-response merge: longest text wins, usage not double-counted
    call1 = session.turns[0].model_calls[0]
    assert call1.id == "msg_01"
    assert call1.text == "我先看下代码"
    assert call1.usage.input == 100
    assert call1.usage.cache_read == 200
    assert call1.cost is not None and abs(call1.cost.total - 0.01) < 1e-9
    # tool pairing via id <-> tool_use_id
    t1, t2 = call1.tool_uses[0], session.turns[0].model_calls[1].tool_uses[0]
    assert t1.status == "ok" and t1.output == "file contents"
    assert t2.status == "error" and t2.output == "1 failed"
    # meta user line did not create a turn
    assert session.turns[1].user_text == "旧版字符串消息"
    # sidechain extracted as child session
    assert len(session.child_sessions) == 1
    child = session.child_sessions[0]
    assert child.stats.model_call_count == 1
    assert child.turns[0].model_calls[0].tool_uses[0].status == "ok"
    assert_golden("claude_code_golden.json", normalized(session))


def test_cc_empty_and_garbage(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    session = cc_adapter.parse_file(p)
    assert session.stats.turn_count == 0

    p2 = tmp_path / "garbage.jsonl"
    p2.write_text("not json\n{bad\n[1,2]\n", encoding="utf-8")
    session = cc_adapter.parse_file(p2)
    assert session.stats.parse_error_count == 3
    assert session.stats.turn_count == 0


def test_cc_list_transcripts(tmp_path):
    (tmp_path / "a.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    (tmp_path / "b.jsonl").write_text("", encoding="utf-8")  # empty → skipped
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    files = cc_adapter.list_transcripts(tmp_path)
    assert [f.name for f in files] == ["a.jsonl"]


# ---------------------------------------------------------------------------
# cost


def test_price_lookup_and_math():
    table = load_price_table()
    usage = Usage(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000)
    cost = estimate_cost(table, "claude-sonnet-5-5", usage)
    assert cost.input == 3.0
    assert cost.output == 15.0
    assert cost.cache_read == pytest.approx(0.3)
    assert cost.cache_write == pytest.approx(3.75)
    assert cost.total == pytest.approx(22.05)

    glm = estimate_cost(table, "GLM-5.3", Usage(input=500_000, output=100_000))
    assert glm.input == pytest.approx(0.3)
    assert glm.output == pytest.approx(0.22)

    # unknown model → fallback pricing; unpriced entry → None
    assert estimate_cost(table, "totally-unknown-model", Usage(input=1_000_000)) is not None
    custom = PriceTable([{"match": "private-model", "input": None, "output": None}])
    assert estimate_cost(custom, "private-model", Usage(input=1000)) is None


def test_price_file_override(tmp_path):
    pf = tmp_path / "prices.json"
    pf.write_text(json.dumps({"models": [{"match": "glm-5.3", "input": 1.0, "output": 1.0}]}),
                  encoding="utf-8")
    table = load_price_table(pf)
    cost = estimate_cost(table, "glm-5.3", Usage(input=1_000_000, output=1_000_000))
    assert cost.total == pytest.approx(2.0)  # 1.0 input + 1.0 output, no cache tokens


# ---------------------------------------------------------------------------
# renderer + CLI


def test_render_smoke(zcode_db, cc_transcript, tmp_path, prices):
    conn = sqlite3.connect(str(zcode_db))
    conn.row_factory = sqlite3.Row
    session = zcode_adapter.parse_session(conn, "session_testmain", prices=prices)
    conn.close()
    out = tmp_path / "out" / "x.html"
    render_session(session, out)
    html = out.read_text(encoding="utf-8")
    assert "__XRAY_" not in html, "placeholder left unreplaced"
    assert 'id="xray-data"' in html
    assert "echarts" in html.lower()
    assert "帮我修复登录 bug" in html  # embedded payload keeps CJK readable
    assert out.stat().st_size > 500_000  # echarts inlined → fully offline

    cc = cc_adapter.parse_file(cc_transcript, prices=prices)
    out2 = tmp_path / "out" / "cc.html"
    render_session(cc, out2)
    assert out2.exists()

    entries = [{"path": "x.html", "title": "t", "when": "w", "turns": 1, "calls": 2,
                "fails": 0, "tokens": "1k", "cost": "$0.01"},
               {"path": "cc.html", "title": "c", "when": "w", "turns": 2, "calls": 3,
                "fails": 1, "tokens": "2k", "cost": "$0.02"}]
    idx = render_index(entries, tmp_path / "out" / "index.html")
    assert "x.html" in idx.read_text(encoding="utf-8")


def test_cli_list_and_summary(zcode_db, capsys):
    assert main(["--db", str(zcode_db), "--list"]) == 0
    out = capsys.readouterr().out
    assert "session_testmain" in out and "修复登录 bug" in out

    assert main(["--db", str(zcode_db), "--summary", "--session", "2"]) == 0
    out = capsys.readouterr().out
    assert "失败点" in out and "工具失败" in out


def test_cli_render_end_to_end(zcode_db, tmp_path, capsys):
    out_dir = tmp_path / "rendered"
    rc = main(["--db", str(zcode_db), "--session", "1", "-o", str(out_dir)])
    assert rc == 0
    files = list(out_dir.glob("*.html"))
    assert len(files) == 1
    assert files[0].stat().st_size > 100_000
    capsys.readouterr()


def test_cli_render_all_with_index(zcode_db, tmp_path):
    out_dir = tmp_path / "rendered"
    rc = main(["--db", str(zcode_db), "--all", "--limit", "5", "-o", str(out_dir)])
    assert rc == 0
    assert (out_dir / "index.html").exists()


def test_cli_missing_db(tmp_path, capsys):
    rc = main(["--db", str(tmp_path / "nope.sqlite"), "--list"])
    assert rc == 2
    assert "错误" in capsys.readouterr().err
