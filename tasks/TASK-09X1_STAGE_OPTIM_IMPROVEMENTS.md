# CURSOR · STAGE-1 / STAGE-2 参数优化改进方案（可执行版）
> 版本：v1.0 · 更新：2025-11-10 (Asia/Tokyo)  
> 依赖：TASK-08（回放/回测）、TASK-09（报表与优化器）

---

## 1) 目标与核心思路
- **目的**：用“两阶段优化”稳定拉升胜率与净收益，并控制成本占比与最大回撤。  
- **阶段职责**  
  - **Stage-1：稳胜率/控回撤/降成本**（小空间、偏保守、可 grid）  
  - **Stage-2：提净利/提单笔期望**（围绕 Stage-1 Champion 收紧范围做 random）  
- **验证**：所有评分基于 **Train/Val 双窗**；多品种采用**等权聚合**；成本采用**双口径**（对 PnL、对成交额）。

---

## 2) 目录与产物（输出契约）
```
runtime/optimizer/
  stage1/<ts>/trial_* / trial_results.csv / recommended_config.yaml / stage1_manifest.json
  stage2/<ts>/trial_* / trial_results.csv / recommended_config.yaml / stage2_manifest.json
reports/daily/<date>/<run_id>_summary.md  # Champion/Runner-up 报表
```
Top-K、Pareto、Train/Val 指标在 CSV 与 MD 中同时落盘，便于复盘与回归。

---

## 3) Runner 与输出路径（必须对齐）
- 新增 CLI：`--runner {replay_harness, orchestrator, auto}`（默认 `auto`，优先 orchestrator）。  
- 统一输出：  
  - **优先**使用 `--output runtime/optimizer/trial_<id>`（若 runner 支持）。  
  - 否则在子进程 `env` 注入 `BACKTEST_OUTPUT_DIR=runtime/optimizer/trial_<id>`，由底层写出 `backtest_*`。

---

## 4) Train/Val 双窗与走步验证
- CLI 新增两种方式：  
  1) `--dates 2025-11-08,2025-11-09`（严格双日）  
  2) `--date 2025-11-09 --train-minutes 720 --val-minutes 720`（同日切半）  
- 评分导出：`*_train/*_val/generalization_gap = score_train - score_val`。  
- **选优依据以 `score_val` 为主，`gap` 为惩罚项**。

---

## 5) 可复现性（Manifest + 种子）
- CLI：`--seed 42`；对随机搜索/并行框架设定统一种子。  
- `*_manifest.json` 必含：`git_sha, engine_version, search_space_hash, cmd, env_subset, runner, dates/slices, symbols, seed, created_at`。

---

## 6) 多品种等权聚合
- 对每个 symbol 独立计算核心指标 → **等权平均**（而不是按成交额/笔数加权），避免被高波动品种“带飞”。  
- CSV 字段加：`symbols_agg="equal_weight"` 与各 symbol 的小计可选落盘（供排错）。

---

## 7) 成本双口径（更稳健）
- `cost_ratio_pnl = (fee+slip) / |gross_pnl|`（单位盈利成本压力）  
- `cost_ratio_notional = (fee+slip) / Σ notional`（稳定、频次可比）  
- 评分使用**两者并行**，并对 `cost_ratio_notional` 赋更高权重。

---

## 8) Stage-1（止血）——搜索空间与评分
**搜索重点**：阈值↑、一致性↑、弱信号↑、冷却/翻转更保守、最小持有≥90s、成本模型 maker_taker + piecewise。  
**建议搜索空间（示例）**：
```json
{
  "fusion.thresholds.fuse_buy": [0.8, 1.0, 1.2],
  "fusion.thresholds.fuse_sell": [-0.8, -1.0, -1.2],
  "fusion.thresholds.regime.A_H.fuse_buy": [1.0, 1.2, 1.4],
  "fusion.thresholds.regime.A_H.fuse_sell": [-1.0, -1.2, -1.4],
  "fusion.weak_signal_threshold": [0.30, 0.35],
  "fusion.consistency.min_consistency": [0.25, 0.35],
  "fusion.adaptive_cooldown_enabled": [true],
  "fusion.adaptive_cooldown_k": [0.10, 0.20],
  "fusion.flip_rearm_margin": [0.10, 0.20],
  "backtest.min_hold_time_sec": [90, 120, 180],
  "backtest.fee_model": ["maker_taker"],
  "backtest.slippage_model": ["piecewise"]
}
```
**Stage-1 评分权重（示例）**：
```json
{
  "weights": {
    "win_rate": 0.8,
    "max_drawdown": -0.4,
    "cost_ratio_notional": -0.6,
    "pnl_per_trade": 0.2
  },
  "penalties": { "min_trades": 50, "unknown_ratio_max": 0.05, "gap_weight": -0.3 },
  "normalize": "rank",
  "symbol_agg": "equal_weight"
}
```
**执行建议**：  
- 方法 `grid` 或 `random`（小样本）+ `--max-workers 4`（若 random）+ `--early-stop-rounds 10`。  
- 输出 `stage1/recommended_config.yaml` 与 `trial_results.csv`（含 train/val）。

---

## 9) Stage-2（增益）——收紧范围与搜索
**策略**：以 Stage-1 Champion 为中心，按 **±10–20%** 收紧范围做 `random`，突出 `net_pnl / pnl_per_trade / cost_ratio_notional`。  
**示例（程序生成的收紧空间）**：
```json
{
  "fusion.thresholds.fuse_buy": ["center*0.9", "center", "center*1.1"],
  "fusion.thresholds.fuse_sell": ["center*0.9", "center", "center*1.1"],
  "fusion.thresholds.regime.A_L.fuse_buy": ["center*0.9", "center", "center*1.1"],
  "fusion.thresholds.regime.Q_L.fuse_buy": ["center*0.9", "center", "center*1.1"],
  "components.fusion.w_ofi": ["center-0.1", "center", "center+0.1"],
  "components.fusion.w_cvd": ["center+0.1", "center", "center-0.1"],
  "backtest.take_profit_bps": ["center-10", "center", "center+10"],
  "backtest.stop_loss_bps": ["center-10", "center", "center+10"]
}
```
**Stage-2 评分权重（示例）**：
```json
{
  "weights": {
    "net_pnl": 1.0,
    "pnl_per_trade": 0.6,
    "win_rate": 0.4,
    "cost_ratio_notional": -0.5,
    "max_drawdown": -0.2
  },
  "penalties": { "min_trades": 50, "unknown_ratio_max": 0.05, "gap_weight": -0.3 },
  "normalize": "rank",
  "symbol_agg": "equal_weight"
}
```
**执行建议**：  
- 方法 `random` + `--max-workers 4..8` + `--early-stop-rounds 10..20` + `--resume`。  
- 输出 `stage2/recommended_config.yaml` 与 `trial_results.csv`；对 Top-K 做 **验证窗回放** 并重算 `score_val`。

---

## 10) Top-K、Pareto 与报表归档
- **Top-K**（默认 10）字段：  
  `rank, config_hash, score_val, win_rate(train/val), net_pnl(train/val), pnl_per_trade, max_dd_val, cost%(pnl/notional), trades_total, tph, unknown_ratio, symbols_agg, report_path, config_path`  
- **Pareto 图**：`net_pnl` vs `win_rate` vs `cost_ratio_notional`（三维→二维投影，PNG）。  
- **报表**：至少对 **Champion/Runner-up** 生成并链接到 Top-K MD。

---

## 11) 容错与断点续跑
- 试验失败时落 `trial_<id>_stderr.txt` 并在 CSV `error` 列注明；  
- `--resume` 跳过已完成 trial；失败率过高时自动**降并行度**+**重试 3 次**。

---

## 12) CLI 示例
```bash
# STAGE-1（稳胜率）——双窗、等权多品种
python scripts/run_stage1_optimization.py   --config config/backtest.yaml   --runner auto   --dates 2025-11-08,2025-11-09   --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT   --minutes 1440   --search-space tasks/TASK-09/search_space_stage1.json   --scoring tasks/TASK-09/scoring_stage1.json   --method grid   --max-workers 4   --seed 42 --resume

# STAGE-2（提收益）——围绕 Stage-1 Champion 收紧随机搜索
python scripts/run_stage2_optimization.py   --config stage1/<ts>/recommended_config.yaml   --runner auto   --dates 2025-11-08,2025-11-09   --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT   --minutes 1440   --search-space tasks/TASK-09/search_space_stage2.json   --scoring tasks/TASK-09/scoring_stage2.json   --method random   --max-workers 6 --early-stop-rounds 15   --seed 123 --resume
```

---

## 13) Definition of Done（DoD）

### 13.1 功能要求
- ✅ 两阶段脚本均支持 `--runner/--seed/--dates/--resume/--max-workers/--early-stop-rounds`；  
- ✅ 产出 `trial_results.csv/json`（含 Train/Val 指标、cost 双口径、等权聚合、未知场景占比）；  
- ✅ 生成 `recommended_config.yaml` 与 `*_manifest.json`（复现实验所需元信息齐全）；  
- ✅ Top-K（≥10）与 Pareto 图导出；Champion/Runner-up 报表可打开；  
- ✅ 任一结果可复现（命令、种子、空间、git_sha、data slice 记录完备）。

### 13.2 多品种公平权重要求
- ✅ `metrics.json` 必须包含 `by_symbol` 字段（按symbol聚合的指标）
- ✅ 多品种优化时自动使用等权评分（`equal_weight_score`）
- ✅ CSV输出包含 `equal_weight_score` 和 `per_symbol_metrics` 列
- ✅ Walk-forward结果包含 `by_symbol_train_metrics`、`by_symbol_val_metrics`、`equal_weight_val_score`

### 13.3 口径一致性要求（必须固定）

**重要**: 以下参数在多品种优化时必须固定，确保"等权"的公平性。

- ✅ **NOTIONAL_PER_TRADE**: **固定为1000**（所有品种使用相同名义，避免不同品种用不同名义破坏"等权"公平性）
  - 配置文件: `config/backtest.yaml` - `backtest.notional_per_trade: 1000`
  - 环境变量: `NOTIONAL_PER_TRADE=1000`（如果使用环境变量覆盖）
  - 验证: 多品种优化前检查所有symbol使用相同notional_per_trade

- ✅ **rollover_timezone**: **固定为UTC**（统一时区，确保切日口径一致）
  - 配置文件: `config/backtest.yaml` - `backtest.rollover_timezone: "UTC"`
  - 默认值: UTC（如果未配置）

- ✅ **rollover_hour**: **固定为0**（统一切日时间，使用日期边界）
  - 配置文件: `config/backtest.yaml` - `backtest.rollover_hour: 0`
  - 默认值: 0（如果未配置）

- ✅ **ignore_gating_in_backtest**: **固定为true**（统一门控开关，确保训练/验证/对比口径一致）
  - 配置文件: `config/backtest.yaml` - `backtest.ignore_gating_in_backtest: true`
  - 默认值: true（如果未配置）

- ✅ **费用和滑点**: 固定费率（确保成本口径一致）
  - `taker_fee_bps: 2.0`
  - `slippage_bps: 1.0`

- ✅ 所有口径参数需记录到 `*_manifest.json` 中，确保历史结果可横向对比

### 13.4 数据输出要求
- ✅ `metrics.json` 必须包含字段：
  - `by_symbol`: 按symbol聚合的指标（pnl_gross, pnl_net, fee, slippage, turnover, count, wins, losses, win_rate, cost_ratio, max_drawdown, MAR, sharpe_ratio）
  - `scenario_breakdown`: 按场景拆解的指标
  - 其他现有字段保持不变
- ✅ `trial_results.csv` 必须包含列：
  - `equal_weight_score`: 等权评分（多品种时）
  - `per_symbol_metrics`: per-symbol指标（JSON字符串）
  - `train_score`, `val_score`, `generalization_gap`: Walk-forward指标
- ✅ `walkforward_results.json` 必须包含字段：
  - `by_symbol_train_metrics`: 训练集per-symbol指标
  - `by_symbol_val_metrics`: 验证集per-symbol指标
  - `equal_weight_train_score`: 训练集等权评分
  - `equal_weight_val_score`: 验证集等权评分

---

## 14) 风险与对策
- **gross≈0 导致 cost_ratio 抖动** → 并行使用 `cost_ratio_notional`；  
- **过拟合风险** → Train/Val 双窗 + `gap` 惩罚 + 走步验证；  
- **单品种“带飞”** → 等权聚合 + Top-K 中显示单品种小计；  
- **日志/结果丢失** → `BACKTEST_OUTPUT_DIR` 强制对齐 + stderr 落盘 + `--resume`。

---

## 15) 路线图
- v1.1：Bayesian Optimization（以 Stage-2 最优群作先验）  
- v1.2：自动化流水线（`run_auto_tuner.py` 循环执行 Stage-1→Stage-2→验证→Top10）  
- v1.3：可视化仪表盘（Streamlit/Gradio）与一键 PR（人审后合并）

---

### 附：搜索空间键位总表（便于 Cursor 搜索/替换）
- `fusion.thresholds.fuse_buy / fuse_sell`  
- `fusion.thresholds.regime.(A_H|A_L|Q_H|Q_L).fuse_buy / fuse_sell`  
- `fusion.weak_signal_threshold`  
- `fusion.consistency.min_consistency`  
- `fusion.adaptive_cooldown_enabled / adaptive_cooldown_k`  
- `fusion.flip_rearm_margin`  
- `components.fusion.w_ofi / w_cvd`  
- `backtest.min_hold_time_sec / take_profit_bps / stop_loss_bps`  
- `backtest.fee_model / slippage_model`  

— END —
