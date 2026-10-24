"""agent-xray CLI.

    agent-xray                      # list sessions in the auto-discovered ZCode db
    agent-xray --summary            # terminal summary of the most recent session
    agent-xray --session <id>       # render one session to a single HTML file
    agent-xray transcript.jsonl     # render a Claude Code transcript
    agent-xray ~/.claude/projects/X # batch-render a directory + index page
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import claude_code, zcode_db
from .cost import load_price_table
from .model import Session, truncate
from .render import render_index, render_session

# ---------------------------------------------------------------------------
# sources


class ZcodeSource:
    kind = "zcode_db"

    def __init__(self, db_path: str | Path | None = None):
        self.path = zcode_db.discover_db(db_path)
        self.conn, self._tmp = zcode_db.open_snapshot(self.path)

    def sessions(self) -> list[dict[str, Any]]:
        return zcode_db.list_sessions(self.conn)

    def load(self, sid: str, trunc: int, prices: Any) -> Session:
        return zcode_db.parse_session(self.conn, sid, trunc=trunc, prices=prices)

    def close(self) -> None:
        zcode_db.close_snapshot(self.conn, self._tmp)


class TranscriptSource:
    """A single Claude Code .jsonl transcript (or a directory of them)."""

    kind = "claude_code"

    def __init__(self, path: Path):
        self.path = path
        self.files = [path] if path.is_file() else claude_code.list_transcripts(path)
        if not self.files:
            raise FileNotFoundError(f"no .jsonl transcripts found under {path}")

    def sessions(self) -> list[dict[str, Any]]:
        out = []
        for i, f in enumerate(self.files):
            out.append(
                {
                    "id": f.stem,
                    "title": f.name,
                    "time_created": f.stat().st_mtime * 1000,
                    "duration_ms": None,
                    "message_count": None,
                    "turn_count": None,
                    "tool_error_count": None,
                    "_file": f,
                    "_index": i,
                }
            )
        out.sort(key=lambda x: x["time_created"], reverse=True)
        return out

    def load(self, sid: str, trunc: int, prices: Any) -> Session:
        for f in self.files:
            if f.stem == sid:
                return claude_code.parse_file(f, trunc=trunc, prices=prices)
        raise ValueError(f"transcript not found: {sid}")

    def load_file(self, f: Path, trunc: int, prices: Any) -> Session:
        return claude_code.parse_file(f, trunc=trunc, prices=prices)

    def close(self) -> None:
        pass


def pick_source(args: argparse.Namespace) -> ZcodeSource | TranscriptSource:
    raw = args.path
    if raw is None:
        return ZcodeSource(args.db)
    p = Path(raw).expanduser()
    if p.is_file() and p.suffix == ".jsonl":
        return TranscriptSource(p)
    if p.is_file() and (p.suffix in (".sqlite", ".db") or p.name.endswith(".sqlite")):
        return ZcodeSource(p)
    if p.is_dir():
        if any(p.glob("*.jsonl")):
            return TranscriptSource(p)
        nested = p / "db.sqlite"
        if nested.exists():
            return ZcodeSource(nested)
        raise FileNotFoundError(f"no .jsonl transcripts or db.sqlite under {p}")
    # unknown file: let zcode db discovery try it (helpful error otherwise)
    return ZcodeSource(p)


def resolve_session_id(source: ZcodeSource | TranscriptSource, sel: str | None) -> tuple[str, dict[str, Any]]:
    sessions = source.sessions()
    if not sessions:
        raise ValueError("no sessions found")
    if sel is None:
        return sessions[0]["id"], sessions[0]
    if sel.isdigit() and len(sel) <= 4:  # 1-based index into --list order
        idx = int(sel)
        if 1 <= idx <= len(sessions):
            return sessions[idx - 1]["id"], sessions[idx - 1]
    for s in sessions:
        if s["id"] == sel:
            return s["id"], s
    matches = [s for s in sessions if s["id"].startswith(sel)]
    if len(matches) == 1:
        return matches[0]["id"], matches[0]
    if len(matches) > 1:
        raise ValueError(f"ambiguous session prefix {sel!r}: {len(matches)} matches")
    raise ValueError(f"session not found: {sel!r} (use --list to see ids)")


# ---------------------------------------------------------------------------
# output


def _fmt_dur(ms: int | None) -> str:
    if not ms:
        return "—"
    s = ms / 1000
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{int(s // 60)}m{int(s % 60):02d}s"
    return f"{int(s // 3600)}h{int((s % 3600) // 60):02d}m"


def _fmt_tok(n: float) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}k"
    return f"{n:.0f}"


FAIL_LABEL = {
    "tool_error": "工具失败",
    "model_error": "模型调用失败",
    "retry": "重试",
    "context_exceeded": "上下文超限",
    "permission_denied": "权限拒绝",
    "interrupted": "中断",
    "long_turn": "超长轮次",
}


def print_summary(session: Session) -> None:
    st = session.stats
    print(f"# {session.title or '(无标题)'}")
    print(f"  id: {session.id}")
    print(f"  来源: {session.source}   版本: {session.app_version or '—'}")
    print(f"  目录: {session.cwd or '—'}")
    print(f"  开始: {_fmt_time(session.created_at)}   时长: {_fmt_dur(session.duration_ms)}")
    print(f"  模型: {', '.join(session.models) or '—'}")
    u = st.usage
    print(
        f"  轮次 {st.turn_count} · 模型调用 {st.model_call_count}"
        + (f" (+{st.aux_call_count} 后台)" if st.aux_call_count else "")
        + f" · 工具 {st.tool_count} · 重试 {st.retry_count}"
    )
    print(
        f"  tokens: in {_fmt_tok(u.input)} / out {_fmt_tok(u.output)} / "
        f"cache {_fmt_tok(u.cache_read)} (合计 {_fmt_tok(u.total)})"
    )
    print(f"  成本估算: ${st.cost.total:.4f}")
    if st.failures:
        print(f"  失败点 ({len(st.failures)}):")
        for f in st.failures[:20]:
            print(f"    [{FAIL_LABEL.get(f.kind, f.kind)}] turn #{f.turn_index}: {truncate(f.message, 120)}")
        if len(st.failures) > 20:
            print(f"    … 还有 {len(st.failures) - 20} 条")
    if st.tool_top:
        tops = " · ".join(f"{s.name}×{s.count}" + (f"({s.errors} err)" if s.errors else "") for s in st.tool_top[:6])
        print(f"  工具 Top: {tops}")
    if session.child_sessions:
        cf = sum(len(c.stats.failures) for c in session.child_sessions)
        print(f"  子代理: {len(session.child_sessions)} 个" + (f"（含 {cf} 个失败点）" if cf else ""))
    if session.warnings:
        for w in session.warnings:
            print(f"  ⚠ {w}")


def _fmt_time(ms: int | None) -> str:
    import datetime as _dt

    if not ms:
        return "—"
    return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _slug(session_id: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in session_id)
    return keep[-24:] if len(keep) > 24 else keep


# ---------------------------------------------------------------------------
# entry


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-xray",
        description="把编码 agent 的会话日志变成一张可交互的执行 X 光片（单个 HTML 文件）。",
    )
    p.add_argument("path", nargs="?",
                   help="Claude Code .jsonl 转录 / ZCode db.sqlite / 转录目录；缺省自动发现 ZCode db")
    p.add_argument("-l", "--list", action="store_true", help="列出可分析的会话")
    p.add_argument("-s", "--summary", action="store_true", help="在终端打印结构化摘要（含失败点）")
    p.add_argument("--session", metavar="ID", help="会话 id（支持前缀或 --list 序号）")
    p.add_argument("-o", "--out", default="./agent-xray-out", help="输出目录 (默认 ./agent-xray-out)")
    p.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    p.add_argument("--trunc", type=int, default=2000, metavar="N",
                   help="文本字段截断长度（默认 2000 字符）")
    p.add_argument("--full", action="store_true", help="不截断（HTML 可能非常大）")
    p.add_argument("--db", help="显式指定 ZCode db.sqlite 路径")
    p.add_argument("--price-file", help="自定义价格表 JSON（覆盖内置估算）")
    p.add_argument("--limit", type=int, default=50, metavar="N", help="目录批量模式最多渲染 N 个（默认 50）")
    p.add_argument("--all", action="store_true", help="db 模式下渲染全部会话（配合 --limit）")
    p.add_argument("-V", "--version", action="version", version=f"agent-xray {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prices = load_price_table(args.price_file)

    try:
        source = pick_source(args)
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    try:
        if args.list or (args.path is None and not args.summary and not args.session and not args.all):
            _print_list(source)
            return 0

        if args.summary:
            sid, _info = resolve_session_id(source, args.session)
            session = source.load(sid, 0 if args.full else args.trunc, prices)
            print_summary(session)
            return 0

        return _render(source, args, prices)
    except (ValueError, KeyError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    finally:
        source.close()


def _print_list(source: ZcodeSource | TranscriptSource) -> None:
    sessions = source.sessions()
    if not sessions:
        print("没有找到会话。")
        return
    print(f"{'#':>3}  {'会话 id':<34} {'开始时间':<17} {'时长':>7} {'轮次':>4} {'消息':>5} {'工具错':>4}  标题")
    for i, s in enumerate(sessions, 1):
        print(
            f"{i:>3}  {s['id'][:34]:<34} {_fmt_time(s.get('time_created')):<17} "
            f"{_fmt_dur(s.get('duration_ms')):>7} "
            f"{str(s.get('turn_count') if s.get('turn_count') is not None else '—'):>4} "
            f"{str(s.get('message_count') if s.get('message_count') is not None else '—'):>5} "
            f"{str(s.get('tool_error_count') if s.get('tool_error_count') is not None else '—'):>4}  "
            f"{truncate(s.get('title') or '', 60)}"
        )
    print(f"\n共 {len(sessions)} 个会话。用 --summary 查看、--session <序号或id前缀> 渲染。")


def _render(source: ZcodeSource | TranscriptSource, args, prices) -> int:
    sessions = source.sessions()
    if isinstance(source, TranscriptSource) and args.path and Path(args.path).is_file():
        targets = [(source.files[0].stem, sessions[0])]
    elif args.all:
        targets = [(s["id"], s) for s in sessions[: max(0, args.limit)]]
    else:
        sid, info = resolve_session_id(source, args.session)
        targets = [(sid, info)]

    entries = []
    outputs = []
    for sid, _info in targets:
        session = source.load(sid, 0 if args.full else args.trunc, prices)
        out = Path(args.out).expanduser() / f"{_slug(sid)}-xray.html"
        render_session(session, out)
        outputs.append(out)
        st = session.stats
        entries.append(
            {
                "path": out.name,
                "title": session.title or sid,
                "when": _fmt_time(session.created_at),
                "turns": st.turn_count,
                "calls": st.model_call_count,
                "fails": len(st.failures),
                "tokens": _fmt_tok(st.usage.total),
                "cost": f"${st.cost.total:.4f}",
            }
        )
        print(f"✓ {out}  （轮次 {st.turn_count} · 失败 {len(st.failures)} · {_fmt_tok(st.usage.total)} tokens）")

    if len(entries) > 1:
        idx = Path(args.out).expanduser() / "index.html"
        render_index(entries, idx)
        outputs.append(idx)
        print(f"✓ {idx}")

    if args.open and outputs:
        webbrowser.open(outputs[0].as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
