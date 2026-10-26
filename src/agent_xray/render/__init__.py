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
:root{--bg:#08060f;--fg:#f2eefb;--fg2:#b6aecb;--fg3:#7f7797;--border:rgba(187,173,230,.13);--grad:linear-gradient(120deg,#bbade6 0%,#9d8cf0 35%,#6fb6f5 70%,#7fd8f0 100%);--mono:ui-monospace,'SFMono-Regular','Cascadia Code',Menlo,Consolas,monospace}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;min-height:100vh;color:var(--fg);font:14px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background-color:var(--bg);background-image:radial-gradient(ellipse 900px 520px at 18% -6%,rgba(120,70,220,.30),transparent 70%),radial-gradient(ellipse 820px 480px at 78% -4%,rgba(40,120,240,.20),transparent 70%),radial-gradient(ellipse 700px 420px at 52% 6%,rgba(70,210,240,.10),transparent 70%);background-repeat:no-repeat;background-attachment:fixed;-webkit-font-smoothing:antialiased}
::selection{background:rgba(187,173,230,.35);color:#fff}
.wrap{max-width:1100px;margin:0 auto;padding:52px 24px 80px}
.top{display:flex;align-items:center;gap:16px}
.top h1{font-size:24px;font-weight:650;letter-spacing:-.02em;margin:0;flex:1;min-width:0;line-height:1.3;text-wrap:balance;overflow-wrap:anywhere}
.top h1::before{content:"";display:inline-block;width:10px;height:10px;margin-right:10px;border-radius:3px;background:var(--grad);box-shadow:0 0 18px rgba(187,173,230,.65);vertical-align:1px}
.lang{display:flex;gap:2px;flex:none;padding:3px;border:1px solid var(--border);background:rgba(255,255,255,.03);border-radius:999px}
.lang button{background:transparent;border:none;color:var(--fg3);border-radius:999px;font-size:11px;padding:4px 10px;cursor:pointer;font-family:inherit;transition:color .14s,background .14s,box-shadow .14s,transform .12s}
.lang button:hover{color:var(--fg2)}
.lang button.on{color:var(--fg);background:rgba(255,255,255,.08);box-shadow:inset 0 0 0 1px rgba(187,173,230,.3),0 2px 8px rgba(0,0,0,.25)}
.lang button:active{transform:scale(.96)}
#idx-sub{color:var(--fg3);font-size:12.5px;margin:9px 0 24px}
.table-card{background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.015));border:1px solid var(--border);border-radius:16px;clip-path:inset(0 round 16px);box-shadow:0 24px 60px -30px rgba(0,0,0,.8);scrollbar-width:thin;scrollbar-color:rgba(187,173,230,.25) transparent}
.table-card::-webkit-scrollbar{height:8px}
.table-card::-webkit-scrollbar-thumb{background:rgba(187,173,230,.25);border-radius:999px}
table{border-collapse:separate;border-spacing:0;width:100%}
th,td{padding:12px 16px;text-align:left;font-size:12.5px}
th{color:var(--fg3);font-weight:600;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;background:rgba(255,255,255,.03);border-bottom:1px solid var(--border)}
td{color:var(--fg2);border-bottom:1px solid rgba(187,173,230,.07)}
tbody tr{cursor:pointer;transition:background .12s}
tbody tr:hover td{background:rgba(187,173,230,.06);color:var(--fg)}
tbody tr:last-child td{border-bottom:none}
td:first-child{color:var(--fg);max-width:560px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.num{text-align:right;font-family:var(--mono);font-size:11.5px;font-variant-numeric:tabular-nums}
@media(max-width:720px){.wrap{padding:32px 14px 60px}.top h1{font-size:19px}th,td{padding:10px 11px;white-space:nowrap}.table-card{overflow-x:auto}table{min-width:640px}td:first-child{max-width:240px}}
</style>
</head>
<body>
<div class="wrap">
<div class="top"><h1 id="idx-title">Agent X-Ray — Session Index</h1>
<div class="lang"><button data-lang="zh">中文</button><button data-lang="en">EN</button></div></div>
<p id="idx-sub"></p>
<div class="table-card">
<table><thead><tr>
<th data-i18n="colTitle">Title</th><th data-i18n="colWhen">Started</th>
<th class="num" data-i18n="colTurns">Turns</th><th class="num" data-i18n="colCalls">Calls</th>
<th class="num" data-i18n="colFails">Failures</th><th class="num" data-i18n="colTokens">Tokens</th>
<th class="num" data-i18n="colCost">Cost</th>
</tr></thead><tbody>__ROWS__</tbody></table>
</div>
</div>
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
