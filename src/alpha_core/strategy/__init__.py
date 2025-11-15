# -*- coding: utf-8 -*-
"""
Alpha Core Strategy Layer

统一的策略决策层，支持：
- 回测环境
- 测试网环境
- 实盘环境

提供统一的策略决策接口，确保三套环境的行为一致性。
"""

from .policy import (
    SOFT_GATING,
    HARD_ALWAYS_BLOCK,
    is_tradeable,
    StrategyEmulator,
)

__all__ = [
    "SOFT_GATING",
    "HARD_ALWAYS_BLOCK",
    "is_tradeable",
    "StrategyEmulator",
]
