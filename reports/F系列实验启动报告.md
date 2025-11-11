# F系列实验启动报告

## 启动时间
2025-11-11

## 实验概述

F系列实验（纯STAGE1版本）已启动，专注于**胜率和PNL**优化。

---

## 实验组配置

### F1｜入口质量闸（弱信号/一致性/连击）
- **组合数**: 8×11×3×3×3×3 = 7128（限制为200个）
- **搜索维度**:
  - `weak_signal_threshold`: 0.75 → 0.82（步长0.01）
  - `consistency_min`: 0.45 → 0.55（步长0.01）
  - `min_consecutive`: 3 → 5
  - `dedupe_ms`: 4000 / 6000 / 8000
  - `cooldown_ms`: 500 / 800 / 1200

### F2｜融合权重与阈值（提"信号纯度"）
- **组合数**: 3×3×3×3×3 = 243
- **搜索维度**:
  - `w_ofi / w_cvd`: {(0.7,0.3), (0.6,0.4), (0.5,0.5)}（自动确保和为1.0）
  - `thresholds.active.buy/sell`: 1.2 / 1.5 / 1.8
  - `adaptive_cooldown_k`: 0.8 / 1.0 / 1.2

### F3｜反向防抖 & 翻向重臂（抑制亏损翻手）
- **组合数**: 3×3 = 9
- **搜索维度**:
  - `flip_rearm_margin`: 0.5 / 0.8 / 1.0
  - `cooldown_after_exit_sec`: 60 / 120 / 180

### F4｜场景化阈值（活跃/安静分档）
- **组合数**: 1（固定偏移）
- **搜索维度**:
  - A_H/Q_H场景：`weak +0.02`、`consistency_min +0.02`、`min_consecutive +1`
  - A_L/Q_L场景：使用全局基线

---

## 运行参数

- **输入目录**: `deploy/data/ofi_cvd`
- **回测日期**: `2025-11-10`
- **交易对**: `BTCUSDT,ETHUSDT,BNBUSDT`
- **回测时长**: `60分钟`
- **信号输出**: `sqlite`
- **最大并发**: `6`

---

## 目标与判据

### 主要指标（3窗口中位数）
- **win_rate_trades ≥ 35%**
- **avg_pnl_per_trade ≥ 0**
- **pnl_net ≥ 0**

### 约束（软）
- **trades_per_hour ≤ 30**（频率这轮不做硬卡，只防"刷频提胜率"）

---

## 运行状态

### 已启动的实验（2025-11-11 14:40）
- ✅ **F1**: 入口质量闸（200个组合，后台运行中）
- ✅ **F2**: 融合权重与阈值（243个组合，后台运行中）
- ✅ **F3**: 反向防抖 & 翻向重臂（9个组合，后台运行中）
- ✅ **F4**: 场景化阈值（1个组合，后台运行中）

### 修复记录
- ✅ **双SINK检查修复**: 修复了`replay_harness.py`不支持`dual` sink的问题，改为分别运行jsonl和sqlite进行比较
- ✅ **单组合验证修复**: 允许F4等单组合配置（固定偏移场景）

### 预计完成时间
- **F3**: ~10-15分钟（9个组合 × 3个交易对 × 60分钟）
- **F4**: ~5-10分钟（1个组合 × 3个交易对 × 60分钟）
- **F2**: ~2-3小时（243个组合 × 3个交易对 × 60分钟）
- **F1**: ~2-3小时（200个组合 × 3个交易对 × 60分钟）

---

## 输出目录

各组的输出将保存在：
- `runtime/optimizer/stage1_YYYYMMDD_HHMMSS/`

每个trial的输出包含：
- `trial_X_config.yaml` - 试验配置
- `trial_X_output/` - 回测输出（signals.db, trades.jsonl, metrics.json等）
- `trial_results.json` - 所有trial的结果汇总
- `trial_results.csv` - CSV格式的结果
- `trial_manifest.json` - 运行清单

---

## 监控命令

### 检查运行状态
```powershell
cd F:\OFICVD
python scripts/check_running_experiments.ps1
```

### 查看最新输出
```powershell
# 查看最新的优化输出目录
Get-ChildItem runtime\optimizer\stage1_* | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

### 停止实验（如需要）
```powershell
cd F:\OFICVD
.\scripts\stop_experiments.ps1
```

---

## 后续步骤

1. **等待实验完成**（预计2-3小时）
2. **分析结果**：检查各组的`trial_results.json`和`trial_results.csv`
3. **验证判据**：确认是否满足`win_rate_trades≥35%`、`avg_pnl_per_trade≥0`、`pnl_net≥0`
4. **选择最优参数**：从满足判据的trial中选择Top-K
5. **进入下一轮优化**：基于最优参数进行微调

---

## 参考文档

- `reports/F系列实验执行说明-STAGE1.md` - 详细执行说明
- `reports/F2F3F4功能实现报告.md` - 功能实现说明
- `reports/F3与TradeSimulator集成完成报告.md` - F3集成说明
- `reports/F2F3F4单元测试报告.md` - 单元测试报告

