# -*- coding: utf-8 -*-
"""单元测试：A组BUG修复"""
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import json
import tempfile

# 添加项目根目录到路径
import sys
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alpha_core.backtest.trade_sim import TradeSimulator
from alpha_core.backtest.metrics import MetricsAggregator


class TestGroupAFixMaxHoldTime(unittest.TestCase):
    """测试A组修复：最大持仓时长保护"""
    
    def setUp(self):
        """设置测试环境"""
        self.config = {
            "taker_fee_bps": 2.0,
            "max_hold_time_sec": 3600,  # 1小时
            "min_hold_time_sec": 180,
            "force_timeout_exit": True,
        }
        self.output_dir = Path("/tmp/test_trade_sim")
        self.trade_sim = TradeSimulator(
            config=self.config,
            output_dir=self.output_dir,
        )
    
    def test_max_hold_time_sec_initialized(self):
        """测试max_hold_time_sec正确初始化"""
        self.assertEqual(self.trade_sim.max_hold_time_sec, 3600)
    
    def test_max_hold_time_sec_default(self):
        """测试max_hold_time_sec默认值"""
        config_no_max = {
            "taker_fee_bps": 2.0,
        }
        trade_sim = TradeSimulator(
            config=config_no_max,
            output_dir=self.output_dir,
        )
        self.assertEqual(trade_sim.max_hold_time_sec, 3600)  # 默认值
    
    def test_max_hold_time_exceeded_triggers_exit(self):
        """测试超过最大持仓时长时触发退出"""
        # 创建持仓
        symbol = "BTCUSDT"
        ts_ms = 1000
        mid_price = 100000.0
        signal = {
            "symbol": symbol,
            "ts_ms": ts_ms,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {},
        }
        
        # 进入持仓
        trade = self.trade_sim._enter_position(symbol, "buy", ts_ms, mid_price, signal)
        self.assertIsNotNone(trade)
        self.assertIn(symbol, self.trade_sim.positions)
        
        # 模拟超过最大持仓时长（3700秒后）
        exit_ts_ms = ts_ms + 3700 * 1000
        exit_signal = {
            "symbol": symbol,
            "ts_ms": exit_ts_ms,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {},
        }
        
        # 检查退出
        exit_trade = self.trade_sim._check_exit(
            self.trade_sim.positions[symbol],
            exit_signal,
            exit_ts_ms,
            mid_price
        )
        
        # 应该触发timeout退出
        self.assertIsNotNone(exit_trade)
        self.assertEqual(exit_trade.get("reason"), "timeout")


class TestGroupAFixLastSignalTracking(unittest.TestCase):
    """测试A组修复：最后一条信号跟踪"""
    
    def setUp(self):
        """设置测试环境"""
        self.config = {
            "taker_fee_bps": 2.0,
        }
        self.output_dir = Path("/tmp/test_trade_sim")
        self.trade_sim = TradeSimulator(
            config=self.config,
            output_dir=self.output_dir,
        )
    
    def test_last_signal_tracking(self):
        """测试最后一条信号跟踪"""
        symbol = "BTCUSDT"
        signal1 = {
            "symbol": symbol,
            "ts_ms": 1000,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {"scenario_2x2": "A_H"},
        }
        
        # 处理信号
        self.trade_sim.process_signal(signal1, 100000.0)
        
        # 验证最后一条信号被跟踪
        self.assertIn(symbol, self.trade_sim._last_signal_per_symbol)
        last_signal = self.trade_sim._last_signal_per_symbol[symbol]
        # 检查_feature_data中的scenario_2x2
        feature_data = last_signal.get("_feature_data", {})
        self.assertEqual(feature_data.get("scenario_2x2"), "A_H")
        
        # 更新信号
        signal2 = {
            "symbol": symbol,
            "ts_ms": 2000,
            "confirm": True,
            "signal_type": "sell",
            "_feature_data": {"scenario_2x2": "Q_L"},
        }
        
        self.trade_sim.process_signal(signal2, 100000.0)
        
        # 验证最后一条信号已更新
        last_signal = self.trade_sim._last_signal_per_symbol[symbol]
        feature_data = last_signal.get("_feature_data", {})
        self.assertEqual(feature_data.get("scenario_2x2"), "Q_L")
    
    def test_close_all_positions_uses_last_signal(self):
        """测试close_all_positions使用最后一条信号"""
        symbol = "BTCUSDT"
        ts_ms = 1000
        mid_price = 100000.0
        signal = {
            "symbol": symbol,
            "ts_ms": ts_ms,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {"scenario_2x2": "A_H", "spread_bps": 2.0},
        }
        
        # 进入持仓
        self.trade_sim.process_signal(signal, mid_price)
        self.assertIn(symbol, self.trade_sim.positions)
        
        # 更新最后一条信号
        last_signal = {
            "symbol": symbol,
            "ts_ms": 2000,
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {"scenario_2x2": "Q_L", "spread_bps": 1.5},
        }
        self.trade_sim._last_signal_per_symbol[symbol] = last_signal
        
        # 强制平仓
        current_prices = {symbol: mid_price}
        self.trade_sim.close_all_positions(current_prices, last_data_ts_ms=2000)
        
        # 验证持仓已关闭
        self.assertEqual(len(self.trade_sim.positions), 0)
        
        # 验证trades中有rollover_close或timeout记录
        exit_trades = [t for t in self.trade_sim.trades if t.get("reason") in ["rollover_close", "timeout"]]
        self.assertGreater(len(exit_trades), 0)


class TestGroupAFixMetricsHoldTime(unittest.TestCase):
    """测试A组修复：Metrics只统计已闭合的持仓对"""
    
    def test_metrics_only_counts_closed_positions(self):
        """测试Metrics只统计已闭合的持仓对"""
        with tempfile.TemporaryDirectory() as tmpdir:
            aggregator = MetricsAggregator(Path(tmpdir))
            
            # 创建测试trades数据
            # 包含entry和exit的完整对
            trades = [
                {"reason": "entry", "side": "buy", "ts_ms": 1000, "symbol": "BTCUSDT"},
                {"reason": "exit", "side": "buy", "ts_ms": 2000, "symbol": "BTCUSDT"},  # 持仓1秒
                {"reason": "entry", "side": "sell", "ts_ms": 3000, "symbol": "ETHUSDT"},
                {"reason": "timeout", "side": "sell", "ts_ms": 5000, "symbol": "ETHUSDT"},  # 持仓2秒
                {"reason": "entry", "side": "buy", "ts_ms": 6000, "symbol": "BTCUSDT"},
                # 注意：这个entry没有对应的exit，不应该被统计
            ]
            
            # 创建测试pnl_daily数据
            pnl_daily = [
                {"date": "2025-11-09", "symbol": "BTCUSDT", "net_pnl": 10, "fee": 1, "slippage": 0.5, "turnover": 1000, "trades": 1, "wins": 1, "losses": 0},
                {"date": "2025-11-09", "symbol": "ETHUSDT", "net_pnl": -5, "fee": 1, "slippage": 0.5, "turnover": 1000, "trades": 1, "wins": 0, "losses": 1},
            ]
            
            metrics = aggregator.compute_metrics(
                trades=trades,
                pnl_daily=pnl_daily,
            )
            
            # 验证avg_hold_sec只统计已闭合的持仓对
            # 应该只有2个已闭合的持仓对：1秒和2秒，平均1.5秒
            avg_hold_sec = metrics.get("avg_hold_sec", 0)
            self.assertAlmostEqual(avg_hold_sec, 1.5, places=1)
    
    def test_metrics_includes_timeout_and_rollover_close(self):
        """测试Metrics包含timeout和rollover_close"""
        with tempfile.TemporaryDirectory() as tmpdir:
            aggregator = MetricsAggregator(Path(tmpdir))
            
            trades = [
                {"reason": "entry", "side": "buy", "ts_ms": 1000, "symbol": "BTCUSDT"},
                {"reason": "timeout", "side": "buy", "ts_ms": 2000, "symbol": "BTCUSDT"},
                {"reason": "entry", "side": "sell", "ts_ms": 3000, "symbol": "ETHUSDT"},
                {"reason": "rollover_close", "side": "sell", "ts_ms": 5000, "symbol": "ETHUSDT"},
            ]
            
            pnl_daily = [
                {"date": "2025-11-09", "symbol": "BTCUSDT", "net_pnl": 10, "fee": 1, "slippage": 0.5, "turnover": 1000, "trades": 1, "wins": 1, "losses": 0},
                {"date": "2025-11-09", "symbol": "ETHUSDT", "net_pnl": -5, "fee": 1, "slippage": 0.5, "turnover": 1000, "trades": 1, "wins": 0, "losses": 1},
            ]
            
            metrics = aggregator.compute_metrics(
                trades=trades,
                pnl_daily=pnl_daily,
            )
            
            # 验证avg_hold_sec计算正确（1秒和2秒，平均1.5秒）
            avg_hold_sec = metrics.get("avg_hold_sec", 0)
            self.assertAlmostEqual(avg_hold_sec, 1.5, places=1)


if __name__ == "__main__":
    unittest.main()

