# -*- coding: utf-8 -*-
"""SignalStream 单元测试

测试 JSONL 和 SQLite 信号流的读取功能
"""
import pytest
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

from src.alpha_core.executors.signal_stream import (
    JsonlSignalStream,
    SqliteSignalStream,
    ExecutionSignal,
    create_signal_stream
)


class TestJsonlSignalStream:
    """JSONL 信号流测试"""

    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        # 清理
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)

    @pytest.fixture
    def jsonl_stream(self, temp_dir):
        """创建 JSONL 信号流"""
        return JsonlSignalStream(str(temp_dir), ["BTCUSDT", "ETHUSDT"])

    def create_test_signal_data(self):
        """创建测试信号数据"""
        return {
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

    def test_initialization(self, jsonl_stream):
        """测试初始化"""
        assert jsonl_stream.base_dir is not None
        assert jsonl_stream.symbols == ["BTCUSDT", "ETHUSDT"]
        assert jsonl_stream._high_water_marks == {}

    def test_signal_creation_from_dict(self):
        """测试从字典创建信号"""
        data = self.create_test_signal_data()
        signal = ExecutionSignal.from_dict(data)

        assert signal.ts_ms == 1000000
        assert signal.symbol == "BTCUSDT"
        assert signal.score == 0.8
        assert signal.z_ofi == 2.1
        assert signal.z_cvd == -1.5
        assert signal.regime == "bull"
        assert signal.div_type == "momentum"
        assert signal.confirm is True
        assert signal.gating == "ok"
        assert signal.guard_reason is None
        assert signal.signal_id is not None  # 应该生成 signal_id

    def test_signal_id_generation(self):
        """测试信号ID生成"""
        data1 = self.create_test_signal_data()
        data2 = self.create_test_signal_data()
        data2["ts_ms"] = 1000001  # 不同的时间戳

        signal1 = ExecutionSignal.from_dict(data1)
        signal2 = ExecutionSignal.from_dict(data2)

        # 相同数据的信号ID应该相同
        data3 = self.create_test_signal_data()
        signal3 = ExecutionSignal.from_dict(data3)
        assert signal1.signal_id == signal3.signal_id

        # 不同数据的信号ID应该不同
        assert signal1.signal_id != signal2.signal_id

    def test_iter_signals_empty_directory(self, jsonl_stream):
        """测试空目录迭代"""
        import asyncio

        async def test_iter():
            signals = []
            async for signal in jsonl_stream.iter_signals("BTCUSDT"):
                signals.append(signal)
            return signals

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            signals = loop.run_until_complete(test_iter())
            assert len(signals) == 0
        finally:
            loop.close()

    def test_iter_signals_with_files(self, jsonl_stream, temp_dir):
        """测试有文件的迭代"""
        # 创建测试文件
        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        # 创建信号文件
        signal_data = self.create_test_signal_data()
        signal_file = signal_dir / "signals_20241114_1200.jsonl"
        with open(signal_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(signal_data, ensure_ascii=False) + '\n')

        import asyncio

        async def test_iter():
            signals = []
            async for signal in jsonl_stream.iter_signals("BTCUSDT"):
                signals.append(signal)
            return signals

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            signals = loop.run_until_complete(test_iter())
            assert len(signals) == 1
            assert signals[0].symbol == "BTCUSDT"
            assert signals[0].score == 0.8
        finally:
            loop.close()

    def test_iter_signals_multiple_files_ordered(self, jsonl_stream, temp_dir):
        """测试多个文件按时间排序"""
        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        # 创建多个时间戳的文件
        base_data = {
            "symbol": "BTCUSDT",
            "z_ofi": 2.1,
            "z_cvd": -1.5,
            "regime": "bull",
            "div_type": "momentum",
            "confirm": True,
            "gating": "ok",
            "guard_reason": None
        }
        files_and_data = [
            ("signals_20241114_1100.jsonl", {**base_data, "ts_ms": 1000000, "score": 0.1}),
            ("signals_20241114_1200.jsonl", {**base_data, "ts_ms": 2000000, "score": 0.2}),
            ("signals_20241114_1000.jsonl", {**base_data, "ts_ms": 3000000, "score": 0.3}),  # 时间戳更早但文件名时间更晚
        ]

        for filename, data in files_and_data:
            with open(signal_dir / filename, 'w', encoding='utf-8') as f:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')

        import asyncio

        async def test_iter():
            signals = []
            async for signal in jsonl_stream.iter_signals("BTCUSDT"):
                signals.append(signal)
            return signals

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            signals = loop.run_until_complete(test_iter())
            # 应该按文件名时间排序：1000, 1100, 1200
            assert len(signals) == 3
            assert signals[0].score == 0.3  # 文件名时间最早
            assert signals[1].score == 0.1  # 文件名时间中间
            assert signals[2].score == 0.2  # 文件名时间最晚
        finally:
            loop.close()

    def test_high_water_mark_filtering(self, jsonl_stream, temp_dir):
        """测试高水位标记过滤"""
        signal_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signal_dir.mkdir(parents=True, exist_ok=True)

        # 设置高水位
        jsonl_stream.update_high_water_mark("BTCUSDT", 1500000)

        # 创建包含新旧信号的文件
        base_data = {
            "symbol": "BTCUSDT",
            "z_ofi": 2.1,
            "z_cvd": -1.5,
            "regime": "bull",
            "div_type": "momentum",
            "confirm": True,
            "gating": "ok",
            "guard_reason": None
        }
        signal_data = [
            {**base_data, "ts_ms": 1000000, "score": 0.1},  # 应该被跳过
            {**base_data, "ts_ms": 2000000, "score": 0.2},  # 应该被处理
        ]

        signal_file = signal_dir / "signals_20241114_1200.jsonl"
        with open(signal_file, 'w', encoding='utf-8') as f:
            for data in signal_data:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')

        import asyncio

        async def test_iter():
            signals = []
            async for signal in jsonl_stream.iter_signals("BTCUSDT"):
                signals.append(signal)
            return signals

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            signals = loop.run_until_complete(test_iter())
            assert len(signals) == 1
            assert signals[0].score == 0.2  # 只处理新的信号
        finally:
            loop.close()


class TestSqliteSignalStream:
    """SQLite 信号流测试"""

    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        # 清理
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)

    @pytest.fixture
    def sqlite_stream(self, temp_dir):
        """创建 SQLite 信号流"""
        return SqliteSignalStream(str(temp_dir), ["BTCUSDT", "ETHUSDT"])

    def create_test_db_with_data(self, sqlite_stream):
        """创建包含测试数据的数据库"""
        conn = sqlite_stream._get_connection()
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
        test_data = [
            (1, 1000000, "BTCUSDT", 0.8, 2.1, -1.5, "bull", "momentum", True, "ok", None),
            (2, 2000000, "BTCUSDT", 0.6, 1.8, -2.0, "bear", "reversal", True, "ok", None),
            (3, 3000000, "ETHUSDT", 0.9, 2.5, 1.2, "bull", "momentum", False, "low_consistency", "spread_too_high"),
        ]

        cursor.executemany("""
            INSERT INTO signals (id, ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, confirm, gating, guard_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, test_data)

        conn.commit()
        return test_data

    def test_initialization(self, sqlite_stream):
        """测试初始化"""
        assert sqlite_stream.base_dir is not None
        assert sqlite_stream.symbols == ["BTCUSDT", "ETHUSDT"]

    def test_iter_signals_basic(self, sqlite_stream):
        """测试基本信号迭代"""
        self.create_test_db_with_data(sqlite_stream)

        import asyncio

        async def test_iter():
            signals = []
            async for signal in sqlite_stream.iter_signals("BTCUSDT"):
                signals.append(signal)
            return signals

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            signals = loop.run_until_complete(test_iter())
            assert len(signals) == 2  # BTCUSDT 的两条记录
            assert all(s.symbol == "BTCUSDT" for s in signals)
            assert signals[0].score == 0.8
            assert signals[1].score == 0.6
        finally:
            loop.close()

    def test_iter_signals_high_water_mark(self, sqlite_stream):
        """测试高水位标记过滤"""
        self.create_test_db_with_data(sqlite_stream)

        # 设置高水位
        sqlite_stream.update_high_water_mark("BTCUSDT", 1500000)

        import asyncio

        async def test_iter():
            signals = []
            async for signal in sqlite_stream.iter_signals("BTCUSDT"):
                signals.append(signal)
            return signals

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            signals = loop.run_until_complete(test_iter())
            assert len(signals) == 1  # 只应该有一条记录（ts_ms > 1500000）
            assert signals[0].ts_ms == 2000000
        finally:
            loop.close()

    def test_close(self, sqlite_stream):
        """测试关闭"""
        sqlite_stream.close()
        assert len(sqlite_stream._connections) == 0


class TestSignalStreamFactory:
    """信号流工厂测试"""

    def test_create_jsonl_stream(self, tmp_path):
        """测试创建 JSONL 流"""
        stream = create_signal_stream("jsonl", str(tmp_path), ["BTCUSDT"])
        assert isinstance(stream, JsonlSignalStream)

    def test_create_sqlite_stream(self, tmp_path):
        """测试创建 SQLite 流"""
        stream = create_signal_stream("sqlite", str(tmp_path), ["BTCUSDT"])
        assert isinstance(stream, SqliteSignalStream)

    def test_create_sqlite_stream_with_db_name(self, tmp_path):
        """测试创建 SQLite 流时指定数据库名"""
        stream = create_signal_stream("sqlite", str(tmp_path), ["BTCUSDT"], db_name="custom.db")
        assert isinstance(stream, SqliteSignalStream)
        assert stream.db_path.name == "custom.db"

    def test_create_invalid_type(self, tmp_path):
        """测试创建无效类型"""
        with pytest.raises(ValueError):
            create_signal_stream("invalid", str(tmp_path), ["BTCUSDT"])
