# -*- coding: utf-8 -*-
"""测试执行层契约 v1 (executor_contract/v1)

验证OrderCtx、ExecResult、CancelResult、AmendResult数据类
以及IExecutor接口扩展方法
"""
import pytest
import time
from dataclasses import asdict

from src.alpha_core.executors.base_executor import (
    OrderCtx,
    ExecResult,
    ExecResultStatus,
    CancelResult,
    AmendResult,
    Order,
    Side,
    OrderType,
    TimeInForce,
    IExecutor,
)


class TestOrderCtx:
    """测试OrderCtx数据类"""
    
    def test_order_ctx_basic(self):
        """测试基础OrderCtx创建"""
        ctx = OrderCtx(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        assert ctx.client_order_id == "test-123"
        assert ctx.symbol == "BTCUSDT"
        assert ctx.side == Side.BUY
        assert ctx.qty == 0.001
        assert ctx.order_type == OrderType.MARKET  # 默认值
        assert ctx.warmup is False  # 默认值
        assert ctx.consistency is None  # 默认值
    
    def test_order_ctx_with_upstream_state(self):
        """测试包含上游状态字段的OrderCtx"""
        ctx = OrderCtx(
            client_order_id="test-456",
            symbol="BTCUSDT",
            side=Side.SELL,
            qty=0.002,
            signal_row_id="signal-789",
            regime="active",
            scenario="HH",
            warmup=True,
            guard_reason="warmup,low_consistency",
            consistency=0.75,
            weak_signal_throttle=False,
        )
        assert ctx.signal_row_id == "signal-789"
        assert ctx.regime == "active"
        assert ctx.scenario == "HH"
        assert ctx.warmup is True
        assert ctx.guard_reason == "warmup,low_consistency"
        assert ctx.consistency == 0.75
        assert ctx.weak_signal_throttle is False
    
    def test_order_ctx_with_exchange_constraints(self):
        """测试包含交易所约束字段的OrderCtx"""
        ctx = OrderCtx(
            client_order_id="test-789",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            tick_size=0.01,
            step_size=0.001,
            min_notional=10.0,
        )
        assert ctx.tick_size == 0.01
        assert ctx.step_size == 0.001
        assert ctx.min_notional == 10.0
    
    def test_order_ctx_to_order(self):
        """测试OrderCtx转换为Order"""
        ctx = OrderCtx(
            client_order_id="test-convert",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            order_type=OrderType.LIMIT,
            price=50000.0,
            ts_ms=1234567890,
        )
        order = ctx.to_order()
        assert isinstance(order, Order)
        assert order.client_order_id == "test-convert"
        assert order.symbol == "BTCUSDT"
        assert order.side == Side.BUY
        assert order.qty == 0.001
        assert order.order_type == OrderType.LIMIT
        assert order.price == 50000.0
        assert order.ts_ms == 1234567890


class TestExecResult:
    """测试ExecResult数据类"""
    
    def test_exec_result_accepted(self):
        """测试接受的执行结果"""
        result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-123",
            exchange_order_id="EX-456",
            latency_ms=12,
            slippage_bps=0.5,
            sent_ts_ms=1234567890,
            ack_ts_ms=1234567902,
        )
        assert result.status == ExecResultStatus.ACCEPTED
        assert result.client_order_id == "test-123"
        assert result.exchange_order_id == "EX-456"
        assert result.latency_ms == 12
        assert result.slippage_bps == 0.5
        assert result.reject_reason is None
    
    def test_exec_result_rejected(self):
        """测试拒绝的执行结果"""
        result = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test-789",
            reject_reason="warmup",
            sent_ts_ms=1234567890,
        )
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "warmup"
        assert result.exchange_order_id is None
    
    def test_exec_result_with_rounding(self):
        """测试包含价格对齐的执行结果"""
        result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-round",
            rounding_applied={"price_diff": 0.01, "qty_diff": 0.0001},
        )
        assert result.rounding_applied == {"price_diff": 0.01, "qty_diff": 0.0001}


class TestCancelResult:
    """测试CancelResult数据类"""
    
    def test_cancel_result_success(self):
        """测试成功的撤销结果"""
        result = CancelResult(
            success=True,
            client_order_id="test-123",
            exchange_order_id="EX-456",
            latency_ms=5,
            cancel_ts_ms=1234567890,
        )
        assert result.success is True
        assert result.client_order_id == "test-123"
        assert result.reason is None
    
    def test_cancel_result_failed(self):
        """测试失败的撤销结果"""
        result = CancelResult(
            success=False,
            client_order_id="test-789",
            reason="order_not_found",
        )
        assert result.success is False
        assert result.reason == "order_not_found"


class TestAmendResult:
    """测试AmendResult数据类（预留）"""
    
    def test_amend_result_basic(self):
        """测试基础AmendResult"""
        result = AmendResult(
            success=True,
            client_order_id="test-123",
        )
        assert result.success is True
        assert result.client_order_id == "test-123"


class TestIExecutorExtension:
    """测试IExecutor接口扩展方法"""
    
    def test_submit_with_ctx_default_implementation(self):
        """测试submit_with_ctx的默认实现"""
        # 创建一个简单的Mock Executor
        class MockExecutor(IExecutor):
            def prepare(self, cfg):
                pass
            
            def submit(self, order):
                return f"EX-{order.client_order_id}"
            
            def cancel(self, order_id):
                return True
            
            def fetch_fills(self, since_ts_ms=None):
                return []
            
            def get_position(self, symbol):
                return 0.0
            
            def close(self):
                pass
            
            @property
            def mode(self):
                return "test"
        
        executor = MockExecutor()
        executor.prepare({})
        
        ctx = OrderCtx(
            client_order_id="test-ctx",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            ts_ms=int(time.time() * 1000),
        )
        
        result = executor.submit_with_ctx(ctx)
        assert isinstance(result, ExecResult)
        assert result.status == ExecResultStatus.ACCEPTED
        assert result.client_order_id == "test-ctx"
        assert result.exchange_order_id == "EX-test-ctx"
        assert result.sent_ts_ms == ctx.ts_ms
    
    def test_cancel_with_result_default_implementation(self):
        """测试cancel_with_result的默认实现"""
        class MockExecutor(IExecutor):
            def prepare(self, cfg):
                pass
            
            def submit(self, order):
                return f"EX-{order.client_order_id}"
            
            def cancel(self, order_id):
                return order_id.startswith("test-")
            
            def fetch_fills(self, since_ts_ms=None):
                return []
            
            def get_position(self, symbol):
                return 0.0
            
            def close(self):
                pass
            
            @property
            def mode(self):
                return "test"
        
        executor = MockExecutor()
        executor.prepare({})
        
        # 测试成功撤销
        result = executor.cancel_with_result("test-123")
        assert isinstance(result, CancelResult)
        assert result.success is True
        assert result.client_order_id == "test-123"
        assert result.reason is None
        
        # 测试失败撤销
        result = executor.cancel_with_result("invalid-123")
        assert isinstance(result, CancelResult)
        assert result.success is False
        assert result.reason == "cancel_failed"
    
    def test_flush_default_implementation(self):
        """测试flush的默认实现（应该不报错）"""
        class MockExecutor(IExecutor):
            def prepare(self, cfg):
                pass
            
            def submit(self, order):
                return f"EX-{order.client_order_id}"
            
            def cancel(self, order_id):
                return True
            
            def fetch_fills(self, since_ts_ms=None):
                return []
            
            def get_position(self, symbol):
                return 0.0
            
            def close(self):
                pass
            
            @property
            def mode(self):
                return "test"
        
        executor = MockExecutor()
        executor.prepare({})
        
        # flush()应该不报错（默认实现为空）
        executor.flush()


class TestDataContractCompatibility:
    """测试数据契约兼容性"""
    
    def test_order_ctx_serialization(self):
        """测试OrderCtx序列化（用于JSON Schema验证）"""
        ctx = OrderCtx(
            client_order_id="test-serial",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            signal_row_id="signal-123",
            regime="active",
            warmup=False,
            consistency=0.85,
        )
        
        # 转换为字典（模拟JSON序列化）
        ctx_dict = asdict(ctx)
        assert ctx_dict["client_order_id"] == "test-serial"
        assert ctx_dict["symbol"] == "BTCUSDT"
        assert ctx_dict["side"] == "buy"  # Enum值
        assert ctx_dict["warmup"] is False
        assert ctx_dict["consistency"] == 0.85
    
    def test_exec_result_serialization(self):
        """测试ExecResult序列化"""
        result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test-result",
            exchange_order_id="EX-123",
            latency_ms=10,
        )
        
        result_dict = asdict(result)
        assert result_dict["status"] == "accepted"  # Enum值
        assert result_dict["client_order_id"] == "test-result"
        assert result_dict["latency_ms"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

