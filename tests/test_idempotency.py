# -*- coding: utf-8 -*-
"""测试幂等性与重试模块

验证幂等键生成、重试策略、幂等性跟踪
"""
import pytest
import time
from unittest.mock import Mock, patch

from src.alpha_core.executors.idempotency import (
    generate_idempotent_key,
    generate_idempotent_key_from_order_ctx,
    generate_idempotent_key_from_order,
    RetryPolicy,
    IdempotencyTracker,
    retry_with_backoff,
)
from src.alpha_core.executors.base_executor import OrderCtx, Order, Side, OrderType


class TestIdempotentKey:
    """测试幂等键生成"""
    
    def test_generate_idempotent_key_basic(self):
        """测试基础幂等键生成"""
        key1 = generate_idempotent_key(
            signal_row_id="signal-123",
            ts_ms=1234567890,
            side="buy",
            qty=0.001,
            price=50000.0,
        )
        
        # 相同输入应该生成相同键
        key2 = generate_idempotent_key(
            signal_row_id="signal-123",
            ts_ms=1234567890,
            side="buy",
            qty=0.001,
            price=50000.0,
        )
        
        assert key1 == key2
        assert len(key1) == 32  # SHA256前32字符
    
    def test_generate_idempotent_key_different_inputs(self):
        """测试不同输入生成不同键"""
        key1 = generate_idempotent_key(
            signal_row_id="signal-123",
            ts_ms=1234567890,
            side="buy",
            qty=0.001,
            price=50000.0,
        )
        
        key2 = generate_idempotent_key(
            signal_row_id="signal-123",
            ts_ms=1234567890,
            side="sell",  # 不同方向
            qty=0.001,
            price=50000.0,
        )
        
        assert key1 != key2
    
    def test_generate_idempotent_key_from_order_ctx(self):
        """测试从OrderCtx生成幂等键"""
        order_ctx = OrderCtx(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            signal_row_id="signal-456",
            ts_ms=1234567890,
        )
        
        key = generate_idempotent_key_from_order_ctx(order_ctx)
        assert len(key) == 32
        assert isinstance(key, str)
    
    def test_generate_idempotent_key_from_order(self):
        """测试从Order生成幂等键（向后兼容）"""
        order = Order(
            client_order_id="test-789",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            ts_ms=1234567890,
            metadata={"signal_row_id": "signal-999"},
        )
        
        key = generate_idempotent_key_from_order(order)
        assert len(key) == 32
        assert isinstance(key, str)
    
    def test_generate_idempotent_key_empty_inputs(self):
        """测试空输入生成幂等键（使用时间戳和随机数）"""
        key1 = generate_idempotent_key()
        key2 = generate_idempotent_key()
        
        # 空输入应该生成不同的键（因为时间戳不同）
        assert key1 != key2
        assert len(key1) == 32


class TestRetryPolicy:
    """测试重试策略"""
    
    def test_should_retry_network_error(self):
        """测试网络错误应该重试"""
        policy = RetryPolicy(max_retries=3)
        
        # 网络错误
        network_error = Exception("Connection timeout")
        assert policy.should_retry(0, network_error) is True
        assert policy.should_retry(1, network_error) is True
        assert policy.should_retry(2, network_error) is True
        assert policy.should_retry(3, network_error) is False  # 超过最大重试次数
    
    def test_should_retry_5xx_error(self):
        """测试5xx错误应该重试"""
        policy = RetryPolicy(max_retries=3)
        
        # 5xx错误（字符串形式）
        error_500 = Exception("HTTP 500 Internal Server Error")
        assert policy.should_retry(0, error_500) is True
        
        error_503 = Exception("HTTP 503 Service Unavailable")
        assert policy.should_retry(0, error_503) is True
    
    def test_should_retry_rejected_error(self):
        """测试拒绝错误不应该重试"""
        policy = RetryPolicy(max_retries=3)
        
        # 拒绝错误
        rejected_error = Exception("Order rejected: invalid parameters")
        assert policy.should_retry(0, rejected_error) is False
    
    def test_get_delay_exponential_backoff(self):
        """测试指数退避延迟"""
        policy = RetryPolicy(base_delay=0.1, max_delay=5.0)
        
        delay0 = policy.get_delay(0)
        delay1 = policy.get_delay(1)
        delay2 = policy.get_delay(2)
        
        # 延迟应该递增
        assert delay0 < delay1 < delay2
        
        # 延迟应该在合理范围内
        assert 0.0 <= delay0 <= 5.0
        assert 0.0 <= delay1 <= 5.0
        assert 0.0 <= delay2 <= 5.0
    
    def test_get_delay_max_limit(self):
        """测试延迟上限"""
        policy = RetryPolicy(base_delay=1.0, max_delay=2.0)
        
        # 即使指数退避计算出的延迟很大，也应该限制在max_delay内
        delay = policy.get_delay(10)  # 很大的尝试次数
        assert delay <= 2.0


class TestIdempotencyTracker:
    """测试幂等性跟踪器"""
    
    def test_is_processed_basic(self):
        """测试基础处理检查"""
        tracker = IdempotencyTracker(max_size=100)
        
        assert tracker.is_processed("order-1") is False
        
        tracker.mark_processed("order-1")
        assert tracker.is_processed("order-1") is True
    
    def test_idempotency_tracker_lru(self):
        """测试LRU机制"""
        tracker = IdempotencyTracker(max_size=3)
        
        # 添加3个订单
        tracker.mark_processed("order-1")
        tracker.mark_processed("order-2")
        tracker.mark_processed("order-3")
        
        assert tracker.is_processed("order-1") is True
        assert tracker.is_processed("order-2") is True
        assert tracker.is_processed("order-3") is True
        
        # 添加第4个订单，应该移除最旧的
        tracker.mark_processed("order-4")
        
        assert tracker.is_processed("order-1") is False  # 被移除
        assert tracker.is_processed("order-2") is True
        assert tracker.is_processed("order-3") is True
        assert tracker.is_processed("order-4") is True
    
    def test_clear(self):
        """测试清空跟踪器"""
        tracker = IdempotencyTracker()
        
        tracker.mark_processed("order-1")
        tracker.mark_processed("order-2")
        
        assert tracker.is_processed("order-1") is True
        
        tracker.clear()
        
        assert tracker.is_processed("order-1") is False
        assert tracker.is_processed("order-2") is False


class TestRetryWithBackoff:
    """测试带退避的重试"""
    
    def test_retry_success_first_attempt(self):
        """测试第一次尝试成功"""
        def mock_func():
            return "success"
        
        result = retry_with_backoff(mock_func)
        assert result == "success"
    
    def test_retry_success_after_retries(self):
        """测试重试后成功"""
        call_count = [0]
        
        def mock_func():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("Connection timeout")
            return "success"
        
        with patch('time.sleep'):  # 模拟sleep，不实际等待
            result = retry_with_backoff(mock_func, RetryPolicy(max_retries=3))
            assert result == "success"
            assert call_count[0] == 2
    
    def test_retry_fail_after_max_retries(self):
        """测试达到最大重试次数后失败"""
        def mock_func():
            raise Exception("Connection timeout")
        
        policy = RetryPolicy(max_retries=2)
        
        with patch('time.sleep'):  # 模拟sleep
            with pytest.raises(Exception, match="Connection timeout"):
                retry_with_backoff(mock_func, policy)
    
    def test_retry_no_retry_for_rejected(self):
        """测试拒绝错误不重试"""
        def mock_func():
            raise Exception("Order rejected")
        
        policy = RetryPolicy(max_retries=3)
        
        with pytest.raises(Exception, match="Order rejected"):
            retry_with_backoff(mock_func, policy)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

