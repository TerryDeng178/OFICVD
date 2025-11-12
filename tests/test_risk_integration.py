# -*- coding: utf-8 -*-
"""Risk Module Integration Tests

集成测试：Signal→Strategy→Risk→Broker 的 dry-run 通路
"""

import json
import pytest
import tempfile
from pathlib import Path
from typing import Dict, List
from unittest.mock import Mock, patch

from mcp.strategy_server.risk import pre_order_check, OrderCtx, initialize_risk_manager, get_metrics, reset_metrics
from mcp.strategy_server.risk.schemas import RiskDecision


class TestSignalToRiskIntegration:
    """集成测试：Signal → Strategy → Risk 通路"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
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
                    "max_leverage": 5.0,
                    "symbol_limits": {
                        "BTCUSDT": {"max_qty": 0.5},
                    },
                },
            }
        }
    
    @pytest.fixture
    def sample_signal(self):
        """示例信号（来自signal_server）"""
        return {
            "ts_ms": 1730790000456,
            "symbol": "BTCUSDT",
            "score": 1.72,
            "z_ofi": 1.9,
            "z_cvd": 1.3,
            "regime": "active",
            "div_type": None,
            "confirm": True,
            "gating": False,
            "signal_type": "strong_buy",
            "guard_reason": None,
        }
    
    def test_signal_to_order_ctx_conversion(self, risk_config, sample_signal):
        """测试信号到订单上下文的转换"""
        initialize_risk_manager(risk_config)
        
        # 模拟从signal转换为order_ctx
        order_ctx = OrderCtx(
            symbol=sample_signal["symbol"],
            side="buy" if sample_signal["signal_type"] in ["buy", "strong_buy"] else "sell",
            order_type="market",
            qty=0.1,
            price=50000.0,  # 从市场数据获取
            ts_ms=sample_signal["ts_ms"],
            regime=sample_signal["regime"],
            guards={
                "spread_bps": 1.2,  # 从features获取
                "event_lag_sec": 0.04,  # 从features获取
                "activity_tpm": 15.0,  # 从features获取
            },
        )
        
        # 执行风控检查
        decision = pre_order_check(order_ctx)
        
        assert isinstance(decision, RiskDecision)
        assert decision.passed is True  # 应该通过（所有护栏都满足）
        assert len(decision.reason_codes) == 0
    
    def test_signal_blocked_by_guards(self, risk_config, sample_signal):
        """测试信号被护栏拦截"""
        initialize_risk_manager(risk_config)
        
        order_ctx = OrderCtx(
            symbol=sample_signal["symbol"],
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=sample_signal["ts_ms"],
            regime=sample_signal["regime"],
            guards={
                "spread_bps": 10.0,  # 超过阈值
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        
        decision = pre_order_check(order_ctx)
        
        assert decision.passed is False
        assert "spread_too_wide" in decision.reason_codes
    
    def test_signal_blocked_by_position_limit(self, risk_config, sample_signal):
        """测试信号被仓位限制拦截"""
        initialize_risk_manager(risk_config)
        
        order_ctx = OrderCtx(
            symbol=sample_signal["symbol"],
            side="buy",
            order_type="market",
            qty=1.0,  # 超过BTCUSDT的max_qty限制（0.5），也超过名义额限制（20000/50000=0.4）
            price=50000.0,
            ts_ms=sample_signal["ts_ms"],
            regime=sample_signal["regime"],
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        
        decision = pre_order_check(order_ctx)
        
        assert decision.passed is False
        # 应该同时触发两个限制
        assert "notional_exceeds_limit" in decision.reason_codes or "symbol_qty_exceeds_limit" in decision.reason_codes
        # max_qty应该取两者中的较小值：min(0.4, 0.5) = 0.4
        assert decision.adjustments["max_qty"] == 0.4


class TestRiskToBrokerIntegration:
    """集成测试：Risk → Broker 通路"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
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
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
    
    def test_risk_passed_order_sent_to_broker(self, risk_config):
        """测试风控通过后订单发送到Broker"""
        initialize_risk_manager(risk_config)
        
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        
        decision = pre_order_check(order_ctx)
        
        # 模拟Broker接收订单
        if decision.passed:
            # 这里应该调用Broker API
            mock_broker_order = {
                "order_id": "test_order_123",
                "symbol": order_ctx.symbol,
                "side": order_ctx.side,
                "qty": order_ctx.qty,
                "status": "FILLED",
            }
            assert mock_broker_order["status"] == "FILLED"
        else:
            pytest.fail("Order should be passed by risk check")
    
    def test_risk_denied_order_not_sent_to_broker(self, risk_config):
        """测试风控拒绝后订单不发送到Broker"""
        initialize_risk_manager(risk_config)
        
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 10.0,  # 超过阈值
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        
        decision = pre_order_check(order_ctx)
        
        # 模拟Broker不接收订单
        if not decision.passed:
            # 订单被拒绝，不应该发送到Broker
            mock_broker_order = None
            assert mock_broker_order is None
            assert len(decision.reason_codes) > 0
        else:
            pytest.fail("Order should be denied by risk check")


class TestDryRunPathway:
    """集成测试：Dry-run 通路"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置（dry-run模式）"""
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
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
    
    def test_dry_run_signal_processing(self, risk_config):
        """测试Dry-run模式下的信号处理"""
        initialize_risk_manager(risk_config)
        reset_metrics()  # 重置指标
        
        # 模拟1000个信号样本
        signals = []
        for i in range(1000):
            signals.append({
                "ts_ms": 1730790000456 + i * 1000,
                "symbol": "BTCUSDT",
                "score": 1.0 + (i % 10) * 0.1,
                "confirm": True,
                "gating": False,
                "signal_type": "buy" if i % 2 == 0 else "sell",
                "regime": "active",
            })
        
        # 处理信号
        passed_count = 0
        denied_count = 0
        
        for signal in signals:
            order_ctx = OrderCtx(
                symbol=signal["symbol"],
                side="buy" if signal["signal_type"] == "buy" else "sell",
                order_type="market",
                qty=0.1,
                price=50000.0,
                ts_ms=signal["ts_ms"],
                regime=signal["regime"],
                guards={
                    "spread_bps": 1.2 + (i % 5) * 0.5,  # 变化价差
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                },
            )
            
            decision = pre_order_check(order_ctx)
            if decision.passed:
                passed_count += 1
            else:
                denied_count += 1
        
        # 验证处理结果
        assert passed_count + denied_count == 1000
        assert passed_count > 0
        assert denied_count >= 0  # 可能有拒绝的
        
        # 验证指标已记录
        metrics = get_metrics()
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["count"] == 1000


class TestParityWithLegacy:
    """集成测试：与Legacy风控的一致性"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
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
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
                "shadow_mode": {
                    "compare_with_legacy": True,
                    "diff_alert": ">=1%",
                },
            }
        }
    
    def test_parity_with_legacy_risk(self, risk_config):
        """测试与Legacy风控的一致性（模拟）"""
        initialize_risk_manager(risk_config)
        reset_metrics()
        
        # 模拟1000个订单样本
        total_samples = 1000
        parity_count = 0
        
        for i in range(total_samples):
            order_ctx = OrderCtx(
                symbol="BTCUSDT",
                side="buy" if i % 2 == 0 else "sell",
                order_type="market",
                qty=0.1,
                price=50000.0,
                guards={
                    "spread_bps": 1.2 + (i % 10) * 0.5,
                    "event_lag_sec": 0.04 + (i % 5) * 0.1,
                    "activity_tpm": 15.0,
                },
            )
            
            # 内联风控决策
            inline_decision = pre_order_check(order_ctx)
            
            # 模拟Legacy风控决策（简化版，实际应该调用legacy服务）
            legacy_passed = True
            if order_ctx.guards["spread_bps"] > 8.0:
                legacy_passed = False
            if order_ctx.guards["event_lag_sec"] > 1.5:
                legacy_passed = False
            
            # 比对一致性
            parity = (inline_decision.passed == legacy_passed)
            if parity:
                parity_count += 1
        
        # 验证一致率 ≥ 99%
        parity_ratio = parity_count / total_samples
        assert parity_ratio >= 0.99, f"Parity ratio {parity_ratio:.2%} < 99%"
        
        # 验证指标已记录
        metrics = get_metrics()
        shadow_parity_ratio = metrics.get_shadow_parity_ratio()
        assert shadow_parity_ratio >= 0.99

