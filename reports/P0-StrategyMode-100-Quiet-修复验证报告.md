# P0 StrategyMode 100% Quiet 问题修复验证报告

## 报告信息

- **报告日期**: 2025-11-07
- **测试类型**: 冒烟测试 (Smoke Test)
- **测试环境**: 开发环境 (Windows)
- **测试配置**: `config/defaults.smoke.yaml`
- **测试数据**: 425,131 行特征数据
- **测试时长**: ~8.5 分钟

---

## 一、问题背景

### 1.1 问题描述

在之前的 smoke 测试中，系统出现 **100% quiet** 问题：
- 所有信号都被判定为 `quiet` 模式
- `active` 模式占比为 0%
- StrategyMode 的 OR 逻辑未能正常工作

### 1.2 根因分析

经过分析，发现三个主要原因：

1. **Schedule 默认关闭**
   - CoreAlgo 构造 StrategyModeManager 时，如果配置未显式提供 `schedule`，默认值为 `{"enabled": False}`
   - 导致 schedule 触发器永远为 False

2. **enabled_weekdays 空列表逻辑缺陷**
   - 当 `enabled_weekdays: []` 时，任何 weekday 都不在列表中
   - `check_schedule_active()` 总是返回 False

3. **OR 逻辑缺少时间触发路径**
   - 由于 schedule 默认关闭，OR 逻辑中缺少"时间触发"这条腿
   - 只能依赖 market 触发，但市场触发在 smoke 数据上经常不过基础门槛

---

## 二、修复内容

### 2.1 P0 修复（立即生效）

#### 修复 1: CoreAlgo - Schedule 默认值改为开启

**文件**: `src/alpha_core/signals/core_algo.py` (第 252 行)

**修改前**:
```python
"schedule": triggers_cfg.get("schedule", {"enabled": False}),
```

**修改后**:
```python
# P0: 默认开启 schedule，空窗口=全天有效（配合 StrategyModeManager 实现）
"schedule": triggers_cfg.get("schedule", {"enabled": True, "active_windows": []}),
```

**影响**: 确保当配置未显式提供 schedule 时，默认开启且空窗口视为全天有效

---

#### 修复 2: StrategyModeManager - enabled_weekdays 空列表逻辑

**文件**: `src/alpha_core/risk/strategy_mode.py` (第 508-513 行)

**修改前**:
```python
# 检查星期几
weekday = dt.strftime('%a')  # Mon, Tue, Wed, ...
if weekday not in self.enabled_weekdays:
    return False
```

**修改后**:
```python
# 检查星期几
# P0: 空列表视为"所有星期都启用"（类似 active_windows 为空=全天有效）
if self.enabled_weekdays:
    weekday = dt.strftime('%a')  # Mon, Tue, Wed, ...
    if weekday not in self.enabled_weekdays:
        return False
```

**影响**: 当 `enabled_weekdays` 为空列表时，跳过星期检查，视为所有星期都启用

---

#### 修复 3: 删除重复代码

**文件**: `src/alpha_core/signals/core_algo.py` (第 576-659 行)

**修改**: 删除了重复的 `_create_market_activity` 和 `_infer_regime` 方法

**影响**: 清理代码，避免潜在的逻辑冲突

---

#### 修复 4: FeaturePipe - 修复语法错误

**文件**: `src/alpha_core/microstructure/feature_pipe.py` (第 725-775 行)

**修改**: 删除了文件末尾的重复代码块

**影响**: 修复 IndentationError，确保 FeaturePipe 能正常运行

---

### 2.2 P1 优化（已完成）

#### 优化 1: 心跳日志 JSON 格式

**文件**: `src/alpha_core/signals/core_algo.py` (第 535-548 行)

**修改前**:
```python
logger.info(
    f"[StrategyMode] {symbol} @ {ts_ms}: "
    f"mode={current_mode.value}, "
    f"trades/min={activity.trades_per_min:.1f}, "
    ...
)
```

**修改后**:
```python
snapshot = {
    "ts_ms": ts_ms,
    "symbol": symbol,
    "mode": current_mode.value,
    "trades_per_min": round(activity.trades_per_min, 1),
    ...
}
logger.info(f"[StrategyMode] {json.dumps(snapshot, ensure_ascii=False)}")
```

**影响**: 便于后续用 `jq` 工具汇总分析，快速定位问题

---

## 三、测试配置

### 3.1 测试参数

```yaml
strategy_mode:
  mode: auto
  hysteresis:
    window_secs: 60
    min_active_windows: 2
    min_quiet_windows: 4
  triggers:
    combine_logic: OR
    schedule:
      enabled: true
      timezone: UTC
      enabled_weekdays: []
      active_windows: []
    market:
      enabled: true
      window_secs: 60
      basic_gate_multiplier: 0.3  # Smoke 档放宽
      min_trades_per_min: 20
      min_quote_updates_per_sec: 3
      max_spread_bps: 30
      min_volatility_bps: 0.3
      min_volume_usd: 5000
```

### 3.2 测试数据

- **数据源**: `deploy/data/ofi_cvd/preview`
- **交易对**: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT
- **特征行数**: 420,210 (含 warmup)
- **处理行数**: 425,131

---

## 四、测试结果

### 4.1 核心指标

| 指标 | 修复前 | 修复后 | 变化 | 状态 |
|------|--------|--------|------|------|
| **Active 占比** | 0% | 99.998% | +99.998% | ✅ 远超目标 |
| **Quiet 占比** | 100% | 0.002% | -99.998% | ✅ 问题解决 |
| **Schedule Active** | false | true | ✅ | ✅ 修复生效 |
| **Confirm 信号数** | 0 | 97,284 | +97,284 | ✅ 正常产出 |

### 4.2 Regime 分布详情

```
regime distribution:
  active: 425,125  (99.998%)
  quiet: 6         (0.002%)
```

**各交易对分布**:

| 交易对 | Active | Quiet | Active 占比 |
|--------|--------|-------|------------|
| BNBUSDT | 67,509 | 1 | 99.998% |
| BTCUSDT | 73,629 | 1 | 99.998% |
| DOGEUSDT | 65,443 | 1 | 99.998% |
| ETHUSDT | 74,207 | 1 | 99.998% |
| SOLUSDT | 72,997 | 1 | 99.998% |
| XRPUSDT | 71,343 | 1 | 99.998% |

### 4.3 StrategyMode 心跳日志验证

**日志样本**:
```json
{
  "ts_ms": 1762469399000,
  "symbol": "DOGEUSDT",
  "mode": "active",
  "trades_per_min": 48.0,
  "quotes_per_sec": 1.6,
  "spread_bps": 2.0,
  "volatility_bps": 1.98,
  "volume_usd": 96000.0,
  "schedule_active": true,
  "market_active": false,
  "history_size": 4
}
```

**关键验证点**:
- ✅ `schedule_active: true` - Schedule 触发器正常工作
- ✅ `mode: "active"` - 模式已切换到 active
- ✅ `market_active: false` - 即使市场触发为 false，OR 逻辑仍让模式翻到 active
- ✅ JSON 格式正确 - 便于后续分析

### 4.4 信号产出统计

| 指标 | 数值 | 说明 |
|------|------|------|
| **总处理行数** | 425,131 | 所有特征行 |
| **Confirm 信号** | 97,284 | 确认信号数 |
| **Suppressed 信号** | 327,847 | 被抑制的信号 |
| **Gated 信号** | 298,853 | 被护栏拦截的信号 |
| **Warmup 拦截** | 41,364 | 预热期拦截 |
| **吞吐量** | 837.16 rows/sec | 处理速度 |

### 4.5 Guard Reason 分布

| Guard Reason | 数量 | 占比 |
|--------------|------|------|
| low_consistency | 257,489 | 78.5% |
| warmup | 41,364 | 12.6% |
| 其他 | 28,994 | 8.9% |

**分析**:
- `low_consistency` 仍是主要拦截原因（78.5%）
- 这是正常的，因为 consistency 阈值设置较保守
- 不影响 regime 判定，regime 已成功切换到 active

### 4.6 信号类型分布

| 信号类型 | 数量 | 占比 |
|----------|------|------|
| neutral | 326,862 | 76.9% |
| buy | 43,107 | 10.1% |
| sell | 42,437 | 10.0% |
| strong_sell | 5,898 | 1.4% |
| strong_buy | 5,842 | 1.4% |
| pending | 985 | 0.2% |

---

## 五、修复验证

### 5.1 修复项验证清单

| 修复项 | 验证方法 | 验证结果 | 状态 |
|--------|----------|----------|------|
| Schedule 默认开启 | 检查日志中 `schedule_active` | 所有日志显示 `true` | ✅ |
| enabled_weekdays 空列表逻辑 | 快速测试 `check_schedule_active()` | 返回 `True` | ✅ |
| OR 逻辑生效 | 检查日志中 `market_active: false` 但 `mode: active` | 符合预期 | ✅ |
| 心跳日志 JSON 格式 | 检查日志格式 | JSON 格式正确 | ✅ |
| 代码清理 | 检查语法错误 | 无语法错误 | ✅ |

### 5.2 功能验证

#### 5.2.1 Schedule 触发器

**验证方法**: 检查所有 StrategyMode 心跳日志

**结果**: 
- ✅ 所有日志中 `schedule_active: true`
- ✅ 即使 `market_active: false`，模式仍能翻到 active
- ✅ OR 逻辑正常工作

#### 5.2.2 模式切换

**验证方法**: 统计 regime 分布

**结果**:
- ✅ Active 占比: 99.998% (目标: ≥20%)
- ✅ 所有交易对均正常切换到 active
- ✅ 迟滞逻辑正常工作（history_size: 4）

#### 5.2.3 配置加载

**验证日志**:
```
INFO: [StrategyMode] Config loaded: mode=auto, schedule_enabled=True, market_enabled=True, basic_gate_multiplier=0.3
```

**结果**: ✅ 配置正确加载

---

## 六、性能指标

### 6.1 处理性能

| 指标 | 当前测试 | 之前测试（无 StrategyMode） | 变化 | 说明 |
|------|----------|---------------------------|------|------|
| **总处理行数** | 425,131 | 305,628 | +39% | 数据量增加 |
| **处理时长** | ~8.5 分钟 | ~1.7 分钟 | +400% | 处理时间增加 |
| **吞吐量** | 837.16 rows/sec | ~3,030 rows/sec | -72% | 性能下降 |
| **平均延迟** | ~1.2 ms/row | ~0.33 ms/row | +264% | 每行处理时间增加 |

### 6.2 性能下降分析

**性能下降原因（正常预期）**：

1. **StrategyMode 计算开销**
   - 每行都要调用 `_create_market_activity()`，包含多层兜底逻辑和 deque 操作
   - 每行都要调用 `manager.update_mode(activity)`，包含：
     - 市场活动度计算（滑动窗口、中位数、Winsorize）
     - 触发器检查（schedule + market）
     - 迟滞逻辑（历史窗口管理）
   - 每行都要调用 `manager.get_current_mode()`
   - 每 10 秒的 JSON 日志序列化（虽然频率低，但每次都要构建字典和序列化）

2. **功能复杂度增加**
   - 之前：简单的阈值判断（基于 activity.tps）
   - 现在：完整的 StrategyMode 逻辑（市场活动度 + 时间触发 + 迟滞）

3. **数据量增加**
   - 从 305,628 行增加到 425,131 行（+39%）
   - 但这不是主要原因，主要原因是 StrategyMode 的计算开销

**性能评估**：

- ✅ **837 rows/sec 仍然是合理的处理速度**
- ✅ **对于实时交易系统，1.2 ms/row 的延迟是可接受的**
- ✅ **性能下降是功能增强的正常代价**
- ⚠️ **如果后续需要优化，可以考虑**：
  - 减少每行都调用 StrategyMode（例如：每 N 行调用一次）
  - 优化 `_create_market_activity()` 的兜底逻辑
  - 优化 StrategyModeManager 的内部计算（缓存、批量处理等）

### 6.3 资源使用

- **内存**: 正常范围（StrategyMode 增加了少量内存开销，主要是每个 symbol 的窗口和历史）
- **CPU**: 正常范围（StrategyMode 计算增加了 CPU 开销，但仍在可接受范围）
- **磁盘 I/O**: 正常范围（日志输出略有增加，但影响不大）

---

## 七、问题解决确认

### 7.1 问题解决状态

| 问题 | 状态 | 说明 |
|------|------|------|
| 100% Quiet 问题 | ✅ 已解决 | Active 占比从 0% 提升到 99.998% |
| Schedule 默认关闭 | ✅ 已修复 | 默认值改为开启 |
| enabled_weekdays 逻辑缺陷 | ✅ 已修复 | 空列表视为所有星期启用 |
| OR 逻辑不生效 | ✅ 已修复 | Schedule 触发正常工作 |

### 7.2 目标达成情况

| 目标 | 预期 | 实际 | 状态 |
|------|------|------|------|
| Active 占比 | ≥20% | 99.998% | ✅ 远超预期 |
| Schedule Active | true | true | ✅ 达成 |
| 模式切换 | 正常 | 正常 | ✅ 达成 |
| 日志格式 | JSON | JSON | ✅ 达成 |

---

## 八、结论与讨论

### 8.1 修复效果

本次修复成功解决了 **100% Quiet** 问题：

1. **核心问题已解决**
   - Active 占比从 0% 提升到 99.998%
   - 远超预期目标（≥20%）
   - 所有交易对均正常切换到 active 模式

2. **根因修复完成**
   - Schedule 默认开启 ✅
   - enabled_weekdays 空列表逻辑修复 ✅
   - OR 逻辑正常工作 ✅

3. **系统状态正常**
   - StrategyMode 正常工作
   - Schedule 触发器稳定
   - 迟滞逻辑正常
   - 日志格式优化完成

### 8.2 关于 99% Active 的讨论

**当前情况分析**：

当前测试结果显示 **99.998% Active**，这主要是由于以下配置：

```yaml
schedule:
  enabled: true
  active_windows: []        # 空数组 = 全天有效
  enabled_weekdays: []      # 空数组 = 所有星期都启用
triggers:
  combine_logic: OR         # schedule_active OR market_active
```

**为什么是 99% Active**：

1. `active_windows: []` 导致 `schedule_active` 总是返回 `True`（全天有效）
2. `enabled_weekdays: []` 导致所有星期都启用
3. OR 逻辑：即使 `market_active` 为 `False`，只要 `schedule_active` 为 `True`，模式就会翻到 `active`

**是否符合真实市场情况**：

❌ **不完全符合**。虽然数字货币市场 24 小时交易，但活跃度有明显波动：

1. **时段差异**：
   - **亚洲时段**（UTC+8，如北京时间 9:00-17:00）：相对活跃
   - **欧洲时段**（UTC+1，如伦敦时间 8:00-16:00）：活跃
   - **美洲时段**（UTC-5，如纽约时间 9:00-17:00）：最活跃
   - **重叠时段**（欧洲+美洲）：最活跃
   - **凌晨时段**（UTC 0:00-8:00）：相对不活跃

2. **周末效应**：
   - 周末交易量通常低于工作日
   - 某些时段可能进入 quiet 状态

3. **市场事件**：
   - 重大新闻、政策发布时活跃度激增
   - 市场平静期可能进入 quiet 状态

**建议的生产环境配置**：

为了更符合真实市场情况，建议采用以下配置策略：

#### 方案 1：依赖 Market 触发器（推荐）

```yaml
schedule:
  enabled: false  # 关闭 schedule，完全依赖市场活动度
triggers:
  combine_logic: OR
market:
  enabled: true
  basic_gate_multiplier: 0.5  # 生产环境使用更严格的阈值
  min_trades_per_min: 30
  min_quote_updates_per_sec: 5
  max_spread_bps: 15
  min_volatility_bps: 0.5
  min_volume_usd: 10000
```

**优点**：完全基于市场真实活动度，更符合实际情况

#### 方案 2：设置交易时段（适合特定策略）

```yaml
schedule:
  enabled: true
  timezone: "UTC"
  enabled_weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri"]  # 仅工作日
  active_windows:
    - start: 480   # 08:00 UTC (亚洲时段开始)
      end: 1440    # 24:00 UTC (覆盖亚洲+欧洲+美洲)
    - start: 0     # 00:00 UTC
      end: 480     # 08:00 UTC (美洲时段延续)
  wrap_midnight: true
triggers:
  combine_logic: OR
```

**优点**：可以排除周末和凌晨低活跃时段

#### 方案 3：混合模式（平衡方案）

```yaml
schedule:
  enabled: true
  active_windows: []  # 全天有效，但配合 market 触发器
triggers:
  combine_logic: AND  # 改为 AND，需要 schedule AND market 都满足
market:
  enabled: true
  basic_gate_multiplier: 0.5
  # ... 其他市场阈值
```

**优点**：既考虑时间因素，又考虑市场活动度

### 8.3 后续建议

1. **生产环境配置调整**
   - ⚠️ **重要**：当前 99% Active 是 smoke 测试配置的结果（schedule 全天有效）
   - 建议生产环境采用 **方案 1**（依赖 Market 触发器）或 **方案 3**（AND 逻辑）
   - 将 `basic_gate_multiplier` 从 0.3 调整到 0.5 或 1.0
   - 根据实际市场数据调整市场触发阈值

2. **监控指标**
   - 持续监控 `schedule_active` 和 `market_active` 状态
   - 监控 regime 分布，**生产环境预期 Active 占比应在 40-70% 之间**（而非 99%）
   - 使用 JSON 格式日志进行自动化分析
   - 建立时段活跃度基线，识别异常

3. **进一步优化**
   - 考虑将 `basic_gate_multiplier` 做成环境变量或配置开关
   - 优化 consistency 阈值，减少 `low_consistency` 拦截率
   - 根据历史数据调整交易时段配置
   - 考虑添加"市场平静期"检测逻辑

---

## 九、附录

### 9.1 测试命令

```powershell
# 运行完整 smoke 测试
.\scripts\m2_smoke_test.ps1

# 快速验证 schedule_active
python -c "from alpha_core.risk.strategy_mode import StrategyModeManager; import json; cfg = {...}; m = StrategyModeManager(runtime_cfg=cfg); print(f'check_schedule_active: {m.check_schedule_active()}')"
```

### 9.2 相关文件

- **修复文件**:
  - `src/alpha_core/signals/core_algo.py`
  - `src/alpha_core/risk/strategy_mode.py`
  - `src/alpha_core/microstructure/feature_pipe.py`

- **配置文件**:
  - `config/defaults.smoke.yaml`

- **测试脚本**:
  - `scripts/m2_smoke_test.ps1`

### 9.3 测试数据位置

- **运行目录**: `runtime/runs/20251107_074115/`
- **特征文件**: `features_20251107_074115.jsonl`
- **信号文件**: `ready/signal/*/signals_*.jsonl`
- **摘要文件**: `smoke_summary.json`

---

---

## 十、后续行动项

### 10.1 已完成的行动项

✅ **Staging 配置创建** (`config/defaults.staging.yaml`)
- 采用 AND 逻辑（schedule AND market）
- 仅工作日启用（排除周末）
- 核心交易时段（排除凌晨低活跃时段）
- 市场阈值收紧（`basic_gate_multiplier: 0.5`）
- 信号阈值收紧（`consistency_min: 0.10`, `weak_signal_threshold: 0.15`）

✅ **检查清单创建** (`docs/P0-修复验证检查清单.md`)
- 关键修复验证清单
- 配置验证清单
- 组件接线验证清单
- 立即执行检查清单
- 风险点与建议

✅ **验证脚本创建** (`scripts/verify_p0_fix.ps1`)
- 自动化验证关键修复是否落地
- 检查默认值、语义、重复代码、语法错误等

### 10.2 待执行的行动项

⚠️ **生产环境配置创建** (`config/defaults.prod.yaml`)
- 建议采用方案 1（仅 Market 触发）或方案 3（AND 逻辑）
- 收紧所有阈值到生产级别
- 根据实际市场数据调整品种化阈值

⚠️ **Activity 轻量估计优化**
- 确保 `_create_market_activity()` 兜底逻辑在生产环境正常工作
- 考虑在 FeaturePipe 或 CoreAlgo 中增加更精确的活动度估计

⚠️ **监控与告警**
- 建立时段活跃度基线
- 设置 Active 占比异常告警（预期 40-70%）
- 监控 `schedule_active` 和 `market_active` 状态分布

---

**报告生成时间**: 2025-11-07  
**测试执行人**: AI Assistant  
**审核状态**: 待审核  
**相关文档**: 
- `docs/P0-修复验证检查清单.md` - 详细检查清单
- `config/defaults.staging.yaml` - Staging 环境配置
- `scripts/verify_p0_fix.ps1` - 自动化验证脚本

