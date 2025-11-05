# Risk MCP：StrategyMode 闸门 + 健康检查（V4）
**任务编号**: TASK-12  
**批次**: M1  
**优先级**: P0  
**所属模块**: risk

## 背景
把时段白名单、市场活跃度、数据质量作为第一层闸门。

## 目标
`/propose_order` 在不允许时段/低活跃/数据异常时直接 HOLD；提供 `/check_system_health`。

## 前置依赖
- TASK-01, TASK-10

## 输出物
- 可读的健康指标，HOLD 原因明确

## 实现步骤（Cursor 分步操作）
- [ ] 引入 `alpha_core.risk.strategy_mode`
- [ ] 接收 Data MCP 的 dq 信号→短 HOLD_DATA
- [ ] `/check_system_health` 输出 schedule/market/data 指标与原因

## 验收标准（Acceptance Criteria）
- 非白名单必 HOLD
- dq 异常触发 HOLD_DATA（10~60s 可配）

## 验收命令/脚本
`curl http://localhost:9003/check_system_health`

## 代码改动清单（相对仓库根）
- mcp/ofi_risk_server/app.py
- config/defaults.yaml

## 潜在风险与回滚
- 时区问题：统一 Asia/Tokyo
- 信号震荡：增加迟滞

## 预计工时
0.5 天
