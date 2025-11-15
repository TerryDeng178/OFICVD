# -*- coding: utf-8 -*-
"""ExecutionWorker 端到端测试

测试完整的业务流：信号生成 -> 执行 -> 结果验证
"""
import pytest
import tempfile
import json
import subprocess
import time
import signal
import os
from pathlib import Path
from unittest.mock import patch

from src.alpha_core.executors.execution_worker import ExecutionWorker, ExecutionConfig
from src.alpha_core.executors.execution_store import ExecutionStore


class TestExecutionE2E:
    """端到端测试"""

    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        # 清理
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)

    def test_complete_execution_flow(self, temp_dir):
        """测试完整执行流程"""
        # 1. 准备测试数据：创建各种类型的信号
        test_signals = [
            # 成功的做多信号
            {
                "ts_ms": 1000000,
                "symbol": "BTCUSDT",
                "score": 0.9,
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            },
            # 成功的做空信号
            {
                "ts_ms": 2000000,
                "symbol": "BTCUSDT",
                "score": -0.8,
                "z_ofi": -1.8,
                "z_cvd": 2.0,
                "regime": "bear",
                "div_type": "reversal",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            },
            # 被跳过的信号（未确认）
            {
                "ts_ms": 3000000,
                "symbol": "BTCUSDT",
                "score": 0.7,
                "z_ofi": 1.5,
                "z_cvd": -1.2,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": False,  # 未确认
                "gating": "ok",
                "guard_reason": None
            },
            # 被跳过的信号（gating 不通过）
            {
                "ts_ms": 4000000,
                "symbol": "BTCUSDT",
                "score": 0.6,
                "z_ofi": 1.2,
                "z_cvd": -0.8,
                "regime": "sideways",
                "div_type": "noise",
                "confirm": True,
                "gating": "low_consistency",  # gating 不通过
                "guard_reason": "spread_bps_exceeded"
            },
            # 另一个交易对的信号
            {
                "ts_ms": 5000000,
                "symbol": "ETHUSDT",
                "score": 0.8,
                "z_ofi": 2.3,
                "z_cvd": -1.8,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            }
        ]

        # 2. 创建信号文件
        btc_signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        btc_signal_dir.mkdir(parents=True, exist_ok=True)

        eth_signal_dir = temp_dir / "ready" / "signal" / "ETHUSDT"
        eth_signal_dir.mkdir(parents=True, exist_ok=True)

        # 分离不同交易对的信号
        btc_signals = [s for s in test_signals if s["symbol"] == "BTCUSDT"]
        eth_signals = [s for s in test_signals if s["symbol"] == "ETHUSDT"]

        with open(btc_signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            for signal in btc_signals:
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        with open(eth_signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            for signal in eth_signals:
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        # 3. 配置和运行 ExecutionWorker
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT", "ETHUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=100,
            max_concurrency=5
        )

        worker = ExecutionWorker(config)

        # 运行 Worker
        import asyncio

        async def run_worker():
            # 启动处理任务
            tasks = []
            semaphore = asyncio.Semaphore(config.max_concurrency)

            for symbol in config.symbols:
                task = asyncio.create_task(worker._process_symbol_signals(symbol, semaphore))
                tasks.append(task)

            # 等待足够时间处理所有信号
            await asyncio.sleep(0.5)

            # 优雅关闭
            for task in tasks:
                task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run(run_worker())

        # 4. 验证执行结果
        store = ExecutionStore(temp_dir / "executions" / "executions.db")

        # 总体统计
        total_stats = asyncio.run(store.get_execution_stats())
        assert total_stats["total_executions"] == 3  # 2个BTC成功 + 1个ETH成功

        # BTCUSDT 统计：应该有2个成功执行（跳过2个）
        btc_stats = asyncio.run(store.get_execution_stats("BTCUSDT"))
        assert btc_stats["total_executions"] == 2

        # ETHUSDT 统计：应该有1个成功执行
        eth_stats = asyncio.run(store.get_execution_stats("ETHUSDT"))
        assert eth_stats["total_executions"] == 1

        # 5. 验证执行记录详情
        # 导出为 JSONL 进行详细验证
        jsonl_path = temp_dir / "execution_results.jsonl"
        count = asyncio.run(store.export_executions_to_jsonl(jsonl_path))
        assert count == 3

        # 读取并验证记录
        executions = []
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                executions.append(json.loads(line))

        # 按交易对分组验证
        btc_executions = [e for e in executions if e["symbol"] == "BTCUSDT"]
        eth_executions = [e for e in executions if e["symbol"] == "ETHUSDT"]

        assert len(btc_executions) == 2
        assert len(eth_executions) == 1

        # 验证 BTC 执行详情
        for exec_record in btc_executions:
            assert exec_record["status"] == "success"
            assert exec_record["gating"] == "ok"
            assert exec_record["qty"] > 0  # 应该有数量
            assert exec_record["side"] in ["long", "short"]
            assert "dryrun:" in exec_record["order_id"]
            # 验证 meta 中包含 dry_run 信息
            meta = json.loads(exec_record.get("meta_json", "{}"))
            assert meta.get("dry_run") is True

        # 验证 ETH 执行详情
        eth_exec = eth_executions[0]
        assert eth_exec["status"] == "success"
        assert eth_exec["symbol"] == "ETHUSDT"
        assert eth_exec["side"] == "long"  # score=0.8 应该做多
        assert eth_exec["qty"] == 100.0  # 默认数量

        # 6. 验证 Worker 统计
        assert worker.stats["signals_processed"] >= 5  # 至少处理了5个信号
        assert worker.stats["executions_success"] == 3  # 3个成功执行
        assert worker.stats["executions_skip"] >= 2     # 至少2个跳过

    def test_execution_output_formats(self, temp_dir):
        """测试执行输出格式"""
        # 创建测试信号
        signal = {
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
        }

        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        with open(signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        # 配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir)
        )

        worker = ExecutionWorker(config)

        # 运行
        import asyncio

        async def run_worker():
            semaphore = asyncio.Semaphore(1)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_worker())

        # 验证数据库输出
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats())
        assert stats["total_executions"] == 1

        # 验证 JSONL 导出
        jsonl_path = temp_dir / "test_export.jsonl"
        count = asyncio.run(store.export_executions_to_jsonl(jsonl_path))
        assert count == 1

        with open(jsonl_path, 'r', encoding='utf-8') as f:
            data = json.loads(f.read().strip())

        # 验证所有必需字段都存在
        required_fields = [
            "exec_ts_ms", "signal_ts_ms", "symbol", "signal_id", "order_id",
            "side", "qty", "gating", "status", "meta_json"
        ]

        for field in required_fields:
            assert field in data

        # 验证元数据
        meta = json.loads(data["meta_json"])
        assert meta.get("dry_run") is True
        assert "execution_mode" in meta

    def test_error_handling_and_recovery(self, temp_dir):
        """测试错误处理和恢复"""
        # 创建包含无效信号的文件
        signals_data = [
            # 有效信号
            {
                "ts_ms": 1000000,
                "symbol": "BTCUSDT",
                "score": 0.8,
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok"
            },
            # 无效信号（缺少必要字段）
            {
                "ts_ms": 2000000,
                "symbol": "BTCUSDT"
                # 缺少其他必要字段
            },
            # 另一个有效信号
            {
                "ts_ms": 3000000,
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
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        # 配置
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir)
        )

        worker = ExecutionWorker(config)

        # 运行（应该能处理无效信号而不崩溃）
        import asyncio

        async def run_worker():
            semaphore = asyncio.Semaphore(1)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_worker())

        # 验证：应该只处理了有效的信号
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats("BTCUSDT"))
        assert stats["total_executions"] == 2  # 应该只处理了2个有效信号

    def test_performance_under_load(self, temp_dir):
        """测试负载下的性能"""
        # 创建大量信号进行压力测试
        num_signals = 100
        signals_data = []

        for i in range(num_signals):
            signals_data.append({
                "ts_ms": 1000000 + i * 10000,  # 递增时间戳
                "symbol": "BTCUSDT",
                "score": 0.8 if i % 2 == 0 else -0.8,  # 交替正负分数
                "z_ofi": 2.1,
                "z_cvd": -1.5,
                "regime": "bull",
                "div_type": "momentum",
                "confirm": True,
                "gating": "ok",
                "guard_reason": None
            })

        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        with open(signal_dir / "signals_20241114_1200.jsonl", 'w', encoding='utf-8') as f:
            for signal in signals_data:
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        # 配置高并发
        config = ExecutionConfig(
            mode="dry_run",
            symbols=["BTCUSDT"],
            sink_type="jsonl",
            output_dir=str(temp_dir),
            rate_limit_qps=1000,  # 高频
            max_concurrency=20
        )

        worker = ExecutionWorker(config)

        # 记录开始时间
        start_time = time.time()

        # 运行
        import asyncio

        async def run_worker():
            semaphore = asyncio.Semaphore(config.max_concurrency)
            task = asyncio.create_task(worker._process_symbol_signals("BTCUSDT", semaphore))
            await asyncio.sleep(3.0)  # 运行足够时间处理所有信号
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_worker())

        end_time = time.time()
        duration = end_time - start_time

        # 验证结果
        store = ExecutionStore(temp_dir / "executions" / "executions.db")
        stats = asyncio.run(store.get_execution_stats("BTCUSDT"))

        # 应该处理了所有信号
        assert stats["total_executions"] == num_signals

        # 性能检查：每秒至少处理10个信号
        signals_per_second = num_signals / duration
        assert signals_per_second >= 10, f"性能不足: {signals_per_second} signals/sec"

        # 验证没有内存泄漏（Worker 统计应该合理）
        assert worker.stats["signals_processed"] == num_signals
        assert worker.stats["executions_success"] == num_signals
