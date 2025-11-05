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
- `/src/alpha_core/ingestion/harvester.py`（**HARVEST** 核心实现）  
- `/src/alpha_core/signals/core_algo.py`（**CORE_ALGO** 核心实现）  
- `/mcp/*/app.py`（各服务薄壳）  
- `/mcp/harvest_server/app.py`（**HARVEST** 薄壳）  
- `/mcp/signal_server/app.py`（**CORE_ALGO** 薄壳）  
- `/orchestrator/run.py`（主控循环）  
- `/config/defaults.yaml`（全局配置：OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE 等）  
- `/TASK_INDEX.md` & `tasks/*.md`（任务卡）  
- `/tools/bootstrap_github.py`（GitHub 初始化脚本）  

> 说明：本仓库遵循“**可复用库在 `src/`，对外接口用 MCP 薄壳，编排放 orchestrator**”的约定。

---

## 1) 目录结构（V4.1 · 已纳入 HARVEST / CORE_ALGO）
```text
repo/
├─ pyproject.toml
├─ README.md
├─ TASK_INDEX.md
├─ .gitignore
├─ .github/                                # GitHub 模板和配置
│  ├─ ISSUE_TEMPLATE/
│  │  ├─ epic.md
│  │  ├─ story.md
│  │  └─ config.yml
│  └─ PULL_REQUEST_TEMPLATE.md
│
├─ src/
│  └─ alpha_core/                         # 核心组件包（可安装）
│     ├─ __init__.py
│     ├─ microstructure/                  # 微结构（成熟组件）
│     │  ├─ ofi/
│     │  │  ├─ __init__.py
│     │  │  └─ real_ofi_calculator.py
│     │  ├─ cvd/
│     │  │  ├─ __init__.py
│     │  │  └─ real_cvd_calculator.py
│     │  ├─ fusion/
│     │  │  ├─ __init__.py
│     │  │  └─ ofi_cvd_fusion.py
│     │  └─ divergence/
│     │     ├─ __init__.py
│     │     └─ ofi_cvd_divergence.py
│     ├─ risk/
│     │  ├─ __init__.py
│     │  └─ strategy_mode.py              # StrategyModeManager
│     ├─ ingestion/                       # ★ 采集层库（HARVEST 成熟实现）
│     │  ├─ __init__.py
│     │  └─ harvester.py                  # HARVEST 采集接入（已实现：WS/重连/分片/落盘/DQ/OFI/CVD/Fusion）
│     └─ signals/                         # ★ 新增：信号层库（CORE_ALGO 实现）
│        ├─ __init__.py
│        └─ core_algo.py                  # CORE_ALGO 信号合成（输入 z_ofi/z_cvd/fusion/div）
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
│  ├─ architecture_flow.md                # 架构流程图（Mermaid）
│  ├─ order_state_machine.md              # 订单状态机（Mermaid）
│  └─ api_contracts.md                    # MCP 接口契约与示例
│
├─ tasks/                                 # 任务卡目录（共 10 个任务）
│  ├─ TASK-01 - 统一 Row Schema & 出站 DQ Gate（Data Contract）.md
│  ├─ TASK-02 - Harvester WS Adapter（Binance Futures）.md
│  ├─ TASK-03 - Harvest MCP 薄壳与本地运行脚本.md
│  ├─ TASK-04 - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）.md
│  ├─ TASK-05 - CORE_ALGO 信号服务（Sink－JSONL 或 SQLite）.md
│  ├─ TASK-06 - StrategyMode ＆ 风控护栏（spread／lag／activity 等）.md
│  ├─ TASK-07 - Orchestrator 编排与端到端冒烟.md
│  ├─ TASK-08 - 回放＋回测 Harness（JSONL 或 Parquet → 信号 → PnL）.md
│  ├─ TASK-09 - 复盘报表（时段胜率、盈亏比、滑点、费用）.md
│  └─ TASK-10 - 文档与契约同步（／docs 与 README 链接校验）.md
│
├─ scripts/
│  ├─ dev_run.sh                          # 开发环境启动脚本
│  ├─ harvest_local.sh                    # ★ 新增：单机Harvester启动脚本
│  └─ run_success_harvest.py              # HARVEST 运行脚本（历史，核心逻辑已迁移至 harvester.py）
│
├─ tools/                                 # 工具脚本
│  ├─ bootstrap_github.py                 # GitHub 初始化脚本（创建标签/里程碑/Epic）
│  └─ github_seed/
│     ├─ labels.json                      # GitHub 标签定义
│     ├─ milestones.json                  # GitHub 里程碑定义
│     └─ epics.json                       # GitHub Epic 定义（V4.1 10个Epic）
│
└─ logs/                                  # 日志目录（运行时生成）
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
# Linux/macOS:
bash scripts/harvest_local.sh

# Windows PowerShell:
.\scripts\harvest_local.ps1

# 或手动命令（Linux/macOS）:
python -m mcp.harvest_server.app \
  --config ./config/defaults.yaml \
  --output ./deploy/data/ofi_cvd \
  --format parquet \
  --rotate.max_rows 200000 --rotate.max_sec 60

# Windows PowerShell (单行):
python -m mcp.harvest_server.app --config ./config/defaults.yaml --output ./deploy/data/ofi_cvd --format parquet --rotate.max_rows 200000 --rotate.max_sec 60

# Windows PowerShell (使用反引号续行):
python -m mcp.harvest_server.app `
  --config ./config/defaults.yaml `
  --output ./deploy/data/ofi_cvd `
  --format parquet `
  --rotate.max_rows 200000 `
  --rotate.max_sec 60
```

**M2 · 启动 CORE_ALGO（信号层）**
```bash
# 信号服务：直接运行 core_algo 模块
python -m alpha_core.signals.core_algo --input data/*.parquet --out out/signals.jsonl

# 或通过 MCP 服务（JSONL Sink）
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

### 任务列表（共 10 个任务）

**M1 · 数据打通**：
- **TASK-01** - 统一 Row Schema & 出站 DQ Gate（Data Contract）
- **TASK-02** - Harvester WS Adapter（Binance Futures）
- **TASK-03** - Harvest MCP 薄壳与本地运行脚本
- **TASK-04** - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）

**M2 · 信号与风控**：
- **TASK-05** - CORE_ALGO 信号服务（Sink: JSONL/SQLite）
- **TASK-06** - StrategyMode & 风控护栏（spread/lag/activity 等）
- **TASK-07** - Orchestrator 编排与端到端冒烟

**M3 · 编排、回测与复盘**：
- **TASK-08** - 回放/回测 Harness（JSONL/Parquet → 信号 → PnL）
- **TASK-09** - 复盘报表（时段胜率、盈亏比、滑点、费用）
- **TASK-10** - 文档与契约同步（/docs 与 README 链接校验）

详见 `/TASK_INDEX.md` 和 `/tasks/` 目录下的完整任务卡文件

---

## 7) 开发节奏与约定
- **库与服务分层**：算法逻辑尽量沉淀在 `src/alpha_core/*`；MCP 只做 I/O 薄壳；`orchestrator` 负责跨服务编排。  
- **数据可复用**：采集层产物（jsonl/parquet）同时服务“在线特征/离线回测/复盘”。  
- **统一 Schema**：上下游 JSON 字段命名保持稳定，版本升级在 `docs/api_contracts.md` 明示。  
- **最小化依赖**：优先使用标准库 + 轻量三方，便于部署与调试。  

---

## 8) 常见问题（FAQ）

### PyYAML 未安装
如果未安装 PyYAML，采集器会使用空配置并继续运行（会使用默认的 6 个交易对）。建议安装 PyYAML 以获得完整的配置支持：

```bash
pip install pyyaml
```

或者安装所有依赖：

```bash
pip install -e .
```

### 配置文件路径问题
如果遇到配置文件加载错误，请确保：
- 配置文件路径正确（默认：`./config/defaults.yaml`）
- 使用 `--config` 参数指定正确的配置文件路径
- 配置文件格式为有效的 YAML

### 输出目录路径问题
如果输出目录路径不正确（例如出现 `deploy/deploy/...`），请确保：
- 使用相对路径时，不要包含 `./deploy/` 前缀（薄壳会自动处理）
- 例如：使用 `--output ./deploy/data/ofi_cvd` 会被转换为 `data/ofi_cvd`
- 或者直接使用绝对路径

### Windows PowerShell 执行策略
如果 PowerShell 脚本无法执行，可能需要调整执行策略：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

或者直接使用 Python 命令：

```powershell
python -m mcp.harvest_server.app --config ./config/defaults.yaml
```

### 端口或网络连接问题
- 确保能够访问 Binance Futures WebSocket API
- 检查防火墙设置
- 如果在中国大陆，可能需要使用代理

### 其他常见问题
- **深夜无量导致 OFI/CVD 异常？**：开启 `risk.gates.require_activity`，低活跃时仅观测不下单。  
- **K 线整点更新的滞后干扰？**：信号层以"逐笔/订单簿微结构"为主，避免依赖整点 K。  
- **跨平台路径不一致？**：统一使用规范化路径与稳定 JSON dump（详见修复记录）。  

---

## 9) 许可证与贡献
- 内部项目默认私有；如需开源，建议采用 Apache-2.0 并在 `NOTICE` 中标注外部依赖。  
- 提交 PR 前请同步更新：`README`、`docs/api_contracts.md`、相关任务卡。

—— END ——
