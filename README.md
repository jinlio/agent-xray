# Agent X-Ray 🔬

[![CI](https://github.com/jinlio/agent-xray/actions/workflows/ci.yml/badge.svg)](https://github.com/jinlio/agent-xray/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentxray-replay)](https://pypi.org/project/agentxray-replay/)
[![Python](https://img.shields.io/pypi/pyversions/agentxray-replay)](https://pypi.org/project/agentxray-replay/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**English** | [简体中文](https://github.com/jinlio/agent-xray/blob/main/README.zh-CN.md)

**Zero-instrumentation, fully local session replay for coding agents** — turn Claude Code / Codex / ZCode session logs into an interactive **execution X-ray**: a timeline, tool-call tree, token/cost curves and highlighted failures. The output is a **single HTML file** you can double-click, drop into a PR, or email to someone.

![Agent X-Ray demo](https://raw.githubusercontent.com/jinlio/agent-xray/main/docs/demo.gif)

"What did the agent actually do for those 40 minutes? Where did the money go? Which step went off the rails?" — `grep`/`jq` over thousands of JSONL lines cannot answer that, and cloud observability platforms (Langfuse/LangSmith) require instrumenting your code and shipping data off your machine. Agent X-Ray reads the logs **already on your disk**; nothing to change.

## What it looks like

**Execution timeline** — one swim lane per turn: model calls on top (colored by source), tool calls below (colored by category), red outlines for failures, yellow edges for retries, diamond markers for context compaction. Click any segment for full details (reasoning / response / tool I/O / tokens / cost):

![Timeline](https://raw.githubusercontent.com/jinlio/agent-xray/main/docs/screenshot-timeline.png)

**Cost curve** — cumulative tokens/spend over time, with peak markers and a per-model breakdown:

![Cost](https://raw.githubusercontent.com/jinlio/agent-xray/main/docs/screenshot-cost.png)

The report UI is **bilingual (English / Chinese)**: it follows your browser language on first open, and the header toggle (中文 / EN) remembers your choice. Session content itself is shown exactly as recorded.

## Quick start

```bash
# install (zero runtime deps: stdlib + inlined ECharts)
uv tool install agentxray-replay   # or: pipx install agentxray-replay / pip install agentxray-replay
                                   # PyPI name is agentxray-replay (agent-xray was taken); the command is agent-xray

agent-xray                         # list all local ZCode sessions
agent-xray --summary               # terminal summary of the latest session (with failure list)
agent-xray --session 3             # render session #3 → ./agent-xray-out/xxx-xray.html
agent-xray --session 3 --open      # render and open in the browser

# Claude Code transcripts
agent-xray ~/.claude/projects/<proj>/<session>.jsonl
agent-xray ~/.claude/projects/<proj>/        # batch + index page (subagents/ picked up automatically)

# Codex CLI rollouts
agent-xray ~/.codex/sessions                 # date-nested rollout tree, discovered recursively
agent-xray ~/.codex/sessions/2026/10/07/rollout-xxx.jsonl
```

Format auto-detection: `.jsonl` files are classified by their first record (Claude Code transcript vs Codex rollout); feeding the wrong format produces a clear warning instead of an empty report.

Terminal summary example (real session output; CLI labels are currently Chinese, while the HTML report is bilingual):

```
# 优化 deep-research-skill 项目计划
  轮次 2 · 模型调用 91 (+1 后台) · 工具 128 · 重试 8
  tokens: in 10.32M / out 74.8k / cache 10.10M (合计 20.50M)
  成本估算: $2.8754
  失败点 (16):
    [模型调用失败] turn #1: Cannot connect to API: Connect Timeout Error (zcode.z.ai:443)
    [重试] turn #1: GLM-5.3-Flash needed 6 attempts
    [工具失败] turn #1: Edit: File has not been read yet. ...
  工具 Top: Bash×38(1 err) · Write×24 · Edit×23(2 err) · Read×18
```

## Supported sources

| Source | Location | Status |
|---|---|---|
| **ZCode** | `~/.zcode/cli/db/db.sqlite` (auto-discovered, read-only snapshot; a running ZCode is unaffected) | ✅ Primary source; 6 weeks / 141 sessions / 9.8k model calls fully parsed |
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | ✅ Verified on 2.1.x: streamed-line merging, tool_use↔tool_result pairing, both `<session>/subagents/` files and inline sidechains |
| **Codex** | `~/.codex/sessions/**/*.jsonl` | ✅ Verified on 0.14x–0.160.x / 55 rollouts: turn_context turns, per-response usage attribution (with token_count fallback), nested collab turns → subagent tabs, turn_aborted → interruption highlight |
| Generic | Custom adapter (~100 lines of Python) | 🚧 planned for v1.0 |

Other commands: `--list`, `--all --limit 20` (batch render + index page), `--trunc N` / `--full` (text truncation), `--price-file` (custom pricing), `--db` (explicit sqlite path).

## Custom pricing

Costs are local estimates. Three-layer precedence: `--price-file` > auto-loaded `~/.agent-xray/prices.json` > built-in table. File format:

```json
{
  "cache_read_factor": 0.1,
  "cache_write_factor": 1.25,
  "models": [
    {"match": "gpt-5.6-terra", "input": 2.5, "output": 10.0},
    {"match": "codex-auto-review", "input": null, "output": null}
  ]
}
```

- `match` is a case-insensitive prefix match; **earlier entries win** — override only the models you care about and the rest keep built-in prices. Add `"replace_defaults": true` to replace the built-in table entirely.
- `input` / `output` are USD per million tokens; set to `null` to leave a model unpriced (excluded from totals).
- `cache_read_factor` / `cache_write_factor` control cache pricing multipliers (defaults 0.1x / 1.25x, matching ccusage).
- `agent-xray --dump-prices` exports the effective table (writes to a file if given one). Edit it and drop it at `~/.agent-xray/prices.json` to make it global — no flags needed.

## Privacy

- All parsing happens **on your machine**; the artifact is a local HTML file
- The HTML **never makes a network request** — ECharts is inlined, works fully offline
- No uploads, no anonymous telemetry
- Costs are **local estimates** (the price table can be overridden with `--price-file`), not billing data

## FAQ

**Q: How is this different from ccusage?**
ccusage answers "how much did I spend" (billing view); Agent X-Ray answers "what did the agent do, and where did it go wrong" (pathology view). The cost curve is just one line on the X-ray; the core is the execution timeline and failure analysis. They complement each other.

**Q: How is this different from Langfuse / LangSmith?**
They require instrumenting your code with an SDK and shipping data to a server, and they cannot help with sessions that **already happened**. Agent X-Ray is zero-instrumentation, fully local, and built for historical logs.

**Q: What if the ZCode format changes?**
Adapters probe capabilities table by table; missing tables/columns degrade gracefully (e.g., deriving durations from message timestamps when there is no usage table), never crash, and write degradations into the page's warning banner.

**Q: Do large sessions make the page slow?**
A real session with 2,633 messages / 2,273 model calls produced a 9.9 MB single-file HTML that stays interactive in a modern browser. Long text is truncated by default (`--trunc 2000`); `--full` disables truncation.

**Q: Why a single HTML file?**
Because the most common use is "show someone else" — put it in a PR, paste it in a chat, email it. One file, nothing to install on their side.

## Development

```bash
git clone <repo> && cd agent-xray
uv sync            # dev deps (pytest/ruff)
uv run pytest      # 29 tests: synthetic fixtures + golden snapshots + robustness + CLI
uv run ruff check src tests
uv run agent-xray --list
```

The architecture is intentionally minimal: `format adapters (zcode_db / claude_code / codex) → unified event model (Session/Turn/ModelCall/ToolUse) → single-file renderer`. The Claude Code adapter took an afternoon, Codex another one. PRs for new agents are welcome.

## License

MIT
