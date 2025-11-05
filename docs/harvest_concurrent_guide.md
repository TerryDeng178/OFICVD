# HARVEST 并发运行指南

## 问题
如果已经有另一个 HARVEST 进程在运行，再运行新的 HARVEST 是否会影响已经运行的进程？

## 答案
**可以同时运行，但建议使用不同的输出目录以避免混乱。**

## 影响分析

### 1. WebSocket 连接
- ✅ **无冲突**：每个进程独立连接到 Binance
- ⚠️ **会重复接收数据**：多个进程会重复订阅相同的数据流
- 📊 **影响**：浪费带宽，但不会导致进程崩溃

### 2. 文件写入
- ✅ **文件名唯一**：使用 `part-{纳秒时间戳}-{UUID}.parquet`，冲突概率极低
- ⚠️ **目录竞争**：如果使用相同输出目录，文件会混在一起
- 📊 **影响**：虽然不会覆盖，但难以区分哪个进程生成了哪个文件

### 3. DQ 报告和 Deadletter
- ✅ **文件名唯一**：使用时间戳 + UUID，冲突概率低
- ⚠️ **报告混淆**：多个进程的报告混在一起，难以区分
- 📊 **影响**：统计和排查困难

## 推荐解决方案

### 方案1：使用不同的输出目录（推荐）

**方法1：通过环境变量**
```bash
# 进程1（已有）
export OUTPUT_DIR=./data/harvest_instance1
python scripts/run_success_harvest.py

# 进程2（新运行）
export OUTPUT_DIR=./data/harvest_instance2
python scripts/run_success_harvest.py
```

**方法2：通过配置文件**
```bash
# 进程1（已有）
python scripts/run_success_harvest.py --config config/harvest1.yaml

# 进程2（新运行）
python scripts/run_success_harvest.py --config config/harvest2.yaml
```

### 方案2：采集不同的 Symbol（如果不需要重复数据）

```bash
# 进程1：采集 BTCUSDT, ETHUSDT
export SYMBOLS=BTCUSDT,ETHUSDT
python scripts/run_success_harvest.py

# 进程2：采集 BNBUSDT, SOLUSDT
export SYMBOLS=BNBUSDT,SOLUSDT
python scripts/run_success_harvest.py
```

### 方案3：添加进程锁（需要修改代码）

如需防止同时运行，可以添加进程锁检查：

```python
import fcntl
import os

lock_file = Path('/tmp/harvest.lock')
if lock_file.exists():
    print("已有 HARVEST 进程在运行，退出")
    sys.exit(1)

with open(lock_file, 'w') as f:
    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    # 运行采集...
```

## 总结

| 项目 | 是否有冲突 | 建议 |
|------|-----------|------|
| WebSocket 连接 | ❌ 无冲突 | 可以同时连接 |
| 文件写入 | ⚠️ 文件名唯一但目录混乱 | 使用不同输出目录 |
| 进程互斥 | ❌ 无保护 | 需要时可添加进程锁 |
| 资源浪费 | ⚠️ 会重复接收数据 | 如不需要重复数据，使用不同 Symbol |

## 最佳实践

1. **使用不同的输出目录**：避免文件混淆
2. **使用不同的日志文件**：便于区分和调试
3. **监控资源使用**：避免过度消耗网络和磁盘
4. **定期检查**：确保数据完整性

