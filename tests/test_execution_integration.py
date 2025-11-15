# -*- coding: utf-8 -*-
"""ExecutionWorker 集成测试

测试 ExecutionWorker 与 signal_server 的联合运行
"""
import pytest
import tempfile
import json
import subprocess
import time
import signal
from pathlib import Path
from unittest.mock import patch

from src.alpha_core.executors.execution_worker import ExecutionWorker, ExecutionConfig
from src.alpha_core.executors.execution_store import ExecutionStore


class TestExecutionIntegration:
    """执行集成测试"""

    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        # 清理
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)

    def create_signal_file(self, signal_dir: Path, filename: str, signals_data: list):
        """创建信号文件"""
        signal_dir.mkdir(parents=True, exist_ok=True)
        signal_file = signal_dir / filename

        with open(signal_file, 'w', encoding='utf-8') as f:
            for signal_data in signals_data:
                f.write(json.dumps(signal_data, ensure_ascii=False) + '\n')

        return signal_file

    def test_jsonl_signal_consumption(self, temp_dir):
        """测试 JSONL 信号消费集成"""
        # 创建测试信号数据
        signals_data = [
            {
                "ts_ms": 1000000,
                "symbol": "BTCUSDT",
                "score": 0.8,
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            },
            {
                "ts_ms": 2000000,
                "symbol": "BTCUSDT",
                "score": 0.6,
                "z_ofi": 1.8,
                "z_cvd": -2.0,
                "regime": "bear",
                "div_type": "reversal",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            },
            {
                "ts_ms": 3000000,
                "symbol": "ETHUSDT",
                "score": 0.9,
                "z_ofi": 2.5,
                "z_cvd": 1.2,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": False,  # 未确认，应该跳过
                "gating": "ok",
                "guard_reason": None
            }
        ]

        # 创建信号文件
        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_file = self.create_signal_file(signal_dir, "signals_20241114_1200.jsonl", signals_data[:2])

        # ETH 信号文件
        eth_signal_dir = temp_dir / "ready" / "signal" / "ETHUSDT"
        eth_signal_file = self.create_signal_file(eth_signal_dir, "signals_20241114_1200.jsonl", signals_data[2:])

        # 创建配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT", "ETHUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=100,  # 高频测试
            max_concurrency=5
        )

        # 创建 Worker
        worker = ExecutionWorker(config)

        # 运行 Worker 一段时间
        import asyncio

        async def run_worker_briefly():
            # 创建任务
            tasks = []
            for symbol in config.symbols:
                task = asyncio.create_task(worker._process_symbol_signals(symbol, asyncio.Semaphore(5)))
                tasks.append(task)

            # 运行一小段时间
            await asyncio.sleep(0.1)

            # 取消任务
            for task in tasks:
                task.cancel()

            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass

        asyncio.run(run_worker_briefly())

        # 验证结果
        store = ExecutionStore(temp_dir / "executions" / "executions.db")

        # 检查执行统计
        stats = asyncio.run(store.get_execution_stats())
        assert stats["total_executions"] >= 2  # BTCUSDT 的两条记录

        # 检查 BTCUSDT 的执行记录
        btc_stats = asyncio.run(store.get_execution_stats("BTCUSDT"))
        assert btc_stats["total_executions"] == 2

        # 检查 ETHUSDT（应该跳过未确认的信号）
        eth_stats = asyncio.run(store.get_execution_stats("ETHUSDT"))
        assert eth_stats["total_executions"] == 0  # 未确认信号被跳过

    def test_sqlite_signal_consumption(self, temp_dir):
        """测试 SQLite 信号消费集成"""
        # 创建 SQLite 数据库和数据
        import sqlite3

        db_path = temp_dir / "signals.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 创建 signals 表
        cursor.execute("""
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY,
                ts_ms INTEGER,
                symbol TEXT,
                score REAL,
                z_ofi REAL,
                z_cvd REAL,
                regime TEXT,
                div_type TEXT,
                confirm BOOLEAN,
                gating TEXT,
                guard_reason TEXT
            )
        """)

        # 插入测试数据
        signals_data = [
            (1, 1000000, "BTCUSDT", 0.8, 2.1, -1.5, "bull", "momentum", True, "ok", None),
            (2, 2000000, "BTCUSDT", 0.6, 1.8, -2.0, "bear", "reversal", True, "ok", None),
        ]

        cursor.executemany("""
            INSERT INTO signals (id, ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, confirm, gating, guard_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, signals_data)

        conn.commit()
        conn.close()

        # 创建配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="sqlite",
            output_dir=str(temp_dir),
            rate_limit_qps=100,
            max_concurrency=5
        )

        # 创建 Worker
        worker = ExecutionWorker(config)

        # 运行 Worker
        import asyncio

        async def run_worker_briefly():
            semaphore = asyncio.Semaphore(5)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))

            await asyncio.sleep(0.1)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_worker_briefly())

        # 验证结果
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats("BTCUSDT"))
        assert stats["total_executions"] >= 1

    def test_idempotency_across_restarts(self, temp_dir):
        """测试重启后的幂等性"""
        # 创建信号文件
        signals_data = [{
            "ts_ms": 1000000,
            "symbol": "BTCUSDT",
            "score": 0.8,
            "z_ofi": 2.1,
            "z_cvd": -1.5,
            "regime": "bull",
            "div_type": "momentum",
            "confirm": True,
            "gating": "ok",
            "guard_reason": None
        }]

        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        self.create_signal_file(signal_dir, "signals_20241114_1200.jsonl", signals_data)

        # 第一次运行
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir)
        )

        worker1 = ExecutionWorker(config)

        import asyncio

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

        # 检查第一次执行的结果
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats1 = asyncio.run(store.get_execution_stats("BTCUSDT"))
        first_count = stats1["total_executions"]

        # 第二次运行（模拟重启）
        worker2 = ExecutionWorker(config)
        asyncio.run(run_once(worker2))

        # 检查第二次执行的结果
        stats2 = asyncio.run(store.get_execution_stats("BTCUSDT"))
        second_count = stats2["total_executions"]

        # 应该没有增加新的执行记录（幂等）
        assert second_count == first_count

    def test_concurrent_processing(self, temp_dir):
        """测试并发处理"""
        # 创建多个交易对的信号
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

        for symbol in symbols:
            signals_data = [{
                "ts_ms": 1000000 + i * 1000000,
                "symbol": symbol,
                "score": 0.8,
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            } for i in range(3)]  # 每个交易对3个信号

            signal_dir = temp_dir / "ready" / "signal" / symbol
            self.create_signal_file(signal_dir, "signals_20241114_1200.jsonl", signals_data)

        # 创建配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=symbols,
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=1000,  # 高频
            max_concurrency=10
        )

        worker = ExecutionWorker(config)

        # 并发运行
        import asyncio

        async def run_concurrent():
            semaphore = asyncio.Semaphore(config.max_concurrency)
            tasks = []

            for symbol in symbols:
                task = asyncio.create_task(worker._process_symbol_signals(symbol, semaphore))
                tasks.append(task)

            await asyncio.sleep(0.2)  # 运行足够时间处理所有信号

            # 取消所有任务
            for task in tasks:
                task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run(run_concurrent())

        # 验证结果
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        total_stats = asyncio.run(store.get_execution_stats())

        # 应该处理了所有信号（3个交易对 * 3个信号 = 9个）
        assert total_stats["total_executions"] == 9

        # 验证每个交易对的统计
        for symbol in symbols:
            symbol_stats = asyncio.run(store.get_execution_stats(symbol))
            assert symbol_stats["total_executions"] == 3
