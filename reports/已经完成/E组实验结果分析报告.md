# E组实验结果分析报告

## 执行时间
2025-11-10 22:02 - 22:11（约9分钟）

## 实验结果汇总

| 实验组 | 交易频率/h | 成本bps | 单笔收益 | 胜率 | 平均持仓时长 | 净PnL |
|--------|-----------|---------|---------|------|-------------|-------|
| **D基线** | 71.0 | 1.93 | -$0.64 | 16.81% | - | -$64.00 |
| **E1** | **35.0** | 1.93 | -$0.68 | 28.57% | 8712s (2.4h) | -$23.68 |
| **E2** | 71.0 | 1.93 | -$0.64 | **39.44%** | 2653s (44min) | -$45.13 |
| **E3** | 74.0 | 1.93 | -$0.78 | 39.19% | 2166s (36min) | -$57.95 |

---

## 关键发现

### 1. 频率控制（E1组有效）

**E1组成功将交易频率从71/h降至35/h（降低51%）**，但仍未达到≤20/h的目标。

**原因分析**：
- `weak_signal_threshold: 0.78` 和 `consistency_min: 0.48` 有效过滤了弱信号
- `dedupe_ms: 6000` 减少了重复触发
- **但持仓时长异常长（8712秒=2.4小时）**，说明退出机制可能有问题

**改进方向**：
- 进一步收紧入口阈值（`weak_signal_threshold` → 0.80）
- 检查E1组的退出逻辑（为什么持仓时长这么长？）

### 2. 成本控制（全组无改进）

**所有实验组的成本bps都是1.93，与D组完全相同**。

**原因分析**：
- E2组虽然提高了Maker概率（Q_L: 0.90, A_L: 0.80）并降低了`maker_fee_ratio`（0.35），但成本未下降
- **可能原因**：
  1. Maker概率提升被滑点增加抵消
  2. 费率模型计算逻辑需要检查
  3. 实际交易中Maker/Taker比例未按预期变化

**改进方向**：
- 检查费率模型的实际执行情况
- 考虑更激进的Maker策略（`maker_fee_ratio` → 0.30）
- 分析滑点模型对成本的影响

### 3. 单笔收益（全组为负）

**所有实验组的单笔收益仍为负值**，E3组甚至更差（-$0.78）。

**原因分析**：
- E3组的TP/SL设置（TP=18bps, SL=6bps）可能过于激进
- 死区设置（3bps）可能限制了盈利机会
- **E1组持仓时长异常长，可能导致更多亏损**

**改进方向**：
- 调整TP/SL比例（TP=15bps, SL=8bps，更平衡）
- 减小死区（`deadband_bps` → 1.5）
- 修复E1组的退出逻辑

### 4. 胜率提升（E2/E3组显著）

**E2和E3组的胜率都达到了39%+，远高于D组的16.81%**。

**原因分析**：
- E2组的Maker概率提升可能改善了入场时机
- E3组的TP/SL和死区可能过滤了部分亏损交易

**但胜率提升未转化为正收益**，说明：
- 盈利交易的收益不足以覆盖亏损
- 需要进一步优化止盈止损策略

---

## 验收结果

### E1组：入口节流+去重加严
- ❌ 交易频率：35/h > 20/h（未达标，但已改善51%）
- ❌ 成本bps：1.93 > 1.75（未达标）
- ❌ 单笔收益：-$0.68 < 0（未达标）
- ✅ ETHUSDT稳健性：通过（但ETHUSDT净PnL为-$9.43，仍偏弱）

### E2组：Maker概率&费率专项
- ❌ 交易频率：71/h > 20/h（未达标）
- ❌ 成本bps：1.93 > 1.75（未达标）
- ❌ 单笔收益：-$0.64 < 0（未达标）
- ✅ ETHUSDT稳健性：通过

### E3组：TP/SL + 死区组合
- ❌ 交易频率：74/h > 20/h（未达标）
- ❌ 成本bps：1.93 > 1.75（未达标）
- ❌ 单笔收益：-$0.78 < 0（未达标，比D组更差）
- ✅ ETHUSDT稳健性：通过

**总体验收：❌ FAIL（所有实验组均未完全达标）**

---

## 下一步行动方案

### P0优先级（立即执行）

#### 1. 修复E1组持仓时长异常问题
**问题**：E1组平均持仓时长8712秒（2.4小时），远超预期。

**检查项**：
- [ ] 检查`force_timeout_exit`是否生效
- [ ] 检查`max_hold_time_sec`是否被正确应用
- [ ] 检查退出信号是否被正确触发

**验证命令**：
```powershell
# 检查E1组的trades.jsonl，查看持仓时长分布
python scripts/analyze_trade_hold_time.py `
  --input runtime/optimizer/group_e1_validation/backtest_20251110_220238/trades.jsonl
```

#### 2. 组合E1+E2策略（频率+成本）
**方案**：将E1组的入口节流参数与E2组的Maker策略结合。

**配置调整**：
- 使用E1组的入口参数（`weak_signal_threshold: 0.78`, `consistency_min: 0.48`, `dedupe_ms: 6000`）
- 使用E2组的Maker参数（`maker_fee_ratio: 0.35`, `scenario_probs.Q_L: 0.90`, `scenario_probs.A_L: 0.80`）
- 修复退出逻辑（确保`force_timeout_exit`生效）

**创建新实验组E4**：
```yaml
# runtime/optimizer/group_e4_combined.yaml
signal:
  weak_signal_threshold: 0.78      # E1
  consistency_min: 0.48            # E1
  dedupe_ms: 6000                 # E1

backtest:
  fee_maker_taker:
    maker_fee_ratio: 0.35         # E2
    scenario_probs:
      Q_L: 0.90                    # E2
      A_L: 0.80                    # E2
  force_timeout_exit: true         # 确保生效
  max_hold_time_sec: 3600         # 最大持仓1小时
```

#### 3. 优化TP/SL策略（基于E3组）
**问题**：E3组的TP/SL设置导致单笔收益更差。

**调整方案**：
- `take_profit_bps`: 18 → **15**（降低目标，提高命中率）
- `stop_loss_bps`: 6 → **8**（放宽止损，减少过早退出）
- `deadband_bps`: 3 → **1.5**（减小死区，增加交易机会）

**创建新实验组E5**：
```yaml
# runtime/optimizer/group_e5_optimized_tp_sl.yaml
backtest:
  take_profit_bps: 15
  stop_loss_bps: 8
  deadband_bps: 1.5
```

### P1优先级（后续优化）

#### 1. 费率模型深度分析
**目标**：理解为什么Maker概率提升未降低成本。

**分析项**：
- [ ] 检查实际Maker/Taker比例
- [ ] 分析滑点对成本的影响
- [ ] 验证费率模型计算逻辑

#### 2. ETHUSDT专项优化
**问题**：ETHUSDT在所有组中表现偏弱（E1组中ETHUSDT净PnL为-$9.43）。

**方案**：
- 为ETHUSDT设置独立参数（更高的入口阈值、更长的dedupe）
- 分析ETHUSDT的成本剖面（价差、滑点、Maker命中率）

---

## 推荐执行顺序

1. **立即**：修复E1组持仓时长异常问题
2. **立即**：运行E4组（E1+E2组合）
3. **立即**：运行E5组（优化TP/SL）
4. **后续**：费率模型深度分析
5. **后续**：ETHUSDT专项优化

---

## 文件清单

### 实验结果
- `runtime/optimizer/e_experiments_comparison.json` - 实验对比结果
- `runtime/optimizer/e_experiments_validation.json` - 验收结果

### 各实验组结果目录
- `runtime/optimizer/group_e1_validation/backtest_20251110_220238/`
- `runtime/optimizer/group_e2_validation/backtest_20251110_220631/`
- `runtime/optimizer/group_e3_validation/backtest_20251110_221124/`

---

## 结论

**E组实验部分达成目标**：
- ✅ E1组成功降低交易频率51%（35/h vs 71/h）
- ✅ E2/E3组显著提升胜率（39%+ vs 16.81%）
- ❌ 成本控制未改进（全组1.93bps）
- ❌ 单笔收益仍为负（全组未达标）

**关键问题**：
1. E1组持仓时长异常（需立即修复）
2. 成本控制策略无效（需深度分析）
3. TP/SL策略需要优化（E3组表现更差）

**建议**：优先修复E1组问题，然后运行E4组（E1+E2组合）和E5组（优化TP/SL），争取在下一轮达到验收标准。

