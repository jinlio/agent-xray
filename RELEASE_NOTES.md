# Release v0.1.0 — 首个公开版本

**Agent X-Ray**：零埋点、纯本地的编码 agent 会话回放器。把 ZCode / Claude Code 的本地会话日志变成一张可交互的执行 X 光片（单个 HTML 文件，完全离线）。

## Highlights

- **执行时间轴**：每轮对话一条泳道，模型调用与工具调用分层着色，失败红框 / 重试黄边 / 上下文压缩标记；点击任意段展开思考过程、回复、工具输入输出、token 与成本明细
- **失败点自动高亮**：工具错误、模型错误、重试、上下文超限、权限拒绝、用户中断、超长轮次，一键跳转定位
- **工具调用树**：按类别聚合的调用统计（次数 / 错误率 / 耗时），可下钻到每一次调用
- **成本曲线**：累积 token/费用曲线 + 峰值标注 + 分模型成本表（本地估算，价格表可自定义）
- **单文件 HTML 输出**：数据 + ECharts 全部内联，双击即看、完全离线、可直接分享
- **零依赖解析端**：纯 Python 标准库，`uv tool install agent-xray` 即用

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
