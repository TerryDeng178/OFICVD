# -*- coding: utf-8 -*-
"""Base Executor Contract Tests

测试IExecutor接口契约（方法/返回/异常）
"""

import pytest
from unittest.mock import Mock

from alpha_core.executors import IExecutor, Order, Fill, Side, OrderType, OrderState


class MockExecutor(IExecutor):
    """Mock执行器用于测试接口契约"""
    
    def __init__(self):
        self._prepared = False
        self._mode = "mock"
        self._orders = {}
        self._fills = []
        self._positions = {}
    
    def prepare(self, cfg):
        self._prepared = True
        self._mode = cfg.get("executor", {}).get("mode", "mock")
    
    def submit(self, order: Order) -> str:
        if not self._prepared:
            raise RuntimeError("Executor not prepared")
        broker_order_id = f"BROKER-{order.client_order_id}"
        self._orders[order.client_order_id] = order
        return broker_order_id
    
    def cancel(self, order_id: str) -> bool:
        if order_id in self._orders:
            del self._orders[order_id]
            return True
        return False
    
    def fetch_fills(self, since_ts_ms=None):
        if since_ts_ms is None:
            return self._fills.copy()
        return [f for f in self._fills if f.ts_ms >= since_ts_ms]
    
    def get_position(self, symbol: str) -> float:
        return self._positions.get(symbol, 0.0)
    
    def close(self):
        self._prepared = False
    
    @property
    def mode(self) -> str:
        return self._mode


class TestIExecutorContract:
    """测试IExecutor接口契约"""
    
    def test_prepare(self):
        """测试prepare方法"""
        executor = MockExecutor()
        cfg = {"executor": {"mode": "test"}}
        executor.prepare(cfg)
        assert executor._prepared is True
        assert executor.mode == "test"
    
    def test_submit_order(self):
        """测试submit方法"""
        executor = MockExecutor()
        executor.prepare({"executor": {}})
        
        order = Order(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
        )
        
        broker_order_id = executor.submit(order)
        assert broker_order_id.startswith("BROKER-")
        assert order.client_order_id in executor._orders
    
    def test_submit_without_prepare(self):
        """测试未prepare时submit应该抛出异常"""
        executor = MockExecutor()
        order = Order("test-123", "BTCUSDT", Side.BUY, 0.1)
        
        with pytest.raises(RuntimeError, match="not prepared"):
            executor.submit(order)
    
    def test_cancel_order(self):
        """测试cancel方法"""
        executor = MockExecutor()
        executor.prepare({"executor": {}})
        
        order = Order("test-123", "BTCUSDT", Side.BUY, 0.1)
        executor.submit(order)
        
        result = executor.cancel("test-123")
        assert result is True
        assert "test-123" not in executor._orders
    
    def test_cancel_nonexistent_order(self):
        """测试撤销不存在的订单"""
        executor = MockExecutor()
        executor.prepare({"executor": {}})
        
        result = executor.cancel("nonexistent")
        assert result is False
    
    def test_fetch_fills(self):
        """测试fetch_fills方法"""
        executor = MockExecutor()
        executor.prepare({"executor": {}})
        
        fill1 = Fill(1000, "BTCUSDT", "order-1", price=50000.0, qty=0.1)
        fill2 = Fill(2000, "BTCUSDT", "order-2", price=51000.0, qty=0.2)
        executor._fills = [fill1, fill2]
        
        all_fills = executor.fetch_fills()
        assert len(all_fills) == 2
        
        recent_fills = executor.fetch_fills(since_ts_ms=1500)
        assert len(recent_fills) == 1
        assert recent_fills[0].ts_ms == 2000
    
    def test_get_position(self):
        """测试get_position方法"""
        executor = MockExecutor()
        executor.prepare({"executor": {}})
        
        executor._positions["BTCUSDT"] = 0.5
        executor._positions["ETHUSDT"] = -0.3
        
        assert executor.get_position("BTCUSDT") == 0.5
        assert executor.get_position("ETHUSDT") == -0.3
        assert executor.get_position("UNKNOWN") == 0.0
    
    def test_close(self):
        """测试close方法"""
        executor = MockExecutor()
        executor.prepare({"executor": {}})
        
        executor.close()
        assert executor._prepared is False
    
    def test_mode_property(self):
        """测试mode属性"""
        executor = MockExecutor()
        assert executor.mode == "mock"
        
        executor.prepare({"executor": {"mode": "backtest"}})
        assert executor.mode == "backtest"


class TestOrderDataclass:
    """测试Order数据类"""
    
    def test_order_creation(self):
        """测试Order创建"""
        order = Order(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
        )
        
        assert order.client_order_id == "test-123"
        assert order.symbol == "BTCUSDT"
        assert order.side == Side.BUY
        assert order.qty == 0.1
        assert order.order_type == OrderType.MARKET  # 默认值
        assert order.price is None  # 默认值
        assert order.ts_ms == 0  # 默认值
    
    def test_order_with_all_fields(self):
        """测试Order所有字段"""
        order = Order(
            client_order_id="test-456",
            symbol="ETHUSDT",
            side=Side.SELL,
            qty=1.0,
            order_type=OrderType.LIMIT,
            price=3000.0,
            ts_ms=1731379200000,
        )
        
        assert order.order_type == OrderType.LIMIT
        assert order.price == 3000.0
        assert order.ts_ms == 1731379200000


class TestFillDataclass:
    """测试Fill数据类"""
    
    def test_fill_creation(self):
        """测试Fill创建"""
        fill = Fill(
            ts_ms=1731379200000,
            symbol="BTCUSDT",
            client_order_id="test-123",
            price=50000.0,
            qty=0.1,
        )
        
        assert fill.ts_ms == 1731379200000
        assert fill.symbol == "BTCUSDT"
        assert fill.client_order_id == "test-123"
        assert fill.price == 50000.0
        assert fill.qty == 0.1
        assert fill.fee == 0.0  # 默认值
        assert fill.liquidity == "unknown"  # 默认值

