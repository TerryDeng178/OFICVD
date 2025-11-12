# -*- coding: utf-8 -*-
"""测试执行前置决策模块

验证ExecutorPrecheck和AdaptiveThrottler的功能
"""
import pytest
import time
from unittest.mock import Mock

from src.alpha_core.executors.executor_precheck import ExecutorPrecheck, AdaptiveThrottler
from src.alpha_core.executors.base_executor import OrderCtx, ExecResultStatus, Side, OrderType


class TestExecutorPrecheck:
    """测试ExecutorPrecheck"""
    
    def test_check_warmup_rejection(self):
        """测试warmup拒单"""
        precheck = ExecutorPrecheck()
        ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            warmup=True,
        )
        result = precheck.check(ctx)
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "warmup"
        assert result.client_order_id == "test-1"
    
    def test_check_guard_reason_rejection(self):
        """测试guard_reason拒单"""
        precheck = ExecutorPrecheck()
        ctx = OrderCtx(
            client_order_id="test-2",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            guard_reason="warmup,spread_too_wide",
        )
        result = precheck.check(ctx)
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason in ["warmup", "spread_too_wide"]
    
    def test_check_low_consistency_rejection(self):
        """测试低一致性拒单"""
        precheck = ExecutorPrecheck({"consistency_min": 0.15})
        ctx = OrderCtx(
            client_order_id="test-3",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            consistency=0.10,  # 低于阈值
        )
        result = precheck.check(ctx)
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "low_consistency"
    
    def test_check_consistency_throttle(self):
        """测试一致性节流"""
        precheck = ExecutorPrecheck({
            "consistency_min": 0.15,
            "consistency_throttle_threshold": 0.20,
        })
        ctx = OrderCtx(
            client_order_id="test-4",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            consistency=0.18,  # 低于节流阈值但高于最低阈值
        )
        result = precheck.check(ctx)
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "low_consistency_throttle"
    
    def test_check_weak_signal_throttle(self):
        """测试弱信号节流"""
        precheck = ExecutorPrecheck()
        ctx = OrderCtx(
            client_order_id="test-5",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            weak_signal_throttle=True,
        )
        result = precheck.check(ctx)
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "weak_signal_throttle"
    
    def test_check_accepted(self):
        """测试通过检查"""
        precheck = ExecutorPrecheck()
        ctx = OrderCtx(
            client_order_id="test-6",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            warmup=False,
            consistency=0.85,
        )
        result = precheck.check(ctx)
        assert result.status == ExecResultStatus.ACCEPTED
        assert result.reject_reason is None
    
    def test_get_stats(self):
        """测试获取统计信息"""
        precheck = ExecutorPrecheck()
        
        # 执行一些检查
        ctx1 = OrderCtx(client_order_id="test-1", symbol="BTCUSDT", side=Side.BUY, qty=0.001, warmup=True)
        precheck.check(ctx1)
        
        ctx2 = OrderCtx(client_order_id="test-2", symbol="BTCUSDT", side=Side.BUY, qty=0.001, consistency=0.10)
        precheck.check(ctx2)
        
        stats = precheck.get_stats()
        assert "deny_stats" in stats
        assert "throttle_stats" in stats
        assert stats["deny_stats"]["warmup"] >= 1
        assert stats["deny_stats"]["low_consistency"] >= 1


class TestAdaptiveThrottler:
    """测试AdaptiveThrottler"""
    
    def test_should_throttle_basic(self):
        """测试基础节流逻辑"""
        throttler = AdaptiveThrottler({
            "base_rate_limit": 10.0,
            "window_seconds": 1,
        })
        
        # 前10个请求应该通过
        for i in range(10):
            assert throttler.should_throttle() is False
        
        # 第11个请求应该被节流
        assert throttler.should_throttle() is True
    
    def test_should_throttle_with_gate_stats(self):
        """测试根据gate_reason_stats调整限速"""
        throttler = AdaptiveThrottler({
            "base_rate_limit": 10.0,
            "window_seconds": 1,
        })
        
        # 高拒绝率应该降低限速
        gate_stats = {"warmup": 100, "low_consistency": 50}
        # 模拟多次调用以触发限速调整
        for _ in range(5):
            throttler.should_throttle(gate_reason_stats=gate_stats)
        
        # 限速应该降低
        assert throttler.get_current_rate_limit() < 10.0
    
    def test_should_throttle_with_market_activity(self):
        """测试根据市场活跃度调整限速"""
        throttler = AdaptiveThrottler({
            "base_rate_limit": 10.0,
            "window_seconds": 1,
        })
        
        # 安静市场应该降低限速
        throttler.should_throttle(market_activity="quiet")
        assert throttler.get_current_rate_limit() < 10.0
        
        # 活跃市场可以提高限速
        throttler2 = AdaptiveThrottler({
            "base_rate_limit": 10.0,
            "window_seconds": 1,
        })
        throttler2.should_throttle(market_activity="active")
        assert throttler2.get_current_rate_limit() >= 10.0
    
    def test_get_current_rate_limit(self):
        """测试获取当前限速"""
        throttler = AdaptiveThrottler({
            "base_rate_limit": 10.0,
        })
        assert throttler.get_current_rate_limit() == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

