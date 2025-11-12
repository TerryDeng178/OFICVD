# -*- coding: utf-8 -*-
"""Adapter Factory

适配器工厂：根据配置创建适配器实例
"""

import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

from .base_adapter import BaseAdapter

if TYPE_CHECKING:
    from .backtest_adapter import BacktestAdapter
    from .testnet_adapter import TestnetAdapter
    from .live_adapter import LiveAdapter

logger = logging.getLogger(__name__)


def create_adapter(config: Dict[str, Any]) -> BaseAdapter:
    """创建适配器实例
    
    Args:
        config: 配置字典，包含 adapter.impl 配置
        
    Returns:
        适配器实例
    """
    adapter_cfg = config.get("adapter", {})
    impl = adapter_cfg.get("impl")
    
    # 如果未配置，从环境变量获取
    if not impl:
        import os
        impl = os.getenv("ADAPTER_IMPL")
    
    # 如果仍未配置，从executor.mode推断
    if not impl:
        executor_cfg = config.get("executor", {})
        mode = executor_cfg.get("mode", "backtest")
        impl = mode  # backtest/testnet/live
    
    # 创建适配器实例（延迟导入，避免循环导入）
    if impl == "backtest":
        from .backtest_adapter import BacktestAdapter
        return BacktestAdapter(config)
    elif impl == "testnet":
        from .testnet_adapter import TestnetAdapter
        return TestnetAdapter(config)
    elif impl == "live":
        from .live_adapter import LiveAdapter
        return LiveAdapter(config)
    else:
        raise ValueError(f"Unknown adapter implementation: {impl}")

