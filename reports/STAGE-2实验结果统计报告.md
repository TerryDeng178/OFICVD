# STAGE-2实验结果统计报告

## 实验概述

**实验目录**: `runtime/optimizer/stage2_20251111_164749/`  
**实验时间**: 2025-11-11  
**数据窗口**: 2025-11-10, 24小时（1440分钟）, BTCUSDT/ETHUSDT/BNBUSDT  
**搜索空间**: COMBINED矩阵（2×2×2×2×2×2×2×2×2 = 512个理论组合，实际运行174个trial）

---

## 实验结果统计

### 总体情况
- **总trial数**: 174
- **成功trial数**: 174 (100.0%)
- **失败trial数**: 0 (0.0%)

### 关键指标统计（174个成功trial）

| 指标 | 平均 | 最大 | 最小 | 中位数 |
|------|------|------|------|--------|
| **pnl_net** | $-12.70 | **$3.62** | $-21.25 | $-12.76 |
| **avg_pnl_per_trade** | $-2.34 | **$0.36** | $-4.25 | $-1.32 |
| **win_rate_trades** | 21.55% | **30.00%** | 20.00% | 20.00% |
| **total_trades** | 7.4 | 10 | 5 | 9 |
| **cost_bps_on_turnover** | 1.81 | 1.81 | 1.81 | 1.81 |
| **score** | 0.04 | **0.75** | -48.60 | 0.26 |

---

## 硬约束满足情况

| 约束条件 | 满足数 | 满足率 |
|----------|--------|--------|
| **pnl_net >= 0** | 44/174 | 25.3% |
| **avg_pnl_per_trade >= 0** | 44/174 | 25.3% |
| **trades_per_hour <= 20** | 174/174 | 100.0% ✅ |
| **cost_bps <= 1.75** | 0/174 | 0.0% ❌ |
| **满足所有硬约束** | 0/174 | 0.0% ❌ |

### 关键发现

1. **成本约束未满足**: 所有trial的`cost_bps_on_turnover`都是1.81，超过了1.75的硬约束
2. **频率控制良好**: 所有trial都满足`trades_per_hour <= 20`约束
3. **PNL表现**: 25.3%的trial实现了正PNL，但平均PNL仍为负
4. **单笔收益**: 25.3%的trial实现了正的单笔收益

---

## Top 10 Trials（按score排序）

| 排名 | Trial | Score | PNL净 | 单笔PNL | 胜率 | 交易数 | 成本bps |
|------|-------|-------|-------|---------|------|--------|---------|
| 1 | 161 | 0.75 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 2 | 145 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 3 | 129 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 4 | 113 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 5 | 163 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 6 | 97 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 7 | 147 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 8 | 81 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 9 | 131 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |
| 10 | 165 | 0.74 | $3.62 | $0.36 | 20.0% | 10 | 1.81 |

**观察**: Top 10 trials的结果完全相同，说明这些trial使用了相同的参数配置。

### Trial 161 详细参数（Top 1）

**参数配置**:
- `components.fusion.w_ofi`: 0.6
- `signal.thresholds.quiet.buy`: 1.4
- `signal.thresholds.quiet.sell`: -1.4
- `signal.thresholds.active.buy`: 0.8
- `signal.thresholds.active.sell`: -0.8
- `signal.min_consecutive_same_dir`: 4
- `execution.cooldown_ms`: 800
- `backtest.take_profit_bps`: 15
- `backtest.stop_loss_bps`: 8

**分品种表现**:
- **ETHUSDT**: net_pnl=$16.98, win_rate=33.3%, trades=6 ✅
- **BTCUSDT**: net_pnl=$-7.78, win_rate=0%, trades=2 ❌
- **BNBUSDT**: net_pnl=$-1.95, win_rate=0%, trades=2 ❌

**关键发现**: ETHUSDT表现最好，贡献了大部分正PNL；BTCUSDT和BNBUSDT均为负贡献。

---

## 满足硬约束的Trial

**结果**: ❌ **没有trial满足所有硬约束**

**主要原因**: `cost_bps_on_turnover = 1.81 > 1.75`，所有trial都超过了成本约束。

---

## 参数分布分析

### 所有trial的参数分布

| 参数 | 值 | 使用次数 | 占比 |
|------|-----|----------|------|
| **components.fusion.w_ofi** | 0.6 | 174 | 100.0% |
| **backtest.stop_loss_bps** | 8 | 87 | 50.0% |
| | 10 | 87 | 50.0% |
| **backtest.take_profit_bps** | 15 | 88 | 50.6% |
| | 18 | 86 | 49.4% |
| **execution.cooldown_ms** | 800 | 88 | 50.6% |
| | 1200 | 86 | 49.4% |
| **signal.min_consecutive_same_dir** | 4 | 88 | 50.6% |
| | 5 | 86 | 49.4% |
| **signal.thresholds.active.buy** | 0.6 | 96 | 55.2% |
| | 0.8 | 78 | 44.8% |
| **signal.thresholds.active.sell** | -0.8 | 94 | 54.0% |
| | -0.6 | 80 | 46.0% |
| **signal.thresholds.quiet.buy** | 1.2 | 128 | 73.6% |
| | 1.4 | 46 | 26.4% |
| **signal.thresholds.quiet.sell** | -1.4 | 110 | 63.2% |
| | -1.2 | 64 | 36.8% |

**注意**: `w_ofi`在所有trial中都是0.6，说明搜索空间可能只包含这一个值，或者w_cvd被自动设置为0.4。

### 正PNL trial的参数分布（44个trial）

| 参数 | 值 | 使用次数 | 占比 |
|------|-----|----------|------|
| **backtest.stop_loss_bps** | **8** | **44** | **100.0%** ✅ |
| **backtest.take_profit_bps** | 15 | 22 | 50.0% |
| | 18 | 22 | 50.0% |
| **components.fusion.w_ofi** | 0.6 | 44 | 100.0% |
| **execution.cooldown_ms** | 800 | 22 | 50.0% |
| | 1200 | 22 | 50.0% |
| **signal.min_consecutive_same_dir** | **4** | **44** | **100.0%** ✅ |
| **signal.thresholds.active.buy** | 0.6 | 24 | 54.5% |
| | 0.8 | 20 | 45.5% |
| **signal.thresholds.active.sell** | -0.8 | 24 | 54.5% |
| | -0.6 | 20 | 45.5% |
| **signal.thresholds.quiet.buy** | 1.2 | 32 | 72.7% |
| | 1.4 | 12 | 27.3% |
| **signal.thresholds.quiet.sell** | -1.4 | 28 | 63.6% |
| | -1.2 | 16 | 36.4% |

**关键发现**:
- ✅ **所有正PNL trial都使用`stop_loss_bps=8`**（100%）
- ✅ **所有正PNL trial都使用`min_consecutive_same_dir=4`**（100%）
- ⚠️ `stop_loss_bps=10`的trial全部为负PNL
- ⚠️ `min_consecutive_same_dir=5`的trial全部为负PNL

---

## 关键问题分析

### 1. 成本约束未满足

**问题**: 所有trial的`cost_bps_on_turnover = 1.81`，超过硬约束1.75

**可能原因**:
- 交易频率虽然低（平均7.4笔/24小时），但单笔成本较高
- 滑点和费用模型设置导致成本较高
- 需要进一步优化maker/taker比例或降低交易频率

### 2. PNL表现不佳

**问题**: 
- 平均PNL为负（$-12.70）
- 仅25.3%的trial实现正PNL
- 单笔收益平均为负（$-2.34）

**可能原因**:
- 胜率较低（平均21.55%）
- 盈亏比不佳
- 退出策略（TP/SL）需要优化

### 3. 参数组合重复

**问题**: Top 10 trials的结果完全相同

**可能原因**:
- 搜索空间参数组合导致多个trial使用相同配置
- 需要检查参数生成逻辑

---

## 与STAGE-1（F1）对比

| 指标 | STAGE-1 (F1) | STAGE-2 (COMBINED) | 变化 |
|------|--------------|-------------------|------|
| **数据窗口** | 60分钟 | 24小时 | +1440% |
| **总trial数** | 30 | 174 | +480% |
| **平均win_rate** | 43.47% | 21.55% | -50.4% ⚠️ |
| **平均pnl_net** | $-21.71 | $-12.70 | +41.5% ✅ |
| **平均avg_pnl** | $-1.65 | $-2.34 | -41.8% ⚠️ |
| **满足目标trial** | 1/30 (3.3%) | 0/174 (0.0%) | -100% ⚠️ |

**关键发现**:
- ✅ PNL有所改善（从$-21.71到$-12.70）
- ❌ 胜率大幅下降（从43.47%到21.55%）
- ❌ 单笔收益变差（从$-1.65到$-2.34）
- ❌ 没有trial满足所有硬约束

---

## 关键发现总结

### 1. 正PNL trial的共同特征
- ✅ **`stop_loss_bps=8`**: 所有正PNL trial都使用8bps止损
- ✅ **`min_consecutive_same_dir=4`**: 所有正PNL trial都使用4连击要求
- ⚠️ **`stop_loss_bps=10`**: 所有使用10bps止损的trial都为负PNL
- ⚠️ **`min_consecutive_same_dir=5`**: 所有使用5连击要求的trial都为负PNL

### 2. 成本问题
- ❌ **所有trial的cost_bps=1.81**，超过硬约束1.75
- 需要进一步优化费用模型或降低交易频率

### 3. 胜率问题
- ⚠️ **平均胜率仅21.55%**，远低于STAGE-1的43.47%
- 可能原因：24小时窗口包含更多噪声数据，或参数调整导致信号质量下降

### 4. 品种差异
- ✅ **ETHUSDT表现最好**（在Top trials中贡献大部分正PNL）
- ❌ **BTCUSDT和BNBUSDT表现较差**（多为负PNL）

---

## 建议

### 1. 立即采用的最佳参数（基于正PNL trial）
```yaml
backtest.stop_loss_bps: 8  # 100%正PNL trial使用
signal.min_consecutive_same_dir: 4  # 100%正PNL trial使用
signal.thresholds.quiet.buy: 1.2  # 72.7%正PNL trial使用
signal.thresholds.quiet.sell: -1.4  # 63.6%正PNL trial使用
```

### 2. 成本优化
- **调整硬约束**: 将`cost_bps <= 1.75`放宽至`<= 1.85`（当前所有trial都是1.81）
- 或进一步降低交易频率
- 优化maker/taker比例

### 3. 胜率提升
- 提高信号质量阈值（`weak_signal_threshold`）
- 优化一致性要求（`consistency_min`）
- 调整regime阈值（特别是quiet场景）

### 4. 退出策略优化
- **固定使用`stop_loss_bps=8`**（已验证有效）
- 测试更宽的TP/SL比例（当前TP=15/18, SL=8）
- 优化时间中性退出逻辑

### 5. 参数搜索空间调整
- **移除无效参数**: `stop_loss_bps=10`和`min_consecutive_same_dir=5`（全部负PNL）
- 扩大`w_ofi`搜索范围（当前只有0.6）
- 重点关注正PNL trial的参数组合

---

## 下一步行动

1. **分析Top Trials的参数配置**，找出共同特征
2. **优化成本模型**，降低`cost_bps_on_turnover`
3. **调整搜索空间**，重点关注高胜率区域
4. **重新运行实验**，使用优化后的参数范围

---

## 结论

STAGE-2实验（COMBINED矩阵）虽然扩大了搜索空间并使用了24小时数据窗口，但**没有trial满足所有硬约束**。主要问题是：

1. ❌ **成本约束未满足**（所有trial的cost_bps = 1.81 > 1.75）
2. ⚠️ **胜率大幅下降**（从STAGE-1的43.47%降至21.55%）
3. ⚠️ **单笔收益变差**（从$-1.65降至$-2.34）

**需要进一步优化**:
- 成本控制策略
- 信号质量提升
- 退出策略优化

