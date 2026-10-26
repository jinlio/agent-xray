"""Adapter + renderer + CLI test suite."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from agent_xray import cost as cost_module
from agent_xray.adapters import claude_code as cc_adapter
from agent_xray.adapters import codex as codex_adapter
from agent_xray.adapters import zcode_db as zcode_adapter
from agent_xray.cli import main, pick_source
from agent_xray.cost import PriceTable, estimate_cost, load_price_table
from agent_xray.model import Usage, to_dict
from agent_xray.render import render_index, render_session
from conftest import BASE, build_codex_fixture, build_zcode_fixture

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
def prices(monkeypatch, tmp_path):
    # hermetic: ignore a real ~/.agent-xray/prices.json on this machine
    monkeypatch.setattr(cost_module, "user_price_path", lambda: tmp_path / "absent.json")
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


def test_cc_list_transcripts_recursive(tmp_path):
    """Claude Code 2.1+ nests subagent files under <session>/subagents/."""
    (tmp_path / "main.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    sub = tmp_path / "main" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-x.jsonl").write_text('{"type":"assistant"}\n', encoding="utf-8")
    (sub / "skip.txt").write_text("x", encoding="utf-8")
    files = cc_adapter.list_transcripts(tmp_path)
    assert [f.name for f in files] == ["agent-x.jsonl", "main.jsonl"]


def test_cc_standalone_subagent_file(tmp_path):
    """A subagent-only transcript (every conversational record isSidechain)
    parses as its own session instead of an empty parent + sidechain child."""
    lines = [
        '{"type": "attachment", "uuid": "at1"}',  # unflagged noise stays in main
        json.dumps({"type": "user", "uuid": "u1", "isSidechain": True,
                    "timestamp": "2026-10-20T10:00:00Z",
                    "message": {"role": "user", "content": "审查后端代码"}}),
        json.dumps({"type": "assistant", "uuid": "u2", "isSidechain": True,
                    "timestamp": "2026-10-20T10:00:30Z",
                    "message": {"id": "msg_s1", "model": "claude-haiku-4-5",
                                "role": "assistant",
                                "content": [{"type": "text", "text": "已审查"}],
                                "usage": {"input_tokens": 50, "output_tokens": 20}}}),
    ]
    p = tmp_path / "agent-x.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    session = cc_adapter.parse_file(p)
    assert session.stats.turn_count == 1
    assert session.stats.model_call_count == 1
    assert session.stats.usage.input == 50
    assert session.child_sessions == []
    assert session.title.startswith("(subagent)")
    assert "审查后端代码" in session.title


def test_cc_subagents_dir_attached(tmp_path):
    """A main transcript picks up <stem>/subagents/*.jsonl as child sessions."""
    main_lines = [
        json.dumps({"type": "user", "uuid": "u1", "timestamp": "2026-10-20T10:00:00Z",
                    "message": {"role": "user", "content": "跑一下测试"}}),
        json.dumps({"type": "assistant", "uuid": "u2", "timestamp": "2026-10-20T10:00:30Z",
                    "message": {"id": "msg_01", "model": "claude-sonnet-4-5",
                                "role": "assistant", "content": [{"type": "text", "text": "ok"}],
                                "usage": {"input_tokens": 100, "output_tokens": 10}}}),
    ]
    main_p = tmp_path / "sess-main.jsonl"
    main_p.write_text("\n".join(main_lines) + "\n", encoding="utf-8")
    sub = tmp_path / "sess-main" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text(
        json.dumps({"type": "user", "uuid": "s1", "isSidechain": True,
                    "timestamp": "2026-10-20T10:01:00Z",
                    "message": {"role": "user", "content": "子代理任务"}}) + "\n"
        + json.dumps({"type": "assistant", "uuid": "s2", "isSidechain": True,
                      "timestamp": "2026-10-20T10:01:30Z",
                      "message": {"id": "msg_s", "model": "claude-haiku-4-5",
                                  "role": "assistant",
                                  "content": [{"type": "text", "text": "完成"}],
                                  "usage": {"input_tokens": 30, "output_tokens": 5}}}) + "\n",
        encoding="utf-8")
    session = cc_adapter.parse_file(main_p)
    assert session.stats.model_call_count == 1
    assert len(session.child_sessions) == 1
    child = session.child_sessions[0]
    assert child.stats.model_call_count == 1
    assert child.stats.usage.input == 30
    assert child.title.startswith("(subagent)")


# ---------------------------------------------------------------------------
# codex adapter


def test_codex_parse_golden(codex_rollout, prices):
    session = codex_adapter.parse_file(codex_rollout, prices=prices)
    st = session.stats
    assert session.id == "sess-cx1"
    assert session.source == "codex"
    assert session.app_version == "0.160.1"
    assert session.cwd == "C:\\tmp\\proj"
    assert session.title == "帮我检查这个仓库"
    assert st.turn_count == 2
    assert st.model_call_count == 3  # turn1: 2 segments, turn2: 1
    assert st.tool_count == 3
    assert st.tool_error_count == 1
    assert st.hidden_message_count == 1  # developer message
    assert st.parse_error_count == 1  # the garbage line
    # usage rolls up across turns: 1000+1200+800 input
    assert st.usage.input == 3000
    assert st.usage.output == 240
    assert st.usage.cache_read == 900
    assert st.usage.cache_write == 100
    assert st.usage.reasoning == 40
    assert session.models == ["gpt-5.6-terra", "gpt-6.1-sol"]  # child not in parent models
    # per-segment usage attribution: seg1 got resp_1, seg2 got resp_2
    t1 = session.turns[0]
    assert t1.user_text == "帮我检查这个仓库"
    assert len(t1.model_calls) == 2
    assert t1.model_calls[0].usage.input == 1000
    assert t1.model_calls[0].tool_uses[0].name == "exec"
    assert t1.model_calls[0].tool_uses[0].status == "ok"
    assert t1.model_calls[1].usage.input == 1200
    assert t1.model_calls[1].text == "检查完成，共 2 个文件"
    # interrupted turn with failed tool
    t2 = session.turns[1]
    assert t2.status == "interrupted"
    kinds = sorted(f.kind for f in st.failures)
    assert kinds.count("tool_error") == 1
    assert kinds.count("interrupted") == 1
    # compaction annotation landed on the last turn
    assert any(a.kind == "compaction" for a in t2.annotations)
    # nested collab turn became a child session
    assert len(session.child_sessions) == 1
    child = session.child_sessions[0]
    assert child.stats.model_call_count == 1
    assert child.stats.usage.input == 300
    assert child.models == ["gpt-5.6-luna"]
    assert "review" in child.title
    assert_golden("codex_golden.json", normalized(session))


def test_codex_empty_and_garbage(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    session = codex_adapter.parse_file(p)
    assert session.stats.turn_count == 0
    assert any("unsupported" in w for w in session.warnings)

    p2 = tmp_path / "garbage.jsonl"
    p2.write_text("not json\n{bad\n", encoding="utf-8")
    session = codex_adapter.parse_file(p2)
    assert session.stats.parse_error_count == 2
    assert session.stats.turn_count == 0
    assert any("session_meta" in w for w in session.warnings)


def test_codex_list_rollouts_recursive(tmp_path):
    """Rollouts live under date-nested YYYY/MM/DD directories."""
    d = tmp_path / "2026" / "10" / "07"
    d.mkdir(parents=True)
    (d / "rollout-a.jsonl").write_text('{"type":"session_meta"}\n', encoding="utf-8")
    (tmp_path / "rollout-b.jsonl").write_text('{"type":"session_meta"}\n', encoding="utf-8")
    (tmp_path / "empty.jsonl").write_text("", encoding="utf-8")
    files = codex_adapter.list_rollouts(tmp_path)
    assert [f.name for f in files] == ["rollout-a.jsonl", "rollout-b.jsonl"]


def test_codex_read_meta(codex_rollout, tmp_path):
    meta = codex_adapter.read_meta(codex_rollout)
    assert meta["session_id"] == "sess-cx1"
    assert meta["cli_version"] == "0.160.1"
    # a claude-code transcript is not a rollout
    other = tmp_path / "cc.jsonl"
    other.write_text('{"type":"user"}\n', encoding="utf-8")
    assert codex_adapter.read_meta(other) == {}


# ---------------------------------------------------------------------------
# cost


def test_price_lookup_and_math(monkeypatch, tmp_path):
    monkeypatch.setattr(cost_module, "user_price_path", lambda: tmp_path / "absent.json")
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


def test_price_file_merges_over_defaults(tmp_path):
    """A price file overrides its own models; other models keep built-in prices."""
    pf = tmp_path / "prices.json"
    pf.write_text(json.dumps({"models": [{"match": "glm-5.3", "input": 1.0, "output": 1.0}]}),
                  encoding="utf-8")
    table = load_price_table(pf)
    cost = estimate_cost(table, "glm-5.3", Usage(input=1_000_000, output=1_000_000))
    assert cost.total == pytest.approx(2.0)  # user entry wins over built-in glm
    # built-ins survive for untouched models
    other = estimate_cost(table, "claude-sonnet-5-5", Usage(input=1_000_000, output=1_000_000))
    assert other.total == pytest.approx(18.0)


def test_price_file_factors_and_replace(tmp_path):
    pf = tmp_path / "prices.json"
    pf.write_text(json.dumps({
        "cache_read_factor": 0.5,
        "cache_write_factor": 2.0,
        "replace_defaults": True,
        "models": [{"match": "m", "input": 1.0, "output": 1.0}],
    }), encoding="utf-8")
    table = load_price_table(pf)
    assert table.cache_read_factor == 0.5 and table.cache_write_factor == 2.0
    cost = estimate_cost(table, "m", Usage(cache_read=1_000_000, cache_write=1_000_000))
    assert cost.cache_read == pytest.approx(0.5)
    assert cost.cache_write == pytest.approx(2.0)
    # replace_defaults: built-ins gone → unknown models fall back to flat pricing
    assert table.lookup("claude-sonnet-5-5") is None


def test_price_user_config_autodiscovered(monkeypatch, tmp_path):
    """~/.agent-xray/prices.json is loaded automatically when --price-file is absent."""
    user = tmp_path / "prices.json"
    user.write_text(json.dumps({"models": [{"match": "gpt-5.6-terra", "input": 1.0, "output": 2.0}]}),
                    encoding="utf-8")
    monkeypatch.setattr(cost_module, "user_price_path", lambda: user)
    table = load_price_table()
    entry = table.lookup("gpt-5.6-terra")
    assert entry["input"] == 1.0  # user entry shadows the built-in gpt-5 prefix
    assert table.lookup("claude-opus-5-5")["input"] == 15.0  # built-ins still there

    # an explicit --price-file still wins over the auto-discovered file
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"models": [{"match": "gpt-5.6-terra", "input": 9.0, "output": 9.0}]}),
                        encoding="utf-8")
    assert load_price_table(explicit).lookup("gpt-5.6-terra")["input"] == 9.0

    # a broken auto-discovered file fails loudly instead of being ignored
    user.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid price file"):
        load_price_table()


def test_cli_dump_prices(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(cost_module, "user_price_path", lambda: tmp_path / "absent.json")
    assert main(["--dump-prices"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["cache_read_factor"] == 0.1
    assert any(e["match"] == "claude-sonnet" for e in data["models"])

    target = tmp_path / "sub" / "my-prices.json"
    assert main(["--dump-prices", str(target)]) == 0
    json.loads(target.read_text(encoding="utf-8"))
    # round-trip: the dumped file loads back to the same effective table
    table = load_price_table(target)
    assert table.lookup("glm-5.3")["input"] == 0.6
    assert "已导出" in capsys.readouterr().out


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
    assert '"时间轴"' in html and '"Timeline"' in html  # bilingual UI dictionary inlined
    assert "xray-lang" in html  # language choice persisted across reports
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
    idx_html = idx.read_text(encoding="utf-8")
    assert "x.html" in idx_html
    assert "会话索引" in idx_html and "Session Index" in idx_html  # bilingual index
    assert 'data-lang="zh"' in idx_html and 'data-lang="en"' in idx_html
    assert "xray-lang" in idx_html


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


# ---------------------------------------------------------------------------
# source sniffing (codex vs claude code)


def test_pick_source_sniffs_jsonl(tmp_path, codex_rollout, cc_transcript):
    import argparse

    src = pick_source(argparse.Namespace(path=str(codex_rollout), db=None))
    assert src.kind == "codex"
    src = pick_source(argparse.Namespace(path=str(cc_transcript), db=None))
    assert src.kind == "claude_code"


def test_cli_codex_end_to_end(tmp_path, capsys):
    sessions_dir = tmp_path / "sessions" / "2026" / "10" / "07"
    sessions_dir.mkdir(parents=True)
    rollout = build_codex_fixture(sessions_dir / "rollout-test.jsonl")
    out_dir = tmp_path / "rendered"

    assert main([str(rollout), "--summary"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and "gpt-5.6-terra" in out
    assert "中断" in out  # interrupted failure surfaced

    rc = main([str(rollout), "-o", str(out_dir)])
    assert rc == 0
    files = list(out_dir.glob("*.html"))
    assert len(files) == 1
    assert files[0].stat().st_size > 100_000

    rc = main([str(sessions_dir.parent.parent.parent), "--list"])
    assert rc == 0
    assert "sess-cx1" in capsys.readouterr().out


def test_cli_codex_unrecognized_format_warns(tmp_path, capsys):
    """A non-rollout, non-claude jsonl must not silently produce an empty report."""
    bogus = tmp_path / "bogus.jsonl"
    bogus.write_text('{"type": "something_else", "payload": {}}\n', encoding="utf-8")
    rc = main([str(bogus), "-o", str(tmp_path / "out")])
    assert rc == 0
    err = capsys.readouterr().err
    assert "⚠" in err and "unsupported" in err
