---
id: "TASK-C2"
title: "文档与契约同步（V4.2）"
stage: "C"
priority: "P1"
status: "Planned"
owners: "TBD"
deps: ["TASK-C1"]
estimate: "~1d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

文档与契约同步（V4.2），统一 README、TASK_INDEX、API 契约与“单一事实来源”的对外说明。

## 依赖

- TASK-C1

## 主要步骤

1. README：新增 `strategy_server`，移除冗余服务；提供“快速上手”三步。
2. `/docs/api_contracts.md`：给出 Features/Signals/Executions 三类产物示例（JSON Schema + 示例）。
3. `/TASK_INDEX.md`：更新任务列表、依赖、里程碑、燃尽图位点。
4. 强调“单一事实来源”（features → signals → strategy 的唯一路径）。

## 交付物

- 文档合并 PR（README、TASK_INDEX、API 契约）

## DoD

- [ ] 文档链接可用、Mermaid 可渲染
- [ ] README 快速上手流程可复现
- [ ] 契约示例能被 schema 校验器通过
