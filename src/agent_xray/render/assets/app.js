/* Agent X-Ray viewer — vanilla JS, no build step. Data is embedded as JSON. */
"use strict";

var DATA = JSON.parse(document.getElementById("xray-data").textContent);
var $ = function (sel, el) { return (el || document).querySelector(sel); };
function el(tag, cls, text) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function esc(s) { return String(s == null ? "" : s); }

/* ---------- i18n ---------- */
var I18N = {
  zh: {
    untitled: "(无标题会话)",
    source: "来源", started: "开始", duration: "时长", model: "模型", version: "版本", cwd: "目录",
    turns: "轮次", modelCalls: "模型调用", toolCalls: "工具调用", errors: "错误", retries: "重试",
    estCost: "成本估算",
    tabTimeline: "时间轴", tabTools: "工具", tabFailures: "失败", tabCost: "成本", tabChildren: "子代理",
    legendMain: "主调用", legendSub: "子代理调用", legendCompact: "压缩", legendTitle: "标题生成",
    legendFail: "失败(红框)", legendRetry: "重试(黄边)",
    noTurns: "没有可显示的轮次", noUserInput: "(无用户输入的轮次)",
    modelCall: "模型调用", toolCall: "工具调用",
    time: "时间", durationK: "耗时", sourceK: "来源", status: "状态", total: "合计",
    costInput: "成本 input", costOutput: "成本 output", costTotal: "成本合计",
    reasoning: "思考过程 (reasoning)", responseText: "回复文本",
    locate: "定位", viewParentCall: "查看所属模型调用",
    input: "输入 (input)", output: "输出 (output)",
    category: "类别", tool: "工具", count: "次数", totalTime: "总耗时", avg: "平均",
    noToolCalls: "本会话没有工具调用", noFailures: "✔ 未发现失败点",
    echartsMissing: "ECharts 未加载，无法绘制图表",
    cumCost: "累计成本 ($)", cumOutput: "累计输出 tokens", minutes: "分钟", peak: "峰值",
    calls: "调用数", estCostShort: "成本估算", modelCol: "模型",
    noChildren: "本会话没有子代理",
    turnsShort: "轮次", callsShort: "调用", toolsShort: "工具", errorsShort: "错误",
    fail_tool_error: "工具失败", fail_model_error: "模型调用失败", fail_retry: "重试",
    fail_context_exceeded: "上下文超限", fail_permission_denied: "权限拒绝",
    fail_interrupted: "中断", fail_long_turn: "超长轮次"
  },
  en: {
    untitled: "(untitled session)",
    source: "source", started: "started", duration: "duration", model: "model", version: "version",
    cwd: "cwd",
    turns: "turns", modelCalls: "model calls", toolCalls: "tool calls", errors: "errors",
    retries: "retries", estCost: "est. cost",
    tabTimeline: "Timeline", tabTools: "Tools", tabFailures: "Failures", tabCost: "Cost",
    tabChildren: "Subagents",
    legendMain: "main call", legendSub: "subagent call", legendCompact: "compaction",
    legendTitle: "title gen", legendFail: "failure (red)", legendRetry: "retry (yellow)",
    noTurns: "No turns to display", noUserInput: "(turn without user input)",
    modelCall: "Model call", toolCall: "Tool call",
    time: "time", durationK: "duration", sourceK: "source", status: "status", total: "total",
    costInput: "cost input", costOutput: "cost output", costTotal: "total cost",
    reasoning: "Reasoning", responseText: "Response text",
    locate: "Locate", viewParentCall: "View parent model call",
    input: "Input", output: "Output",
    category: "category", tool: "tool", count: "count", totalTime: "total time", avg: "avg",
    noToolCalls: "No tool calls in this session", noFailures: "✔ No failures found",
    echartsMissing: "ECharts not loaded — cannot draw chart",
    cumCost: "cumulative cost ($)", cumOutput: "cumulative output tokens", minutes: "minutes",
    peak: "peak",
    calls: "calls", estCostShort: "est. cost", modelCol: "model",
    noChildren: "No subagents in this session",
    turnsShort: "turns", callsShort: "calls", toolsShort: "tools", errorsShort: "errors",
    fail_tool_error: "tool error", fail_model_error: "model error", fail_retry: "retry",
    fail_context_exceeded: "context exceeded", fail_permission_denied: "permission denied",
    fail_interrupted: "interrupted", fail_long_turn: "long turn"
  }
};

var LANG = (function () {
  try {
    var saved = localStorage.getItem("xray-lang");
    if (saved === "zh" || saved === "en") return saved;
  } catch (e) {}
  return ((navigator.language || "en").toLowerCase().indexOf("zh") === 0) ? "zh" : "en";
})();

function t(key) {
  var d = I18N[LANG] || I18N.en;
  if (d[key] !== undefined) return d[key];
  return I18N.en[key] !== undefined ? I18N.en[key] : key;
}
function failLabel(kind) {
  var key = "fail_" + kind;
  return (I18N[LANG] && I18N[LANG][key]) || (I18N.en && I18N.en[key]) || kind;
}
function locale() { return LANG === "zh" ? "zh-CN" : "en-US"; }
function setLang(lang) {
  LANG = lang;
  try { localStorage.setItem("xray-lang", lang); } catch (e) {}
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  renderAll();
}

var SRC_COLORS = {
  main_turn: "#4c8dff", subagent: "#a06bff", compact: "#8a93a5",
  session_title: "#6b7686", other: "#3fb6a8"
};
var CAT_COLORS = {
  bash: "#e2b93d", read: "#4ca6ff", write: "#4cd7b0", edit: "#ffa657",
  search: "#b18cff", web: "#46c2cb", agent: "#ff6ebb", todo: "#97ca72",
  skill: "#7ee787", mcp: "#ff7b72", other: "#8a93a5"
};

function colorFor(source, cat) { return cat ? (CAT_COLORS[cat] || CAT_COLORS.other) : (SRC_COLORS[source] || SRC_COLORS.other); }
function fmtMs(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return ms + "ms";
  if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + "s";
  var m = Math.floor(ms / 60000), s = Math.round((ms % 60000) / 1000);
  return m + "m" + (s < 10 ? "0" : "") + s + "s";
}
function fmtTokens(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}
function fmtCost(c) {
  if (c == null) return "—";
  if (c >= 1) return "$" + c.toFixed(2);
  if (c >= 0.01) return "$" + c.toFixed(3);
  if (c > 0) return "$" + c.toFixed(4);
  return "$0";
}
function fmtTime(ms) {
  if (ms == null) return "—";
  return new Date(ms).toLocaleTimeString(locale(), { hour12: false });
}
function fmtDate(ms) {
  if (ms == null) return "—";
  return new Date(ms).toLocaleString(locale(), { hour12: false });
}
function statusDot(s) { return el("span", "dot " + (s || "ok")); }

/* ---------- header ---------- */
function langSwitch() {
  var wrap = el("div", "lang");
  [["zh", "中文"], ["en", "EN"]].forEach(function (x) {
    var b = el("button", LANG === x[0] ? "on" : null, x[1]);
    b.title = x[0] === "zh" ? "Switch to Chinese" : "Switch to English";
    b.onclick = function () { if (LANG !== x[0]) setLang(x[0]); };
    wrap.appendChild(b);
  });
  return wrap;
}
function renderHeader() {
  var s = DATA;
  var h1 = el("h1", null, s.title || t("untitled"));
  var top = el("div", "hdr-top");
  top.appendChild(h1);
  top.appendChild(langSwitch());
  var meta = el("div", "meta");
  function m(label, val) {
    var d = el("span"); var b = el("b", null, val); d.appendChild(document.createTextNode(label + " ")); d.appendChild(b); meta.appendChild(d);
  }
  m(t("source"), s.source);
  m(t("started"), fmtDate(s.created_at));
  m(t("duration"), fmtMs(s.duration_ms));
  m(t("model"), (s.models || []).join(", ") || "—");
  if (s.app_version) m(t("version"), s.app_version);
  if (s.cwd) { var c = el("span"); c.textContent = t("cwd") + " "; var cb = el("b", null, s.cwd); c.appendChild(cb); meta.appendChild(c); }

  var chips = el("div", "chips");
  var st = s.stats || {};
  function chip(label, val, cls) { var d = el("div", "chip" + (cls ? " " + cls : "")); d.appendChild(document.createTextNode(label)); d.appendChild(el("span", "v", val)); chips.appendChild(d); }
  chip(t("turns"), st.turn_count);
  chip(t("modelCalls"), st.model_call_count + (st.aux_call_count ? "+" + st.aux_call_count : ""));
  chip(t("toolCalls"), st.tool_count);
  chip(t("errors"), (st.tool_error_count || 0) + (st.failures ? "/" + st.failures.length : ""), st.failures && st.failures.length ? "bad" : "");
  chip(t("retries"), st.retry_count || 0, st.retry_count ? "bad" : "");
  var u = st.usage || {};
  chip("Tokens", fmtTokens(u.total) + " (in " + fmtTokens(u.input) + " / out " + fmtTokens(u.output) + " / cache " + fmtTokens(u.cache_read) + ")");
  chip(t("estCost"), fmtCost(st.cost && st.cost.total), "money");

  var hdr = $("#hdr"); hdr.innerHTML = "";
  hdr.appendChild(top); hdr.appendChild(meta); hdr.appendChild(chips);

  var banner = $("#banner");
  var warns = s.warnings || [];
  if (warns.length) {
    banner.textContent = "⚠ " + warns.join(" · ");
    banner.classList.add("show");
  }
}

/* ---------- tabs ---------- */
var currentTab = "timeline";
function renderTabs() {
  var st = DATA.stats || {};
  var tabs = [
    ["timeline", t("tabTimeline"), null],
    ["tools", t("tabTools"), st.tool_count],
    ["failures", t("tabFailures"), st.failures ? st.failures.length : 0, "bad"],
    ["cost", t("tabCost"), null],
    ["children", t("tabChildren"), DATA.child_sessions ? DATA.child_sessions.length : 0],
  ];
  var nav = $("#tabs"); nav.innerHTML = "";
  tabs.forEach(function (t2) {
    var b = el("button", null, t2[1]);
    if (t2[2] != null && t2[2] !== 0) {
      var c = el("span", "count" + (t2[3] ? " " + t2[3] : ""), String(t2[2]));
      b.appendChild(c);
    }
    if (t2[0] === "children" && !(t2[2] > 0)) b.style.display = "none";
    b.dataset.tab = t2[0];
    if (t2[0] === currentTab) b.classList.add("active");
    b.onclick = function () { switchTab(t2[0]); };
    nav.appendChild(b);
  });
}
function switchTab(name) {
  currentTab = name;
  document.querySelectorAll("#tabs button").forEach(function (b) { b.classList.toggle("active", b.dataset.tab === name); });
  ["timeline", "tools", "failures", "cost", "children"].forEach(function (v) {
    var sec = $("#view-" + v); if (sec) sec.hidden = v !== name;
  });
  if (name === "cost") drawCostChart();
}

/* ---------- timeline ---------- */
function segTitle(call) {
  return fmtTime(call.started_at) + " · " + (call.model || "?") + " · " + fmtMs(call.duration_ms) +
    (call.query_source && call.query_source !== "main_turn" ? " · " + call.query_source : "") +
    (call.attempt > 1 ? " · attempt " + call.attempt : "") +
    (call.tool_uses && call.tool_uses.length ? " · " + call.tool_uses.length + " " + t("toolsShort") : "");
}
function placeSeg(seg, start, dur, base, span, sequentialIdx, total) {
  if (base && span && start != null) {
    var left = Math.max(0, (start - base) / span * 100);
    var w = Math.max(0.8, Math.min(100 - left, (dur || span * 0.01) / span * 100));
    seg.style.left = left + "%";
    seg.style.width = w + "%";
  } else {
    var step = 100 / Math.max(1, total);
    seg.style.left = (sequentialIdx * step) + "%";
    seg.style.width = "calc(" + step + "% - 2px)";
  }
}
function renderTimeline() {
  var root = $("#turn-list"); root.innerHTML = "";
  var legend = el("div", "legend");
  [["main_turn", t("legendMain")], ["subagent", t("legendSub")], ["compact", t("legendCompact")], ["session_title", t("legendTitle")]].forEach(function (x) {
    var s = el("span", null, x[1]); s.style.setProperty("--c", colorFor(x[0])); legend.appendChild(s);
  });
  Object.keys(CAT_COLORS).forEach(function (c) {
    var s = el("span", null, c); s.style.setProperty("--c", CAT_COLORS[c]); legend.appendChild(s);
  });
  var legend2 = el("div", "legend");
  var e1 = el("span", null, t("legendFail")); e1.style.setProperty("--c", "transparent"); e1.style.color = "#ff9d9d"; legend2.appendChild(e1);
  var e2 = el("span", null, t("legendRetry")); e2.style.setProperty("--c", "transparent"); e2.style.color = "#e2b93d"; legend2.appendChild(e2);
  root.appendChild(legend); root.appendChild(legend2);

  (DATA.turns || []).forEach(function (turn) { root.appendChild(turnBlock(turn)); });
  if (!(DATA.turns || []).length) root.appendChild(el("div", "empty", t("noTurns")));
}
function turnBlock(turn) {
  var box = el("div", "turn");
  box.id = "turn-" + turn.index;
  var head = el("div", "turn-head");
  var no = el("span", "turn-no", "#" + turn.index);
  head.appendChild(no);
  head.appendChild(statusDot(turn.status));
  var tt = el("div", "turn-text");
  var txt = el("div", "txt" + (turn.user_text ? "" : " dim"), turn.user_text || t("noUserInput"));
  txt.onclick = function () { txt.classList.toggle("open"); };
  tt.appendChild(txt);
  head.appendChild(tt);
  head.appendChild(el("span", "turn-dur", fmtMs(turn.duration_ms)));
  box.appendChild(head);

  var wrap = el("div", "lane-wrap");
  var lane = el("div", "lane");
  var base = turn.started_at, span = turn.duration_ms;
  var calls = turn.model_calls || [];
  var total = calls.length;
  var toolsAll = [];
  calls.forEach(function (c) { (c.tool_uses || []).forEach(function (t2) { toolsAll.push({ call: c, tool: t2 }); }); });

  var r1 = el("div", "lane-row"); r1.appendChild(el("span", "row-label", "call"));
  var r2 = el("div", "lane-row r2"); r2.appendChild(el("span", "row-label", "tool"));
  lane.appendChild(r1); lane.appendChild(r2);

  var seqIdx = 0;
  calls.forEach(function (call) {
    var seg = el("div", "seg");
    seg.style.background = colorFor(call.query_source);
    if (call.error || call.status === "error" || call.finish_reason === "failed") seg.classList.add("err");
    if (call.attempt > 1) seg.classList.add("retry");
    seg.title = segTitle(call);
    placeSeg(seg, call.started_at, call.duration_ms, base, span, seqIdx, Math.max(total, 1));
    seqIdx++;
    seg.onclick = function () { openCallDrawer(call, turn); };
    r1.appendChild(seg);
  });
  toolsAll.forEach(function (pair, i) {
    var t2 = pair.tool;
    var seg = el("div", "seg t");
    seg.style.background = colorFor(null, t2.category);
    if (t2.status === "error") seg.classList.add("err");
    var st = t2.started_at || pair.call.started_at;
    seg.title = fmtTime(st) + " · " + t2.name + " · " + fmtMs(t2.duration_ms) + (t2.error ? " · " + t2.error : "");
    placeSeg(seg, st, t2.duration_ms, base, span, i, Math.max(toolsAll.length, 1));
    seg.onclick = function () { openToolDrawer(t2, pair.call, turn); };
    r2.appendChild(seg);
  });
  (turn.annotations || []).forEach(function (a) {
    var d = el("div", "ann" + (a.kind === "compaction" ? " compaction" : ""));
    d.title = a.kind + ": " + a.message;
    if (base && span && a.at != null) d.style.left = Math.min(99, Math.max(0, (a.at - base) / span * 100)) + "%";
    lane.appendChild(d);
  });
  wrap.appendChild(lane);
  var axis = el("div", "lane-axis");
  axis.appendChild(el("span", null, fmtTime(base)));
  axis.appendChild(el("span", null, fmtMs(span)));
  axis.appendChild(el("span", null, fmtTime(base != null && span != null ? base + span : null)));
  wrap.appendChild(axis);
  box.appendChild(wrap);
  return box;
}

/* ---------- drawer ---------- */
function openDrawer() { $("#drawer").classList.add("open"); }
function closeDrawer() { $("#drawer").classList.remove("open"); }
function drawerHead(title, sub) {
  var d = $("#drawer");
  d.innerHTML = "";
  var close = el("button", "close", "×"); close.onclick = closeDrawer; d.appendChild(close);
  d.appendChild(el("h3", null, title));
  if (sub) d.appendChild(el("div", "sub", sub));
  return d;
}
function kvGrid(pairs) {
  var g = el("div", "kv");
  pairs.forEach(function (p) {
    if (p[1] === undefined || p[1] === null || p[1] === "") return;
    g.appendChild(el("div", "k", p[0]));
    g.appendChild(el("div", "v", esc(p[1])));
  });
  return g;
}
function pre(title, body) {
  if (!body) return null;
  var det = el("details");
  det.appendChild(el("summary", null, title));
  det.appendChild(el("pre", null, body));
  return det;
}
function openCallDrawer(call, turn) {
  var d = drawerHead(t("modelCall") + " · " + (call.model || "?"),
    "Turn #" + (turn ? turn.index : "?") + " · " + (call.id || ""));
  d.appendChild(kvGrid([
    [t("time"), fmtDate(call.started_at)],
    [t("durationK"), fmtMs(call.duration_ms)],
    [t("sourceK"), call.query_source],
    ["agent", call.agent],
    ["attempt", call.attempt > 1 ? call.attempt + " (" + t("retries") + ")" : "1"],
    ["finish", call.finish_reason],
    [t("status"), call.status],
  ]));
  var u = call.usage || {};
  d.appendChild(kvGrid([
    ["input", fmtTokens(u.input)], ["output", fmtTokens(u.output)],
    ["reasoning", fmtTokens(u.reasoning)], ["cache read", fmtTokens(u.cache_read)],
    ["cache write", fmtTokens(u.cache_write)], [t("total"), fmtTokens(u.total)],
  ]));
  if (call.cost) {
    d.appendChild(kvGrid([
      [t("costInput"), fmtCost(call.cost.input)], [t("costOutput"), fmtCost(call.cost.output)],
      ["cache read", fmtCost(call.cost.cache_read)], ["cache write", fmtCost(call.cost.cache_write)],
      [t("costTotal"), fmtCost(call.cost.total)],
    ]));
  }
  if (call.error) d.appendChild(el("div", "errbox", call.error));
  var r1 = pre(t("reasoning"), call.reasoning_text); if (r1) d.appendChild(r1);
  var r2 = pre(t("responseText"), call.text); if (r2) d.appendChild(r2);
  (call.tool_uses || []).forEach(function (t2) { d.appendChild(toolCard(t2, call, turn)); });
  openDrawer();
}
function toolCard(t2, call, turn) {
  var card = el("div", "toolcard");
  var head = el("div", "tc-head");
  var dot = el("span", "tag" + (t2.status === "error" ? " err" : ""), t2.status);
  head.appendChild(dot);
  head.appendChild(el("b", null, t2.name));
  head.appendChild(el("span", "tag", t2.category));
  head.appendChild(el("span", null, fmtMs(t2.duration_ms)));
  if (t2.exit_code != null) head.appendChild(el("span", null, "exit " + t2.exit_code));
  var btn = el("button", "jump", t("locate"));
  btn.onclick = function (e) { e.stopPropagation(); openToolDrawer(t2, call, turn); };
  head.appendChild(btn);
  card.appendChild(head);
  var body = el("pre", null, (t2.input ? "> " + t2.input : "") + (t2.output ? "\n" + t2.output : "") + (t2.error ? "\n[error] " + t2.error : ""));
  card.appendChild(body);
  return card;
}
function openToolDrawer(tool, call, turn) {
  var d = drawerHead(t("toolCall") + " · " + tool.name,
    "Turn #" + (turn ? turn.index : "?") + " · " + (tool.id || ""));
  d.appendChild(kvGrid([
    [t("status"), tool.status], [t("category"), tool.category],
    [t("durationK"), fmtMs(tool.duration_ms)], ["exit code", tool.exit_code],
    [t("time"), fmtDate(tool.started_at)],
  ]));
  if (tool.error) d.appendChild(el("div", "errbox", tool.error));
  var pi = pre(t("input"), tool.input); if (pi) d.appendChild(pi);
  var po = pre(t("output"), tool.output); if (po) d.appendChild(po);
  if (call) {
    var btn = el("button", "jump", t("viewParentCall"));
    btn.onclick = function () { openCallDrawer(call, turn); };
    d.appendChild(btn);
  }
  openDrawer();
}

/* ---------- tools view ---------- */
function toolOccurrences(name) {
  var out = [];
  (DATA.turns || []).forEach(function (turn) {
    (turn.model_calls || []).forEach(function (call) {
      (call.tool_uses || []).forEach(function (t2) {
        if (t2.name === name) out.push({ turn: turn, call: call, tool: t2 });
      });
    });
  });
  return out;
}
function renderTools() {
  var root = $("#tool-table"); root.innerHTML = "";
  var st = DATA.stats || {};
  var top = st.tool_top || [];
  if (!top.length) { root.appendChild(el("div", "empty", t("noToolCalls"))); return; }
  var table = el("table", "grid");
  table.innerHTML = "<thead><tr><th>" + t("category") + "</th><th>" + t("tool") + "</th><th class=num>" + t("count") +
    "</th><th class=num>" + t("errors") + "</th><th class=num>" + t("totalTime") + "</th><th class=num>" + t("avg") + "</th></tr></thead>";
  var tbody = el("tbody");
  top.forEach(function (s) {
    var tr = el("tr", "occ-row");
    tr.appendChild(el("td", null, "")).appendChild(el("span", "tag", s.category));
    tr.appendChild(el("td", null, s.name));
    tr.appendChild(el("td", "num", String(s.count)));
    var etd = el("td", "num", String(s.errors)); if (s.errors) etd.style.color = "var(--red)";
    tr.appendChild(etd);
    tr.appendChild(el("td", "num", fmtMs(s.total_ms)));
    tr.appendChild(el("td", "num", fmtMs(s.count ? Math.round(s.total_ms / s.count) : null)));
    tr.onclick = function () { toggleOccurrences(tr, s.name); };
    tbody.appendChild(tr);
  });
  table.appendChild(tbody); root.appendChild(table);
}
function toggleOccurrences(tr, name) {
  var next = tr.nextSibling;
  if (next && next.classList && next.classList.contains("occ-detail")) { next.remove(); return; }
  var det = el("tr", "occ-detail"); var td = el("td"); td.colSpan = 6;
  toolOccurrences(name).slice(0, 50).forEach(function (o) {
    var line = el("tr", "occ-row");
    line.appendChild(el("td", null, ""));
    var c = el("td", null, "");
    c.appendChild(el("span", "tag" + (o.tool.status === "error" ? " err" : ""), "turn #" + o.turn.index));
    c.appendChild(document.createTextNode(" " + fmtTime(o.tool.started_at) + " · " + fmtMs(o.tool.duration_ms) + (o.tool.error ? " · " + o.tool.error : "")));
    line.appendChild(c);
    line.appendChild(el("td", null, ""));
    line.onclick = function () {
      switchTab("timeline");
      setTimeout(function () {
        var t2 = $("#turn-" + o.turn.index);
        if (t2) t2.scrollIntoView({ behavior: "smooth", block: "center" });
        openToolDrawer(o.tool, o.call, o.turn);
      }, 60);
    };
    td.appendChild(line);
  });
  det.appendChild(td);
  tr.parentNode.insertBefore(det, next);
}

/* ---------- failures view ---------- */
function renderFailures() {
  var root = $("#fail-list"); root.innerHTML = "";
  var fails = (DATA.stats && DATA.stats.failures) || [];
  if (!fails.length) { root.appendChild(el("div", "empty", t("noFailures"))); return; }
  fails.forEach(function (f) {
    var d = el("div", "fail");
    d.appendChild(el("span", "k", failLabel(f.kind)));
    d.appendChild(el("span", "m", f.message));
    d.appendChild(el("span", "t", "turn #" + f.turn_index + " · " + fmtTime(f.at)));
    d.onclick = function () {
      switchTab("timeline");
      setTimeout(function () {
        var t2 = $("#turn-" + f.turn_index);
        if (t2) t2.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 60);
    };
    root.appendChild(d);
  });
}

/* ---------- cost view ---------- */
var costChart = null;
function costSeries() {
  var pts = []; var cum = 0; var cumTok = 0; var t0 = DATA.created_at;
  (DATA.turns || []).forEach(function (turn, ti) {
    var turnCost = 0;
    (turn.model_calls || []).forEach(function (c) {
      if (c.cost) cum += c.cost.total || 0;
      turnCost += (c.cost && c.cost.total) || 0;
      cumTok += (c.usage && c.usage.output) || 0;
      if (c.started_at != null && t0 != null) {
        pts.push({ t: (c.started_at - t0) / 60000, cum: cum, tok: cumTok, turn: ti, spike: turnCost, call: c });
      }
    });
  });
  return pts;
}
function drawCostChart() {
  var dom = $("#cost-chart");
  var pts = costSeries();
  if (!window.echarts) { dom.textContent = t("echartsMissing"); return; }
  if (costChart) { costChart.dispose(); costChart = null; }
  var chart = window.echarts.init(dom, "dark");
  costChart = chart;
  var times = pts.map(function (p) { return +p.t.toFixed(2); });
  var t0 = DATA.created_at;
  var cumLabel = t("cumCost"), outLabel = t("cumOutput");
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      formatter: function (params) {
        var i = params[0].dataIndex; var p = pts[i];
        return "turn #" + p.turn + "<br>" + fmtDate(t0 != null ? t0 + p.t * 60000 : null) +
          "<br>" + cumLabel + " " + fmtCost(p.cum) + "<br>" + outLabel + " " + fmtTokens(p.tok) +
          (p.call ? "<br>" + p.call.model + " · " + fmtMs(p.call.duration_ms) : "");
      }
    },
    legend: { data: [cumLabel, outLabel] },
    grid: { left: 60, right: 60, top: 40, bottom: 40 },
    xAxis: { type: "category", data: times, name: t("minutes") },
    yAxis: [
      { type: "value", name: "$", axisLabel: { formatter: function (v) { return "$" + v; } } },
      { type: "value", name: "tokens", axisLabel: { formatter: fmtTokens } }
    ],
    series: [
      { name: cumLabel, type: "line", data: pts.map(function (p) { return +p.cum.toFixed(4); }),
        showSymbol: false, lineStyle: { color: "#4cd7b0", width: 2 }, itemStyle: { color: "#4cd7b0" },
        markPoint: { data: [{ type: "max", name: t("peak") }] } },
      { name: outLabel, type: "line", yAxisIndex: 1, data: pts.map(function (p) { return p.tok; }),
        showSymbol: false, lineStyle: { color: "#4c8dff", width: 1.5, type: "dashed" }, itemStyle: { color: "#4c8dff" } }
    ]
  });

  var tbl = el("table", "grid cost-table");
  tbl.innerHTML = "<thead><tr><th>" + t("modelCol") + "</th></tr></thead>";
  var byModel = {};
  (DATA.turns || []).forEach(function (turn) {
    (turn.model_calls || []).forEach(function (c) {
      var m = byModel[c.model || "?"] = byModel[c.model || "?"] || { calls: 0, tokens: 0, cost: 0 };
      m.calls++; m.tokens += (c.usage && c.usage.total) || 0; m.cost += (c.cost && c.cost.total) || 0;
    });
  });
  var thead = tbl.querySelector("thead tr");
  [t("calls"), "tokens", t("estCostShort")].forEach(function (h) { thead.appendChild(el("th", "num", h)); });
  Object.keys(byModel).forEach(function (name) {
    var m = byModel[name]; var tr = el("tr");
    tr.appendChild(el("td", null, name));
    tr.appendChild(el("td", "num", String(m.calls)));
    tr.appendChild(el("td", "num", fmtTokens(m.tokens)));
    tr.appendChild(el("td", "num", fmtCost(m.cost)));
    tbl.appendChild(tr);
  });
  var holder = $("#cost-table"); holder.innerHTML = "";
  holder.appendChild(tbl);
}

/* ---------- children view ---------- */
function renderChildren() {
  var root = $("#child-list"); root.innerHTML = "";
  var kids = DATA.child_sessions || [];
  if (!kids.length) { root.appendChild(el("div", "empty", t("noChildren"))); return; }
  kids.forEach(function (k) {
    var card = el("div", "child-card");
    var st = k.stats || {};
    card.appendChild(el("h4", null, k.title || k.id));
    var meta = el("div", "meta");
    meta.textContent = t("turnsShort") + " " + (st.turn_count || 0) + " · " + t("callsShort") + " " + (st.model_call_count || 0) +
      " · " + t("toolsShort") + " " + (st.tool_count || 0) + " · " + t("errorsShort") + " " + ((st.failures || []).length) +
      " · tokens " + fmtTokens(st.usage && st.usage.total) + " · " + fmtMs(k.duration_ms) +
      " · " + (k.models || []).join(",");
    card.appendChild(meta);
    var fails = (st.failures || []).slice(0, 5);
    fails.forEach(function (f) {
      card.appendChild(el("div", "errbox", failLabel(f.kind) + " · turn #" + f.turn_index + " · " + f.message));
    });
    root.appendChild(card);
  });
}

/* ---------- boot ---------- */
function renderAll() {
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  renderHeader();
  renderTabs();
  renderTimeline();
  renderTools();
  renderFailures();
  renderChildren();
  closeDrawer();
  if (currentTab === "cost") drawCostChart();
}
renderAll();
document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });
window.addEventListener("resize", function () { if (costChart) costChart.resize(); });
