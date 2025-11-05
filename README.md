# OFI+CVD 交易系统 · 主开发文档（Cursor 友好版 · V4.1）
> 更新日期：2025-11-05 (Asia/Tokyo)

本版（V4.1）在 V4 基础上进行**增量更新**：
- **HARVEST**：实时行情/成交/订单簿采集与落库（统一 Row Schema + 分片轮转 + 出站 DQ 闸门）。
- **CORE_ALGO**：信号层核心算法服务（直接调用成熟组件 OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE，带可插拔 Sink：JSONL/SQLite）。
- 同步更新**目录结构、架构图、API 契约、快速起步、任务卡**，保持与既有 **src layout + MCP 薄壳 + orchestrator 编排** 一致。

---

## 0) 快速导航（建议固定在 Cursor 侧边）
- `/README.md`（本文）  
- `/docs/architecture_flow.md`（架构/业务流 · Mermaid）  
- `/docs/order_state_machine.md`（订单状态机 · Mermaid）  
- `/docs/api_contracts.md`（MCP 接口契约与示例）  
- `/mcp/*/app.py`（各服务薄壳）  
- `/mcp/harvest_server/app.py`（**新增：HARVEST** 薄壳）  
- `/mcp/signal_server/app.py`（**新增：CORE_ALGO** 薄壳）  
- `/orchestrator/run.py`（主控循环）  
- `/config/defaults.yaml`（全局配置：OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE 等）  
- `/TASK_INDEX.md` & `tasks/*.md`（任务卡）  

> 说明：本仓库遵循“**可复用库在 `src/`，对外接口用 MCP 薄壳，编排放 orchestrator**”的约定。

---

## 1) 目录结构（V4.1 · 已纳入 HARVEST / CORE_ALGO）
```text
repo/
├─ pyproject.toml
├─ README.md
├─ TASK_INDEX.md
├─ .gitignore
│
├─ src/
│  └─ alpha_core/                         # 核心组件包（可安装）
│     ├─ __init__.py
│     ├─ microstructure/                  # 微结构（成熟组件）
│     │  ├─ ofi/real_ofi_calculator.py
│     │  ├─ cvd/real_cvd_calculator.py
│     │  ├─ fusion/ofi_cvd_fusion.py
│     │  └─ divergence/ofi_cvd_divergence.py
│     ├─ risk/strategy_mode.py            # StrategyModeManager
│     ├─ ingestion/                       # ★ 新增：采集层库（HARVEST 可复用实现）
│     │  └─ harvester.py                  # WS接入→统一Row→分片→DQ
│     └─ signals/                         # ★ 新增：信号层库（CORE_ALGO 实现）
│        └─ core_algo.py                  # 统一信号API，Sink: JSONL/SQLite
│
├─ mcp/                                   # MCP 服务器（薄壳层）
│  ├─ data_feed_server/app.py             # 复用 ingestion.harvester
│  ├─ ofi_feature_server/app.py
│  ├─ ofi_risk_server/app.py
│  ├─ broker_gateway_server/app.py
│  ├─ report_server/app.py
│  ├─ harvest_server/app.py               # ★ 新增：HARVEST 薄壳
│  └─ signal_server/app.py                # ★ 新增：CORE_ALGO 薄壳
│
├─ orchestrator/
│  └─ run.py                              # 主控循环（编排 MCP 调用）
│
├─ config/
│  ├─ defaults.yaml                       # 默认配置（策略、采集、风控、执行等）
│  └─ overrides.d/                        # 环境覆盖
│
├─ docs/
│  ├─ architecture_flow.md
│  ├─ order_state_machine.md
│  └─ api_contracts.md
│
├─ tasks/
│  ├─ TASK-01 - Data MCP：统一 Row Schema + 出站 DQ Gate（V4）.md
│  ├─ TASK-02 - Data MCP：接入真实 WS／Harvester（实时）.md
│  ├─ TASK-03 - Harvest：WS→统一Row→DQ→落地（jsonl/parquet）.md
│  ├─ TASK-04 - Signal：CORE_ALGO 服务化（Sink: jsonl/sqlite）.md
│  ├─ TASK-05 - Docs：补齐 HARVEST/CORE_ALGO 契约示例.md
│  └─ TASK-06 - Orchestrator：编排与烟囱测试（M1→M3）.md
│
└─ scripts/
   ├─ dev_run.sh
   └─ harvest_local.sh                    # ★ 新增：单机Harvester启动脚本（可选）
```

---

## 2) 总体架构 · 业务流（Mermaid · 含 HARVEST / CORE_ALGO）
```mermaid
flowchart LR
  subgraph Ingestion[HARVEST（采集层）]
    H1[WS: Binance Futures\ntrades/aggTrade/bookTicker/depth@100ms]
    H2[Row Schema 统一\n(ts_ms,symbol,src,...) + DQ]
    H3[分片落地：/data/date=.../symbol=...\n(jsonl/parquet)]
  end

  subgraph Alpha[特征层（alpha_core.microstructure）]
    O[OFI] --> F[FUSION]
    C[CVD] --> F
    D[DIV] --> CA
  end

  subgraph Signal[CORE_ALGO 信号层]
    F --> CA[CoreAlgo\n融合+一致性+背离+护栏\nSink: JSONL/SQLite]
    D --> CA
    SM[StrategyMode] --> CA
  end

  subgraph RiskExec[风控与执行]
    CA --> R[Risk Gates\nspread,lag,missing,\nscenario,hold]
    R --> GW[Broker Gateway MCP]
    GW --> EX[Exchange]
  end

  H1 --> H2 --> H3 --> O
  H3 --> C
  H3 --> D
  SM -. 市场/时间窗触发 .-> CA
```

---

## 3) API 契约（摘要 · 详细见 `/docs/api_contracts.md`）

### 3.1 HARVEST → 特征层（统一 Row Schema）
```json
{
  "ts_ms": 1730790000123,
  "symbol": "BTCUSDT",
  "src": "aggTrade|bookTicker|depth",
  "price": 70321.5,
  "qty": 0.01,
  "side": "buy|sell|null",        // 可空：tick rule 回退
  "bid": 70321.4,
  "ask": 70321.6,
  "best_spread_bps": 1.4,
  "meta": { "latency_ms": 12, "recv_ts_ms": 1730790000125 }
}
```

### 3.2 特征层 → CORE_ALGO（输入）
```json
{
  "ts_ms": 1730790000456,
  "symbol": "BTCUSDT",
  "z_ofi": 1.8,
  "z_cvd": 0.9,
  "price": 70325.1,
  "lag_sec": 0.04,
  "spread_bps": 1.2,
  "activity": { "tps": 2.3 }
}
```

### 3.3 CORE_ALGO → 风控/执行（信号输出）
```json
{
  "ts_ms": 1730790000123,
  "symbol": "BTCUSDT",
  "score": 1.72,
  "z_ofi": 1.9,
  "z_cvd": 1.3,
  "regime": "active",
  "div_type": null,
  "confirm": true,
  "gating": false
}
```

> 统一以 **JSON Lines**（一行一条）落地，便于回放与离线分析。

---

## 4) 配置关键项（示例片段：`/config/defaults.yaml`）
```yaml
market:
  symbols: ["BTCUSDT"]
  exchange: "binance-futures"

harvest:
  ws:
    urls:
      - "wss://fstream.binance.com/stream"
    topics:
      - "aggTrade"
      - "bookTicker"
      - "depth@100ms"
  rotate:
    max_rows: 200000
    max_sec: 60
  dq:
    stale_ms: 1500
    require_fields: ["ts_ms","symbol","price"]
  output:
    format: "parquet"        # jsonl|parquet
    base_dir: "./data/ofi_cvd"

features:
  ofi:
    window_ms: 5000
    zscore_window: 30000
  cvd:
    window_ms: 60000
  fusion:
    method: "zsum"           # zsum|weighted
  divergence:
    lookback_bars: 60

signal:
  sink: "jsonl"              # jsonl|sqlite
  output_dir: "./runtime"
  replay_mode: 0
  debug: true

risk:
  gates:
    max_spread_bps: 2.5
    max_lag_sec: 0.5
    require_activity: true
```

---

## 5) 最小可跑（M1 → M2 → M3）

> 在仓库根执行：

**M1 · 安装与本地采集**
```bash
# 1) 安装为可编辑包
pip install -e .

# 2) 启动 HARVEST（本地）
python -m mcp.harvest_server.app \
  --config ./config/defaults.yaml \
  --output ./data \
  --format parquet \
  --rotate.max_rows 200000 --rotate.max_sec 60
```

**M2 · 启动 CORE_ALGO（信号层）**
```bash
# JSONL Sink（默认）
V13_SINK=jsonl V13_OUTPUT_DIR=./runtime \
python -m mcp.signal_server.app --config ./config/defaults.yaml

# 或使用 SQLite Sink（便于并发读）
V13_SINK=sqlite V13_OUTPUT_DIR=./runtime \
python -m mcp.signal_server.app --config ./config/defaults.yaml
```

**M3 · 主控编排（Orchestrator）**
```bash
python -m orchestrator.run \
  --config ./config/defaults.yaml \
  --enable harvest,signal,broker,report
```

---

## 6) 任务卡（与 `TASK_INDEX.md` 对齐）

### V4.1 新增任务
- **TASK-03** - Harvest：WS统一RowDQ落地（jsonl parquet） · M1 · harvest
- **TASK-04** - Signal：CORE_ALGO 服务化（Sink jsonl sqlite） · M1 · signal
- **TASK-05** - Docs：补齐 HARVEST CORE_ALGO 契约示例 · M1 · docs
- **TASK-06** - Orchestrator：编排与烟囱测试（M1→M3） · M1 · orchestrator

### 原有任务（V4）
详见 `/TASK_INDEX.md` 和 `/tasks/` 目录下的完整任务列表（共 18 个任务）

---

## 7) 开发节奏与约定
- **库与服务分层**：算法逻辑尽量沉淀在 `src/alpha_core/*`；MCP 只做 I/O 薄壳；`orchestrator` 负责跨服务编排。  
- **数据可复用**：采集层产物（jsonl/parquet）同时服务“在线特征/离线回测/复盘”。  
- **统一 Schema**：上下游 JSON 字段命名保持稳定，版本升级在 `docs/api_contracts.md` 明示。  
- **最小化依赖**：优先使用标准库 + 轻量三方，便于部署与调试。  

---

## 8) 常见问题（FAQ）
- **深夜无量导致 OFI/CVD 异常？**：开启 `risk.gates.require_activity`，低活跃时仅观测不下单。  
- **K 线整点更新的滞后干扰？**：信号层以“逐笔/订单簿微结构”为主，避免依赖整点 K。  
- **跨平台路径不一致？**：统一使用规范化路径与稳定 JSON dump（详见修复记录）。  

---

## 9) 许可证与贡献
- 内部项目默认私有；如需开源，建议采用 Apache-2.0 并在 `NOTICE` 中标注外部依赖。  
- 提交 PR 前请同步更新：`README`、`docs/api_contracts.md`、相关任务卡。

—— END ——
