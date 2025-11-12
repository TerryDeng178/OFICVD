# -*- coding: utf-8 -*-
"""Risk Module Unit Tests

测试 mcp/strategy_server/risk/ 模块的各个组件
"""

import pytest
import time
from pathlib import Path
from typing import Dict

from mcp.strategy_server.risk.schemas import OrderCtx, RiskDecision
from mcp.strategy_server.risk.guards import GuardChecker
from mcp.strategy_server.risk.position import PositionManager
from mcp.strategy_server.risk.stops import StopRulesManager
from mcp.strategy_server.risk.precheck import RiskManager, initialize_risk_manager, pre_order_check
from mcp.strategy_server.risk.shadow import ShadowComparator


class TestGuardChecker:
    """测试护栏检查器"""
    
    def test_check_spread_pass(self):
        """测试价差检查通过"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        passed, reason = checker.check_spread(5.0)
        assert passed is True
        assert reason is None
    
    def test_check_spread_fail(self):
        """测试价差检查失败"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        passed, reason = checker.check_spread(10.0)
        assert passed is False
        assert reason == "spread_too_wide"
    
    def test_check_lag_pass(self):
        """测试延迟检查通过"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        passed, reason = checker.check_lag(1.0)
        assert passed is True
        assert reason is None
    
    def test_check_lag_fail(self):
        """测试延迟检查失败"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        passed, reason = checker.check_lag(2.0)
        assert passed is False
        assert reason == "lag_exceeds_cap"
    
    def test_check_activity_pass(self):
        """测试活跃度检查通过"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        passed, reason = checker.check_activity(15.0)
        assert passed is True
        assert reason is None
    
    def test_check_activity_fail(self):
        """测试活跃度检查失败"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        passed, reason = checker.check_activity(5.0)
        assert passed is False
        assert reason == "market_inactive"
    
    def test_check_all_pass(self):
        """测试所有护栏检查通过"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        guards = {
            "spread_bps": 5.0,
            "event_lag_sec": 1.0,
            "activity_tpm": 15.0,
        }
        reasons = checker.check_all(guards)
        assert len(reasons) == 0
    
    def test_check_all_fail_multiple(self):
        """测试多个护栏检查失败"""
        config = {
            "guards": {
                "spread_bps_max": 8.0,
                "lag_sec_cap": 1.5,
                "activity_min_tpm": 10.0,
            }
        }
        checker = GuardChecker(config)
        guards = {
            "spread_bps": 10.0,  # 超过阈值
            "event_lag_sec": 2.0,  # 超过阈值
            "activity_tpm": 5.0,  # 低于阈值
        }
        reasons = checker.check_all(guards)
        assert len(reasons) == 3
        assert "spread_too_wide" in reasons
        assert "lag_exceeds_cap" in reasons
        assert "market_inactive" in reasons


class TestPositionManager:
    """测试仓位管理器"""
    
    def test_check_notional_pass(self):
        """测试名义额检查通过"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "max_leverage": 5.0,
                "symbol_limits": {},
            }
        }
        manager = PositionManager(config)
        passed, reason, max_qty = manager.check_notional("BTCUSDT", 0.1, 50000.0)
        assert passed is True
        assert reason is None
        assert max_qty is None
    
    def test_check_notional_fail(self):
        """测试名义额检查失败"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "max_leverage": 5.0,
                "symbol_limits": {},
            }
        }
        manager = PositionManager(config)
        passed, reason, max_qty = manager.check_notional("BTCUSDT", 1.0, 50000.0)
        assert passed is False
        assert reason == "notional_exceeds_limit"
        assert max_qty == 0.4  # 20000 / 50000
    
    def test_check_symbol_limit_pass(self):
        """测试单币种限制检查通过"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "max_leverage": 5.0,
                "symbol_limits": {
                    "BTCUSDT": {"max_qty": 0.5},
                },
            }
        }
        manager = PositionManager(config)
        passed, reason, max_qty = manager.check_symbol_limit("BTCUSDT", 0.3)
        assert passed is True
        assert reason is None
        assert max_qty is None
    
    def test_check_symbol_limit_fail(self):
        """测试单币种限制检查失败"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "max_leverage": 5.0,
                "symbol_limits": {
                    "BTCUSDT": {"max_qty": 0.5},
                },
            }
        }
        manager = PositionManager(config)
        passed, reason, max_qty = manager.check_symbol_limit("BTCUSDT", 0.6)
        assert passed is False
        assert reason == "symbol_qty_exceeds_limit"
        assert max_qty == 0.5
    
    def test_check_all_pass(self):
        """测试所有仓位检查通过"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "max_leverage": 5.0,
                "symbol_limits": {
                    "BTCUSDT": {"max_qty": 0.5},
                },
            }
        }
        manager = PositionManager(config)
        reasons, adjustments = manager.check_all("BTCUSDT", 0.1, 50000.0)
        assert len(reasons) == 0
        assert len(adjustments) == 0
    
    def test_check_all_fail_both(self):
        """测试名义额和单币种限制都失败"""
        config = {
            "position": {
                "max_notional_usd": 20000.0,
                "max_leverage": 5.0,
                "symbol_limits": {
                    "BTCUSDT": {"max_qty": 0.3},
                },
            }
        }
        manager = PositionManager(config)
        # 数量0.5超过单币种限制0.3，名义额50000*0.5=25000超过20000
        reasons, adjustments = manager.check_all("BTCUSDT", 0.5, 50000.0)
        assert len(reasons) == 2
        assert "notional_exceeds_limit" in reasons
        assert "symbol_qty_exceeds_limit" in reasons
        # 应该取较小的max_qty
        assert adjustments["max_qty"] == 0.3


class TestStopRulesManager:
    """测试止损/止盈规则管理器"""
    
    def test_calculate_price_cap_buy(self):
        """测试买单限价上限计算"""
        config = {
            "stop_rules": {
                "take_profit_bps": 40.0,
                "stop_loss_bps": 25.0,
            }
        }
        manager = StopRulesManager(config)
        price_cap = manager.calculate_price_cap("buy", 50000.0, 10.0)
        assert price_cap == 50000.0 * (1 + 10.0 / 10000)
    
    def test_calculate_price_cap_sell(self):
        """测试卖单限价上限计算"""
        config = {
            "stop_rules": {
                "take_profit_bps": 40.0,
                "stop_loss_bps": 25.0,
            }
        }
        manager = StopRulesManager(config)
        price_cap = manager.calculate_price_cap("sell", 50000.0, 10.0)
        assert price_cap == 50000.0 * (1 - 10.0 / 10000)


class TestRiskManager:
    """测试风险管理器"""
    
    def test_pre_order_check_disabled(self):
        """测试风控未启用时直接通过"""
        config = {
            "risk": {
                "enabled": False,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
            }
        }
        manager = RiskManager(config)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
        )
        decision = manager.pre_order_check(order_ctx)
        assert decision.passed is True
        assert len(decision.reason_codes) == 0
    
    def test_pre_order_check_enabled_pass(self):
        """测试风控启用且通过"""
        config = {
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
        manager = RiskManager(config)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 5.0,
                "event_lag_sec": 1.0,
                "activity_tpm": 15.0,
            },
        )
        decision = manager.pre_order_check(order_ctx)
        assert decision.passed is True
        assert len(decision.reason_codes) == 0
        assert decision.metrics["check_latency_ms"] >= 0
    
    def test_pre_order_check_enabled_fail_guards(self):
        """测试风控启用但护栏检查失败"""
        config = {
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
        manager = RiskManager(config)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 10.0,  # 超过阈值
                "event_lag_sec": 1.0,
                "activity_tpm": 15.0,
            },
        )
        decision = manager.pre_order_check(order_ctx)
        assert decision.passed is False
        assert "spread_too_wide" in decision.reason_codes
    
    def test_pre_order_check_enabled_fail_position(self):
        """测试风控启用但仓位检查失败"""
        config = {
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
        manager = RiskManager(config)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=1.0,  # 名义额50000超过20000
            price=50000.0,
            guards={
                "spread_bps": 5.0,
                "event_lag_sec": 1.0,
                "activity_tpm": 15.0,
            },
        )
        decision = manager.pre_order_check(order_ctx)
        assert decision.passed is False
        assert "notional_exceeds_limit" in decision.reason_codes
        assert decision.adjustments["max_qty"] == 0.4
    
    def test_pre_order_check_limit_order_price_cap(self):
        """测试限价单价格上限计算"""
        config = {
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
                "stop_rules": {
                    "take_profit_bps": 40.0,
                    "stop_loss_bps": 25.0,
                },
            }
        }
        manager = RiskManager(config)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            qty=0.1,
            price=50000.0,
            max_slippage_bps=10.0,
            guards={
                "spread_bps": 5.0,
                "event_lag_sec": 1.0,
                "activity_tpm": 15.0,
            },
        )
        decision = manager.pre_order_check(order_ctx)
        assert decision.passed is True
        assert "price_cap" in decision.adjustments
        assert decision.adjustments["price_cap"] == 50000.0 * (1 + 10.0 / 10000)


class TestGlobalPreOrderCheck:
    """测试全局pre_order_check函数"""
    
    def test_pre_order_check_not_initialized(self):
        """测试未初始化时调用pre_order_check"""
        # 重置全局实例
        import mcp.strategy_server.risk.precheck as precheck_module
        precheck_module._risk_manager = None
        
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
        )
        
        with pytest.raises(RuntimeError, match="RiskManager not initialized"):
            pre_order_check(order_ctx)
    
    def test_pre_order_check_initialized(self):
        """测试初始化后调用pre_order_check"""
        config = {
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
        initialize_risk_manager(config)
        
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 5.0,
                "event_lag_sec": 1.0,
                "activity_tpm": 15.0,
            },
        )
        
        decision = pre_order_check(order_ctx)
        assert decision.passed is True


class TestShadowComparator:
    """测试影子对比器"""
    
    def test_shadow_comparison_disabled(self):
        """测试shadow对比未启用"""
        config = {
            "risk": {
                "shadow_mode": {
                    "compare_with_legacy": False,
                    "diff_alert": ">=1%",
                }
            }
        }
        output_dir = Path("./runtime/test_shadow")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        comparator = ShadowComparator(config, output_dir)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
        )
        inline_decision = RiskDecision(passed=True)
        
        result = comparator.compare_with_legacy(order_ctx, inline_decision, None)
        assert result["parity"] is True
        assert result["legacy_passed"] is None
    
    def test_shadow_comparison_parity(self):
        """测试shadow对比一致"""
        config = {
            "risk": {
                "shadow_mode": {
                    "compare_with_legacy": True,
                    "diff_alert": ">=1%",
                }
            }
        }
        output_dir = Path("./runtime/test_shadow")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        comparator = ShadowComparator(config, output_dir)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=1730790000456,
        )
        inline_decision = RiskDecision(passed=True)
        legacy_decision = {"allow": True, "reason": []}
        
        result = comparator.compare_with_legacy(order_ctx, inline_decision, legacy_decision)
        assert result["parity"] is True
        assert result["legacy_passed"] is True
        assert inline_decision.shadow_compare["parity"] is True
    
    def test_shadow_comparison_diff(self):
        """测试shadow对比不一致"""
        config = {
            "risk": {
                "shadow_mode": {
                    "compare_with_legacy": True,
                    "diff_alert": ">=1%",
                }
            }
        }
        output_dir = Path("./runtime/test_shadow")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        comparator = ShadowComparator(config, output_dir)
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=1730790000456,
        )
        inline_decision = RiskDecision(passed=False, reason_codes=["spread_too_wide"])
        legacy_decision = {"allow": True, "reason": []}
        
        result = comparator.compare_with_legacy(order_ctx, inline_decision, legacy_decision)
        assert result["parity"] is False
        assert result["legacy_passed"] is True
        assert inline_decision.shadow_compare["parity"] is False
    
    def test_get_parity_ratio(self):
        """测试获取一致率"""
        config = {
            "risk": {
                "shadow_mode": {
                    "compare_with_legacy": True,
                    "diff_alert": ">=1%",
                }
            }
        }
        output_dir = Path("./runtime/test_shadow")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        comparator = ShadowComparator(config, output_dir)
        
        # 模拟多次比对
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=1730790000456,
        )
        
        # 10次一致，2次不一致
        for i in range(10):
            inline_decision = RiskDecision(passed=True)
            legacy_decision = {"allow": True, "reason": []}
            comparator.compare_with_legacy(order_ctx, inline_decision, legacy_decision)
        
        for i in range(2):
            inline_decision = RiskDecision(passed=False)
            legacy_decision = {"allow": True, "reason": []}
            comparator.compare_with_legacy(order_ctx, inline_decision, legacy_decision)
        
        parity_ratio = comparator.get_parity_ratio()
        assert parity_ratio == 10.0 / 12.0  # 10/12 = 0.8333...
    
    def test_generate_summary(self):
        """测试生成汇总报告"""
        config = {
            "risk": {
                "shadow_mode": {
                    "compare_with_legacy": True,
                    "diff_alert": ">=1%",
                }
            }
        }
        output_dir = Path("./runtime/test_shadow")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        comparator = ShadowComparator(config, output_dir)
        
        # 模拟比对
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=1730790000456,
        )
        
        inline_decision = RiskDecision(passed=True)
        legacy_decision = {"allow": True, "reason": []}
        comparator.compare_with_legacy(order_ctx, inline_decision, legacy_decision)
        
        summary = comparator.generate_summary()
        assert "ts" in summary
        assert summary["total_checks"] == 1
        assert summary["parity_count"] == 1
        assert summary["diff_count"] == 0
        assert summary["parity_ratio"] == 1.0


class TestOrderCtxSchema:
    """测试OrderCtx数据契约"""
    
    def test_order_ctx_creation(self):
        """测试OrderCtx创建"""
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=1730790000456,
            regime="active",
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
            context={
                "fees_bps": 4.0,
                "maker_ratio_target": 0.6,
                "recent_pnl": 100.0,
            },
        )
        assert order_ctx.symbol == "BTCUSDT"
        assert order_ctx.side == "buy"
        assert order_ctx.order_type == "market"
        assert order_ctx.qty == 0.1
        assert order_ctx.price == 50000.0
        assert order_ctx.guards["spread_bps"] == 1.2
        assert order_ctx.context["fees_bps"] == 4.0
    
    def test_order_ctx_defaults(self):
        """测试OrderCtx默认值"""
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
        )
        assert order_ctx.price is None
        assert order_ctx.account_mode == "isolated"
        assert order_ctx.max_slippage_bps == 10.0
        assert order_ctx.ts_ms == 0
        assert order_ctx.regime == "normal"
        assert "spread_bps" in order_ctx.guards
        assert "fees_bps" in order_ctx.context


class TestRiskDecisionSchema:
    """测试RiskDecision数据契约"""
    
    def test_risk_decision_creation(self):
        """测试RiskDecision创建"""
        decision = RiskDecision(
            passed=True,
            reason_codes=[],
            adjustments={"max_qty": None, "price_cap": None},
            metrics={"check_latency_ms": 1.5},
            shadow_compare={"legacy_passed": True, "parity": True},
        )
        assert decision.passed is True
        assert len(decision.reason_codes) == 0
        assert decision.metrics["check_latency_ms"] == 1.5
        assert decision.shadow_compare["parity"] is True
    
    def test_risk_decision_defaults(self):
        """测试RiskDecision默认值"""
        decision = RiskDecision(passed=False)
        assert decision.passed is False
        assert len(decision.reason_codes) == 0
        assert decision.adjustments["max_qty"] is None
        assert decision.metrics["check_latency_ms"] == 0.0
        assert decision.shadow_compare["parity"] is False

