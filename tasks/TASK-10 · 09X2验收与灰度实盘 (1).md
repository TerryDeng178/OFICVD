# ✅TASK-10 · 09X2 验收与灰度实盘
**目标**：在你完成 **TASK-09X2（Stage1→Stage2 自动化 + Top10）** 后，基于 `Top10` 结果**冻结 Champion 配置**、完成**再验证（Train/Val/OOS）**、**标定风控墙**，并以 **灰度（模拟盘/最小真实资金）** 运行，形成标准化 **日报/周报** 与 **回滚机制**。

---

## 0) 先决条件（Prerequisites）
- 已完成 **TASK-09X2** 并产出：
  - `top10.csv` / `top10.md`（含 `score, net_pnl, cost_ratio, trades_per_hour, pnl_per_trade, max_dd, generalization_gap` 等关键列）
  - `recommended_config.yaml`（09X2 的建议参数）
  - `pareto.png`（`pnl_per_trade` vs `cost_ratio` 前沿）
- 目录/清单统一：所有 trial 目录均含 4 件套：`trades.jsonl / pnl_daily.jsonl / metrics.json / run_manifest.json`。
- 数据区间：至少包含 **最近 7–14 天** 的训练/验证窗口；可额外预留 **最近 2–3 天** 作为 OOS（Out-of-Sample）前瞻验证。

---

## 1) 统一约定（Global Conventions）
- 环境变量：
  - `BACKTEST_OUTPUT_DIR`：09X2 产物根目录（只读）
  - `T10_OUTPUT_DIR`：本任务输出根目录（默认：`./artifacts/TASK-10`）
  - `USE_CUDA`：`0|1`（GPU 可选）
- 目录规范：
  ```text
  {T10_OUTPUT_DIR}/
    champion/
      config_frozen.yaml         # 选中的“冠军”参数（冻结版本）
      risk_wall.yaml             # 风控墙（仓位、回撤、冷却）
      manifest.json              # 选拔与验证过程元信息（区间、版本、阈值）
    validation/
      train_val_report.md        # 训练/验证对比 + 稳健性指标
      oos_forward_report.md      # OOS（前瞻）窗口报告
      metrics.json               # 关键指标聚合
    grayscale_run/
      paper/                     # 模拟盘输出（首选）
      tiny_live/                 # 最小资金真实盘（可选）
    monitors/
      prometheus_rules.yaml      # 告警规则
      grafana.json               # 看板模板（可选）
    logs/
      *.log
  ```

---

## 2) 关键指标与门槛（Gating）
- **稳定性**：`generalization_gap ≤ 10%`（Train vs Val 的关键指标相对差异）
- **成本占比**：`cost_ratio ≤ 35%`（费用+滑点 / 毛利）
- **回撤**：`max_drawdown ≤ 8%`（Val 窗口）
- **频率**：`trades_per_hour ≥ 1.0`（避免过稀导致统计不稳）
- **收益密度**：`pnl_per_trade ≥ 0` 且 `p50(pnl_per_trade) ≥ 0`
> 任何一项未达标 → **NO-GO**，回到 09X2 继续调参/裁剪。

---

## 3) 任务分解（Steps）

### Step A. Champion 选拔与冻结
1. **Champion 选择规则**（建议）：
   - 以 09X2 的 `score` 排序为主；剔除 `cost_ratio` 超阈、`generalization_gap` 超阈、`max_dd` 超阈的候选。
   - 在剩余候选中，优先 **Pareto 前沿** 的配置；若并列，选 `trades_per_hour` 更高者。
2. **冻结**：将选中的配置写入 `champion/config_frozen.yaml`；附上 `manifest.json`（版本、区间、阈值、指纹）。

> 若你已有 `recommended_config.yaml`，本步骤可作为校验/微调后再次冻结。

### Step B. 训练/验证/前瞻再验证（Train/Val/OOS）
- 训练（Train）：如 `T-14d ~ T-7d`
- 验证（Val）：如 `T-7d ~ T-1d`
- 前瞻（OOS Forward）：如 `T-1d ~ T`（或未来模拟盘）

**执行命令（示例）**：
```bash
# 1) Train 验证
python scripts/run_validate.py \
  --config champion/config_frozen.yaml \
  --dates 2025-11-01,2025-11-07 \
  --out {T10_OUTPUT_DIR}/validation/train \
  --sink jsonl

# 2) Val 验证
python scripts/run_validate.py \
  --config champion/config_frozen.yaml \
  --dates 2025-11-08,2025-11-09 \
  --out {T10_OUTPUT_DIR}/validation/val \
  --sink jsonl

# 3) OOS（前瞻）
python scripts/run_validate.py \
  --config champion/config_frozen.yaml \
  --dates 2025-11-09,2025-11-10 \
  --out {T10_OUTPUT_DIR}/validation/oos \
  --sink jsonl \
  --enable report
```

> 若脚本尚未存在，请在 Cursor 中按现有 `orchestrator`/`backtest_runner` 模式生成同名脚本，参数对齐到 09X2。

### Step C. 风控墙（Risk Wall）标定
新建 `champion/risk_wall.yaml`：
```yaml
max_position_usdt: 500        # 单品种最大名义仓位
max_concurrent_symbols: 2     # 同时持仓的交易对数
daily_max_loss_usdt: 150      # 当日最大亏损（触发停机）
cooldown_on_flip_s: 300       # 反手后冷却秒数
cooldown_on_drawdown_s: 600   # 触发回撤阈值后的冷却
max_orders_per_minute: 30
slippage_bps_guard: 8         # 单笔滑点上限（基于估计）
fee_bps_guard: 5              # 单笔费率上限
```

### Step D. 灰度运行（优先模拟盘，其次最小真实资金）
```bash
# 模拟盘（paper）
python scripts/run_paper.py \
  --config champion/config_frozen.yaml \
  --risk champion/risk_wall.yaml \
  --out {T10_OUTPUT_DIR}/grayscale_run/paper \
  --minutes 120 \
  --enable report

# 最小真实资金（谨慎）
python scripts/run_tiny_live.py \
  --config champion/config_frozen.yaml \
  --risk champion/risk_wall.yaml \
  --out {T10_OUTPUT_DIR}/grayscale_run/tiny_live \
  --minutes 60 \
  --notional_usdt 50 \
  --enable report
```
> 真实盘前必须完成 **Prometheus/Grafana** 监控与告警。

### Step E. 监控与告警（Pushgateway/Prometheus）
- 输出指标：`trades_per_hour, slippage_bps, fee_bps, cost_ratio, win_rate, pnl_per_trade, max_dd, error_rate, latency_ms`。
- 阈值告警示例（`monitors/prometheus_rules.yaml`）：
```yaml
groups:
- name: trading.rules
  rules:
  - alert: HighErrorRate
    expr: error_rate > 0.05
    for: 5m
    labels: { severity: page }
    annotations: { summary: "Error rate > 5%" }
  - alert: AbnormalSlippage
    expr: slippage_bps > 12
    for: 3m
    labels: { severity: warn }
    annotations: { summary: "Slippage above 12 bps" }
```

### Step F. 报告产出与归档
- `validation/train_val_report.md`：Train vs Val 对比；`generalization_gap`、`max_dd`、`cost_ratio`。
- `validation/oos_forward_report.md`：OOS 指标与图；是否满足 Gating。
- `grayscale_run/*/report.md`：灰度运行摘要；告警统计；改进建议。

---

## 4) GPU（可选加速，一键开关）
- 运行前设置：`export USE_CUDA=1`（Windows `set USE_CUDA=1`）。
- 若使用 GPU：将 OFI/CVD/成本评估等密集核切到 `cupy/numba-cuda` 后端；批量化输入（≥ 数百万行），减少 host↔device 往返。
- 保障：先用小样本运行 `np.allclose(cpu, gpu, rtol=1e-6)` 校验一致性。

---

## 5) Definition of Done（DoD）
- [ ] `champion/config_frozen.yaml` 与 `champion/manifest.json` 已生成；指纹与区间清晰
- [ ] `validation/train_val_report.md` 与 `oos_forward_report.md` 完成；Gating 全部通过
- [ ] `risk_wall.yaml` 成立且已在灰度运行中生效（有日志/指标证明）
- [ ] 灰度运行 **≥ 2 小时** 的稳定记录；无 P0 告警
- [ ] 日报/周报产出模板落地；自动入库到 `T10_OUTPUT_DIR`
- [ ] 设立 **回滚机制**：若任一阈值触发 → 自动停机 + 切回上一个稳定版本

---

## 6) 风险与缓解
- **数据/口径不一致** → 第 0 步严格检查 trial 4 件套与字段口径；不通过即中止
- **成本/滑点突增** → 风控墙 + 告警；阈值触发后自动降频/停机
- **GPU 不稳定** → 切回 CPU/Numba；保持相同结果口径

---

## 7) 建议执行顺序（光标可直接跑）
1. 冒烟：检查 09X2 产物与 trial 4 件套
2. `Champion` 选拔 + 冻结
3. Train/Val/OOS 批量再验证（自动生成三份报告）
4. 标定/落地风控墙
5. 灰度运行（先 Paper，再 Tiny Live）并开启监控
6. 验收 DoD → GO/NO-GO 决策 → 进入真正实盘任务

---

## 8) 备注
- 本任务卡不改动 09X2 的产物定义，仅在其之上增加“验收→风控→灰度实盘”的业务闭环。
- 若你的仓库脚本命名不同，请在 Cursor 中做一层 **CLI 适配**，参数名保持与本卡一致，方便自动化流水线复用。
