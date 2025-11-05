# -*- coding: utf-8 -*-
"""
OFI Risk MCP Server

风控服务器：使用 StrategyModeManager 做第一层闸门
"""

# TODO: 实现 Risk MCP 服务器
# - 使用 StrategyModeManager 做第一层闸门
# - 实现波动率目标仓位与日内损失墙（迟滞）
# - 输出：{allow, side, qty, lev, mode, reason, risk_state}

from alpha_core.risk import StrategyModeManager, StrategyMode, MarketActivity

