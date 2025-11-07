# TASK-07 · Orchestrator 编排与端到端冒烟（优化版 V4.1）

> 里程碑：M2 · 依赖：TASK-03/05/06 · 最近更新：2025-11-07 (Asia/Tokyo)

---

## 0) 背景与目标

本任务负责实现 `orchestrator/run.py` 的编排与端到端冒烟（Smoke Test），串联 **HARVEST → FEATURES → SIGNAL → BROKER → REPORT** 的最小闭环，面向 **Cursor 一键运行**、**最小开发量**、**可观测/可回放**、**全局一致性**（Schema、路径、参数）。

**预期产物**：

* 可执行的 Orchestrator（支持命令行开关、模块选择、健康检查与优雅退出）。
* 30 分钟端到端烟测脚本/流程（JSONL 或 SQLite Sink）。
* 最小日报（信号条数/买卖分布/强信号占比/异常计数）。

---

## 1) 范围

### In Scope

* 启动/监管 MCP 薄壳：`mcp.harvest_server.app`、`mcp.signal_server.app`、`mcp.broker_gateway_server.app`（Mock）、`mcp.report_server.app`（简报）。
* 进程级健康检查：心跳、stderr 关键字、文件落地节律、内存/FD 粗监控。
* 抽象化 **Sink**（jsonl / sqlite），支持通过环境注入到 Signal Server。
* 生成最小日报（JSON + Markdown），并落地 `/logs/` 与 `/runtime/`。

### Out of Scope

* 真正的实盘下单与风控落地（本任务用 **Mock Broker**）。
* 回测与复盘（见 TASK-08/09）。

---

## 2) 前置与依赖

* **TASK-03**：Harvest MCP 薄壳可用（本地可运行）。
* **TASK-05**：Core Algo（信号）可用，支持 JSONL/SQLite Sink。
* **TASK-06**：StrategyMode 护栏生效（spread/lag/activity）。
* 已安装本仓库（`pip install -e .`）并具备 `config/defaults.yaml`。

---

## 3) 运行契约（CLI & 环境）

### 3.1 Orchestrator CLI（建议）

```bash
python -m orchestrator.run \
  --config ./config/defaults.yaml \
  --enable harvest,signal,broker,report \
  --sink jsonl \
  --minutes 30 \
  --symbols BTCUSDT,ETHUSDT \
  --debug
```

**参数约定**：

* `--enable`：逗号分隔，合法值 `{harvest,signal,broker,report}`；为空则仅做健康自检。
* `--sink`：`jsonl|sqlite`，传递给信号服务；
* `--minutes`：运行时长（Smoke 用）；
* `--symbols`：覆盖默认交易对（透传给 Harvester）；
* `--config`：主配置；
* `--debug`：打开详细日志。

### 3.2 环境变量透传（给 Signal Server）

* `V13_SINK={jsonl|sqlite}`
* `V13_OUTPUT_DIR=./runtime`
* （可选）`PAPER_ENABLE=1`（端到端演示时用于 Mock Broker 行为切换）

> 以上变量在 Orchestrator 中精准注入子进程环境，禁止全局污染；保持 **白名单式** 传参。

---

## 4) 编排设计

### 4.1 进程模型

* **Supervisor**：每个启用模块由 `ProcessSpec` 描述（命令、环境、就绪判据、健康探针、重启策略）。
* **启动顺序**：harvest → signal → broker → report；关闭顺序反向。
* **就绪判据**：

  * 日志关键字：`"成功导入所有核心组件"`/`"Server started"` 等；
  * 文件就绪：`./runtime/ready/signal/...` 出现（JSONL Sink）或 `./runtime/signals.db` 可打开（SQLite Sink）；
  * 时间上限：若 120 秒内未就绪，执行一次有界重启（最多 2 次）。

### 4.2 健康检查（每 10s）

* **Harvester**：最近 60 秒内 **raw/preview** 至少各落地 1 个文件；`artifacts/deadletter` 空；`queue_dropped` 无增长；
* **Signal**：`get_health()` 指标采集（队列长度、掉包计数）；分钟级 **.part→.jsonl** 轮转正常；
* **Broker**：Mock 订单流吞吐>0；
* **Report**：日报文件刷新。

### 4.3 日志与目录

* 遵循仓库的 `./data/`、`./preview/`、`./runtime/`、`./logs/` 约定；
* Orchestrator 自身日志：`./logs/orchestrator/orchestrator.log`；子进程各自 `stdout/stderr` 归档到 `./logs/<name>/`；
* 会话级 `run_manifest`（UTC 时间命名）放置 `./artifacts/run_logs/`。

---

## 5) 实现清单（Cursor 可执行）

### 5.1 `orchestrator/run.py`

* [ ] `argparse` 解析上述 CLI；
* [ ] `ProcessSpec` 数据类：`name, cmd, env, ready_probe, health_probe, restart_policy`；
* [ ] `Supervisor`：

  * `start_all()`：按顺序启动已启用模块；
  * `wait_ready()`：并行等待各模块就绪；
  * `tick_health()`：周期性健康探测（10s）；
  * `graceful_shutdown()`：SIGINT/SIGTERM 捕获，反向停止；
  * `bounded_restart()`：失败后指数退避（最多 2 次）；
* [ ] **Probe 实现**：

  * 文件就绪探针（路径通配 + 最短尺寸）；
  * JSONL 轮转探针（`spool/` → `ready/` 的新文件数增加）；
  * SQLite 连接探针（读 1 条）
* [ ] **日报器**：

  * 输入：`./runtime/ready/signal/**/*.jsonl` 或 `./runtime/signals.db`；
  * 统计：总信号数、BUY/SELL/STRONG_* 占比、近 5 分钟节律、`dropped` 计数；
  * 输出：`./logs/report/summary_{YYYYMMDD_HHMM}.json|md`。

### 5.2 子进程命令模板

* Harvest：`python -m mcp.harvest_server.app --config {cfg}`
* Signal（JSONL）：

  ```bash
  V13_SINK=jsonl V13_OUTPUT_DIR=./runtime \
  python -m mcp.signal_server.app --config {cfg}
  ```
* Signal（SQLite）：

  ```bash
  V13_SINK=sqlite V13_OUTPUT_DIR=./runtime \
  python -m mcp.signal_server.app --config {cfg}
  ```
* Broker（Mock）：`python -m mcp.broker_gateway_server.app --mock 1`
* Report（最小版）：`python -m mcp.report_server.app --tail ./runtime/ready/signal`（可选，或由 Orchestrator 内置实现）

> **兼容性**：Windows/WSL/Linux 全部使用 `python -m` 方式与显式环境注入；路径统一使用 `Path` 与 UTF-8。

---

## 6) 验收（Definition of Done）

**运行条件**：`--enable harvest,signal,broker,report --minutes 30`，`--sink` 分别对 `jsonl` 与 `sqlite` 各跑一轮。

**功能**

* [ ] 30 分钟端到端跑通，无未捕获异常；
* [ ] JSONL 模式：`./runtime/ready/signal/` 产生 ≥ 20 个 **.jsonl** 分片；
* [ ] SQLite 模式：`./runtime/signals.db` **signals** 表记录数 ≥ 10,000；
* [ ] Mock Broker 产生 ≥ 100 条模拟订单（买卖均有）；
* [ ] 生成日报（JSON + Markdown），字段包含：`total`, `buy_ratio`, `strong_ratio`, `per_minute`, `dropped`, `warnings`；

**一致性**

* [ ] 目录结构与字段命名与主文档一致；
* [ ] Orchestrator 仅白名单注入 `V13_SINK`, `V13_OUTPUT_DIR`, `PAPER_ENABLE`；
* [ ] Schema/契约：上游/下游字段与 `/docs/api_contracts.md` 对齐（抽检 100 条）。

**稳定性**

* [ ] Signal 队列 `dropped == 0`；
* [ ] JSONL 轮转每分钟至少 1 次（`spool/`→`ready/`）；
* [ ] 进程 RSS 峰值 < 600MB；打开文件数 < 256；
* [ ] Harvester `deadletter/` 目录为空；

**可观测性**

* [ ] `./artifacts/run_logs/run_manifest_*.json` 生成；
* [ ] `./logs/orchestrator/orchestrator.log` 包含 **Start/Ready/Health/Stop** 关键事件；
* [ ] 报表中展示最近 5 分钟信号节律与强信号占比（用于肉眼确认）。

---

## 7) 冒烟脚本（可选：`scripts/smoke_orchestrator.sh`）

```bash
#!/usr/bin/env bash
set -euo pipefail
CFG=${1:-./config/defaults.yaml}
# JSONL
python -m orchestrator.run --config "$CFG" --enable harvest,signal,broker,report --sink jsonl --minutes 30 --debug
# SQLite
python -m orchestrator.run --config "$CFG" --enable harvest,signal,broker,report --sink sqlite --minutes 30 --debug
```

---

## 8) 风险与回滚

* **就绪失败**：首次失败退避 10s，二次 30s，第三次标记为 `degraded` 并继续烟测（不中断其他模块）。
* **高跌落**：`dropped > 0` 或 JSONL 轮转停滞 → 打入告警并立即出日报，提前结束烟测。
* **磁盘压力**：检测 `runtime/` 分片过多（> 5,000）或单文件 > 200MB → 提前换日目录并继续。

---

## 9) 交付物

* `orchestrator/run.py`（含 Supervisor/Probe/Reporter）。
* `scripts/smoke_orchestrator.sh`（一键烟测）。
* `docs/orchestrator_smoke.md`（运行指南 + 故障排查）。
* 每次提交需附 **运行截图/日志片段** 与 **日报样例**。

---

## 10) 开发提示（Cursor）

* 先实现 **JSONL Sink** 路径与轮转探针，再做 SQLite；
* 在 Windows 下优先用 **唯一名兜底** 的轮转逻辑，避免 `PermissionError`；
* Mock Broker 简化为“每条强信号→模拟下单，普通信号按 1/5 抽样下单”，输出到 `./runtime/mock_orders.jsonl`；
* Reporter 计算 5 分钟滚动速率与强信号占比，生成 `summary_{ts}.json|md`；

---

## 11) 质量门禁（PR 勾选）

* [ ] CLI 帮助与示例命令；
* [ ] `--enable` 精确控制模块启动；
* [ ] JSONL/SQLite 两种 Sink 冒烟通过；
* [ ] 运行 30 分钟稳定；
* [ ] 日报字段齐全；
* [ ] 日志/目录/契约与主文档一致；
* [ ] 无未处理异常；
* [ ] 文档同步（README/Docs 链接）。
