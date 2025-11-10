# ✅STAGE-01 · Cursor 优化提示词 · 任务卡（止血向试参）
**目标**：用 *最小变更* 完成 Stage-1（止血/控回撤/降成本）参数搜索，确保每个 TRIAL 使用**不同参数组合**，产出稳定的 `trial_results.csv` 与 `recommended_config.yaml`，并生成可复现的运行记录。

---

## 0) 先决条件
- 已具备基础回放/回测入口（`scripts/run_stage1_optimization.py`）。
- 数据可读（例如 `deploy/data/ofi_cvd/`，或你的数据仓库目录）。
- 具备 `config/backtest.yaml`（或等价配置）。

---

## 1) **直接贴到 Cursor Chat 的提示词（AI 指令）**
> 复制以下块到 Cursor Chat，即可指导其自动修改/创建文件并执行。

```text
你是“Stage-1 优化工程师 Agent”。请按以下要求操作，所有变更以最小侵入为原则，严格保证可复现与日志完备。

[目标]
- 完成 Stage-1 止血向参数搜索。
- 确保每个 TRIAL 的参数组合不同，避免“组合数=1”导致的重复结果。
- 产出：trial_results.csv、recommended_config.yaml、stage1_summary.md。
- 所有产物写入一个全新目录：runtime/optimizer/stage1_retest_20251110/

[步骤A：健壮性补丁]
1. 打开 scripts/run_stage1_optimization.py，在读取 search_space 后加入：
   - 若缺少顶层 "search_space" 键，则回退为“使用文件顶层作为搜索空间”，并打印警告。
   - 计算“组合数（combos）”，当 combos<=1 时，打印 ERROR 并直接退出（返回码 !=0）。
   - 在日志中打印：搜索空间键数、组合数、前 3 个参数组合预览（用于肉眼核对）。
2. 确保优化器不会静默忽略“点路径”键：若某键无法在 base_config 中定位，必须在日志中打印 WARNING。
3. 保持 resume=True，但**必须使用全新输出目录**，避免复用历史结果。

[步骤B：新建搜索空间文件]
- 新建文件 tasks/TASK-09/search_space_stage1.json，内容如下（注意外层 "search_space" 键）：
```
{
  "search_space": {
    "signal.thresholds.active.buy":  [0.6, 0.7, 0.8],
    "signal.thresholds.active.sell": [-0.6, -0.7, -0.8],
    "signal.consistency_min":        [0.20, 0.25, 0.30],
    "components.fusion.w_ofi":       [0.6, 0.7, 0.8],
    "components.fusion.w_cvd":       [0.4, 0.3, 0.2],
    "backtest.take_profit_bps":      [30, 40, 50],
    "backtest.stop_loss_bps":        [20, 30, 40],
    "backtest.min_hold_time_sec":    [60, 120, 180],
    "backtest.slippage_model":       ["static", "piecewise"],
    "backtest.fee_model":            ["taker_static", "maker_taker"]
  }
}
```

[步骤C：执行命令（不要复用旧目录）]
- 在项目根目录执行（Windows PowerShell 或 Bash 均可）：
```
python scripts/run_stage1_optimization.py ^
  --config config/backtest.yaml ^
  --search-space tasks/TASK-09/search_space_stage1.json ^
  --input deploy/data/ofi_cvd ^
  --date 2025-11-09 ^
  --symbols BTCUSDT,ETHUSDT ^
  --minutes 1440 ^
  --method grid ^
  --max-workers 4 ^
  --output runtime/optimizer/stage1_retest_20251110
```
- 若使用 Bash，将换行续行符从 ^ 改为 \\。

[步骤D：运行后自动校验]
1. 确认日志出现“组合数>1”，且打印了前三个组合预览。
2. 打开 runtime/optimizer/stage1_retest_20251110/trial_results.csv，验证下列字段存在：score, net_pnl, max_drawdown, trades_per_hour, pnl_per_trade, cost_ratio, generalization_gap, config_file。
3. 随机抽取 2 个 TRIAL 的 config_file，打开比较相关键值，确认确实不同。
4. 确认同目录生成了 recommended_config.yaml（为 Stage-2 的输入）。

[步骤E：可选 GPU]
- 若设备有 NVIDIA GPU：在运行前设置环境变量 USE_CUDA=1（Windows: set USE_CUDA=1；Linux/macOS: export USE_CUDA=1）。
- 要求：OFI/CVD/成本评估等密集核已支持 cupy/numba-cuda 后端；批次化处理，避免 host↔device 频繁往返。

[输出]
- runtime/optimizer/stage1_retest_20251110/trial_results.csv
- runtime/optimizer/stage1_retest_20251110/recommended_config.yaml
- runtime/optimizer/stage1_retest_20251110/stage1_summary.md（若不存在，请自动生成一个 Markdown 摘要，包含 Top10 表格与关键指标）

[完毕条件（DoD）]
- 组合数 > 1，且日志留存前 3 个组合预览
- trial_results.csv 至少含 10 条记录（如不足，请提示扩大搜索空间）
- Top10 的 cost_ratio <= 0.35，且 generalization_gap <= 0.10（任一超阈需在摘要中标注 WARNING）
- recommended_config.yaml 已产生，且与最佳 TRIAL 参数一致
```

---

## 2) 关键注意事项（避免“每次都一样”）
- 搜索空间必须放在 `"search_space": {...}` 下，每个键**是列表**且至少 2 个取值。
- 不要把多次运行写入同一个 `--output` 目录；本卡默认新建 `runtime/optimizer/stage1_retest_20251110/`。
- 断点续跑是按输出目录识别；目录复用会导致跳过已完成的 TRIAL。
- 日志必须打印“组合数”和“前 3 个组合预览”；这是最可靠的事前校验。

---

## 3) 可直接复制的命令（Bash 版）
```bash
python scripts/run_stage1_optimization.py   --config config/backtest.yaml   --search-space tasks/TASK-09/search_space_stage1.json   --input deploy/data/ofi_cvd   --date 2025-11-09   --symbols BTCUSDT,ETHUSDT   --minutes 1440   --method grid   --max-workers 4   --output runtime/optimizer/stage1_retest_20251110
```

---

## 4) Definition of Done（DoD）
- [ ] 组合数>1 的日志证据（含前三组合预览）
- [ ] `trial_results.csv` ≥ 10 条，且字段齐全（score/net_pnl/max_drawdown/trades_per_hour/pnl_per_trade/cost_ratio/generalization_gap/config_file）
- [ ] Top10 表格已生成到 `stage1_summary.md`，并标注是否满足阈值：`cost_ratio ≤ 35%`、`generalization_gap ≤ 10%`
- [ ] `recommended_config.yaml` 已产出且指向最佳 TRIAL
- [ ] 所有产物归档于 `runtime/optimizer/stage1_retest_20251110/`

---

## 5) 故障排查速查
- **组合数=1**：通常是外层缺少 `"search_space"` 或某些键不是列表；修正后重跑。
- **各 TRIAL 指标完全相同**：多为键路径写错或优化器覆盖失败；从 `config_file` 对比实际参数值。
- **结果太少**：扩大列表取值或新增键；确保分钟数/交易对覆盖足够产生交易样本。
- **重复复用旧结果**：换一个全新 `--output` 目录，或临时把 `resume=False` 验证。

---

## 6) 附：键位示例（常用 dot-path）
- `signal.thresholds.active.buy` / `signal.thresholds.active.sell`
- `signal.consistency_min`
- `components.fusion.w_ofi` / `components.fusion.w_cvd`
- `backtest.take_profit_bps` / `backtest.stop_loss_bps`
- `backtest.min_hold_time_sec`
- `backtest.slippage_model` / `backtest.fee_model`

> 建议先对照 `config/backtest.yaml` 手工修改一项验证“点路径”无误，再加入搜索空间。



参考search_space_stage1_template：
{
  "search_space": {
    "signal.thresholds.active.buy": [
      0.6,
      0.7,
      0.8
    ],
    "signal.thresholds.active.sell": [
      -0.6,
      -0.7,
      -0.8
    ],
    "signal.consistency_min": [
      0.2,
      0.25,
      0.3
    ],
    "components.fusion.w_ofi": [
      0.6,
      0.7,
      0.8
    ],
    "components.fusion.w_cvd": [
      0.4,
      0.3,
      0.2
    ],
    "backtest.take_profit_bps": [
      30,
      40,
      50
    ],
    "backtest.stop_loss_bps": [
      20,
      30,
      40
    ],
    "backtest.min_hold_time_sec": [
      60,
      120,
      180
    ],
    "backtest.slippage_model": [
      "static",
      "piecewise"
    ],
    "backtest.fee_model": [
      "taker_static",
      "maker_taker"
    ]
  }
}














