---
id: "TASK-B4"
title: "订单状态机（最小闭环）"
stage: "B"
priority: "P1"
status: "Planned"
owners: "TBD"
deps: ["TASK-A3"]
estimate: "~2d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

实现订单状态机（NEW→PARTIALLY_FILLED→FILLED/CANCELED/REJECTED），纳入等价性测试。

## 依赖

- TASK-A3

## 主要步骤

1. 设计状态机与事件：`submit/ack/partial_fill/fill/cancel/reject/timeout`。
2. 合并部分成交：按 `order_id` 聚合多次成交明细，计算加权均价/滑点/费用。
3. 衍生统计：每笔/每日成交量、胜率、MAE/MFE、滑点分布。
4. 覆盖测试：延迟、拒单、撤单回补等路径。

## 交付物

- 状态机模块 + 单元测试 + 报表字段说明

## DoD

- [ ] 回测与实时均能正确推进状态
- [ ] 等价性测试覆盖状态转换（含延迟与拒单）
