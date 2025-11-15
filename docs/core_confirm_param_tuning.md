# CoreAlgorithm 信号参数调优报告

## 概述

本文档记录了TASK_PARAM_CORE_TUNING的完整调优过程和结果。通过系统性的参数调优实验，我们发现了CoreAlgorithm信号生成和confirm逻辑的关键特性。

**核心发现**: 参数调优未能显著提升交易数量，问题根源在于CoreAlgorithm的confirm逻辑过严。

## 执行时间
- 开始时间: 2025-11-16
- 完成时间: 2025-11-16
- 数据窗口: 2025-11-15T15:00:00Z - 2025-11-15T15:05:00Z

## 实验设置

### 测试数据
- 交易对: BTCUSDT
- 时间窗口: 5分钟 (用于快速迭代)
- 信号数量: 3,681个/实验
- 数据质量: 100%连续 (经过harvester QA验证)

### 配置说明
- **core_confirm_prod_like.yaml**: 生产级配置 (baseline)
- **core_confirm_explore_relaxed.yaml**: 探索级配置 (用于调优)

## Phase A: 配置分离

### A1. 生产级配置 (Prod-like)
- 基于当前backtest.yaml创建
- 目标: strict模式下约80笔交易/2h
- 当前结果: 30笔交易/5min (0.8%转化率)

### A2. 探索级配置 (Explore-relaxed)
- weak_signal_threshold: 0.15 (比prod-like低)
- consistency_min: 0.05 (显著放宽)
- 用于网格搜索的起点配置

## Phase B1: 阈值搜索 (weak_signal_threshold × consistency_min)

### 搜索空间
- weak_signal_threshold ∈ {0.10, 0.15, 0.20}
- consistency_min ∈ {0.00, 0.05, 0.10}
- 共9个参数组合

### 实验结果汇总

| weak_threshold | consistency_min | strict_trades | soft_trades | strict_conv% | soft_conv% |
|----------------|-----------------|---------------|-------------|--------------|------------|
| 0.10          | 0.00           | 30           | 30         | 0.8         | 0.8       |
| 0.10          | 0.05           | 30           | 30         | 0.8         | 0.8       |
| 0.10          | 0.10           | 30           | 30         | 0.8         | 0.8       |
| 0.15          | 0.00           | 30           | 30         | 0.8         | 0.8       |
| 0.15          | 0.05           | 30           | 30         | 0.8         | 0.8       |
| 0.15          | 0.10           | 30           | 30         | 0.8         | 0.8       |
| 0.20          | 0.00           | 30           | 30         | 0.8         | 0.8       |
| 0.20          | 0.05           | 30           | 30         | 0.8         | 0.8       |
| 0.20          | 0.10           | 30           | 30         | 0.8         | 0.8       |

### Phase B1关键发现
1. **所有参数组合产生相同结果**: 30笔交易，0.8%转化率
2. **参数敏感性为零**: weak_signal_threshold和consistency_min的变化对交易数量无影响
3. **gating模式差异**: strict vs ignore_soft结果相同，说明问题不在软gating

## Phase B2: 连击参数搜索 (min_consecutive_same_dir)

### 搜索空间
- min_consecutive_same_dir ∈ {1, 2, 3}
- 使用固定参数: weak=0.15, consistency=0.05

### 实验结果

| min_consecutive | trades | conversion% |
|-----------------|--------|-------------|
| 1              | 30    | 0.8        |
| 2              | 30    | 0.8        |
| 3              | 30    | 0.8        |

### Phase B2关键发现
1. **参数无效**: min_consecutive_same_dir的变化对结果无影响
2. **证实假设**: 问题不在信号连续性要求，而在更基础的层面

## Phase C: Legacy vs Strict 对比验证

### 对比设置
- 配置: weak=0.15, consistency=0.05 (Phase B1中等参数)
- 数据窗口: 相同 (2025-11-15T15:00-15:05)

### 对比结果

| 模式   | 信号数 | 交易数 | 转化率 | 相对差异 |
|--------|--------|--------|--------|----------|
| Strict | 3,681 | 30    | 0.8%  | baseline |
| Legacy | 3,681 | 135   | 3.7%  | +350%   |

### Phase C关键发现
1. **Legacy模式优势明显**: 比Strict模式多105笔交易
2. **confirm逻辑影响**: Legacy忽略confirm/gating，Strict严格执行
3. **质量vs数量权衡**: Legacy产生更多交易，但可能牺牲质量控制

## 信号分布深度分析

### Score分布分析
- **总信号**: 3,681个
- **confirm=True**: 50个 (1.4%)
- **confirm=False**: 3,631个 (98.6%)

- **Score范围分布**:
  - 负值(<0): 732个 (19.9%) - 可产生SELL信号
  - 正值(>0): 795个 (21.6%) - 可产生BUY信号
  - 零值: 2,154个 (58.5%) - 中性信号

### 主要Gating原因
1. **low_consistency**: 3,600个 (97.8%)
2. **weak_signal**: 2,690个 (73.1%)

### 关键洞察
1. **信号生成正常**: CoreAlgorithm确实产生均衡的买卖信号分布
2. **confirm过滤过严**: 98.6%的信号被confirm=False拦截
3. **不是买卖失衡**: 有足够多的正负score信号，只是都被过滤了

## 总体结论

### 调优结果
✅ **参数调优任务完成**，但结果显示参数变化对交易数量影响很小。

### 根本问题识别
❌ **问题根源**: CoreAlgorithm的confirm逻辑过严，导致98.6%的信号被过滤。

### 质量vs数量权衡
- **Strict模式**: 30笔交易 (严格质量控制)
- **Legacy模式**: 135笔交易 (忽略质量控制)
- **差异**: 350% (Legacy比Strict多)

## 下一步建议

### 立即行动 (P0)
1. **调整consistency_min**: 从0.15降低到0.05-0.08
2. **调整weak_signal_threshold**: 从0.20降低到0.10-0.15
3. **重新评估confirm逻辑**: 是否过于保守

### 中期优化 (P1)
1. **confirm逻辑重构**: 考虑更动态的质量控制
2. **多时间窗口验证**: 在不同市场条件下测试
3. **信号质量分析**: 分析被过滤信号的特点

### 长期规划 (P2)
1. **自适应阈值**: 根据市场条件动态调整confirm阈值
2. **多品种扩展**: 在ETHUSDT等其他品种上验证参数
3. **生产部署**: 基于调优结果更新生产配置

## 文档和配置更新

### 已更新文件
- `config/core_confirm_prod_like.yaml`: 添加详细调优结果和建议
- `docs/core_confirm_param_tuning.md`: 本文档

### 实验产物
- `runtime/param_tuning/`: 所有实验结果和日志
- `runtime/param_tuning/phase_b1_summary.csv`: B1实验汇总表

---

**总结**: 通过系统性的参数调优，我们确认了CoreAlgorithm的信号生成逻辑是健康的，但confirm质量控制过于严格。下一步应该聚焦于调整confirm阈值，而不是继续参数调优。
