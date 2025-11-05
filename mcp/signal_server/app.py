# -*- coding: utf-8 -*-
"""
CORE_ALGO MCP Server

信号层服务器：使用 alpha_core.signals.core_algo 实现
"""

# TODO: 实现 CORE_ALGO MCP 服务器
# - 调用 alpha_core.signals.core_algo
# - 提供 MCP 接口：/compute_signal, /get_status
# - 支持 Sink：JSONL/SQLite
# - 健康度指标输出

from alpha_core.signals import CoreAlgo

