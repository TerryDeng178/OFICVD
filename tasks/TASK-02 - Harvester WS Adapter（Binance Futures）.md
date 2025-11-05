# TASK-02 · Harvester WS Adapter（Binance Futures）
> 里程碑：M1 | 更新：2025-11-05 (Asia/Tokyo)

## 背景
基于 TASK-01 的 Schema 与 DQ，接入 Binance Futures WS（`aggTrade` / `bookTicker` / `depth@100ms`）。

## 目标
- 建立稳健的 WS 连接与重连；
- 将原始事件映射为统一 Row 并通过 DQ；
- 分片轮转（行数/秒数）；
- 统计健康度（重连次数、吞吐、丢包）。

## 成果物
- 代码：`src/alpha_core/ingestion/harvester.py`（`run_ws_harvest(config)`）  
- 配置：`config/defaults.yaml` → `harvest.ws.urls`, `topics`, `rotate.*`  
- 日志：`logs/harvest/*.jsonl`（健康指标）

## 步骤清单
- [ ] 连接 fstream WS 并订阅 topics；  
- [ ] 统一事件到 Row，送 DQ；  
- [ ] 每 `rotate.max_rows` 或 `rotate.max_sec` 轮转；  
- [ ] 统计：`reconnect_count/tps/queue_dropped`。

## 验收标准
- [ ] 连续运行 1 小时无崩溃；  
- [ ] 数据可被特征层读取；  
- [ ] 健康日志包含关键指标。
