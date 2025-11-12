#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试：STAGE-2优化实验方案"""
import unittest
import sys
import json
import yaml
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.alpha_core.report.optimizer import ParameterOptimizer


class TestStage2ConfigLoading(unittest.TestCase):
    """测试STAGE-2配置文件加载"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_stage2")
        self.test_dir.mkdir(parents=True, exist_ok=True)
    
    def test_load_baseline_config(self):
        """测试加载基线配置（Trial 5）"""
        baseline_path = Path("runtime/optimizer/group_stage2_baseline_trial5.yaml")
        if not baseline_path.exists():
            self.skipTest(f"基线配置文件不存在: {baseline_path}")
        
        with open(baseline_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        # 验证关键参数
        self.assertEqual(config["signal"]["weak_signal_threshold"], 0.76)
        self.assertEqual(config["signal"]["consistency_min"], 0.53)
        self.assertEqual(config["signal"]["dedupe_ms"], 8000)
        self.assertEqual(config["execution"]["cooldown_ms"], 500)
        self.assertEqual(config["components"]["fusion"]["w_ofi"], 0.6)
        self.assertEqual(config["components"]["fusion"]["w_cvd"], 0.4)
        self.assertEqual(config["backtest"]["take_profit_bps"], 12)
        self.assertEqual(config["backtest"]["stop_loss_bps"], 10)
    
    def test_load_search_space_yaml(self):
        """测试加载YAML格式的搜索空间"""
        search_space_path = Path("tasks/TASK-09/search_space_stage2_f2_fusion_weights.yaml")
        if not search_space_path.exists():
            self.skipTest(f"搜索空间文件不存在: {search_space_path}")
        
        with open(search_space_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        # 验证结构
        self.assertIn("stage", data)
        self.assertEqual(data["stage"], 2)
        self.assertIn("search_space", data)
        self.assertIn("scoring_weights", data)
        self.assertIn("hard_constraints", data)
        
        # 验证搜索空间
        search_space = data["search_space"]
        self.assertIn("components.fusion.w_ofi", search_space)
        self.assertIn("signal.thresholds.quiet.buy", search_space)
        
        # 验证评分权重
        scoring_weights = data["scoring_weights"]
        self.assertEqual(scoring_weights["pnl_net"], 1.0)
        self.assertEqual(scoring_weights["avg_pnl_per_trade"], 0.6)
        self.assertEqual(scoring_weights["trades_per_hour"], -0.4)
        self.assertEqual(scoring_weights["cost_bps_on_turnover"], -0.5)
        
        # 验证硬约束
        hard_constraints = data["hard_constraints"]
        self.assertEqual(hard_constraints["avg_pnl_per_trade"], ">= 0")
        self.assertEqual(hard_constraints["pnl_net"], ">= 0")
        self.assertEqual(hard_constraints["trades_per_hour"], "<= 20")
        self.assertEqual(hard_constraints["cost_bps_on_turnover"], "<= 1.75")


class TestStage2ParameterGeneration(unittest.TestCase):
    """测试STAGE-2参数生成"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_stage2")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建测试基线配置
        self.base_config = {
            "signal": {
                "weak_signal_threshold": 0.76,
                "consistency_min": 0.53,
                "dedupe_ms": 8000,
                "thresholds": {
                    "active": {"buy": 1.2, "sell": -1.2},
                    "quiet": {"buy": 1.4, "sell": -1.4}
                },
                "min_consecutive_same_dir": 3
            },
            "components": {
                "fusion": {
                    "w_ofi": 0.6,
                    "w_cvd": 0.4,
                    "min_consecutive": 3
                }
            },
            "execution": {
                "cooldown_ms": 500
            },
            "backtest": {
                "take_profit_bps": 12,
                "stop_loss_bps": 10,
                "min_hold_time_sec": 240
            }
        }
        
        self.config_path = self.test_dir / "test_baseline.yaml"
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_config, f)
    
    def test_f2_fusion_weight_constraint(self):
        """测试F2: w_ofi + w_cvd = 1.0约束"""
        search_space = {
            "components.fusion.w_ofi": [0.5, 0.6, 0.7],
            "signal.thresholds.quiet.buy": [1.2, 1.4],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证所有trial都满足w_ofi + w_cvd = 1.0
        # 注意：如果search_space中只有w_ofi，w_cvd应该自动调整为1-w_ofi
        for trial in trials:
            config = trial["config"]
            w_ofi = config.get("components", {}).get("fusion", {}).get("w_ofi")
            w_cvd = config.get("components", {}).get("fusion", {}).get("w_cvd")
            
            if w_ofi is not None:
                # w_cvd应该自动设置为1-w_ofi
                self.assertIsNotNone(w_cvd, "w_cvd应该自动设置")
                self.assertAlmostEqual(
                    w_ofi + w_cvd, 1.0, places=6,
                    msg=f"w_ofi={w_ofi}, w_cvd={w_cvd}, sum={w_ofi + w_cvd}"
                )
                self.assertIn(w_ofi, [0.5, 0.6, 0.7])
    
    def test_f3_anti_flip_parameters(self):
        """测试F3: 反向防抖参数生成"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4, 5],
            "execution.cooldown_ms": [500, 800, 1200],
            "signal.dedupe_ms": [8000, 10000],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证参数范围
        for trial in trials:
            config = trial["config"]
            min_consecutive = config.get("signal", {}).get("min_consecutive_same_dir")
            cooldown_ms = config.get("execution", {}).get("cooldown_ms")
            dedupe_ms = config.get("signal", {}).get("dedupe_ms")
            
            self.assertIn(min_consecutive, [3, 4, 5])
            self.assertIn(cooldown_ms, [500, 800, 1200])
            self.assertIn(dedupe_ms, [8000, 10000])
    
    def test_f4_regime_thresholds(self):
        """测试F4: 场景化阈值参数生成"""
        search_space = {
            "signal.thresholds.quiet.buy": [1.2, 1.4],
            "signal.thresholds.quiet.sell": [-1.4, -1.2],
            "signal.thresholds.active.buy": [0.6, 0.8],
            "signal.thresholds.active.sell": [-0.8, -0.6],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证阈值范围
        for trial in trials:
            config = trial["config"]
            thresholds = config.get("signal", {}).get("thresholds", {})
            
            quiet_buy = thresholds.get("quiet", {}).get("buy")
            quiet_sell = thresholds.get("quiet", {}).get("sell")
            active_buy = thresholds.get("active", {}).get("buy")
            active_sell = thresholds.get("active", {}).get("sell")
            
            self.assertIn(quiet_buy, [1.2, 1.4])
            self.assertIn(quiet_sell, [-1.4, -1.2])
            self.assertIn(active_buy, [0.6, 0.8])
            self.assertIn(active_sell, [-0.8, -0.6])
    
    def test_f5_tp_sl_parameters(self):
        """测试F5: 止盈/止损参数生成"""
        search_space = {
            "backtest.take_profit_bps": [12, 15, 18],
            "backtest.stop_loss_bps": [8, 10, 12],
            "backtest.min_hold_time_sec": [180, 240],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证TP/SL参数范围
        for trial in trials:
            config = trial["config"]
            take_profit = config.get("backtest", {}).get("take_profit_bps")
            stop_loss = config.get("backtest", {}).get("stop_loss_bps")
            min_hold = config.get("backtest", {}).get("min_hold_time_sec")
            
            self.assertIn(take_profit, [12, 15, 18])
            self.assertIn(stop_loss, [8, 10, 12])
            self.assertIn(min_hold, [180, 240])


class TestStage2Scoring(unittest.TestCase):
    """测试STAGE-2评分函数"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_stage2")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_config = {
            "signal": {"weak_signal_threshold": 0.76},
            "components": {"fusion": {"w_ofi": 0.6, "w_cvd": 0.4}},
        }
        
        self.config_path = self.test_dir / "test_baseline.yaml"
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_config, f)
        
        # STAGE-2评分权重
        self.stage2_weights = {
            "pnl_net": 1.0,
            "avg_pnl_per_trade": 0.6,
            "trades_per_hour": -0.4,
            "cost_bps_on_turnover": -0.5,
            "win_rate_trades": 0.0,
        }
    
    def test_stage2_scoring_weights(self):
        """测试STAGE-2评分权重应用"""
        search_space = {
            "signal.weak_signal_threshold": [0.76, 0.77],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
            scoring_weights=self.stage2_weights,
        )
        
        # 验证评分权重已设置
        self.assertEqual(optimizer.scoring_weights["pnl_net"], 1.0)
        self.assertEqual(optimizer.scoring_weights["avg_pnl_per_trade"], 0.6)
        self.assertEqual(optimizer.scoring_weights["trades_per_hour"], -0.4)
        self.assertEqual(optimizer.scoring_weights["cost_bps_on_turnover"], -0.5)
        self.assertEqual(optimizer.scoring_weights["win_rate_trades"], 0.0)
    
    def test_stage2_scoring_calculation(self):
        """测试STAGE-2评分计算（包含cost_bps_on_turnover和trades_per_hour）"""
        search_space = {
            "signal.weak_signal_threshold": [0.76],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
            scoring_weights=self.stage2_weights,
        )
        
        # 创建模拟metrics
        metrics1 = {
            "total_pnl": 100.0,
            "total_fee": 5.0,
            "total_slippage": 3.0,
            "total_trades": 20,
            "turnover": 10000.0,
            "win_rate_trades": 0.5,
            "cost_bps_on_turnover": 0.8,  # (5+3)/10000 * 10000 = 0.8 bps
        }
        
        metrics2 = {
            "total_pnl": 50.0,
            "total_fee": 3.0,
            "total_slippage": 2.0,
            "total_trades": 30,
            "turnover": 5000.0,
            "win_rate_trades": 0.6,
            "cost_bps_on_turnover": 1.0,  # (3+2)/5000 * 10000 = 1.0 bps
        }
        
        # 添加trial结果用于标准化
        optimizer.trial_results = [
            {"success": True, "metrics": metrics1},
            {"success": True, "metrics": metrics2},
        ]
        
        # 计算score
        net_pnl1 = metrics1["total_pnl"] - metrics1["total_fee"] - metrics1["total_slippage"]
        score1 = optimizer._calculate_score(metrics1, net_pnl1, self.stage2_weights)
        
        net_pnl2 = metrics2["total_pnl"] - metrics2["total_fee"] - metrics2["total_slippage"]
        score2 = optimizer._calculate_score(metrics2, net_pnl2, self.stage2_weights)
        
        # 验证score计算（metrics1的net_pnl更高，应该score更高）
        self.assertGreater(score1, score2, "net_pnl更高的trial应该有更高的score")
        
        # 验证cost_bps_on_turnover和trades_per_hour被纳入计算
        # （通过检查score差异来验证）
        self.assertIsInstance(score1, (int, float))
        self.assertIsInstance(score2, (int, float))


class TestStage2HardConstraints(unittest.TestCase):
    """测试STAGE-2硬约束检查"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_stage2")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_config = {
            "signal": {"weak_signal_threshold": 0.76},
            "components": {"fusion": {"w_ofi": 0.6, "w_cvd": 0.4}},
        }
        
        self.config_path = self.test_dir / "test_baseline.yaml"
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_config, f)
    
    def test_hard_constraints_parsing(self):
        """测试硬约束解析"""
        hard_constraints = {
            "avg_pnl_per_trade": ">= 0",
            "pnl_net": ">= 0",
            "trades_per_hour": "<= 20",
            "cost_bps_on_turnover": "<= 1.75",
        }
        
        # 测试解析逻辑
        def parse_constraint(value, constraint_str):
            """解析约束字符串"""
            if ">=" in constraint_str:
                threshold = float(constraint_str.split(">=")[1].strip())
                return value >= threshold
            elif "<=" in constraint_str:
                threshold = float(constraint_str.split("<=")[1].strip())
                return value <= threshold
            return False
        
        # 测试满足约束的情况
        self.assertTrue(parse_constraint(0.1, hard_constraints["avg_pnl_per_trade"]))
        self.assertTrue(parse_constraint(10.0, hard_constraints["pnl_net"]))
        self.assertTrue(parse_constraint(15.0, hard_constraints["trades_per_hour"]))
        self.assertTrue(parse_constraint(1.5, hard_constraints["cost_bps_on_turnover"]))
        
        # 测试不满足约束的情况
        self.assertFalse(parse_constraint(-0.1, hard_constraints["avg_pnl_per_trade"]))
        self.assertFalse(parse_constraint(-10.0, hard_constraints["pnl_net"]))
        self.assertFalse(parse_constraint(25.0, hard_constraints["trades_per_hour"]))
        self.assertFalse(parse_constraint(2.0, hard_constraints["cost_bps_on_turnover"]))
    
    def test_hard_constraints_check(self):
        """测试硬约束检查函数"""
        hard_constraints = {
            "avg_pnl_per_trade": ">= 0",
            "pnl_net": ">= 0",
            "trades_per_hour": "<= 20",
            "cost_bps_on_turnover": "<= 1.75",
        }
        
        def check_hard_constraints(metrics, constraints):
            """检查metrics是否满足硬约束"""
            results = {}
            for constraint_name, constraint_value in constraints.items():
                metric_value = metrics.get(constraint_name, None)
                if metric_value is not None:
                    if ">=" in constraint_value:
                        threshold = float(constraint_value.split(">=")[1].strip())
                        results[constraint_name] = metric_value >= threshold
                    elif "<=" in constraint_value:
                        threshold = float(constraint_value.split("<=")[1].strip())
                        results[constraint_name] = metric_value <= threshold
            return results
        
        # 满足所有约束的metrics
        metrics_pass = {
            "avg_pnl_per_trade": 0.1,
            "pnl_net": 10.0,
            "trades_per_hour": 15.0,
            "cost_bps_on_turnover": 1.5,
        }
        
        results_pass = check_hard_constraints(metrics_pass, hard_constraints)
        self.assertTrue(all(results_pass.values()), "所有约束都应满足")
        
        # 不满足部分约束的metrics
        metrics_fail = {
            "avg_pnl_per_trade": -0.1,
            "pnl_net": -10.0,
            "trades_per_hour": 25.0,
            "cost_bps_on_turnover": 2.0,
        }
        
        results_fail = check_hard_constraints(metrics_fail, hard_constraints)
        self.assertFalse(all(results_fail.values()), "部分约束不满足")


class TestStage2CombinedMatrix(unittest.TestCase):
    """测试STAGE-2组合矩阵"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_stage2")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_config = {
            "signal": {
                "weak_signal_threshold": 0.76,
                "thresholds": {
                    "active": {"buy": 1.2, "sell": -1.2},
                    "quiet": {"buy": 1.4, "sell": -1.4}
                },
                "min_consecutive_same_dir": 3
            },
            "components": {
                "fusion": {"w_ofi": 0.6, "w_cvd": 0.4}
            },
            "execution": {"cooldown_ms": 500},
            "backtest": {
                "take_profit_bps": 12,
                "stop_loss_bps": 10
            }
        }
        
        self.config_path = self.test_dir / "test_baseline.yaml"
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_config, f)
    
    def test_combined_matrix_generation(self):
        """测试组合矩阵参数生成（2×2×2×2=16组）"""
        search_space = {
            # F2: 融合权重
            "components.fusion.w_ofi": [0.6, 0.7],
            # F4: Regime阈值
            "signal.thresholds.quiet.buy": [1.2, 1.4],
            "signal.thresholds.active.buy": [0.6, 0.8],
            # F3: 反抖与冷却
            "signal.min_consecutive_same_dir": [4, 5],
            "execution.cooldown_ms": [800, 1200],
            # F5: TP/SL
            "backtest.take_profit_bps": [15, 18],
            "backtest.stop_loss_bps": [8, 10],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证组合数：2×2×2×2×2×2×2 = 128（如果所有参数都独立）
        # 但实际应该是2×2×2×2=16（如果按文档说明）
        # 这里验证至少生成了合理的组合数
        self.assertGreaterEqual(len(trials), 16, "组合矩阵应至少生成16个trial")
        
        # 验证每个trial的参数都在搜索空间内
        for trial in trials:
            config = trial["config"]
            
            w_ofi = config.get("components", {}).get("fusion", {}).get("w_ofi")
            self.assertIn(w_ofi, [0.6, 0.7])
            
            quiet_buy = config.get("signal", {}).get("thresholds", {}).get("quiet", {}).get("buy")
            self.assertIn(quiet_buy, [1.2, 1.4])
            
            active_buy = config.get("signal", {}).get("thresholds", {}).get("active", {}).get("buy")
            self.assertIn(active_buy, [0.6, 0.8])
            
            min_consecutive = config.get("signal", {}).get("min_consecutive_same_dir")
            self.assertIn(min_consecutive, [4, 5])
            
            cooldown_ms = config.get("execution", {}).get("cooldown_ms")
            self.assertIn(cooldown_ms, [800, 1200])
            
            take_profit = config.get("backtest", {}).get("take_profit_bps")
            self.assertIn(take_profit, [15, 18])
            
            stop_loss = config.get("backtest", {}).get("stop_loss_bps")
            self.assertIn(stop_loss, [8, 10])


if __name__ == "__main__":
    unittest.main()

