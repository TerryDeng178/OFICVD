# Broker MCP：幂等键 + 订单状态机（TIMEOUT→REQUERY）
**任务编号**: TASK-10  
**批次**: M1  
**优先级**: P0  
**所属模块**: broker

## 背景
避免重复下单与僵尸单，保证审计回放可复现。

## 目标
实现最小状态机与 `idempotency_key`；所有迁移写入 `logs/orders.jsonl`。

## 前置依赖
- —

## 输出物
- `/place_order`、`/cancel_order`、`/sync_fills_and_positions` 完整

## 实现步骤（Cursor 分步操作）
- [ ] `idempotency_key=sha256(side,qty,ts_bucket,signal_fp)`
- [ ] 下单前查同 key 未终态→直接返回
- [ ] ack/fill 超时→REQUERY
- [ ] 所有迁移落日志

## 验收标准（Acceptance Criteria）
- 并发压测重复率为 0；状态稳定收敛

## 验收命令/脚本
自备并发脚本或 locust

## 代码改动清单（相对仓库根）
- mcp/broker_gateway_server/app.py
- logs/orders.jsonl

## 潜在风险与回滚
- 终态判断遗漏：覆盖测试

## 预计工时
1 天
