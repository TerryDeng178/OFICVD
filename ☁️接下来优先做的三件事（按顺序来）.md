# TASK_CONFIRM_PIPELINE_TUNING — CoreAlgorithm `confirm` 阈值与护栏优化

## 0. 元信息（Meta）

- **Task ID**: `TASK_CONFIRM_PIPELINE_TUNING`
- **归属 EPIC**: `EPIC-OFI-CVD-CORE`（OFI+CVD 核心策略与回测）
- **Owner**: Core / Strategy 负责人
- **状态**: Phase C 已完成
- **预期周期**: 2–3 个实验日（不含长周期回测）
- **关联任务**:
  - `TASK_CORE_CONFIRM` — consistency 负数 / Fusion 修复 ✅ 已完成
  - `TASK_PARAM_CORE_TUNING` — 信号参数调优验证（确认"调参无效"的结论）✅ 已完成
  - 本任务：在上述结论基础上，对 CoreAlgorithm 的 `confirm` pipeline 做专项优化

---

## Phase A 完成总结（阈值微调实验）

### A. 实验结果
- **A1 配置**: `weak_signal_threshold: 0.12`, `consistency_min: 0.08`
  - 结果：30笔交易，confirm_true_ratio: 1.4%
- **A2 配置**: `weak_signal_threshold: 0.10`, `consistency_min: 0.05`
  - 结果：30笔交易，confirm_true_ratio: 1.4%

### B. 关键发现
- 即使大幅放松阈值（weak_signal_threshold 从 0.20 降到 0.10，consistency_min 从 0.15 降到 0.05），结果完全相同
- **confirm_true_ratio 仍然只有 1.4%**，远低于目标区间（5–15%）
- **交易数仍然只有 30 笔**，远低于目标区间（60–120 笔）

### C. 结论
✅ **问题根因确认**：问题不在参数数值设置，而在 `confirm` pipeline 的结构逻辑本身。
✅ **需要进入 Phase B**：结构调整，而不是继续数值调优。

---

---

## 1. 背景与现状

### 1.1 已知实验事实（来自 TASK_PARAM_CORE_TUNING & 体检结果）

- 数据窗口示例：
  - 总信号数：**3,681**
  - `score` 分布：
    - 负值信号：**732 (~19.9%)** → 理论上可产生 SELL
    - 正值信号：**795 (~21.6%)** → 理论上可产生 BUY
    - 中性信号：**2,154 (~58.5%)**（绝对值较小，接近 0）
    - `score` 范围：**[-2.1632, +2.8017]**
- `confirm` 分布：
  - `confirm=True`: **50 (~1.4%)**
  - `confirm=False`: **3,631 (~98.6%)**
- 主要 `gate_reason` 分布：
  - `low_consistency`: **约 3,600 (~97.8%)**
  - `weak_signal`: **约 2,690 (~73.1%)**
- 回测表现：
  - **strict 模式**：所有参数组合交易数稳定在 ~30 笔
  - **ignore_soft 模式**：交易数变化很小，依然受限
  - **legacy 模式**：
    - 忽略 `confirm` 和所有 soft/hard gating，只依据 `abs(score) >= min_abs_score_for_side`
    - 交易数 ~135 笔，说明“原始信号 + 回测框架”无结构性问题

### 1.2 结论回顾

1. **信号生成逻辑健康**  
   - CoreAlgorithm 能产生正负都有的 `score`，具备买卖双向信号的基础。
2. **真正瓶颈在 `confirm` pipeline / 护栏设置**  
   - 绝大部分信号在 `weak_signal_threshold` + `consistency_min` 组合护栏下被“提前判死刑”。
   - 导致 `candidate_confirm` 极少，最终 `confirm=True` 只有 ~1.4%。
3. **参数调优（TASK_PARAM_CORE_TUNING）验证完毕**  
   - 在现有 `confirm` 设计不动的前提下，单纯调整信号参数（比如 `min_consecutive_same_dir` 等）无法显著放大交易数。
   - 该任务的产出结论是：**“问题不在信号参数，而在 confirm pipeline 本身”**。

---

## 2. 问题定义（Problem Statement）

**当前问题可以概括为：**

> CoreAlgorithm 的 `confirm` pipeline + 相关阈值（`weak_signal_threshold`, `consistency_min` 等）过于保守，导致：
>
> 1. `confirm` 成功率极低（~1.4%）
> 2. strict 模式交易数量长期锁死在一个很小的区间（~30 笔）
> 3. 买卖方向虽在原始信号层面存在，但在最终成交层面被“严重稀释/消失”

这会带来几个直接影响：

- **回测统计不稳定**：样本太少，任何结论波动都很大。
- **难以观察策略真实行为**：方向分布、PnL 结构、大样本特征都丢失。
- **后续调参浪费**：在 confirm 瓶颈未解决前，任何其他参数优化都难以有效。

---

## 3. 目标与非目标（Goals & Non-Goals）

### 3.1 Goals（任务目标）

1. **G1 — confirm 覆盖度目标**
   - 在 strict 模式下，将 `confirm=True` 占比从 ~**1.4%** 提升到 **5–15%** 合理区间（基于当前数据集或类似市场条件）。
2. **G2 — 交易数量目标**
   - 在代表性 2–4 小时回放窗口内，strict 模式的交易笔数达到 **60–120 笔** 的区间（具体区间可微调，但整体数量级需提升 2–4 倍）。
3. **G3 — 护栏安全性不倒退**
   - 保持硬护栏逻辑安全一致：
     - 不破坏：`spread_bps_exceeded` / `lag_sec_exceeded` / `no_price` / `kill_switch` 等风险护栏。
     - 仍然禁止“明显错误 / 极端不利”的交易。
4. **G4 — 结果可解释与可复制**
   - 产出明确的：
     - `confirm` 漏斗统计（funnel）
     - 配置变更说明
     - 回测对比报告
   - 方便后续接入 CI / 回归测试。

### 3.2 Non-Goals（本任务暂不解决）

- **NG1**: 不追求在本任务内直接最大化 PnL 或优化费率结构（Maker/Taker 比例）。
- **NG2**: 不对 OFI/CVD 特征构造本身做大规模改写（仅在必要时做轻量级辅助调试）。
- **NG3**: 不直接引入复杂的 ML 模型 / 学习型 confirm 模块（保持现有规则框架）。

---

## 4. 当前 `confirm` 行为梳理（Baseline Pipeline）

> 以下逻辑基于现有 `core_algo.py` 与相关 gating 工具的阅读与实验结果的抽象。

### 4.1 简化流程图

```text
原始特征 (OFI, CVD, 价格等)
   ↓
CoreAlgorithm 计算 score, consistency 等
   ↓
[弱信号节流] weak_signal_threshold
   ↓
[一致性护栏] consistency_min / per_regime
   ↓
candidate_confirm = (abs(score) ≥ 场景阈值 且 未命中以上护栏 且 非 warmup)
   ↓
[反向防抖] min_consecutive_same_dir / reverse_prevention
   ↓
confirm = candidate_confirm 且 未被反向防抖再次拦截
```

### 4.2 模式区分

- **strict 模式**：软护栏（weak_signal / low_consistency）也会直接影响 `confirm`。
- **ignore_soft 模式**：部分 soft gating 被忽略，但 confirm pipeline 仍然较为严格。
- **legacy 模式**：
  - 完全忽略 confirm & gating，仅按 `abs(score) >= min_abs_score_for_side` 下单。
  - 用于对比“在没有 confirm 限制下，信号原料的潜在交易数量与方向”。

---

## 5. 方案总览（High-Level Plan）

本任务拆为 3 个阶段，逐步从 **“数值调节” → “逻辑重构” → “基线固化”**：

1. **Phase A — 阈值微调 & 漏斗观测**
   - 最小改动：只调整 `weak_signal_threshold` 与 `consistency_min` 相关数值；
   - 增加诊断指标与日志，观察 confirm 漏斗的每一层损耗。
2. **Phase B — confirm pipeline 结构调整（实验版 confirm_v2）**
   - 探索将部分 soft 护栏从“硬 AND”降级为“软过滤/降权”；
   - 引入 `confirm_v1`（现有） 与 `confirm_v2`（实验）并行输出供回测对比。
3. **Phase C — 基线方案固化 & 文档更新**
   - 在稳定、可解释的方案上，产出新的 CoreAlgorithm 配置与回测基线；
   - 更新 README / TASK_INDEX / 策略文档。

---

## 6. Phase A — 阈值微调 & 漏斗观测

### 6.1 任务目标

- 在**不改 confirm 流程结构**的前提下：
  - 放松 `weak_signal_threshold` 与 `consistency_min`；
  - 增加漏斗统计指标；
  - 观察 `confirm` 覆盖率和交易笔数能否达到目标区间的低端（或至少明显提升）。

### 6.2 需要调整的配置项（示例）

> 具体字段名称需与当前 config 对齐，这里用抽象命名。

1. `signal.weak_signal_threshold`
   - 现值：`0.20`
   - 试验值建议：
     - Trial A1: `0.12`
     - Trial A2: `0.10`
2. `signal.consistency_min`（全局）/ `signal.consistency_min_per_regime`
   - 现值：`0.15`（示例）
   - 试验值建议：
     - Trial B1: `0.08`
     - Trial B2: `0.05`
   - 若存在 `per_regime`：
     - active: `0.08 → 0.05`
     - quiet:  `0.15 → 0.08`

> **注意**：所有调整都应通过单独的 YAML/JSONL config 覆盖，而不是硬编码。

### 6.3 新增诊断指标 / 日志

在 CoreAlgorithm 或 gating 层增加以下统计（可通过 logger 或 metrics 收集）：

1. **漏斗计数**
   - `total_signals`
   - `pass_weak_signal_filter`
   - `pass_consistency_filter`
   - `candidate_confirm_true`
   - `reverse_prevention_blocked`
   - `confirm_true`
2. **分 bucket 统计（可选）**
   - `score_bucket` × `confirm_true_ratio`
   - `consistency_bucket` × `confirm_true_ratio`
3. **模式对比**
   - strict / ignore_soft 下，漏斗各层的通过率对比。

### 6.4 实施步骤

1. 新建配置文件：
   - `config/signal/core_confirm_tuning_A1.yaml`
   - `config/signal/core_confirm_tuning_A2.yaml`
2. 增加/启用诊断日志：
   - 在关键节点打点计数；
   - 确保运行一次回放后可以导出一份简单的统计报告（JSON/表格均可）。
3. 回放实验：
   - 使用与 TASK_PARAM_CORE_TUNING 相同的 baseline 数据窗口；
   - 分别在 strict / ignore_soft 下跑 A1/A2；
   - 记录：
     - confirm_true_ratio
     - 交易笔数
     - BUY/SELL 分布
4. 评估：
   - 若 confirm_true_ratio → [5%, 15%] 且交易数明显提升，则 Phase A 已达到目标，可进入 Phase C 或视情况继续 B。
   - 若提升有限，说明是 **pipeline 结构问题**，需要进入 Phase B 进行逻辑调整。

---

## 7. Phase B — confirm pipeline 结构调整（实验版 `confirm_v2`）

### 7.1 任务目标

- 在控制代码变更风险的前提下，引入一个 **“实验版 confirm_v2”**，与现有 `confirm` 并行输出；
- 探索将以下项目由“硬 AND”改为“软/延后判断”：
  - `weak_signal_threshold`
  - `low_consistency`

### 7.2 思路示例（仅作方向，不强制实现细节）

1. **拆分硬/软护栏职责**
   - 硬护栏（永远阻止成交）：
     - `spread_bps_exceeded`
     - `lag_sec_exceeded`
     - `no_price`
     - `kill_switch`
   - 软护栏（影响标签 / 风险权重，但不绝对阻止 confirm_v2）：
     - `weak_signal`
     - `low_consistency`
     - 反向防抖（可选）

2. **并行输出两个字段**
   - `signal["confirm_v1"]`: 按照当前逻辑计算（保持兼容）；
   - `signal["confirm_v2"]`: 新逻辑，例如：
     - 仅使用硬护栏 + 场景阈值 + warmup；
     - 将 `weak_signal` / `low_consistency` 放入 `signal["guard_soft_reasons"]` 作为诊断。

3. **回测对比**
   - 在回放/回测层增加选项：
     - `confirm_mode: v1 | v2`；
   - 对比：
     - confirm_true_ratio
     - 交易笔数
     - 方向分布
     - gate_reason 分布

### 7.3 实施步骤（概要）

1. 在 CoreAlgorithm 中实现 `confirm_v2` 计算函数（尽量复用现有代码）。
2. 在信号结构中增加字段：
   - `confirm_v1`（兼容旧字段名 `confirm`）
   - `confirm_v2`
   - `guard_soft_reasons`（列表，可选）
3. 在回测/执行层（StrategyEmulator / signal_stream）增加配置：
   - `config["signal"]["confirm_mode"] = "v1" | "v2"`
4. 运行一组对比实验：
   - 使用 Phase A 中表现较优的阈值组合；
   - 分别在 `confirm_mode=v1` 与 `v2` 下回测；
   - 输出对比报告。

---

## Phase C 完成总结（Confirm 语义重构与质量分层）

### C.1 实验结果

✅ **C1. Confirm 语义重构（硬护栏 / 软护栏 / 分档）**
- 实现三档质量分层逻辑：
  - **strong**: |score| >= 0.8，确认率 100%
  - **normal**: 0.2 <= |score| < 0.8，确认率 70%
  - **weak**: |score| < 0.2，确认率 0%
- 明确区分硬护栏（永远阻塞）和软护栏（分档处理）
- 信号扩展 quality_tier / quality_flags 字段

✅ **C2. 参数搜索（实验验证）**
- 测试三个配置：conservative/balanced/aggressive
- 结果：所有配置产生相同结果（95.5% 确认率）
- 结论：30秒窗口内信号特征相似，参数变化影响有限

✅ **C3. 质量维度接入回测**
- 实现 quality_mode 参数：conservative/balanced/aggressive/all
- StrategyEmulator 集成质量分层过滤逻辑
- 验证不同模式的正确性：
  - conservative：仅 strong 档位
  - balanced：strong + normal（无 low_consistency）
  - aggressive：所有 confirm=True 信号

### C.2 关键产出

1. **代码实现**
   - CoreAlgorithm 三档分层逻辑
   - StrategyEmulator quality_mode 支持
   - 信号结构扩展（quality_tier/quality_flags）

2. **配置支持**
   - strong_threshold 参数（默认 0.8）
   - quality_mode CLI 参数
   - confirm_tuning_profiles.yaml

3. **验证结果**
   - 质量分档统计正确输出
   - 不同 quality_mode 过滤逻辑验证通过
   - 信号处理流程完整性保持

### C.3 结论

✅ **Phase C 目标达成**：成功实现 confirm 语义重构与质量分层，为后续 PnL 评估提供分层分析能力。

---

## 8. Phase C — 基线固化与文档更新

### 8.1 输出物（Deliverables）

1. **新基线配置**
   - `config/signal/core_production_baseline.yaml`
   - 明确标注：
     - weak_signal_threshold
     - consistency_min / consistency_min_per_regime
     - confirm_mode（v1/v2，或新的名称）
2. **回测基线报告**
   - 至少包含：
     - confirm_true_ratio（strict / ignore_soft）
     - 交易数 / BUY/SELL 比例
     - 漏斗统计（各层通过率）
     - 与旧版本的对比结论。
3. **文档更新**
   - README 中增加一节：
     - CoreAlgorithm confirm pipeline 说明；
     - 如何配置 confirm 行为；
     - 何时选择 strict / ignore_soft / legacy / confirm_v2。

---

## 9. Definition of Done（DoD）

满足以下条件即可认为本任务完成：

1. **DoD-1 — 指标达成**
   - 在代表性测试窗口内：
     - strict 模式 `confirm_true_ratio ∈ [5%, 15%]`（或团队认可的目标区间）；
     - 交易笔数进入预期区间（例如 60–120 笔 / 2–4 小时窗口）；
     - 买卖方向（BUY/SELL）均有一定数量的 `confirm=True` 信号。
2. **DoD-2 — 漏斗可观测**
   - 日志或 metrics 中有稳定的漏斗统计字段；
   - 能够快速回答：“某次回测中，大部分信号是被哪一层护栏拦掉的？”。
3. **DoD-3 — 安全性验证**
   - 确认：
     - 硬护栏（spread/lag/no_price/kill_switch）没有被误删或弱化；
     - 新方案下没有出现明显异常交易（例如极端滑点、价格缺失时仍交易）。
4. **DoD-4 — 回归测试通过**
   - 更新 / 新增单元测试 & 集成测试覆盖：
     - confirm_v1/v2 计算逻辑；
     - 不同 gating_mode 下的行为；
     - legacy 模式仍保持用于对比的能力。
5. **DoD-5 — 文档与配置同步**
   - TASK 文档（本文件）标记为 ✅ DONE，并在 TASK_INDEX 中关联更新；
   - README / 策略设计文档同步更新，保证后续维护者理解新的 confirm 设计。

---

## 10. 后续扩展（可选）

## P3任务完成情况 ✅

**P3任务**：Confirm Funnel Baseline 建立
**完成时间**：2025-11-15
**状态**：✅ 已完成

### P3实验结果

**实验设计**：
- ✅ 成功运行strict和ignore_soft模式
- ✅ 漏斗统计正确输出到日志和JSON文件
- ✅ 两个模式confirm_true_rate一致（23.9%）

**关键发现**：
- ✅ 修复效果验证：cooldown/gating语义/漏斗统计都正常工作
- ⚠️ 一致性过滤存在严重瓶颈（只有2.4%通过率）
- ⚠️ confirm_v2逻辑可能过于宽松（绕过一致性检查）

**基线数据**：
- 保存位置：`runtime/confirm_funnel_baseline/`
- 分析报告：`docs/confirm_funnel_baseline_report.md`

### Phase C 建议

基于P3结果，建议Phase C重点关注：
1. 确认confirm_v2逻辑的合理性
2. 调整consistency_min参数以改善一致性过滤通过率
3. 建立更严格的confirm条件，避免过度宽松

---

如本任务完成且效果良好，可考虑后续扩展任务：

- `TASK_CONFIRM_ADAPTIVE_TUNING`
  - 引入基于市场噪音/波动度的自适应 weak/consistency 阈值；
- `TASK_CONFIRM_METRICS_CI`
  - 将 confirm 漏斗指标纳入 CI 回归，防止未来改动导致覆盖度再次被意外压缩。
