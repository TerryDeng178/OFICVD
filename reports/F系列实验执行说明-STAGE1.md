# F系列实验执行说明（纯STAGE1版本）

## 概述

F系列实验已重排为**纯STAGE1的四条实验线**，专注于**胜率和PNL**，不再触碰执行/成本。

## 目标与判据（STAGE1）

### 主要指标（3窗口中位数）
- **win_rate_trades ≥ 35%**
- **avg_pnl_per_trade ≥ 0**
- **pnl_net ≥ 0**

### 约束（软）
- **trades_per_hour ≤ 30**（频率这轮不做硬卡，只防"刷频提胜率"）

### 执行要求
- **固定Sink**：`--sink sqlite`
- **双SINK前置Gate**：脚本已内置fail-closed检查（2分钟预检）

---

## 实验组列表

### F1｜入口质量闸（弱信号/一致性/连击）

**动因**：弱信号节流/一致性门槛是提升胜率与PnL的第一性闸门

**搜索维度**：
- `weak_signal_threshold`: 0.75 → 0.82（步长0.01，共8个值）
- `consistency_min`: 0.45 → 0.55（步长0.01，共11个值）
- `min_consecutive`（连击确认）：3 → 5（步长1，共3个值）
- `dedupe_ms`: 4000 / 6000 / 8000（共3个值）
- `cooldown_ms`: 500 / 800 / 1200（共3个值）

**组合数**：8×11×3×3×3×3 = 7128（可用`--max-trials`限制）

**放行判据**：
- 满足"胜率、单笔≥0、净PnL≥0"的最小组合即入围
- 频率≤30/h仅作警戒

---

### F2｜融合权重与阈值（提"信号纯度"）

**动因**：OFI/CVD融合权重与阈值是胜率/PNL的"质变旋钮"

**搜索维度**：
- `components.fusion.w_ofi / w_cvd`: {(0.7,0.3), (0.6,0.4), (0.5,0.5)}（需确保w_ofi+w_cvd=1.0）
- `thresholds.active.buy/sell`：1.2 / 1.5 / 1.8（对应更强的打分门槛）
- `adaptive_cooldown_k`: 0.8 / 1.0 / 1.2

**组合数**：3×3×3×3×3 = 243（需在代码中确保w_ofi+w_cvd=1.0）

**放行判据**：
- 同F1的三条主判据
- 若频率上升>20%则降权

---

### F3｜反向防抖 & 翻向重臂（抑制亏损翻手）

**动因**：反向防抖检查可阻断"来回亏损的翻手单"

**搜索维度**：
- `flip_rearm_margin`: 0.5 / 0.8 / 1.0
- `cooldown_after_exit_sec`: 60 / 120 / 180（从信号侧实现"退出后冷静期"）

**组合数**：3×3 = 9

**放行判据**：
- 在持仓回撤/连环亏损明显收敛、且三条主判据成立时入围

**注意**：需要在代码中实现`cooldown_after_exit_sec`支持

---

### F4｜场景化阈值（活跃/安静分档）

**动因**：不同市场状态使用不同门槛，常能"提胜率不增频"

**搜索维度**：
- 为A_H/Q_H：`weak +0.02`、`consistency_min +0.02`、`min_consecutive +1`
- 为A_L/Q_L：使用全局基线（来自F1的最优解）

**组合数**：1（固定偏移，需实现`scenario_overrides`支持）

**放行判据**：
- 在活跃时段胜率/单笔显著提升，且整体频率不反弹

**注意**：需要在代码中实现`scenario_overrides`支持

---

## 运行命令

### 快速启动（所有组）

```powershell
cd F:\OFICVD
$env:PYTHONUTF8=1
python scripts/run_f_experiments.py `
  --input deploy/data/ofi_cvd `
  --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --minutes 60 `
  --groups F1,F2,F3,F4 `
  --sink sqlite `
  --max-workers 6
```

### 单独运行各组

#### F1（入口质量闸）

```powershell
python scripts/run_stage1_optimization.py `
  --config runtime/optimizer/group_f1_entry_gating.yaml `
  --search-space tasks/TASK-09/search_space_f1.json `
  --input deploy/data/ofi_cvd --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --method grid --max-trials 200 `
  --max-workers 6 --sink sqlite
```

#### F2（融合权重与阈值）

```powershell
python scripts/run_stage1_optimization.py `
  --config runtime/optimizer/group_f2_fusion_threshold.yaml `
  --search-space tasks/TASK-09/search_space_f2.json `
  --input deploy/data/ofi_cvd --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --method grid `
  --max-workers 6 --sink sqlite
```

**注意**：需要在代码中确保`w_ofi + w_cvd = 1.0`

#### F3（反向防抖 & 翻向重臂）

```powershell
python scripts/run_stage1_optimization.py `
  --config runtime/optimizer/group_f3_reverse_prevention.yaml `
  --search-space tasks/TASK-09/search_space_f3.json `
  --input deploy/data/ofi_cvd --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --method grid `
  --max-workers 6 --sink sqlite
```

**注意**：需要在代码中实现`cooldown_after_exit_sec`支持

#### F4（场景化阈值）

```powershell
python scripts/run_stage1_optimization.py `
  --config runtime/optimizer/group_f4_scenario_threshold.yaml `
  --search-space tasks/TASK-09/search_space_f4.json `
  --input deploy/data/ofi_cvd --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --method grid `
  --max-workers 6 --sink sqlite
```

**注意**：需要在代码中实现`scenario_overrides`支持

---

## 执行建议（统一节奏）

### 1. 三窗口交叉验证
- 每个试验对3个不同时段跑STAGE1
- 评分取中位数，抗偶然

### 2. 早停
- `--method grid`可配`--max-trials`做剪枝
- `--method random`则用`--early-stop-rounds`

### 3. 候选Top-K
- 每条支线留3–5组满足主判据的参数
- 进入下一轮"合并微调"

### 4. 保持双SINK预检/固定Sink
- 每批次开跑前先过2分钟双SINK等价性
- 全批固定`--sink sqlite`以保证口径一致

---

## 评分权重

所有F组使用相同的评分权重（STAGE1专注胜率和PNL）：

```json
{
  "win_rate_trades": 0.40,
  "pnl_net": 0.30,
  "avg_pnl_per_trade": 0.20,
  "trades_per_hour": 0.10,
  "trades_per_hour_threshold": 30,
  "cost_bps_on_turnover": 0.0
}
```

**注意**：`cost_bps_on_turnover`权重设为0，STAGE1暂不看成本

---

## 报表口径

- **胜率/PNL的读取**：统一用`metrics.py`聚合输出
  - `win_rate_trades` / `pnl_net` / `cost_bps_on_turnover`等
- **避免人为计算偏差**：使用标准metrics口径

---

## 待实现功能

### F2
- **w_ofi + w_cvd = 1.0约束**：需要在优化器中确保融合权重和为1.0

### F3
- **cooldown_after_exit_sec**：需要在信号生成器中实现退出后冷静期

### F4
- **scenario_overrides**：需要在配置加载和信号生成器中实现场景化覆写

---

## 参考文档

- `runtime/optimizer/group_f*.yaml`：F组配置文件
- `tasks/TASK-09/search_space_f*.json`：F组搜索空间
- `scripts/run_f_experiments.py`：F系列实验运行脚本
- `scripts/run_stage1_optimization.py`：Stage1优化脚本

