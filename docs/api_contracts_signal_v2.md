# Signal v2 API Contract

## 概述

`signal/v2` 是 CoreAlgorithm 的统一输出契约，实现了单点判定逻辑（gating/regime/confirm/cooldown/expiry），下游（Executor/Adapter/Report）只消费已判定好的结果位与审计信息。

## Schema 定义

### 字段说明

| 字段                | 类型                                       | 说明                                                                           |
| ----------------- | ---------------------------------------- | ---------------------------------------------------------------------------- |
| `schema_version`  | string, const=`"signal/v2"`              | 契约版本（便于灰度/回放）                                                                |
| `ts_ms`           | int                                      | UTC 毫秒级时间戳（生产时区统一）                                                           |
| `symbol`          | string                                   | 交易对（大写标准化，如 `BTCUSDT`）                                                       |
| `signal_id`       | string                                   | `<run_id>-<symbol>-<ts_ms>-<seq>` 幂等键（无空格）                                   |
| `score`           | float                                    | 归一化打分（-inf..+inf，推荐范围 -5..+5）                                                |
| `side_hint`       | enum{`buy`,`sell`,`flat`}                | 方向提示（供下游映射 side/qty）                                                         |
| `z_ofi`           | float                                    | OFI z-score（可选审计）                                                            |
| `z_cvd`           | float                                    | CVD z-score（可选审计）                                                            |
| `div_type`        | enum{`none`,`bull`,`bear`}               | 背离类型（可选）                                                                     |
| `regime`          | enum{`quiet`,`trend`,`revert`,`unknown`} | 市场状态判定（单点产出）                                                                 |
| `gating`          | int{0,1}                                 | 是否通过门控（单点产出）                                                                 |
| `confirm`         | bool                                     | 是否形成"可执行信号"（`gating==1 && score>=entry` 且未触发冷却 && 未过期） |
| `cooldown_ms`     | int                                      | 当前信号需要执行的冷却时长（ms），0 表示不受限                                                    |
| `expiry_ms`       | int                                      | 信号有效期（ms），到期仍未执行则无效                                                          |
| `decision_code`   | string                                   | 判定代码（如 `OK`, `COOLDOWN`, `EXPIRE`, `LOW_SCORE`, `BAD_REGIME`, `FAIL_GATING`） |
| `decision_reason` | string                                   | 人类可读原因（简短）                                                                   |
| `config_hash`     | string                                   | `core.*` 参数哈希（稳定序列化+SHA1）                                                    |
| `run_id`          | string                                   | 本次运行指纹（回放可溯源）                                                                |
| `meta`            | object                                   | 其他审计字段：`{window_ms, features_ver, rules_ver}`                                |

### 约束

* `confirm=true ⇒ gating=1 && decision_code=OK`

## JSONL 示例

```json
{"schema_version":"signal/v2","ts_ms":1731369600123,"symbol":"BTCUSDT","signal_id":"r42-BTCUSDT-1731369600123-0","score":2.41,"side_hint":"buy","z_ofi":1.8,"z_cvd":1.5,"div_type":"bull","regime":"trend","gating":1,"confirm":true,"cooldown_ms":0,"expiry_ms":60000,"decision_code":"OK","decision_reason":"score>=entry & trend","config_hash":"9ef1d7...","run_id":"r42","meta":{"window_ms":120000,"features_ver":"ofi/cvd v3","rules_ver":"core v1"}}
```

## SQLite 表结构

```sql
CREATE TABLE IF NOT EXISTS signals (
  ts_ms INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  signal_id TEXT NOT NULL,
  schema_version TEXT NOT NULL DEFAULT 'signal/v2',
  score REAL NOT NULL,
  side_hint TEXT NOT NULL,
  z_ofi REAL,
  z_cvd REAL,
  div_type TEXT,
  regime TEXT NOT NULL,
  gating INTEGER NOT NULL,
  confirm INTEGER NOT NULL,
  cooldown_ms INTEGER NOT NULL,
  expiry_ms INTEGER NOT NULL,
  decision_code TEXT NOT NULL,
  decision_reason TEXT,
  config_hash TEXT NOT NULL,
  run_id TEXT NOT NULL,
  meta TEXT,
  PRIMARY KEY(symbol, ts_ms, signal_id)
) WITHOUT ROWID;
```

## 下游消费规则

### Executor/Adapter

* **只消费 `confirm` 和 `side_hint`**：如果 `confirm=true`，Executor 应该直接执行，不再做二次门控检查。
* **禁止二次门控**：Executor/Adapter 不再检查 gating/threshold/regime，这些检查已在 CoreAlgorithm 中完成。
* **数据质量检查**：ExecutorPrecheck 中的检查（warmup、consistency、spread、lag）是数据质量相关的，不是门控逻辑，可以保留。

### 配置

启用 signal/v2 需要在配置中设置：

```yaml
core:
  use_signal_v2: true
  expiry_ms: 60000
  cooldown_ms: 30000
  allow_quiet: false
  gating:
    ofi_z: 1.5
    cvd_z: 1.2
    enable_divergence_alt: true
  threshold:
    entry:
      trend: 1.8
      revert: 2.2
      quiet: 2.8
  regime:
    z_t: 1.2
    z_r: 1.0
```

## 输出文件规范

### JSONL 文件命名

**v2 标准命名**（新标准）：
- 格式：`signals-YYYYMMDD-HH.jsonl`（连字符，按小时轮转）
- 路径：`{output_dir}/ready/signal/{SYMBOL}/signals-YYYYMMDD-HH.jsonl`
- 示例：`runtime/ready/signal/BTCUSDT/signals-20241112-14.jsonl`

**v1 兼容命名**（向后兼容）：
- 格式：`signals_YYYYMMDD_HHMM.jsonl`（下划线，按分钟轮转）
- 路径：`{output_dir}/ready/signal/{SYMBOL}/signals_YYYYMMDD_HHMM.jsonl`
- 示例：`runtime/ready/signal/BTCUSDT/signals_20241112_1430.jsonl`

**读取策略**：
- Strategy Server 的 `read_signals_from_jsonl()` 同时支持两种命名格式
- 优先读取 v2 格式（`signals-*.jsonl`），然后兼容 v1 格式（`signals_*.jsonl`）

### SQLite 数据库

**v2 标准数据库**：
- 文件名：`signals_v2.db`（默认，避免与 v1 冲突）
- 表名：`signals`
- 主键：`(symbol, ts_ms, signal_id)`

**v1 兼容数据库**：
- 文件名：`signals.db`（旧格式）
- 表名：`signals`
- 主键：`(symbol, ts_ms)`（无 signal_id 列）

**自动探测策略**：
- Strategy Server 的 `--signals-source=auto` 模式：
  1. 优先查找 `signals_v2.db`（v2 格式）
  2. 回退到 `signals.db`（v1 格式）
  3. 如果数据库不存在，查找 JSONL 文件（优先 v2 格式）

### 优雅退出要求

**SignalWriterV2.close()**：
- 关闭时刷新 SQLite 剩余批次，确保所有队列数据写入数据库
- 对 JSONL 当前小时文件执行最后一次 fsync，确保数据持久化
- 确保进程退出时所有数据已落盘

**使用建议**：
- Orchestrator/Strategy Server 在收到 SIGTERM/SIGINT 信号时，应调用 `CoreAlgorithm.close()`，进而调用 `SignalWriterV2.close()`
- 确保优雅退出，避免数据丢失

## v1→v2 升级

使用 `SignalV2.upgrade_v1_to_v2()` 函数可以将 `signal/v1` 格式升级为 `signal/v2` 格式（只读升级，不修改原始数据）。

