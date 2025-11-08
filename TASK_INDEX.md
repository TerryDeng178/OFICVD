# TASK_INDEX · OFI+CVD（V4.1）
> 更新日期：2025-11-08 (Asia/Tokyo)

本索引对应 README V4.1（已纳入 **HARVEST / CORE_ALGO**）。按里程碑分三阶段：

- **M1 · 数据打通**：TASK-01 ~ 04
- **M2 · 信号与风控**：TASK-05 ~ 07
- **M3 · 编排、回测与复盘**：TASK-07A ~ 10

## 任务清单
1. ✅ TASK-01 - 统一 Row Schema & 出站 DQ Gate（Data Contract）  
2. ✅ TASK-02 - Harvester WS Adapter（Binance Futures）  
3. ✅ TASK-03 - Harvest MCP 薄壳与本地运行脚本  
4. ✅ TASK-04 - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）  
5. ✅ TASK-05 - CORE_ALGO 信号服务（Sink: JSONL/SQLite）  
6. ✅ TASK-06 - StrategyMode & 风控护栏（spread/lag/activity 等）**（已签收，2025-11-07）**  
7. ✅ TASK-07 - Orchestrator 编排与端到端冒烟**（已签收，2025-11-08）**  
8. ⏳ TASK-07A - LIVE 60 分钟端到端实测（Soak Test）  
9. ⏳ TASK-07B - 双 Sink 等价性收敛（目标 < 0.2%）  
10. TASK-08 - 回放/回测 Harness（JSONL/Parquet → 信号 → PnL）  
11. TASK-09 - 复盘报表（时段胜率、盈亏比、滑点、费用）  
12. TASK-10 - 文档与契约同步（/docs 与 README 链接校验）  

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

### TASK-07 完成摘要

**状态**：✅ 已完成（2025-11-08）

**关键成果**：
- ✅ Orchestrator 完整实现（Supervisor、Probe、Reporter）
- ✅ 双 Sink 支持（JSONL + SQLite 并行写入，等价性验证通过）
- ✅ 健康检查优化（LIVE/replay 模式区分，避免误报）
- ✅ 优雅重启功能（故障注入测试通过，12 秒内成功重启）
- ✅ P1 增强功能（Runtime State、事件→信号联动、时序库导出、告警）

**验证结果**：
- ✅ E2E 测试通过（Smoke 场景、双 Sink 等价性、优雅关闭、故障注入）
- ✅ 功能验证完成度 83%（5/6 任务完全验证，1/6 任务代码级验证）
- ✅ 代码实现完成度 100%

**相关文档**：
- 总体执行报告：`reports/v4.0.6-总体执行报告.md`
- E2E 测试报告：`reports/v4.0.6-E2E测试报告.md`
- 双 Sink 测试评估：`reports/v4.0.6-双Sink-E2E测试评估报告.md`
- 故障注入验证报告：`reports/v4.0.6-P0-3-故障注入验证报告.md`  

## 依赖关系（简）
- 02 依赖 01  
- 03 依赖 02  
- 04 依赖 01/02  
- 05 依赖 04  
- 06 依赖 05  
- 07 依赖 03/05/06  
- 07A 依赖 07  
- 07B 依赖 07/07A  
- 08 依赖 01/04/05  
- 09 依赖 08  
- 10 贯穿全程
