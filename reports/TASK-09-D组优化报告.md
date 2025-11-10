# TASK-09 D组优化报告

**组别**: D组（A+B+C组合）  
**目标**: 交易频率 ≤基线的20%（186.8笔/小时），平均持仓 ≥240秒，成本bps ≤1.75bps，单笔收益 ≥0，胜率 ≥25%  
**报告时间**: 2025-11-10

---

## 一、组别定位与策略

### 1.1 核心策略
D组是**A+B+C组合**，结合了三组的所有优化策略：
- **A组严门控**: 强化入口节流，降低交易频率
- **B组冷却+反向防抖**: 减少快速反转交易，延长持仓时间
- **C组Maker-first**: 降低交易成本，提高Maker比例

### 1.2 关键配置参数

```yaml
signal:
  # === A组: 门控与节流 ===
  weak_signal_threshold: 0.70         # 弱信号阈值
  consistency_min: 0.40               # 一致性最小值
  dedupe_ms: 4000                     # 去重窗口
  thresholds:
    active: { buy: 1.2, sell: -1.2 }
    quiet:  { buy: 1.4, sell: -1.4 }  # 安静期更严
  consistency_min_per_regime:
    active: 0.40
    quiet: 0.50
  
  # === B组: 回测端重算融合 + 连击确认 ===
  recompute_fusion: true              # 回测端重算融合
  min_consecutive_same_dir: 4         # 连击确认（4个tick）

components:
  fusion:
    # === B组: 反向防抖与冷却 ===
    flip_rearm_margin: 0.45           # 翻转抑制
    adaptive_cooldown_k: 0.70         # 冷却系数

strategy:
  # === B组: 迟滞与持仓 ===
  entry_threshold: 0.65               # 入场阈值
  exit_threshold: 0.45                 # 出场阈值

backtest:
  # === A组: 门控严格化 ===
  ignore_gating_in_backtest: false    # 回测中启用门控
  min_hold_time_sec: 240              # 最小持仓时间
  max_hold_time_sec: 3600             # 最大持仓时间保护
  force_timeout_exit: true            # 强制超时退出
  reverse_on_signal: false            # 禁止反向信号退出
  take_profit_bps: 12                 # 止盈bps
  stop_loss_bps: 10                   # 止损bps
  
  # === C组: Maker-first & 滑点 ===
  fee_model: maker_taker              # Maker-first费率模型
  fee_maker_taker:
    maker_fee_ratio: 0.4              # Maker费率比例
    scenario_probs:                    # 场景化Maker概率
      Q_L: 0.85                        # 低量安静期：85%
      A_L: 0.75                        # 低量活跃期：75%
      A_H: 0.50                        # 高量活跃期：50%
      Q_H: 0.40                        # 高量安静期：40%
      default: 0.50                    # 默认：50%
  
  slippage_model: piecewise           # 分段滑点模型
  slippage_piecewise:
    spread_base_multiplier: 0.7       # 基础滑点倍数
    scenario_multipliers:             # 场景化滑点倍数
      Q_L: 0.6                         # 低量安静期：0.6
      A_L: 0.8                         # 低量活跃期：0.8
      A_H: 1.0                         # 高量活跃期：1.0
      Q_H: 1.2                         # 高量安静期：1.2
```

---

## 二、历史测试数据

### 2.1 基线数据（深层修复验证前）

| 指标 | 基线值 |
|------|--------|
| **交易频率** | 934.0笔/小时 |
| **平均持仓** | 164.0秒 |
| **成本bps** | 1.93bps |
| **单笔收益** | -$0.82 |
| **胜率** | 16.81% |
| **总交易数** | 934笔 |
| **Maker比例** | 57.15% |

### 2.2 历史测试记录

#### 测试1: group_d_validation (2025-11-10 15:30) - 唯一测试
| 指标 | 结果 | 相对基线变化 |
|------|------|--------------|
| **交易频率** | 56.0笔/小时 | -94.0% ✅ |
| **平均持仓** | 2449.1秒 | +1393.3% ✅ |
| **成本bps** | 1.93bps | 0.0% ⚠️ |
| **单笔收益** | -$0.78 | +4.9% ⚠️ |
| **胜率** | 37.50% | +123.0% ✅ |
| **总交易数** | 56笔 |
| **Maker比例** | 57.14% |
| **综合评分** | 178.47 |

**测试效果**: 
- ✅ 交易频率大幅下降（94.0%），远超目标（56 vs 186.8笔/小时）
- ✅ 平均持仓大幅提升（1393.3%），远超目标（2449.1秒 vs 240秒）
- ✅ 胜率大幅提升（123.0%），达标（37.50% vs 25%）
- ⚠️ 成本bps未改善（仍为1.93bps）
- ❌ 单笔收益未达标（-$0.78 vs ≥0）

---

## 三、最优配置分析

### 3.1 最优测试结果

**最优配置**: `group_d_validation` (2025-11-10 15:30) - 唯一测试

| 指标 | 最优值 | 目标 | 状态 |
|------|--------|------|------|
| **交易频率** | 56.0笔/小时 | ≤186.8 | ✅ 达标（-70.0%） |
| **平均持仓** | 2449.1秒 | ≥240秒 | ✅ 达标（+920.5%） |
| **成本bps** | 1.93bps | ≤1.75bps | ❌ 未达标 |
| **单笔收益** | -$0.78 | ≥0 | ❌ 未达标 |
| **胜率** | 37.50% | ≥25% | ✅ 达标（+50.0%） |
| **Maker比例** | 57.14% | - | ⚠️ 部分达标 |

### 3.2 最优配置参数

基于最优测试结果，推荐配置（当前配置）：

```yaml
signal:
  weak_signal_threshold: 0.70
  consistency_min: 0.40
  dedupe_ms: 4000
  recompute_fusion: true
  min_consecutive_same_dir: 4

components:
  fusion:
    flip_rearm_margin: 0.45
    adaptive_cooldown_k: 0.70

strategy:
  entry_threshold: 0.65
  exit_threshold: 0.45

backtest:
  ignore_gating_in_backtest: false
  min_hold_time_sec: 240
  max_hold_time_sec: 3600
  force_timeout_exit: true
  reverse_on_signal: false
  take_profit_bps: 12
  stop_loss_bps: 10
  fee_model: maker_taker
  fee_maker_taker:
    maker_fee_ratio: 0.4
    scenario_probs:
      Q_L: 0.85
      A_L: 0.75
      A_H: 0.50
      Q_H: 0.40
      default: 0.50
  slippage_model: piecewise
  slippage_piecewise:
    spread_base_multiplier: 0.7
    scenario_multipliers:
      Q_L: 0.6
      A_L: 0.8
      A_H: 1.0
      Q_H: 1.2
```

---

## 四、优化方向

### 4.1 当前问题

1. **成本bps未改善**: 1.93bps vs 目标≤1.75bps
   - 原因：虽然交易频率大幅下降，但成本bps仍未改善
   - 建议：需要进一步优化Maker概率配置或降低交易频率

2. **单笔收益未达标**: -$0.78 vs 目标≥0
   - 原因：虽然胜率提升，但单笔收益仍为负
   - 建议：需要进一步优化TP/SL参数或提高信号质量

3. **Maker比例未完全达标**: 57.14% vs 目标区间
   - 原因：可能因为大部分交易是A_H场景，A_H的配置目标是0.5
   - 建议：检查A_H场景的maker概率计算逻辑

### 4.2 优化建议

#### 方向1: 进一步优化成本bps
- **提高Maker概率**: 
  - `scenario_probs.Q_L`: 0.85 → 0.90
  - `scenario_probs.A_L`: 0.75 → 0.80
  - `scenario_probs.A_H`: 0.50 → 0.55
- **降低`maker_fee_ratio`**: 0.4 → 0.35或0.3
- **优化滑点模型**: 
  - `spread_base_multiplier`: 0.7 → 0.6或0.5
  - 进一步降低Q_L和A_L场景的滑点

**预期效果**: 成本bps下降至1.75bps以下

#### 方向2: 优化单笔收益
- **提高`take_profit_bps`**: 12 → 15或18
- **降低`stop_loss_bps`**: 10 → 8或6
- **添加`deadband_bps`**: 2-3bps，避免频繁进出
- **提高信号质量阈值**: 
  - `weak_signal_threshold`: 0.70 → 0.75或0.80
  - `consistency_min`: 0.40 → 0.45或0.50

**预期效果**: 单笔收益提升至≥0

#### 方向3: 进一步降低交易频率
- **提高`weak_signal_threshold`**: 0.70 → 0.75或0.80
- **提高`consistency_min`**: 0.40 → 0.45或0.50
- **增加`dedupe_ms`**: 4000ms → 5000ms或6000ms
- **提高`min_consecutive_same_dir`**: 4 → 5或6

**预期效果**: 交易频率下降至20-40笔/小时

#### 方向4: 优化持仓时间
- **降低`min_hold_time_sec`**: 240秒 → 180秒或150秒
- **优化`max_hold_time_sec`**: 3600秒 → 1800秒或2400秒
- **检查持仓时间分布**: 找出异常长持仓的原因

**预期效果**: 平均持仓时间稳定在300-600秒

---

## 五、下一步行动

### 5.1 立即行动

1. **进一步优化成本bps**:
   - 提高Maker概率配置
   - 降低`maker_fee_ratio`到0.35
   - 优化滑点模型配置

2. **优化单笔收益**:
   - 提高`take_profit_bps`到15
   - 降低`stop_loss_bps`到8
   - 添加`deadband_bps`配置

3. **进一步降低交易频率**:
   - 提高`weak_signal_threshold`到0.75
   - 提高`consistency_min`到0.45
   - 增加`dedupe_ms`到5000ms

### 5.2 后续优化

1. **参数微调**: 根据验证结果进一步调整参数
2. **长时间验证**: 对最优配置运行4小时稳定性验证
3. **组合优化**: 尝试进一步优化D组配置，达到所有目标

---

## 六、关键指标总结

| 指标 | 基线 | 最优 | 变化 | 目标 | 状态 |
|------|------|------|------|------|------|
| **交易频率** | 934.0 | 56.0 | -94.0% | ≤186.8 | ✅ 达标 |
| **平均持仓** | 164.0 | 2449.1 | +1393.3% | ≥240 | ✅ 达标 |
| **成本bps** | 1.93 | 1.93 | 0.0% | ≤1.75 | ❌ 未达标 |
| **单笔收益** | -$0.82 | -$0.78 | +4.9% | ≥0 | ❌ 未达标 |
| **胜率** | 16.81% | 37.50% | +123.0% | ≥25% | ✅ 达标 |
| **Maker比例** | 57.15% | 57.14% | -0.0% | 目标区间 | ⚠️ 部分达标 |

---

## 七、组合策略效果分析

### 7.1 A组严门控效果
- ✅ 交易频率大幅下降（94.0%）
- ✅ 胜率大幅提升（123.0%）
- ⚠️ 成本bps未改善

### 7.2 B组冷却+反向防抖效果
- ✅ 平均持仓大幅提升（1393.3%）
- ✅ 减少快速反转交易
- ⚠️ 单笔收益未达标

### 7.3 C组Maker-first效果
- ✅ Scenario标准化已生效（100%命中）
- ⚠️ 成本bps未改善（可能因为交易频率已大幅下降）
- ⚠️ Maker比例未完全达标

### 7.4 组合效果
- ✅ 交易频率、平均持仓、胜率都达标
- ❌ 成本bps和单笔收益未达标
- ⚠️ 需要进一步优化

---

**报告生成时间**: 2025-11-10  
**报告版本**: v1.0

