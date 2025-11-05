# -*- coding: utf-8 -*-
"""
HARVEST MCP Server

采集层服务器：使用 alpha_core.ingestion.harvester 实现
"""

# TODO: 实现 HARVEST MCP 服务器
# - 调用 alpha_core.ingestion.harvester
# - 提供 MCP 接口：/start, /stop, /status
# - 配置：WS URL、输出格式、分片策略等

from alpha_core.ingestion import Harvester

