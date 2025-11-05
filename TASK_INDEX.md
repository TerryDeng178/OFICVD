# 任务卡索引（V4.1 · Cursor 执行顺序建议）

> 版本：2025-11-05 (V4.1)

本版任务卡已对齐 **src/alpha_core** 包结构与 V4.1 主文档；按依赖分为 M1→M2→M3。

## M1 里程碑（核心功能）

- [ ] TASK-01 — Data MCP：统一 Row Schema + 出站 DQ Gate（V4） · M1 · data
- [ ] TASK-02 — Data MCP：接入真实 WS／Harvester（实时） · M1 · data
- [ ] TASK-03 — Harvest：WS统一RowDQ落地（jsonl parquet） · M1 · harvest ★ V4.1新增
- [ ] TASK-04 — Signal：CORE_ALGO 服务化（Sink jsonl sqlite） · M1 · signal ★ V4.1新增
- [ ] TASK-05 — Docs：补齐 HARVEST CORE_ALGO 契约示例 · M1 · docs ★ V4.1新增
- [ ] TASK-06 — Orchestrator：编排与烟囱测试（M1→M3） · M1 · orchestrator ★ V4.1新增
- [ ] TASK-07 — Data MCP：历史回放（Parquet/CSV） · M1 · data
- [ ] TASK-08 — alpha_core：打包成熟组件（OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE） · M1 · pkg
- [ ] TASK-09 — Feature MCP：defaults.yaml → 组件构造器映射（V4） · M1 · feature
- [ ] TASK-10 — Feature MCP：compute_features 接线（OFI/CVD/FUSION/DIVERGENCE） · M1 · feature
- [ ] TASK-11 — Feature MCP：generate_signal 稳定化（冷却/持仓最小/翻转滞后/Regime） · M1 · feature
- [ ] TASK-12 — Risk MCP：StrategyMode 闸门 + 健康检查（V4） · M1 · risk
- [ ] TASK-13 — Risk MCP：波动率目标仓位 + 日内损失墙（迟滞） · M1 · risk
- [ ] TASK-14 — Broker MCP：幂等键 + 订单状态机（TIMEOUT→REQUERY） · M1 · broker
- [ ] TASK-16 — Orchestrator：事件流 JSONL + 模式（HOLD/PAPER/SHADOW/LIVE） · M1 · orchestrator
- [ ] TASK-20 — 治理：Kill Switch 梯度（DATA/BROKER/RISK/MANUAL）+ 脚本 · M1 · ops

## M2 里程碑（增强功能）

- [ ] TASK-15 — Broker MCP：后端切换（paper｜ccxt｜testnet） · M2 · broker
- [ ] TASK-17 — PnL Engine：手续费/资金费率/已未实现盈亏（独立模块） · M2 · pnl
- [ ] TASK-18 — Report MCP：日报 + 分层指标 + 参数 Scoreboard · M2 · report
- [ ] TASK-19 — 控制面：set_config(new, activate_at) + 变更事件 · M2 · orchestrator
- [ ] TASK-21 — 回放一致性：Replay Harness（离线→在线对齐） · M2 · test
- [ ] TASK-22 — CI：Mermaid/JSON 契约校验 + Smoke 起停 · M2 · ci

---

**说明**：标记 ★ V4.1新增 的任务是 V4.1 版本新增的核心功能模块。
