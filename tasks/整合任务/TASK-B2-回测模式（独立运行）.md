---
id: "TASK-B2"
title: "回测模式（独立运行）"
stage: "B"
priority: "P0"
status: "Planned"
owners: "TBD"
deps: ["TASK-A2", "TASK-A5"]
estimate: "~1.5d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

回测模式（独立运行），复用 replay_harness，单机可跑。

## 依赖

- TASK-A2, TASK-A5

## 主要步骤

1. BacktestAdapter 从 features 宽表读取 `mid/bid/ask/spread_bps` 等字段。
2. 输出 `signals/、trades.jsonl、pnl_daily.jsonl、run_manifest.json`。
3. 提供一键脚本：`scripts/run_backtest.sh`（Windows 提供 `.ps1` 版本）。

## 交付物

- 回测产物目录 + 一键脚本

## DoD

- [ ] 与旧回测路径结果等价（|Δ| < 1e-8）
- [ ] 产物可被 Report 服务直接消费
