# -*- coding: utf-8 -*-
"""ExecutionStore 单元测试

测试幂等插入、高水位计算、状态更新等核心功能
"""
import pytest
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

from src.alpha_core.executors.execution_store import ExecutionStore, ExecutionRecord


class TestExecutionStore:
    """ExecutionStore 单元测试"""

    @pytest.fixture
    def temp_db_path(self):
        """临时数据库路径"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        # 清理（Windows 下可能有锁定问题，忽略错误）
        try:
            if db_path.exists():
                db_path.unlink()
        except (OSError, PermissionError):
            pass  # 忽略清理错误

    @pytest.fixture
    def store(self, temp_db_path):
        """创建测试用的 ExecutionStore"""
        return ExecutionStore(temp_db_path)

    def test_initialization(self, store):
        """测试初始化"""
        assert store.db_path.exists()

        # 检查表是否创建
        conn = store._connection
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='executions'")
        assert cursor.fetchone() is not None

        # 检查索引是否创建
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_executions_symbol_ts'")
        assert cursor.fetchone() is not None

    def test_record_execution_basic(self, store):
        """测试基本执行记录"""
        record = ExecutionRecord(
            exec_ts_ms=1000,
            signal_ts_ms=900,
            symbol="BTCUSDT",
            signal_id="test_signal_1",
            order_id="test_order_1",
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

        # 记录执行
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(store.record_execution(record))
        finally:
            loop.close()

        # 验证记录存在
        conn = store._connection
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM executions WHERE signal_id = ?", ("test_signal_1",))
        row = cursor.fetchone()
        assert row is not None
        assert row[3] == "BTCUSDT"  # symbol
        assert row[4] == "test_signal_1"  # signal_id
        assert row[5] == "test_order_1"  # order_id
        assert row[11] == "success"  # status

    def test_idempotency(self, store):
        """测试幂等性"""
        record1 = ExecutionRecord(
            exec_ts_ms=1000,
            signal_ts_ms=900,
            symbol="BTCUSDT",
            signal_id="test_signal_1",
            order_id="test_order_1",
            side="long",
            qty=100.0,
            price=50000.0,
            gating="ok",
            guard_reason=None,
            status="success",
            error_code=None,
            error_msg=None,
            meta_json='{}'
        )

        record2 = ExecutionRecord(
            exec_ts_ms=2000,  # 不同的执行时间
            signal_ts_ms=900,
            symbol="BTCUSDT",
            signal_id="test_signal_1",  # 相同信号ID
            order_id="test_order_1",    # 相同订单ID
            side="long",
            qty=100.0,
            price=50000.0,
            gating="ok",
            guard_reason=None,
            status="success",
            error_code=None,
            error_msg=None,
            meta_json='{}'
        )

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 第一次记录应该成功
            result1 = loop.run_until_complete(store.record_execution(record1))
            # 这里没有返回值，检查数据库

            # 第二次记录应该被幂等处理（不插入）
            result2 = loop.run_until_complete(store.record_execution(record2))
        finally:
            loop.close()

        # 验证只插入了一条记录
        conn = store._connection
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM executions WHERE signal_id = ?", ("test_signal_1",))
        count = cursor.fetchone()[0]
        assert count == 1

    def test_is_already_executed(self, store):
        """测试已执行检查"""
        record = ExecutionRecord(
            exec_ts_ms=1000,
            signal_ts_ms=900,
            symbol="BTCUSDT",
            signal_id="test_signal_1",
            order_id="test_order_1",
            side="long",
            qty=100.0,
            price=50000.0,
            gating="ok",
            guard_reason=None,
            status="success",
            error_code=None,
            error_msg=None,
            meta_json='{}'
        )

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 初始状态应该返回 False
            result = loop.run_until_complete(store.is_already_executed("BTCUSDT", "test_signal_1", "test_order_1"))
            assert result is False

            # 记录执行后应该返回 True
            loop.run_until_complete(store.record_execution(record))
            result = loop.run_until_complete(store.is_already_executed("BTCUSDT", "test_signal_1", "test_order_1"))
            assert result is True

            # 不同的订单ID应该返回 False
            result = loop.run_until_complete(store.is_already_executed("BTCUSDT", "test_signal_1", "different_order"))
            assert result is False
        finally:
            loop.close()

    def test_get_execution_stats(self, store):
        """测试执行统计"""
        # 插入一些测试数据
        records = [
            ExecutionRecord(1000, 900, "BTCUSDT", "sig1", "ord1", "long", 100.0, 50000.0, "ok", None, "success", None, None, '{}'),
            ExecutionRecord(2000, 1900, "BTCUSDT", "sig2", "ord2", "short", 50.0, 51000.0, "ok", None, "failed", "ERROR", "test error", '{}'),
            ExecutionRecord(3000, 2900, "ETHUSDT", "sig3", "ord3", "long", 10.0, 3000.0, "ok", None, "success", None, None, '{}'),
        ]

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for record in records:
                loop.run_until_complete(store.record_execution(record))

            # 获取全局统计
            stats = loop.run_until_complete(store.get_execution_stats())
            assert stats["total_executions"] == 3
            assert stats["status_counts"]["success"] == 2
            assert stats["status_counts"]["failed"] == 1
            assert stats["latest_exec_ts_ms"] == 3000
            assert stats["latest_signal_ts_ms"] == 2900

            # 获取 BTCUSDT 统计
            stats_btc = loop.run_until_complete(store.get_execution_stats("BTCUSDT"))
            assert stats_btc["total_executions"] == 2
            assert stats_btc["status_counts"]["success"] == 1
            assert stats_btc["status_counts"]["failed"] == 1
        finally:
            loop.close()

    def test_export_to_jsonl(self, store, tmp_path):
        """测试导出到 JSONL"""
        record = ExecutionRecord(
            exec_ts_ms=1000,
            signal_ts_ms=900,
            symbol="BTCUSDT",
            signal_id="test_signal_1",
            order_id="test_order_1",
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

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 插入记录
            loop.run_until_complete(store.record_execution(record))

            # 导出到 JSONL
            jsonl_path = tmp_path / "export.jsonl"
            count = loop.run_until_complete(store.export_executions_to_jsonl(jsonl_path))

            assert count == 1
            assert jsonl_path.exists()

            # 验证导出的内容
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                assert len(lines) == 1

                data = json.loads(lines[0])
                assert data["symbol"] == "BTCUSDT"
                assert data["signal_id"] == "test_signal_1"
                assert data["status"] == "success"
                assert data["meta"]["test"] == "value"
        finally:
            loop.close()

    def test_high_water_mark(self, store):
        """测试高水位标记"""
        # 初始高水位应该是 0
        assert store.get_high_water_mark("BTCUSDT") == 0

        # 插入记录后，高水位应该更新
        record = ExecutionRecord(
            exec_ts_ms=1000,
            signal_ts_ms=900,
            symbol="BTCUSDT",
            signal_id="test_signal_1",
            order_id="test_order_1",
            side="long",
            qty=100.0,
            price=50000.0,
            gating="ok",
            guard_reason=None,
            status="success",
            error_code=None,
            error_msg=None,
            meta_json='{}'
        )

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(store.record_execution(record))
            # 注意：高水位是在记录执行时更新的
            assert store.get_high_water_mark("BTCUSDT") == 900
        finally:
            loop.close()

    def test_close(self, store):
        """测试关闭"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(store.close())
            # 关闭后连接应该为 None
            assert store._connection is None
        finally:
            loop.close()
