# 数据质量（DQ）日报规范

> **版本**: v4.0.3  
> **更新日期**: 2025-11-07

---

## 1. 概述

数据质量（DQ）日报用于监控和报告系统运行过程中的数据质量指标，包括信号生成质量、场景覆盖、护栏统计等。

---

## 2. 信号→订单链路一致口径（DoD）

### 2.1 核心约定

**所有统计和订单处理均以 `confirm=true` 为准**：

### 2.0 P0: DoD 固化为 CI 断言

以下断言在 CI 中自动验证：

- ✅ `confirm=true` 口径一致（双 Sink ≤10%）
- ✅ 报表 `warnings` 不包含 `NO_INPUT_FILES`/`QUIET_RUN`/`ALL_GATED`
- ✅ 产出 `run_manifest_*.json` 且 `source_versions` 字段完整

### 2.1 核心约定

- ✅ **Reporter 统计**: 仅统计 `confirm=true` 的信号
  - `total`: 确认信号总数
  - `buy_count` / `sell_count`: 确认的买卖信号数
  - `strong_buy_count` / `strong_sell_count`: 确认的强信号数
  - `strong_ratio`: 强信号比例（基于确认信号）

- ✅ **Broker 下单**: 仅处理 `confirm=true` 的信号
  - 强信号（`strong_buy` / `strong_sell`）: 100% 下单
  - 普通信号（`buy` / `sell`）: 按 `sample_rate` 抽样下单（默认 0.2）

- ✅ **统计口径一致性**: JSONL 和 SQLite 两种 Sink 的统计口径完全一致
  - 双 Sink 结果对齐脚本（`scripts/verify_sink_parity.*`）验证一致性
  - 容忍差异 ≤10%

### 2.2 护栏（Gating）说明

信号在生成过程中可能被以下护栏拦截：

#### 2.2.1 护栏原因枚举/映射表（P1）

**Canonical Keys**（标准键名）:

| Canonical Key | 别名/变体 | 说明 |
|--------------|----------|------|
| `low_consistency` | `low_consistency`, `consistency_low` | 一致性不足（低于 `consistency_min` 或 `consistency_min_per_regime`） |
| `warmup` | `warmup`, `warm_up` | 预热期（特征计算窗口未满） |
| `weak_signal` | `weak_signal`, `weak`, `signal_weak` | 弱信号（低于 `weak_signal_threshold`） |
| `lag_sec>3.0` | `lag_sec>3.0`, `lag_too_high`, `lag_exceeded` | 延迟过大（超过 `lag_cap_sec`） |
| `spread_bps>20.0` | `spread_bps>20.0`, `spread_too_high`, `spread_exceeded` | 价差过大（超过 `spread_bps_cap`） |

**Reporter 侧处理**:
- 对 `guard_reason` 做拆分+映射，统一到 canonical key
- 避免因大小写/别名导致对齐误差

**标准护栏原因**:
- `low_consistency`: 一致性不足（低于 `consistency_min` 或 `consistency_min_per_regime`）
- `warmup`: 预热期（特征计算窗口未满）
- `weak_signal`: 弱信号（低于 `weak_signal_threshold`）
- `lag_sec>3.0`: 延迟过大（超过 `lag_cap_sec`）
- `spread_bps>20.0`: 价差过大（超过 `spread_bps_cap`）

被护栏拦截的信号 `confirm=false`，不计入统计和订单处理。

---

## 3. 场景覆盖切面（P1）

### 3.1 场景定义

基于 StrategyMode 的 regime 和信号强度，定义 2×2 场景矩阵：

| Regime | 强信号 | 普通信号 |
|--------|--------|----------|
| **ACTIVE** | A_H | A_L |
| **QUIET** | Q_H | Q_L |

### 3.2 覆盖统计

Harvester 输出 `slices_manifest`，包含场景覆盖信息：

```json
{
  "scenarios": {
    "A_H": {"count": 150, "coverage": 0.95},
    "A_L": {"count": 1200, "coverage": 0.98},
    "Q_H": {"count": 50, "coverage": 0.90},
    "Q_L": {"count": 800, "coverage": 0.92}
  }
}
```

### 3.3 DQ 日报展示

建议在日报或 CI 工件中展示：

- ✅ 场景覆盖率（每个场景的 `coverage`）
- ⚠️ 失败项（`coverage < 0.90`）
- 📊 场景分布（各场景的信号数量）

---

## 4. 护栏分解统计

### 4.1 总体统计

Reporter 输出 `gating_breakdown`，统计各护栏原因的触发次数：

```json
{
  "gating_breakdown": {
    "low_consistency": 1529501,
    "warmup": 181543,
    "weak_signal": 29426,
    "lag_sec>3.0": 24
  }
}
```

### 4.2 按 Regime 分组

Reporter 输出 `gating_breakdown_by_regime`，按 regime 分组统计：

```json
{
  "gating_breakdown_by_regime": {
    "active": {
      "weak_signal": 29426,
      "lag_sec>3.0": 24
    },
    "quiet": {
      "low_consistency": 1529501,
      "warmup": 181543
    }
  }
}
```

### 4.3 按分钟分组

Reporter 输出 `gating_breakdown_by_minute`，按分钟分组统计（最近5分钟）：

```json
{
  "gating_breakdown_by_minute": [
    {"low_consistency": 2075, "warmup": 186, "weak_signal": 46},
    {"low_consistency": 1901, "warmup": 360, "weak_signal": 7},
    ...
  ]
}
```

---

## 5. 健康/就绪探针基线配置

### 5.1 实时场景

- **JSONL 文件探针**:
  - `min_new_last_seconds`: 120（最近120秒内）
  - `min_new_count`: 1（至少1个新文件）
  - `max_idle_seconds`: 60（最近60秒内必须有文件更新）

- **SQLite 行增长探针**:
  - `min_growth_window_seconds`: 120（最近2分钟）
  - `min_growth_count`: 1（至少1行增长）

### 5.2 SMOKE/回放场景

- **JSONL 文件探针**:
  - `min_new_last_seconds`: 0（跳过时间窗口检查，历史数据友好化）
  - `min_new_count`: 1（至少1个新文件）
  - `max_idle_seconds`: None（不检查最大空闲时间）

- **SQLite 行增长探针**:
  - 保持实时场景配置（或根据回放数据量调整）

### 5.3 配置方式

通过环境变量或配置文件名称控制：

```powershell
# 回放模式
$env:V13_REPLAY_MODE = "1"
python -m orchestrator.run --config ./config/defaults.replay.yaml ...

# 实时模式（默认）
python -m orchestrator.run --config ./config/defaults.yaml ...
```

---

## 6. 运行清单（run_manifest）作为发布证据

### 6.1 清单内容

每次运行生成 `run_manifest_*.json`，包含：

```json
{
  "run_id": "20251107_142033",
  "started_at": "2025-11-07T14:19:22.822496",
  "ended_at": "2025-11-07T14:20:33.097688",
  "duration_s": 70.275192,
  "config": "F:\\OFICVD\\config\\defaults.smoke.yaml",
  "sink": "jsonl",
  "enabled_modules": ["report", "signal"],
  "status": {...},
  "report": {...},
  "source_versions": {
    "git_head": "6d99b6d28cd8d0f005ec20bf42d679638c13b02a",
    "git_dirty": true,
    "python_version": "3.11.9"
  }
}
```

### 6.2 CI 集成

GitHub Actions CI 自动上传运行清单作为发布证据：

```yaml
- name: 上传运行清单（发布证据）
  uses: actions/upload-artifact@v4
  with:
    name: run-manifests-${{ matrix.os }}-${{ github.run_number }}
    path: |
      deploy/artifacts/ofi_cvd/run_logs/*.json
      logs/report/*.json
      logs/report/*.md
    retention-days: 30
```

---

## 7. Broker 抽样率作为策略节律旋钮

### 7.1 配置方式

通过环境变量或 CLI 参数控制：

```powershell
# 默认抽样率（0.2）
python -m orchestrator.run --config ./config/defaults.smoke.yaml --enable broker

# 自定义抽样率
$env:BROKER_SAMPLE_RATE = "0.5"
python -m orchestrator.run --config ./config/defaults.smoke.yaml --enable broker
```

### 7.2 SMOKE 档基线（P1）

建议在不同 SMOKE 档做回归基线：

| 档位 | 抽样率 | 说明 |
|------|--------|------|
| **低档** | 0.1 | 10% 普通信号下单，用于低频率场景 |
| **默认档** | 0.2 | 20% 普通信号下单，当前默认值 |
| **高档** | 0.5 | 50% 普通信号下单，用于高频率场景 |

用于观察成交节律与 PnL 的敏感度。

### 7.3 夜间定时回归（P1）

建议在 CI 中添加夜间定时回归任务，使用不同抽样率档位：

```yaml
on:
  schedule:
    - cron: '0 2 * * *'  # 每天凌晨 2 点
```

### 7.4 日报字段（P1）

建议在日报中添加以下字段：

- `broker_sample_rate`: 普通信号抽样率
- `strong_to_normal_ratio`: 强/普下单比
- `order_rhythm`: 成交节律（每分钟订单数）

用于长期监控成交节律对 PnL 的敏感度。

---

## 8. 监控告警阈值

### 8.1 OFI 心跳频率

- **告警阈值**: 连续 2 分钟 = 0/分钟
- **告警动作**: 记录警告日志，触发健康检查失败

### 8.2 数据质量警示

- **场景覆盖不足**: `coverage < 0.90` 的场景
- **护栏占比过高**: `low_consistency` 占比 > 90%
- **信号生成异常**: `total == 0` 或 `per_minute` 全为 0

---

**文档维护**: 随系统版本更新，保持与代码实现一致。

