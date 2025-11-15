# TASK_P3_CONFIRM_FUNNEL_BASELINE.md
# CoreAlgorithm 确认漏斗基线建立任务

## 任务概述

**前置条件**：CoreAlgorithm confirm pipeline 修复已完成（cooldown/软硬护栏/gating语义/漏斗配置）

**目标**：
1. 开启漏斗诊断，重新跑一轮基准数据窗口
2. 建立修复后的 confirm pipeline 性能基线
3. 为 CONFIRM_PIPELINE_TUNING Phase A 提供前后对比基准

**预期产出**：
- `runtime/confirm_funnel_baseline/` 目录下的完整实验结果
- `docs/confirm_funnel_baseline_report.md` 分析报告
- Pre-tuning baseline 数据，供后续调参任务使用

## 任务上下文

### 为什么需要 P3

1. **修复验证**：确认 cooldown/gating/漏斗配置修复没有引入新的拦截
2. **基线建立**：提供 CONFIRM_PIPELINE_TUNING Phase A 的"修复后"对比基准
3. **漏斗体检**：第一次系统性观测 confirm pipeline 的各层拦截情况

### 实验设计原则

- **数据窗口**：使用之前实验的同一批数据（15:59:00Z - 15:59:30Z，376信号）
- **配置**：使用修复后的 `config/core_confirm_tuning_B1.yaml`
- **对比维度**：strict vs ignore_soft 两种 gating 模式
- **诊断输出**：开启 confirm funnel diagnostics（log + json）

## Phase 1: 漏斗诊断实验准备

### 1.1 配置更新

在 `config/core_confirm_tuning_B1.yaml` 中确保：

```yaml
signal:
  # ... 现有配置保持不变 ...

  # === P3: 漏斗诊断配置 ===
  enable_confirm_funnel_diagnostics: true
  funnel_output_mode: "both"  # log + json

  # === 调试保持开启（可选）===
  debug:
    core_confirm_trace: true
```

### 1.2 实验命令准备

**Strict 模式实验**：
```bash
python -m backtest.app \
  --mode A \
  --features-dir deploy/data/ofi_cvd \
  --start 2025-11-15T15:59:00Z \
  --end 2025-11-15T15:59:30Z \
  --config config/core_confirm_tuning_B1.yaml \
  --out-dir runtime/confirm_funnel_baseline/strict \
  --gating-mode strict \
  --run-id confirm_funnel_baseline_strict \
  --consistency-qa
```

**Ignore Soft 模式实验**：
```bash
python -m backtest.app \
  --mode A \
  --features-dir deploy/data/ofi_cvd \
  --start 2025-11-15T15:59:00Z \
  --end 2025-11-15T15:59:30Z \
  --config config/core_confirm_tuning_B1.yaml \
  --out-dir runtime/confirm_funnel_baseline/ignore_soft \
  --gating-mode ignore_soft \
  --run-id confirm_funnel_baseline_ignore_soft \
  --consistency-qa
```

## Phase 2: 实验执行与数据收集

### 2.1 执行实验

按顺序执行上述两个命令，确保：

1. 每次实验完成无错误
2. 输出目录结构完整（signals.jsonl, run_manifest.json 等）
3. 日志中出现 `[CONFIRM_FUNNEL_STATS]` 统计输出

### 2.2 关键输出文件收集

**每个实验产出**：
- `runtime/confirm_funnel_baseline/{mode}/run_manifest.json`
- `runtime/confirm_funnel_baseline/{mode}/signals.jsonl`
- `runtime/confirm_funnel_baseline/{mode}/confirm_funnel_stats.json` ⭐ **重点**
- `runtime/confirm_funnel_baseline/{mode}/gating_qa_summary.json`

**日志中的统计**：
```
[CONFIRM_FUNNEL_STATS] 确认漏斗统计:
  总信号数: XXX
  弱信号过滤通过: XXX (XX.X%)
  一致性过滤通过: XXX (XX.X%)
  候选确认: XXX (XX.X%)
  反向防抖拦截: XXX (XX.X%)
  最终确认: XXX (XX.X%)
```

## Phase 3: 结果分析与基线建立

### 3.1 修复前后对比

**对比维度**：
- 修复前（confirm_tuning_B1_fixed）：376信号，0交易
- 修复后（本实验）：预期相近，但漏斗统计更详细

**重点检查**：
1. `confirm_true_rate` 是否在合理区间（预期 1-2%）
2. `reverse_prevention_blocked` 是否符合连击确认逻辑
3. `consistency` 分布是否正常（90%在[0,0.05)区间）

### 3.2 模式对比分析

**Strict vs Ignore_Soft**：
- 信号总数应该相同
- `confirm_true` 数量应该相同（confirm 不受 gating_mode 影响）
- `passed_signals` 应该不同（ignore_soft 会放行更多软护栏）

### 3.3 基线数据保存

创建 `docs/confirm_funnel_baseline_report.md`：

```markdown
# Confirm Funnel Baseline Report

## 实验配置
- 数据窗口：2025-11-15T15:59:00Z - 2025-11-15T15:59:30Z
- 信号总数：376
- 配置：core_confirm_tuning_B1.yaml（修复后版本）

## 关键指标

### Strict 模式
- confirm_true_rate: X.X%
- 各层拦截统计：
  - 弱信号过滤通过: XX (XX.X%)
  - 一致性过滤通过: XX (XX.X%)
  - 候选确认: XX (XX.X%)
  - 反向防抖拦截: XX (XX.X%)
  - 最终确认: XX (XX.X%)

### Ignore_Soft 模式
- confirm_true_rate: X.X%
- 各层拦截统计：...

## 结论
- 修复效果验证：✅/❌
- 基线数据完整性：✅/❌
- 建议进入 CONFIRM_PIPELINE_TUNING Phase A：是/否
```

## Phase 4: 文档更新与任务衔接

### 4.1 更新 CONFIRM_PIPELINE_TUNING 任务卡

在 `TASK_CONFIRM_PIPELINE_TUNING_CoreAlgorithm_confirm阈值与护栏优化.md` 中：

1. **Phase A 状态更新**：
   ```
   Phase A ✅ 已完成（P3基线建立）
   - 修复后基线已建立
   - 漏斗统计机制验证正常
   ```

2. **Phase A 实验数据**：
   - 记录本次 P3 的 confirm_true_rate
   - 记录各层拦截比例
   - 作为 Phase A 阈值调优的"前"基准

### 4.2 任务状态总结

**P3 任务完成标志**：
- ✅ 两个实验都成功运行
- ✅ confirm_funnel_stats.json 文件生成
- ✅ 分析报告完成
- ✅ CONFIRM_PIPELINE_TUNING 任务卡已更新衔接

**进入下一阶段条件**：
- 漏斗统计显示系统正常（无意外拦截）
- 基线数据完整可靠
- Phase A 实验设计清晰

## 风险与注意事项

1. **数据一致性**：确保使用完全相同的输入数据
2. **配置一致性**：实验间只有 gating_mode 不同
3. **诊断输出**：确认漏斗统计正确输出到文件和日志
4. **性能影响**：diagnostics开启会略微增加运行时间

## 验收标准

- [ ] 两个实验成功完成，无错误
- [ ] confirm_funnel_stats.json 正确生成
- [ ] 分析报告完成，包含前后对比
- [ ] CONFIRM_PIPELINE_TUNING 任务卡已更新
- [ ] 基线数据可用于后续调参任务

---

# TASK_CONFIRM_PIPELINE_TUNING — Phase C

CoreAlgorithm Confirm 语义与阈值优化

## 0. 元信息（Meta）

- **Task ID**: `TASK_CONFIRM_PIPELINE_TUNING_PHASE_C`
- **归属上游任务**: `TASK_CONFIRM_PIPELINE_TUNING`
- **状态**: TODO
- **Owner**: Core / Strategy
- **前置依赖**:
  - ✅ P1/P2：core_algo confirm bug 修复（cooldown/gating/漏斗诊断）
  - ✅ P3：confirm_funnel_baseline 基线已生成
    - `runtime/confirm_funnel_baseline/.../confirm_funnel_stats.json`
    - `docs/confirm_funnel_baseline_report.md`

---

## 1. 背景简述

当前我们已经有：

1. **v1 confirm**：
   - 逻辑过于保守，`confirm_true_rate ≈ 1–2%`，大部分信号被 `weak_signal + low_consistency` 拦截。

2. **v2 confirm（修复后基线，P3）**：
   - 在测试窗口中 `confirm_true_rate ≈ 23.9%`（strict / ignore_soft 一致）。
   - 一致性过滤实际通过率仅 ~2.4%，说明 v2 confirm 在设计上绕过了 `low_consistency` 软护栏。

这两个极端给我们提供了确认的**"左/右边界"**：

- v1：**极严**，保证质量但几乎没有交易量；
- v2（当前）：**偏松**，有交易量但质量护栏形同虚设。

**本 Phase C 的目标**：
在这两端之间，找到一套 **confirm 语义 + 阈值组合**，使：

- `confirm_true_rate ∈ [5%, 15%]`（可微调，但需明显低于 24%，高于 1–2%）；
- 软护栏（weak_signal / low_consistency）仍然参与质量控制，而不是完全被绕过；
- 保证 BUY/SELL 双向都有一定数量的 `confirm=True` 信号。

---

## 2. 任务目标（Goals）

1. **G1 — 明确 confirm_v2 的业务语义**
   - 明确区分：
     - 硬护栏（hard_block）：warmup / cooldown / spread / lag / kill_switch / reverse_prevention…
     - 质量护栏（quality_guard）：weak_signal / low_consistency…
   - 在代码中实现一个**显式分档逻辑**：
     - strong / normal / weak 三档信号；
     - 每档对应不同的 confirm 条件。

2. **G2 — 在 v1/v2 边界之间找到合理参数区间**
   - 以现基线（v1 极严 / v2 偏松）为左右两端 anchor；
   - 通过调整 `weak_signal_threshold` / `consistency_min` / strong 阈值等，找到 2–3 套候选参数：
     - conservative
     - balanced
     - aggressive（但不要回到 24% 那么高）

3. **G3 — 输出可用于回测/评估的质量标签**
   - 在信号层输出 `quality_tier` / `quality_flags`；
   - 为后续评估 PnL 时做分层分析（strong-only / balanced / aggressive）。

---

## 3. 工作内容分解

### C1. Confirm 语义重构（硬护栏 / 软护栏 / 分档）

**目标**：在 CoreAlgorithm / DecisionEngine 中，把 confirm_v2 的语义写清楚、写死，不再是"只要不是 hard 就直接 confirm"。

#### C1.1 代码定位

- `core_algo.py`
  - v1 confirm pipeline 实现位置
  - v2 confirm 相关的 gating / confirm_mode 分支
- `decision_engine.py`
  - v2 决策逻辑（DecisionCode / Reason / gating / confirm）

#### C1.2 分层语义设计

在设计文档 + 代码里明确三类信息：

1. **hard_block（硬护栏，必杀）**
   - 条件（示例）：
     - warmup
     - cooldown_after_exit(...)
     - spread_bps > spread_threshold
     - lag_sec > lag_threshold
     - kill_switch
     - reverse_prevention（反向防抖阻塞）
   - 语义：
     - 命中 hard_block ⇒ `confirm=False` 且 `gating=0`（v2 模式）
     - 不允许任何模式绕过

2. **quality_guard（质量护栏 / 软）**
   - 条件（示例）：
     - weak_signal（abs(score) < weak_signal_threshold）
     - low_consistency（consistency < consistency_min）
   - 语义：
     - 不直接决定 `gating`（在 v2 模式下）；
     - 参与 confirm 的决策逻辑；
     - 同时写入 `quality_flags`。

3. **strong / normal / weak 分档**

根据当前 config 中的阈值（可复用现有 thresholds）定义三档：

```text
- strong: |score| >= strong_threshold
- normal: weak_threshold <= |score| < strong_threshold
- weak:   |score| <  weak_threshold
```

对应策略：

**strong 档**：
- 只要 not hard_block ⇒ 可以 confirm=True
- 即使有 low_consistency / weak_signal，只做打标，不 kill

**normal 档**：
- 需要：not hard_block AND not weak_signal AND consistency >= consistency_min

**weak 档**：
- 统一 confirm=False，并记录 weak_signal_throttle

实现要求：

以上逻辑要以函数或清晰的 if 结构固化在代码中，并在注释中写清楚 trigger 条件与语义。

#### C1.3 信号结构扩展

在 v2 信号中新增字段（建议）：

- `quality_tier`: "strong" | "normal" | "weak"
- `quality_flags`: List[str]（例如 ["low_consistency"]）

修改：
- `core_algo.py` v2 path 中构造 SignalV2 的地方；
- `signal_schema.py` 中的 SignalV2 schema（如有需要，可做为可选字段）。

---

### C2. 参数搜索：在 v1/v2 之间收敛目标区间

目标：利用 v1/v2 作为极端，对 weak_signal_threshold / consistency_min / strong 阈值做小范围扫描，找到 2–3 套候选配置。

#### C2.1 固定条件

使用与 P3 相同或更大一点的代表性数据窗口；

保持：
- symbol / 交易对不变（例如 BTCUSDT）
- backtest 配置不变（回放速度 / minutes / mode 等）
- strategy_mode / gating_mode 使用 strict（必要时附带 ignore_soft 做对照）

#### C2.2 调整的配置项

在 signal config（或 core config）中定义一个「参数组」列表，例如：

```yaml
confirm_tuning_profiles:
  - name: "C2_conservative"
    weak_signal_threshold: 0.15
    consistency_min: 0.10
    strong_threshold: 1.0
  - name: "C2_balanced"
    weak_signal_threshold: 0.12
    consistency_min: 0.08
    strong_threshold: 0.9
  - name: "C2_aggressive"
    weak_signal_threshold: 0.10
    consistency_min: 0.05
    strong_threshold: 0.8
```

要求：
- 要覆盖从接近 v1（极严）到接近当前 v2（偏松）的区间；
- 每个 profile 单独运行一次回放，记录漏斗统计。

#### C2.3 实验执行

对每个 profile，执行：
- 启动 backtest / replay（strict 模式）；
- 打开漏斗诊断：
  ```yaml
  enable_confirm_funnel_diagnostics: true
  funnel_output_mode: "json" 或 "both"
  ```
- 收集输出：
  - `runtime/confirm_funnel_tuning/<profile_name>/confirm_funnel_stats.json`
  - （可选）导出简单 markdown 报告 `docs/confirm_tuning_<profile_name>.md`

#### C2.4 评估维度

对每个 profile 统计并记录：

- `confirm_true_rate`（strict 模式）
- 总交易笔数（按回放窗口标准化到每小时）
- BUY/SELL 比例（confirm=True 的方向分布）
- `quality_tier` 分布（strong/normal/weak 各占比）
- 主要 soft_guard 命中分布：
  - weak_signal
  - low_consistency

目标是选出 2–3 个「站得住脚」的候选配置：
- conservative：confirm_true_rate ~ 5% 左右；
- balanced：confirm_true_rate ~ 8–12%；
- aggressive：confirm_true_rate ~ 12–15%（但不过度偏向单边）。

---

### C3. 将质量维度接入回测（前置集成）

目标：为后续 PnL 评估准备基础，使回测可以按质量档位做分层统计。

#### C3.1 StrategyEmulator / Backtest 集成

在回测端（如 StrategyEmulator / BacktestAdapter）中：
- 接收 v2 信号的 `quality_tier` / `quality_flags` 字段；
- 增加可选配置项：
  ```yaml
  quality_mode: "conservative" | "balanced" | "aggressive" | "all"
  ```

按 quality_mode 决定是否执行交易：
- conservative：只允许 quality_tier == "strong"
- balanced：允许 strong + normal 且无 low_consistency
- aggressive：所有 confirm=True 的信号均允许

#### C3.2 验证集成正确性

在小窗口下：
- 分别以不同 quality_mode 跑一次回测；
- 确认：
  - 交易笔数随模式递增；
  - 底层 confirm 漏斗统计不变（只改变执行层过滤逻辑）。

注意：Phase C 不要求完成完整 PnL 分析，只需完成质量维度接入与基本 sanity check。

---

## 4. 输出物（Deliverables）

### 代码层面

更新后的 `core_algo.py` / `decision_engine.py`：
- 明确的 hard_block / quality_guard 分层；
- 三档 quality_tier 策略；
- confirm_v2 逻辑实现与注释。

更新后的 `signal_schema.py`（如新增字段）；

回测端对 `quality_tier` / `quality_flags` 的集成代码。

### 配置与实验数据

`config/signal/confirm_tuning_profiles.yaml`（或同等文件）；

`runtime/confirm_funnel_tuning/<profile>/confirm_funnel_stats.json`；

如有必要，生成简短对比报告：
- `docs/confirm_tuning_summary.md`

### 文档

在 `TASK_CONFIRM_PIPELINE_TUNING_CoreAlgorithm_confirm阈值与护栏优化.md` 中追加 Phase C 进展与决策结果；

简短说明：
- 最终推荐使用的 profile（conservative/balanced/...）；
- 其 confirm_true_rate / 交易数 / BUY/SELL / 质量分布。

---

## 5. Definition of Done（DoD）

当满足以下条件时，本 Phase C 任务可视为完成：

**DoD-1 — confirm 语义清晰可读**
- 代码中有清晰注释说明：
  - 硬护栏列表；
  - 质量护栏列表；
  - strong/normal/weak 的划分与 confirm 条件。
- 任何新加入的开发者能在 5 分钟内读懂 confirm 的决策流程。

**DoD-2 — 取得候选参数集**
- 至少产出 2–3 组候选配置（conservative/balanced/aggressive），每组都有对应漏斗统计；
- 其中至少 1 组满足：
  - confirm_true_rate ∈ [5%, 15%]；
  - BUY/SELL 均有显著 confirm=True 信号；
  - soft_guard（weak/low_consistency）仍有分布，不是完全闲置。

**DoD-3 — 质量维度接入回测**
- 回测可以按 quality_mode 分档执行（conservative/balanced/aggressive/all）；
- 在不同 quality_mode 下：
  - confirm_funnel 统计不变；
  - 交易笔数有合理分层。

**DoD-4 — 文档更新**
- TASK_CONFIRM_PIPELINE_TUNING 主文档更新 Phase C 状态；
- confirm_funnel_baseline_report.md 中加入一节：
  - 描述 Phase C 后 confirm 行为的变化及选中配置的理由。
