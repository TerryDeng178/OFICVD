# STAGE-2基线配置文件创建报告

## 概述

**配置文件**: `runtime/optimizer/group_stage2_baseline_trial5.yaml`  
**创建时间**: 2025-11-11  
**状态**: ✅ 已创建并验证

---

## 配置文件内容

### Trial 5 核心参数（固定）

根据F1实验总结报告，Trial 5是唯一满足所有目标条件的trial：
- **win_rate_trades**: 47.37% ✅
- **pnl_net**: $1.06 ✅
- **avg_pnl_per_trade**: $0.06 ✅
- **total_trades**: 19

**核心参数**:
```yaml
signal:
  weak_signal_threshold: 0.76
  consistency_min: 0.53
  min_consecutive_same_dir: 3
  dedupe_ms: 8000

components:
  fusion:
    min_consecutive: 3

execution:
  cooldown_ms: 500
```

### 完整配置结构

配置文件包含以下主要部分：

1. **signal**: 信号生成参数
   - Trial 5基线参数（固定）
   - Regime阈值（F4将调整）
   - 退出后冷静期（F3将启用）

2. **components**: 组件配置
   - fusion权重（F2将调整）
   - fusion其他参数（Trial 5基线）

3. **execution**: 执行参数
   - cooldown_ms（F3将调整）

4. **backtest**: 回测参数
   - 止盈/止损（F5将调整）
   - 时间中性退出参数（F5将调整）

5. **其他**: strategy, risk, aligner, reader, paths等

---

## F2-F5优化方向

### F2 - 融合权重/阈值搜索
**将调整的参数**:
- `components.fusion.w_ofi`: 当前0.6，搜索范围[0.5, 0.7]
- `components.fusion.w_cvd`: 自动计算为1-w_ofi
- `signal.thresholds.quiet.buy/sell`: 当前±1.4，搜索范围
- `signal.thresholds.active.buy/sell`: 当前±1.2，搜索范围

### F3 - 反向防抖 & 连击/冷却联合
**将调整的参数**:
- `signal.min_consecutive_same_dir`: 当前3，搜索范围[3, 4, 5]
- `execution.cooldown_ms`: 当前500，搜索范围[500, 800, 1200]
- `signal.dedupe_ms`: 当前8000，搜索范围[8000, 10000]
- `signal.cooldown_after_exit_sec`: 当前0，F3将启用

### F4 - 场景化阈值
**将调整的参数**:
- `signal.thresholds.quiet.buy/sell`: 当前±1.4，搜索范围
- `signal.thresholds.active.buy/sell`: 当前±1.2，搜索范围

### F5 - 止盈/止损与时间中性退出
**将调整的参数**:
- `backtest.take_profit_bps`: 当前12，搜索范围[12, 15, 18]
- `backtest.stop_loss_bps`: 当前10，搜索范围[8, 10, 12]
- `backtest.min_hold_time_sec`: 当前240，搜索范围[180, 240]

---

## 验证结果

✅ **配置文件已创建**: `runtime/optimizer/group_stage2_baseline_trial5.yaml`  
✅ **Trial 5核心参数已设置**: 所有6个核心参数正确  
✅ **配置结构完整**: 包含所有必要的配置段  
✅ **F2-F5优化标记**: 已添加注释说明哪些参数将被调整

---

## 使用说明

### 运行STAGE-2实验

```powershell
cd F:\OFICVD
$env:PYTHONUTF8=1
python scripts/run_stage2_experiments.py `
  --input deploy/data/ofi_cvd `
  --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --minutes 1440 `
  --groups F2,F3,F4,F5,COMBINED `
  --sink sqlite `
  --max-workers 6
```

### 单独运行各组

```powershell
# F3组（18个组合，最快验证）
python scripts/run_stage2_optimization.py `
  --config runtime/optimizer/group_stage2_baseline_trial5.yaml `
  --search-space tasks/TASK-09/search_space_stage2_f3_anti_flip.yaml `
  --input deploy/data/ofi_cvd `
  --date 2025-11-10 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT `
  --minutes 1440 `
  --max-workers 6 `
  --sink sqlite
```

---

## 注意事项

1. **基线参数固定**: Trial 5的6个核心参数在F2-F5实验中保持不变
2. **参数覆盖**: F2-F5实验只调整各自相关的参数，其他参数使用基线值
3. **数据窗口**: STAGE-2使用24小时窗口（1440分钟），比STAGE-1的60分钟更长
4. **评分权重**: STAGE-2使用新的评分权重（纳入成本和密度）

---

## 下一步

1. ✅ 基线配置文件已创建
2. ⚠️ 运行F3实验验证配置正确性（18个组合，约1-2小时）
3. ⚠️ 如果验证通过，运行所有STAGE-2实验组


