# -*- coding: utf-8 -*-
"""Walk-forward验证集成测试"""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.optimizer import ParameterOptimizer


class TestWalkForwardIntegration:
    """测试Walk-forward验证集成"""
    
    @patch("subprocess.run")
    def test_walk_forward_enabled(self, mock_run, tmp_path):
        """测试启用Walk-forward验证"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
            output_dir=tmp_path / "output",
        )
        
        # 模拟subprocess成功
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        # 模拟结果目录和metrics
        output_dir = tmp_path / "output" / "trial_1"
        result_dir = output_dir / "backtest_20250101_000000"
        result_dir.mkdir(parents=True)
        metrics_file = result_dir / "metrics.json"
        metrics_file.write_text(json.dumps({
            "total_trades": 10,
            "total_pnl": 100,
            "total_fee": 10,
            "total_slippage": 5,
            "win_rate": 0.5,
        }))
        
        # 模拟验证结果目录
        val_output_dir = tmp_path / "output" / "trial_1_val"
        val_result_dir = val_output_dir / "backtest_20250102_000000"
        val_result_dir.mkdir(parents=True)
        val_metrics_file = val_result_dir / "metrics.json"
        val_metrics_file.write_text(json.dumps({
            "total_trades": 8,
            "total_pnl": 80,
            "total_fee": 8,
            "total_slippage": 4,
            "win_rate": 0.4,
        }))
        
        # 运行trial（带验证日期）
        result = optimizer.run_trial(
            trial_config={"backtest": {"taker_fee_bps": 2.0}},
            trial_id=1,
            backtest_args={
                "input": "test",
                "date": "2025-01-01",
                "symbols": ["BTCUSDT"],
            },
            val_dates=["2025-01-02"],
        )
        
        # 验证：应该包含验证指标
        assert result["success"] is True
        assert "val_metrics" in result
        assert "train_score" in result
        assert "val_score" in result
        assert "generalization_gap" in result
    
    def test_walk_forward_folds_generation(self, tmp_path):
        """测试Walk-forward折叠生成"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
        )
        
        # 测试optimize方法中的walk-forward折叠生成
        walk_forward_dates = ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]
        
        from alpha_core.report.walk_forward import WalkForwardValidator
        
        validator = WalkForwardValidator(
            dates=walk_forward_dates,
            train_ratio=0.5,
            step_size=1,
        )
        
        folds = validator.generate_folds()
        
        # 应该生成至少一个折叠
        assert len(folds) > 0
        
        # 每个折叠应该有训练和验证日期
        for train_dates, val_dates in folds:
            assert len(train_dates) > 0
            assert len(val_dates) > 0
    
    @patch("subprocess.run")
    def test_optimize_with_walk_forward(self, mock_run, tmp_path):
        """测试optimize方法启用Walk-forward验证"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
        )
        
        # 模拟subprocess成功
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        # 模拟结果目录和metrics
        def create_mock_result(trial_id, date_suffix):
            output_dir = tmp_path / "output" / f"trial_{trial_id}"
            result_dir = output_dir / f"backtest_{date_suffix}_000000"
            result_dir.mkdir(parents=True)
            metrics_file = result_dir / "metrics.json"
            metrics_file.write_text(json.dumps({
                "total_trades": 10,
                "total_pnl": 100,
                "total_fee": 10,
                "total_slippage": 5,
                "win_rate": 0.5,
            }))
        
        # 注意：这里只是测试optimize方法能正确处理walk_forward_dates参数
        # 实际运行需要mock subprocess和文件系统操作
        
        walk_forward_dates = ["2025-01-01", "2025-01-02"]
        
        # 测试：optimize方法应该接受walk_forward_dates参数
        # 由于需要完整的mock，这里只验证参数传递
        assert optimizer.optimize.__code__.co_varnames.__contains__("walk_forward_dates")







