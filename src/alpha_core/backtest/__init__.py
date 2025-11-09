# -*- coding: utf-8 -*-
"""Backtest Harness Module

This module provides components for backtesting trading strategies:
- Reader: Read and filter historical data (JSONL/Parquet)
- Aligner: Align raw data to seconds and compute features
- Feeder: Feed data to CORE_ALGO in replay mode
- TradeSim: Simulate trades with fees and slippage
- Aggregator: Compute performance metrics
"""

from .reader import DataReader
from .aligner import DataAligner
from .feeder import ReplayFeeder
from .trade_sim import TradeSimulator
from .metrics import MetricsAggregator

__all__ = [
    "DataReader",
    "DataAligner",
    "ReplayFeeder",
    "TradeSimulator",
    "MetricsAggregator",
]

