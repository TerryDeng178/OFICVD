# -*- coding: utf-8 -*-
"""Adapters Module

BaseAdapter 统一适配层：错误码/重试/节流/数量规范化
"""

from .base_adapter import (
    BaseAdapter,
    AdapterOrder,
    AdapterResp,
    AdapterErrorCode,
)
from .backtest_adapter import BacktestAdapter
from .testnet_adapter import TestnetAdapter
from .live_adapter import LiveAdapter
from .error_map import (
    map_http_status_to_error_code,
    map_binance_error_to_error_code,
    map_error_message_to_error_code,
    map_exception_to_error_code,
)

__all__ = [
    "BaseAdapter",
    "AdapterOrder",
    "AdapterResp",
    "AdapterErrorCode",
    "BacktestAdapter",
    "TestnetAdapter",
    "LiveAdapter",
    "map_http_status_to_error_code",
    "map_binance_error_to_error_code",
    "map_error_message_to_error_code",
    "map_exception_to_error_code",
]

