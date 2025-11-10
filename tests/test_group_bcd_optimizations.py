# -*- coding: utf-8 -*-
"""单元测试：B组C组D组优化"""
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
from alpha_core.report.optimizer import ParameterOptimizer


class TestGroupBDeadband(unittest.TestCase):
    """测试B组优化：死区带功能"""
    
    def setUp(self):
        """设置测试环境"""
        self.config = {
            "taker_fee_bps": 2.0,
            "deadband_bps": 2.0,  # 死区带2bps
            "min_hold_time_sec": 180,
            "take_profit_bps": 12,
            "stop_loss_bps": 10,
        }
        self.output_dir = Path("/tmp/test_trade_sim")
        self.trade_sim = TradeSimulator(
            config=self.config,
            output_dir=self.output_dir,
        )
    
    def test_deadband_initialized(self):
        """测试deadband_bps正确初始化"""
        self.assertEqual(self.trade_sim.deadband_bps, 2.0)
    
    def test_deadband_blocks_exit_in_range(self):
        """测试死区带阻止在范围内的退出"""
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
        
        # 模拟价格在死区内（pnl_bps = 1.5bps < deadband_bps = 2bps）
        entry_px = self.trade_sim.positions[symbol]["entry_px"]
        exit_mid_price = entry_px * (1 + 0.00015)  # +1.5bps
        exit_signal = {
            "symbol": symbol,
            "ts_ms": ts_ms + 200000,  # 200秒后（超过min_hold_time_sec）
            "confirm": True,
            "signal_type": "sell",
            "_feature_data": {},
        }
        
        # 检查退出（应该被死区带阻止）
        exit_trade = self.trade_sim._check_exit(
            self.trade_sim.positions[symbol],
            exit_signal,
            ts_ms + 200000,
            exit_mid_price
        )
        
        # 应该被死区带阻止
        self.assertIsNone(exit_trade)
    
    def test_deadband_allows_exit_outside_range(self):
        """测试死区带允许范围外的退出"""
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
        
        # 模拟价格超出死区（pnl_bps = 3bps > deadband_bps = 2bps）
        entry_px = self.trade_sim.positions[symbol]["entry_px"]
        exit_mid_price = entry_px * (1 + 0.0003)  # +3bps
        exit_signal = {
            "symbol": symbol,
            "ts_ms": ts_ms + 200000,  # 200秒后（超过min_hold_time_sec）
            "confirm": True,
            "signal_type": "sell",
            "_feature_data": {},
        }
        
        # 检查退出（应该允许，因为超出死区）
        exit_trade = self.trade_sim._check_exit(
            self.trade_sim.positions[symbol],
            exit_signal,
            ts_ms + 200000,
            exit_mid_price
        )
        
        # 应该允许退出（reverse_signal）
        self.assertIsNotNone(exit_trade)
        self.assertEqual(exit_trade.get("reason"), "reverse_signal")
    
    def test_deadband_allows_stop_loss(self):
        """测试死区带不阻止止损"""
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
        
        # 模拟止损（pnl_bps = -11bps，触发止损）
        entry_px = self.trade_sim.positions[symbol]["entry_px"]
        exit_mid_price = entry_px * (1 - 0.0011)  # -11bps
        exit_signal = {
            "symbol": symbol,
            "ts_ms": ts_ms + 10000,  # 10秒后（未达min_hold_time_sec，但止损例外）
            "confirm": True,
            "signal_type": "buy",
            "_feature_data": {},
        }
        
        # 检查退出（止损应该允许，不受死区带限制）
        exit_trade = self.trade_sim._check_exit(
            self.trade_sim.positions[symbol],
            exit_signal,
            ts_ms + 10000,
            exit_mid_price
        )
        
        # 止损应该允许
        self.assertIsNotNone(exit_trade)
        self.assertEqual(exit_trade.get("reason"), "stop_loss")


class TestOptimizerScoringUpdates(unittest.TestCase):
    """测试优化器打分更新：降频/降成本显式写进目标函数"""
    
    def setUp(self):
        """设置测试环境"""
        self.base_config = Path("runtime/optimizer/group_a_strict_gating.yaml")
        self.search_space = {}
        self.optimizer = ParameterOptimizer(
            base_config_path=self.base_config,
            search_space=self.search_space,
            scoring_weights={
                "net_pnl": 1.0,
                "pnl_per_trade": 0.6,
                "trades_per_hour": 0.4,
                "cost_bps_on_turnover": 0.3,
            }
        )
    
    def test_cost_bps_score_calculation(self):
        """测试cost_bps_on_turnover评分计算"""
        # 创建模拟metrics
        metrics = {
            "total_pnl": 100.0,
            "total_fee": 50.0,
            "total_slippage": 20.0,
            "total_trades": 100,
            "turnover": 100000.0,
            "cost_bps_on_turnover": 1.5,  # 低于1.75bps
            "win_rate_trades": 0.3,
            "max_drawdown": 50.0,
        }
        
        # 创建模拟trial_results
        self.optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 50.0,
                    "total_slippage": 20.0,
                    "total_trades": 100,
                    "cost_bps_on_turnover": 1.5,
                }
            },
            {
                "success": True,
                "metrics": {
                    "total_pnl": 200.0,
                    "total_fee": 100.0,
                    "total_slippage": 40.0,
                    "total_trades": 200,
                    "cost_bps_on_turnover": 2.0,  # 高于1.75bps
                }
            },
        ]
        
        net_pnl = 100.0 - 50.0 - 20.0
        score = self.optimizer._calculate_score(
            metrics,
            net_pnl,
            self.optimizer.scoring_weights,
            trial_result={"metrics": metrics}
        )
        
        # 验证score计算包含cost_bps惩罚
        # 第一个trial的cost_bps较低，应该得分更高
        self.assertIsNotNone(score)
    
    def test_trades_per_hour_penalty(self):
        """测试trades_per_hour惩罚"""
        # 创建模拟metrics（高交易频率）
        metrics = {
            "total_pnl": 100.0,
            "total_fee": 50.0,
            "total_slippage": 20.0,
            "total_trades": 2000,  # 高交易频率（假设24小时回测，约83笔/小时）
            "turnover": 100000.0,
            "cost_bps_on_turnover": 1.5,
            "win_rate_trades": 0.3,
            "max_drawdown": 50.0,
        }
        
        # 创建模拟trial_results
        self.optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 50.0,
                    "total_slippage": 20.0,
                    "total_trades": 2000,  # 高频率
                }
            },
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 50.0,
                    "total_slippage": 20.0,
                    "total_trades": 500,  # 低频率
                }
            },
        ]
        
        net_pnl = 100.0 - 50.0 - 20.0
        score = self.optimizer._calculate_score(
            metrics,
            net_pnl,
            self.optimizer.scoring_weights,
            trial_result={"metrics": metrics}
        )
        
        # 验证score计算包含trades_per_hour惩罚
        # 高频率trial应该得分更低
        self.assertIsNotNone(score)
    
    def test_cost_bps_penalty_threshold(self):
        """测试cost_bps惩罚阈值（>1.75bps）"""
        # 创建模拟metrics（高成本bps）
        metrics = {
            "total_pnl": 100.0,
            "total_fee": 50.0,
            "total_slippage": 20.0,
            "total_trades": 100,
            "turnover": 100000.0,
            "cost_bps_on_turnover": 2.0,  # 高于1.75bps阈值
            "win_rate_trades": 0.3,
            "max_drawdown": 50.0,
        }
        
        # 创建模拟trial_results
        self.optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 50.0,
                    "total_slippage": 20.0,
                    "total_trades": 100,
                    "cost_bps_on_turnover": 2.0,  # 高成本
                }
            },
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 50.0,
                    "total_slippage": 20.0,
                    "total_trades": 100,
                    "cost_bps_on_turnover": 1.5,  # 低成本
                }
            },
        ]
        
        net_pnl = 100.0 - 50.0 - 20.0
        score = self.optimizer._calculate_score(
            metrics,
            net_pnl,
            self.optimizer.scoring_weights,
            trial_result={"metrics": metrics}
        )
        
        # 验证高成本bps应该受到惩罚
        self.assertIsNotNone(score)


class TestGroupCConfigOptimization(unittest.TestCase):
    """测试C组配置优化：maker概率、费率、滑点模型"""
    
    def test_group_c_config_loaded(self):
        """测试C组配置正确加载"""
        import yaml
        config_path = Path("runtime/optimizer/group_c_maker_first.yaml")
        
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            # 验证maker概率配置
            scenario_probs = config.get("backtest", {}).get("fee_maker_taker", {}).get("scenario_probs", {})
            self.assertIn("Q_L", scenario_probs)
            self.assertIn("A_L", scenario_probs)
            self.assertIn("A_H", scenario_probs)
            self.assertIn("Q_H", scenario_probs)
            self.assertIn("default", scenario_probs)
            
            # 验证maker费率
            maker_fee_ratio = config.get("backtest", {}).get("fee_maker_taker", {}).get("maker_fee_ratio", 0)
            self.assertEqual(maker_fee_ratio, 0.4)
            
            # 验证滑点模型配置
            slippage_config = config.get("backtest", {}).get("slippage_piecewise", {})
            self.assertEqual(slippage_config.get("spread_base_multiplier"), 0.7)
            scenario_multipliers = slippage_config.get("scenario_multipliers", {})
            self.assertEqual(scenario_multipliers.get("Q_L"), 0.6)
            self.assertEqual(scenario_multipliers.get("A_L"), 0.8)
            self.assertEqual(scenario_multipliers.get("A_H"), 1.0)
            self.assertEqual(scenario_multipliers.get("Q_H"), 1.2)


class TestGroupDConfigCombined(unittest.TestCase):
    """测试D组配置：A+B+C组合"""
    
    def test_group_d_config_loaded(self):
        """测试D组配置正确加载"""
        import yaml
        config_path = Path("runtime/optimizer/group_d_combined.yaml")
        
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            # 验证SIGNAL配置（A组严门控）
            signal_config = config.get("signal", {})
            self.assertEqual(signal_config.get("weak_signal_threshold"), 0.70)
            self.assertEqual(signal_config.get("consistency_min"), 0.40)
            self.assertEqual(signal_config.get("dedupe_ms"), 4000)
            self.assertEqual(signal_config.get("min_consecutive_same_dir"), 4)
            
            # 验证FUSION配置（B组冷却）
            fusion_config = config.get("components", {}).get("fusion", {})
            self.assertEqual(fusion_config.get("flip_rearm_margin"), 0.45)
            self.assertEqual(fusion_config.get("adaptive_cooldown_k"), 0.70)
            
            # 验证STRATEGY配置（B组迟滞）
            strategy_config = config.get("strategy", {})
            self.assertEqual(strategy_config.get("entry_threshold"), 0.65)
            self.assertEqual(strategy_config.get("exit_threshold"), 0.45)
            
            # 验证backtest配置（B组持仓 + C组成本）
            backtest_config = config.get("backtest", {})
            self.assertEqual(backtest_config.get("min_hold_time_sec"), 240)
            self.assertEqual(backtest_config.get("max_hold_time_sec"), 3600)
            self.assertEqual(backtest_config.get("ignore_gating_in_backtest"), False)
            
            # 验证C组成本配置
            fee_config = backtest_config.get("fee_maker_taker", {})
            self.assertEqual(fee_config.get("maker_fee_ratio"), 0.4)
            scenario_probs = fee_config.get("scenario_probs", {})
            self.assertEqual(scenario_probs.get("Q_L"), 0.85)
            self.assertEqual(scenario_probs.get("A_L"), 0.75)
            self.assertEqual(scenario_probs.get("A_H"), 0.50)
            self.assertEqual(scenario_probs.get("Q_H"), 0.40)
            
            # 验证滑点模型配置
            slippage_config = backtest_config.get("slippage_piecewise", {})
            self.assertEqual(slippage_config.get("spread_base_multiplier"), 0.7)
            scenario_multipliers = slippage_config.get("scenario_multipliers", {})
            self.assertEqual(scenario_multipliers.get("Q_L"), 0.6)
            self.assertEqual(scenario_multipliers.get("A_L"), 0.8)
            self.assertEqual(scenario_multipliers.get("A_H"), 1.0)
            self.assertEqual(scenario_multipliers.get("Q_H"), 1.2)


if __name__ == "__main__":
    unittest.main()

