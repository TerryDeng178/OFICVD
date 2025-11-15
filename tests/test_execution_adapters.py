# -*- coding: utf-8 -*-
"""ExecutionAdapter 单元测试

测试执行适配器的功能，包括 DryRun 和 Live 模式
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from src.alpha_core.executors.execution_adapters import (
    ExecutionAdapter,
    DryRunExecutionAdapter,
    LiveExecutionAdapter,
    ExecutionRequest,
    create_execution_adapter,
)
from src.alpha_core.executors.base_executor import ExecResult, ExecResultStatus


class TestExecutionRequest:
    """ExecutionRequest 测试"""

    def test_creation(self):
        """测试创建请求"""
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="long",
            quantity=100.0,
            price=50000.0,
            client_order_id="test_order_123",
            signal_id="test_signal_456"
        )

        assert request.symbol == "BTCUSDT"
        assert request.side == "long"
        assert request.quantity == 100.0
        assert request.price == 50000.0
        assert request.client_order_id == "test_order_123"
        assert request.signal_id == "test_signal_456"


class TestExecutionAdapter:
    """ExecutionAdapter 基类测试"""

    def test_abstract_methods(self):
        """测试抽象方法"""
        # ExecutionAdapter 是抽象类，不能直接实例化
        # 这里我们测试抽象方法的定义
        assert hasattr(ExecutionAdapter, 'send_order')
        assert hasattr(ExecutionAdapter, 'health_check')

    def test_health_check_default(self):
        """测试默认健康检查"""
        # 由于是抽象类，我们创建一个子类来测试
        class TestAdapter(ExecutionAdapter):
            async def send_order(self, request):
                raise NotImplementedError

        adapter = TestAdapter()
        result = asyncio.run(adapter.health_check())
        assert result is True


class TestDryRunExecutionAdapter:
    """DryRunExecutionAdapter 测试"""

    @pytest.fixture
    def adapter(self):
        """创建 DryRun 适配器"""
        return DryRunExecutionAdapter()

    def test_initialization(self, adapter):
        """测试初始化"""
        assert adapter.config == {}
        assert adapter.logger is not None

    def test_send_order_skip(self, adapter):
        """测试跳过订单"""
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="skip",
            quantity=0.0,
            price=None,
            client_order_id="dryrun:test_signal",
            signal_id="test_signal"
        )

        result = asyncio.run(adapter.send_order(request))

        assert result.status == ExecResultStatus.ACCEPTED
        assert result.client_order_id == "dryrun:test_signal"
        assert result.meta["dry_run"] is True
        assert result.meta["reason"] == "skip_signal"

    def test_send_order_long_success(self, adapter):
        """测试成功做多订单"""
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="long",
            quantity=100.0,
            price=50000.0,
            client_order_id="dryrun:test_signal",
            signal_id="test_signal"
        )

        result = asyncio.run(adapter.send_order(request))

        assert result.status == ExecResultStatus.ACCEPTED
        assert result.client_order_id == "dryrun:test_signal"
        assert result.sent_ts_ms is not None
        assert result.latency_ms == 15
        assert result.meta["dry_run"] is True
        assert result.meta["simulated_price"] == 50000.0

    def test_send_order_short_success(self, adapter):
        """测试成功做空订单"""
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="short",
            quantity=50.0,
            price=None,  # 市价
            client_order_id="dryrun:test_signal",
            signal_id="test_signal"
        )

        result = asyncio.run(adapter.send_order(request))

        assert result.status == ExecResultStatus.ACCEPTED
        assert result.meta["simulated_price"] == 50000.0  # 默认价格

    def test_send_order_invalid_quantity(self, adapter):
        """测试无效数量"""
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="long",
            quantity=-10.0,  # 无效数量
            price=50000.0,
            client_order_id="dryrun:test_signal",
            signal_id="test_signal"
        )

        result = asyncio.run(adapter.send_order(request))

        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "invalid_quantity"
        assert result.meta["dry_run"] is True
        assert "quantity_must_be_positive" in result.meta["error"]

    def test_send_order_invalid_side(self, adapter):
        """测试无效方向"""
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="invalid_side",  # 无效方向
            quantity=100.0,
            price=50000.0,
            client_order_id="dryrun:test_signal",
            signal_id="test_signal"
        )

        result = asyncio.run(adapter.send_order(request))

        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "invalid_side"
        assert result.meta["dry_run"] is True

    def test_health_check(self, adapter):
        """测试健康检查"""
        result = asyncio.run(adapter.health_check())
        assert result is True


class TestLiveExecutionAdapter:
    """LiveExecutionAdapter 测试"""

    def test_initialization(self):
        """测试初始化"""
        adapter = LiveExecutionAdapter()
        assert adapter.config == {}

    def test_send_order_not_implemented(self):
        """测试未实现的发送订单方法"""
        adapter = LiveExecutionAdapter()
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side="long",
            quantity=100.0,
            price=50000.0,
            client_order_id="test_order",
            signal_id="test_signal"
        )

        with pytest.raises(NotImplementedError):
            asyncio.run(adapter.send_order(request))


class TestExecutionAdapterFactory:
    """执行适配器工厂测试"""

    def test_create_dry_run_adapter(self):
        """测试创建 DryRun 适配器"""
        adapter = create_execution_adapter("dry_run")
        assert isinstance(adapter, DryRunExecutionAdapter)

    def test_create_live_adapter(self):
        """测试创建 Live 适配器"""
        adapter = create_execution_adapter("live")
        assert isinstance(adapter, LiveExecutionAdapter)

    def test_create_with_config(self):
        """测试带配置创建适配器"""
        config = {"test": "value"}
        adapter = create_execution_adapter("dry_run", config)
        assert isinstance(adapter, DryRunExecutionAdapter)
        assert adapter.config == config

    def test_create_invalid_mode(self):
        """测试无效模式"""
        with pytest.raises(ValueError, match="不支持的执行模式"):
            create_execution_adapter("invalid_mode")
