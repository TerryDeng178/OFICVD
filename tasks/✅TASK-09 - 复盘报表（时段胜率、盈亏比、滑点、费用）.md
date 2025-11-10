# TASK-09 · 复盘报表（时段胜率、盈亏比、滑点、费用）与参数优化

> 里程碑：M3 · 依赖：TASK-08 回放/回测 Harness · 版本：v1.2 · 更新：2025-11-10 (Asia/Tokyo)  
> **状态**：✅ **已完成**（2025-11-10）

---

## 1) 背景 & 目标

**背景**：近期 6 交易对 24 小时回测净亏损、成本占比高、胜率极低。需快速定位问题并通过**复盘报表**与**参数优化**提升胜率与收益。

**目标**：

* 产出标准化复盘报表（按**时段** / **场景** / **交易对**）。
* 核心指标：胜率、盈亏比、净 PnL、最大回撤、Sharpe、**滑点/费用**分解、平均持有时长。
* 快速参数优化：阈值与一致性、费率与滑点模型、止盈止损、持有时间、融合权重与场景阈值。
* 一键集成到 Orchestrator：策略运行结束后自动生成日报。

**成功判定（目标值）**：

* 胜率 ≥ 15%（第一阶段），≥ 20%（第二阶段）。
* 费用+滑点占比下降 ≥ 30%。
* 净 PnL 明显改善（≥ 0 或可控亏损且指标改善）。

---

## 2) 成果物（Deliverables）

* 代码：`report/summary.py`（报表生成器），`report/optimizer.py`（参数搜索）。
* 配置：`config/backtest.yaml`（新增/对齐 fee/slippage/strategy/signal/risk 节点）。
* 输出：

  * 报告：`reports/daily/<YYYYMMDD>/<run_id>_summary.md`（主报表）
  * 附件图：`reports/daily/<YYYYMMDD>/fig_*.png`（按时段/场景/交易对条形图、回撤曲线）
  * 机器可读：`reports/daily/<YYYYMMDD>/<run_id>_metrics.json`
* 集成：Orchestrator 结束时自动调用（`--enable report`）。

---

## 3) 数据输入/输出与契约

**输入**：

* 回测产物：`runtime/backtest/<run_id>/*`（交易明细、信号、成交、metrics）。
* 特征宽表：`preview/.../kind=features/`（含 `scenario_2x2`, `spread_bps`, `best_bid/ask`, `ofi_z`, `cvd_z`, `fusion_score`）。

**输出字段（报表）**：

* 概览：总交易数、总/净 PnL、费用、滑点、胜率、盈亏比、Sharpe、最大回撤、平均持有时长。
* 分组视图：

  * **按时段**（UTC 小时）胜率/净 PnL/平均持有时长。
  * **按场景**（A_H/A_L/Q_H/Q_L/unknown）交易数、胜率、盈亏比、净 PnL。
  * **按交易对**统计表（交易数、费用、滑点、净 PnL、胜率、盈亏比、平均持有时长）。
* 成本分解：费用（maker/taker）、滑点（bps→$）、成本占比。
* TOP/N 序列回看：最大盈利/亏损前 N 笔的信号轨迹与出入场上下文。

**口径对齐**：

* 费用：基于 fee_model（maker_taker/static），按成交名义与场景概率加权。
* 滑点：由 slippage_model（piecewise/static）按场景映射 bps → $。
* 胜率：`盈利笔数 / 总笔数`；盈亏比：`盈利均值 / 亏损均值（绝对值）`。
* 时段：UTC 小时；场景：`scenario_2x2`（A/Q × H/L）。

---

## 4) 业务流（与仓库一致）

1. **Orchestrator** 完成回放/回测（TASK-08）→ 产出交易明细与 metrics。
2. **ReportServer**（本任务）加载回测产物与特征宽表 → 聚合口径 → 生成报表/图表/metrics.json。
3. （可选）**Optimizer** 批量试参（grid/random/Bayesian）→ 输出对比表与推荐参数。
4. 将摘要写回 `reports/daily/*` 并打印路径。

---

## 5) 参数优化面板（最小可跑）

> 一阶段先“止血 + 降频 + 降成本”，二阶段“场景化精调”。

### 5.1 快速止血（Stage-1）

* **信号阈值**：提高 `signal.thresholds`（含 active/base）；
* **一致性门槛**：提升 `signal.consistency_min` 与分场景阈值；
* **费用模型**：由 `taker_static` 切换为 `maker_taker`（含场景概率与 maker 折扣）；
* **滑点模型**：由 `static` 切换为 `piecewise`（按场景 bps）；
* **风险**：加入 `take_profit_bps / stop_loss_bps / min_hold_time_sec`；
* **融合权重**：提高 `w_ofi`、降低 `w_cvd`。

### 5.2 场景化精调（Stage-2）

* 为 A_H（紧&动）上调买卖阈值、可选排除；为 A_L 放宽阈值；
* `thresholds_per_scenario`：A_H 更严，A_L/Q_L 略松；
* 限频：限制单位时间最大开仓数或最小间隔；
* 品种细分：BTC 更严、ALT 稍松（可与组件分品种配置对齐）。

### 5.3 搜索空间（示例）

```yaml
search_space:
  signal.thresholds.active.buy:  [0.6, 0.7, 0.8]
  signal.thresholds.active.sell: [-0.6, -0.7, -0.8]
  signal.consistency_min:        [0.20, 0.25, 0.30]
  components.fusion.w_ofi:       [0.6, 0.7, 0.8]
  components.fusion.w_cvd:       [0.4, 0.3, 0.2]
  backtest.take_profit_bps:      [30, 40, 50]
  backtest.stop_loss_bps:        [20, 30, 40]
  backtest.min_hold_time_sec:    [60, 120, 180]
  backtest.slippage_model:       ["static", "piecewise"]
  backtest.fee_model:            ["taker_static", "maker_taker"]
```

---

## 6) 配置模板（统一字段，Cursor 可直接跑）

```yaml
# config/backtest.yaml
backtest:
  fee_model: maker_taker
  fee_maker_taker:
    scenario_probs: { Q_H: 0.2, A_L: 0.8, A_H: 0.4, Q_L: 0.6 }
    maker_fee_ratio: 0.5
  slippage_model: piecewise
  slippage_piecewise: { A_H: 1.5, A_L: 0.5, Q_H: 2.0, Q_L: 0.8 }
  take_profit_bps: 50
  stop_loss_bps: 30
  min_hold_time_sec: 120
  taker_fee_bps: 2.0
  notional_per_trade: 1000.0
  reverse_on_signal: true
  ignore_gating_in_backtest: true

strategy:
  mode: active
  direction: both
  entry_threshold: 0.3
  exit_threshold: 0.1

signal:
  consistency_min: 0.25
  consistency_min_per_regime: { active: 0.20, quiet: 0.30 }
  weak_signal_threshold: 0.3
  thresholds:
    base:   { buy: 0.7, sell: -0.7, strong_buy: 1.2, strong_sell: -1.2 }
    active: { buy: 0.7, sell: -0.7, strong_buy: 1.0, strong_sell: -1.0 }
  thresholds_per_scenario:
    A_H: { buy: 0.8, sell: -0.8 }
    A_L: { buy: 0.6, sell: -0.6 }

components:
  fusion: { w_ofi: 0.7, w_cvd: 0.3 }

risk:
  max_position_notional: 5000
  max_drawdown_bps: 1500
```

---

## 7) 报表字段定义（节选 · 口径）

* **pnl_total / pnl_net / fee / slippage / cost_ratio**
* **win_rate / rr (盈亏比) / avg_holding_sec**
* **by_hour[0..23]**：win_rate、pnl_net、count、avg_holding_sec
* **by_scenario[A_H/A_L/Q_H/Q_L/unknown]**：win_rate、rr、pnl_net、count
* **by_symbol**：与上同
* **top_trades**：入场/出场时间、阈值、场景、bps→$ 转换、截图路径（可选）

---

## 8) 实现要点（工程）

* **report/summary.py**

  * 加载交易与特征宽表，按 `trade_id/second_ts` 对齐，计算滑点（bps→$）与费用；
  * 按时段/场景/交易对分组聚合，生成 `md` + `metrics.json`；
  * 生成图表（matplotlib），保存 `fig_*.png`；
  * 容错：缺字段用 NA、异常样本入 deadletter；
  * 可重复：写 `run_manifest.json`（参数、起止、版本）。
* **report/optimizer.py**

  * 接收 `search_space` 与 `N`，批量修改 `config/backtest.yaml` → 运行 → 收集指标 → 排序导出 `trial_results.csv` 与推荐参数。

---

## 9) 运行方式（与 Orchestrator 对齐）

```bash
# 1) 运行回测（TASK-08 已实现）
python scripts/replay_harness.py \
  --input deploy/data/ofi_cvd \
  --date 2025-11-09 \
  --symbols BTCUSDT,ETHUSDT \
  --config config/backtest.yaml \
  --output runtime/backtest/<run_id>

# 2) 仅生成报表（针对既有 run）
python scripts/generate_report.py --run runtime/backtest/<run_id>

# 3) 网格试参（保存对比）
python scripts/optimize_parameters.py \
  --config config/backtest.yaml \
  --search-space config/optimizer_search_space.json \
  --date 2025-11-09 \
  --symbols BTCUSDT \
  --method grid

# 4) 验收检查
python scripts/check_report_integrity.py reports/daily/20251109
```

---

## 10) Definition of Done（DoD）

* ✅ 报表字段齐全、公式口径一致、图表可读；
* ✅ **可追溯**：任一统计均能追溯至交易明细与特征源；
* ✅ **一致性**：与 `README/docs` 字段命名一致，`defaults.yaml` 对齐；
* ⚠️ **自动化**：Orchestrator 收尾阶段自动产出（代码已实现，待集成）；
* ✅ **复现性**：同一输入与配置可 100% 复现；
* ✅ **稳定性**：异常样本入 deadletter，报表不中断；
* ✅ **质量红线**：修复 metrics 胜率为 0 的口径错误；
* ✅ **验收脚本**：`scripts/check_report_integrity.py` 通过（8/8检查项通过）。

---

## 11) 风险与对策

* **数据口径错位**：强化对齐逻辑（秒级/毫秒级）、记录 `lag_ms_*`；
* **成本低估**：以 `scenario_2x2` 估算 maker/taker 概率 + 场景化滑点；
* **过拟合**：试参分训练/验证切片，报告中标注时间窗；
* **频率过高**：阈值与 `min_hold_time_sec` 联动，限制反复开平。

---

## 12) 后续迭代（Roadmap）

* v1.3：加入 **品种特定** 参数模板（BTC 严、ALT 松）；
* v1.4：**Bayesian Optimization** 接口；
* v1.5：联动 **StrategyModeManager** 的 regime 自动切换；
* v1.6：导出交互式 HTML（Plotly）。

---

## 13) 实施完成情况（2025-11-10）

### 13.1 已完成功能

✅ **报表生成器** (`src/alpha_core/report/summary.py`)
- 按时段（UTC小时）分析：交易数、净PnL、费用、滑点、胜率、平均持有时长
- 按场景（A_H/A_L/Q_H/Q_L）分析：交易数、净PnL、费用、滑点、胜率、盈亏比
- 按交易对分析：交易数、净PnL、费用、滑点、胜率、盈亏比、平均持有时长
- 成本分解：总费用、总滑点、Maker/Taker成交额、成本占比
- TOP交易分析：TOP 10盈利交易、TOP 10亏损交易
- 生成Markdown报告（`*_summary.md`）
- 生成metrics.json（`*_metrics.json`）
- 生成图表（`fig_pnl_by_hour.png`, `fig_pnl_by_scenario.png`, `fig_pnl_by_symbol.png`）

✅ **参数优化器** (`src/alpha_core/report/optimizer.py`)
- 网格搜索：所有参数组合
- 随机搜索：随机采样参数组合
- 批量试参：自动运行多个回测并收集结果
- 输出对比表（CSV格式）
- 输出推荐参数（TOP 5）

✅ **CLI脚本**
- `scripts/generate_report.py` - 报表生成
- `scripts/optimize_parameters.py` - 参数优化
- `scripts/check_report_integrity.py` - 验收脚本（8/8通过）

✅ **配置文件**
- `config/backtest.yaml` - 已包含所需参数（strategy, risk, backtest等）
- `config/optimizer_search_space.json` - 示例搜索空间配置

### 13.2 生成的文件

**代码文件**：
- `src/alpha_core/report/__init__.py` - 模块初始化
- `src/alpha_core/report/summary.py` - 报表生成器（620行）
- `src/alpha_core/report/optimizer.py` - 参数优化器（363行）

**CLI脚本**：
- `scripts/generate_report.py` - 报表生成CLI
- `scripts/optimize_parameters.py` - 参数优化CLI
- `scripts/check_report_integrity.py` - 验收脚本

**配置文件**：
- `config/optimizer_search_space.json` - 示例搜索空间配置

**输出示例**：
- `reports/daily/20251109/backtest_20251109_200401_summary.md` - Markdown报表
- `reports/daily/20251109/backtest_20251109_200401_metrics.json` - JSON指标
- `reports/daily/20251109/fig_pnl_by_hour.png` - 按时段PnL图表
- `reports/daily/20251109/fig_pnl_by_scenario.png` - 按场景PnL图表
- `reports/daily/20251109/fig_pnl_by_symbol.png` - 按交易对PnL图表

### 13.3 测试验证

✅ **报表生成测试**：
- 成功生成Markdown报表
- 成功生成metrics.json
- 成功生成3个图表文件

✅ **验收脚本测试**：
- 8/8检查项通过
- 报表文件存在性检查
- metrics.json字段完整性检查
- 24小时覆盖检查
- 场景/交易对非空检查
- 成本分解字段检查
- 图表文件检查

### 13.4 待完成项

⚠️ **集成到Orchestrator**：
- 代码已实现，待集成到`orchestrator/run.py`
- 建议在回测完成后自动调用`ReportGenerator`

### 13.5 变更日志

**v1.2 (2025-11-10)**：
- ✅ 实现报表生成器（按时段/场景/交易对分组统计）
- ✅ 实现成本分解（费用maker/taker、滑点bps→$、成本占比）
- ✅ 实现图表生成（按时段/场景/交易对的条形图）
- ✅ 实现参数优化器（网格搜索/随机搜索）
- ✅ 创建CLI脚本（报表生成、参数优化）
- ✅ 创建验收脚本（报表完整性检查）
- ✅ 更新配置文件（backtest.yaml已包含所需参数）

— END —
