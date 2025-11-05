# Data MCP：统一 Row Schema + 出站 DQ Gate（V4）
**任务编号**: TASK-01  
**批次**: M1  
**优先级**: P0  
**所属模块**: data

## 背景
实时与回放必须同一行结构，提供 dq{ok,reason} 给风控闸门使用。

## 目标
固定 Row Schema 与时间基准（交易所 ts_ms），实现 DQ：spread/lag/静默/时间回退。

## 前置依赖
- V4 主文档 §6

## 输出物
- `/get_live_snapshot` 与 `/get_historical_slice` 统一行结构
- `dq:{ok,reason}`

## 实现步骤（Cursor 分步操作）
- [ ] 打开 `mcp/data_feed_server/app.py`
- [ ] 固化字段：`ts_ms,bid,ask,bid_sz,ask_sz,mid,spread_bps,lag_ms,exch_seq,schema_version`
- [ ] 实作 DQ：时间不回退、spread_bps≤阈、lag≤阈、静默超时→dq.ok=false
- [ ] 压测：limit=64/256/1024

## 验收标准（Acceptance Criteria）
- 两接口返回结构完全一致；异常样本触发 dq.ok=false 且 reason 准确

## 验收命令/脚本
```bash
curl -s http://localhost:9001/get_live_snapshot -X POST -H 'Content-Type: application/json' -d '{"limit":64}' | jq '.dq'
```

## 代码改动清单（相对仓库根）
- mcp/data_feed_server/app.py
- docs/api_contracts.md（如有字段微调）

## 潜在风险与回滚
- 行情异常导致频繁 HOLD：按分位数自适应阈值
- 时钟混乱：统一 ts_ms 为交易所服务器时间

## 预计工时
0.5~1 天
