# -*- coding: utf-8 -*-
"""TASK-B2: 回测集成测试

测试回测模块的组件协作和端到端流程
"""

import pytest
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

from backtest.app import BacktestAdapter, BrokerSimulator, BacktestWriter, load_config


class TestBacktestIntegration:
    """回测集成测试"""

    def test_mode_a_full_flow(self, tmp_path):
        """测试模式A完整流程（features -> signals -> trades -> pnl）"""
        # 创建模拟features数据
        features_dir = tmp_path / "features"
        features_dir.mkdir()

        # 创建模拟parquet文件（这里用JSON代替）
        feature_file = features_dir / "features_test.json"
        features_data = [
            {"ts_ms": 1731470000000, "symbol": "BTCUSDT", "mid": 50000.0},
            {"ts_ms": 1731470060000, "symbol": "BTCUSDT", "mid": 50010.0}
        ]

        with feature_file.open("w") as f:
            json.dump(features_data, f)

        # 创建配置
        config = {
            "signal": {"thresholds": {"base": 0.1}},
            "broker": {"fee_bps_maker": -25, "fee_bps_taker": 75}
        }

        # 初始化组件
        adapter = BacktestAdapter('A', features_dir, None, symbols={"BTCUSDT"}, start_ms=None, end_ms=None)
        broker = BrokerSimulator(config.get("broker", {}))
        writer = BacktestWriter(tmp_path, "test_run_a", write_signals=True, emit_sqlite=False)

        # 执行流程
        signal_count = 0
        trade_count = 0

        for signal in adapter.iter_signals(config):
            signal_count += 1
            writer.write_signal(signal)

            # 模拟交易逻辑
            if signal.get("confirm", False):
                order = {
                    "symbol": signal["symbol"],
                    "side": "BUY",
                    "price": 50000.0,
                    "quantity": 0.001,
                    "maker": True
                }
                trade = broker.execute_order(order)
                if trade:
                    writer.write_trade(trade)
                    trade_count += 1

        # 写入PNL和manifest
        pnl_record = {"date": "2025-11-13", "pnl": 0.0, "trades": trade_count}
        writer.write_pnl(pnl_record)

        manifest = {
            "run_id": "test_run_a",
            "mode": "A",
            "perf": {"signals_processed": signal_count, "trades_generated": trade_count}
        }
        writer.write_manifest(manifest)

        writer.close()

        # 验证输出文件
        output_dir = tmp_path / "test_run_a"
        assert (output_dir / "signals.jsonl").exists()
        assert (output_dir / "trades.jsonl").exists()
        assert (output_dir / "pnl_daily.jsonl").exists()
        assert (output_dir / "run_manifest.json").exists()

        # 验证signals内容
        with (output_dir / "signals.jsonl").open() as f:
            signals = [json.loads(line) for line in f if line.strip()]
            assert len(signals) == signal_count

    def test_mode_b_full_flow(self, tmp_path):
        """测试模式B完整流程（signals -> trades -> pnl）"""
        # 创建模拟signals数据
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

        # 创建配置
        config = {
            "broker": {"fee_bps_maker": -25, "fee_bps_taker": 75}
        }

        # 初始化组件
        adapter = BacktestAdapter('B', None, f"jsonl://{signals_dir}", symbols={"BTCUSDT"}, start_ms=None, end_ms=None)
        broker = BrokerSimulator(config.get("broker", {}))
        writer = BacktestWriter(tmp_path, "test_run_b", write_signals=False, emit_sqlite=False)

        # 执行流程
        signal_count = 0
        trade_count = 0

        for signal in adapter.iter_signals():
            signal_count += 1

            # 模拟交易逻辑
            if signal.get("confirm", False):
                order = {
                    "symbol": signal["symbol"],
                    "side": "BUY",
                    "price": 50000.0,
                    "quantity": 0.001,
                    "maker": True
                }
                trade = broker.execute_order(order)
                if trade:
                    writer.write_trade(trade)
                    trade_count += 1

        # 写入PNL和manifest
        pnl_record = {"date": "2025-11-13", "pnl": 0.0, "trades": trade_count}
        writer.write_pnl(pnl_record)

        manifest = {
            "run_id": "test_run_b",
            "mode": "B",
            "perf": {"signals_processed": signal_count, "trades_generated": trade_count}
        }
        writer.write_manifest(manifest)

        writer.close()

        # 验证输出文件
        output_dir = tmp_path / "test_run_b"
        assert not (output_dir / "signals.jsonl").exists()  # 模式B不应产生signals.jsonl
        assert (output_dir / "trades.jsonl").exists()
        assert (output_dir / "pnl_daily.jsonl").exists()
        assert (output_dir / "run_manifest.json").exists()

        # 验证trades内容（应该只有1个，因为只有1个confirm=true的信号）
        with (output_dir / "trades.jsonl").open() as f:
            trades = [json.loads(line) for line in f if line.strip()]
            assert len(trades) == 1

    def test_determinism_verification(self, tmp_path):
        """测试确定性：相同配置应产生相同结果"""
        # 创建模拟signals数据
        signals_dir = tmp_path / "signals"
        btc_dir = signals_dir / "BTCUSDT"
        btc_dir.mkdir(parents=True)

        signals_file = btc_dir / "signals-20241113-10.jsonl"
        test_signals = [
            {"ts_ms": 1731470000000, "symbol": "BTCUSDT", "score": 1.0, "confirm": True, "run_id": "test"},
            {"ts_ms": 1731470060000, "symbol": "BTCUSDT", "score": 0.5, "confirm": True, "run_id": "test"}
        ]

        with signals_file.open("w") as f:
            for signal in test_signals:
                f.write(json.dumps(signal) + "\n")

        # 第一次运行
        adapter1 = BacktestAdapter('B', None, f"jsonl://{signals_dir}")
        signals1 = list(adapter1.iter_signals())

        # 第二次运行（相同配置）
        adapter2 = BacktestAdapter('B', None, f"jsonl://{signals_dir}")
        signals2 = list(adapter2.iter_signals())

        # 结果应该完全相同
        assert len(signals1) == len(signals2)
        for s1, s2 in zip(signals1, signals2):
            assert s1["ts_ms"] == s2["ts_ms"]
            assert s1["symbol"] == s2["symbol"]
            assert s1["score"] == s2["score"]
