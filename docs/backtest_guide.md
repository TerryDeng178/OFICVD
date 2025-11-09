# 回放+回测 Harness 使用指南

**版本**: v4.0.6  
**任务卡**: TASK-08

---

## 一、概述

回放+回测 Harness 用于离线复现实盘行为，快速定位"信号→成交→收益"的断点。支持两种输入路径：

1. **快路径**（推荐）：`features → signals → pnl`
2. **全路径**：`raw → features → signals → pnl`

---

## 二、快速开始

### 2.1 最小示例（快路径）

```powershell
python scripts/replay_harness.py `
  --input ./deploy/data/ofi_cvd `
  --date 2025-10-30 `
  --symbols BTCUSDT `
  --kinds features `
  --minutes 60 `
  --config ./config/backtest.yaml
```

### 2.2 全路径示例

```powershell
python scripts/replay_harness.py `
  --input ./deploy/data/ofi_cvd `
  --date 2025-10-30 `
  --symbols BTCUSDT,ETHUSDT `
  --kinds prices,orderbook `
  --session NY `
  --taker-fee-bps 2.0 `
  --slippage-bps 1.0 `
  --output ./runtime/backtest
```

---

## 三、输入数据格式

### 3.1 支持的输入格式

**JSONL格式**:
- 路径：`data/ofi_cvd/ready/{kind}/{symbol}/*.jsonl`
- 或：`data/ofi_cvd/preview/{kind}/{symbol}/*.jsonl`

**Parquet格式**:
- 路径：`data/ofi_cvd/date={YYYY-MM-DD}/symbol={SYMBOL}/kind={KIND}/*.parquet`

### 3.2 数据种类（kinds）

- **features**: 特征数据（快路径）
- **prices**: 价格数据（全路径）
- **orderbook**: 订单簿数据（全路径）
- **signals**: 信号数据（可选，用于验证）

---

## 四、配置说明

### 4.1 配置文件（backtest.yaml）

```yaml
signal:
  sink: jsonl  # jsonl | sqlite | null
  output_dir: ./runtime
  replay_mode: 1

components:
  fusion:
    w_ofi: 0.6
    w_cvd: 0.4

strategy:
  mode: active  # auto | active | quiet

risk:
  gates:
    max_spread_bps: 2.5
    max_lag_sec: 0.5
    require_activity: true

backtest:
  taker_fee_bps: 2.0
  slippage_bps: 1.0
  notional_per_trade: 1000
  reverse_on_signal: false
  take_profit_bps: null
  stop_loss_bps: null
  min_hold_time_sec: null
```

### 4.2 参数优先级

1. **命令行参数**（最高优先级）
2. **YAML配置**
3. **环境变量**（兜底）
4. **默认值**

---

## 五、输出文件

### 5.1 输出目录结构

```
runtime/backtest/{run_id}/
├── signals/
│   ├── ready/signal/{symbol}/signals_*.jsonl
│   └── signals.db (if sink=sqlite)
├── trades.jsonl
├── pnl_daily.jsonl
├── metrics.json
└── run_manifest.json
```

### 5.2 文件说明

**trades.jsonl**: 每笔交易记录
```json
{
  "ts_ms": 1731110400000,
  "symbol": "BTCUSDT",
  "side": "buy",
  "px": 50000.0,
  "qty": 0.02,
  "fee": 2.0,
  "slippage_bps": 1.0,
  "reason": "entry",
  "pos_after": 1
}
```

**pnl_daily.jsonl**: 每日PnL汇总
```json
{
  "date": "2025-10-30",
  "symbol": "BTCUSDT",
  "gross_pnl": 100.0,
  "fee": 4.0,
  "slippage": 2.0,
  "net_pnl": 94.0,
  "turnover": 2000.0,
  "win_rate": 0.6,
  "rr": 1.5,
  "trades": 10
}
```

**metrics.json**: 聚合指标
```json
{
  "total_trades": 100,
  "total_pnl": 1000.0,
  "win_rate": 0.55,
  "sharpe_ratio": 1.2,
  "sortino_ratio": 1.5,
  "max_drawdown": 200.0,
  "MAR": 5.0,
  "avg_hold_sec": 300.0
}
```

---

## 六、常见问题

### 6.1 数据不存在

**问题**: `[ERROR] 数据库不存在` 或 `[WARN] 未找到数据文件`

**解决**:
1. 确认输入目录路径正确
2. 检查数据文件是否存在
3. 确认日期格式为 `YYYY-MM-DD`

### 6.2 信号数量为0

**问题**: 运行后没有生成信号

**解决**:
1. 检查features数据是否包含必需字段（z_ofi, z_cvd, spread_bps等）
2. 检查风控参数是否过于严格
3. 查看日志中的gating原因

### 6.3 交易数量为0

**问题**: 有信号但没有交易

**解决**:
1. 确认信号中 `confirm=true` 且 `gating=false`
2. 检查交易模拟器配置
3. 查看信号类型是否正确（buy/sell/strong_buy/strong_sell）

---

## 七、性能优化

### 7.1 使用快路径

优先使用 `features` 输入，避免重复计算OFI/CVD。

### 7.2 限制时间范围

使用 `--minutes` 或 `--start-ms/--end-ms` 限制处理范围。

### 7.3 选择Sink类型

- **jsonl**: 适合单次回测，便于审计
- **sqlite**: 适合并发读取和查询

---

## 八、验证与对齐

### 8.1 信号对齐验证

使用 `verify_sink_parity.py` 验证回测信号与线上信号的一致性：

```powershell
python scripts/verify_sink_parity.py `
  --jsonl-dir ./runtime/backtest/{run_id}/signals/ready/signal `
  --sqlite-db ./runtime/backtest/{run_id}/signals/signals.db `
  --run-id {run_id}
```

### 8.2 差异阈值

- **信号数量差异**: ≤ 5%
- **StrongRatio差异**: ≤ 10%
- **PnL曲线**: 主要场景（A_H/Q_H）同向

### 8.3 常见差异来源（P1）

**窗口对齐**:
- 回测使用UTC时间，生产可能使用本地时间
- 使用 `--start-ms` 和 `--end-ms` 精确指定时间范围

**日切口径**:
- 默认使用UTC日切（`rollover_timezone: "UTC"`）
- 可在 `config/backtest.yaml` 中配置 `rollover_timezone: "Asia/Tokyo"` 等
- 多平台时区/夏令时会影响MAR与日收益曲线年化口径

**闸门口径**:
- 默认 `ignore_gating_in_backtest: true`（绕过闸门，用于纯策略收益评估）
- 但仍统计gate原因分布，输出到 `gate_reason_breakdown.json`
- 可通过 `--ignore-gating false` 或配置关闭

**缺秒回填**:
- Aligner自动检测缺失秒（gap > 1.5秒）
- 使用拉链式回填（前一个有效价格）
- `is_gap_second` 标志位标识缺失秒

**滑点/费用口径**:
- 滑点：`slippage_bps`（默认1.0 bps）
- 费用：`taker_fee_bps`（默认2.0 bps）
- 滑点已修正成交价，不再单独扣除（P0修复）

**Reader去重口径**:
- **Features数据**: 按 `(symbol, second_ts)` 去重
  - 策略：每秒末样本优先（保留该秒内最后一条记录）
  - 原因：features数据按秒聚合，每秒应只有一条记录
- **其他数据（prices/orderbook）**: 按 `(symbol, ts_ms)` 去重
  - 策略：最后事件优先（保留该毫秒内最后一条记录）
  - 原因：原始数据可能在同一毫秒内有多次更新
- **去重率**: 通过 `reader_stats.deduplicated_rows` 和 `reader_stats.total_rows` 计算
- **建议**: 如果去重率过高（>50%），检查数据源是否有重复写入

---

## 九、Pushgateway指标推送（P1）

### 9.1 启用指标推送

**状态**: ✅ **已实现，支持11个backtest_*指标，带重试机制**

设置环境变量启用Pushgateway指标推送：

```powershell
# Windows PowerShell
$env:TIMESERIES_ENABLED = "1"
$env:TIMESERIES_TYPE = "prometheus"
$env:TIMESERIES_URL = "http://localhost:9091"
$env:RUN_ID = "backtest_20251109_001"
$env:BACKTEST_SYMBOL = "BTCUSDT"
$env:BACKTEST_SESSION = "all"

# Linux/macOS Bash
export TIMESERIES_ENABLED=1
export TIMESERIES_TYPE=prometheus
export TIMESERIES_URL=http://localhost:9091
export RUN_ID=backtest_20251109_001
export BACKTEST_SYMBOL=BTCUSDT
export BACKTEST_SESSION=all
```

**说明**:
- 方法已实现（`MetricsAggregator._export_to_pushgateway()`）
- 自动在保存metrics后调用
- 支持指数退避重试（最多3次）
- 需要启动Pushgateway服务才能验证推送功能

### 9.2 推送的指标

- `backtest_total_pnl{run_id, symbol, session}`
- `backtest_sharpe{run_id, symbol, session}`
- `backtest_sortino{run_id, symbol, session}`
- `backtest_mar{run_id, symbol, session}`
- `backtest_win_rate{run_id, symbol, session}`
- `backtest_rr{run_id, symbol, session}`
- `backtest_avg_hold_sec{run_id, symbol, session}`
- `backtest_trades_total{run_id, symbol, session}`
- `backtest_turnover{run_id, symbol, session}`
- `backtest_fee_total{run_id, symbol, session}`
- `backtest_slippage_total{run_id, symbol, session}`

### 9.3 使用示例

完整回测并推送指标：

```powershell
# Windows PowerShell
$env:TIMESERIES_ENABLED = "1"
$env:TIMESERIES_TYPE = "prometheus"
$env:TIMESERIES_URL = "http://localhost:9091"
$env:RUN_ID = "backtest_20251109_001"
$env:BACKTEST_SYMBOL = "BTCUSDT"
$env:BACKTEST_SESSION = "all"

python scripts/replay_harness.py `
  --input ./deploy/data/ofi_cvd `
  --kinds features `
  --symbols BTCUSDT `
  --minutes 60
```

### 9.4 重试机制

Pushgateway推送支持指数退避重试：
- **最大重试次数**: 3次
- **重试延迟**: 0.5s, 1s, 2s（指数退避）
- **失败处理**: 记录警告日志，不影响回测流程

### 9.5 查看指标

访问 Pushgateway 的 `/metrics` 端点查看推送的指标：

```bash
# 查看所有指标
curl http://localhost:9091/metrics

# 查看特定run_id的指标
curl "http://localhost:9091/metrics/job/backtest_backtest_20251109_001"
```

### 9.6 验证推送

检查日志输出，确认推送成功：

```
[MetricsAggregator] Exported 11 metrics to Pushgateway (attempt 1)
```

如果推送失败，会看到重试日志：

```
[MetricsAggregator] Pushgateway export failed (attempt 1): Connection refused, retrying in 0.5s
[MetricsAggregator] Exported 11 metrics to Pushgateway (attempt 2)
```

---

## 十、健康度指标（P1）

### 10.1 Sink健康度指标

回测系统会收集并报告sink的健康度指标：

- **signal_sink_queue_size**: SQLite Sink的批量队列大小
- **signal_sink_dropped**: SQLite Sink的丢弃计数（批量刷新失败时）
- **sink_kind**: Sink类型（jsonl/sqlite/multi）

这些指标会出现在：
- `run_manifest.json` 的 `sink_health` 字段
- `feeder_stats` 中（如果启用）

### 10.2 监控建议

- **queue_size > 1000**: 可能表示批量刷新频率过低，建议调整 `SQLITE_FLUSH_MS`
- **dropped_count > 0**: 表示有数据丢失，需要检查数据库写入和磁盘空间

---

## 十一、示例脚本

### 11.1 Windows PowerShell

见 `scripts/demo_backtest.ps1`

### 11.2 Linux/macOS Bash

见 `scripts/demo_backtest.sh`

---

**文档版本**: v4.0.6  
**最后更新**: 2025-11-09  
**P1改进**: 已更新（Pushgateway推送、日切口径、闸门口径、健康度指标等）

