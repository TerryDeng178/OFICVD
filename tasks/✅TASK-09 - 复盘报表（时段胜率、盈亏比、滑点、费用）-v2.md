# TASK-09 · 复盘报表（时段胜率、盈亏比、滑点、费用）与参数优化 v2.0

> 里程碑：M3 · 依赖：TASK-08 回放/回测 Harness · 版本：v2.0 · 更新：2025-11-10 (Asia/Tokyo)  
> **状态**：✅ **已完成**（2025-11-10）

---

## 1) 背景 & 目标

**背景**：近期 6 交易对 24 小时回测净亏损、成本占比高、胜率极低。需快速定位问题并通过**复盘报表**与**参数优化**提升胜率与收益。

**目标**：

在"6 交易对 / 24 小时"基准集上，显著提高胜率与净收益，同时降低成本占比与最大回撤，并产出可复现实验与推荐配置。

**成功阈值（相对原基线）**：

- 胜率 +5pp 以上
- net_pnl ≥ +15%
- cost_ratio 下降 ≥ 10%
- max_drawdown 不劣于基线 5% 以上

---

## 2) 成果物（Deliverables）

* 代码：`src/alpha_core/report/summary.py`（报表生成器），`src/alpha_core/report/optimizer.py`（参数搜索）。
* 配置：`config/backtest.yaml`（新增/对齐 fee/slippage/strategy/signal/risk 节点）。
* 搜索空间：`tasks/TASK-09/search_space.json`（参数优化搜索空间配置）。
* 输出：
  * 报告：`reports/daily/<YYYYMMDD>/<run_id>_summary.md`（主报表）
  * 附件图：`reports/daily/<YYYYMMDD>/fig_*.png`（按时段/场景/交易对条形图）
  * 机器可读：`reports/daily/<YYYYMMDD>/<run_id>_metrics.json`
  * 优化结果：`runtime/optimizer/trial_results.json` 与 `trial_results.csv`（含 score）
  * 推荐配置：`runtime/optimizer/recommended_config.yaml`
* 集成：Orchestrator 结束时自动调用（`--enable report`）。

---

## 3) 数据输入/输出与契约

**输入**：

* 固定的数据/回放包含：原基准 6 交易对（同一日），同一撮合/费用/滑点模型。
* 基础配置 `config/defaults.yaml` 与搜索空间 `tasks/TASK-09/search_space.json`。
* 回测入口：`scripts/replay_harness.py`（或 `orchestrator.run`）。

**输出字段（报表）**：

* 概览：总交易数、总/净 PnL、费用、滑点、胜率、盈亏比、Sharpe、最大回撤、平均持有时长。
* 分组视图：
  * **按时段**（UTC 小时）胜率/净 PnL/每笔平均PnL/平均持有时长。
  * **按场景**（A_H/A_L/Q_H/Q_L/unknown）交易数、胜率、盈亏比、净 PnL。
  * **按交易对**统计表（交易数、费用、滑点、净 PnL、胜率、盈亏比、平均持有时长）。
* 成本分解：费用（maker/taker）、滑点（bps→$）、成本占比。
* 数据质量提示：unknown场景占比（用于数据质量监控）。
* TOP/N 序列回看：最大盈利/亏损前 N 笔的信号轨迹与出入场上下文。

**关键度量（DoD 同时验收）**：

- 胜率 win_rate
- 净收益 net_pnl
- 最大回撤 max_drawdown
- 成本占比 cost_ratio=(fee+slip)/|gross_pnl|
- 每小时交易数 trades_per_hour
- 每笔期望收益 pnl_per_trade

---

## 4) 参数搜索空间

参数搜索空间定义在 `tasks/TASK-09/search_space.json`，包含以下参数位（均被 CORE_ALGO/FUSION 侧读取并生效）：

```json
{
  "fusion.thresholds.fuse_buy": [0.8, 1.0, 1.2],
  "fusion.thresholds.fuse_sell": [-0.8, -1.0, -1.2],
  "fusion.thresholds.regime.A_H.fuse_buy": [1.0, 1.2, 1.4],
  "fusion.thresholds.regime.A_H.fuse_sell": [-1.0, -1.2, -1.4],
  "fusion.thresholds.regime.Q_H.fuse_buy": [1.0, 1.2, 1.4],
  "fusion.thresholds.regime.Q_H.fuse_sell": [-1.0, -1.2, -1.4],
  "fusion.thresholds.regime.A_L.fuse_buy": [0.6, 0.8, 1.0],
  "fusion.thresholds.regime.A_L.fuse_sell": [-0.6, -0.8, -1.0],
  "fusion.thresholds.regime.Q_L.fuse_buy": [0.6, 0.8, 1.0],
  "fusion.thresholds.regime.Q_L.fuse_sell": [-0.6, -0.8, -1.0],
  "fusion.consistency.min_consistency": [0.15, 0.25, 0.35],
  "fusion.weak_signal_threshold": [0.20, 0.30, 0.35],
  "fusion.adaptive_cooldown_enabled": [true],
  "fusion.adaptive_cooldown_k": [0.10, 0.20, 0.30],
  "fusion.flip_rearm_margin": [0.00, 0.10, 0.20],
  "fusion.burst_coalesce_ms": [0, 300, 600],
  "fusion.min_warmup_samples": [50, 120, 240]
}
```

**参数说明**：

- **阈值参数**：提高高活动场景（A_H/Q_H）的买卖阈值，抑制噪音；降低低活动场景（A_L/Q_L）的阈值，避免"机会丢失"。
- **弱信号节流**：提高 `weak_signal_threshold` 和 `consistency.min_consistency`，可显著提高胜率（代价是交易频率下降）。
- **去噪与冷却**：降低 `adaptive_cooldown_k`、提高 `flip_rearm_margin`，减少"误翻向"后的连续亏损。
- **其他**：适度增大 `min_warmup_samples`、在极端行情下增加 `burst_coalesce_ms`，避免同方向"抖动"触发多笔无效单。

---

## 5) 流程

### 5.1 固定数据 & 费用/滑点

锁定 6 交易对与 24h 数据切片；锁定 taker/maker 费率与滑点模型（减少不可比因素）。

### 5.2 跑通单次回放

使用基础配置跑一遍，确保 `backtest_*` 完整产出。

### 5.3 参数试参

**CLI命令**：

```bash
python scripts/optimize_parameters.py \
  --config config/defaults.yaml \
  --search-space tasks/TASK-09/search_space.json \
  --input deploy/data/ofi_cvd \
  --date 2025-11-09 \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,DOGEUSDT,SOLUSDT,XRPUSDT \
  --minutes 1440 \
  --method grid \
  --runner auto
```

**支持的方法**：
- `grid`：网格搜索（所有参数组合）
- `random`：随机搜索（随机采样参数组合）

**支持的runner**：
- `replay_harness`：使用 `scripts/replay_harness.py`
- `orchestrator`：使用 `orchestrator.run`（需设置 `BACKTEST_OUTPUT_DIR` 环境变量）
- `auto`：自动探测（优先使用 `replay_harness`）

### 5.4 汇总 & 选优

生成 `trial_results.csv/json` 与推荐配置；评分函数使用"稳健标准化 + 样本数惩罚"。

**评分函数**：

```
score = rank(net_pnl) + 0.5*rank(win_rate) - 0.5*rank(cost_ratio) - 0.2*rank(max_drawdown)
- 惩罚：极端低样本（total_trades < 10）-0.3
- 惩罚：成本占比过高（cost_ratio > 50%）-0.2
```

### 5.5 复盘报表

对最佳/次佳配置各生成报表（by_hour/by_scenario/by_symbol + 成本分解 + TOP盈亏）。

**CLI命令**：

```bash
python scripts/generate_report.py --run runtime/optimizer/trial_1
```

### 5.6 回归验证

用不同日样本做"交叉日验证"，确认并非过拟合。

### 5.7 落盘推荐

将 `recommended_config.yaml` 与报表归档到 `reports/daily/<date>/`，并更新 README 的任务清单（TASK-09）。

---

## 6) 两轮试参策略（实操建议）

### 第 1 轮（稳胜率）

把 `weak_signal_threshold`、`consistency.min_consistency`、A_H/Q_H 的阈值拉高一个档位，搭配更保守的 `adaptive_cooldown_k` 与更大的 `flip_rearm_margin`，先把胜率与回撤拉到可接受。

**推荐参数范围**：
- `weak_signal_threshold`: 0.30-0.35
- `consistency.min_consistency`: 0.25-0.35
- `regime.A_H.fuse_buy`: 1.2-1.4
- `regime.Q_H.fuse_buy`: 1.2-1.4
- `adaptive_cooldown_k`: 0.10-0.20
- `flip_rearm_margin`: 0.10-0.20

### 第 2 轮（提收益）

在胜率稳定的前提下，微降低活动场景阈值与 `burst_coalesce_ms`，恢复合理频次，观察 `pnl_per_trade` 与 `cost_ratio` 的 Pareto 前沿。

**推荐参数范围**：
- `regime.A_L.fuse_buy`: 0.6-0.8
- `regime.Q_L.fuse_buy`: 0.6-0.8
- `burst_coalesce_ms`: 0-300

---

## 7) DoD（Definition of Done）

✅ 所有 trial 目录均含完整 4 文件：`trades.jsonl` / `pnl_daily.jsonl` / `metrics.json` / `run_manifest.json`。

✅ `trial_results.csv` 含 `score`/`error`/成本/交易数等关键列（`total_fee`, `total_slippage`, `cost_ratio`, `trades_per_hour`, `pnl_per_trade`）。

✅ `*_summary.md` 与 3 张图（时段/场景/交易对）生成成功。

✅ 推荐配置保存到 `recommended_config.yaml`（已修复空指针，从 `config_file` 反读 YAML）。

✅ 复跑最佳配置，结果不劣于试参期表现（防"虚高"）。

✅ 滑点成本名义本金智能回退（优先 `notional`，其次 `qty*px`，最后保守默认值）。

✅ 评分函数使用稳健标准化（rank_score）和惩罚项（低样本、高成本）。

✅ 报表包含 unknown 场景占比提示（数据质量监控）。

---

## 8) 关键修复项（v2.0）

### 8.1 推荐配置保存修复

**问题**：`_print_recommendations()` 使用了 `best_result["config"]`，但 `run_trial` 返回的是 `config_file`。

**修复**：从 `config_file` 反读 YAML：

```python
best_cfg = {}
if "config_file" in best_result:
    import yaml
    config_file_path = Path(best_result["config_file"])
    if config_file_path.exists():
        with open(config_file_path, "r", encoding="utf-8") as f:
            best_cfg = yaml.safe_load(f) or {}
```

### 8.2 Orchestrator Runner 输出路径统一

**问题**：`orchestrator` runner 没有把结果写进 trial 目录。

**修复**：通过环境变量 `BACKTEST_OUTPUT_DIR` 统一输出路径：

```python
env = os.environ.copy()
if self.runner == "orchestrator":
    env["BACKTEST_OUTPUT_DIR"] = str(trial_dir)
result = subprocess.run(cmd, ..., env=env)
```

### 8.3 滑点成本名义本金智能回退

**问题**：`_extract_slippage_cost()` 在缺失时用 `notional=1000`，会显著扭曲成本占比。

**修复**：智能回退逻辑：
1. 优先使用 `trade["notional"]`
2. 没有则用 `abs(qty) * px`（或 `entry_px`）
3. 再不行才回退保守默认值（200.0），并标记为估算

### 8.4 评分函数改进

**问题**：综合分仅在写行时临时计算，且成本/回撤的标准化和交易数惩罚不足。

**修复**：
- 使用 `rank_score` 进行稳健标准化（rank到[0,1]）
- 添加惩罚项：极端低样本（total_trades < 10）-0.3，成本占比过高（cost_ratio > 50%）-0.2

### 8.5 报表质量提升

**改进**：
- 在 `by_hour` 上输出 `win_rate` 与 `avg_pnl_per_trade`，并在图表副标题标注交易数
- 场景标准化限定到 `{A_H,A_L,Q_H,Q_L}`，其余归为 `unknown`，并在 Markdown 中单列 `unknown` 占比提示数据质量

---

## 9) 运行方式

### 9.1 运行回测（TASK-08 已实现）

```bash
python scripts/replay_harness.py \
  --input deploy/data/ofi_cvd \
  --date 2025-11-09 \
  --symbols BTCUSDT,ETHUSDT \
  --config config/backtest.yaml \
  --output runtime/backtest/<run_id>
```

### 9.2 仅生成报表（针对既有 run）

```bash
python scripts/generate_report.py --run runtime/backtest/<run_id>
```

### 9.3 网格试参（保存对比）

```bash
python scripts/optimize_parameters.py \
  --config config/backtest.yaml \
  --search-space tasks/TASK-09/search_space.json \
  --date 2025-11-09 \
  --symbols BTCUSDT \
  --method grid \
  --runner auto
```

### 9.4 验收检查

```bash
python scripts/check_report_integrity.py reports/daily/20251109
```

---

## 10) 变更日志

**v2.0 (2025-11-10)**：
- ✅ 修复推荐配置保存（从 `config_file` 反读 YAML）
- ✅ 修复 orchestrator runner 输出路径统一（通过环境变量）
- ✅ 改进滑点成本名义本金回退逻辑（智能回退）
- ✅ 改进评分函数（稳健标准化 + 惩罚项）
- ✅ 报表质量提升（添加更多指标和 unknown 占比提示）
- ✅ 创建参数搜索空间配置文件（`tasks/TASK-09/search_space.json`）
- ✅ 更新任务卡到 v2.0 版本

**v1.2 (2025-11-10)**：
- ✅ 实现报表生成器（按时段/场景/交易对分组统计）
- ✅ 实现成本分解（费用maker/taker、滑点bps→$、成本占比）
- ✅ 实现图表生成（按时段/场景/交易对的条形图）
- ✅ 实现参数优化器（网格搜索/随机搜索）
- ✅ 创建CLI脚本（报表生成、参数优化）
- ✅ 创建验收脚本（报表完整性检查）
- ✅ 更新配置文件（backtest.yaml已包含所需参数）

---

**报告生成时间**: 2025-11-10

