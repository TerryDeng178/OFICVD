# -*- coding: utf-8 -*-
"""P0修复单元测试：持仓超长退出逻辑 + 成本观测指标"""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime, timezone

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.backtest.trade_sim import TradeSimulator
from alpha_core.backtest.metrics import MetricsAggregator


class TestP0HoldTimeExitFix(unittest.TestCase):
    """测试持仓超长退出逻辑修复"""
    
    def setUp(self):
        self.output_dir = Path("/tmp/test_p0_hold_time")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.config = {
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 1000,
            "reverse_on_signal": False,
            "take_profit_bps": 12,
            "stop_loss_bps": 10,
            "min_hold_time_sec": 240,
            "max_hold_time_sec": 3600,
            "force_timeout_exit": True,
            "ignore_gating_in_backtest": False,
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
            "slippage_model": "static",
            "fee_model": "taker_static",
        }
    
    def test_force_timeout_exit_priority_over_tp(self):
        """测试force_timeout_exit优先级高于TP"""
        sim = TradeSimulator(self.config, self.output_dir)
        
        # 创建持仓
        symbol = "BTCUSDT"
        entry_ts_ms = 1000000
        entry_px = 50000.0
        
        position = {
            "symbol": symbol,
            "side": "buy",
            "entry_ts_ms": entry_ts_ms,
            "entry_px": entry_px,
            "qty": 0.02,
            "entry_fee": 0.2,
            "entry_notional": 1000.0,
            "maker_probability": 0.5,
        }
        sim.positions[symbol] = position
        
        # 模拟达到min_hold_time_sec但未达到TP的信号
        # 时间：entry + 250秒（超过min_hold_time_sec=240）
        signal_ts_ms = entry_ts_ms + 250 * 1000
        mid_price = 50050.0  # 只涨了50，未达到TP=12bps（需要60）
        
        signal = {
            "symbol": symbol,
            "ts_ms": signal_ts_ms,
            "mid_price": mid_price,
            "confirm": True,
            "signal_type": "neutral",
            "_feature_data": {},
        }
        
        # 应该触发timeout退出（因为force_timeout_exit=True且达到min_hold_time_sec）
        exit_trade = sim._check_exit(position, signal, signal_ts_ms, mid_price)
        
        self.assertIsNotNone(exit_trade, "应该触发timeout退出")
        self.assertEqual(exit_trade.get("reason"), "timeout", "退出原因应该是timeout")
    
    def test_max_hold_time_sec_highest_priority(self):
        """测试max_hold_time_sec优先级最高"""
        sim = TradeSimulator(self.config, self.output_dir)
        
        # 创建持仓
        symbol = "BTCUSDT"
        entry_ts_ms = 1000000
        entry_px = 50000.0
        
        position = {
            "symbol": symbol,
            "side": "buy",
            "entry_ts_ms": entry_ts_ms,
            "entry_px": entry_px,
            "qty": 0.02,
            "entry_fee": 0.2,
            "entry_notional": 1000.0,
            "maker_probability": 0.5,
        }
        sim.positions[symbol] = position
        
        # 模拟超过max_hold_time_sec的信号（即使未达到min_hold_time_sec也应该退出）
        # 时间：entry + 3700秒（超过max_hold_time_sec=3600）
        signal_ts_ms = entry_ts_ms + 3700 * 1000
        mid_price = 50000.0
        
        signal = {
            "symbol": symbol,
            "ts_ms": signal_ts_ms,
            "mid_price": mid_price,
            "confirm": True,
            "signal_type": "neutral",
            "_feature_data": {},
        }
        
        # 应该触发timeout退出（因为超过max_hold_time_sec）
        exit_trade = sim._check_exit(position, signal, signal_ts_ms, mid_price)
        
        self.assertIsNotNone(exit_trade, "应该触发timeout退出")
        self.assertEqual(exit_trade.get("reason"), "timeout", "退出原因应该是timeout")
    
    def test_force_timeout_exit_before_tp_signal(self):
        """测试force_timeout_exit在TP信号之前触发"""
        sim = TradeSimulator(self.config, self.output_dir)
        
        # 创建持仓
        symbol = "BTCUSDT"
        entry_ts_ms = 1000000
        entry_px = 50000.0
        
        position = {
            "symbol": symbol,
            "side": "buy",
            "entry_ts_ms": entry_ts_ms,
            "entry_px": entry_px,
            "qty": 0.02,
            "entry_fee": 0.2,
            "entry_notional": 1000.0,
            "maker_probability": 0.5,
        }
        sim.positions[symbol] = position
        
        # 模拟达到min_hold_time_sec且达到TP的信号
        # 时间：entry + 250秒（超过min_hold_time_sec=240）
        signal_ts_ms = entry_ts_ms + 250 * 1000
        mid_price = 50060.0  # 涨了60，达到TP=12bps
        
        signal = {
            "symbol": symbol,
            "ts_ms": signal_ts_ms,
            "mid_price": mid_price,
            "confirm": True,
            "signal_type": "neutral",
            "_feature_data": {},
        }
        
        # 由于force_timeout_exit优先级高于TP，应该触发timeout退出
        exit_trade = sim._check_exit(position, signal, signal_ts_ms, mid_price)
        
        self.assertIsNotNone(exit_trade, "应该触发退出")
        # 注意：由于force_timeout_exit优先级更高，应该是timeout而不是take_profit
        self.assertEqual(exit_trade.get("reason"), "timeout", "退出原因应该是timeout（优先级高于TP）")


class TestP0CostMetrics(unittest.TestCase):
    """测试成本观测指标"""
    
    def setUp(self):
        self.output_dir = Path("/tmp/test_p0_cost_metrics")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def test_trade_record_contains_cost_fields(self):
        """测试trade记录包含成本观测字段"""
        config = {
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 1000,
            "slippage_model": "static",
            "fee_model": "maker_taker",
            "fee_maker_taker": {
                "maker_fee_ratio": 0.4,
                "scenario_probs": {
                    "Q_L": 0.85,
                    "A_L": 0.75,
                    "A_H": 0.5,
                    "Q_H": 0.4,
                },
            },
        }
        
        sim = TradeSimulator(config, self.output_dir)
        
        # 创建entry信号
        signal = {
            "symbol": "BTCUSDT",
            "ts_ms": 1000000,
            "mid_price": 50000.0,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {
                "spread_bps": 1.5,
                "scenario_2x2": "Q_L",
            },
        }
        
        entry_trade = sim._enter_position("BTCUSDT", "buy", 1000000, 50000.0, signal)
        
        # 检查entry trade记录是否包含成本观测字段
        self.assertIn("maker_probability", entry_trade, "entry trade应包含maker_probability")
        self.assertIn("is_maker_actual", entry_trade, "entry trade应包含is_maker_actual")
        self.assertIn("effective_spread_bps", entry_trade, "entry trade应包含effective_spread_bps")
        self.assertIn("spread_bps", entry_trade, "entry trade应包含spread_bps")
        
        # 检查字段值
        self.assertIsInstance(entry_trade["maker_probability"], (int, float))
        self.assertIsInstance(entry_trade["is_maker_actual"], bool)
        self.assertGreaterEqual(entry_trade["effective_spread_bps"], 0)
        self.assertGreaterEqual(entry_trade["spread_bps"], 0)
    
    def test_exit_trade_contains_cost_fields(self):
        """测试exit trade记录包含成本观测字段"""
        config = {
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 1000,
            "slippage_model": "static",
            "fee_model": "maker_taker",
            "fee_maker_taker": {
                "maker_fee_ratio": 0.4,
                "scenario_probs": {
                    "Q_L": 0.85,
                    "A_L": 0.75,
                    "A_H": 0.5,
                    "Q_H": 0.4,
                },
            },
        }
        
        sim = TradeSimulator(config, self.output_dir)
        
        # 创建entry
        entry_signal = {
            "symbol": "BTCUSDT",
            "ts_ms": 1000000,
            "mid_price": 50000.0,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {
                "spread_bps": 1.5,
                "scenario_2x2": "Q_L",
            },
        }
        sim._enter_position("BTCUSDT", "buy", 1000000, 50000.0, entry_signal)
        
        # 创建exit信号
        exit_signal = {
            "symbol": "BTCUSDT",
            "ts_ms": 1003000,  # 3秒后
            "mid_price": 50050.0,
            "confirm": True,
            "signal_type": "neutral",
            "_feature_data": {
                "spread_bps": 1.2,
                "scenario_2x2": "Q_L",
            },
        }
        
        position = sim.positions.get("BTCUSDT")
        self.assertIsNotNone(position, "应该有持仓")
        
        # 强制退出（通过设置force_timeout_exit和min_hold_time_sec）
        sim.force_timeout_exit = True
        sim.min_hold_time_sec = 2  # 2秒即可退出
        
        exit_trade = sim._check_exit(position, exit_signal, 1003000, 50050.0)
        
        if exit_trade:
            # 检查exit trade记录是否包含成本观测字段
            self.assertIn("maker_probability", exit_trade, "exit trade应包含maker_probability")
            self.assertIn("is_maker_actual", exit_trade, "exit trade应包含is_maker_actual")
            self.assertIn("effective_spread_bps", exit_trade, "exit trade应包含effective_spread_bps")
            self.assertIn("spread_bps", exit_trade, "exit trade应包含spread_bps")
    
    def test_metrics_contains_cost_observability_fields(self):
        """测试metrics包含成本观测指标"""
        aggregator = MetricsAggregator(self.output_dir)
        
        # 创建包含成本观测字段的trades
        trades = [
            {
                "ts_ms": 1000000,
                "symbol": "BTCUSDT",
                "side": "buy",
                "px": 50000.0,
                "qty": 0.02,
                "fee": 0.2,
                "reason": "entry",
                "pos_after": 1,
                "gross_pnl": 0,
                "net_pnl": 0,
                "maker_probability": 0.85,
                "is_maker_actual": True,
                "effective_spread_bps": 2.5,
                "spread_bps": 1.5,
                "slippage_bps": 1.0,
            },
            {
                "ts_ms": 1003000,
                "symbol": "BTCUSDT",
                "side": "sell",
                "px": 50050.0,
                "qty": 0.02,
                "fee": 0.2,
                "reason": "exit",
                "pos_after": 0,
                "gross_pnl": 1.0,
                "net_pnl": 0.6,
                "maker_probability": 0.75,
                "is_maker_actual": True,
                "effective_spread_bps": 2.2,
                "spread_bps": 1.2,
                "slippage_bps": 1.0,
            },
            {
                "ts_ms": 1004000,
                "symbol": "ETHUSDT",
                "side": "buy",
                "px": 3000.0,
                "qty": 0.33,
                "fee": 0.2,
                "reason": "entry",
                "pos_after": 1,
                "gross_pnl": 0,
                "net_pnl": 0,
                "maker_probability": 0.3,
                "is_maker_actual": False,
                "effective_spread_bps": 3.0,
                "spread_bps": 2.0,
                "slippage_bps": 1.0,
            },
            {
                "ts_ms": 1007000,
                "symbol": "ETHUSDT",
                "side": "sell",
                "px": 3005.0,
                "qty": 0.33,
                "fee": 0.2,
                "reason": "exit",
                "pos_after": 0,
                "gross_pnl": 1.65,
                "net_pnl": 1.25,
                "maker_probability": 0.2,
                "is_maker_actual": False,
                "effective_spread_bps": 3.5,
                "spread_bps": 2.5,
                "slippage_bps": 1.0,
            },
        ]
        
        pnl_daily = [
            {
                "date": "2025-11-09",
                "symbol": "BTCUSDT",
                "gross_pnl": 1.0,
                "fee": 0.4,
                "slippage": 0.04,
                "net_pnl": 0.6,
                "turnover": 2000.0,
                "trades": 1,
                "wins": 1,
                "losses": 0,
            },
            {
                "date": "2025-11-09",
                "symbol": "ETHUSDT",
                "gross_pnl": 1.65,
                "fee": 0.4,
                "slippage": 0.066,
                "net_pnl": 1.25,
                "turnover": 1980.0,
                "trades": 1,
                "wins": 1,
                "losses": 0,
            },
        ]
        
        metrics = aggregator.compute_metrics(trades, pnl_daily)
        
        # 检查是否包含成本观测指标
        self.assertIn("maker_ratio_actual", metrics, "metrics应包含maker_ratio_actual")
        self.assertIn("taker_ratio_actual", metrics, "metrics应包含taker_ratio_actual")
        self.assertIn("effective_spread_bps_p50", metrics, "metrics应包含effective_spread_bps_p50")
        self.assertIn("effective_spread_bps_p95", metrics, "metrics应包含effective_spread_bps_p95")
        
        # 检查指标值
        # 4笔交易：2笔maker（BTC entry+exit），2笔taker（ETH entry+exit）
        self.assertEqual(metrics["maker_ratio_actual"], 0.5, "maker比例应该是0.5")
        self.assertEqual(metrics["taker_ratio_actual"], 0.5, "taker比例应该是0.5")
        
        # effective_spread_bps: [2.5, 2.2, 3.0, 3.5]
        # P50 (median): (2.5 + 3.0) / 2 = 2.75
        self.assertAlmostEqual(metrics["effective_spread_bps_p50"], 2.75, places=1)
        # P95: 3.5 (最大值)
        self.assertAlmostEqual(metrics["effective_spread_bps_p95"], 3.5, places=1)
    
    def test_empty_metrics_contains_cost_fields(self):
        """测试空metrics也包含成本观测字段"""
        aggregator = MetricsAggregator(self.output_dir)
        
        metrics = aggregator.compute_metrics([], [])
        
        # 检查是否包含成本观测指标（应该为0）
        self.assertIn("maker_ratio_actual", metrics)
        self.assertIn("taker_ratio_actual", metrics)
        self.assertIn("effective_spread_bps_p50", metrics)
        self.assertIn("effective_spread_bps_p95", metrics)
        
        # 检查默认值
        self.assertEqual(metrics["maker_ratio_actual"], 0.0)
        self.assertEqual(metrics["taker_ratio_actual"], 0.0)
        self.assertEqual(metrics["effective_spread_bps_p50"], 0.0)
        self.assertEqual(metrics["effective_spread_bps_p95"], 0.0)


if __name__ == "__main__":
    unittest.main()

