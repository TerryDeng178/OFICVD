# OFI+CVD 交易系统 · 主开发文档（Cursor 友好版 · V4.1）
> 更新日期：2025-11-08 (Asia/Tokyo)  
> 最后同步：TASK-07 已签收（Orchestrator 编排与端到端冒烟完成，功能验证完成度 83%）

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
- `/src/alpha_core/microstructure/feature_pipe.py`（**FeaturePipe** 特征计算接线）  
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
│     │  ├─ divergence/
│     │  │  ├─ __init__.py
│     │  │  └─ ofi_cvd_divergence.py
│     │  └─ feature_pipe.py              # ★ FeaturePipe：特征计算接线（OFI+CVD+FUSION+DIVERGENCE）
│     ├─ risk/
│     │  ├─ __init__.py
│     │  └─ strategy_mode.py              # ★ StrategyModeManager（已集成，TASK-06）
│     ├─ ingestion/                       # ★ 采集层库（HARVEST 成熟实现）
│     │  ├─ __init__.py
│     │  └─ harvester.py                  # HARVEST 采集接入（已实现：WS/重连/分片/落盘/DQ/OFI/CVD/Fusion）
│     └─ signals/                         # ★ 信号层库（CORE_ALGO 实现）
│        ├─ __init__.py
│        └─ core_algo.py                  # ★ CORE_ALGO 信号合成（已集成 StrategyMode，TASK-06）
│
├─ mcp/                                   # MCP 服务器（薄壳层，精简为5个核心服务）
│  ├─ harvest_server/app.py               # ★ HARVEST：采集/对齐/落盘（Raw+Preview/宽表）
│  ├─ signal_server/app.py                # ★ SIGNAL：信号生成（CoreAlgo薄壳）
│  ├─ strategy_server/                    # ★ STRATEGY：策略执行（含风控模块）
│  │  ├─ app.py
│  │  └─ risk/                            # 风控模块（合并ofi_risk_server逻辑）
│  ├─ broker_gateway_server/app.py        # ★ BROKER：交易所网关（Testnet/Live）
│  └─ report_server/app.py                # ★ REPORT：报表生成
│
├─ legacy/                                 # 已下线服务（只读，不进入部署链路）
│  └─ mcp/
│     ├─ data_feed_server/                 # 功能由harvest_server覆盖
│     ├─ ofi_feature_server/               # 特征计算在库层，由signal_server调用
│     └─ ofi_risk_server/                  # 逻辑已合并到strategy_server/risk/
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
│  └─ api_contracts.md                    # MCP 接口契约与示例（包含 FeaturePipe 输入输出契约）
│
├─ tasks/                                 # 任务卡目录（共 10 个任务）
│  ├─ TASK-01 - 统一 Row Schema & 出站 DQ Gate（Data Contract）.md
│  ├─ TASK-02 - Harvester WS Adapter（Binance Futures）.md
│  ├─ TASK-03 - Harvest MCP 薄壳与本地运行脚本.md
│  ├─ TASK-04 - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）.md
│  ├─ TASK-05 - CORE_ALGO 信号服务（Sink－JSONL 或 SQLite）.md
│  ├─ TASK-06 - StrategyMode ＆ 风控护栏（spread／lag／activity 等）.md
│  ├─ TASK-07 - Orchestrator 编排与端到端冒烟.md
│  ├─ TASK-07A - LIVE 60分钟端到端实测（Soak Test）.md
│  ├─ TASK-07B - 双Sink等价性收敛.md
│  ├─ TASK-08 - 回放＋回测 Harness（JSONL 或 Parquet → 信号 → PnL）.md
│  ├─ TASK-09 - 复盘报表（时段胜率、盈亏比、滑点、费用）.md
│  └─ TASK-10 - 文档与契约同步（／docs 与 README 链接校验）.md
│
├─ scripts/
│  ├─ dev_run.sh                          # 开发环境启动脚本
│  ├─ harvest_local.sh                    # ★ 新增：单机Harvester启动脚本（Bash）
│  ├─ harvest_local.ps1                   # ★ 新增：单机Harvester启动脚本（Windows）
│  ├─ feature_demo.sh                     # ★ 新增：FeaturePipe 演示脚本（Bash）
│  ├─ feature_demo.ps1                    # ★ 新增：FeaturePipe 演示脚本（Windows）
│  ├─ signal_demo.sh                      # ★ 新增：CORE_ALGO 演示脚本（Bash）
│  ├─ signal_demo.ps1                     # ★ 新增：CORE_ALGO 演示脚本（Windows）
│  ├─ performance_test.sh                 # ★ 新增：性能测试脚本（Bash）
│  ├─ performance_test.ps1                # ★ 新增：性能测试脚本（Windows）
│  ├─ m2_smoke_test.sh                    # ★ 新增：M2 冒烟测试脚本（Bash）
│  ├─ m2_smoke_test.ps1                   # ★ 新增：M2 冒烟测试脚本（Windows）
│  └─ run_success_harvest.py              # HARVEST 运行脚本（历史，核心逻辑已迁移至 harvester.py）
│
├─ tools/                                 # 工具脚本
│  ├─ bootstrap_github.py                 # GitHub 初始化脚本（创建标签/里程碑/Epic）
│  └─ github_seed/
│     ├─ labels.json                      # GitHub 标签定义
│     ├─ milestones.json                  # GitHub 里程碑定义
│     └─ epics.json                       # GitHub Epic 定义（V4.1 10个Epic）
│
├─ tests/                                 # 测试目录
│  ├─ conftest.py                         # pytest 配置（路径设置）
│  └─ test_feature_pipe.py                # ★ 新增：FeaturePipe 单元测试（7 个用例）
├─ TASK-04-评估报告-签收清单.md          # ★ 新增：TASK-04 签收清单（完整证据链）
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
  "bids": [[70321.4, 10.5], [70321.3, 8.2], ...],  // 必须高→低排序
  "asks": [[70321.6, 11.2], [70321.7, 9.5], ...],  // 必须低→高排序
  "meta": { "latency_ms": 12, "recv_ts_ms": 1730790000125 }
}
```

**排序约定**: bids 必须按价格从高到低，asks 必须按价格从低到高（如输入未保证顺序，实现侧会先排序）。

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
  "fusion_score": 0.73,
  "consistency": 0.42,
  "dispersion": 0.9,
  "sign_agree": 1,
  "div_type": null,
  "activity": { "tps": 2.3 },
  "warmup": false,
  "signal": "neutral"
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
  "gating": false,
  "signal_type": "strong_buy",
  "guard_reason": null
}
```

> **重要约定（DoD）**: 信号→订单链路的一致口径
> - **Reporter 统计**: 仅统计 `confirm=true` 的信号（`total`, `buy_count`, `sell_count`, `strong_ratio` 等）
> - **Broker 下单**: 仅处理 `confirm=true` 的信号（强信号必下单，普通信号按 `sample_rate` 抽样）
> - **统计口径一致性**: JSONL 和 SQLite 两种 Sink 的统计口径完全一致，确保可对比性
> - 统一以 **JSON Lines**（一行一条）落地，便于回放与离线分析。

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
    levels: 5
    weights: [0.4, 0.25, 0.2, 0.1, 0.05]
    ema_alpha: 0.2
  cvd:
    window_ms: 60000
    z_mode: "delta"          # delta|level
  fusion:
    method: "zsum"           # zsum|weighted (预留字段，当前实现未使用)
    w_ofi: 0.6
    w_cvd: 0.4
  divergence:
    lookback_bars: 60
sink:
  kind: jsonl               # jsonl|sqlite
  output_dir: ./runtime

signal:
  dedupe_ms: 250
  weak_signal_threshold: 0.2
  consistency_min: 0.15
  spread_bps_cap: 20.0
  lag_cap_sec: 3.0
  weights:
    w_ofi: 0.6
    w_cvd: 0.4
  activity:
    active_min_tps: 3.0
    normal_min_tps: 1.0
  thresholds:
    base:
      buy: 0.6
      strong_buy: 1.2
      sell: -0.6
      strong_sell: -1.2
    active:
      buy: 0.5
      strong_buy: 1.0
      sell: -0.5
      strong_sell: -1.0
    quiet:
      buy: 0.7
      strong_buy: 1.4
      sell: -0.7
      strong_sell: -1.4
  sink:
    kind: jsonl               # jsonl|sqlite|null
    output_dir: ./runtime
  replay_mode: 0
  debug: true

strategy_mode:                # ★ StrategyMode 配置（TASK-06）
  mode: auto                  # auto | force_active | force_quiet
  hysteresis:
    window_secs: 60
    min_active_windows: 2
    min_quiet_windows: 4
  triggers:
    combine_logic: OR         # OR | AND
    schedule:
      enabled: true           # 默认开启（空窗口=全天有效）
      timezone: "UTC"
      enabled_weekdays: []    # 空数组=所有星期启用
      active_windows: []      # 空数组=全天有效
      wrap_midnight: true
    market:
      enabled: true
      window_secs: 60
      basic_gate_multiplier: 0.5
      min_trades_per_min: 30
      min_quote_updates_per_sec: 5
      max_spread_bps: 15
      min_volatility_bps: 0.5
      min_volume_usd: 10000
      use_median: true
      winsorize_percentile: 95

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

**M2 · 特征计算与信号生成**

```bash
# 步骤 1: 运行 FeaturePipe 生成特征（从 HARVEST 数据生成特征）
# Windows PowerShell:
python -m alpha_core.microstructure.feature_pipe `
  --input ./deploy/data/ofi_cvd `
  --sink jsonl `
  --out ./runtime/features.jsonl `
  --symbols BTCUSDT ETHUSDT `
  --config ./config/defaults.yaml

# 或使用脚本:
.\scripts\feature_demo.ps1

# Linux/macOS:
python -m alpha_core.microstructure.feature_pipe \
  --input ./deploy/data/ofi_cvd \
  --sink jsonl \
  --out ./runtime/features.jsonl \
  --symbols BTCUSDT ETHUSDT \
  --config ./config/defaults.yaml

# 或使用脚本:
bash scripts/feature_demo.sh

# 性能测试（可选）:
# Windows PowerShell:
.\scripts\performance_test.ps1

# Linux/macOS:
bash scripts/performance_test.sh

# 步骤 2: 运行 CORE_ALGO 生成信号（从特征生成交易信号）
# Windows PowerShell:
python -m mcp.signal_server.app `
  --config ./config/defaults.yaml `
  --input ./runtime/features.jsonl `
  --sink jsonl `
  --out ./runtime `
  --print

# 或使用脚本:
.\scripts\signal_demo.ps1 -Print

# Linux/macOS:
python -m mcp.signal_server.app \
  --config ./config/defaults.yaml \
  --input ./runtime/features.jsonl \
  --sink jsonl \
  --out ./runtime \
  --print

# 或使用脚本:
bash scripts/signal_demo.sh

# 切换 SQLite Sink（便于并发读写）:
python -m mcp.signal_server.app \
  --config ./config/defaults.yaml \
  --input ./runtime/features.jsonl \
  --sink sqlite \
  --out ./runtime
```

**FeaturePipe 说明**:
- **输入**: HARVEST 层输出的统一 Row（支持 Parquet/JSONL 文件或标准输入）
- **输出**: FeatureRow（包含 z_ofi, z_cvd, fusion_score, signal 等）
- **性能**: 实际测试 14,524 rows/s，CPU 38.54%（远超要求）
- **Sink**: 支持 JSONL（默认）和 SQLite 两种格式
- **排序约定**: bids 高→低，asks 低→高（实现侧自动排序）
- **稳定输出**: JSON 序列化使用稳定排序（sort_keys=True），支持回放可复现

**CORE_ALGO 说明**:
- **入口**: `python -m mcp.signal_server.app` 或 `scripts/signal_demo.(sh|ps1)`
- **输入**: FeaturePipe JSONL（支持 `--input` 目录/文件/标准输入）
- **输出**: JSONL 分片或 SQLite `signals.db`
- **阈值**: 由 `signal.thresholds` 驱动，支持 active/quiet 差异化
- **StrategyMode**: 集成 StrategyModeManager，支持 schedule + market 触发器，OR/AND 逻辑
- **统计**: 运行结束打印 processed/emitted/suppressed/deduped/warmup_blocked
- **心跳日志**: 每 10s 输出 JSON 格式快照（包含 `schedule_active`/`market_active`/`mode`）

**M3 · 主控编排（Orchestrator）**
```bash
# 基本用法（Windows PowerShell，5个核心服务）:
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,strategy,broker,report `
  --sink jsonl `
  --minutes 3

# 双 Sink 模式（同时写入 JSONL 和 SQLite）:
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,strategy,broker,report `
  --sink dual `
  --minutes 3

# SQLite 模式:
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,strategy,broker,report `
  --sink sqlite `
  --minutes 3

# Linux/macOS:
python -m orchestrator.run \
  --config ./config/defaults.yaml \
  --enable harvest,signal,strategy,broker,report \
  --sink jsonl \
  --minutes 3
```

**Orchestrator 说明**:
- **功能**: 统一编排 HARVEST → SIGNAL → STRATEGY(含Risk) → BROKER → REPORT 流程（5个核心服务）
- **Sink 支持**: `jsonl`、`sqlite`、`dual`（双 Sink 并行写入）
- **健康检查**: 每 10 秒检查一次，支持 LIVE/replay 模式区分
- **优雅重启**: 支持故障注入测试，进程被 kill 后自动重启（12 秒内）
- **日报生成**: 自动生成 JSON + Markdown 格式日报，包含 Runtime State、事件→信号联动、告警信息
- **详细文档**: `reports/v4.0.6-总体执行报告.md`

---

## 6) 任务卡（与 `TASK_INDEX.md` 对齐）

### 任务列表（共 10 个任务）

**M1 · 数据打通**：
- ✅ **TASK-01** - 统一 Row Schema & 出站 DQ Gate（Data Contract）
- ✅ **TASK-02** - Harvester WS Adapter（Binance Futures）
- ✅ **TASK-03** - Harvest MCP 薄壳与本地运行脚本
- ✅ **TASK-04** - 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）**（已签收）**

**M2 · 信号与风控**：
- ✅ **TASK-05** - CORE_ALGO 信号服务（Sink: JSONL/SQLite）
- ✅ **TASK-06** - StrategyMode & 风控护栏（spread/lag/activity 等）**（已签收，2025-11-07）**
- ✅ **TASK-07** - Orchestrator 编排与端到端冒烟**（已签收，2025-11-08）**

**M3 · 编排、回测与复盘**：
- **TASK-07A** - LIVE 60 分钟端到端实测（Soak Test）
- **TASK-07B** - 双 Sink 等价性收敛（目标 < 0.2%）
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

### FeaturePipe 相关
- **特征生成为 0？**：FeaturePipe 需要同时具备订单簿和成交数据才能生成特征。如果测试数据只包含其中一种类型，则不会生成特征。这是设计预期。
- **性能测试说明**：性能测试脚本位于 `scripts/performance_test.ps1`（Windows）和 `scripts/performance_test.sh`（Linux/macOS）。实际测试结果：14,524 rows/s，CPU 38.54%（远超要求）。
- **SQLite schema 问题？**：如果遇到 SQLite 表缺少 `signal` 字段，FeaturePipe 会自动执行 `ALTER TABLE` 添加该字段（向后兼容）。

### StrategyMode 相关（TASK-06）
- **100% Quiet 问题**：已修复。根因是 Schedule 默认关闭 + `enabled_weekdays: []` 语义缺陷。修复后 Active 占比从 0% 提升到 99.998%（smoke 配置）。
- **Active 占比过高（99%）**：这是 smoke 配置的预期结果（`schedule.active_windows: []` = 全天有效 + OR 逻辑）。生产环境需切换配置（见 `config/defaults.staging.yaml` 或报告中的生产配置方案）。
- **性能下降**：引入 StrategyMode 后，吞吐量从 ~3,030 rows/sec 降到 ~837 rows/sec（-72%），但仍在可接受范围（1.2ms/row）。这是功能增强的正常代价。
- **配置说明**：
  - **Smoke**：`combine_logic: OR` + 全天有效，用于 CI/E2E 验证
  - **Staging**：`combine_logic: AND` + 工作日核心时段，用于预生产验证
  - **Prod**：建议采用方案 1（仅 Market 触发）或方案 3（AND 逻辑）
- **详细文档**：`reports/P0-StrategyMode-100-Quiet-修复验证报告.md`

### 其他常见问题
- **深夜无量导致 OFI/CVD 异常？**：开启 `risk.gates.require_activity`，低活跃时仅观测不下单。  
- **K 线整点更新的滞后干扰？**：信号层以"逐笔/订单簿微结构"为主，避免依赖整点 K。  
- **跨平台路径不一致？**：统一使用规范化路径与稳定 JSON dump（详见修复记录）。  

---

## 9) 许可证与贡献
- 内部项目默认私有；如需开源，建议采用 Apache-2.0 并在 `NOTICE` 中标注外部依赖。  
- 提交 PR 前请同步更新：`README`、`docs/api_contracts.md`、相关任务卡。

—— END ——
