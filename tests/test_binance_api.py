# -*- coding: utf-8 -*-
"""Binance API Tests

测试Binance Futures API客户端（Mock测试，不实际调用API）
"""

import pytest
from unittest.mock import Mock, patch

from alpha_core.executors.binance_api import BinanceFuturesAPI
from alpha_core.executors import Side, Order


@pytest.fixture
def mock_api():
    """Mock Binance API客户端（禁用SDK，使用自定义实现）"""
    with patch("alpha_core.executors.binance_api.requests") as mock_requests:
        with patch("alpha_core.executors.binance_api.PYTHON_BINANCE_AVAILABLE", False):
            api = BinanceFuturesAPI(
                api_key="test_key",
                secret_key="test_secret",
                testnet=True,
                use_sdk=False  # 禁用SDK，使用自定义实现进行测试
            )
            api._request = Mock()  # Mock _request方法
            yield api


class TestBinanceFuturesAPI:
    """测试Binance Futures API"""
    
    def test_init(self):
        """测试初始化（禁用SDK）"""
        with patch("alpha_core.executors.binance_api.PYTHON_BINANCE_AVAILABLE", False):
            api = BinanceFuturesAPI(
                api_key="test_key",
                secret_key="test_secret",
                testnet=True,
                use_sdk=False  # 禁用SDK
            )
            
            assert api.api_key == "test_key"
            assert api.secret_key == "test_secret"
            assert api.testnet is True
            assert api.base_url == BinanceFuturesAPI.TESTNET_BASE_URL
            assert api.use_sdk is False
    
    def test_init_live(self):
        """测试实盘初始化（禁用SDK）"""
        with patch("alpha_core.executors.binance_api.PYTHON_BINANCE_AVAILABLE", False):
            api = BinanceFuturesAPI(
                api_key="test_key",
                secret_key="test_secret",
                testnet=False,
                use_sdk=False  # 禁用SDK
            )
            
            assert api.testnet is False
            assert api.base_url == BinanceFuturesAPI.LIVE_BASE_URL
            assert api.use_sdk is False
    
    def test_generate_signature(self):
        """测试签名生成（禁用SDK）"""
        with patch("alpha_core.executors.binance_api.PYTHON_BINANCE_AVAILABLE", False):
            api = BinanceFuturesAPI("test_key", "test_secret", testnet=True, use_sdk=False)
            
            params = {"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.1}
            signature = api._generate_signature(params)
            
            assert isinstance(signature, str)
            assert len(signature) == 64  # SHA256 hex string length
    
    def test_submit_order_market(self, mock_api):
        """测试提交市价单"""
        mock_api._request.return_value = {
            "orderId": 12345,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "avgPrice": "50000.0",
            "executedQty": "0.1",
            "commission": "0.001",
            "updateTime": 1731379200000,
        }
        
        response = mock_api.submit_order(
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            order_type="MARKET",
        )
        
        assert response["orderId"] == 12345
        assert response["status"] == "FILLED"
        mock_api._request.assert_called_once()
    
    def test_submit_order_limit(self, mock_api):
        """测试提交限价单"""
        mock_api._request.return_value = {
            "orderId": 12346,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "price": "50000.0",
        }
        
        response = mock_api.submit_order(
            symbol="BTCUSDT",
            side=Side.SELL,
            qty=0.1,
            order_type="LIMIT",
            price=50000.0,
        )
        
        assert response["orderId"] == 12346
        assert response["status"] == "NEW"
    
    def test_cancel_order(self, mock_api):
        """测试撤销订单"""
        mock_api._request.return_value = {
            "orderId": 12345,
            "symbol": "BTCUSDT",
            "status": "CANCELED",
        }
        
        response = mock_api.cancel_order(
            symbol="BTCUSDT",
            order_id=12345
        )
        
        assert response["status"] == "CANCELED"
        mock_api._request.assert_called_once()
    
    def test_get_position(self, mock_api):
        """测试获取持仓"""
        mock_api._request.return_value = {
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "positionAmt": "0.5",
                },
                {
                    "symbol": "ETHUSDT",
                    "positionAmt": "-0.3",
                },
            ]
        }
        
        position = mock_api.get_position("BTCUSDT")
        
        assert position == 0.5
    
    def test_get_trades(self, mock_api):
        """测试获取成交历史"""
        mock_api._request.return_value = [
            {
                "id": 1001,
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": "50000.0",
                "qty": "0.1",
                "commission": "0.001",
                "time": 1731379200000,
                "maker": False,
                "clientOrderId": "test-123",
            }
        ]
        
        trades = mock_api.get_trades(symbol="BTCUSDT", limit=10)
        
        assert len(trades) == 1
        assert trades[0]["symbol"] == "BTCUSDT"
        assert trades[0]["side"] == "BUY"

