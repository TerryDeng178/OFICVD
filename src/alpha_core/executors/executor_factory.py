# -*- coding: utf-8 -*-
"""Executor Factory

执行器工厂：根据mode创建对应的执行器实例
"""

import logging
from typing import Dict, Any

from .base_executor import IExecutor
from .backtest_executor import BacktestExecutor
from .testnet_executor import TestnetExecutor
from .live_executor import LiveExecutor

logger = logging.getLogger(__name__)


def create_executor(mode: str, cfg: Dict[str, Any]) -> IExecutor:
    """创建执行器实例
    
    Args:
        mode: 执行模式（backtest/testnet/live）
        cfg: 配置字典
        
    Returns:
        IExecutor实例
    """
    executor_cfg = cfg.get("executor", {})
    actual_mode = executor_cfg.get("mode", mode)
    
    if actual_mode == "backtest":
        executor = BacktestExecutor()
    elif actual_mode == "testnet":
        executor = TestnetExecutor()
    elif actual_mode == "live":
        executor = LiveExecutor()
    else:
        raise ValueError(f"Unknown executor mode: {actual_mode}")
    
    # 初始化执行器
    executor.prepare(cfg)
    
    logger.info(f"[ExecutorFactory] Created {actual_mode} executor")
    return executor

