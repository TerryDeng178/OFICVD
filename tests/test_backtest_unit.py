# -*- coding: utf-8 -*-
"""TASK-B2: 回测单元测试

测试回测模块的核心组件：BacktestAdapter, BrokerSimulator, BacktestWriter
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from backtest.app import BacktestAdapter, BrokerSimulator, BacktestWriter


class TestBacktestAdapter:
    """BacktestAdapter单元测试"""

    def test_adapter_mode_validation(self):
        """测试适配器模式验证"""
        # 模式A需要features_dir
        with pytest.raises(ValueError, match="features_dir required for mode A"):
            BacktestAdapter('A', None, None)

        # 模式B需要signals_src
        with pytest.raises(ValueError, match="signals_src required for mode B"):
            BacktestAdapter('B', None, None)

    def test_signals_jsonl_iteration(self, tmp_path):
        """测试JSONL信号文件迭代"""
        # 创建测试数据
        signals_dir = tmp_path / "signals"
        btc_dir = signals_dir / "BTCUSDT"
        btc_dir.mkdir(parents=True)

        signals_file = btc_dir / "signals-20241113-10.jsonl"
        test_signals = [
            {"ts_ms": 1731470000000, "symbol": "BTCUSDT", "score": 1.0, "confirm": True},
            {"ts_ms": 1731470060000, "symbol": "BTCUSDT", "score": 0.5, "confirm": False}
        ]

        with signals_file.open("w") as f:
            for signal in test_signals:
                f.write(json.dumps(signal) + "\n")

        # 测试迭代
        adapter = BacktestAdapter('B', None, f"jsonl://{signals_dir}", symbols={"BTCUSDT"})
        signals = list(adapter.iter_signals())

        assert len(signals) == 2
        assert signals[0]["score"] == 1.0
        assert signals[1]["confirm"] is False

    def test_signals_sqlite_iteration(self, tmp_path):
        """测试SQLite信号数据库迭代"""
        import sqlite3

        db_path = tmp_path / "signals.db"
        conn = sqlite3.connect(str(db_path))

        # 创建表
        conn.execute("""
            CREATE TABLE signals (
                ts_ms INTEGER, symbol TEXT, score REAL,
                confirm INTEGER, run_id TEXT
            )
        """)

        # 插入测试数据
        test_signals = [
            (1731470000000, "BTCUSDT", 1.0, 1, "test_run"),
            (1731470060000, "BTCUSDT", 0.5, 0, "test_run")
        ]
        conn.executemany("INSERT INTO signals VALUES (?, ?, ?, ?, ?)", test_signals)
        conn.commit()
        conn.close()

        # 测试迭代
        adapter = BacktestAdapter('B', None, f"sqlite://{db_path}", symbols={"BTCUSDT"})
        signals = list(adapter.iter_signals())

        assert len(signals) == 2
        assert signals[0]["score"] == 1.0
        assert signals[1]["confirm"] == 0


class TestBrokerSimulator:
    """BrokerSimulator单元测试"""

    def test_order_execution(self):
        """测试订单执行"""
        config = {
            "fee_bps_maker": -25,  # 负数表示返佣
            "fee_bps_taker": 75,
            "slippage_bps": 10,
            "latency_ms": 50
        }

        broker = BrokerSimulator(config)

        order = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.001,
            "maker": True
        }

        trade = broker.execute_order(order)

        assert trade is not None
        assert trade["symbol"] == "BTCUSDT"
        assert trade["side"] == "BUY"
        assert trade["maker"] is True
        assert "fee_bps" in trade
        assert "slip_bps" in trade
        assert "lat_ms" in trade

    def test_fee_calculation(self):
        """测试手续费计算"""
        config = {"fee_bps_maker": -20, "fee_bps_taker": 80}
        broker = BrokerSimulator(config)

        # Maker订单（返佣）
        maker_order = {"symbol": "BTCUSDT", "side": "BUY", "price": 50000, "quantity": 0.001, "maker": True}
        maker_trade = broker.execute_order(maker_order)
        assert maker_trade["fee_bps"] == -20

        # Taker订单
        taker_order = {"symbol": "BTCUSDT", "side": "BUY", "price": 50000, "quantity": 0.001, "maker": False}
        taker_trade = broker.execute_order(taker_order)
        assert taker_trade["fee_bps"] == 80


class TestBacktestWriter:
    """BacktestWriter单元测试"""

    def test_writer_initialization(self, tmp_path):
        """测试写入器初始化"""
        writer = BacktestWriter(tmp_path, "test_run", write_signals=True, emit_sqlite=False)

        assert (tmp_path / "test_run").exists()
        assert (tmp_path / "test_run" / "signals.jsonl").exists()
        assert (tmp_path / "test_run" / "trades.jsonl").exists()
        assert (tmp_path / "test_run" / "pnl_daily.jsonl").exists()

        writer.close()

    def test_signal_writing(self, tmp_path):
        """测试信号写入"""
        writer = BacktestWriter(tmp_path, "test_run", write_signals=True, emit_sqlite=False)

        signal = {
            "ts_ms": 1731470000000,
            "symbol": "BTCUSDT",
            "score": 1.0,
            "confirm": True
        }

        writer.write_signal(signal)
        writer.close()

        # 验证文件内容
        signals_file = tmp_path / "test_run" / "signals.jsonl"
        with signals_file.open() as f:
            lines = f.readlines()
            assert len(lines) == 1
            parsed = json.loads(lines[0].strip())
            assert parsed["symbol"] == "BTCUSDT"

    def test_trade_writing(self, tmp_path):
        """测试交易写入"""
        writer = BacktestWriter(tmp_path, "test_run", write_signals=True, emit_sqlite=False)

        trade = {
            "ts_ms": 1731470000000,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "exec_px": 50000.0,
            "qty": 0.001
        }

        writer.write_trade(trade)
        writer.close()

        # 验证文件内容
        trades_file = tmp_path / "test_run" / "trades.jsonl"
        with trades_file.open() as f:
            lines = f.readlines()
            assert len(lines) == 1
            parsed = json.loads(lines[0].strip())
            assert parsed["symbol"] == "BTCUSDT"

    def test_manifest_writing(self, tmp_path):
        """测试清单文件写入"""
        writer = BacktestWriter(tmp_path, "test_run", write_signals=True, emit_sqlite=False)

        manifest = {
            "run_id": "test_run",
            "mode": "A",
            "start": "2025-11-12T00:00:00Z"
        }

        writer.write_manifest(manifest)
        writer.close()

        # 验证文件内容
        manifest_file = tmp_path / "test_run" / "run_manifest.json"
        assert manifest_file.exists()

        with manifest_file.open() as f:
            parsed = json.load(f)
            assert parsed["run_id"] == "test_run"
            assert parsed["mode"] == "A"
