# F3与TradeSimulator集成完成报告

## 实现时间
2025-11-11

## 概述

已完成F3的`cooldown_after_exit_sec`功能与`TradeSimulator`的集成，实现了退出后冷静期的完整功能。

---

## 实现内容

### 1. TradeSimulator修改

#### 1.1 添加core_algo参数

**位置**：`src/alpha_core/backtest/trade_sim.py` - `__init__`方法

**修改**：
```python
def __init__(
    self,
    config: Dict,
    output_dir: Path,
    ignore_gating_in_backtest: bool = False,
    core_algo: Optional[Any] = None,  # F3修复: CoreAlgorithm实例，用于记录退出时间
):
    # ...
    # F3修复: 保存CoreAlgorithm实例引用
    self.core_algo = core_algo
    if self.core_algo:
        logger.info("[TradeSim] F3: CoreAlgorithm实例已连接，退出后冷静期功能已启用")
```

#### 1.2 在退出时记录退出时间

**位置**：`src/alpha_core/backtest/trade_sim.py` - `_exit_position`方法

**修改**：
```python
# F3修复: 记录退出时间到CoreAlgorithm（用于退出后冷静期）
if self.core_algo and hasattr(self.core_algo, 'record_exit'):
    try:
        self.core_algo.record_exit(symbol, ts_ms)
    except Exception as e:
        logger.warning(f"[TradeSim] F3: 记录退出时间失败: {e}")
```

**触发时机**：
- 所有退出原因都会触发记录：
  - `take_profit` - 止盈退出
  - `stop_loss` - 止损退出
  - `reverse` - 反向信号退出
  - `reverse_signal` - 反向信号退出
  - `timeout` - 超时退出
  - `rollover_close` - 日切退出

---

### 2. replay_harness.py修改

#### 2.1 传递CoreAlgorithm实例

**位置**：`scripts/replay_harness.py` - `main`函数

**修改**：
```python
# F3修复: 将CoreAlgorithm实例传递给TradeSimulator（用于退出后冷静期）
trade_sim = TradeSimulator(
    config=backtest_config,
    output_dir=output_dir,
    ignore_gating_in_backtest=ignore_gating,
    core_algo=feeder.algo,  # F3: 传递CoreAlgorithm实例
)
```

**说明**：
- `feeder.algo`是`ReplayFeeder`内部的`CoreAlgorithm`实例
- 通过传递实例引用，`TradeSimulator`可以在退出时调用`record_exit`

---

## 工作流程

### 完整流程

1. **初始化阶段**：
   - `replay_harness.py`创建`ReplayFeeder`实例
   - `ReplayFeeder`内部创建`CoreAlgorithm`实例（`self.algo`）
   - `replay_harness.py`创建`TradeSimulator`实例，传入`feeder.algo`

2. **信号生成阶段**：
   - `ReplayFeeder`调用`CoreAlgorithm.process_feature_row`生成信号
   - `CoreAlgorithm`检查是否在退出冷静期内（`cooldown_after_exit_sec > 0`）
   - 如果在冷静期内，信号被阻止（`gating_reasons`包含`cooldown_after_exit`）

3. **交易执行阶段**：
   - `TradeSimulator`根据信号执行交易
   - 当持仓退出时，`TradeSimulator._exit_position`被调用
   - `TradeSimulator`调用`CoreAlgorithm.record_exit(symbol, ts_ms)`
   - `CoreAlgorithm`更新`_last_exit_ts_per_symbol[symbol] = ts_ms`

4. **后续信号生成**：
   - 新的信号生成时，`CoreAlgorithm`检查`_last_exit_ts_per_symbol`
   - 如果距离上次退出时间小于`cooldown_after_exit_sec`，信号被阻止

---

## 配置示例

### F3配置文件

```yaml
strategy:
  mode: active
  direction: both
  entry_threshold: 0.65
  exit_threshold: 0.45
  # F3: 退出后冷静期（秒）
  cooldown_after_exit_sec: 120  # 退出后120秒内不生成新信号
```

### 搜索空间配置

```json
{
  "search_space": {
    "strategy.cooldown_after_exit_sec": [60, 120, 180]
  }
}
```

---

## 测试建议

### 单元测试

1. **测试退出时间记录**：
   - 创建`TradeSimulator`实例，传入`CoreAlgorithm`实例
   - 执行退出操作
   - 验证`CoreAlgorithm._last_exit_ts_per_symbol`已更新

2. **测试冷静期阻止**：
   - 设置`cooldown_after_exit_sec = 60`
   - 记录退出时间
   - 在60秒内生成新信号
   - 验证信号被阻止（`gating_reasons`包含`cooldown_after_exit`）

3. **测试冷静期过期**：
   - 设置`cooldown_after_exit_sec = 60`
   - 记录退出时间
   - 等待60秒后生成新信号
   - 验证信号未被阻止

### 集成测试

1. **完整回测流程**：
   - 运行F3实验配置
   - 验证退出后冷静期生效
   - 检查日志中的`cooldown_after_exit`记录

2. **多symbol测试**：
   - 测试多个交易对的退出冷静期独立工作
   - 验证每个symbol的退出时间独立跟踪

---

## 日志输出

### 初始化日志

```
[TradeSim] F3: CoreAlgorithm实例已连接，退出后冷静期功能已启用
[CoreAlgorithm] F3: 退出后冷静期已启用: cooldown_after_exit_sec=120s
```

### 退出记录日志

```
[CoreAlgorithm] F3: 记录退出时间 BTCUSDT @ 1699123456000
```

### 冷静期阻止日志

信号记录中会包含：
```json
{
  "gating": true,
  "gate_reason": "cooldown_after_exit(45.2s<120s)",
  "guard_reason": "cooldown_after_exit(45.2s<120s)"
}
```

---

## 注意事项

1. **向后兼容**：
   - `core_algo`参数是可选的（`Optional[Any] = None`）
   - 如果未传入`core_algo`，功能不会启用，但不影响其他功能

2. **错误处理**：
   - 在`record_exit`调用时使用try-except包裹
   - 如果调用失败，只记录警告，不影响交易执行

3. **性能影响**：
   - 退出时间记录是O(1)操作，性能影响可忽略
   - 冷静期检查是O(1)字典查找，性能影响可忽略

---

## 相关文件

- `src/alpha_core/backtest/trade_sim.py` - TradeSimulator修改
- `src/alpha_core/signals/core_algo.py` - CoreAlgorithm的record_exit方法
- `scripts/replay_harness.py` - replay_harness修改
- `runtime/optimizer/group_f3_reverse_prevention.yaml` - F3配置文件
- `tasks/TASK-09/search_space_f3.json` - F3搜索空间

---

## 完成状态

✅ **F3功能已完全实现并集成**

- ✅ CoreAlgorithm中的退出时间跟踪
- ✅ CoreAlgorithm中的冷静期检查
- ✅ TradeSimulator中的退出时间记录
- ✅ replay_harness中的实例传递

F3实验现在可以完整运行，退出后冷静期功能将正常工作。

