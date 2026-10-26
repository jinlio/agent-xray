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


_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent X-Ray — Session Index</title>
<style>
body{background:#0d1117;color:#e6edf3;font:14px -apple-system,'Segoe UI','PingFang SC',sans-serif;margin:24px}
.top{display:flex;align-items:center;gap:12px}
.top h1{font-size:18px;margin:0;flex:1;min-width:0}
.lang{display:flex;gap:2px;flex:none}
.lang button{background:#161b22;border:1px solid #2d333b;color:#8a93a5;border-radius:4px;padding:3px 9px;font-size:12px;cursor:pointer;font-family:inherit}
.lang button.on{color:#e6edf3;border-color:#4c8dff}
table{border-collapse:collapse;width:100%;margin-top:14px}
th,td{padding:7px 10px;border-bottom:1px solid #2d333b;text-align:left;font-size:13px}
th{color:#8a93a5;font-weight:500}
tr:hover td{background:#1c2330;cursor:pointer}
.num{text-align:right;font-family:ui-monospace,monospace}
p{color:#8a93a5;font-size:12px}
</style>
</head>
<body>
<div class="top"><h1 id="idx-title">Agent X-Ray — Session Index</h1>
<div class="lang"><button data-lang="zh">中文</button><button data-lang="en">EN</button></div></div>
<p id="idx-sub"></p>
<table><thead><tr>
<th data-i18n="colTitle">Title</th><th data-i18n="colWhen">Started</th>
<th class="num" data-i18n="colTurns">Turns</th><th class="num" data-i18n="colCalls">Calls</th>
<th class="num" data-i18n="colFails">Failures</th><th class="num" data-i18n="colTokens">Tokens</th>
<th class="num" data-i18n="colCost">Cost</th>
</tr></thead><tbody>__ROWS__</tbody></table>
<script>
var I18N = {
  zh: {indexTitle: "Agent X-Ray — 会话索引", indexSub: "{n} 个会话 · 点击行打开对应 X 光片",
       colTitle: "标题", colWhen: "开始时间", colTurns: "轮次", colCalls: "调用",
       colFails: "失败", colTokens: "tokens", colCost: "成本"},
  en: {indexTitle: "Agent X-Ray — Session Index", indexSub: "{n} sessions · click a row to open its X-ray",
       colTitle: "Title", colWhen: "Started", colTurns: "Turns", colCalls: "Calls",
       colFails: "Failures", colTokens: "Tokens", colCost: "Cost"}
};
var COUNT = __COUNT__;
var LANG = (function () {
  try { var s = localStorage.getItem("xray-lang"); if (s === "zh" || s === "en") return s; } catch (e) {}
  return ((navigator.language || "en").toLowerCase().indexOf("zh") === 0) ? "zh" : "en";
})();
function apply() {
  var d = I18N[LANG] || I18N.en;
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  document.title = d.indexTitle;
  document.getElementById("idx-title").textContent = d.indexTitle;
  document.getElementById("idx-sub").textContent = d.indexSub.replace("{n}", COUNT);
  document.querySelectorAll("[data-i18n]").forEach(function (n) {
    if (d[n.dataset.i18n]) n.textContent = d[n.dataset.i18n];
  });
  document.querySelectorAll(".lang button").forEach(function (b) {
    b.classList.toggle("on", b.dataset.lang === LANG);
  });
}
document.querySelectorAll(".lang button").forEach(function (b) {
  b.onclick = function () {
    LANG = b.dataset.lang;
    try { localStorage.setItem("xray-lang", LANG); } catch (e) {}
    apply();
  };
});
apply();
</script>
</body></html>
"""


def render_index(entries: list[dict[str, Any]], out_path: str | Path) -> Path:
    """Render the batch-mode index page. entries: [{path, title, when, turns, calls, fails, tokens, cost}]"""
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
    html = _INDEX_TEMPLATE.replace("__ROWS__", rows).replace("__COUNT__", str(len(entries)))
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
