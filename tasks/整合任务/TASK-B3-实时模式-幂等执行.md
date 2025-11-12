---
id: "TASK-B3"
title: "实时模式 + 幂等执行"
stage: "B"
priority: "P0"
status: "Planned"
owners: "TBD"
deps: ["TASK-B1"]
estimate: "~2d"
created: "2025-11-11"
risk: "中"
tags: ["MCP", "Strategy", "OFI", "CVD"]
---

## 目标

实时模式（仅读 signals）+ 幂等执行，稳定长跑。

## 依赖

- TASK-B1

## 主要步骤

1. 文件监听与执行：从 `signal_server` 产物拉流，逐条处理，写入 `runtime/executions/*`。
2. 幂等保证：以 `order_id` + `signal_id` 作为去重键，重复投递不重入。
3. 失败重试/节流：沿用 BaseAdapter 策略；超时、速率限制、网络波动处理。
4. 运行日志：按小时滚动保存，记录 `lag_ms`、`queue_len`、`success/fail/retry`。

## 交付物

- `runtime/executions/*` 产物 + 运行日志 + 配置

## DoD

- [ ] 长跑 1 小时不漏读/不重放/不崩溃
- [ ] 宕机重启后能够从上次 offset 恢复继续执行
