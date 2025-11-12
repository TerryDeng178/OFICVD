# -*- coding: utf-8 -*-
"""Executor Integration Tests

集成测试：signals.jsonl → BacktestExecutor → exec_log.jsonl
"""

import json
import pytest
import tempfile
from pathlib import Path

from alpha_core.executors import BacktestExecutor, Order, Side
from mcp.strategy_server.app import (
    read_signals_from_jsonl,
    read_signals_from_sqlite,
    signal_to_order,
    process_signals,
)


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_signals(temp_output_dir):
    """创建示例信号文件"""
    signals_dir = temp_output_dir / "ready" / "signal" / "BTCUSDT"
    signals_dir.mkdir(parents=True, exist_ok=True)
    
    signals_file = signals_dir / "signals_20241112_1200.jsonl"
    
    # 创建示例信号
    signals = [
        {
            "ts_ms": 1731379200000,
            "symbol": "BTCUSDT",
            "score": 0.8,
            "z_ofi": 1.2,
            "z_cvd": 0.9,
            "regime": "active",
            "div_type": None,
            "signal_type": "buy",
            "confirm": True,
            "gating": False,
            "guard_reason": None,
            "run_id": "test-run",
            "mid_price": 50000.0,
        },
        {
            "ts_ms": 1731379201000,
            "symbol": "BTCUSDT",
            "score": -0.7,
            "z_ofi": -1.1,
            "z_cvd": -0.8,
            "regime": "active",
            "div_type": None,
            "signal_type": "sell",
            "confirm": True,
            "gating": False,
            "guard_reason": None,
            "run_id": "test-run",
            "mid_price": 51000.0,
        },
        {
            "ts_ms": 1731379202000,
            "symbol": "BTCUSDT",
            "score": 0.3,
            "z_ofi": 0.5,
            "z_cvd": 0.2,
            "regime": "quiet",
            "div_type": None,
            "signal_type": "neutral",
            "confirm": False,  # 未确认信号
            "gating": False,
            "guard_reason": None,
            "run_id": "test-run",
            "mid_price": 50500.0,
        },
        {
            "ts_ms": 1731379203000,
            "symbol": "BTCUSDT",
            "score": 0.9,
            "z_ofi": 1.5,
            "z_cvd": 1.2,
            "regime": "active",
            "div_type": None,
            "signal_type": "strong_buy",
            "confirm": True,
            "gating": True,  # 被门控
            "guard_reason": "spread_too_wide",
            "run_id": "test-run",
            "mid_price": 52000.0,
        },
    ]
    
    with signals_file.open("w", encoding="utf-8") as f:
        for signal in signals:
            f.write(json.dumps(signal, ensure_ascii=False) + "\n")
    
    return signals_dir, signals


class TestSignalsToExecutorIntegration:
    """测试信号到执行器的集成"""
    
    def test_read_signals_from_jsonl(self, sample_signals):
        """测试从JSONL读取信号"""
        signals_dir, expected_signals = sample_signals
        
        signals = list(read_signals_from_jsonl(signals_dir.parent))
        
        assert len(signals) == len(expected_signals)
        assert signals[0]["symbol"] == "BTCUSDT"
        assert signals[0]["ts_ms"] == 1731379200000
    
    def test_signal_to_order(self, temp_output_dir):
        """测试信号转订单"""
        executor_cfg = {"order_size_usd": 100}
        
        # 确认的买入信号
        signal1 = {
            "ts_ms": 1731379200000,
            "symbol": "BTCUSDT",
            "signal_type": "buy",
            "confirm": True,
            "gating": False,
            "run_id": "test-run",
            "mid_price": 50000.0,
        }
        
        order1 = signal_to_order(signal1, executor_cfg)
        assert order1 is not None
        assert order1.side == Side.BUY
        assert order1.symbol == "BTCUSDT"
        assert order1.qty == 100 / 50000.0  # order_size_usd / mid_price
        
        # 未确认信号
        signal2 = {
            "ts_ms": 1731379201000,
            "symbol": "BTCUSDT",
            "signal_type": "buy",
            "confirm": False,
            "gating": False,
            "run_id": "test-run",
            "mid_price": 50000.0,
        }
        
        order2 = signal_to_order(signal2, executor_cfg)
        assert order2 is None
        
        # 被门控信号
        signal3 = {
            "ts_ms": 1731379202000,
            "symbol": "BTCUSDT",
            "signal_type": "buy",
            "confirm": True,
            "gating": True,
            "run_id": "test-run",
            "mid_price": 50000.0,
        }
        
        order3 = signal_to_order(signal3, executor_cfg)
        assert order3 is None
    
    def test_process_signals_e2e(self, sample_signals, temp_output_dir):
        """测试端到端处理信号"""
        signals_dir, _ = sample_signals
        
        executor_cfg = {
            "mode": "backtest",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
            "order_size_usd": 100,
        }
        
        backtest_cfg = {
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 100,
        }
        
        executor = BacktestExecutor()
        executor.prepare({
            "executor": executor_cfg,
            "backtest": backtest_cfg,
            "sink": {"kind": "jsonl", "output_dir": str(temp_output_dir)},
        })
        
        # 读取信号
        signals = read_signals_from_jsonl(signals_dir.parent)
        
        # 处理信号
        stats = process_signals(executor, signals, executor_cfg)
        
        # 验证统计信息
        assert stats["total_signals"] == 4
        assert stats["confirmed_signals"] == 3  # 3个确认信号
        assert stats["gated_signals"] == 1  # 1个被门控
        assert stats["orders_submitted"] == 2  # 2个订单（1个buy + 1个sell）
        assert stats["orders_filled"] == 2  # 2个成交
        
        executor.close()
    
    def test_exec_log_output(self, sample_signals, temp_output_dir):
        """测试exec_log输出"""
        signals_dir, _ = sample_signals
        
        executor_cfg = {
            "mode": "backtest",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
            "order_size_usd": 100,
        }
        
        backtest_cfg = {
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
        }
        
        executor = BacktestExecutor()
        executor.prepare({
            "executor": executor_cfg,
            "backtest": backtest_cfg,
            "sink": {"kind": "jsonl", "output_dir": str(temp_output_dir)},
        })
        
        signals = read_signals_from_jsonl(signals_dir.parent)
        process_signals(executor, signals, executor_cfg)
        executor.close()
        
        # 检查exec_log.jsonl文件
        exec_log_dir = temp_output_dir / "ready" / "execlog" / "BTCUSDT"
        assert exec_log_dir.exists()
        
        jsonl_files = list(exec_log_dir.glob("exec_log_*.jsonl"))
        assert len(jsonl_files) > 0
        
        # 读取并验证日志
        events = []
        with jsonl_files[0].open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        
        # 应该有submit、ack、filled事件
        event_types = [e["event"] for e in events]
        assert "submit" in event_types
        assert "ack" in event_types
        assert "filled" in event_types

