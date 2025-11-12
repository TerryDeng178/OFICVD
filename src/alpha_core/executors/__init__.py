# -*- coding: utf-8 -*-
"""Execution Layer Abstraction

IExecutor抽象层：统一回测/测试网/实盘执行接口
"""

from .base_executor import (
    IExecutor,
    Order,
    OrderCtx,
    Fill,
    ExecResult,
    ExecResultStatus,
    CancelResult,
    AmendResult,
    Side,
    OrderType,
    TimeInForce,
    OrderState,
)
from .backtest_executor import BacktestExecutor
from .testnet_executor import TestnetExecutor
from .live_executor import LiveExecutor
from .executor_factory import create_executor
from .broker_gateway_client import BrokerGatewayClient
from .executor_metrics import ExecutorMetrics, get_executor_metrics
from .executor_precheck import ExecutorPrecheck, AdaptiveThrottler

try:
    from .binance_api import BinanceFuturesAPI
    __all__ = [
        "IExecutor",
        "Order",
        "OrderCtx",
        "Fill",
        "ExecResult",
        "ExecResultStatus",
        "CancelResult",
        "AmendResult",
        "Side",
        "OrderType",
        "TimeInForce",
        "OrderState",
        "BacktestExecutor",
        "TestnetExecutor",
        "LiveExecutor",
        "create_executor",
        "BrokerGatewayClient",
        "BinanceFuturesAPI",
        "ExecutorMetrics",
        "get_executor_metrics",
        "ExecutorPrecheck",
        "AdaptiveThrottler",
    ]
except ImportError:
    __all__ = [
        "IExecutor",
        "Order",
        "OrderCtx",
        "Fill",
        "ExecResult",
        "ExecResultStatus",
        "CancelResult",
        "AmendResult",
        "Side",
        "OrderType",
        "TimeInForce",
        "OrderState",
        "BacktestExecutor",
        "TestnetExecutor",
        "LiveExecutor",
        "create_executor",
        "BrokerGatewayClient",
        "ExecutorMetrics",
        "get_executor_metrics",
        "ExecutorPrecheck",
        "AdaptiveThrottler",
    ]
