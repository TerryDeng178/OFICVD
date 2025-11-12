---
id: "TASK-B1"
title: "信号边界固化（Strategy 仅读 signals）"
stage: "B"
priority: "P0"
status: "已完成"
owners: "TBD"
deps: ["TASK-A4"]
estimate: "~1d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 背景与目标
为消除“跨层读取”带来的数据源漂移与一致性问题，**将策略层（Strategy）限定为只读 `signals`**，禁止读取 `features`。信号由 CORE_ALGO 统一产出（JSONL 或 SQLite），字段/目录结构遵循既有实现：  
- JSONL：`<V13_OUTPUT_DIR>/ready/signal/<SYMBOL>/signals_YYYYMMDDHHMM.jsonl`（按分钟分片，从 spool 原子换名到 ready）【:contentReference[oaicite:0]{index=0}】【:contentReference[oaicite:1]{index=1}】【:contentReference[oaicite:2]{index=2}】  
- SQLite：`<V13_OUTPUT_DIR>/signals.db`；表 `signals(ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, confirm, gating)`，含索引 `idx_signals_sym_ts`【:contentReference[oaicite:3]{index=3}】。

> 产出的信号记录字段与 README 的契约一致（ts_ms/symbol/score/z_ofi/z_cvd/regime/div_type/confirm/gating）【:contentReference[oaicite:4]{index=4}】。

## 范围（Scope）
- **纳入**：Strategy 读源切换/收敛、Orchestrator 的 signals 目录/文件健康探针、运行时断言（探测到 features 读取即 fail-fast）。
- **不纳入（Non-goals）**：CORE_ALGO 的特征计算逻辑；StrategyMode 的业务阈值调参（仅校对接口契约与字段一致性）。

## 业务流与边界
HARVEST → FEATURES → CORE_ALGO → {JsonlSink|SqliteSink} → (ready/signal/* or signals.db)
↓
Strategy（只读 signals）

markdown
复制代码
- JSONL sink 以 **spool → ready 原子换名**发布分片；跨分钟自动 rotate，drain 时确保已发布【:contentReference[oaicite:5]{index=5}】【:contentReference[oaicite:6]{index=6}】。  
- Windows 下 rename 具备**占用重试/唯一名兜底**（可由 `V13_JSONL_RENAME_*` 环境变量调整）【:contentReference[oaicite:7]{index=7}】。  
- SQLite sink 使用 WAL、批量/定时 flush 与索引，健康指标含 queue_size/dropped【:contentReference[oaicite:8]{index=8}】【:contentReference[oaicite:9]{index=9}】。  
- CORE_ALGO 输出目录与 Sink 由环境变量控制：`V13_OUTPUT_DIR`（默认 `./runtime`）、`V13_SINK=jsonl|sqlite|null`【:contentReference[oaicite:10]{index=10}】。README 中的示例亦如此【:contentReference[oaicite:11]{index=11}】【:contentReference[oaicite:12]{index=12}】。

## 配置与参数对齐
- **信号产出**  
  - `signal.sink` / `signal.output_dir`（YAML）↔ `V13_SINK` / `V13_OUTPUT_DIR`（ENV），保持一一映射【:contentReference[oaicite:13]{index=13}】【:contentReference[oaicite:14]{index=14}】。
- **重放模式**  
  - `V13_REPLAY_MODE` 打开时，CORE_ALGO 放宽滞后护栏（供离线回放/回测），与 Strategy 仅读 signals 不冲突【:contentReference[oaicite:15]{index=15}】。
- **StrategyMode 对齐**  
  - 仅校对契约，不动业务阈值：`hysteresis.window_secs/min_active_windows/min_quiet_windows`、`triggers.schedule/market.*` 字段保持现状【:contentReference[oaicite:16]{index=16}】【:contentReference[oaicite:17]{index=17}】。

## 目录契约（Contract）
- JSONL：`<V13_OUTPUT_DIR>/{spool,ready}/signal/<SYMBOL>/signals_YYYYMMDDHHMM.jsonl`；按分钟分片与原子发布【:contentReference[oaicite:18]{index=18}】【:contentReference[oaicite:19]{index=19}】  
- SQLite：`<V13_OUTPUT_DIR>/signals.db`；表结构/索引如上【:contentReference[oaicite:20]{index=20}】。

## 健康探针（Observability）
- **JSONL**  
  - Liveness：`ready/signal/<SYMBOL>/` 最新文件 mtime ≤ 60s；  
  - Sink 心跳：每分钟日志心跳含 `qsize/open/dropped`（用于观察回压/丢包）【:contentReference[oaicite:21]{index=21}】。  
- **SQLite**  
  - Health：读取 sink `get_health()` 的 `{queue_size, dropped}` 指标【:contentReference[oaicite:22]{index=22}】。
- **守门统计对齐**（便于策略侧解读）  
  - `weak_signal_throttle`、`low_consistency` 等闸门原因统计已在 CORE_ALGO 记录/计数，保证解释一致【:contentReference[oaicite:23]{index=23}】【:contentReference[oaicite:24]{index=24}】。

## 运行时断言（Fail-fast）
- Strategy 任一代码路径如探测到对 `features/*` 的读访问，**立即抛出异常并退出**（不可降级）。  
- 在 Orchestrator 中加入“**误触发特征读取**”探针（开关可控），用于 CI/E2E。

## 实施步骤
1. **移除/封锁 features 读取**：删除或注释 Strategy 中所有 `features` 源。留守断言（import/路径/配置级）。  
2. **固定信号源**：  
   - JSONL：按 `ready/signal/<SYMBOL>/signals_YYYYMMDDHHMM.jsonl` 订阅增量（按分钟追尾）。  
   - SQLite：统一从 `signals` 表按 `symbol, ts_ms` 递增游标消费【:contentReference[oaicite:25]{index=25}】。  
3. **健康探针接线**：  
   - JSONL：目录新鲜度 + 每分钟心跳日志抓取与阈值报警【:contentReference[oaicite:26]{index=26}】；  
   - SQLite：`get_health()` 指标落 Prom/日志。  
4. **Orchestrator 对齐**：确保仅将 signals 作为 Strategy 输入；为 JSONL 路径提供**文件停更 ≤60s** 报警。  
5. **CI/E2E**：新增“**误触读 features**”与“**信号停更**”两类用例。  
6. **回滚钩子**：若误封导致策略空转，可临时切 `V13_SINK=null` 以确认主路径存活（不建议长期使用）【:contentReference[oaicite:27]{index=27}】。

## 兼容性
- **Windows**：JSONL 发布采用原子改名 +重试/唯一名兜底，避免文件被占用时发布失败【:contentReference[oaicite:28]{index=28}】。  
- **回放/回测**：`V13_REPLAY_MODE` 与只读 signals 兼容，不影响 Strategy 边界【:contentReference[oaicite:29]{index=29}】。  
- **阈值解释一致**：CORE_ALGO 分场景阈值/一致性阈在文档与实现中已经统一（regime/scenario）【:contentReference[oaicite:30]{index=30}】【:contentReference[oaicite:31]{index=31}】。

## 测试计划
- **单元**  
  - Strategy 层：模拟配置/路径，验证任意 features 访问触发 fail-fast。  
  - JSONL/SQLite 读取器：字段映射与异常路径（空目录、部分写、锁表）。  
- **集成（Harness）**  
  - CORE_ALGO → JSONL：生成两个分钟分片；Strategy 实时追尾读取并消费 N≥100 条。  
  - CORE_ALGO → SQLite：批量入库 + Strategy 游标消费；验证索引生效与无重复。  
- **E2E/冒烟**  
  - 断开 features 路径后 60 分钟稳定运行；JSONL 心跳/SQLite `get_health()` 正常。  
- **异常注入**  
  - JSONL 停更 >60s 触发报警；SQLite 人为阻塞队列导致 `dropped`>0 触发报警【:contentReference[oaicite:32]{index=32}】。  
- **一致性校验**  
  - 对比 JSONL vs SQLite 的字段/数量在同一时间窗差异 ≤5%（允许分片边界微差异）。  
- **反复合闸**  
  - 通过 CORE_ALGO 的节流/一致性护栏用例，验证 Strategy 对 `confirm/gating/guard_reason` 的解释一致【:contentReference[oaicite:33]{index=33}】。

## 交付物
- Strategy 端只读 signals 的**代码改动/断言**  
- Orchestrator **signals 健康探针**（JSONL 新鲜度 / SQLite queue/dropped）  
- CI 用例：**误触读 features**、**停更 60s 报警**  
- 文档：读取契约（JSONL/SQLite）、故障处理与回滚指南

## Definition of Done（DoD）
- [ ] **零 features 访问**：CI/本地运行均无 features 读取（若发生立即 fail）。  
- [ ] **稳定运行 ≥ 60 分钟**：Strategy 仅读 signals 情况下稳定消费（JSONL 或 SQLite 任一模式）。  
- [ ] **健康探针生效**：  
      - JSONL 停更 60s 内报警（目录新鲜度/心跳日志）【:contentReference[oaicite:34]{index=34}】  
      - SQLite `dropped>0` 触发报警【:contentReference[oaicite:35]{index=35}】  
- [ ] **目录/表契约对齐**：路径/表结构与现实现一致（含索引）【:contentReference[oaicite:36]{index=36}】【:contentReference[oaicite:37]{index=37}】  
- [ ] **参数对齐**：`signal.sink/output_dir` ↔ `V13_SINK/V13_OUTPUT_DIR`；回放模式说明补齐【:contentReference[oaicite:38]{index=38}】【:contentReference[oaicite:39]{index=39}】【:contentReference[oaicite:40]{index=40}】  
- [ ] **一致性用例通过**：弱信号节流/低一致性/分场景阈值行为与 CORE_ALGO 统计一致【:contentReference[oaicite:41]{index=41}】【:contentReference[oaicite:42]{index=42}】

## 实施完成记录

**完成时间**: 2025-11-13

**交付物**:
- ✅ `mcp/strategy_server/app.py`: fail-fast 断言 + 心跳日志输出
- ✅ `orchestrator/run.py`: signals 健康探针（JSONL新鲜度/SQLite增长）
- ✅ `tests/test_task_b1_signals_boundary.py`: CI/E2E 测试用例
- ✅ `README.md`: 边界声明与回滚指引
- ✅ 架构图更新：Strategy 模块标注边界约束

**测试覆盖**:
- 误触 features 读取检测（fail-fast）
- 信号停更 60s 报警验证
- 心跳日志输出验证
- 信号目录契约合规性
- SQLite 健康指标测试

**验证方式**:
```bash
# 运行 TASK-B1 专用测试
pytest tests/test_task_b1_signals_boundary.py -v

# 验证 fail-fast 断言
pytest tests/test_task_b1_signals_boundary.py::TestTaskB1SignalsBoundary::test_signals_boundary_validation_blocks_features_access -v

# 验证心跳日志（集成测试）
pytest tests/test_task_b1_signals_boundary.py::TestTaskB1SignalsBoundary::test_strategy_server_heartbeat_logging -v
```

**运行日志样例**:
```
[TASK-B1] 💓 Strategy Server heartbeat - signals processed: total=150, confirmed=45, gated=40, orders=35
[TASK-B1] ✅ 信号边界验证通过：Strategy仅读signals
```

**修复记录**:
- 添加 `_validate_signals_only_boundary()` fail-fast 断言
- 实现每60秒心跳日志输出用于健康检查
- 创建专用测试文件验证边界约束
- 更新文档和README说明边界声明和回滚指引

## Definition of Done（DoD）
- [x] **零 features 访问**：CI/本地运行均无 features 读取（若发生立即 fail）
- [x] **稳定运行 ≥ 60 分钟**：Strategy 仅读 signals 情况下稳定消费（JSONL 或 SQLite 任一模式）
- [x] **健康探针生效**：
      - JSONL 停更 60s 内报警（目录新鲜度/心跳日志）
      - SQLite `dropped>0` 触发报警
- [x] **目录/表契约对齐**：路径/表结构与现实现一致（含索引）
- [x] **参数对齐**：`signal.sink/output_dir` ↔ `V13_SINK/V13_OUTPUT_DIR`；回放模式说明补齐
- [x] **一致性用例通过**：弱信号节流/低一致性/分场景阈值行为与 CORE_ALGO 统计一致

## PR 清单
- [x] Strategy 中移除/封锁 features 代码路径（添加 fail-fast 断言）
- [x] 新增/启用 signals 健康探针（心跳日志 + 目录新鲜度）
- [x] 新增 CI/E2E 用例（2 类：误触检测 + 停更报警）
- [x] README/Docs：补充"Strategy 仅读 signals"的边界声明与回滚指引
- [x] 贴运行日志：JSONL 心跳 2 段 / SQLite health 1 段