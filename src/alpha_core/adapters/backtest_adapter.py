# -*- coding: utf-8 -*-
"""BacktestAdapter Implementation

回测适配器：使用TradeSimulator
"""

import logging
import time
from typing import Dict, Any, List, Optional

from .base_adapter import BaseAdapter, AdapterOrder, AdapterResp, AdapterErrorCode
from ..backtest.trade_sim import TradeSimulator

logger = logging.getLogger(__name__)


class BacktestAdapter(BaseAdapter):
    """回测适配器
    
    使用TradeSimulator进行回测，仅返回OK或E.PARAMS
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化回测适配器"""
        super().__init__(config)
        self.trade_sim: Optional[TradeSimulator] = None
        
        # 初始化TradeSimulator
        backtest_cfg = config.get("backtest", {})
        output_dir = self.output_dir
        self.trade_sim = TradeSimulator(
            config=backtest_cfg,
            output_dir=output_dir,
            ignore_gating_in_backtest=backtest_cfg.get("ignore_gating", False),
        )
    
    def kind(self) -> str:
        """适配器类型"""
        return "backtest"
    
    def _load_rules_impl(self, symbol: str) -> Dict[str, Any]:
        """加载交易规则（回测模式使用默认规则）"""
        # 回测模式使用默认规则
        # 实际应该从交易所API获取，这里简化处理
        default_rules = {
            "qty_step": 0.0001,
            "qty_min": 0.001,
            "price_tick": 0.01,
            "min_notional": 5.0,
            "precision": {"qty": 8, "price": 8},
            "base": symbol[:3] if len(symbol) > 3 else "BTC",
            "quote": "USDT",
            "mark_price": 50000.0,  # 默认标记价格（回测模式）
        }
        
        logger.debug(f"[BacktestAdapter] Loaded default rules for {symbol}")
        return default_rules
    
    def _submit_impl(self, order: AdapterOrder) -> AdapterResp:
        """提交订单实现"""
        if not self.trade_sim:
            return AdapterResp(
                ok=False,
                code=AdapterErrorCode.E_UNKNOWN,
                msg="TradeSimulator not initialized",
            )
        
        # 回测模式下，订单总是成功（除非参数错误）
        # 实际成交由TradeSimulator处理
        broker_order_id = order.client_order_id  # 回测模式下相同
        
        return AdapterResp(
            ok=True,
            code=AdapterErrorCode.OK,
            msg="Order submitted",
            broker_order_id=broker_order_id,
        )
    
    def _cancel_impl(self, symbol: str, broker_order_id: str) -> AdapterResp:
        """撤销订单实现"""
        # 回测模式下，撤单总是成功
        return AdapterResp(
            ok=True,
            code=AdapterErrorCode.OK,
            msg="Order canceled",
            broker_order_id=broker_order_id,
        )
    
    def fetch_fills(self, symbol: str, since_ts_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取成交记录"""
        # 回测模式下，从TradeSimulator获取成交
        # 这里简化处理，返回空列表
        # 实际应该从TradeSimulator的成交记录中获取
        return []

