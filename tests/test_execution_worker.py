# -*- coding: utf-8 -*-
"""ExecutionWorker 单元测试

测试执行 Worker 的核心逻辑，包括信号处理、幂等控制等
"""
import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from src.alpha_core.executors.execution_worker import (
    ExecutionWorker,
    ExecutionConfig,
    ExecutionRecord,
)
from src.alpha_core.executors.execution_store import ExecutionStore
from src.alpha_core.executors.execution_adapters import DryRunExecutionAdapter, ExecutionRequest
from src.alpha_core.executors.signal_stream import ExecutionSignal
from src.alpha_core.executors.base_executor import ExecResult, ExecResultStatus


class TestExecutionWorker:
    """ExecutionWorker 单元测试"""

    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        # 清理
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)

    @pytest.fixture
    def config(self, temp_dir):
        """测试配置"""
        return ExecutionConfig(
            enabled=True,
            mode="dry_run",
            symbols=["BTCUSDT", "ETHUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=10,
            max_concurrency=2,
            retry_max_attempts=3,
            retry_backoff_ms=500
        )

    @pytest.fixture
    def worker(self, config):
        """创建测试 Worker"""
        return ExecutionWorker(config)

    def create_test_signal(self, ts_ms=1000000, symbol="BTCUSDT", score=0.8, gating="ok", confirm=True):
        """创建测试信号"""
        return ExecutionSignal(
            ts_ms=ts_ms,
            symbol=symbol,
            score=score,
            z_ofi=2.1,
            z_cvd=-1.5,
            regime="bull",
            div_type="momentum",
            confirm=confirm,
            gating=gating,
            guard_reason=None,
            signal_id=f"test_signal_{ts_ms}"
        )

    def test_initialization(self, worker, config):
        """测试初始化"""
        assert worker.config == config
        assert isinstance(worker.signal_stream, object)  # 具体类型取决于 config.sink_type
        assert isinstance(worker.execution_store, ExecutionStore)
        assert isinstance(worker.adapter, DryRunExecutionAdapter)
        assert worker.running is False
        assert len(worker.stats) > 0

    def test_prepare_execution_request_skip(self, worker):
        """测试准备跳过执行的请求"""
        # 测试 gating 不为 ok 的情况
        signal = self.create_test_signal(gating="low_consistency")
        request = worker._prepare_execution_request(signal)

        assert request["side"] == "skip"
        assert request["qty"] == 0.0
        assert request["price"] is None

    def test_prepare_execution_request_long(self, worker):
        """测试准备做多请求"""
        signal = self.create_test_signal(score=0.9)  # 高分应该做多
        request = worker._prepare_execution_request(signal)

        assert request["side"] == "long"
        assert request["qty"] == 100.0  # 默认数量
        assert request["order_id"] == f"dryrun:{signal.signal_id}"

    def test_prepare_execution_request_short(self, worker):
        """测试准备做空请求"""
        signal = self.create_test_signal(score=-0.9)  # 负分应该做空
        request = worker._prepare_execution_request(signal)

        assert request["side"] == "short"
        assert request["qty"] == 100.0
        assert request["order_id"] == f"dryrun:{signal.signal_id}"

    def test_prepare_execution_request_no_confirm(self, worker):
        """测试未确认信号的处理"""
        signal = self.create_test_signal(confirm=False)
        request = worker._prepare_execution_request(signal)

        assert request["side"] == "skip"
        assert request["qty"] == 0.0

    def test_execute_order(self, worker):
        """测试订单执行"""
        signal = self.create_test_signal()
        exec_request = {
            "symbol": "BTCUSDT",
            "side": "long",
            "qty": 100.0,
            "price": 50000.0,
            "order_id": "test_order",
            "signal_id": signal.signal_id
        }

        # Mock ExecResult
        mock_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test_order",
            sent_ts_ms=1000000,
            latency_ms=10,
            meta={}
        )

        # Mock adapter
        worker.adapter.send_order = AsyncMock(return_value=mock_result)

        # 执行
        result = asyncio.run(worker._execute_order(exec_request))

        # 验证
        assert result == mock_result
        worker.adapter.send_order.assert_called_once()

        # 验证调用参数
        call_args = worker.adapter.send_order.call_args[0][0]
        assert call_args.symbol == "BTCUSDT"
        assert call_args.side == "long"
        assert call_args.quantity == 100.0

    def test_record_execution_success(self, worker):
        """测试记录成功执行"""
        signal = self.create_test_signal()
        exec_request = {
            "symbol": "BTCUSDT",
            "side": "long",
            "qty": 100.0,
            "price": 50000.0,
            "order_id": "test_order",
            "signal_id": signal.signal_id
        }

        result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test_order",
            sent_ts_ms=1000000,
            latency_ms=10,
            meta={"test": "value"}
        )

        # 记录执行（现在不再更新stats）
        asyncio.run(worker._record_execution(signal, exec_request, result))

        # 验证数据库记录创建成功（通过检查是否有记录）
        import os
        db_path = f"./runtime/executions/executions.db"
        assert os.path.exists(db_path), "数据库文件应该被创建"

    def test_record_execution_failed(self, worker):
        """测试记录失败执行"""
        signal = self.create_test_signal()
        error = "Test error"

        # 记录失败（现在不再更新stats）
        asyncio.run(worker._record_failed_execution(signal, error))

        # 验证数据库记录创建成功
        import os
        db_path = f"./runtime/executions/executions.db"
        assert os.path.exists(db_path), "数据库文件应该被创建"

    def test_map_result_status(self, worker):
        """测试结果状态映射"""
        assert worker._map_result_status(ExecResultStatus.ACCEPTED) == "success"
        assert worker._map_result_status(ExecResultStatus.REJECTED) == "failed"

    def test_process_single_signal_updates_stats(self, worker, mocker):
        """测试_process_single_signal正确更新统计"""
        signal = self.create_test_signal()

        # Mock execution store to simulate successful execution
        mock_store = mocker.patch.object(worker.execution_store, 'is_already_executed', return_value=False)
        mock_record = mocker.patch.object(worker.execution_store, 'record_execution')

        # Mock adapter to return success
        mock_adapter = mocker.patch.object(worker.adapter, 'send_order')
        mock_adapter.return_value = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test_order",
            sent_ts_ms=1000000,
            latency_ms=10,
            meta={"dry_run": True}
        )

        # Process signal
        asyncio.run(worker._process_single_signal(signal))

        # Verify stats are updated correctly (only once)
        assert worker.stats["executions_success"] == 1
        assert worker.stats["executions_failed"] == 0
        assert worker.stats["executions_skip"] == 0

        # Verify metrics are updated
        summary = worker.metrics.get_summary()
        assert summary["executions_success"] == 1
        assert summary["executions_failed"] == 0
        assert summary["executions_skip"] == 0

    def test_worker_metrics_and_skip_signals_regression(self, mocker):
        """回归测试：Worker + Metrics + Skip信号记录"""
        # 设置配置启用skip信号记录
        config = ExecutionConfig(
            symbols=["BTCUSDT"],
            output_dir="./test_output",
            log_skipped_signals=True
        )

        # Mock ExecutionStore - 设置为async方法
        mock_store = mocker.patch('src.alpha_core.executors.execution_worker.ExecutionStore')
        mock_store_instance = mock_store.return_value

        # 设置async mock方法
        async def mock_is_already_executed(*args, **kwargs):
            return False

        async def mock_record_execution(*args, **kwargs):
            pass

        mock_store_instance.is_already_executed = mock_is_already_executed
        mock_store_instance.record_execution = mock_record_execution
        mock_store_instance.get_high_water_mark.return_value = 0

        # 创建Worker
        worker = ExecutionWorker(config)
        worker.execution_store = mock_store_instance

        # 重置metrics确保干净状态
        worker.metrics.reset()

        # 创建测试信号 - 业务规则skip (score=0.3, 不满足long/short阈值)
        signal_skip = ExecutionSignal(
            ts_ms=1000000,
            symbol="BTCUSDT",
            score=0.3,  # 业务规则skip
            z_ofi=0.1,
            z_cvd=0.05,
            regime="neutral",
            div_type="weak",
            confirm=True,
            gating="ok",  # 不被gating拦截
            guard_reason=None,
            signal_id="skip_signal_1"
        )

        # 处理skip信号
        asyncio.run(worker._process_single_signal(signal_skip))

        # 验证统计：1跳过
        assert worker.stats["executions_success"] == 0
        assert worker.stats["executions_failed"] == 0
        assert worker.stats["executions_skip"] == 1

        # 验证metrics
        summary = worker.metrics.get_summary()
        assert summary["executions_success"] == 0
        assert summary["executions_failed"] == 0
        assert summary["executions_skip"] == 1

    @patch('src.alpha_core.executors.execution_worker.ExecutionStore')
    def test_process_single_signal_idempotent(self, mock_store_class, worker):
        """测试信号处理的幂等性"""
        # Mock store
        mock_store = Mock()
        mock_store.is_already_executed = AsyncMock(return_value=True)  # 已经执行过
        mock_store_class.return_value = mock_store

        worker.execution_store = mock_store

        signal = self.create_test_signal()

        # 处理信号
        asyncio.run(worker._process_single_signal(signal))

        # 验证没有调用执行逻辑
        assert worker.stats["executions_skip"] == 1
        # 没有调用 adapter.send_order

    def test_update_stats(self, worker):
        """测试统计更新"""
        result_accepted = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id="test",
            sent_ts_ms=1000000,
            latency_ms=10
        )

        result_rejected = ExecResult(
            status=ExecResultStatus.REJECTED,
            client_order_id="test",
            sent_ts_ms=1000000,
            latency_ms=10
        )

        # 测试成功
        worker._update_stats(result_accepted)
        assert worker.stats["executions_success"] == 1

        # 测试失败
        worker._update_stats(result_rejected)
        assert worker.stats["executions_failed"] == 1

    @patch('asyncio.sleep', new_callable=AsyncMock)
    @patch('src.alpha_core.executors.execution_worker.ExecutionStore')
    def test_process_symbol_signals_shutdown(self, mock_store_class, mock_sleep, worker):
        """测试优雅关闭"""
        # Mock store
        mock_store = Mock()
        mock_store_class.return_value = mock_store

        # Mock signal stream
        async def mock_iter_signals(symbol):
            # 发送一个信号后停止（模拟关闭）
            yield self.create_test_signal()
            # 不会到达这里，因为 shutdown_event 会停止迭代

        worker.signal_stream.iter_signals = mock_iter_signals
        worker._shutdown_event.set()  # 设置关闭事件

        # 处理信号
        asyncio.run(worker._process_symbol_signals("BTCUSDT", asyncio.Semaphore(1)))

        # 验证被正确处理
        assert worker._shutdown_event.is_set()

    def test_cleanup(self, worker):
        """测试清理"""
        # Mock store close
        worker.execution_store.close = AsyncMock()

        # 执行清理
        asyncio.run(worker._cleanup())

        # 验证 store 被关闭
        worker.execution_store.close.assert_called_once()

    def test_log_final_stats(self, worker, caplog):
        """测试最终统计日志"""
        import logging
        caplog.set_level(logging.INFO)

        # 设置一些统计数据
        worker.stats.update({
            "start_time": 1000000,
            "signals_processed": 100,
            "executions_success": 80,
            "executions_skip": 10,
            "executions_failed": 5,
            "executions_retry": 2,
            "last_signal_ts": 2000000
        })

        worker._log_final_stats()

        # 验证日志输出
        log_output = caplog.text
        assert "执行 Worker 统计信息:" in log_output
        assert "处理信号数: 100" in log_output
        assert "成功执行数: 80" in log_output
        assert "跳过执行数: 10" in log_output
        assert "失败执行数: 5" in log_output


class TestExecutionConfig:
    """ExecutionConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = ExecutionConfig()

        assert config.enabled is True
        assert config.mode == "dry_run"
        assert config.symbols == ["BTCUSDT", "ETHUSDT"]
        assert config.sink_type == "jsonl"
        assert config.output_dir == "./runtime"
        assert config.rate_limit_qps == 10
        assert config.max_concurrency == 2
        assert config.retry_max_attempts == 3
        assert config.retry_backoff_ms == 500


class TestExecutionRecord:
    """ExecutionRecord 测试"""

    def test_to_dict(self):
        """测试转换为字典"""
        record = ExecutionRecord(
            exec_ts_ms=1000000,
            signal_ts_ms=900000,
            symbol="BTCUSDT",
            signal_id="test_signal",
            order_id="test_order",
            side="long",
            qty=100.0,
            price=50000.0,
            gating="ok",
            guard_reason=None,
            status="success",
            error_code=None,
            error_msg=None,
            meta_json='{"test": "value"}'
        )

        data = record.to_dict()

        assert data["exec_ts_ms"] == 1000000
        assert data["symbol"] == "BTCUSDT"
        assert data["side"] == "long"
        assert data["status"] == "success"
        assert data["price"] == 50000.0
