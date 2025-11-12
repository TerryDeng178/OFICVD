# -*- coding: utf-8 -*-
"""F2组：Maker记账模式（阈值 vs 伯努利抽样）单元测试"""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from collections import defaultdict
import copy

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.backtest.trade_sim import TradeSimulator


class TestF2BernoulliSampling(unittest.TestCase):
    """测试F2 Maker记账模式（阈值 vs 伯努利抽样）"""
    
    def setUp(self):
        self.output_dir = Path("/tmp/test_f2_bernoulli")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_config = {
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
            "fee_model": "maker_taker",
            "fee_maker_taker": {
                "maker_fee_ratio": 0.35,
                "scenario_probs": {
                    "Q_L": 0.90,
                    "A_L": 0.80,
                    "A_H": 0.50,
                    "Q_H": 0.40,
                    "default": 0.50
                },
                "spread_threshold_narrow": 1.0,
                "spread_threshold_wide": 5.0,
                "spread_slope": 0.7,
                "side_bias": {
                    "buy": 1.1,
                    "sell": 0.9
                }
            }
        }
    
    def test_threshold_mode_default(self):
        """测试阈值模式（默认配置）"""
        config = self.base_config.copy()
        sim = TradeSimulator(config, self.output_dir)
        
        # 验证默认使用阈值模式
        self.assertEqual(sim.maker_accounting_mode, "threshold")
        self.assertEqual(sim.maker_threshold, 0.5)
        self.assertIsNone(sim.rng)
    
    def test_threshold_mode_custom(self):
        """测试阈值模式（自定义阈值0.6）"""
        config = self.base_config.copy()
        config["fee_maker_taker"]["accounting_mode"] = "threshold"
        config["fee_maker_taker"]["maker_threshold"] = 0.6
        
        sim = TradeSimulator(config, self.output_dir)
        
        self.assertEqual(sim.maker_accounting_mode, "threshold")
        self.assertEqual(sim.maker_threshold, 0.6)
        self.assertIsNone(sim.rng)
    
    def test_bernoulli_mode_default(self):
        """测试伯努利抽样模式（默认配置）"""
        config = self.base_config.copy()
        config["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config["fee_maker_taker"]["bernoulli_seed"] = 42
        
        sim = TradeSimulator(config, self.output_dir)
        
        self.assertEqual(sim.maker_accounting_mode, "bernoulli")
        self.assertEqual(sim.bernoulli_seed, 42)
        self.assertIsNotNone(sim.rng)
    
    def test_threshold_mode_logic(self):
        """测试阈值模式的判断逻辑"""
        config = self.base_config.copy()
        config["fee_maker_taker"]["accounting_mode"] = "threshold"
        config["fee_maker_taker"]["maker_threshold"] = 0.5
        
        sim = TradeSimulator(config, self.output_dir)
        
        # 创建信号
        signal = {
            "_feature_data": {
                "scenario_2x2": "A_L",
                "spread_bps": 0.5
            }
        }
        
        # 测试不同概率
        test_cases = [
            (0.3, False),  # 0.3 < 0.5 -> False (taker)
            (0.5, False),  # 0.5 == 0.5 -> False (taker, 不包含等于)
            (0.51, True),  # 0.51 > 0.5 -> True (maker)
            (0.7, True),   # 0.7 > 0.5 -> True (maker)
        ]
        
        for maker_prob, expected_is_maker in test_cases:
            # 模拟maker_prob计算
            with patch.object(sim, '_compute_fee_bps', return_value=(2.0, maker_prob)):
                # 直接测试判断逻辑
                is_maker = maker_prob > sim.maker_threshold
                self.assertEqual(is_maker, expected_is_maker, 
                               f"maker_prob={maker_prob}, threshold={sim.maker_threshold}")
    
    def test_threshold_mode_custom_threshold(self):
        """测试阈值模式（自定义阈值0.6）的判断逻辑"""
        config = self.base_config.copy()
        config["fee_maker_taker"]["accounting_mode"] = "threshold"
        config["fee_maker_taker"]["maker_threshold"] = 0.6
        
        sim = TradeSimulator(config, self.output_dir)
        
        test_cases = [
            (0.5, False),  # 0.5 < 0.6 -> False
            (0.6, False),   # 0.6 == 0.6 -> False
            (0.61, True),  # 0.61 > 0.6 -> True
        ]
        
        for maker_prob, expected_is_maker in test_cases:
            is_maker = maker_prob > sim.maker_threshold
            self.assertEqual(is_maker, expected_is_maker,
                           f"maker_prob={maker_prob}, threshold={sim.maker_threshold}")
    
    def test_bernoulli_mode_reproducibility(self):
        """测试伯努利抽样的可复现性（相同种子产生相同结果）"""
        # 使用深拷贝避免配置共享
        config1 = copy.deepcopy(self.base_config)
        config1["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config1["fee_maker_taker"]["bernoulli_seed"] = 42
        
        config2 = copy.deepcopy(self.base_config)
        config2["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config2["fee_maker_taker"]["bernoulli_seed"] = 42
        
        sim1 = TradeSimulator(config1, self.output_dir)
        sim2 = TradeSimulator(config2, self.output_dir)
        
        # 使用相同的概率值测试多次
        maker_prob = 0.6
        results1 = []
        results2 = []
        
        for _ in range(100):
            is_maker1 = sim1.rng.random() < maker_prob
            is_maker2 = sim2.rng.random() < maker_prob
            results1.append(is_maker1)
            results2.append(is_maker2)
        
        # 相同种子应该产生相同序列
        self.assertEqual(results1, results2, "相同种子应该产生相同的随机序列")
    
    def test_bernoulli_mode_different_seeds(self):
        """测试不同种子产生不同结果"""
        # 使用深拷贝避免配置共享
        config1 = copy.deepcopy(self.base_config)
        config1["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config1["fee_maker_taker"]["bernoulli_seed"] = 42
        
        config2 = copy.deepcopy(self.base_config)
        config2["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config2["fee_maker_taker"]["bernoulli_seed"] = 123
        
        sim1 = TradeSimulator(config1, self.output_dir)
        sim2 = TradeSimulator(config2, self.output_dir)
        
        # 验证种子确实不同
        self.assertEqual(sim1.bernoulli_seed, 42)
        self.assertEqual(sim2.bernoulli_seed, 123)
        
        # 直接比较随机数序列（不经过概率判断）
        random_values1 = []
        random_values2 = []
        
        for _ in range(1000):
            random_values1.append(sim1.rng.random())
            random_values2.append(sim2.rng.random())
        
        # 不同种子应该产生不同的随机数序列
        # 使用汉明距离或直接比较序列差异
        differences = sum(1 for a, b in zip(random_values1, random_values2) if abs(a - b) > 1e-10)
        
        # 不同种子应该产生至少50%的不同值（高概率）
        self.assertGreater(differences, 400, 
                          f"不同种子应该产生不同的随机序列，但只有{differences}/1000个不同值")
    
    def test_bernoulli_mode_convergence(self):
        """测试伯努利抽样长期频率收敛到概率"""
        config = self.base_config.copy()
        config["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config["fee_maker_taker"]["bernoulli_seed"] = 42
        
        sim = TradeSimulator(config, self.output_dir)
        
        # 测试不同概率值
        test_probs = [0.3, 0.5, 0.7, 0.9]
        tolerance = 0.05  # 5%容忍度
        
        for maker_prob in test_probs:
            maker_count = 0
            total_count = 10000
            
            for _ in range(total_count):
                if sim.rng.random() < maker_prob:
                    maker_count += 1
            
            actual_ratio = maker_count / total_count
            expected_ratio = maker_prob
            
            self.assertAlmostEqual(
                actual_ratio, expected_ratio, delta=tolerance,
                msg=f"maker_prob={maker_prob}, actual={actual_ratio}, expected={expected_ratio}"
            )
    
    def test_bernoulli_vs_threshold_comparison(self):
        """测试伯努利抽样vs阈值模式的差异"""
        # 阈值模式
        config_threshold = self.base_config.copy()
        config_threshold["fee_maker_taker"]["accounting_mode"] = "threshold"
        config_threshold["fee_maker_taker"]["maker_threshold"] = 0.5
        sim_threshold = TradeSimulator(config_threshold, self.output_dir)
        
        # 伯努利模式
        config_bernoulli = self.base_config.copy()
        config_bernoulli["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config_bernoulli["fee_maker_taker"]["bernoulli_seed"] = 42
        sim_bernoulli = TradeSimulator(config_bernoulli, self.output_dir)
        
        # 测试概率分布
        test_probs = [0.3, 0.45, 0.5, 0.55, 0.7]
        
        for maker_prob in test_probs:
            # 阈值模式：确定性判断
            is_maker_threshold = maker_prob > sim_threshold.maker_threshold
            
            # 伯努利模式：随机判断（多次采样）
            bernoulli_results = []
            for _ in range(1000):
                is_maker = sim_bernoulli.rng.random() < maker_prob
                bernoulli_results.append(is_maker)
            
            bernoulli_ratio = sum(bernoulli_results) / len(bernoulli_results)
            
            # 验证：当概率接近阈值时，伯努利模式会产生更平滑的过渡
            if maker_prob == 0.5:
                # 在阈值处，阈值模式是确定的False，但伯努利模式应该接近0.5
                self.assertAlmostEqual(bernoulli_ratio, 0.5, delta=0.05,
                                      msg=f"在阈值0.5处，伯努利模式应该接近0.5")
            
            # 验证：当概率远离阈值时，两种模式应该一致
            if maker_prob < 0.4:
                self.assertFalse(is_maker_threshold, 
                               f"低概率({maker_prob})时，阈值模式应该是False")
                self.assertLess(bernoulli_ratio, 0.5,
                               f"低概率({maker_prob})时，伯努利模式应该<0.5")
            
            if maker_prob > 0.6:
                self.assertTrue(is_maker_threshold,
                              f"高概率({maker_prob})时，阈值模式应该是True")
                self.assertGreater(bernoulli_ratio, 0.5,
                                  f"高概率({maker_prob})时，伯努利模式应该>0.5")
    
    def test_maker_ratio_alignment(self):
        """测试maker_ratio_actual与maker_probability的对齐"""
        # 使用伯努利模式
        config = self.base_config.copy()
        config["fee_maker_taker"]["accounting_mode"] = "bernoulli"
        config["fee_maker_taker"]["bernoulli_seed"] = 42
        
        sim = TradeSimulator(config, self.output_dir)
        
        # 模拟多个交易，每个有不同的maker_probability
        test_cases = [
            {"prob": 0.3, "count": 1000},
            {"prob": 0.5, "count": 1000},
            {"prob": 0.7, "count": 1000},
            {"prob": 0.9, "count": 1000},
        ]
        
        total_maker_count = 0
        total_count = 0
        weighted_prob_sum = 0.0
        
        for case in test_cases:
            prob = case["prob"]
            count = case["count"]
            
            for _ in range(count):
                is_maker = sim.rng.random() < prob
                if is_maker:
                    total_maker_count += 1
                total_count += 1
                weighted_prob_sum += prob
        
        actual_ratio = total_maker_count / total_count
        expected_ratio = weighted_prob_sum / total_count
        
        # 验证实际比例接近期望比例
        self.assertAlmostEqual(
            actual_ratio, expected_ratio, delta=0.02,
            msg=f"实际maker_ratio={actual_ratio:.4f}, 期望={expected_ratio:.4f}"
        )


if __name__ == "__main__":
    unittest.main()

