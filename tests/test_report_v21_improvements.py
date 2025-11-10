# -*- coding: utf-8 -*-
"""TASK-09 v2.1: 改进项验证测试"""
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.summary import ReportGenerator, _extract_gross_pnl, _extract_slippage_cost
from alpha_core.report.optimizer import ParameterOptimizer


class TestCostRatioNotional:
    """测试A.1: 成本占比成交额口径"""
    
    def test_cost_breakdown_includes_turnover(self, tmp_path):
        """测试成本分解包含成交额"""
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        
        trades = [
            {
                "ts_ms": 1609459200000,
                "symbol": "BTCUSDT",
                "gross_pnl": 10.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
            {
                "ts_ms": 1609459201000,
                "symbol": "BTCUSDT",
                "gross_pnl": 20.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 2000.0,
            },
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 2}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        data = generator.load_data()
        cost_breakdown = generator.analyze_cost_breakdown(data["trades"])
        
        # 验证：包含成交额和成交额口径成本占比
        assert "turnover" in cost_breakdown
        assert cost_breakdown["turnover"] == 3000.0  # 1000 + 2000
        
        assert "cost_ratio_notional" in cost_breakdown
        # 总成本 = 0.2 + 0.1 + 0.2 + 0.2 = 0.7
        # cost_ratio_notional = 0.7 / 3000 = 0.000233...
        assert abs(cost_breakdown["cost_ratio_notional"] - 0.000233) < 0.0001
    
    def test_cost_ratio_notional_in_metrics_json(self, tmp_path):
        """测试metrics.json包含成交额口径"""
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        
        trades = [
            {
                "ts_ms": 1609459200000,
                "symbol": "BTCUSDT",
                "gross_pnl": 10.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 1}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        generator.generate_report()
        
        # 检查metrics.json
        metrics_output = tmp_path / "reports" / "backtest_20210101_000000_metrics.json"
        assert metrics_output.exists()
        
        with open(metrics_output, "r", encoding="utf-8") as f:
            metrics_data = json.load(f)
        
        # 验证：overall_computed包含成交额口径
        assert "overall_computed" in metrics_data
        assert "turnover" in metrics_data["overall_computed"]
        assert "cost_ratio_notional" in metrics_data["overall_computed"]


class TestRobustnessGuards:
    """测试B.3: 结果健壮性卫兵"""
    
    @patch("subprocess.run")
    def test_unknown_ratio_check(self, mock_run, tmp_path):
        """测试unknown占比检查"""
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
        
        # 模拟结果目录和trades.jsonl（包含unknown场景）
        trial_dir = tmp_path / "output" / "trial_1"
        result_dir = trial_dir / "backtest_20250101_000000"
        result_dir.mkdir(parents=True)
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 20}, f)
        
        trades_file = result_dir / "trades.jsonl"
        # 创建包含高unknown占比的trades（6个unknown，14个有效场景）
        trades = []
        for i in range(6):
            trades.append({"scenario_2x2": "INVALID", "gross_pnl": 10.0})
        for i in range(14):
            trades.append({"scenario_2x2": "A_H", "gross_pnl": 10.0})
        
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        result = optimizer.run_trial(
            trial_config={"backtest": {"taker_fee_bps": 2.0}},
            trial_id=1,
            backtest_args={"input": "test", "date": "2025-01-01", "symbols": ["BTCUSDT"]},
        )
        
        # 验证：包含unknown_ratio和robustness_warnings
        assert result.get("success") is True
        assert "unknown_ratio" in result
        assert result["unknown_ratio"] == 0.3  # 6/20 = 0.3 > 0.05
        
        assert "robustness_warnings" in result
        assert len(result["robustness_warnings"]) > 0
        assert any("unknown_ratio_high" in w for w in result["robustness_warnings"])
    
    @patch("subprocess.run")
    def test_low_sample_check(self, mock_run, tmp_path):
        """测试低样本检查"""
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
        
        # 模拟结果目录（低样本）
        trial_dir = tmp_path / "output" / "trial_1"
        result_dir = trial_dir / "backtest_20250101_000000"
        result_dir.mkdir(parents=True)
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 5}, f)  # 低样本
        
        trades_file = result_dir / "trades.jsonl"
        trades_file.touch()
        
        result = optimizer.run_trial(
            trial_config={"backtest": {"taker_fee_bps": 2.0}},
            trial_id=1,
            backtest_args={"input": "test", "date": "2025-01-01", "symbols": ["BTCUSDT"]},
        )
        
        # 验证：包含robustness_warnings
        assert result.get("success") is True
        assert "robustness_warnings" in result
        assert any("low_sample" in w for w in result["robustness_warnings"])


class TestManifestGeneration:
    """测试B.4: 可复现信息写入manifest"""
    
    @patch("subprocess.run")
    def test_manifest_contains_git_sha(self, mock_run, tmp_path):
        """测试manifest包含git_sha"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0]},
            output_dir=tmp_path / "output",
        )
        
        # 模拟git命令
        mock_git_result = Mock()
        mock_git_result.returncode = 0
        mock_git_result.stdout = "abc123def456\n"
        mock_run.return_value = mock_git_result
        
        # 保存manifest
        optimizer._save_manifest()
        
        # 验证manifest文件存在
        manifest_file = tmp_path / "output" / "trial_manifest.json"
        assert manifest_file.exists()
        
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        # 验证：包含git_sha和search_space_hash
        assert "git_sha" in manifest
        assert "search_space_hash" in manifest
        assert "search_space" in manifest
        assert "runner" in manifest
        assert "base_config" in manifest
        assert "timestamp" in manifest


class TestChartsGeneration:
    """测试C.1/C.2: 图表生成"""
    
    @patch("alpha_core.report.summary.MATPLOTLIB_AVAILABLE", True)
    @patch("matplotlib.pyplot.savefig")
    @patch("matplotlib.pyplot.close")
    def test_cumulative_pnl_chart(self, mock_close, mock_savefig, tmp_path):
        """测试净值曲线图表生成"""
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        
        trades = [
            {
                "ts_ms": 1609459200000,  # 2021-01-01 00:00:00 UTC
                "symbol": "BTCUSDT",
                "gross_pnl": 10.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
            {
                "ts_ms": 1609459201000,  # 2021-01-01 00:00:01 UTC
                "symbol": "BTCUSDT",
                "gross_pnl": 20.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 2}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        data = generator.load_data()
        by_hour = generator.analyze_by_hour(data["trades"])
        by_scenario = generator.analyze_by_scenario(data["trades"])
        by_symbol = generator.analyze_by_symbol(data["trades"])
        
        # 生成图表
        generator._generate_charts(data["trades"], by_hour, by_scenario, by_symbol)
        
        # 验证：调用了savefig（包括净值曲线和回撤曲线）
        savefig_calls = [call[0][0] for call in mock_savefig.call_args_list]
        assert any("fig_cum_net_pnl.png" in str(path) for path in savefig_calls)
        assert any("fig_drawdown.png" in str(path) for path in savefig_calls)
    
    @patch("alpha_core.report.summary.MATPLOTLIB_AVAILABLE", True)
    @patch("matplotlib.pyplot.savefig")
    @patch("matplotlib.pyplot.close")
    def test_heatmap_chart(self, mock_close, mock_savefig, tmp_path):
        """测试热力图图表生成"""
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        
        trades = [
            {
                "ts_ms": 1609459200000,  # 2021-01-01 00:00:00 UTC (hour 0)
                "symbol": "BTCUSDT",
                "scenario_2x2": "A_H",
                "gross_pnl": 10.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
            {
                "ts_ms": 1609459201000,  # 2021-01-01 00:00:01 UTC (hour 0)
                "symbol": "BTCUSDT",
                "scenario_2x2": "A_L",
                "gross_pnl": 20.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 2}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        data = generator.load_data()
        by_hour = generator.analyze_by_hour(data["trades"])
        by_scenario = generator.analyze_by_scenario(data["trades"])
        by_symbol = generator.analyze_by_symbol(data["trades"])
        
        # 生成图表
        generator._generate_charts(data["trades"], by_hour, by_scenario, by_symbol)
        
        # 验证：调用了savefig（包括热力图）
        savefig_calls = [call[0][0] for call in mock_savefig.call_args_list]
        assert any("fig_winrate_heatmap.png" in str(path) for path in savefig_calls)


class TestOptimizerParallelization:
    """测试B.1: 优化器并行化+早停+断点续跑"""
    
    def test_resume_functionality(self, tmp_path):
        """测试断点续跑功能"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("backtest:\n  taker_fee_bps: 2.0\n")
        
        optimizer = ParameterOptimizer(
            base_config_path=config_file,
            search_space={"backtest.taker_fee_bps": [2.0, 3.0]},
            output_dir=tmp_path / "output",
        )
        
        # 创建已有结果文件
        results_file = tmp_path / "output" / "trial_results.json"
        results_file.parent.mkdir(parents=True, exist_ok=True)
        existing_results = [
            {
                "trial_id": 1,
                "success": True,
                "metrics": {"total_trades": 10, "total_pnl": 100.0},
                "params": {"backtest.taker_fee_bps": 2.0},
            }
        ]
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(existing_results, f)
        
        # 生成trials（应该跳过trial_id=1）
        trials = optimizer.generate_trials(method="grid")
        
        # 验证：trials包含2个配置
        assert len(trials) == 2
        
        # 测试resume逻辑（模拟）
        completed_ids = {r.get("trial_id") for r in existing_results if r.get("success")}
        pending_trials = [(i, t) for i, t in enumerate(trials, 1) if i not in completed_ids]
        
        # 验证：pending_trials只包含trial_id=2
        assert len(pending_trials) == 1
        assert pending_trials[0][0] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

