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
- [x] 连接 fstream WS 并订阅 topics（已实现统一流连接：`connect_unified_streams`）；  
- [x] 统一事件到 Row，送 DQ（已实现：`_process_trade_data` 和 `_process_orderbook_data`）；  
- [x] 每 `rotate.max_rows` 或 `rotate.max_sec` 轮转（已实现：`_check_and_rotate_data`，支持动态轮转间隔）；  
- [x] 统计：`reconnect_count/tps/queue_dropped`（已实现完整统计和健康监控）。

## 验收标准
- [x] 连续运行 1 小时无崩溃（已支持 7x24 小时连续运行，带自愈重连）；  
- [x] 数据可被特征层读取（已实现 Parquet 格式，支持特征层读取）；  
- [x] 健康日志包含关键指标（已实现健康检查循环和统计信息输出）。

**状态：已完成（核心逻辑已从 `run_success_harvest.py` 迁移至 `src/alpha_core/ingestion/harvester.py`，包含完整的 WebSocket 连接、重连、数据处理、OFI/CVD/Fusion 计算、分片轮转等功能）**
