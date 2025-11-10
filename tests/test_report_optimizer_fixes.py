# -*- coding: utf-8 -*-
"""TASK-09: 参数优化器修复项单元测试"""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.optimizer import ParameterOptimizer


class TestRunnerSelection:
    """测试Fix 8: Runner选择"""
    
    def test_replay_harness_runner(self, tmp_path):
        """测试replay_harness runner"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
            output_dir=tmp_path / "output",
            runner="replay_harness",
        )
        
        assert optimizer.runner == "replay_harness"
    
    def test_orchestrator_runner(self, tmp_path):
        """测试orchestrator runner"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
            output_dir=tmp_path / "output",
            runner="orchestrator",
        )
        
        assert optimizer.runner == "orchestrator"
    
    def test_auto_runner_detection(self, tmp_path):
        """测试auto runner自动探测"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        # 创建replay_harness.py文件以模拟存在
        replay_harness_file = Path("scripts/replay_harness.py")
        original_exists = replay_harness_file.exists()
        
        try:
            # 如果文件不存在，创建一个临时文件
            if not original_exists:
                replay_harness_file.parent.mkdir(exist_ok=True)
                replay_harness_file.write_text("# Temporary test file")
            
            optimizer = ParameterOptimizer(
                base_config_path=config_file,
                search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
                output_dir=tmp_path / "output",
                runner="auto",
            )
            
            assert optimizer.runner == "replay_harness"
        finally:
            # 清理临时文件
            if not original_exists and replay_harness_file.exists():
                replay_harness_file.unlink()


class TestScoreCalculation:
    """测试Fix 9: 多目标综合分计算"""
    
    def test_calculate_score_single_result(self, tmp_path):
        """单个结果时返回net_pnl"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
        )
        
        optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 2.0,
                    "total_slippage": 1.0,
                    "win_rate": 0.5,
                    "max_drawdown": 10.0,
                },
            }
        ]
        
        score = optimizer._calculate_score(
            optimizer.trial_results[0]["metrics"],
            97.0,  # net_pnl
        )
        
        # 单个结果时应该返回net_pnl
        assert score == 97.0
    
    def test_calculate_score_multiple_results(self, tmp_path):
        """多个结果时计算z-score"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
            output_dir=tmp_path / "output",
        )
        
        optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 2.0,
                    "total_slippage": 1.0,
                    "win_rate": 0.5,
                    "max_drawdown": 10.0,
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
                },
            },
        ]
        
        # 计算第一个结果的score
        score = optimizer._calculate_score(
            optimizer.trial_results[0]["metrics"],
            97.0,  # net_pnl = 100 - 2 - 1
        )
        
        # score应该是一个数值（z-score的加权和）
        assert isinstance(score, (int, float))
    
    def test_score_ranking(self, tmp_path):
        """测试按score排序"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
            output_dir=tmp_path / "output",
        )
        
        optimizer.trial_results = [
            {
                "success": True,
                "metrics": {
                    "total_pnl": 100.0,
                    "total_fee": 2.0,
                    "total_slippage": 1.0,
                    "win_rate": 0.5,
                    "max_drawdown": 10.0,
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
                },
            },
        ]
        
        # 计算score
        for result in optimizer.trial_results:
            metrics = result["metrics"]
            net_pnl = metrics["total_pnl"] - metrics["total_fee"] - metrics["total_slippage"]
            result["net_pnl"] = net_pnl
            result["score"] = optimizer._calculate_score(metrics, net_pnl)
        
        # 按score排序
        sorted_results = sorted(
            optimizer.trial_results,
            key=lambda x: x.get("score", 0),
            reverse=True
        )
        
        # 验证：score高的应该排在前面
        assert sorted_results[0]["score"] >= sorted_results[1]["score"]


class TestStderrOutput:
    """测试Fix 10: stderr输出"""
    
    @patch("subprocess.run")
    def test_save_stderr_on_failure(self, mock_run, tmp_path):
        """测试失败时保存stderr"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
        )
        
        # 模拟subprocess失败
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: Test error message"
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        result = optimizer.run_trial(
            trial_config={"backtest": {"taker_fee_bps": 2.0}},
            trial_id=1,
            backtest_args={"input": "test", "date": "2025-01-01", "symbols": ["BTCUSDT"]},
        )
        
        # 验证：应该保存stderr文件
        assert result["success"] is False
        assert "stderr_file" in result
        assert result["stderr_file"].endswith("trial_1_stderr.txt")
        
        # 验证：stderr文件存在且包含错误信息
        stderr_file = Path(result["stderr_file"])
        assert stderr_file.exists()
        assert "Test error message" in stderr_file.read_text(encoding="utf-8")
    
    @patch("subprocess.run")
    def test_command_recorded(self, mock_run, tmp_path):
        """测试记录实际使用的命令"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
            runner="replay_harness",
        )
        
        # 模拟subprocess成功
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        # 模拟结果目录
        output_dir = tmp_path / "output" / "trial_1"
        result_dir = output_dir / "backtest_20250101_000000"
        result_dir.mkdir(parents=True)
        metrics_file = result_dir / "metrics.json"
        metrics_file.write_text(json.dumps({"total_trades": 0}))
        
        result = optimizer.run_trial(
            trial_config={"backtest": {"taker_fee_bps": 2.0}},
            trial_id=1,
            backtest_args={"input": "test", "date": "2025-01-01", "symbols": ["BTCUSDT"]},
        )
        
        # 验证：应该记录命令
        assert "command" in result
        assert "replay_harness.py" in result["command"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

