# TASK_INDEX · OFI+CVD（V4.1）
> 更新日期：2025-11-07 (Asia/Tokyo)

本索引对应 README V4.1（已纳入 **HARVEST / CORE_ALGO**）。按里程碑分三阶段：

- **M1 · 数据打通**：TASK-01 ~ 04
- **M2 · 信号与风控**：TASK-05 ~ 07
- **M3 · 编排、回测与复盘**：TASK-08 ~ 10

## 任务清单
1. ✅ TASK-01 - 统一 Row Schema & 出站 DQ Gate（Data Contract）  
2. ✅ TASK-02 - Harvester WS Adapter（Binance Futures）  
3. ✅ TASK-03 - Harvest MCP 薄壳与本地运行脚本  
4. ✅ TASK-04 - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）  
5. ✅ TASK-05 - CORE_ALGO 信号服务（Sink: JSONL/SQLite）  
6. ✅ TASK-06 - StrategyMode & 风控护栏（spread/lag/activity 等）**（已签收，2025-11-07）**  
7. TASK-07 - Orchestrator 编排与端到端冒烟  
8. TASK-08 - 回放/回测 Harness（JSONL/Parquet → 信号 → PnL）  
9. TASK-09 - 复盘报表（时段胜率、盈亏比、滑点、费用）  
10. TASK-10 - 文档与契约同步（/docs 与 README 链接校验）  

### TASK-06 完成摘要

**状态**：✅ 已完成（2025-11-07）

**关键成果**：
- ✅ StrategyModeManager 成功集成到 CoreAlgorithm
- ✅ 解决了 100% Quiet 问题（Active 占比从 0% 提升到 99.998%）
- ✅ Schedule 触发器正常工作（默认开启，空窗口=全天有效）
- ✅ 心跳日志 JSON 格式优化（每 10s 快照）
- ✅ 性能可接受（~837 rows/sec，1.2ms/row）

**相关文档**：
- 修复验证报告：`reports/P0-StrategyMode-100-Quiet-修复验证报告.md`
- 检查清单：`docs/P0-修复验证检查清单.md`
- Staging 配置：`config/defaults.staging.yaml`  

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
