# -*- coding: utf-8 -*-
"""LiveAdapter Implementation

实盘适配器：使用Binance Live API
"""

import logging
import time
from typing import Dict, Any, List, Optional

from .base_adapter import BaseAdapter, AdapterOrder, AdapterResp, AdapterErrorCode
from ..executors.binance_api import BinanceFuturesAPI
from ..executors.broker_gateway_client import BrokerGatewayClient

logger = logging.getLogger(__name__)


class LiveAdapter(BaseAdapter):
    """实盘适配器
    
    使用Binance Live API或Broker Gateway MCP
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化实盘适配器"""
        super().__init__(config)
        
        broker_cfg = config.get("broker", {})
        
        # 优先使用Broker Gateway MCP
        use_broker_gateway = broker_cfg.get("use_broker_gateway", True)
        
        if use_broker_gateway:
            # 使用Broker Gateway MCP客户端
            broker_cfg_with_mock = broker_cfg.copy()
            broker_cfg_with_mock["mock_enabled"] = broker_cfg.get("mock_enabled", False)  # 实盘默认不使用Mock
            broker_cfg_with_mock["mock_output_path"] = str(self.output_dir / "live_orders.jsonl")
            self.broker_client = BrokerGatewayClient(broker_cfg_with_mock)
            self.binance_api = None
        else:
            # 直接使用Binance API
            import os
            api_key = broker_cfg.get("api_key") or os.getenv(broker_cfg.get("api_key_env", "BINANCE_API_KEY"), "")
            secret_key = broker_cfg.get("secret_key") or os.getenv(broker_cfg.get("secret_env", "BINANCE_API_SECRET"), "")
            
            if not api_key or not secret_key:
                raise ValueError("Binance API credentials not found")
            
            self.binance_api = BinanceFuturesAPI(api_key=api_key, secret_key=secret_key, testnet=False)
            self.broker_client = None
        
        logger.warning("[LiveAdapter] LIVE TRADING MODE - Real money at risk!")
    
    def kind(self) -> str:
        """适配器类型"""
        return "live"
    
    def _load_rules_impl(self, symbol: str) -> Dict[str, Any]:
        """加载交易规则（从交易所API获取）"""
        try:
            if self.binance_api:
                # 从Binance API获取交易规则
                exchange_info = self.binance_api.get_exchange_info()
                # 解析exchange_info获取symbol的规则
                # 这里简化处理，返回默认规则
                pass
            
            # 默认规则（如果API调用失败）
            default_rules = {
                "qty_step": 0.0001,
                "qty_min": 0.001,
                "price_tick": 0.01,
                "min_notional": 5.0,
                "precision": {"qty": 8, "price": 8},
                "base": symbol[:3] if len(symbol) > 3 else "BTC",
                "quote": "USDT",
            }
            
            # P0: 补充 mark_price（用于市价单名义额计算）
            mark_price = self._get_mark_price(symbol)
            if mark_price and mark_price > 0:
                default_rules["mark_price"] = mark_price
            else:
                # 如果无法获取，使用配置的 order_size_usd 作为回退
                order_size_usd = self.config.get("adapter", {}).get("order_size_usd", 100.0)
                default_mark_price = 50000.0 if "BTC" in symbol else 1000.0
                default_rules["mark_price"] = default_mark_price
                logger.warning(f"[LiveAdapter] Using fallback mark_price={default_mark_price} for {symbol}")
            
            logger.debug(f"[LiveAdapter] Loaded rules for {symbol}, mark_price={default_rules.get('mark_price')}")
            return default_rules
            
        except Exception as e:
            logger.error(f"[LiveAdapter] Failed to load rules for {symbol}: {e}")
            # 返回默认规则
            fallback_rules = {
                "qty_step": 0.0001,
                "qty_min": 0.001,
                "price_tick": 0.01,
                "min_notional": 5.0,
                "precision": {"qty": 8, "price": 8},
                "base": symbol[:3] if len(symbol) > 3 else "BTC",
                "quote": "USDT",
            }
            
            # P0: 补充 mark_price
            mark_price = self._get_mark_price(symbol)
            if mark_price and mark_price > 0:
                fallback_rules["mark_price"] = mark_price
            else:
                fallback_rules["mark_price"] = 50000.0 if "BTC" in symbol else 1000.0
            
            return fallback_rules
    
    def _get_mark_price(self, symbol: str) -> Optional[float]:
        """获取标记价格（用于市价单名义额计算）
        
        Args:
            symbol: 交易对
            
        Returns:
            标记价格，如果无法获取则返回 None
        """
        try:
            # P1: 优先从 Broker Gateway 获取 ticker
            if self.broker_client:
                try:
                    # 尝试调用 broker_client 的 ticker 接口（如果可用）
                    if hasattr(self.broker_client, 'get_ticker'):
                        ticker = self.broker_client.get_ticker(symbol)
                        if ticker:
                            price = ticker.get("lastPrice") or ticker.get("markPrice") or ticker.get("price")
                            if price:
                                return float(price)
                    # 如果 broker_client 没有 ticker 接口，尝试从订单簿获取
                    if hasattr(self.broker_client, 'get_orderbook'):
                        orderbook = self.broker_client.get_orderbook(symbol, limit=1)
                        if orderbook and orderbook.get("bids"):
                            bid_price = float(orderbook["bids"][0][0])
                            if bid_price > 0:
                                return bid_price
                except Exception as e:
                    logger.debug(f"[LiveAdapter] Broker client ticker failed: {e}")
            
            # 回退到 Binance API
            if self.binance_api:
                ticker = self.binance_api.get_ticker(symbol)
                if ticker:
                    return float(ticker.get("lastPrice", ticker.get("markPrice", 0.0)))
            
            return None
        except Exception as e:
            logger.debug(f"[LiveAdapter] Failed to get mark_price for {symbol}: {e}")
            return None
    
    def _submit_impl(self, order: AdapterOrder) -> AdapterResp:
        """提交订单实现"""
        try:
            if self.broker_client:
                # 使用Broker Gateway MCP
                from ..executors.base_executor import Order as ExecOrder, Side, OrderType
                
                exec_order = ExecOrder(
                    client_order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=Side.BUY if order.side == "buy" else Side.SELL,
                    qty=order.qty,
                    order_type=OrderType.MARKET if order.order_type == "market" else OrderType.LIMIT,
                    price=order.price,
                    ts_ms=order.ts_ms,
                )
                
                broker_order_id = self.broker_client.submit_order(exec_order)
                
                return AdapterResp(
                    ok=True,
                    code=AdapterErrorCode.OK,
                    msg="Order submitted",
                    broker_order_id=broker_order_id,
                )
            
            if self.binance_api:
                # 直接使用Binance API
                result = self.binance_api.place_order(
                    symbol=order.symbol,
                    side=order.side.upper(),
                    order_type=order.order_type.upper(),
                    quantity=order.qty,
                    price=order.price,
                )
                
                return AdapterResp(
                    ok=True,
                    code=AdapterErrorCode.OK,
                    msg="Order submitted",
                    broker_order_id=str(result.get("orderId", "")),
                    raw=result,
                )
            
            return AdapterResp(
                ok=False,
                code=AdapterErrorCode.E_UNKNOWN,
                msg="No broker client available",
            )
            
        except Exception as e:
            logger.error(f"[LiveAdapter] Submit failed: {e}")
            # P1: 使用表驱动错误映射，尝试提取 HTTP status
            from .error_map import map_exception_to_error_code
            http_status = None
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                http_status = e.response.status_code
            elif hasattr(e, "status_code"):
                http_status = e.status_code
            error_code = map_exception_to_error_code(e, http_status=http_status)
            
            return AdapterResp(
                ok=False,
                code=error_code,
                msg=str(e),
            )
    
    def _cancel_impl(self, symbol: str, broker_order_id: str) -> AdapterResp:
        """撤销订单实现"""
        try:
            if self.broker_client:
                # 使用Broker Gateway MCP
                success = self.broker_client.cancel_order(broker_order_id, symbol=symbol)
                
                return AdapterResp(
                    ok=success,
                    code=AdapterErrorCode.OK if success else AdapterErrorCode.E_BROKER_REJECT,
                    msg="Order canceled" if success else "Cancel failed",
                    broker_order_id=broker_order_id,
                )
            
            if self.binance_api:
                # 直接使用Binance API
                result = self.binance_api.cancel_order(symbol=symbol, order_id=int(broker_order_id))
                
                return AdapterResp(
                    ok=True,
                    code=AdapterErrorCode.OK,
                    msg="Order canceled",
                    broker_order_id=broker_order_id,
                    raw=result,
                )
            
            return AdapterResp(
                ok=False,
                code=AdapterErrorCode.E_UNKNOWN,
                msg="No broker client available",
            )
            
        except Exception as e:
            logger.error(f"[LiveAdapter] Cancel failed: {e}")
            error_code = AdapterErrorCode.E_UNKNOWN
            if "network" in str(e).lower() or "timeout" in str(e).lower():
                error_code = AdapterErrorCode.E_NETWORK
            elif "rate limit" in str(e).lower() or "429" in str(e):
                error_code = AdapterErrorCode.E_RATE_LIMIT
            elif "not found" in str(e).lower() or "does not exist" in str(e).lower():
                error_code = AdapterErrorCode.E_STATE_CONFLICT
            
            return AdapterResp(
                ok=False,
                code=error_code,
                msg=str(e),
            )
    
    def fetch_fills(self, symbol: str, since_ts_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取成交记录"""
        try:
            if self.binance_api:
                # 从Binance API获取成交
                trades = self.binance_api.get_user_trades(symbol=symbol, start_time=since_ts_ms)
                return trades
            
            # Broker Gateway MCP暂不支持成交查询
            return []
            
        except Exception as e:
            logger.error(f"[LiveAdapter] Fetch fills failed: {e}")
            return []

