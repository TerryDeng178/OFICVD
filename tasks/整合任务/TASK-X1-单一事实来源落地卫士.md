---
id: "TASK-X1"
title: "单一事实来源“落地卫士”"
stage: "X"
priority: "P0"
status: "Planned"
owners: "TBD"
deps: []
estimate: "~1d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

为“单一事实来源”落地添加守卫（Linter/Hook/运行时断言/日志审计）。

## 依赖

- 与 A/B/C 并行

## 主要步骤

1. Linter 规则：禁止 Strategy 读取 `features/*` 路径。
2. Pre-commit Hook：检测新增代码中的跨层读取调用。
3. 运行时断言：Strategy 进程启动时验证数据来源；异常即报警退出。
4. 日志审计：每小时汇总异常尝试次数并告警。

## 交付物

- Linter/Hook/断言/审计脚本 + 配置

## DoD

- [ ] 任意组件尝试跨层读 features 将被拒绝并记录
- [ ] CI 增设静态检查，不合规则拒绝合并
