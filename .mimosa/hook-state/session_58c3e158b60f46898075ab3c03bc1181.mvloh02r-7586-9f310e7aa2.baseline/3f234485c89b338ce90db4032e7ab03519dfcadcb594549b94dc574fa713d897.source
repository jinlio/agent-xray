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

var SRC_COLORS = {
  main_turn: "#4c8dff", subagent: "#a06bff", compact: "#8a93a5",
  session_title: "#6b7686", other: "#3fb6a8"
};
var CAT_COLORS = {
  bash: "#e2b93d", read: "#4ca6ff", write: "#4cd7b0", edit: "#ffa657",
  search: "#b18cff", web: "#46c2cb", agent: "#ff6ebb", todo: "#97ca72",
  skill: "#7ee787", mcp: "#ff7b72", other: "#8a93a5"
};
var FAIL_LABEL = {
  tool_error: "工具失败", model_error: "模型调用失败", retry: "重试",
  context_exceeded: "上下文超限", permission_denied: "权限拒绝",
  interrupted: "中断", long_turn: "超长轮次"
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
  return new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });
}
function fmtDate(ms) {
  if (ms == null) return "—";
  return new Date(ms).toLocaleString("zh-CN", { hour12: false });
}
function statusDot(s) { return el("span", "dot " + (s || "ok")); }

/* ---------- header ---------- */
function renderHeader() {
  var s = DATA;
  var h1 = el("h1", null, s.title || "(无标题会话)");
  var meta = el("div", "meta");
  function m(label, val) {
    var d = el("span"); var b = el("b", null, val); d.appendChild(document.createTextNode(label + " ")); d.appendChild(b); meta.appendChild(d);
  }
  m("来源", s.source);
  m("开始", fmtDate(s.created_at));
  m("时长", fmtMs(s.duration_ms));
  m("模型", (s.models || []).join(", ") || "—");
  if (s.app_version) m("版本", s.app_version);
  if (s.cwd) { var c = el("span"); c.textContent = "目录 "; var cb = el("b", null, s.cwd); c.appendChild(cb); meta.appendChild(c); }

  var chips = el("div", "chips");
  var st = s.stats || {};
  function chip(label, val, cls) { var d = el("div", "chip" + (cls ? " " + cls : "")); d.appendChild(document.createTextNode(label)); d.appendChild(el("span", "v", val)); chips.appendChild(d); }
  chip("轮次", st.turn_count);
  chip("模型调用", st.model_call_count + (st.aux_call_count ? "+" + st.aux_call_count : ""));
  chip("工具调用", st.tool_count);
  chip("错误", (st.tool_error_count || 0) + (st.failures ? "/" + st.failures.length : ""), st.failures && st.failures.length ? "bad" : "");
  chip("重试", st.retry_count || 0, st.retry_count ? "bad" : "");
  var u = st.usage || {};
  chip("Tokens", fmtTokens(u.total) + " (in " + fmtTokens(u.input) + " / out " + fmtTokens(u.output) + " / cache " + fmtTokens(u.cache_read) + ")");
  chip("成本估算", fmtCost(st.cost && st.cost.total), "money");

  var hdr = $("#hdr"); hdr.innerHTML = "";
  hdr.appendChild(h1); hdr.appendChild(meta); hdr.appendChild(chips);

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
    ["timeline", "时间轴", null],
    ["tools", "工具", st.tool_count],
    ["failures", "失败", st.failures ? st.failures.length : 0, "bad"],
    ["cost", "成本", null],
    ["children", "子代理", DATA.child_sessions ? DATA.child_sessions.length : 0],
  ];
  var nav = $("#tabs"); nav.innerHTML = "";
  tabs.forEach(function (t) {
    var b = el("button", null, t[1]);
    if (t[2] != null && t[2] !== 0) {
      var c = el("span", "count" + (t[3] ? " " + t[3] : ""), String(t[2]));
      b.appendChild(c);
    }
    if (t[0] === "children" && !(t[2] > 0)) b.style.display = "none";
    b.dataset.tab = t[0];
    if (t[0] === currentTab) b.classList.add("active");
    b.onclick = function () { switchTab(t[0]); };
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
    (call.tool_uses && call.tool_uses.length ? " · " + call.tool_uses.length + " tools" : "");
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
  [["main_turn", "主调用"], ["subagent", "子代理调用"], ["compact", "压缩"], ["session_title", "标题生成"]].forEach(function (x) {
    var s = el("span", null, x[1]); s.style.setProperty("--c", colorFor(x[0])); legend.appendChild(s);
  });
  Object.keys(CAT_COLORS).forEach(function (c) {
    var s = el("span", null, c); s.style.setProperty("--c", CAT_COLORS[c]); legend.appendChild(s);
  });
  var legend2 = el("div", "legend");
  var e1 = el("span", null, "失败(红框)"); e1.style.setProperty("--c", "transparent"); e1.style.color = "#ff9d9d"; legend2.appendChild(e1);
  var e2 = el("span", null, "重试(黄边)"); e2.style.setProperty("--c", "transparent"); e2.style.color = "#e2b93d"; legend2.appendChild(e2);
  root.appendChild(legend); root.appendChild(legend2);

  (DATA.turns || []).forEach(function (turn) { root.appendChild(turnBlock(turn)); });
  if (!(DATA.turns || []).length) root.appendChild(el("div", "empty", "没有可显示的轮次"));
}
function turnBlock(turn) {
  var box = el("div", "turn");
  box.id = "turn-" + turn.index;
  var head = el("div", "turn-head");
  var no = el("span", "turn-no", "#" + turn.index);
  head.appendChild(no);
  head.appendChild(statusDot(turn.status));
  var tt = el("div", "turn-text");
  var txt = el("div", "txt" + (turn.user_text ? "" : " dim"), turn.user_text || "(无用户输入的轮次)");
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
  calls.forEach(function (c) { (c.tool_uses || []).forEach(function (t) { toolsAll.push({ call: c, tool: t }); }); });

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
    var t = pair.tool;
    var seg = el("div", "seg t");
    seg.style.background = colorFor(null, t.category);
    if (t.status === "error") seg.classList.add("err");
    var st = t.started_at || pair.call.started_at;
    seg.title = fmtTime(st) + " · " + t.name + " · " + fmtMs(t.duration_ms) + (t.error ? " · " + t.error : "");
    placeSeg(seg, st, t.duration_ms, base, span, i, Math.max(toolsAll.length, 1));
    seg.onclick = function () { openToolDrawer(t, pair.call, turn); };
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
  var d = drawerHead("模型调用 · " + (call.model || "?"),
    "Turn #" + (turn ? turn.index : "?") + " · " + (call.id || ""));
  d.appendChild(kvGrid([
    ["时间", fmtDate(call.started_at)],
    ["耗时", fmtMs(call.duration_ms)],
    ["来源", call.query_source],
    ["agent", call.agent],
    ["attempt", call.attempt > 1 ? call.attempt + " (重试)" : "1"],
    ["finish", call.finish_reason],
    ["状态", call.status],
  ]));
  var u = call.usage || {};
  d.appendChild(kvGrid([
    ["input", fmtTokens(u.input)], ["output", fmtTokens(u.output)],
    ["reasoning", fmtTokens(u.reasoning)], ["cache read", fmtTokens(u.cache_read)],
    ["cache write", fmtTokens(u.cache_write)], ["合计", fmtTokens(u.total)],
  ]));
  if (call.cost) {
    d.appendChild(kvGrid([
      ["成本 input", fmtCost(call.cost.input)], ["成本 output", fmtCost(call.cost.output)],
      ["cache read", fmtCost(call.cost.cache_read)], ["cache write", fmtCost(call.cost.cache_write)],
      ["成本合计", fmtCost(call.cost.total)],
    ]));
  }
  if (call.error) d.appendChild(el("div", "errbox", call.error));
  var r1 = pre("思考过程 (reasoning)", call.reasoning_text); if (r1) d.appendChild(r1);
  var r2 = pre("回复文本", call.text); if (r2) d.appendChild(r2);
  (call.tool_uses || []).forEach(function (t) { d.appendChild(toolCard(t, call, turn)); });
  openDrawer();
}
function toolCard(t, call, turn) {
  var card = el("div", "toolcard");
  var head = el("div", "tc-head");
  var dot = el("span", "tag" + (t.status === "error" ? " err" : ""), t.status);
  head.appendChild(dot);
  head.appendChild(el("b", null, t.name));
  head.appendChild(el("span", "tag", t.category));
  head.appendChild(el("span", null, fmtMs(t.duration_ms)));
  if (t.exit_code != null) head.appendChild(el("span", null, "exit " + t.exit_code));
  var btn = el("button", "jump", "定位");
  btn.onclick = function (e) { e.stopPropagation(); openToolDrawer(t, call, turn); };
  head.appendChild(btn);
  card.appendChild(head);
  var body = el("pre", null, (t.input ? "> " + t.input : "") + (t.output ? "\n" + t.output : "") + (t.error ? "\n[error] " + t.error : ""));
  card.appendChild(body);
  return card;
}
function openToolDrawer(tool, call, turn) {
  var d = drawerHead("工具调用 · " + tool.name,
    "Turn #" + (turn ? turn.index : "?") + " · " + (tool.id || ""));
  d.appendChild(kvGrid([
    ["状态", tool.status], ["类别", tool.category],
    ["耗时", fmtMs(tool.duration_ms)], ["exit code", tool.exit_code],
    ["时间", fmtDate(tool.started_at)],
  ]));
  if (tool.error) d.appendChild(el("div", "errbox", tool.error));
  var pi = pre("输入 (input)", tool.input); if (pi) d.appendChild(pi);
  var po = pre("输出 (output)", tool.output); if (po) d.appendChild(po);
  if (call) {
    var btn = el("button", "jump", "查看所属模型调用");
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
      (call.tool_uses || []).forEach(function (t) {
        if (t.name === name) out.push({ turn: turn, call: call, tool: t });
      });
    });
  });
  return out;
}
function renderTools() {
  var root = $("#tool-table"); root.innerHTML = "";
  var st = DATA.stats || {};
  var top = st.tool_top || [];
  if (!top.length) { root.appendChild(el("div", "empty", "本会话没有工具调用")); return; }
  var table = el("table", "grid");
  table.innerHTML = "<thead><tr><th>类别</th><th>工具</th><th class=num>次数</th><th class=num>错误</th><th class=num>总耗时</th><th class=num>平均</th></tr></thead>";
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
        var t = $("#turn-" + o.turn.index);
        if (t) t.scrollIntoView({ behavior: "smooth", block: "center" });
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
  if (!fails.length) { root.appendChild(el("div", "empty", "✔ 未发现失败点")); return; }
  fails.forEach(function (f) {
    var d = el("div", "fail");
    d.appendChild(el("span", "k", FAIL_LABEL[f.kind] || f.kind));
    d.appendChild(el("span", "m", f.message));
    d.appendChild(el("span", "t", "turn #" + f.turn_index + " · " + fmtTime(f.at)));
    d.onclick = function () {
      switchTab("timeline");
      setTimeout(function () {
        var t = $("#turn-" + f.turn_index);
        if (t) t.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 60);
    };
    root.appendChild(d);
  });
}

/* ---------- cost view ---------- */
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
  if (!window.echarts) { dom.textContent = "ECharts 未加载，无法绘制图表"; return; }
  var chart = window.echarts.init(dom, "dark");
  var times = pts.map(function (p) { return +p.t.toFixed(2); });
  var t0 = DATA.created_at;
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      formatter: function (params) {
        var i = params[0].dataIndex; var p = pts[i];
        return "turn #" + p.turn + "<br>" + fmtDate(t0 != null ? t0 + p.t * 60000 : null) +
          "<br>累计成本 " + fmtCost(p.cum) + "<br>累计输出 " + fmtTokens(p.tok) +
          (p.call ? "<br>" + p.call.model + " · " + fmtMs(p.call.duration_ms) : "");
      }
    },
    legend: { data: ["累计成本 ($)", "累计输出 tokens"] },
    grid: { left: 60, right: 60, top: 40, bottom: 40 },
    xAxis: { type: "category", data: times, name: "分钟" },
    yAxis: [
      { type: "value", name: "$", axisLabel: { formatter: function (v) { return "$" + v; } } },
      { type: "value", name: "tokens", axisLabel: { formatter: fmtTokens } }
    ],
    series: [
      { name: "累计成本 ($)", type: "line", data: pts.map(function (p) { return +p.cum.toFixed(4); }),
        showSymbol: false, lineStyle: { color: "#4cd7b0", width: 2 }, itemStyle: { color: "#4cd7b0" },
        markPoint: { data: [{ type: "max", name: "峰值" }] } },
      { name: "累计输出 tokens", type: "line", yAxisIndex: 1, data: pts.map(function (p) { return p.tok; }),
        showSymbol: false, lineStyle: { color: "#4c8dff", width: 1.5, type: "dashed" }, itemStyle: { color: "#4c8dff" } }
    ]
  });
  window.addEventListener("resize", function () { chart.resize(); });

  var st = DATA.stats || {};
  var t = $("#cost-table"); t.innerHTML = "";
  var tbl = el("table", "grid cost-table");
  tbl.innerHTML = "<thead><tr><th>模型</th></tr></thead>";
  var byModel = {};
  (DATA.turns || []).forEach(function (turn) {
    (turn.model_calls || []).forEach(function (c) {
      var m = byModel[c.model || "?"] = byModel[c.model || "?"] || { calls: 0, tokens: 0, cost: 0 };
      m.calls++; m.tokens += (c.usage && c.usage.total) || 0; m.cost += (c.cost && c.cost.total) || 0;
    });
  });
  var thead = tbl.querySelector("thead tr");
  ["调用数", "tokens", "成本估算"].forEach(function (h) { thead.appendChild(el("th", "num", h)); });
  Object.keys(byModel).forEach(function (name) {
    var m = byModel[name]; var tr = el("tr");
    tr.appendChild(el("td", null, name));
    tr.appendChild(el("td", "num", String(m.calls)));
    tr.appendChild(el("td", "num", fmtTokens(m.tokens)));
    tr.appendChild(el("td", "num", fmtCost(m.cost)));
    tbl.appendChild(tr);
  });
  t.appendChild(tbl);
}

/* ---------- children view ---------- */
function renderChildren() {
  var root = $("#child-list"); root.innerHTML = "";
  var kids = DATA.child_sessions || [];
  if (!kids.length) { root.appendChild(el("div", "empty", "本会话没有子代理")); return; }
  kids.forEach(function (k) {
    var card = el("div", "child-card");
    var st = k.stats || {};
    card.appendChild(el("h4", null, k.title || k.id));
    var meta = el("div", "meta");
    meta.textContent = "轮次 " + (st.turn_count || 0) + " · 调用 " + (st.model_call_count || 0) +
      " · 工具 " + (st.tool_count || 0) + " · 错误 " + ((st.failures || []).length) +
      " · tokens " + fmtTokens(st.usage && st.usage.total) + " · " + fmtMs(k.duration_ms) +
      " · " + (k.models || []).join(",");
    card.appendChild(meta);
    var fails = (st.failures || []).slice(0, 5);
    fails.forEach(function (f) {
      card.appendChild(el("div", "errbox", (FAIL_LABEL[f.kind] || f.kind) + " · turn #" + f.turn_index + " · " + f.message));
    });
    root.appendChild(card);
  });
}

/* ---------- boot ---------- */
renderHeader();
renderTabs();
renderTimeline();
renderTools();
renderFailures();
renderChildren();
document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });
