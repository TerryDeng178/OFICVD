# -*- coding: utf-8 -*-
"""测试价格对齐模块

验证价格/数量对齐、名义价值验证、滑点模型
"""
import pytest

from src.alpha_core.executors.price_alignment import (
    PriceAligner,
    StaticSlippageModel,
    LinearSlippageModel,
    MakerTakerSlippageModel,
    create_slippage_model,
)
from src.alpha_core.executors.base_executor import OrderCtx, Order, Side, OrderType


class TestPriceAligner:
    """测试PriceAligner"""
    
    def test_align_price_basic(self):
        """测试基础价格对齐"""
        aligner = PriceAligner()
        
        # tick_size = 0.01
        aligned_price, price_diff = aligner.align_price(50000.123, tick_size=0.01)
        assert aligned_price == 50000.12
        assert abs(price_diff) < 0.01
    
    def test_align_price_rounding(self):
        """测试价格四舍五入"""
        aligner = PriceAligner()
        
        # 测试四舍五入
        aligned_price1, _ = aligner.align_price(50000.125, tick_size=0.01)
        assert aligned_price1 == 50000.13  # 四舍五入
        
        aligned_price2, _ = aligner.align_price(50000.124, tick_size=0.01)
        assert aligned_price2 == 50000.12  # 四舍五入
    
    def test_align_price_no_tick_size(self):
        """测试无tick_size时不对齐"""
        aligner = PriceAligner()
        
        price = 50000.123
        aligned_price, price_diff = aligner.align_price(price, tick_size=None)
        assert aligned_price == price
        assert price_diff == 0.0
    
    def test_align_quantity_basic(self):
        """测试基础数量对齐"""
        aligner = PriceAligner()
        
        # step_size = 0.001
        aligned_qty, qty_diff = aligner.align_quantity(0.001234, step_size=0.001)
        assert aligned_qty == 0.001
        assert qty_diff < 0
    
    def test_align_quantity_floor(self):
        """测试数量向下取整"""
        aligner = PriceAligner()
        
        # 测试向下取整
        aligned_qty, _ = aligner.align_quantity(0.0019, step_size=0.001)
        assert aligned_qty == 0.001  # 向下取整
        
        aligned_qty2, _ = aligner.align_quantity(0.0021, step_size=0.001)
        assert aligned_qty2 == 0.002  # 向下取整
    
    def test_align_quantity_minimum(self):
        """测试最小数量"""
        aligner = PriceAligner()
        
        # 如果向下取整后为0，应使用最小step_size
        aligned_qty, _ = aligner.align_quantity(0.0005, step_size=0.001)
        assert aligned_qty == 0.001  # 最小step_size
    
    def test_align_order_ctx(self):
        """测试OrderCtx对齐"""
        aligner = PriceAligner()
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001234,
            order_type=OrderType.LIMIT,
            price=50000.123,
            tick_size=0.01,
            step_size=0.001,
        )
        
        aligned_ctx, rounding_diff = aligner.align_order_ctx(order_ctx)
        
        assert aligned_ctx.qty == 0.001
        assert aligned_ctx.price == 50000.12
        assert "qty_diff" in rounding_diff
        assert "price_diff" in rounding_diff
    
    def test_align_order_ctx_market_order(self):
        """测试市价单对齐（只对齐数量，不对齐价格）"""
        aligner = PriceAligner()
        
        order_ctx = OrderCtx(
            client_order_id="test-2",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001234,
            order_type=OrderType.MARKET,
            price=None,
            step_size=0.001,
        )
        
        aligned_ctx, rounding_diff = aligner.align_order_ctx(order_ctx)
        
        assert aligned_ctx.qty == 0.001
        assert aligned_ctx.price is None
        assert "qty_diff" in rounding_diff
        assert "price_diff" not in rounding_diff
    
    def test_align_order(self):
        """测试Order对齐（向后兼容）"""
        aligner = PriceAligner()
        
        order = Order(
            client_order_id="test-3",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001234,
            order_type=OrderType.LIMIT,
            price=50000.123,
        )
        
        aligned_order, rounding_diff = aligner.align_order(order, tick_size=0.01, step_size=0.001)
        
        assert aligned_order.qty == 0.001
        assert aligned_order.price == 50000.12
        assert "qty_diff" in rounding_diff
        assert "price_diff" in rounding_diff
    
    def test_validate_notional_pass(self):
        """测试名义价值验证通过"""
        aligner = PriceAligner()
        
        passed, reason, suggested_qty = aligner.validate_notional(
            qty=0.001,
            price=50000.0,
            min_notional=10.0,
        )
        
        assert passed is True
        assert reason is None
        assert suggested_qty is None
    
    def test_validate_notional_fail(self):
        """测试名义价值验证失败"""
        aligner = PriceAligner()
        
        passed, reason, suggested_qty = aligner.validate_notional(
            qty=0.0001,
            price=50000.0,
            min_notional=10.0,
        )
        
        assert passed is False
        assert reason == "notional_below_minimum"
        assert suggested_qty is not None
        assert suggested_qty * 50000.0 >= 10.0


class TestSlippageModel:
    """测试滑点模型"""
    
    def test_static_slippage_model(self):
        """测试静态滑点模型"""
        model = StaticSlippageModel(slippage_bps=1.5)
        
        order_ctx = OrderCtx(
            client_order_id="test",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        slippage = model.calculate_slippage_bps(order_ctx, {})
        assert slippage == 1.5
    
    def test_linear_slippage_model(self):
        """测试线性滑点模型"""
        model = LinearSlippageModel(base_slippage_bps=1.0, spread_coeff=0.5, vol_coeff=0.3)
        
        order_ctx = OrderCtx(
            client_order_id="test",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        market_data = {
            "spread_bps": 2.0,
            "vol_bps": 1.0,
        }
        
        slippage = model.calculate_slippage_bps(order_ctx, market_data)
        # 1.0 + 0.5 * 2.0 + 0.3 * 1.0 = 2.3
        assert slippage >= 2.0
    
    def test_maker_taker_slippage_model(self):
        """测试Maker/Taker滑点模型"""
        model = MakerTakerSlippageModel(maker_slippage_bps=0.1, taker_slippage_bps=1.0)
        
        # 限价单（maker）
        limit_order = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            order_type=OrderType.LIMIT,
        )
        
        slippage_maker = model.calculate_slippage_bps(limit_order, {})
        assert slippage_maker == 0.1
        
        # 市价单（taker）
        market_order = OrderCtx(
            client_order_id="test-2",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            order_type=OrderType.MARKET,
        )
        
        slippage_taker = model.calculate_slippage_bps(market_order, {})
        assert slippage_taker == 1.0
    
    def test_create_slippage_model_static(self):
        """测试创建静态滑点模型"""
        model = create_slippage_model("static", {"slippage_bps": 2.0})
        assert isinstance(model, StaticSlippageModel)
        assert model.slippage_bps == 2.0
    
    def test_create_slippage_model_linear(self):
        """测试创建线性滑点模型"""
        model = create_slippage_model("linear", {
            "base_slippage_bps": 1.0,
            "spread_coeff": 0.5,
            "vol_coeff": 0.3,
        })
        assert isinstance(model, LinearSlippageModel)
    
    def test_create_slippage_model_maker_taker(self):
        """测试创建Maker/Taker滑点模型"""
        model = create_slippage_model("maker_taker", {
            "maker_slippage_bps": 0.1,
            "taker_slippage_bps": 1.0,
        })
        assert isinstance(model, MakerTakerSlippageModel)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

