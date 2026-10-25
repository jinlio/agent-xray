# Release v0.2.0 — Codex 适配 + Claude Code 子代理修复

## 新增

- **Codex CLI 适配器**（`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`）
  - 实测 0.14x–0.160.x 共 55 个真实 rollout：其中 52 个 token 总量与文件内 `token_count` 自报值比例 1.00–1.03（其余 3 个为源数据 usage 记录缺失，会输出"总量可能低估"警告）
  - 轮次（`turn_context`）↔ 逐响应 usage 归因（`token_usage_record` 按行序落到前面的响应段）；老格式无 usage 记录时自动回退 `token_count.last_token_usage` 并去重
  - 嵌套协作轮（`root_turn_id != turn_id`）按根轮分组为子代理标签页；整文件都是嵌套轮的续写会话自动提升为主会话
  - `turn_aborted` → 中断失败点 + 轮次状态；`compacted` → 上下文压缩标记；`developer` 注入消息计入隐藏计数
  - 老格式 `passthrough.turn_id` 与 turn_context 不同 id 空间的问题：只在命中已知 turn_context 时才信任，否则回退到最近一条 turn_context
- **CLI 格式自动识别**：`.jsonl` 按首行 `session_meta` 判定 Codex / Claude Code；无法识别的格式现在会在渲染时输出 stderr 警告，不再静默产出空白报告

## 修复

- **Claude Code 2.1+ 子代理**：新版把每个子代理写到 `<session-id>/subagents/agent-*.jsonl` 独立文件（主转录内联 `isSidechain` 记录已消失）
  - 独立子代理文件现在解析为真实会话（此前是全 0 的空父会话 + 影子子会话）
  - 渲染主转录时自动挂载兄弟 `subagents/` 目录下的子代理到子代理标签页
  - 目录模式递归发现（旧版非递归 glob 完全扫不到子代理文件）
- Claude Code 子代理文件中不带 `isSidechain` 标志的 `attachment`/`api-request` 噪声行不再干扰独立文件判定

## 其他

- **价格表全面可自定义**：`~/.agent-xray/prices.json` 自动加载（无需每次传参）；自定义条目与内置表**合并、靠前优先**（此前 `--price-file` 为整体替换，覆盖一个模型会把其余模型打回 fallback 估价）；缓存计价系数 `cache_read_factor` / `cache_write_factor` 可配；`"replace_defaults": true` 保留完全替换语义；`agent-xray --dump-prices [FILE]` 导出当前生效表作为起点
- 价格表新增 `codex` 前缀条目（`codex-auto-review` 等内部模型不计价）
- 测试 16 → 29 个（Codex golden / 递归发现 / 格式嗅探 / 子代理三个新测试 / 价格表合并·系数·自动加载·导出 / CLI 端到端）；现有 zcode 与 claude_code golden 逐字节不变

# Release v0.1.0 — 首个公开版本

**Agent X-Ray**：零埋点、纯本地的编码 agent 会话回放器。把 ZCode / Claude Code 的本地会话日志变成一张可交互的执行 X 光片（单个 HTML 文件，完全离线）。

## Highlights

- **执行时间轴**：每轮对话一条泳道，模型调用与工具调用分层着色，失败红框 / 重试黄边 / 上下文压缩标记；点击任意段展开思考过程、回复、工具输入输出、token 与成本明细
- **失败点自动高亮**：工具错误、模型错误、重试、上下文超限、权限拒绝、用户中断、超长轮次，一键跳转定位
- **工具调用树**：按类别聚合的调用统计（次数 / 错误率 / 耗时），可下钻到每一次调用
- **成本曲线**：累积 token/费用曲线 + 峰值标注 + 分模型成本表（本地估算，价格表可自定义）
- **单文件 HTML 输出**：数据 + ECharts 全部内联，双击即看、完全离线、可直接分享
- **零依赖解析端**：纯 Python 标准库，`uv tool install agentxray-replay` 即用（PyPI 包名 `agentxray-replay`，命令简写 `agent-xray`）

## 数据源

- ZCode（`~/.zcode/cli/db/db.sqlite`，自动发现、只读快照）— 实测 6 周 / 141 会话 / 9.8k 模型调用全量解析通过，平均 9ms/会话
- Claude Code（`~/.claude/projects/**/*.jsonl`）— **experimental**，按公开格式文档开发，支持流式拆行合并 / tool_use 配对 / sidechain 子代理

## 质量

- 16 个测试：合成 fixture（schema 与真实库一致）+ golden 快照 + 缺表降级 + 坏行健壮性 + 20k 消息规模 + CLI 端到端
- ruff 全绿；GitHub Actions 三版本（3.11/3.12/3.13）矩阵

## 已知限制

- Claude Code 适配器未经本机真实日志验证（experimental，欢迎附脱敏样本提 issue）
- 成本为本地估算（对齐 ccusage 缓存计价口径），非账单
- ZCode rollout JSONL（原始 request/response 快照）适配排在 v0.2
