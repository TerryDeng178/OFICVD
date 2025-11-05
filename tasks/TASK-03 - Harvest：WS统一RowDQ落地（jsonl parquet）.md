# Harvest：WS→统一Row→DQ→落地（jsonl/parquet）
**任务编号**: TASK-03  
**批次**: M1  
**优先级**: P0  
**所属模块**: harvest

## 背景
实现 HARVEST 采集层：WebSocket 接入 → 统一 Row Schema → 分片轮转 → 出站 DQ 闸门 → 落地（jsonl/parquet）

## 目标
- 封装 `alpha_core.ingestion.harvester` 可复用库
- 实现 HARVEST MCP 服务器薄壳
- 支持 Binance Futures WebSocket（aggTrade/bookTicker/depth）
- 统一 Row Schema 输出
- 分片轮转（按行数/时间）
- DQ 闸门检查

## 前置依赖
- TASK-01（统一 Row Schema）

## 输出物
- `src/alpha_core/ingestion/harvester.py`（可复用库）
- `mcp/harvest_server/app.py`（MCP 薄壳）
- 分片落地文件（jsonl/parquet）

## 实现步骤（Cursor 分步操作）
- [ ] 从 `run_success_harvest.py` 提取核心逻辑到 `harvester.py`
- [ ] 实现统一 Row Schema 转换
- [ ] 实现分片轮转逻辑
- [ ] 实现 DQ 闸门检查
- [ ] 实现 HARVEST MCP 服务器接口

## 验收标准（Acceptance Criteria）
- HARVEST 可独立运行，输出文件格式正确
- Row Schema 统一，符合 API 契约

## 验收命令/脚本
```bash
python -m mcp.harvest_server.app --config ./config/defaults.yaml
```

## 代码改动清单（相对仓库根）
- src/alpha_core/ingestion/harvester.py
- mcp/harvest_server/app.py
- scripts/harvest_local.sh

## 潜在风险与回滚
- WebSocket 连接不稳定：实现重连机制
- 分片文件过多：实现自动清理策略

## 预计工时
1-2 天

