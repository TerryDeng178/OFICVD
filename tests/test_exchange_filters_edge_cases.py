# -*- coding: utf-8 -*-
"""Exchange Filters Edge Cases Tests

交易所约束的用例加固：最小名义额边界、数量步长溢出、价格步长溢出
"""

import pytest

from mcp.strategy_server.risk import pre_order_check, OrderCtx, initialize_risk_manager, reset_metrics


class TestExchangeFiltersEdgeCases:
    """测试交易所Filter约束的边界用例"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置（包含交易所Filter约束）"""
        return {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "exchange_filters": {
                        "BTCUSDT": {
                            "min_notional": 10.0,  # 最小名义额10 USDT
                            "step_size": 0.001,     # 数量步长0.001
                            "tick_size": 0.01,      # 价格步长0.01
                        },
                    },
                },
            }
        }
    
    def test_min_notional_boundary(self, risk_config):
        """测试最小名义额边界"""
        initialize_risk_manager(risk_config)
        
        # 测试：名义额刚好等于最小值（应该通过）
        order_ctx1 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.0002,  # 0.0002 * 50000 = 10.0 USDT（刚好等于最小值）
            price=50000.0,
            guards={"spread_bps": 1.2, "event_lag_sec": 0.04, "activity_tpm": 15.0},
        )
        decision1 = pre_order_check(order_ctx1)
        assert decision1.passed is True, "名义额等于最小值应该通过"
        
        # 测试：名义额低于最小值（应该拒绝，并给出建议数量）
        order_ctx2 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.0001,  # 0.0001 * 50000 = 5.0 USDT（低于最小值）
            price=50000.0,
            guards={"spread_bps": 1.2, "event_lag_sec": 0.04, "activity_tpm": 15.0},
        )
        decision2 = pre_order_check(order_ctx2)
        assert decision2.passed is False, "名义额低于最小值应该拒绝"
        assert "notional_below_min" in decision2.reason_codes
        assert "min_qty" in decision2.adjustments
        # 建议数量应该是 min_notional / price = 10.0 / 50000.0 = 0.0002
        assert abs(decision2.adjustments["min_qty"] - 0.0002) < 1e-6
    
    def test_step_size_overflow(self, risk_config):
        """测试数量步长溢出"""
        initialize_risk_manager(risk_config)
        
        # 测试：数量未对齐到step_size（应该拒绝，并给出对齐后的数量）
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.00015,  # 0.00015 不是 0.001 的倍数
            price=50000.0,
            guards={"spread_bps": 1.2, "event_lag_sec": 0.04, "activity_tpm": 15.0},
        )
        decision = pre_order_check(order_ctx)
        assert decision.passed is False, "数量未对齐到step_size应该拒绝"
        assert "qty_not_aligned_to_step_size" in decision.reason_codes
        assert "aligned_qty" in decision.adjustments
        # 对齐后的数量应该是 round(0.00015/0.001)*0.001 = 0.000
        assert abs(decision.adjustments["aligned_qty"] - 0.000) < 1e-6
    
    def test_tick_size_overflow(self, risk_config):
        """测试价格步长溢出"""
        initialize_risk_manager(risk_config)
        
        # 测试：价格未对齐到tick_size（应该拒绝，并给出对齐后的价格）
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            qty=0.1,
            price=50000.123,  # 50000.123 不是 0.01 的倍数
            guards={"spread_bps": 1.2, "event_lag_sec": 0.04, "activity_tpm": 15.0},
        )
        decision = pre_order_check(order_ctx)
        assert decision.passed is False, "价格未对齐到tick_size应该拒绝"
        assert "price_not_aligned_to_tick_size" in decision.reason_codes
        assert "aligned_price" in decision.adjustments
        # 对齐后的价格应该是 round(50000.123/0.01)*0.01 = 50000.12
        assert abs(decision.adjustments["aligned_price"] - 50000.12) < 1e-6
    
    def test_all_filters_violated(self, risk_config):
        """测试所有Filter约束同时违反"""
        initialize_risk_manager(risk_config)
        
        # 测试：名义额低于最小值 + 数量未对齐 + 价格未对齐
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            qty=0.00015,      # 未对齐到step_size
            price=50000.123,  # 未对齐到tick_size，且名义额低于最小值
            guards={"spread_bps": 1.2, "event_lag_sec": 0.04, "activity_tpm": 15.0},
        )
        decision = pre_order_check(order_ctx)
        assert decision.passed is False
        
        # 应该包含所有拒绝原因
        assert "notional_below_min" in decision.reason_codes
        assert "qty_not_aligned_to_step_size" in decision.reason_codes
        assert "price_not_aligned_to_tick_size" in decision.reason_codes
        
        # 应该包含所有调整建议
        assert "min_qty" in decision.adjustments
        assert "aligned_qty" in decision.adjustments
        assert "aligned_price" in decision.adjustments
        
        # 最终数量应该是min_qty和对齐数量的较大值
        if "final_qty" in decision.adjustments:
            final_qty = decision.adjustments["final_qty"]
            assert final_qty >= decision.adjustments.get("min_qty", 0)
            assert final_qty >= decision.adjustments.get("aligned_qty", 0)

