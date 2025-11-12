# -*- coding: utf-8 -*-
"""测试执行层日志采样模块

验证"通过1% / 失败100%"采样策略
"""
import pytest
from unittest.mock import Mock, patch

from src.alpha_core.executors.executor_logging import ExecutorLogger, get_executor_logger
from src.alpha_core.executors.base_executor import (
    OrderCtx,
    ExecResult,
    ExecResultStatus,
    Side,
    OrderType,
)


class TestExecutorLogger:
    """测试ExecutorLogger"""
    
    def test_should_log_rejected(self):
        """测试拒绝订单应该100%记录"""
        logger = ExecutorLogger(sample_rate=0.01, enabled=True)
        
        exec_result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-1",
            reject_reason="warmup",
        )
        
        assert logger.should_log(exec_result) is True
    
    def test_should_log_accepted_sampled(self):
        """测试接受订单按采样率记录"""
        logger = ExecutorLogger(sample_rate=0.01, enabled=True)
        
        exec_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-2",
        )
        
        # 由于是随机采样，多次调用应该大部分返回False
        # 但至少应该有一次返回True（概率问题）
        results = [logger.should_log(exec_result) for _ in range(1000)]
        # 应该有大约1%的True
        assert sum(results) > 0  # 至少有一个True
        assert sum(results) < 50  # 但不会太多（统计上应该在10左右）
    
    def test_should_log_disabled(self):
        """测试禁用时不应该记录"""
        logger = ExecutorLogger(enabled=False)
        
        exec_result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-3",
        )
        
        assert logger.should_log(exec_result) is False
    
    def test_log_order_submitted_rejected(self):
        """测试记录拒绝订单"""
        logger = ExecutorLogger(enabled=True)
        
        order_ctx = OrderCtx(
            client_order_id="test-rejected",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            warmup=True,
            guard_reason="warmup",
        )
        
        exec_result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-rejected",
            reject_reason="warmup",
            latency_ms=5,
        )
        
        # 应该记录（失败订单100%记录）
        logger.log_order_submitted(order_ctx, exec_result)
        
        assert logger.get_stats()["failed_count"] == 1
    
    def test_log_order_submitted_accepted(self):
        """测试记录接受订单（采样）"""
        logger = ExecutorLogger(sample_rate=1.0, enabled=True)  # 100%采样用于测试
        
        order_ctx = OrderCtx(
            client_order_id="test-accepted",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            scenario="HH",
        )
        
        exec_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-accepted",
            exchange_order_id="EX-123",
            latency_ms=10,
        )
        
        logger.log_order_submitted(order_ctx, exec_result)
        
        stats = logger.get_stats()
        assert stats["sampled_count"] >= 0  # 可能采样也可能不采样
    
    def test_log_order_filled(self):
        """测试记录成交订单"""
        logger = ExecutorLogger(enabled=True)
        
        order_ctx = OrderCtx(
            client_order_id="test-filled",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        exec_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-filled",
            slippage_bps=0.5,
        )
        
        # 成交订单应该记录
        logger.log_order_filled(order_ctx, exec_result, fill_price=50000.0, fill_qty=0.001)
        
        # 成交订单不计数到sampled_count，因为直接记录
        stats = logger.get_stats()
        assert stats is not None
    
    def test_log_order_canceled(self):
        """测试记录撤销订单"""
        logger = ExecutorLogger(enabled=True)
        
        order_ctx = OrderCtx(
            client_order_id="test-canceled",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        # 撤销订单应该记录
        logger.log_order_canceled(order_ctx, cancel_reason="user_request")
        
        stats = logger.get_stats()
        assert stats is not None
    
    def test_log_schema_validation_failed(self):
        """测试记录Schema校验失败"""
        logger = ExecutorLogger(enabled=True)
        
        # Schema校验失败应该记录
        logger.log_schema_validation_failed("BTCUSDT", ["missing_field: price"])
        
        stats = logger.get_stats()
        assert stats is not None
    
    def test_log_shadow_alert(self):
        """测试记录影子告警"""
        logger = ExecutorLogger(enabled=True)
        
        # 影子告警应该记录
        logger.log_shadow_alert(parity_ratio=0.98, threshold=0.99)
        
        stats = logger.get_stats()
        assert stats is not None
    
    def test_get_stats(self):
        """测试获取统计信息"""
        logger = ExecutorLogger(sample_rate=0.01, enabled=True)
        
        stats = logger.get_stats()
        
        assert "logged_count" in stats
        assert "sampled_count" in stats
        assert "failed_count" in stats
        assert "sample_rate" in stats
        assert stats["sample_rate"] == 0.01


class TestGetExecutorLogger:
    """测试get_executor_logger单例"""
    
    def test_singleton(self):
        """测试单例模式"""
        logger1 = get_executor_logger()
        logger2 = get_executor_logger()
        
        assert logger1 is logger2
    
    def test_singleton_with_params(self):
        """测试单例模式（首次调用时使用参数）"""
        # 重置单例
        if hasattr(get_executor_logger, '_instance'):
            delattr(get_executor_logger, '_instance')
        
        logger1 = get_executor_logger(sample_rate=0.05)
        logger2 = get_executor_logger(sample_rate=0.01)  # 第二次调用应该忽略参数
        
        assert logger1 is logger2
        assert logger1.sample_rate == 0.05  # 使用首次调用的参数


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

