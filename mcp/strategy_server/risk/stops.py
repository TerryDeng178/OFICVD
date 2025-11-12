# -*- coding: utf-8 -*-
"""Stop Rules Module

止损/止盈规则
"""

import logging
import math
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class StopRulesManager:
    """止损/止盈规则管理器"""
    
    def __init__(self, config: Dict):
        """初始化止损/止盈规则管理器
        
        Args:
            config: 配置字典，包含stop_rules配置段
        """
        stop_rules_config = config.get("stop_rules", {})
        self.take_profit_bps = stop_rules_config.get("take_profit_bps", 40.0)
        self.stop_loss_bps = stop_rules_config.get("stop_loss_bps", 25.0)
        # 交易所tick_size（从配置或adapter获取，默认None表示不对齐）
        self.tick_size = stop_rules_config.get("tick_size", None)
    
    def _align_to_tick_size(self, price: float) -> float:
        """对齐价格到交易所tick_size
        
        Args:
            price: 原始价格
            
        Returns:
            对齐后的价格
        """
        if self.tick_size is None or self.tick_size <= 0:
            return price
        
        # 四舍五入到tick_size的倍数（避免向下取整导致限价过严）
        aligned_price = round(price / self.tick_size) * self.tick_size
        return aligned_price
    
    def calculate_price_cap(self, side: str, entry_price: float, max_slippage_bps: float, align_to_tick: bool = True) -> Optional[float]:
        """计算限价上限（根据滑点护栏），并对齐到交易所tick_size
        
        Args:
            side: 订单方向（buy/sell）
            entry_price: 入场价格
            max_slippage_bps: 最大滑点（基点）
            align_to_tick: 是否对齐到tick_size（默认True）
            
        Returns:
            限价上限（None表示不限制）
        """
        if side == "buy":
            # 买单：限价不能超过 entry_price * (1 + max_slippage_bps / 10000)
            price_cap = entry_price * (1 + max_slippage_bps / 10000)
        else:
            # 卖单：限价不能低于 entry_price * (1 - max_slippage_bps / 10000)
            price_cap = entry_price * (1 - max_slippage_bps / 10000)
        
        # 对齐到交易所tick_size（避免Broker端再四舍五入导致成交率与影子对齐出现微抖动）
        if align_to_tick and self.tick_size:
            price_cap = self._align_to_tick_size(price_cap)
        
        return price_cap

