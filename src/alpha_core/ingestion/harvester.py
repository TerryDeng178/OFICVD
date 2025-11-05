# -*- coding: utf-8 -*-
"""
HARVEST 采集层库

实现 WebSocket 接入 → 统一 Row Schema → 分片轮转 → 出站 DQ 闸门
可复用于 HARVEST MCP 服务器和 data_feed_server

功能：
- Binance Futures WebSocket 接入（aggTrade/bookTicker/depth）
- 统一 Row Schema 输出
- 分片轮转（按行数/时间）
- 数据质量检查（DQ Gate）
- 输出格式：JSONL/Parquet
"""

# TODO: 从 run_success_harvest.py 提取核心逻辑，封装为可复用库
# - WS 连接管理
# - 统一 Row Schema 转换
# - 分片轮转逻辑
# - DQ 闸门检查
# - 输出格式处理（JSONL/Parquet）

class Harvester:
    """
    HARVEST 采集器
    
    职责：
    - WebSocket 连接与消息处理
    - 数据格式统一转换
    - 分片轮转
    - 数据质量检查
    """
    pass

