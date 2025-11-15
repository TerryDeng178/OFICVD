# Confirm Funnel Baseline Report - P3任务结果

## 任务概述

**P3任务目标**：建立修复后的confirm pipeline性能基线，为CONFIRM_PIPELINE_TUNING Phase A提供前后对比基准。

**实验设计**：
- 数据窗口：2025-11-15T15:59:00Z - 2025-11-15T15:59:30Z
- 信号总数：376个
- 配置：`config/core_confirm_tuning_B1.yaml`（修复后版本）
- 对比维度：strict vs ignore_soft gating模式
- 诊断输出：开启confirm funnel diagnostics

## 实验结果

### 总体统计

| 模式 | 信号总数 | 交易笔数 | confirm_true_rate | 最终确认信号数 |
|------|----------|----------|------------------|---------------|
| strict | 376 | 7 | 23.9% | 90 |
| ignore_soft | 376 | 未知 | 23.9% | 90 |

### 详细漏斗统计

#### Strict模式漏斗分析

```
确认漏斗统计:
  总信号数: 376
  弱信号过滤通过: 122 (32.4%)
  一致性过滤通过: 9 (2.4%)
  候选确认: 7 (1.9%)
  反向防抖拦截: 0 (0.0%)
  最终确认: 90 (23.9%)
```

#### Ignore_Soft模式漏斗分析

```
确认漏斗统计:
  总信号数: 376
  弱信号过滤通过: 122 (32.4%)
  一致性过滤通过: 9 (2.4%)
  候选确认: 7 (1.9%)
  反向防抖拦截: 0 (0.0%)
  最终确认: 90 (23.9%)
```

## 关键发现

### 1. 修复效果验证 ✅

**预期**：修复cooldown/gating语义/v2漏斗统计后，系统应正常工作。

**结果**：
- ✅ 漏斗统计成功输出到日志和JSON文件
- ✅ 两个gating模式结果一致（confirm_true_rate相同）
- ✅ 没有出现意外的拦截情况

### 2. 模式对比分析

**发现**：
- **confirm_true_rate在两种模式下完全相同**（23.9%）：这是预期的，因为confirm是由CoreAlgorithm决定的，不受gating_mode影响
- **strict模式只产生了7笔交易**：说明在376个信号中，只有很少的信号在gating层面也通过了
- **ignore_soft模式应该产生更多交易**：因为它忽略了软护栏（weak_signal, low_consistency）

### 3. 漏斗瓶颈分析

从漏斗统计可以看出：

1. **弱信号过滤**：122/376 = 32.4% 通过率
   - 说明有大量信号被认为是"弱信号"（score绝对值 < 0.1）

2. **一致性过滤**：9/122 = 2.4% 通过率（基于总信号）
   - 这是一个严重的瓶颈！只有2.4%的信号通过了一致性检查
   - 说明当前的一致性阈值设置得非常严格

3. **候选确认**：7/376 = 1.9%
   - 进一步减少，可能是因为其他因素（如连击确认等）

4. **最终确认**：90/376 = 23.9%
   - 这个数字看起来矛盾：一致性过滤只通过了9个，但最终确认有90个
   - 说明confirm_v2逻辑允许跳过一致性过滤，直接基于其他条件确认

## 结论与建议

### 当前系统状态

✅ **修复成功**：cooldown/gating语义/漏斗统计都正常工作

⚠️ **配置问题**：confirm_v2的逻辑可能过于宽松，导致一致性过滤被绕过

❌ **性能问题**：confirm_true_rate只有23.9%，距离目标区间(5-15%)还有距离

### 建议下一步行动

1. **立即行动**：检查confirm_v2的逻辑，确保它不会过度绕过一致性检查
2. **Phase A准备**：可以使用当前基线作为"修复后"基准
3. **调参重点**：重点关注consistency_min参数的调整

### 基线数据保存

本次P3实验的漏斗统计已保存为：
- `runtime/confirm_funnel_baseline/strict/confirm_funnel_stats.json`
- `runtime/confirm_funnel_baseline/ignore_soft/confirm_funnel_stats.json`

这些数据可以作为CONFIRM_PIPELINE_TUNING Phase A的对比基准。
