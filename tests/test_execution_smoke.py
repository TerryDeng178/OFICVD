# -*- coding: utf-8 -*-
"""ExecutionWorker 冒烟测试

测试长跑稳定性和基本功能完整性
"""
import pytest
import tempfile
import json
import time
import asyncio
from pathlib import Path
from unittest.mock import patch

from src.alpha_core.executors.execution_worker import ExecutionWorker, ExecutionConfig
from src.alpha_core.executors.execution_store import ExecutionStore


class TestExecutionSmoke:
    """冒烟测试"""

    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        # 清理
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)

    def test_basic_smoke_test(self, temp_dir):
        """基本冒烟测试"""
        # 创建简单的信号
        signal_data = {
            "ts_ms": int(time.time() * 1000),
            "symbol": "BTCUSDT",
            "score": 0.8,
            "z_ofi": 2.1,
            "z_cvd": -1.5,
            "regime": "bull",
            "div_type": "momentum",
            "confirm": True,
            "gating": "ok",
            "guard_reason": None
        }

        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        with open(signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            f.write(json.dumps(signal_data, ensure_ascii=False) + '\n')

        # 创建 Worker
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir)
        )

        worker = ExecutionWorker(config)

        # 运行一小段时间
        async def run_smoke():
            semaphore = asyncio.Semaphore(1)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))
            await asyncio.sleep(0.1)  # 冒烟测试，只运行很短时间
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_smoke())

        # 验证基本功能工作
        assert worker.stats["signals_processed"] >= 1

        # 验证数据库创建
        db_path = temp_dir / "executions" / "executions.db"
        assert db_path.exists()

        # 验证有执行记录
        store = ExecutionStore(db_path)
        stats = asyncio.run(store.get_execution_stats())
        assert stats["total_executions"] >= 1

    def test_long_running_stability(self, temp_dir):
        """长跑稳定性测试"""
        # 创建持续的信号流
        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        # 创建多个信号文件模拟持续输入
        for i in range(5):
            signals_data = []
            for j in range(10):  # 每个文件10个信号
                signal_data = {
                    "ts_ms": int(time.time() * 1000) + (i * 10 + j) * 1000,
                    "symbol": "BTCUSDT",
                    "score": 0.8 if j % 2 == 0 else -0.8,
                    "z_ofi": 2.1,
                    "z_cvd": -1.5,
                    "regime": "bull",
                    "div_type": "momentum",
                    "confirm": True,
                    "gating": "ok",
                    "guard_reason": None
                }
                signals_data.append(signal_data)

            filename = f"signals_20241114_{1200 + i:04d}.jsonl"
            with open(signal_dir / filename, 'w', encoding='utf-8') as f:
                for signal in signals_data:
                    f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        # 配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=50,  # 控制速率避免过快
            max_concurrency=3
        )

        worker = ExecutionWorker(config)

        # 记录开始时间
        start_time = time.time()

        # 运行相对较长时间（5秒）
        async def run_long_test():
            semaphore = asyncio.Semaphore(config.max_concurrency)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))

            # 运行5秒
            await asyncio.sleep(5.0)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_long_test())

        end_time = time.time()
        duration = end_time - start_time

        # 验证稳定性
        assert duration >= 4.5  # 应该至少运行了接近5秒

        # 验证处理了合理数量的信号
        assert worker.stats["signals_processed"] > 0
        assert worker.stats["executions_success"] > 0

        # 验证没有崩溃（如果有异常，stats 应该仍然合理）
        assert worker.stats["executions_success"] + worker.stats["executions_failed"] + worker.stats["executions_skip"] == worker.stats["signals_processed"]

        # 验证数据库完整性
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats())
        assert stats["total_executions"] > 0

    def test_memory_usage_stability(self, temp_dir):
        """内存使用稳定性测试"""
        # 创建大量信号测试内存稳定性
        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        # 创建大量信号
        num_signals = 1000
        signals_data = []

        for i in range(num_signals):
            signal_data = {
                "ts_ms": int(time.time() * 1000) + i * 100,
                "symbol": "BTCUSDT",
                "score": 0.8,
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            }
            signals_data.append(signal_data)

        with open(signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            for signal in signals_data:
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        # 配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=1000,
            max_concurrency=10
        )

        worker = ExecutionWorker(config)

        # 运行处理大量信号
        async def run_memory_test():
            semaphore = asyncio.Semaphore(config.max_concurrency)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))

            # 运行足够时间处理所有信号
            await asyncio.sleep(2.0)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_memory_test())

        # 验证处理了大量信号但没有崩溃
        assert worker.stats["signals_processed"] == num_signals
        assert worker.stats["executions_success"] == num_signals

        # 验证数据库完整性
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats())
        assert stats["total_executions"] == num_signals

    def test_restart_recovery_smoke(self, temp_dir):
        """重启恢复冒烟测试"""
        # 创建信号
        signal_data = {
            "ts_ms": int(time.time() * 1000),
            "symbol": "BTCUSDT",
            "score": 0.8,
            "z_ofi": 2.1,
            "z_cvd": -1.5,
            "regime": "bull",
            "div_type": "momentum",
            "confirm": True,
            "gating": "ok",
            "guard_reason": None
        }

        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        with open(signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            f.write(json.dumps(signal_data, ensure_ascii=False) + '\n')

        # 第一次运行
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir)
        )

        worker1 = ExecutionWorker(config)

        async def run_once(worker):
            semaphore = asyncio.Semaphore(1)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_once(worker1))

        first_execution_count = worker1.stats["executions_success"]

        # 模拟重启（创建新的 Worker）
        worker2 = ExecutionWorker(config)
        asyncio.run(run_once(worker2))

        second_execution_count = worker2.stats["executions_success"]

        # 验证幂等性：重启后不应该重复执行
        assert second_execution_count == 0  # 新的 worker 应该从高水位开始，不处理已处理的信号

    def test_configuration_validation_smoke(self, temp_dir):
        """配置验证冒烟测试"""
        # 测试各种配置组合
        configs = [
            ExecutionConfig(mode="dry_run", symbols=["BTCUSDT"]),
            ExecutionConfig(mode="live", symbols=["BTCUSDT", "ETHUSDT"]),
            ExecutionConfig(sink_type="sqlite", symbols=["BTCUSDT"]),
            ExecutionConfig(rate_limit_qps=1, max_concurrency=1, symbols=["BTCUSDT"]),
            ExecutionConfig(rate_limit_qps=1000, max_concurrency=100, symbols=["BTCUSDT"]),
        ]

        for config in configs:
            config.output_dir = str(temp_dir)
            worker = ExecutionWorker(config)

            # 验证初始化成功
            assert worker.config == config
            assert worker.execution_store is not None
            assert worker.adapter is not None

    def test_error_resilience_smoke(self, temp_dir):
        """错误恢复能力冒烟测试"""
        # 创建包含各种问题的信号文件
        signals_data = [
            # 正常信号
            {
                "ts_ms": int(time.time() * 1000),
                "symbol": "BTCUSDT",
                "score": 0.8,
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok"
            },
            # 无效JSON（会被跳过）
            "invalid json line",
            # 另一个正常信号
            {
                "ts_ms": int(time.time() * 1000) + 1000,
                "symbol": "BTCUSDT",
                "score": 0.6,
                "z_ofi": 1.8,
                "z_cvd": -2.0,
                "regime": "bear",
                "div_type": "reversal",
                "confirm": True,
                "gating": "ok"
            }
        ]

        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        with open(signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            for signal in signals_data:
                if isinstance(signal, dict):
                    f.write(json.dumps(signal, ensure_ascii=False) + '\n')
                else:
                    f.write(signal + '\n')

        # 配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir)
        )

        worker = ExecutionWorker(config)

        # 运行（应该能处理错误而不崩溃）
        async def run_with_errors():
            semaphore = asyncio.Semaphore(1)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_with_errors())

        # 验证：应该处理了有效的信号，跳过无效的
        assert worker.stats["signals_processed"] >= 2  # 应该尝试处理所有行
        assert worker.stats["executions_success"] >= 2  # 应该成功处理2个有效信号

        # 验证数据库完整性
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats())
        assert stats["total_executions"] >= 2
