"""Single-file HTML renderer: data + app.js + CSS + ECharts inlined, fully offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..model import Session, to_dict

_ASSETS = Path(__file__).parent / "assets"
_MAX_DATA_BYTES = 50 * 1024 * 1024  # guardrail for the embedded JSON payload


def _load(name: str) -> str:
    return (_ASSETS / name).read_text(encoding="utf-8")


def _json_payload(data: dict[str, Any]) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # the payload lives inside <script type="application/json">; a literal
    # "</script" would terminate it early. "\/" is a valid JSON escape.
    text = text.replace("</", "<\\/")
    return text


def render_session(
    session: Session,
    out_path: str | Path,
    trunc_note: str = "",
) -> Path:
    """Render one Session into a standalone HTML file. Returns the path."""
    data = to_dict(session)
    payload = _json_payload(data)
    if len(payload.encode("utf-8")) > _MAX_DATA_BYTES:
        session.warnings.append(
            "data payload exceeded 50MB — output may be heavy; consider --trunc or --full=false"
        )
        payload = _json_payload(to_dict(session))
    html = _load_template(payload, session.title or session.id, trunc_note)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def render_index(
    entries: list[dict[str, Any]],
    out_path: str | Path,
    title: str = "Agent X-Ray — 会话索引",
) -> Path:
    """Render the batch-mode index page. entries: [{path, title, created_at, turns, cost, ...}]"""
    rows = "".join(
        "<tr onclick=\"location.href='{path}'\"><td>{title}</td><td>{when}</td>"
        "<td class=num>{turns}</td><td class=num>{calls}</td><td class=num>{fails}</td>"
        "<td class=num>{tokens}</td><td class=num>{cost}</td></tr>".format(
            path=e["path"],
            title=_esc(e.get("title") or e.get("path", "")),
            when=e.get("when", ""),
            turns=e.get("turns", ""),
            calls=e.get("calls", ""),
            fails=e.get("fails", ""),
            tokens=e.get("tokens", ""),
            cost=e.get("cost", ""),
        )
        for e in entries
    )
    html = (
        "<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
        f"<title>{_esc(title)}</title><style>"
        "body{background:#0d1117;color:#e6edf3;font:14px -apple-system,'PingFang SC',sans-serif;"
        "margin:24px}table{border-collapse:collapse;width:100%}"
        "th,td{padding:7px 10px;border-bottom:1px solid #2d333b;text-align:left;font-size:13px}"
        "th{color:#8a93a5;font-weight:500}tr:hover td{background:#1c2330;cursor:pointer}"
        ".num{text-align:right;font-family:ui-monospace,monospace}h1{font-size:18px}"
        "p{color:#8a93a5;font-size:12px}</style></head><body>"
        f"<h1>{_esc(title)}</h1><p>{len(entries)} sessions · 点击行打开对应 X 光片</p>"
        "<table><thead><tr><th>标题</th><th>开始时间</th><th class=num>轮次</th>"
        "<th class=num>调用</th><th class=num>失败</th><th class=num>tokens</th>"
        "<th class=num>成本</th></tr></thead><tbody>" + rows + "</tbody></table></body></html>"
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load_template(payload: str, title: str, trunc_note: str) -> str:
    template = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    echarts_js = _load("echarts.min.js")
    app_js = _load("app.js")
    css = _load("style.css")
    safe_title = _esc(title)
    html = (
        template.replace("__XRAY_TITLE__", safe_title)
        .replace("__XRAY_DATA__", payload)
        .replace("__XRAY_ECHARTS__", echarts_js)
        .replace("__XRAY_APP__", app_js)
        .replace("__XRAY_CSS__", css)
    )
    if trunc_note:
        html = html.replace("</header>", f"<div class='banner show'>{_esc(trunc_note)}</div></header>")
    return html
