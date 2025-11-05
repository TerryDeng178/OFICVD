# -*- coding: utf-8 -*-
"""
Broker Gateway MCP Server

交易所网关服务器：幂等键 + 订单状态机
"""

# TODO: 实现 Broker MCP 服务器
# - 幂等键 + 订单状态机（TIMEOUT→REQUERY→ACK/FILLED/CANCELLED）
# - 后端可切换 paper|ccxt|testnet|live

