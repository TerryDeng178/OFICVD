
# TASK09X — 一致性优先优化任务卡（仅模式 / 护栏 / 对齐 / 活动度）
**项目**：OFI·CVD 微结构交易框架  
**版本**：v13 系（回放/回测通用）  
**适用环境**：Replay / Backtest（非实盘）  
**日期**：2025-11-10（Asia/Tokyo）

> 说明：本任务卡**仅**覆盖“一致性优先”工作面（StrategyMode、Risk Guards、Time/Book 对齐、Activity 注入）。**不包含参数优化**（融合阈值、防抖、网格等）；参数优化将另起任务卡。

---

## 0. 背景与目标
近期回测交易质量不佳，初步判断与**深层逻辑/一致性**有关：模式长期 quiet、延迟护栏在回放模式下过严、盘口/时间对齐存在偏移、活动度字段缺失/失真等。  
**目标**：在不动“策略参数”的前提下，完成四大一致性层的统一校准，建立**可复现、可审计、可回滚**的一致性基线。

**达成效果（预期）**
- 回放样本下，策略不再长期处于 quiet；确认节奏稳定。
- Gate 统计无单一“主因门”长期压制（top-1 占比 < 60%）。
- 事件延迟/盘口价差/活动度分布合理；JSONL/SQLite 窗口一致。
- 形成完整的一致性报告与配置基线，作为后续参数优化与实盘上线的前置条件。

---

## 1. 范围（Scope）
**在回放/回测环境**完成一致性校准的设计、实施与验收（DoD）。输出工件、报告与配置基线。
- **在范围**：StrategyMode 固定与触发阈值校准；Risk Guards 降格与影子化；时间/盘口对齐；活动度计算与注入；A/B 对照以定位“主因门”；I/O 干扰排除。
- **不在范围**：任意融合阈值、防抖、持仓、下单参数的调优；实盘风控联动与交易执行策略调整。

---

## 2. 统一业务流（SSOT 视图）
```mermaid
flowchart LR
  H[Harvester 数据源] --> F[Features: OFI/CVD/统计要素]
  F --> U[Fusion(仅做特征汇聚，不改阈值)]
  U --> M[StrategyMode 判定]
  M --> G[Risk Guards(延迟/价差/活动度/去重/冷却)]
  G --> C[Confirm 确认]
  C --> R[Replay/Backtest 执行]
  R --> S[Sink(JSONL/SQLite/Null)]
  S --> T[指标聚合与一致性报告]
```
> **SSOT（Single Source of Truth）**：配置以 `config/` 下 YAML 为唯一权威；CLI/ENV 仅覆写，所有覆写需写入运行元数据以便审计与复现。

---

## 3. 目录与产物（建议）
```
repo/
  config/
    stage1_consistency.yaml       # 一致性基线配置（本卡核心）
    stage1_shadow.yaml            # 影子护栏 A/B 对照配置
    schema_maps.yaml              # 字段名映射（适配器层）
  scripts/
    run_stage1_optimization.py                 # 执行器（回放样本→产物）
    collect_gate_stats.py         # Gate 聚合与TOP原因统计
    audit_alignment.py            # 对齐/延迟/价差/活动度审计
  runtime/
    artifacts/
      gate_stats.jsonl
      gate_stats.parquet
      ab_compare.parquet
    reports/
      report_consistency.md
      alignment_audit.md
      ab_summary.md
    logs/
```

---

## 4. 配置契约与适配（关键字段对齐）
> 若现有工程字段名不同，请在 **adapter 层**用 `schema_maps.yaml` 做统一映射；保持下述 SSOT 键。

### 4.1 StrategyMode（模式层）
```yaml
strategy_mode:
  dynamic_enabled: false        # 一致性阶段固定模式
  fixed_mode: "active"          # active | quiet | aggressive
  activity:                     # 仅用于后续启用动态模式时的阈值参考
    min_trades_per_min: 120
    min_quote_updates_per_sec: 20
  combine_logic: "OR"           # OR | AND（避免过苛导致假静默）
```

### 4.2 Risk Guards（护栏层）
```yaml
guards:
  # 活动度门：一致性阶段先关闭强制要求，避免“无活动”误伤
  require_activity: false

  # 事件延迟护栏：统一以 shadow 影子化运行，用于定位因果，不拦截确认
  max_event_lag_sec:
    value: 2.0
    mode: "shadow"              # active | shadow

  # 盘口价差护栏：保持 active，先校正 spread 计算与对齐
  spread_bps_cap:
    value: 8.0
    mode: "active"

  # 去重/冷却：一致性阶段保持基线值，不做优化，只验证是否过度/不足
  dedup_window_ms: 250
  cooldown_secs: 0.6
```

### 4.3 Replay/Backtest 与 Sink
```yaml
replay:
  enabled: true                 # 等价环境变量：V13_REPLAY_MODE=1
  tz: "Asia/Tokyo"
  cutover: "day"                # 切日口径与统计一致（可选 day/hour）

sink:
  type: "jsonl"                 # A/B 时可切 "null" 排除 I/O 干扰
  out_dir: "./runtime"
```

### 4.4 环境变量（统一覆写通道）
```
V13_REPLAY_MODE=1
V13_OUTPUT_DIR=./runtime
```

---

## 5. 数据契约与计算口径（Consistency Facts）
1. **时间戳精度**：`event_ts_ms`、`recv_ts_ms` 统一毫秒（ms）。`lag_ms = recv_ts_ms - event_ts_ms`。  
2. **盘口对齐**：1 秒粒度聚合对齐；盘口快照窗口 ≤ 1s；  
   `spread_bps = (best_ask - best_bid) / mid * 1e4`；异常值裁剪到 99.9 分位。  
3. **活动度（Activity）**：
   - `trades_per_min` = 60s 滚动交易笔数（或成交笔数累积差分）；
   - `quote_updates_per_sec` = 最近 1s 内报价更新次数（或深度变更事件数）；
   - 空值/0 值占比应 < 5%，覆盖率 ≥ 95%。
4. **时区与切日**：统一 `Asia/Tokyo`，统计报表与数据切分一致（`cutover: day` 或 `hour` 一致）。
5. **Schema 版本**：读取侧车/特征文件需记录 `schema_version`，若混用版本需在读取侧自动升级。

---

## 6. 执行步骤（一步一验）
### S1｜预检与映射
- 校验输入数据源可读性、时间范围、样本大小（≥ 10–20 分钟回放区间）。
- 完成 `schema_maps.yaml` 字段映射，确保 SSOT 键一致。
- 运行 `audit_alignment.py --fast`，输出 `alignment_audit.md`（ts 单调性、缺失率、活动度覆盖率初判）。

### S2｜开启回放与 Gate 统计
- 设置 `V13_REPLAY_MODE=1`、`V13_OUTPUT_DIR=./runtime`。
- 使用 `config/stage1_consistency.yaml` 回放 10–20 分钟。
- 产出 `runtime/artifacts/gate_stats.jsonl`（按原因聚合 top-k）。

### S3｜A/B：模式固定 + 影子护栏
- **A 组（一致性基线）**：`dynamic_enabled=false`, `fixed_mode=active`；`max_event_lag_sec.mode=shadow`；`sink.type=null`。  
- **B 组（当前配置）**：保持现有工程默认。  
- 产出 `ab_compare.parquet`；在 `ab_summary.md` 汇总：确认率、胜率、单笔期望（仅用于质控趋势，**不做参数优化解读**）、持仓秒数、gate top-1 占比。

### S4｜活动度计算与注入复核
- 若活动度缺失：以 1s 粒度从 trades/quotes 计算（见 §5.3），写回特征流或临时侧表并 join；
- 再跑 S2–S3，对比 gate 中与 `require_activity` 相关的触发占比变化。

### S5｜盘口/时间对齐深度审计
- 验证 `lag_ms` 分布：P50、P95、max；P95 目标 < 1500ms；  
- 验证 `spread_bps` 分布：P50、P95、99.9% 裁剪后曲线；极值与快市时段抽样复核；
- 检查 JSONL vs SQLite 窗口一致性：记录数差异 < 5%。

### S6｜I/O 干扰排除对照
- 将 `sink.type` 切换为 `null`，短跑 5 分钟，观察确认节奏、gate 分布是否显著变化；若变化明显，记录 I/O 影响并在后续回放中固定使用高性能 sink。

### S7｜固定一致性基线与回归集
- 确认 A 组为一致性基线（若 A 明显优于 B）；将 `stage1_consistency.yaml` 标记为 `baseline=true`；
- 选取 2–3 个代表性时段（快市、慢市、震荡）作为一致性回归集，归档输入数据指纹（path, size, mtime / sha）。

### S8｜报告与归档
- 生成 `report_consistency.md`：包含配置摘要、A/B 对照、gate top-k、lag 分位、spread 分布、活动度覆盖率、I/O 对照结论、问题树与建议；
- 报告、产物、日志统一归档到 `runtime/` 且记录 CLI/ENV 覆写实际生效值。

---

## 7. 验收标准（DoD）
- ✅ **非静默**：A 组与 B 组均有非零确认，且 A 组无长期 quiet（>80% 时段为 active）。  
- ✅ **主因门消散**：`gate_stats` 的 top-1 原因占比 < 60%。  
- ✅ **延迟/价差合理**：`lag_ms` P95 < 1500ms；`spread_bps` 分布合理且异常已裁剪/解释。  
- ✅ **活动度齐备**：活动度字段覆盖率 ≥ 95%，空缺/0 值占比 < 5%。  
- ✅ **窗口一致**：JSONL 与 SQLite（如启用）记录数差异 < 5%。  
- ✅ **可复现**：同样本、同配置、同种子重复运行结果一致（误差在统计抖动范围）。  
- ✅ **报告完备**：`alignment_audit.md`、`ab_summary.md`、`report_consistency.md` 与运行元数据齐全。

---

## 8. 质量与兼容性约束
- **时间戳**统一毫秒（ms）；**时区**统一 `Asia/Tokyo`；**切日口径**一致。  
- **配置 SSOT**：YAML 为唯一权威，所有 CLI/ENV 覆写需落库为“实际生效配置”。  
- **幂等与确定性**：脚本与配置可重复；新增字段/参数必须在 `schema_maps.yaml` 与 `SCHEMA.md` 登记默认值与校验规则。  
- **性能中立**：一致性阶段不以吞吐为目标，但需记录 I/O 对节奏的影响以供后续优化。

---

## 9. CLI 样例（可直接在 Cursor 运行）
```bash
# 一致性基线跑样（10~20 分钟）
python scripts/run_stage1_optimization.py --config config/stage1_consistency.yaml --minutes 20

# A/B 对照（A=active+shadow+null sink；B=现有配置）
python scripts/run_stage1_optimization.py --config config/stage1_shadow.yaml --minutes 15

# Gate 统计与对齐审计
python scripts/collect_gate_stats.py --in runtime/artifacts/gate_stats.jsonl --out runtime/reports/report_consistency.md
python scripts/audit_alignment.py --out runtime/reports/alignment_audit.md
```

---

## 10. 变更与回滚策略
- 若 A 组显著优于 B 组：冻结 B 组中触发异常的护栏为 **shadow**，分阶段再收紧；
- 若活动度估算偏差过大：`require_activity=false` 保持关闭，记录影响评估并计划真实注入路径；
- 若对齐修复后交易频率异常：暂以 `dedup_window_ms: 250`、`cooldown_secs: 0.6` 保持稳定，待下一任务卡（参数优化）处理。

---

## 11. Cursor 提示词（可直接粘贴）
> 读取 `config/stage1_consistency.yaml` 并设置 `V13_REPLAY_MODE=1`，对 10–20 分钟样本跑回放；产出 `gate_stats.jsonl`；再用 `config/stage1_shadow.yaml` 跑 A/B，对比确认节奏、gate top-k、lag 分位、spread 分布、活动度覆盖率；将结果写入 `alignment_audit.md`、`ab_summary.md`、`report_consistency.md` 并归档到 `runtime/`。**禁止**修改融合/防抖等策略参数。注意：使用现有的 `scripts/run_stage1_optimization.py`，不要重新写代码。

---

### 附：`config/stage1_consistency.yaml`（示例，供落地）
```yaml
strategy_mode:
  dynamic_enabled: false
  fixed_mode: "active"
  activity:
    min_trades_per_min: 120
    min_quote_updates_per_sec: 20
  combine_logic: "OR"

guards:
  require_activity: false
  max_event_lag_sec: { value: 2.0, mode: "shadow" }
  spread_bps_cap: { value: 8.0, mode: "active" }
  dedup_window_ms: 250
  cooldown_secs: 0.6

replay:
  enabled: true
  tz: "Asia/Tokyo"
  cutover: "day"

sink:
  type: "jsonl"
  out_dir: "./runtime"
```

### 附：`config/stage1_shadow.yaml`（示例，A/B 用）
```yaml
# A 组建议：锁定 active + 影子延迟 + null sink
strategy_mode:
  dynamic_enabled: false
  fixed_mode: "active"
  combine_logic: "OR"

guards:
  require_activity: false
  max_event_lag_sec: { value: 2.0, mode: "shadow" }
  spread_bps_cap: { value: 8.0, mode: "active" }
  dedup_window_ms: 250
  cooldown_secs: 0.6

replay: { enabled: true, tz: "Asia/Tokyo", cutover: "day" }

sink: { type: "null", out_dir: "./runtime" }
```
