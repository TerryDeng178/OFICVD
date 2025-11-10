# TASK-09X · 自动化两阶段优化（Stage1→Stage2 循环）与 Top10 榜单输出

> 里程碑：M3 · 依赖：TASK-08、TASK-09 · 版本：v1.0 · 更新：2025-11-10 (Asia/Tokyo)

---

## 1) 背景 & 目标

**背景**：已实现阶段化试参脚本 `run_stage1_optimization.py`（稳胜率+控回撤）与 `run_stage2_optimization.py`（提收益+控成本），并产出报告/CSV/推荐配置。现需要**自动循环执行 Stage1→Stage2**，在固定数据窗与多品种下**反复逼近**稳健参数，并输出一个长期可参考的 **Top10 榜单**（含训练/验证双窗指标）。

**目标**：

* 一键脚本：自动依次执行 Stage1→Stage2→验证→归档；可设重复轮数/每日计划。
* 产出 Top10 榜单（CSV+Markdown），可直接打开查看；附带每条目的报表链接。
* 支持断点续跑、早停、并行、重试、走步/交叉日验证、等权多品种汇总。
* 输出“推荐配置”（冠军）+“候选配置”（Top10）+“Pareto 前沿可视化”。

---

## 2) 依赖 & 目录

**依赖**：

* TASK-08 回放/回测 Harness 已能稳定产出 backtest_* 目录。
* TASK-09 报表与优化器（summary.py / optimizer.py）已稳定。

**目录规范**：

```
runtime/optimizer/
  auto_runs/
    <date>/
      run_<ts>/
        stage1/ ... trial_*  # Stage1 结果
        stage2/ ... trial_*  # Stage2 结果
        reports/             # 最终 champion/challenger 的报表与图表
        manifests/           # run_manifest.json, stage*_manifest.json
        top10.csv
        top10.md
        recommended_config.yaml
        pareto.png
```

---

## 3) 成果物（Deliverables）

* **脚本**：`scripts/run_auto_tuner.py`（主入口），`scripts/utils/scoreboard.py`（汇总）、`scripts/utils/pareto.py`（可视化）。
* **配置**：

  * `tasks/TASK-09/search_space_stage1.json`（已有）、`search_space_stage2.json`（已有/增强）
  * `tasks/TASK-09/scoring_weights.json`（score 权重与惩罚项）
  * `config/backtest.yaml`（基础配置，Stage2 以 Stage1 最优为基准）
* **输出**：`top10.csv`、`top10.md`、`recommended_config.yaml`、`pareto.png`、`run_manifest.json`。

---

## 4) 输入/输出契约

**输入**：

* `--input <dir>`：特征/撮合数据根目录（与回放一致）。
* `--date <YYYY-MM-DD>`：回测日期；支持多日 `--dates=2025-11-08,2025-11-09`（走步）。
* `--symbols <CSV>`：多交易对（等权聚合指标）。
* `--minutes <int?>`：快速验证可截短时长。

**输出字段（Top10 CSV/MD，按列）**：

* `rank, config_hash, score, win_rate_train, win_rate_val, net_pnl_train, net_pnl_val, max_dd_val, cost_ratio_pnl_val, cost_ratio_notional_val, trades_total, trades_per_hour, pnl_per_trade, unknown_ratio, symbols_agg, stage1_dir, stage2_dir, report_path, config_path`

**口径对齐**：

* 净值：`net_pnl = gross_pnl - fee - slippage`；
* 成本占比：并行输出 `cost_ratio_pnl=(fee+slip)/|gross_pnl|` 与 `cost_ratio_notional=(fee+slip)/Σnotional`；
* 胜率：`wins/total`；盈亏比：`avg_win/avg_loss_abs`；
* 多品种：按 symbol 先算再**等权**汇总；
* 验证：按 Train/Val 双窗分别统计。

---

## 5) 运行流程（自动循环）

1. **准备运行环境**：锁定数据窗（date/minutes）、交易对（symbols）、基础配置（backtest.yaml）。
2. **Stage1（稳胜率+控回撤）**：

   * 使用 `search_space_stage1.json` 与 `method=grid`；
   * 评分权重偏重 `win_rate / max_drawdown / cost_ratio_notional`；
   * 选出 Top-K（默认 K=5），并导出 `stage1/recommended_config.yaml`。
3. **Stage2（提收益+控成本）**：

   * 基于 Stage1 最优配置进行**收紧范围**的随机搜索（±10–20%）；
   * 评分权重偏重 `net_pnl / pnl_per_trade / cost_ratio_notional`，保留样本数惩罚；
   * 产出 `stage2/recommended_config.yaml` 与 trial 对比表。
4. **验证（Train/Val）**：

   * 对 Stage2 Top-K 逐个进行验证窗回放；
   * 计算 `generalization_gap = score_train - score_val`；
   * 以 `score_val` 与 `gap` 共同排序，生成 Top10。
5. **报表与归档**：

   * 对 Top10（至少 Champion/Runner-up）生成报表与图表；
   * 汇总 `top10.csv/md`、`pareto.png`、`recommended_config.yaml`、manifests。
6. **重复循环（可选）**：

   * `--repeat N`（默认 1），每轮可换随机种子或滚动窗口；
   * 每轮输出独立 `run_<ts>/` 目录；
   * `--resume` 断点续跑；`--cron` 进入每日定时。

---

## 6) CLI 设计（run_auto_tuner.py）

```bash
python scripts/run_auto_tuner.py \
  --config config/backtest.yaml \
  --stage1-space tasks/TASK-09/search_space_stage1.json \
  --stage2-space tasks/TASK-09/search_space_stage2.json \
  --scoring tasks/TASK-09/scoring_weights.json \
  --input deploy/data/ofi_cvd \
  --dates 2025-11-08,2025-11-09 \
  --symbols BTCUSDT,ETHUSDT,... \
  --minutes 1440 \
  --method1 grid --method2 random \
  --stage1-topk 5 --stage2-topk 10 \
  --max-workers 4 --early-stop-rounds 10 \
  --repeat 2 --resume --output runtime/optimizer/auto_runs
```

**主要参数**：

* `--method1/--method2`：Stage1/2 的搜索方法（grid/random）。
* `--stage1-topk/--stage2-topk`：各阶段保留候选数。
* `--repeat`：重复执行轮数（不同随机种子/滚动窗）。
* `--cron`：crontab 表达式（可选），用于每日跑批；无则立即执行一次。
* `--scoring`：JSON 定义权重与惩罚（见 §7）。

---

## 7) 评分函数（稳健标准化 + 惩罚）

**scoring_weights.json（示例）**：

```json
{
  "weights": {"net_pnl": 1.0, "win_rate": 0.5, "cost_ratio_notional": -0.5, "max_drawdown": -0.2, "pnl_per_trade": 0.4},
  "penalties": {"min_trades": 50, "unknown_ratio_max": 0.05, "gap_weight": -0.3},
  "normalize": "rank", 
  "symbol_agg": "equal_weight"
}
```

**说明**：

* 标准化：rank 到 [0,1]，降低异常值影响；
* 惩罚：总交易数不足、unknown 场景占比过高、泛化落差过大；
* 多品种：等权聚合后再打分。

---

## 8) Top10 榜单渲染（Markdown）

* 表头：`𝚛𝚊𝚗𝚔 | config_hash | win_rate(train/val) | net_pnl(train/val) | max_dd(val) | cost%(pnl/notional) | trades | tph | pnl/trade | unknown% | report | config`
* 每行附超链接：指向 `reports/<run_id>_summary.md` 与 `recommended_config.yaml`。
* 附图：`pareto.png`（三维投影：`net_pnl` vs `win_rate` vs `cost_ratio_notional`）。

---

## 9) 关键实现要点

* **复用现有阶段脚本**：子进程调用 `run_stage1_optimization.py` / `run_stage2_optimization.py`，并读取各自输出目录。
* **范围收紧**：Stage2 自动以 Stage1 推荐配置为中心，按 ±比例生成随机搜索空间。
* **Train/Val 切片**：`--dates` 支持多日或同日分窗（前 12h 训练/后 12h 验证）。
* **断点续跑**：发现已有 `stage1/`、`stage2/`、`top10.csv` 时，按 `--resume` 跳过已完成步骤。
* **并行与早停**：并行度传递给子阶段脚本；早停在 Stage2 生效。
* **Manifest**：记录 `git_sha`、`engine_version`、`search_space_hash`、`data_slice`、`cmd`、`env`。
* **失败重试**：trial 失败写 `error` 字段并保存 stderr；失败率超过阈值触发降级（减小并行度/重试3次）。

---

## 10) 与 Orchestrator/Report 集成

* Orchestrator 启动参数：`--enable report`；Stage 完成后调用 `summary.py` 生成报表。
* Champion 与 Runner-up 自动生成报表并入榜单；其余候选仅保留 trial 目录与 metrics.json。

---

## 11) Definition of Done（DoD）

* ✅ 完整产出：`top10.csv`、`top10.md`、`recommended_config.yaml`、`pareto.png`、`manifests/*`。
* ✅ Top10 统计含 **Train/Val** 双窗、**两种成本占比**口径、**等权多品种**聚合；
* ✅ 链接可用：每条目可打开报表与配置文件；
* ✅ 断点续跑、早停、并行、失败重试均生效；
* ✅ 任意结果可 100% 复现（manifest 完整）。

---

## 12) 后续 Roadmap

* v1.1：Bayesian Optimization 接口（以 Stage2 最优群作为先验）；
* v1.2：增量滑动窗（每日自动推进 1 日/6 小时）；
* v1.3：仪表盘（Streamlit/Gradio）在线浏览 Top10 与报表；
* v1.4：自动提 PR 更新 `config/backtest.yaml`（人审后合并）。

— END —
