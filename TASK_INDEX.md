# TASK_INDEX · OFI+CVD（V4.1）
> 更新日期：2025-11-05 (Asia/Tokyo)

本索引对应 README V4.1（已纳入 **HARVEST / CORE_ALGO**）。按里程碑分三阶段：

- **M1 · 数据打通**：TASK-01 ~ 04
- **M2 · 信号与风控**：TASK-05 ~ 07
- **M3 · 编排、回测与复盘**：TASK-08 ~ 10

## 任务清单
1. TASK-01 - 统一 Row Schema & 出站 DQ Gate（Data Contract）  
2. TASK-02 - Harvester WS Adapter（Binance Futures）  
3. TASK-03 - Harvest MCP 薄壳与本地运行脚本  
4. TASK-04 - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）  
5. TASK-05 - CORE_ALGO 信号服务（Sink: JSONL/SQLite）  
6. TASK-06 - StrategyMode & 风控护栏（spread/lag/activity 等）  
7. TASK-07 - Orchestrator 编排与端到端冒烟  
8. TASK-08 - 回放/回测 Harness（JSONL/Parquet → 信号 → PnL）  
9. TASK-09 - 复盘报表（时段胜率、盈亏比、滑点、费用）  
10. TASK-10 - 文档与契约同步（/docs 与 README 链接校验）  

## 依赖关系（简）
- 02 依赖 01  
- 03 依赖 02  
- 04 依赖 01/02  
- 05 依赖 04  
- 06 依赖 05  
- 07 依赖 03/05/06  
- 08 依赖 01/04/05  
- 09 依赖 08  
- 10 贯穿全程
