# -*- coding: utf-8 -*-
"""Signal Writer v2 Tests

测试 signal/v2 writer 的 JSONL/SQLite 双 Sink 功能
"""

import pytest
import tempfile
import shutil
import json
import sqlite3
from pathlib import Path

from src.alpha_core.signals.signal_schema import SignalV2, SideHint, Regime, DecisionCode
from src.alpha_core.signals.signal_writer import SignalWriterV2


class TestSignalWriterV2:
    """Signal Writer v2 测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_write_jsonl_only(self, temp_dir):
        """测试仅 JSONL 写入"""
        writer = SignalWriterV2(temp_dir, sink_kind="jsonl")
        
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="test-1",
            score=2.41,
            side_hint=SideHint.BUY,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            config_hash="test",
            run_id="r42",
        )
        
        writer.write(signal)
        writer.close()
        
        # 验证 JSONL 文件
        jsonl_file = temp_dir / "ready" / "signal" / "BTCUSDT" / "signals-20241112-00.jsonl"
        assert jsonl_file.exists()
        
        with jsonl_file.open("r", encoding="utf-8") as f:
            line = f.readline().strip()
            data = json.loads(line)
            assert data["schema_version"] == "signal/v2"
            assert data["symbol"] == "BTCUSDT"
            assert data["signal_id"] == "test-1"
    
    def test_write_sqlite_only(self, temp_dir):
        """测试仅 SQLite 写入"""
        writer = SignalWriterV2(temp_dir, sink_kind="sqlite")
        
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="test-1",
            score=2.41,
            side_hint=SideHint.BUY,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            config_hash="test",
            run_id="r42",
        )
        
        writer.write(signal)
        writer.close()
        
        # 验证 SQLite 数据库（默认使用 signals_v2.db）
        db_path = temp_dir / "signals_v2.db"
        assert db_path.exists()
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT * FROM signals WHERE signal_id = ?", ("test-1",))
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
    
    def test_write_dual_sink(self, temp_dir):
        """测试双 Sink 写入（JSONL + SQLite）"""
        writer = SignalWriterV2(temp_dir, sink_kind="dual")
        
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="test-1",
            score=2.41,
            side_hint=SideHint.BUY,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            config_hash="test",
            run_id="r42",
        )
        
        writer.write(signal)
        writer.close()
        
        # 验证 JSONL
        jsonl_file = temp_dir / "ready" / "signal" / "BTCUSDT" / "signals-20241112-00.jsonl"
        assert jsonl_file.exists()
        
        # 验证 SQLite
        db_path = temp_dir / "signals_v2.db"
        assert db_path.exists()
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM signals WHERE signal_id = ?", ("test-1",))
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 1
    
    def test_write_multiple_signals(self, temp_dir):
        """测试写入多个信号"""
        writer = SignalWriterV2(temp_dir, sink_kind="dual")
        
        for i in range(10):
            signal = SignalV2(
                ts_ms=1731369600123 + i * 1000,
                symbol="BTCUSDT",
                signal_id=f"test-{i}",
                score=2.41 + i * 0.1,
                side_hint=SideHint.BUY,
                regime=Regime.TREND,
                gating=1,
                confirm=True,
                expiry_ms=60000,
                decision_code=DecisionCode.OK,
                config_hash="test",
                run_id="r42",
            )
            writer.write(signal)
        
        writer.close()
        
        # 验证 JSONL（应该有 10 行）
        jsonl_file = temp_dir / "ready" / "signal" / "BTCUSDT" / "signals-20241112-00.jsonl"
        with jsonl_file.open("r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            assert len(lines) == 10
        
        # 验证 SQLite（应该有 10 条记录）
        db_path = temp_dir / "signals_v2.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM signals")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 10
    
    def test_write_thread_safety(self, temp_dir):
        """测试线程安全性"""
        import threading
        
        writer = SignalWriterV2(temp_dir, sink_kind="dual")
        errors = []
        
        def write_signals(thread_id: int):
            try:
                for i in range(10):
                    signal = SignalV2(
                        ts_ms=1731369600123 + thread_id * 10000 + i * 1000,
                        symbol="BTCUSDT",
                        signal_id=f"thread-{thread_id}-{i}",
                        score=2.41,
                        side_hint=SideHint.BUY,
                        regime=Regime.TREND,
                        gating=1,
                        confirm=True,
                        expiry_ms=60000,
                        decision_code=DecisionCode.OK,
                        config_hash="test",
                        run_id="r42",
                    )
                    writer.write(signal)
            except Exception as e:
                errors.append((thread_id, str(e)))
        
        # 启动多个线程
        threads = []
        for thread_id in range(5):
            thread = threading.Thread(target=write_signals, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        writer.close()
        
        # 验证无错误
        assert len(errors) == 0
        
        # 验证数据完整性（应该有 50 条记录）
        db_path = temp_dir / "signals_v2.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM signals")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 50

