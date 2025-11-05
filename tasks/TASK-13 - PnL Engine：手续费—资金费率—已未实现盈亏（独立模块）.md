# PnL Engine：手续费/资金费率/已未实现盈亏（独立模块）
**任务编号**: TASK-13  
**批次**: M2  
**优先级**: P1  
**所属模块**: pnl

## 背景
账务与可回放的核心；不要耦合在 Broker。

## 目标
单独模块从 fills/positions 计算 `pnl_ledger.jsonl`；可重算。

## 前置依赖
- TASK-12

## 输出物
- `logs/pnl_ledger.jsonl` 周期更新
- （可选）`GET /pnl_snapshot`

## 实现步骤（Cursor 分步操作）
- [ ] 解析 fills（方向/价/量/fee）
- [ ] 已实现/未实现 PnL（avg_px）
- [ ] 资金费率计提（如适用）
- [ ] ledger 可重算

## 验收标准（Acceptance Criteria）
- 样例账务正确；删除重算一致

## 验收命令/脚本
`python scripts/recompute_pnl.py`

## 代码改动清单（相对仓库根）
- orchestrator/pnl_engine.py
- mcp/report_server/app.py

## 潜在风险与回滚
- 局部平仓平均价处理：谨慎实现

## 预计工时
1 天
