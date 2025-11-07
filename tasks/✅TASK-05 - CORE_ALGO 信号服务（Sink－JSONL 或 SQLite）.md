# TASK-05 · CORE_ALGO 信号服务（Sink: JSONL / SQLite）

> 里程碑：M2 · 目标：最小可跑 + 可观测 + 可回放｜状态：已完成（2025-11-06）
> 产出：CoreAlgorithm 精简实现 + MCP 薄壳 + JSONL/SQLite Sink + 单测 5/5 ✅

---

## 1) 背景与范围（Scope）

统一信号服务，将 OFI / CVD / FUSION / DIVERGENCE 四路成熟组件输出做融合、护栏与确认，输出到可插拔 Sink（JSONL / SQLite）。本任务仅聚焦**信号层**：

* **输入**：来自 features 宽表/流的单行 feature_row（含 z_ofi、z_cvd、价格、活跃度/波动、盘口指标、缺报率等）。
* **处理**：CoreAlgorithm 计算融合分数、护栏判断、反向防抖、一致性与弱信号节流、背离加成；得出 confirm/gating。
* **输出**：结构化信号（JSONL 或 SQLite），供风控/执行与回放/复盘复用。

不含：行情采集（HARVEST）、下单网关、策略PNL验证等。

---

## 2) 模块与入口（与仓库对齐）

* **核心类**：`src/alpha_core/signals/core_algo.py` → `class CoreAlgorithm`
* **薄壳**：`mcp/signal_server/app.py`（CLI/HTTP，可选）
* **运行环境变量**：`V13_SINK`=`jsonl|sqlite|null`，`V13_OUTPUT_DIR`，`V13_DEBUG`（布尔），`V13_REPLAY_MODE`（0/1，可选）

---

## 3) 对外契约（I/O）

### 3.1 输入（features → CORE_ALGO）

```jsonc
{
  "ts_ms": 1730790000456,
  "symbol": "BTCUSDT",
  "z_ofi": 1.8,
  "z_cvd": 0.9,
  "price": 70325.1,
  "lag_sec": 0.04,
  "spread_bps": 1.2,
  "fusion_score": 0.73,
  "consistency": 0.42,
  "div_type": null,
  "activity": { "tps": 2.3 },
  "warmup": false,
  "reason_codes": []
}
```

> 说明：直接消费 FeaturePipe 输出（任务 04）。如缺少 `fusion_score`，信号层会按权重重新加总 `z_ofi` 和 `z_cvd`。

### 3.2 输出（CORE_ALGO → Sink）

```jsonc
{
  "ts_ms": 1730790000456,
  "symbol": "BTCUSDT",
  "score": 1.72,
  "z_ofi": 1.9,
  "z_cvd": 1.3,
  "regime": "active",
  "div_type": null,
  "confirm": true,
  "gating": false,
  "signal_type": "strong_buy",
  "guard_reason": null
}
```

* **JSONL 落地**：`<output_dir>/ready/signal/{symbol}/signals_YYYYMMDD_HHMM.jsonl`
* **SQLite 表结构**：`signals(ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason)`

---

## 4) 核心类与函数（Cursor 执行要点）

### 4.1 `CoreAlgorithm.process_feature_row(row: Dict[str, Any]) -> Optional[Dict]`

* 校验字段：`ts_ms/symbol/z_ofi/z_cvd/spread_bps/lag_sec/consistency/warmup`
* 去重：同一 `symbol` 若时间戳差 < `dedupe_ms`（默认 250ms）直接丢弃
* 评分：优先使用 `fusion_score`，缺失时按权重组合 `z_ofi/z_cvd`
* 护栏：warmup / spread / lag / consistency / weak signal / reason_codes → `guard_reason`
* Regime：基于 `activity.tps`（active/normal/quiet）读取阈值
* 输出：返回信号字典（见 3.2）；若被去重或字段缺失 → 返回 `None`

### 4.2 Sink 抽象与实现

* `JsonlSink(base_dir)`：按分钟追加到 `ready/signal/{symbol}/signals_YYYYMMDD_HHMM.jsonl`
* `SqliteSink(base_dir)`：`signals.db` + WAL，`INSERT OR REPLACE` 写入信号表
* `NullSink()`：测试/压测专用（禁用 I/O）

### 4.3 运行时配置

* `config/defaults.yaml` 的 `signal.*` 段：权重、阈值、护栏、Sink 输出位置
* CLI 参数：`--sink jsonl|sqlite|null`、`--out ./runtime`、`--print`
* 支持 YAML 覆盖：`python -m mcp.signal_server.app --config ./config/defaults.yaml`

---

## 5) MCP 薄壳 / 本地运行（最小可跑）

### 5.1 JSONL Sink（默认）

```bash
python -m mcp.signal_server.app \
  --config ./config/defaults.yaml \
  --input ./runtime/features.jsonl \
  --sink jsonl \
  --out ./runtime \
  --print
```

### 5.2 SQLite Sink（并发友好）

```bash
python -m mcp.signal_server.app \
  --config ./config/defaults.yaml \
  --input ./runtime/features.jsonl \
  --sink sqlite \
  --out ./runtime
```

### 5.3 脚本

* Bash：`bash scripts/signal_demo.sh`
* PowerShell：`.\scripts\signal_demo.ps1 -Print`

---

## 6) 测试用例（Cursor 可直接跑）

1. **功能冒烟**：mock 一条 features 行，期望产出 `confirm=true`；再降低 z_ofi/z_cvd、增大 spread/缺报率，期望 `gating=true` 与正确 `guard_reason`。
2. **弱信号节流**：`|score| < weak_signal_threshold` → 被拦截；`|score| >= weak_signal_threshold` 且一致性达标 → 放行。
3. **背离加成**：模拟 bull_div 信号，阈值应按 0.8 系数降低，通过概率提高。
4. **JSONL Sink**：并发 `emit` 写入，轮转分钟边界后文件换名成功，`ready/signal/{symbol}` 目录存在新增文件。
5. **SQLite Sink（WAL）**：并发读脚本周期性 `SELECT count(*)`，写入线程持续插入；无阻塞、无死锁。
6. **资源回收**：`CoreAlgorithm` 关闭时 Sink `close()` 触发，JSONL `drain` & SQLite `commit` 完成。

---

## 7) Definition of Done（DoD）

* [x] **Contract 对齐**：FeatureRow 输入字段与 3.1 匹配；输出包含 `signal_type` / `guard_reason`
* [x] **去重与护栏**：`dedupe_ms`、warmup / lag / spread / consistency / weak-signal 守卫生效
* [x] **Sink 落地**：JSONL 路径 `ready/signal/{symbol}`，SQLite `signals.db` 列对齐并建主键
* [x] **CLI / Script**：`python -m mcp.signal_server.app` + `scripts/signal_demo.(sh|ps1)` 可直接运行
* [x] **单测覆盖**：`tests/test_core_algo.py`（5 个用例）通过；CI 入口 `python -m pytest tests/test_core_algo.py -v`
* [x] **文档同步**：README、`docs/api_contracts.md`、任务卡更新参数及命令示例

---

## 8) 常见坑与兼容性

* **分钟分片**：JSONL 以分钟粒度追加，历史数据需按文件名前缀回放
* **SQLite WAL**：首次写入自动启用 WAL + `synchronous=NORMAL`，Windows 上亦可并发读
* **去重窗口**：`dedupe_ms` 过大可能丢失行情；默认 250ms，按品种活跃度调优
* **阈值调参**：`signal.thresholds.*` 支持 per-regime 值；缺失时回退 `base`

---

## 9) 开发清单（最终交付）

1. `src/alpha_core/signals/core_algo.py` —— 轻量版 `CoreAlgorithm` + JSONL/SQLite/Null Sink
2. `mcp/signal_server/app.py` —— CLI 薄壳，支持 `--sink/--out/--print`
3. `scripts/signal_demo.sh` / `scripts/signal_demo.ps1`
4. `tests/test_core_algo.py` —— 5 个单测覆盖护栏、去重、Sink I/O
5. 文档与配置同步：`defaults.yaml`、README、`docs/api_contracts.md`、本任务卡

---

## 10) 验收脚本示例

```python
import json
from alpha_core.signals import CoreAlgorithm

algo = CoreAlgorithm(config={"sink": {"kind": "null"}})

with open("./runtime/features.jsonl", "r", encoding="utf-8") as fp:
    for line in fp:
        algo.process_feature_row(json.loads(line))

print(algo.stats)
```

> 若需查看落地效果，可将 `sink.kind` 切换为 `jsonl` 或 `sqlite`，并检查 `./runtime/ready/signal` / `./runtime/signals.db`。