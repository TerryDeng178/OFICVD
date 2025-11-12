# -*- coding: utf-8 -*-
"""Broker Gateway MCP Client

Broker Gateway MCP客户端：用于TestnetExecutor和LiveExecutor调用Broker Gateway服务
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, List

from .base_executor import Order, Fill, Side, OrderState

try:
    from .binance_api import BinanceFuturesAPI
    BINANCE_API_AVAILABLE = True
except ImportError:
    BINANCE_API_AVAILABLE = False
    BinanceFuturesAPI = None

logger = logging.getLogger(__name__)


class BrokerGatewayClient:
    """Broker Gateway MCP客户端
    
    支持Mock模式和真实API模式
    """
    
    def __init__(self, config: Dict):
        """初始化Broker Gateway客户端
        
        Args:
            config: broker配置段
        """
        self.config = config
        self.name = config.get("name", "binance-futures")
        self.testnet = config.get("testnet", True)
        self.dry_run = config.get("dry_run", True)
        self.api_key_env = config.get("api_key_env", "BINANCE_API_KEY")
        self.secret_env = config.get("secret_env", "BINANCE_API_SECRET")
        
        # Mock模式配置
        self.mock_enabled = config.get("mock_enabled", True)  # 默认Mock模式
        self.mock_output_path = Path(config.get("mock_output_path", "./runtime/mock_orders.jsonl"))
        self.mock_sample_rate = config.get("mock_sample_rate", 0.2)
        
        # 真实API配置
        self.api_key = None
        self.secret_key = None
        self.binance_api: Optional[BinanceFuturesAPI] = None
        
        if not self.mock_enabled:
            # 从环境变量或配置中获取API密钥
            api_key_env = config.get("api_key_env", "BINANCE_API_KEY")
            secret_env = config.get("secret_env", "BINANCE_API_SECRET")
            
            self.api_key = os.getenv(api_key_env) or config.get("api_key")
            self.secret_key = os.getenv(secret_env) or config.get("secret_key")
            
            if not self.api_key or not self.secret_key:
                raise ValueError(
                    f"API credentials not found. Set {api_key_env} and {secret_env} "
                    f"environment variables or provide api_key/secret_key in config."
                )
            
            if BINANCE_API_AVAILABLE and self.name == "binance-futures":
                self.binance_api = BinanceFuturesAPI(
                    api_key=self.api_key,
                    secret_key=self.secret_key,
                    testnet=self.testnet
                )
                if not self.testnet:
                    logger.warning("[BrokerGatewayClient] WARNING: LIVE TRADING MODE - Real money at risk!")
                    logger.warning("[BrokerGatewayClient] Please ensure mock_enabled=false is intentional.")
                logger.info("[BrokerGatewayClient] Binance API client initialized")
            else:
                if not BINANCE_API_AVAILABLE:
                    raise ImportError("Binance API not available. Install requests: pip install requests")
                raise ValueError(f"Unsupported broker: {self.name}")
        
        # 订单映射（client_order_id -> broker_order_id）
        self.order_map: Dict[str, str] = {}
        self.fill_map: Dict[str, List[Fill]] = {}  # client_order_id -> List[Fill]
        
        logger.info(
            f"[BrokerGatewayClient] Initialized: name={self.name}, "
            f"testnet={self.testnet}, dry_run={self.dry_run}, mock={self.mock_enabled}"
        )
    
    def submit_order(self, order: Order) -> str:
        """提交订单
        
        Args:
            order: 订单对象
            
        Returns:
            broker_order_id: 交易所订单ID
        """
        if self.mock_enabled:
            return self._submit_order_mock(order)
        else:
            return self._submit_order_real(order)
    
    def _submit_order_mock(self, order: Order) -> str:
        """Mock模式提交订单"""
        # 生成broker_order_id
        broker_order_id = f"MOCK-{int(time.time() * 1000)}-{order.client_order_id}"
        self.order_map[order.client_order_id] = broker_order_id
        
        # 获取中间价（优先从 metadata，其次从 order.price，最后使用默认值）
        mid_price = order.metadata.get("mid_price", 0.0) if order.metadata else 0.0
        if not mid_price:
            mid_price = order.price or 50000.0
        
        # 计算成交价格（考虑滑点，与 BacktestExecutor 保持一致）
        # 优先从 backtest 配置获取，其次从 broker 配置，最后使用默认值
        backtest_cfg = self.config.get("backtest", {})
        slippage_bps = backtest_cfg.get("slippage_bps") or self.config.get("slippage_bps", 1.0)
        if order.side == Side.BUY:
            fill_price = mid_price * (1 + slippage_bps / 10000)
        else:
            fill_price = mid_price * (1 - slippage_bps / 10000)
        
        # 计算手续费（与 BacktestExecutor 保持一致）
        # 优先从 backtest 配置获取 taker_fee_bps，其次从 broker 配置，最后使用默认值
        fee_bps = backtest_cfg.get("taker_fee_bps") or backtest_cfg.get("fee_bps") or self.config.get("fee_bps", 1.93)
        notional = fill_price * order.qty
        fee = notional * (fee_bps / 10000)
        
        # 模拟成交（Mock模式立即成交）
        fill = Fill(
            ts_ms=order.ts_ms + 50,  # 模拟50ms延迟
            symbol=order.symbol,
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            price=fill_price,
            qty=order.qty,
            fee=fee,
            liquidity="taker",
            side=order.side,
        )
        
        if order.client_order_id not in self.fill_map:
            self.fill_map[order.client_order_id] = []
        self.fill_map[order.client_order_id].append(fill)
        
        # 写入Mock订单文件（与broker_gateway_server格式一致）
        try:
            self.mock_output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.mock_output_path.open("a", encoding="utf-8", newline="") as f:
                mock_order = {
                    "order_id": broker_order_id,
                    "symbol": order.symbol,
                    "side": order.side.value.upper(),
                    "strength": "NORMAL",
                    "signal_type": order.side.value,
                    "signal_score": order.metadata.get("score", 0.0),
                    "signal_ts_ms": order.ts_ms,
                    "order_ts_ms": int(time.time() * 1000),
                    "status": "FILLED",
                    "filled_qty": fill.qty,
                    "filled_price": fill.price,
                    "fee": fill.fee,
                }
                f.write(json.dumps(mock_order, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[BrokerGatewayClient] Failed to write mock order: {e}")
        
        logger.info(
            f"[BrokerGatewayClient] Mock order submitted: {order.client_order_id} -> {broker_order_id}"
        )
        
        return broker_order_id
    
    def _submit_order_real(self, order: Order) -> str:
        """真实API提交订单"""
        if not self.binance_api:
            raise RuntimeError("Binance API client not initialized")
        
        # 转换订单类型
        order_type_map = {
            "market": "MARKET",
            "limit": "LIMIT",
        }
        binance_order_type = order_type_map.get(order.order_type.value.lower(), "MARKET")
        
        # 提交订单到Binance
        try:
            response = self.binance_api.submit_order(
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                order_type=binance_order_type,
                price=order.price,
                client_order_id=order.client_order_id,
            )
            
            broker_order_id = str(response.get("orderId", response.get("order_id", "")))
            self.order_map[order.client_order_id] = broker_order_id
            
            # 如果是市价单且立即成交，记录成交
            if response.get("status") == "FILLED":
                fill_price = float(response.get("avgPrice", response.get("price", order.price or 0.0)))
                fill_qty = float(response.get("executedQty", order.qty))
                
                fill = Fill(
                    ts_ms=int(response.get("updateTime", time.time() * 1000)),
                    symbol=order.symbol,
                    client_order_id=order.client_order_id,
                    broker_order_id=broker_order_id,
                    price=fill_price,
                    qty=fill_qty,
                    fee=float(response.get("commission", 0.0)),
                    liquidity="taker" if binance_order_type == "MARKET" else "maker",
                    side=order.side,
                )
                
                if order.client_order_id not in self.fill_map:
                    self.fill_map[order.client_order_id] = []
                self.fill_map[order.client_order_id].append(fill)
            
            logger.info(
                f"[BrokerGatewayClient] Real order submitted: {order.client_order_id} -> {broker_order_id}"
            )
            
            return broker_order_id
            
        except Exception as e:
            logger.error(f"[BrokerGatewayClient] Failed to submit real order: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """撤销订单
        
        Args:
            order_id: 订单ID（client_order_id或broker_order_id）
            symbol: 交易对（真实API需要）
            
        Returns:
            是否撤销成功
        """
        if self.mock_enabled:
            # Mock模式：查找client_order_id
            client_order_id = None
            if order_id in self.order_map:
                client_order_id = order_id
            else:
                # 反向查找broker_order_id
                for cid, bid in self.order_map.items():
                    if bid == order_id:
                        client_order_id = cid
                        break
            
            if not client_order_id:
                return False
            
            # Mock模式下，如果已成交则无法撤销
            if client_order_id in self.fill_map and len(self.fill_map[client_order_id]) > 0:
                logger.warning(f"[BrokerGatewayClient] Cannot cancel filled order: {client_order_id}")
                return False
            
            # 从映射中移除
            del self.order_map[client_order_id]
            
            logger.info(f"[BrokerGatewayClient] Mock order canceled: {client_order_id}")
            return True
        else:
            # 真实API模式
            if not self.binance_api:
                raise RuntimeError("Binance API client not initialized")
            
            if not symbol:
                # 尝试从order_map查找symbol
                for cid, bid in self.order_map.items():
                    if cid == order_id or bid == order_id:
                        # 需要从订单对象获取symbol，这里简化处理
                        logger.warning("[BrokerGatewayClient] Symbol required for real API cancel")
                        return False
            
            try:
                # 尝试作为client_order_id撤销
                self.binance_api.cancel_order(symbol=symbol, client_order_id=order_id)
                logger.info(f"[BrokerGatewayClient] Real order canceled: {order_id}")
                return True
            except Exception as e:
                logger.error(f"[BrokerGatewayClient] Failed to cancel real order: {e}")
                return False
    
    def fetch_fills(self, since_ts_ms: Optional[int] = None, symbol: Optional[str] = None) -> List[Fill]:
        """获取成交记录
        
        Args:
            since_ts_ms: 起始时间戳（ms），None表示获取所有成交
            symbol: 交易对（真实API需要）
            
        Returns:
            成交记录列表
        """
        if self.mock_enabled:
            # Mock模式：从本地缓存获取
            all_fills = []
            for fills in self.fill_map.values():
                for fill in fills:
                    if symbol and fill.symbol != symbol:
                        continue
                    if since_ts_ms is None or fill.ts_ms >= since_ts_ms:
                        all_fills.append(fill)
            
            # 按时间戳排序
            all_fills.sort(key=lambda f: f.ts_ms)
            return all_fills
        else:
            # 真实API模式：从Binance获取成交历史
            if not self.binance_api:
                raise RuntimeError("Binance API client not initialized")
            
            if not symbol:
                logger.warning("[BrokerGatewayClient] Symbol required for real API fetch_fills")
                return []
            
            try:
                trades = self.binance_api.get_trades(symbol=symbol, start_time=since_ts_ms)
                fills = []
                
                for trade in trades:
                    fill = Fill(
                        ts_ms=trade.get("time", 0),
                        symbol=trade.get("symbol", symbol),
                        client_order_id=str(trade.get("clientOrderId", "")),
                        broker_order_id=str(trade.get("id", "")),
                        price=float(trade.get("price", 0.0)),
                        qty=float(trade.get("qty", 0.0)),
                        fee=float(trade.get("commission", 0.0)),
                        liquidity="taker" if trade.get("maker", False) == False else "maker",
                        side=Side.BUY if trade.get("side") == "BUY" else Side.SELL,
                    )
                    fills.append(fill)
                
                return fills
            except Exception as e:
                logger.error(f"[BrokerGatewayClient] Failed to fetch real fills: {e}")
                return []
    
    def get_position(self, symbol: str) -> float:
        """获取持仓
        
        Args:
            symbol: 交易对
            
        Returns:
            持仓数量（正数=多头，负数=空头）
        """
        if self.mock_enabled:
            # Mock模式：从fill_map计算持仓
            position = 0.0
            for fills in self.fill_map.values():
                for fill in fills:
                    if fill.symbol == symbol:
                        if fill.side == Side.BUY:
                            position += fill.qty
                        else:
                            position -= fill.qty
            return position
        else:
            # 真实API模式：从Binance获取持仓
            if not self.binance_api:
                raise RuntimeError("Binance API client not initialized")
            
            try:
                return self.binance_api.get_position(symbol=symbol)
            except Exception as e:
                logger.error(f"[BrokerGatewayClient] Failed to get real position: {e}")
                return 0.0

