---
id: "TASK-A5"
title: "等价性测试框架（回测 vs 执行器）"
stage: "A"
priority: "P0"
status: "Planned"
owners: "TBD"
deps: ["TASK-A2"]
estimate: "~1.5d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

建立“回测 vs 执行器”等价性测试框架，成为 PR 合并闸门。

## 依赖

- TASK-A2

## 主要步骤

1. 新增 `tests/test_equivalence.py`：同一 features+quotes → BacktestExecutor 与 replay_harness 输出比对（成交/PNL）。
2. CI：新增 `pytest -k equivalence` 任务，阈值 `|Δ| < 1e-8`；不达标即 fail。
3. 提供样例数据与跑法文档 `docs/equivalence_guide.md`。

## 交付物

- 测试套件 + 样例数据描述 + CI 配置片段

## DoD

- [ ] 本地与 CI 均可稳定复现等价性（|Δ| < 1e-8）
- [ ] 引入回归防护：任意执行层改动触发对齐校验
