---
id: "TASK-C1"
title: "Orchestrator 集成与健康探针"
stage: "C"
priority: "P0"
status: "Planned"
owners: "TBD"
deps: ["TASK-A1", "TASK-B1", "TASK-B2", "TASK-B3"]
estimate: "~1.5d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

Orchestrator 集成：`build_strategy_spec()` + 健康/就绪探针，一键拉起主链。

## 依赖

- TASK-A1，TASK-B1~B3

## 主要步骤

1. 提供 `build_strategy_spec()`，统一构建 `harvester/signal/strategy/broker/report` 进程编排。
2. 健康探针：
   - `signal`：`ready(file_exists)`；`health(log_keyword)`。
   - `strategy`：`health(file_count, lag_ms)`。
   - `broker/report`：最小心跳探针。
3. 提供示例 `configs/strategy_spec.yaml` 与本地启动脚本。

## 交付物

- Orchestrator 代码与样例配置

## DoD

- [ ] 一键启动后，五服务健康/就绪全部绿灯
- [ ] 停止任一服务，探针能在 60s 内识别为红
