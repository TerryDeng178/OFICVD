# -*- coding: utf-8 -*-
"""Position Management Module

仓位管理：最大名义额、杠杆、单币种限制等
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PositionManager:
    """仓位管理器"""
    
    def __init__(self, config: Dict):
        """初始化仓位管理器
        
        Args:
            config: 配置字典，包含position配置段
        """
        position_config = config.get("position", {})
        self.max_notional_usd = position_config.get("max_notional_usd", 20000.0)
        self.max_leverage = position_config.get("max_leverage", 5.0)
        self.symbol_limits = position_config.get("symbol_limits", {})
        
        # 交易所Filter约束（从配置或adapter获取）
        self.exchange_filters = position_config.get("exchange_filters", {})
        # 示例：{"BTCUSDT": {"min_notional": 10.0, "step_size": 0.001, "tick_size": 0.01}}
    
    def check_notional(self, symbol: str, qty: float, price: float) -> Tuple[bool, Optional[str], Optional[float]]:
        """检查名义额限制
        
        Args:
            symbol: 交易对符号
            qty: 数量
            price: 价格
            
        Returns:
            (是否通过, 拒绝原因码, 建议的最大数量)
        """
        notional = qty * price
        
        if notional > self.max_notional_usd:
            max_qty = self.max_notional_usd / price if price > 0 else None
            return False, "notional_exceeds_limit", max_qty
        
        return True, None, None
    
    def check_symbol_limit(self, symbol: str, qty: float) -> Tuple[bool, Optional[str], Optional[float]]:
        """检查单币种限制
        
        Args:
            symbol: 交易对符号
            qty: 数量
            
        Returns:
            (是否通过, 拒绝原因码, 建议的最大数量)
        """
        if symbol in self.symbol_limits:
            max_qty = self.symbol_limits[symbol].get("max_qty")
            if max_qty is not None and qty > max_qty:
                return False, "symbol_qty_exceeds_limit", max_qty
        
        return True, None, None
    
    def check_exchange_filters(self, symbol: str, qty: float, price: float) -> Tuple[List[str], Dict[str, Optional[float]]]:
        """检查交易所Filter约束（最小名义、步长、TickSize）
        
        Args:
            symbol: 交易对符号
            qty: 数量
            price: 价格
            
        Returns:
            (拒绝原因码列表, 调整建议字典)
        """
        reasons = []
        adjustments = {}
        
        if symbol not in self.exchange_filters:
            return reasons, adjustments
        
        filters = self.exchange_filters[symbol]
        
        # 检查最小名义额
        min_notional = filters.get("min_notional")
        if min_notional is not None:
            notional = qty * price
            if notional < min_notional:
                reasons.append("notional_below_min")
                # 建议调整到最小名义额
                suggested_qty = min_notional / price if price > 0 else None
                if suggested_qty is not None:
                    adjustments["min_qty"] = suggested_qty
        
        # 检查步长（step_size）
        step_size = filters.get("step_size")
        if step_size is not None and step_size > 0:
            # 对齐数量到step_size
            aligned_qty = round(qty / step_size) * step_size
            if abs(qty - aligned_qty) > 1e-10:  # 浮点数精度容差
                reasons.append("qty_not_aligned_to_step_size")
                adjustments["aligned_qty"] = aligned_qty
        
        # 检查TickSize（价格精度）
        tick_size = filters.get("tick_size")
        if tick_size is not None and tick_size > 0:
            # 对齐价格到tick_size
            aligned_price = round(price / tick_size) * tick_size
            if abs(price - aligned_price) > 1e-10:  # 浮点数精度容差
                reasons.append("price_not_aligned_to_tick_size")
                adjustments["aligned_price"] = aligned_price
        
        return reasons, adjustments
    
    def check_all(self, symbol: str, qty: float, price: float) -> Tuple[List[str], Dict[str, Optional[float]]]:
        """检查所有仓位限制（包括交易所Filter约束）
        
        Args:
            symbol: 交易对符号
            qty: 数量
            price: 价格
            
        Returns:
            (拒绝原因码列表, 调整建议字典)
        """
        reasons = []
        adjustments = {}
        
        # 1. 检查交易所Filter约束（优先，确保可落单）
        exchange_reasons, exchange_adjustments = self.check_exchange_filters(symbol, qty, price)
        reasons.extend(exchange_reasons)
        adjustments.update(exchange_adjustments)
        
        # 2. 检查名义额
        passed, reason, max_qty = self.check_notional(symbol, qty, price)
        if not passed:
            reasons.append(reason)
            if max_qty is not None:
                # 取最小值（交易所约束和名义额约束的较小值）
                current_max_qty = adjustments.get("max_qty", float("inf"))
                adjustments["max_qty"] = min(current_max_qty, max_qty)
        
        # 3. 检查单币种限制
        passed, reason, max_qty = self.check_symbol_limit(symbol, qty)
        if not passed:
            reasons.append(reason)
            if max_qty is not None:
                current_max_qty = adjustments.get("max_qty", float("inf"))
                adjustments["max_qty"] = min(current_max_qty, max_qty)
        
        # 4. 最终数量对齐（如果存在aligned_qty，优先使用）
        if "aligned_qty" in adjustments:
            aligned_qty = adjustments["aligned_qty"]
            # 同时考虑max_qty约束
            if "max_qty" in adjustments:
                adjustments["final_qty"] = min(aligned_qty, adjustments["max_qty"])
            else:
                adjustments["final_qty"] = aligned_qty
        
        return reasons, adjustments

