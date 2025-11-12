---
id: "TASK-B1"
title: "信号边界固化（Strategy 仅读 signals）"
stage: "B"
priority: "P0"
status: "Planned"
owners: "TBD"
deps: ["TASK-A4"]
estimate: "~1d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

信号边界固化：Strategy 仅读 `signals`，不跨层读取 `features`（单一事实来源）。

## 依赖

- TASK-A4

## 主要步骤

1. Strategy 监听 `signals.jsonl` 或 `SQLite`；移除任何 features 读取路径与配置。
2. Orchestrator 固定 `signals` 目录结构，增加文件数与延迟健康探针。
3. 新增运行时断言：若读取到 features 路径，立即报错并退出。

## 交付物

- 监控探针 + 配置 + 运行时断言

## DoD

- [ ] 断开 features 后仍可稳定执行 1 小时
- [ ] 健康探针可在文件停更 60s 内报警
