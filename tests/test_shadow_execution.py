# -*- coding: utf-8 -*-
"""测试影子执行模块

验证Testnet影子单验证、对比逻辑、一致性比率计算
"""
import pytest
from unittest.mock import Mock, MagicMock

from src.alpha_core.executors.shadow_execution import (
    ShadowExecutor,
    ShadowExecutorWrapper,
    ShadowComparison,
)
from src.alpha_core.executors.base_executor import (
    OrderCtx,
    ExecResult,
    ExecResultStatus,
    Side,
    OrderType,
)


class TestShadowExecutor:
    """测试ShadowExecutor"""
    
    def test_execute_shadow_disabled(self):
        """测试影子执行禁用"""
        mock_testnet = Mock()
        executor = ShadowExecutor(mock_testnet, enabled=False)
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        
        comparison = executor.execute_shadow(order_ctx, main_result)
        
        assert comparison.main_result == main_result
        assert comparison.shadow_result is None
        assert mock_testnet.submit_with_ctx.called is False
    
    def test_execute_shadow_enabled(self):
        """测试影子执行启用"""
        mock_testnet = Mock()
        shadow_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
            exchange_order_id="EX-123",
        )
        mock_testnet.submit_with_ctx.return_value = shadow_result
        
        executor = ShadowExecutor(mock_testnet, enabled=True)
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            tick_size=0.01,
        )
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
            exchange_order_id="EX-456",
        )
        
        comparison = executor.execute_shadow(order_ctx, main_result)
        
        assert comparison.main_result == main_result
        assert comparison.shadow_result == shadow_result
        assert mock_testnet.submit_with_ctx.called
    
    def test_compare_results_status_parity(self):
        """测试状态一致性对比"""
        executor = ShadowExecutor(Mock(), enabled=False)
        
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        shadow_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        comparison = executor._compare_results(main_result, shadow_result, order_ctx)
        
        assert comparison.status_parity == 1.0  # 状态一致
    
    def test_compare_results_status_mismatch(self):
        """测试状态不一致"""
        executor = ShadowExecutor(Mock(), enabled=False)
        
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        shadow_result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-1",
            reject_reason="warmup",
        )
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        comparison = executor._compare_results(main_result, shadow_result, order_ctx)
        
        assert comparison.status_parity == 0.0  # 状态不一致
    
    def test_compare_results_reason_parity(self):
        """测试原因一致性对比"""
        executor = ShadowExecutor(Mock(), enabled=False)
        
        main_result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-1",
            reject_reason="warmup",
        )
        shadow_result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-1",
            reject_reason="warmup",
        )
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        comparison = executor._compare_results(main_result, shadow_result, order_ctx)
        
        assert comparison.reason_parity == 1.0  # 原因一致
    
    def test_get_parity_ratio_no_comparisons(self):
        """测试无对比时的parity ratio"""
        executor = ShadowExecutor(Mock(), enabled=False)
        
        ratio = executor.get_parity_ratio()
        assert ratio == 1.0  # 默认完全一致
    
    def test_get_parity_ratio_with_comparisons(self):
        """测试有对比时的parity ratio"""
        mock_testnet = Mock()
        executor = ShadowExecutor(mock_testnet, enabled=True)
        
        # 模拟多次对比
        for i in range(10):
            order_ctx = OrderCtx(
                client_order_id=f"test-{i}",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
            )
            main_result = ExecResult(
                status=ExecResultStatus.ACCEPTED,
                client_order_id=f"test-{i}",
            )
            shadow_result = ExecResult(
                status=ExecResultStatus.ACCEPTED,
                client_order_id=f"test-{i}",
            )
            mock_testnet.submit_with_ctx.return_value = shadow_result
            
            executor.execute_shadow(order_ctx, main_result)
        
        ratio = executor.get_parity_ratio()
        assert 0.0 <= ratio <= 1.0
    
    def test_get_stats(self):
        """测试获取统计信息"""
        mock_testnet = Mock()
        executor = ShadowExecutor(mock_testnet, enabled=True)
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        shadow_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        mock_testnet.submit_with_ctx.return_value = shadow_result
        
        executor.execute_shadow(order_ctx, main_result)
        
        stats = executor.get_stats()
        assert "comparison_count" in stats
        assert "parity_ratio" in stats
        assert stats["comparison_count"] == 1
    
    def test_reset_stats(self):
        """测试重置统计信息"""
        mock_testnet = Mock()
        executor = ShadowExecutor(mock_testnet, enabled=True)
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        shadow_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        mock_testnet.submit_with_ctx.return_value = shadow_result
        
        executor.execute_shadow(order_ctx, main_result)
        assert executor.get_stats()["comparison_count"] == 1
        
        executor.reset_stats()
        assert executor.get_stats()["comparison_count"] == 0


class TestShadowExecutorWrapper:
    """测试ShadowExecutorWrapper"""
    
    def test_submit_with_ctx_without_shadow(self):
        """测试无影子执行时的提交"""
        mock_main = Mock()
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        mock_main.submit_with_ctx.return_value = main_result
        
        wrapper = ShadowExecutorWrapper(mock_main, shadow_executor=None)
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        result = wrapper.submit_with_ctx(order_ctx)
        
        assert result == main_result
        assert mock_main.submit_with_ctx.called
    
    def test_submit_with_ctx_with_shadow(self):
        """测试有影子执行时的提交"""
        mock_main = Mock()
        main_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        mock_main.submit_with_ctx.return_value = main_result
        
        mock_testnet = Mock()
        shadow_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-1",
        )
        mock_testnet.submit_with_ctx.return_value = shadow_result
        
        shadow_executor = ShadowExecutor(mock_testnet, enabled=True)
        wrapper = ShadowExecutorWrapper(mock_main, shadow_executor=shadow_executor)
        
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        result = wrapper.submit_with_ctx(order_ctx)
        
        assert result == main_result
        assert mock_main.submit_with_ctx.called
        assert mock_testnet.submit_with_ctx.called
    
    def test_get_shadow_stats(self):
        """测试获取影子执行统计信息"""
        mock_main = Mock()
        mock_testnet = Mock()
        shadow_executor = ShadowExecutor(mock_testnet, enabled=True)
        wrapper = ShadowExecutorWrapper(mock_main, shadow_executor=shadow_executor)
        
        stats = wrapper.get_shadow_stats()
        assert stats is not None
        assert "parity_ratio" in stats
    
    def test_get_shadow_stats_no_shadow(self):
        """测试无影子执行时的统计信息"""
        mock_main = Mock()
        wrapper = ShadowExecutorWrapper(mock_main, shadow_executor=None)
        
        stats = wrapper.get_shadow_stats()
        assert stats is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

