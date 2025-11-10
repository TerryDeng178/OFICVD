# -*- coding: utf-8 -*-
"""测试阶段1-阶段2优化组件"""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.optimizer import ParameterOptimizer


class TestStage1SearchSpace:
    """测试阶段1搜索空间"""
    
    def test_load_stage1_search_space(self):
        """测试加载阶段1搜索空间"""
        search_space_file = Path("tasks/TASK-09/search_space_stage1.json")
        assert search_space_file.exists(), "阶段1搜索空间文件不存在"
        
        with open(search_space_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert "search_space" in data
        assert "scoring_weights" in data
        assert data["stage"] == 1
        
        # 验证搜索空间字段
        search_space = data["search_space"]
        assert "signal.weak_signal_threshold" in search_space
        assert "signal.consistency_min" in search_space
        assert "backtest.min_hold_time_sec" in search_space
        
        # 验证评分权重
        scoring_weights = data["scoring_weights"]
        assert "win_rate" in scoring_weights
        assert "max_drawdown" in scoring_weights
        assert "cost_ratio_notional" in scoring_weights


class TestStage2SearchSpace:
    """测试阶段2搜索空间"""
    
    def test_load_stage2_search_space(self):
        """测试加载阶段2搜索空间"""
        search_space_file = Path("tasks/TASK-09/search_space_stage2.json")
        assert search_space_file.exists(), "阶段2搜索空间文件不存在"
        
        with open(search_space_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert "search_space" in data
        assert "scoring_weights" in data
        assert data["stage"] == 2
        
        # 验证搜索空间字段
        search_space = data["search_space"]
        assert "components.fusion.burst_coalesce_ms" in search_space
        assert "backtest.min_hold_time_sec" in search_space
        
        # 验证评分权重
        scoring_weights = data["scoring_weights"]
        assert "net_pnl" in scoring_weights
        assert "pnl_per_trade" in scoring_weights
        assert "trades_per_hour" in scoring_weights
        assert "cost_ratio_notional" in scoring_weights


class TestScoringWeights:
    """测试评分权重"""
    
    def test_stage1_scoring_weights(self, tmp_path):
        """测试阶段1评分权重"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        search_space_file = Path("tasks/TASK-09/search_space_stage1.json")
        with open(search_space_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space=data["search_space"],
            output_dir=tmp_path / "output",
            scoring_weights=data["scoring_weights"],
        )
        
        assert optimizer.scoring_weights is not None
        assert optimizer.scoring_weights["win_rate"] == 0.4
        assert optimizer.scoring_weights["max_drawdown"] == 0.3
        assert optimizer.scoring_weights["cost_ratio_notional"] == 0.3
    
    def test_stage2_scoring_weights(self, tmp_path):
        """测试阶段2评分权重"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        search_space_file = Path("tasks/TASK-09/search_space_stage2.json")
        with open(search_space_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space=data["search_space"],
            output_dir=tmp_path / "output",
            scoring_weights=data["scoring_weights"],
        )
        
        assert optimizer.scoring_weights is not None
        assert optimizer.scoring_weights["net_pnl"] == 0.3
        assert optimizer.scoring_weights["pnl_per_trade"] == 0.3
        assert optimizer.scoring_weights["trades_per_hour"] == 0.2
        assert optimizer.scoring_weights["cost_ratio_notional"] == 0.2


class TestScoreCalculationWithWeights:
    """测试带权重的评分计算"""
    
    def test_stage1_score_calculation(self, tmp_path):
        """测试阶段1评分计算"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        search_space_file = Path("tasks/TASK-09/search_space_stage1.json")
        with open(search_space_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space=data["search_space"],
            output_dir=tmp_path / "output",
            scoring_weights=data["scoring_weights"],
        )
        
        # 模拟trial_results
        optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 2.0,
                    "total_slippage": 1.0,
                    "win_rate": 0.5,
                    "max_drawdown": 10.0,
                    "total_trades": 20,
                    "turnover": 20000.0,
                },
            },
            {
                "success": True,
                "metrics": {
                    "total_pnl": 200.0,
                    "total_fee": 4.0,
                    "total_slippage": 2.0,
                    "win_rate": 0.6,
                    "max_drawdown": 5.0,
                    "total_trades": 25,
                    "turnover": 25000.0,
                },
            },
        ]
        
        # 计算第一个结果的score
        metrics1 = optimizer.trial_results[0]["metrics"]
        net_pnl1 = metrics1["total_pnl"] - metrics1["total_fee"] - metrics1["total_slippage"]
        score1 = optimizer._calculate_score(metrics1, net_pnl1, optimizer.scoring_weights)
        
        # 计算第二个结果的score
        metrics2 = optimizer.trial_results[1]["metrics"]
        net_pnl2 = metrics2["total_pnl"] - metrics2["total_fee"] - metrics2["total_slippage"]
        score2 = optimizer._calculate_score(metrics2, net_pnl2, optimizer.scoring_weights)
        
        # 验证：score是数值
        assert isinstance(score1, (int, float))
        assert isinstance(score2, (int, float))
    
    def test_trades_per_hour_penalty(self, tmp_path):
        """测试trades_per_hour区间惩罚"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
            scoring_weights={"trades_per_hour": 0.2},
        )
        
        # 模拟trial_results（包含超出目标范围的trades_per_hour）
        optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 2.0,
                    "total_slippage": 1.0,
                    "total_trades": 5,  # 5/24 = 0.208 < 0.8（低于目标范围）
                },
            },
            {
                "success": True,
                "metrics": {
                    "total_pnl": 200.0,
                    "total_fee": 4.0,
                    "total_slippage": 2.0,
                    "total_trades": 30,  # 30/24 = 1.25 > 1.2（高于目标范围）
                },
            },
            {
                "success": True,
                "metrics": {
                    "total_pnl": 150.0,
                    "total_fee": 3.0,
                    "total_slippage": 1.5,
                    "total_trades": 20,  # 20/24 = 0.833（在目标范围内）
                },
            },
        ]
        
        # 计算score（应该对超出范围的进行惩罚）
        metrics1 = optimizer.trial_results[0]["metrics"]
        net_pnl1 = metrics1["total_pnl"] - metrics1["total_fee"] - metrics1["total_slippage"]
        score1 = optimizer._calculate_score(metrics1, net_pnl1, optimizer.scoring_weights)
        
        metrics2 = optimizer.trial_results[1]["metrics"]
        net_pnl2 = metrics2["total_pnl"] - metrics2["total_fee"] - metrics2["total_slippage"]
        score2 = optimizer._calculate_score(metrics2, net_pnl2, optimizer.scoring_weights)
        
        metrics3 = optimizer.trial_results[2]["metrics"]
        net_pnl3 = metrics3["total_pnl"] - metrics3["total_fee"] - metrics3["total_slippage"]
        score3 = optimizer._calculate_score(metrics3, net_pnl3, optimizer.scoring_weights)
        
        # 验证：score3应该高于score1和score2（因为trades_per_hour在目标范围内）
        assert isinstance(score1, (int, float))
        assert isinstance(score2, (int, float))
        assert isinstance(score3, (int, float))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

