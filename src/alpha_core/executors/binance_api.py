# -*- coding: utf-8 -*-
"""Binance Futures API Client

Binance期货API客户端：支持测试网和实盘
使用 python-binance SDK 进行交易，避免签名错误
"""

import hashlib
import hmac
import json
import logging
import math
import os
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from binance.client import Client as BinanceClient
    PYTHON_BINANCE_AVAILABLE = True
except ImportError:
    PYTHON_BINANCE_AVAILABLE = False
    BinanceClient = None

from .base_executor import Order, Fill, Side

logger = logging.getLogger(__name__)


class BinanceFuturesAPI:
    """Binance期货API客户端"""
    
    # 测试网和实盘的基础URL
    # 注意：Binance期货测试网使用 testnet.binancefuture.com
    # demo.binance.com 是演示网站，不支持期货API
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"  # Binance期货测试网域名
    LIVE_BASE_URL = "https://fapi.binance.com"
    
    def __init__(self, api_key: str, secret_key: str, testnet: bool = True, use_sdk: bool = True):
        """初始化Binance API客户端
        
        Args:
            api_key: API密钥
            secret_key: 密钥
            testnet: 是否使用测试网
            use_sdk: 是否使用 python-binance SDK（默认True，推荐使用SDK避免签名错误）
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        self.base_url = self.TESTNET_BASE_URL if testnet else self.LIVE_BASE_URL
        self.use_sdk = use_sdk and PYTHON_BINANCE_AVAILABLE
        
        # 优先使用 python-binance SDK
        if self.use_sdk:
            if not PYTHON_BINANCE_AVAILABLE:
                logger.warning("[BinanceAPI] python-binance未安装，回退到自定义实现")
                logger.warning("[BinanceAPI] 建议安装: pip install python-binance")
                self.use_sdk = False
            else:
                try:
                    self.binance_client = BinanceClient(api_key, secret_key, testnet=testnet)
                    logger.info(f"[BinanceAPI] Using python-binance SDK: testnet={testnet}")
                except Exception as e:
                    logger.warning(f"[BinanceAPI] Failed to initialize python-binance SDK: {e}")
                    logger.warning("[BinanceAPI] Falling back to custom implementation")
                    self.use_sdk = False
        
        # 如果未使用SDK，需要requests库
        if not self.use_sdk:
            if not REQUESTS_AVAILABLE:
                raise ImportError("requests库未安装，请运行: pip install requests")
            logger.info(f"[BinanceAPI] Using custom implementation: testnet={testnet}, base_url={self.base_url}")
        
        if not testnet:
            logger.warning("[BinanceAPI] WARNING: LIVE TRADING MODE - Real money at risk!")
            logger.warning("[BinanceAPI] Please ensure you have proper risk controls in place.")
    
    def _generate_signature(self, params: Dict) -> str:
        """生成API签名
        
        Args:
            params: 请求参数字典
            
        Returns:
            HMAC-SHA256签名（十六进制字符串）
        """
        # 移除signature字段（如果存在）
        params_clean = {k: v for k, v in params.items() if k != "signature"}
        # 确保所有值都是字符串（Binance API要求）
        params_str = {k: str(v) for k, v in params_clean.items()}
        # 按key排序并生成query string
        # 使用urlencode确保正确的URL编码（与Binance API要求一致）
        query_string = urlencode(sorted(params_str.items()))
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, signed: bool = True) -> Dict:
        """发送API请求
        
        Args:
            method: HTTP方法（GET/POST/DELETE）
            endpoint: API端点（如 /fapi/v1/order）
            params: 请求参数
            signed: 是否需要签名
            
        Returns:
            API响应（JSON字典）
        """
        if params is None:
            params = {}
        
        url = f"{self.base_url}{endpoint}"
        headers = {
            "X-MBX-APIKEY": self.api_key,
        }
        
        # 添加时间戳
        timestamp = int(time.time() * 1000)
        
        # 如果需要签名，生成签名
        if signed:
            if method.upper() == "POST":
                # POST请求：参数在body中，timestamp在query string中
                # 签名基于body中的所有参数（不包括timestamp）+ query string中的timestamp
                # 根据Binance API文档，POST请求的签名应该基于body中的所有参数（转换为query string格式）
                # 但timestamp和signature放在query string中
                body_params = params.copy()
                # 签名基于body中的所有参数（转换为query string格式）+ timestamp
                signature_params = body_params.copy()
                signature_params["timestamp"] = timestamp
                signature = self._generate_signature(signature_params)
                
                headers["Content-Type"] = "application/json"
                query_params = {"timestamp": timestamp, "signature": signature}
                response = requests.post(
                    url,
                    json=body_params,  # body中不包含timestamp
                    params=query_params,  # query string中包含timestamp和signature
                    headers=headers,
                    timeout=10
                )
            else:
                # GET/DELETE请求：所有参数（包括timestamp和signature）都在query string中
                params["timestamp"] = timestamp
                signature = self._generate_signature(params)
                params["signature"] = signature
                response = requests.request(
                    method.upper(),
                    url,
                    params=params,
                    headers=headers,
                    timeout=10
                )
        else:
            # 不需要签名的请求
            if method.upper() == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method.upper() == "POST":
                headers["Content-Type"] = "application/json"
                response = requests.post(url, json=params, headers=headers, timeout=10)
            elif method.upper() == "DELETE":
                response = requests.delete(url, params=params, headers=headers, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        
        try:
            response.raise_for_status()
            # 检查响应内容
            content_type = response.headers.get("Content-Type", "")
            # 尝试解析JSON
            try:
                return response.json()
            except ValueError:
                # 如果不是JSON，检查是否是简单的文本响应（如ping返回"ok"）
                text_response = response.text.strip()
                if text_response == "ok" or text_response == "{}":
                    return {}
                logger.error(f"[BinanceAPI] Non-JSON response: Content-Type={content_type}, Text={text_response[:200]}")
                raise ValueError(f"Non-JSON response: {text_response[:200]}")
        except requests.exceptions.RequestException as e:
            logger.error(f"[BinanceAPI] Request failed: {e}")
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_data = e.response.json()
                    logger.error(f"[BinanceAPI] Error response: {error_data}")
                except:
                    logger.error(f"[BinanceAPI] Error response text: {e.response.text[:500]}")
                    logger.error(f"[BinanceAPI] Response status: {e.response.status_code}")
                    logger.error(f"[BinanceAPI] Response headers: {dict(e.response.headers)}")
            raise
    
    def submit_order(
        self,
        symbol: str,
        side: Side,
        qty: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict:
        """提交订单
        
        Args:
            symbol: 交易对（如BTCUSDT）
            side: 方向（BUY/SELL）
            qty: 数量
            order_type: 订单类型（MARKET/LIMIT）
            price: 限价单价格（限价单必需）
            client_order_id: 客户端订单ID（可选）
            
        Returns:
            订单响应字典
        """
        # 规范化数量：Binance BTCUSDT期货的step size是0.001，需要向下取整
        # 对于其他交易对，使用通用的精度处理
        qty_step = 0.001  # BTCUSDT期货的step size
        if "ETH" in symbol:
            qty_step = 0.01  # ETHUSDT期货的step size通常是0.01
        elif "USDT" in symbol:
            qty_step = 0.001  # 大多数USDT期货的step size是0.001
        
        # 向下取整到最近的step
        normalized_qty = math.floor(qty / qty_step) * qty_step
        # 确保至少是最小step（避免为0）
        if normalized_qty == 0.0 and qty > 0:
            normalized_qty = qty_step
        
        # 格式化数量字符串（保留3位小数）
        qty_str = f"{normalized_qty:.3f}".rstrip('0').rstrip('.')
        if not qty_str or qty_str == '0':
            qty_str = f"{qty_step:.3f}".rstrip('0').rstrip('.')
        
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                order_params = {
                    "symbol": symbol,
                    "side": side.value.upper(),
                    "type": order_type.upper(),
                    "quantity": float(qty_str),  # 使用规范化后的数量
                }
                
                if order_type.upper() == "LIMIT":
                    if price is None:
                        raise ValueError("Limit order requires price")
                    order_params["price"] = price
                    order_params["timeInForce"] = "GTC"
                
                if client_order_id:
                    order_params["newClientOrderId"] = client_order_id
                
                response = self.binance_client.futures_create_order(**order_params)
                logger.info(f"[BinanceAPI] Order submitted (SDK): {response.get('orderId')}, symbol={symbol}, side={side.value}")
                return response
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK order submission failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                # 回退到自定义实现
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        # 构建请求参数（注意：quantity需要转换为字符串，避免精度问题）
        params = {
            "symbol": symbol,
            "side": side.value.upper(),
            "type": order_type.upper(),
            "quantity": qty_str,  # 使用规范化后的数量字符串
        }
        
        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("Limit order requires price")
            params["price"] = str(price)  # 价格也需要字符串格式
            params["timeInForce"] = "GTC"
        
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        
        response = self._request("POST", "/fapi/v1/order", params, signed=True)
        logger.info(f"[BinanceAPI] Order submitted (custom): {response.get('orderId')}, symbol={symbol}, side={side.value}")
        return response
    
    def cancel_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> Dict:
        """撤销订单
        
        Args:
            symbol: 交易对
            order_id: 交易所订单ID
            client_order_id: 客户端订单ID
            
        Returns:
            撤销响应字典
        """
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                if order_id:
                    response = self.binance_client.futures_cancel_order(symbol=symbol, orderId=order_id)
                elif client_order_id:
                    response = self.binance_client.futures_cancel_order(symbol=symbol, origClientOrderId=client_order_id)
                else:
                    raise ValueError("Either order_id or client_order_id must be provided")
                logger.info(f"[BinanceAPI] Order canceled (SDK): {response.get('orderId')}, symbol={symbol}")
                return response
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK cancel order failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        params = {"symbol": symbol}
        
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")
        
        response = self._request("DELETE", "/fapi/v1/order", params, signed=True)
        logger.info(f"[BinanceAPI] Order canceled (custom): {response.get('orderId')}, symbol={symbol}")
        return response
    
    def get_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> Dict:
        """查询订单状态
        
        Args:
            symbol: 交易对
            order_id: 交易所订单ID
            client_order_id: 客户端订单ID
            
        Returns:
            订单信息字典
        """
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                if order_id:
                    return self.binance_client.futures_get_order(symbol=symbol, orderId=order_id)
                elif client_order_id:
                    return self.binance_client.futures_get_order(symbol=symbol, origClientOrderId=client_order_id)
                else:
                    raise ValueError("Either order_id or client_order_id must be provided")
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK get order failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        params = {"symbol": symbol}
        
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")
        
        response = self._request("GET", "/fapi/v1/order", params, signed=True)
        return response
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取当前挂单
        
        Args:
            symbol: 交易对（可选，None表示所有交易对）
            
        Returns:
            挂单列表
        """
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                if symbol:
                    return self.binance_client.futures_get_open_orders(symbol=symbol)
                else:
                    return self.binance_client.futures_get_open_orders()
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK get open orders failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        response = self._request("GET", "/fapi/v1/openOrders", params, signed=True)
        return response if isinstance(response, list) else [response]
    
    def get_account_info(self) -> Dict:
        """获取账户信息
        
        Returns:
            账户信息字典
        """
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                return self.binance_client.futures_account()
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK get account info failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        response = self._request("GET", "/fapi/v2/account", signed=True)
        return response
    
    def get_position(self, symbol: str) -> float:
        """获取持仓
        
        Args:
            symbol: 交易对
            
        Returns:
            持仓数量（正数=多头，负数=空头）
        """
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                positions = self.binance_client.futures_position_information(symbol=symbol)
                if positions:
                    for pos in positions:
                        if pos.get("symbol") == symbol:
                            return float(pos.get("positionAmt", 0))
                return 0.0
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK get position failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        positions = self.get_account_info().get("positions", [])
        for pos in positions:
            if pos["symbol"] == symbol:
                position_amt = float(pos["positionAmt"])
                return position_amt
        return 0.0
    
    def get_trades(self, symbol: str, limit: int = 500, start_time: Optional[int] = None) -> List[Dict]:
        """获取成交历史
        
        Args:
            symbol: 交易对
            limit: 返回数量限制
            start_time: 起始时间戳（ms）
            
        Returns:
            成交记录列表
        """
        # 优先使用 python-binance SDK
        if self.use_sdk:
            try:
                params = {"symbol": symbol, "limit": limit}
                if start_time:
                    params["startTime"] = start_time
                return self.binance_client.futures_account_trades(**params)
            except Exception as e:
                logger.error(f"[BinanceAPI] SDK get trades failed: {e}")
                logger.warning("[BinanceAPI] Falling back to custom implementation")
                self.use_sdk = False
        
        # 自定义实现（回退方案）
        params = {
            "symbol": symbol,
            "limit": limit,
        }
        
        if start_time:
            params["startTime"] = start_time
        
        response = self._request("GET", "/fapi/v1/userTrades", params, signed=True)
        return response if isinstance(response, list) else []

