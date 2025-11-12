# -*- coding: utf-8 -*-
"""P1 Optimizations Unit Tests

测试P1优化：StrategyMode参数注入、Position交易所约束、Stops tick_size对齐
"""

import pytest
import math

from mcp.strategy_server.risk import (
    initialize_risk_manager,
    pre_order_check,
    OrderCtx,
    apply_strategy_mode_params,
    initialize_strategy_mode_injector,
)
from mcp.strategy_server.risk.stops import StopRulesManager
from mcp.strategy_server.risk.position import PositionManager


class TestStrategyModeIntegration:
    """测试StrategyMode参数注入"""
    
    def test_apply_strategy_mode_params(self):
        """测试应用StrategyMode参数"""
        base_config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                },
            }
        }
        
        initialize_risk_manager(base_config)
        initialize_strategy_mode_injector(base_config)
        
        # 应用active模式的参数
        mode_params = {
            "risk": {
                "guards": {
                    "spread_bps_max": 10.0,  # active模式放宽价差
                    "activity_min_tpm": 5.0,  # active模式降低活跃度要求
                },
                "position": {
                    "max_notional_usd": 30000.0,  # active模式提高名义额
                },
            }
        }
        
        success, duration = apply_strategy_mode_params("active", mode_params)
        
        assert success is True
        assert duration >= 0
        
        # 验证参数已应用（通过检查新的订单）
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 9.0,  # 超过8.0但不超过10.0（active模式）
                "event_lag_sec": 0.04,
                "activity_tpm": 6.0,  # 低于10.0但超过5.0（active模式）
            },
        )
        
        decision = pre_order_check(order_ctx)
        # 在active模式下应该通过（spread_bps_max=10.0, activity_min_tpm=5.0）
        assert decision.passed is True, f"Decision failed with reasons: {decision.reason_codes}"


class TestExchangeFilters:
    """测试交易所Filter约束"""
    
    def test_check_exchange_filters_min_notional(self):
        """测试检查最小名义额"""
        config = {
            "position": {
                "exchange_filters": {
                    "BTCUSDT": {
                        "min_notional": 10.0,
                        "step_size": 0.001,
                        "tick_size": 0.01,
                    },
                },
            }
        }
        
        manager = PositionManager(config)
        
        # 测试名义额低于最小值
        reasons, adjustments = manager.check_exchange_filters("BTCUSDT", 0.0001, 50000.0)
        # 0.0001 * 50000 = 5.0 < 10.0
        assert "notional_below_min" in reasons
        assert "min_qty" in adjustments
        
        # 测试名义额满足最小值
        reasons, adjustments = manager.check_exchange_filters("BTCUSDT", 0.0002, 50000.0)
        # 0.0002 * 50000 = 10.0 >= 10.0
        assert "notional_below_min" not in reasons
    
    def test_check_exchange_filters_step_size(self):
        """测试检查步长对齐"""
        config = {
            "position": {
                "exchange_filters": {
                    "BTCUSDT": {
                        "step_size": 0.001,
                    },
                },
            }
        }
        
        manager = PositionManager(config)
        
        # 测试数量未对齐到step_size
        reasons, adjustments = manager.check_exchange_filters("BTCUSDT", 0.00015, 50000.0)
        # 0.00015 不是 0.001 的倍数
        assert "qty_not_aligned_to_step_size" in reasons
        assert "aligned_qty" in adjustments
        assert adjustments["aligned_qty"] == 0.000  # 向下取整到0.001的倍数
        
        # 测试数量已对齐
        reasons, adjustments = manager.check_exchange_filters("BTCUSDT", 0.001, 50000.0)
        assert "qty_not_aligned_to_step_size" not in reasons
    
    def test_check_exchange_filters_tick_size(self):
        """测试检查TickSize对齐"""
        config = {
            "position": {
                "exchange_filters": {
                    "BTCUSDT": {
                        "tick_size": 0.01,
                    },
                },
            }
        }
        
        manager = PositionManager(config)
        
        # 测试价格未对齐到tick_size
        reasons, adjustments = manager.check_exchange_filters("BTCUSDT", 0.1, 50000.123)
        # 50000.123 不是 0.01 的倍数
        assert "price_not_aligned_to_tick_size" in reasons
        assert "aligned_price" in adjustments
        assert adjustments["aligned_price"] == 50000.12  # 对齐到0.01的倍数
        
        # 测试价格已对齐
        reasons, adjustments = manager.check_exchange_filters("BTCUSDT", 0.1, 50000.12)
        assert "price_not_aligned_to_tick_size" not in reasons


class TestTickSizeAlignment:
    """测试tick_size对齐"""
    
    def test_calculate_price_cap_with_tick_size(self):
        """测试限价上限对齐到tick_size"""
        config = {
            "stop_rules": {
                "tick_size": 0.01,  # BTCUSDT的tick_size
            }
        }
        
        manager = StopRulesManager(config)
        
        # 买单：限价上限应该对齐到tick_size
        price_cap = manager.calculate_price_cap("buy", 50000.0, 10.0, align_to_tick=True)
        # 50000.0 * (1 + 10/10000) = 50050.0，应该对齐到0.01的倍数
        assert abs(price_cap - 50050.0) < 1e-6  # 允许浮点数精度误差
        
        # 测试需要对齐的情况
        price_cap = manager.calculate_price_cap("buy", 50000.123, 10.0, align_to_tick=True)
        # 50000.123 * (1 + 10/10000) = 50050.123123，应该四舍五入到0.01的倍数
        expected = round(50050.123123 / 0.01) * 0.01
        assert abs(price_cap - expected) < 1e-6
    
    def test_calculate_price_cap_without_tick_size(self):
        """测试没有tick_size时不对齐"""
        config = {
            "stop_rules": {}
        }
        
        manager = StopRulesManager(config)
        
        price_cap = manager.calculate_price_cap("buy", 50000.123, 10.0, align_to_tick=True)
        # 没有tick_size，应该返回原始计算结果
        expected = 50000.123 * (1 + 10.0 / 10000)
        assert abs(price_cap - expected) < 1e-6


class TestPositionWithExchangeFilters:
    """测试Position与交易所约束一体化"""
    
    def test_check_all_with_exchange_filters(self):
        """测试check_all包含交易所Filter约束"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "exchange_filters": {
                    "BTCUSDT": {
                        "min_notional": 10.0,
                        "step_size": 0.001,
                        "tick_size": 0.01,
                    },
                },
            }
        }
        
        manager = PositionManager(config)
        
        # 测试：数量未对齐到step_size，但名义额满足
        reasons, adjustments = manager.check_all("BTCUSDT", 0.00015, 50000.0)
        # 0.00015 未对齐到 0.001（round(0.00015/0.001)*0.001 = 0.000）
        assert "qty_not_aligned_to_step_size" in reasons
        assert "aligned_qty" in adjustments
        # 对齐后的数量应该是0.000（向下取整）或0.001（四舍五入），这里使用round所以是0.000
        
        # 测试：名义额超过限制，同时数量未对齐
        reasons, adjustments = manager.check_all("BTCUSDT", 0.5, 50000.0)
        # 0.5 * 50000 = 25000 > 20000
        assert "notional_exceeds_limit" in reasons
        assert "max_qty" in adjustments
        # max_qty应该是20000/50000=0.4，但也要考虑step_size对齐
        assert adjustments["max_qty"] == 0.4

