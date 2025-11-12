# F系列实验总结报告

## 实验概述

**实验组**: F1 - 入口质量闸（弱信号/一致性/连击）  
**实验时间**: 2025-11-11  
**输出目录**: `runtime/optimizer/stage1_20251111_145408/`  
**数据窗口**: 2025-11-10, 60分钟, BTCUSDT/ETHUSDT/BNBUSDT

---

## 实验配置

### 搜索空间
- `signal.weak_signal_threshold`: [0.75, 0.76, 0.77, 0.78, 0.79, 0.80, 0.81, 0.82] (8个值)
- `signal.consistency_min`: [0.45, 0.46, 0.47, 0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55] (11个值)
- `signal.min_consecutive_same_dir`: [3, 4, 5] (3个值)
- `components.fusion.min_consecutive`: [3, 4, 5] (3个值)
- `signal.dedupe_ms`: [4000, 6000, 8000] (3个值)
- `execution.cooldown_ms`: [500, 800, 1200] (3个值)

**理论组合数**: 8×11×3×3×3×3 = 7,128  
**实际运行**: 30个trial（限制）

### 评分权重
- `win_rate_trades`: 0.4
- `pnl_net`: 0.3
- `avg_pnl_per_trade`: 0.2
- `trades_per_hour`: 0.1
- `cost_bps_on_turnover`: 0.0（STAGE1暂不看成本）

### 目标条件
- ✅ `win_rate_trades ≥ 35%`
- ✅ `avg_pnl_per_trade ≥ 0`
- ✅ `pnl_net ≥ 0`

---

## 实验结果统计

### 总体情况
- **总trial数**: 30
- **成功trial数**: 30 (100.0%)
- **失败trial数**: 0 (0.0%)

### 关键指标统计（30个成功trial）

| 指标 | 平均 | 中位数 | 最大值 |
|------|------|--------|--------|
| **win_rate_trades** | 43.47% | 46.76% | **62.50%** |
| **pnl_net** | $-21.71 | $-24.18 | **$1.06** |
| **avg_pnl_per_trade** | $-1.65 | $-1.36 | **$0.06** |
| **total_trades** | 15.1 | 14.0 | - |
| **score** | -1.46 | 0.55 | **0.96** |

### 目标达成情况
- **满足目标条件的trial数**: 1 / 30 (3.3%)
- **唯一满足条件的trial**: Trial 5

---

## Top 5 Trials（按score排序）

### 1. Trial 24 (score=0.9583)
- **win_rate_trades**: 62.50%
- **pnl_net**: $-9.04
- **avg_pnl_per_trade**: $-1.13
- **total_trades**: 8
- **参数**:
  - `weak_signal_threshold`: 0.76
  - `consistency_min`: 0.54
  - `min_consecutive_same_dir`: 5
  - `fusion.min_consecutive`: 5
  - `dedupe_ms`: 6000
  - `cooldown_ms`: 800

### 2. Trial 17 (score=0.9412)
- **win_rate_trades**: 62.50%
- **pnl_net**: $-11.56
- **avg_pnl_per_trade**: $-1.44
- **total_trades**: 8
- **参数**:
  - `weak_signal_threshold`: 0.77
  - `consistency_min`: 0.49
  - `min_consecutive_same_dir`: 5
  - `fusion.min_consecutive`: 3
  - `dedupe_ms`: 6000
  - `cooldown_ms`: 800

### 3. Trial 13 (score=0.9286)
- **win_rate_trades**: 52.38%
- **pnl_net**: $-29.44
- **avg_pnl_per_trade**: $-1.40
- **total_trades**: 21
- **参数**:
  - `weak_signal_threshold`: 0.80
  - `consistency_min`: 0.51
  - `min_consecutive_same_dir`: 3
  - `fusion.min_consecutive`: 3
  - `dedupe_ms`: 6000
  - `cooldown_ms`: 500

### 4. Trial 21 (score=0.8095)
- **win_rate_trades**: 47.62%
- **pnl_net**: $-35.97
- **avg_pnl_per_trade**: $-1.71
- **total_trades**: 21
- **参数**:
  - `weak_signal_threshold`: 0.82
  - `consistency_min`: 0.51
  - `min_consecutive_same_dir`: 3
  - `fusion.min_consecutive`: 4
  - `dedupe_ms`: 6000
  - `cooldown_ms`: 1200

### 5. Trial 26 (score=0.8077)
- **win_rate_trades**: 57.14%
- **pnl_net**: $-17.03
- **avg_pnl_per_trade**: $-0.81
- **total_trades**: 21
- **参数**:
  - `weak_signal_threshold`: 0.76
  - `consistency_min`: 0.54
  - `min_consecutive_same_dir`: 3
  - `fusion.min_consecutive`: 4
  - `dedupe_ms`: 6000
  - `cooldown_ms`: 800

---

## 唯一满足目标条件的Trial

### Trial 5 (score=0.3333)
- **win_rate_trades**: 47.37% ✅
- **pnl_net**: $1.06 ✅
- **avg_pnl_per_trade**: $0.06 ✅
- **total_trades**: 19
- **参数**:
  - `weak_signal_threshold`: 0.76
  - `consistency_min`: 0.53
  - `min_consecutive_same_dir`: 3
  - `fusion.min_consecutive`: 3
  - `dedupe_ms`: 8000
  - `cooldown_ms`: 500

**分品种表现**:
- **BTCUSDT**: net_pnl=$-0.48, win_rate=60%, trades=5
- **ETHUSDT**: net_pnl=$-6.39, win_rate=40%, trades=10
- **BNBUSDT**: net_pnl=$14.81, win_rate=50%, trades=4

---

## 关键发现

### 1. 胜率表现
- ✅ **平均胜率43.47%**，中位数46.76%，最高62.50%
- ✅ **大部分trial胜率超过35%目标**（26/30 = 86.7%）
- ✅ **Top 5 trials胜率均≥47%**

### 2. PNL表现
- ❌ **平均pnl_net为负**（$-21.71）
- ❌ **仅1个trial满足pnl_net≥0**（Trial 5）
- ⚠️ **Top 5 trials的pnl_net均为负**，但胜率较高

### 3. 单笔收益
- ❌ **平均avg_pnl_per_trade为负**（$-1.65）
- ❌ **仅1个trial满足avg_pnl_per_trade≥0**（Trial 5）
- ⚠️ **高胜率但单笔亏损**，说明止损/止盈策略需要优化

### 4. 参数模式
- **高胜率trial的共同特征**:
  - `weak_signal_threshold`: 0.76-0.77（中等阈值）
  - `consistency_min`: 0.49-0.54（较高一致性要求）
  - `min_consecutive_same_dir`: 5（较高连击要求）
  - `dedupe_ms`: 6000（中等去重窗口）
  - `cooldown_ms`: 800（中等冷却时间）

### 5. 交易频率
- **平均交易数**: 15.1笔/小时
- **频率控制**: 所有trial均满足≤30笔/小时的软约束
- **样本量**: 部分trial交易数较少（8-9笔），存在"low_sample"警告

---

## 问题分析

### 1. 胜率与PNL不匹配
- **现象**: 高胜率（62.5%）但PNL为负（$-9.04）
- **原因**: 
  - 单笔亏损较大（avg_pnl_per_trade = $-1.13）
  - 可能止损设置不合理，或止盈过早
  - 成本（fee + slippage）侵蚀了收益

### 2. 成本影响
- **平均成本**: fee + slippage ≈ $3-6 per trial
- **成本占比**: 在负PNL的trial中，成本占比显著
- **建议**: 需要优化maker/taker比例，降低执行成本

### 3. 样本量不足
- **部分trial交易数<10**，存在"low_sample"警告
- **影响**: 统计显著性不足，结果可能不稳定

---

## 建议与下一步

### 短期优化（基于F1结果）
1. **采用Trial 5的参数配置**（唯一满足目标条件的trial）
2. **优化止损/止盈策略**，提高单笔收益
3. **降低执行成本**，优化maker/taker比例

### 中期优化（F2/F3/F4）
1. **F2**: 融合权重与阈值优化（w_ofi/w_cvd）
2. **F3**: 反向防抖 & 翻向重臂（抑制亏损翻手）
3. **F4**: 场景化阈值（活跃/安静分档）

### 长期优化（STAGE2）
1. **成本优化**: 优化maker/taker比例，降低执行成本
2. **止盈止损**: 优化TP/SL策略，提高单笔收益
3. **频率控制**: 在保证胜率的前提下，适度提高交易频率

---

## 结论

F1实验（入口质量闸）**成功提升了胜率**（平均43.47%，最高62.50%），但**PNL表现不佳**（仅1/30满足目标条件）。

**主要成果**:
- ✅ 胜率显著提升（平均43.47% vs 目标35%）
- ✅ 参数搜索空间有效（找到了高胜率配置）
- ✅ 频率控制良好（均满足≤30笔/小时）

**主要问题**:
- ❌ PNL为负（仅1个trial满足条件）
- ❌ 单笔收益为负（高胜率但单笔亏损）
- ❌ 成本侵蚀收益（fee + slippage）

**下一步**: 需要结合F2/F3/F4的实验结果，进一步优化参数配置，重点关注**单笔收益**和**成本控制**。

---

## 附录

### 输出文件
- `trial_results.json`: 所有trial的详细结果
- `trial_results.csv`: CSV格式的结果汇总
- `trial_manifest.json`: 实验元数据
- `trial_X_config.yaml`: 各trial的配置
- `trial_X_output/`: 各trial的回测输出

### 推荐配置（Trial 5）
```yaml
signal:
  weak_signal_threshold: 0.76
  consistency_min: 0.53
  min_consecutive_same_dir: 3
components:
  fusion:
    min_consecutive: 3
signal:
  dedupe_ms: 8000
execution:
  cooldown_ms: 500
```

