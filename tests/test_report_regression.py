# -*- coding: utf-8 -*-
"""TASK-09: 报表生成器回归测试"""
import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.summary import ReportGenerator


class TestPnLConsistencyRegression:
    """回归测试：PnL口径一致性"""
    
    def test_no_double_deduction(self, tmp_path):
        """测试：确保费用和滑点不会被重复扣减"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        # 创建只有net_pnl的交易（模拟上游已扣减成本）
        trades = [
            {
                "ts_ms": 1609459200000,
                "symbol": "BTCUSDT",
                "net_pnl": 95.0,  # 已经扣除了费用和滑点
                "fee": 2.0,
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
        cost_breakdown = generator.analyze_cost_breakdown(trades)
        
        # 验证：gross_pnl应该回推正确
        # gross_pnl = net_pnl + fee + slippage_cost
        # slippage_cost = 1.0 * 1000 / 10000 = 0.1
        expected_gross = 95.0 + 2.0 + 0.1
        
        assert abs(cost_breakdown["total_gross_pnl"] - expected_gross) < 0.01
        
        # 验证：net_pnl应该等于原始net_pnl（不重复扣减）
        assert abs(cost_breakdown["total_net_pnl"] - 95.0) < 0.01
        
        # 验证：成本占比应该基于gross_pnl
        total_cost = cost_breakdown["total_fee"] + cost_breakdown["total_slippage"]
        expected_ratio = total_cost / abs(expected_gross)
        assert abs(cost_breakdown["cost_ratio"] - expected_ratio) < 0.01
    
    def test_gross_pnl_consistency_across_analyses(self, tmp_path):
        """测试：所有分析函数使用相同的gross_pnl口径"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        trades = [
            {
                "ts_ms": 1609459200000,
                "symbol": "BTCUSDT",
                "gross_pnl": 100.0,
                "fee": 2.0,
                "slippage_bps": 1.0,
                "notional": 1000.0,
                "scenario_2x2": "A_H",
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
        data = generator.load_data()
        
        # 执行各种分析
        by_hour = generator.analyze_by_hour(data["trades"])
        by_scenario = generator.analyze_by_scenario(data["trades"])
        by_symbol = generator.analyze_by_symbol(data["trades"])
        cost_breakdown = generator.analyze_cost_breakdown(data["trades"])
        
        # 验证：所有分析中的gross_pnl应该一致
        hour_0_gross = by_hour[0]["pnl_gross"]
        scenario_gross = by_scenario["A_H"]["pnl_gross"]
        symbol_gross = by_symbol["BTCUSDT"]["pnl_gross"]
        breakdown_gross = cost_breakdown["total_gross_pnl"]
        
        assert abs(hour_0_gross - 100.0) < 0.01
        assert abs(scenario_gross - 100.0) < 0.01
        assert abs(symbol_gross - 100.0) < 0.01
        assert abs(breakdown_gross - 100.0) < 0.01
        
        # 验证：所有分析中的net_pnl应该一致
        hour_0_net = by_hour[0]["pnl_net"]
        scenario_net = by_scenario["A_H"]["pnl_net"]
        symbol_net = by_symbol["BTCUSDT"]["pnl_net"]
        breakdown_net = cost_breakdown["total_net_pnl"]
        
        expected_net = 100.0 - 2.0 - 0.1
        
        assert abs(hour_0_net - expected_net) < 0.01
        assert abs(scenario_net - expected_net) < 0.01
        assert abs(symbol_net - expected_net) < 0.01
        assert abs(breakdown_net - expected_net) < 0.01


class TestScenarioNormalizationRegression:
    """回归测试：场景标准化"""
    
    def test_no_unknown_unknown(self, tmp_path):
        """测试：不应该出现unknown_unknown场景"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        trades = [
            {"scenario_2x2": None, "gross_pnl": 10.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459200000},
            {"scenario_2x2": "", "gross_pnl": 20.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459201000},
            {"scenario_2x2": "INVALID", "gross_pnl": 30.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459202000},
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 3}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        data = generator.load_data()
        by_scenario = generator.analyze_by_scenario(data["trades"])
        
        # 验证：不应该有unknown_unknown
        assert "unknown_unknown" not in by_scenario
        
        # 验证：应该有unknown
        assert "unknown" in by_scenario
        assert by_scenario["unknown"]["count"] == 3
    
    def test_valid_scenarios_preserved(self, tmp_path):
        """测试：有效场景应该被保留"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        trades = [
            {"scenario_2x2": "A_H", "gross_pnl": 10.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459200000},
            {"scenario_2x2": "A_L", "gross_pnl": 20.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459201000},
            {"scenario_2x2": "Q_H", "gross_pnl": 30.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459202000},
            {"scenario_2x2": "Q_L", "gross_pnl": 40.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459203000},
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 4}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        data = generator.load_data()
        by_scenario = generator.analyze_by_scenario(data["trades"])
        
        # 验证：所有有效场景都应该存在
        assert "A_H" in by_scenario
        assert "A_L" in by_scenario
        assert "Q_H" in by_scenario
        assert "Q_L" in by_scenario
        
        # 验证：每个场景的交易数
        assert by_scenario["A_H"]["count"] == 1
        assert by_scenario["A_L"]["count"] == 1
        assert by_scenario["Q_H"]["count"] == 1
        assert by_scenario["Q_L"]["count"] == 1


class TestMetricsJsonStructureRegression:
    """回归测试：metrics.json结构"""
    
    def test_overall_computed_structure(self, tmp_path):
        """测试：overall_computed结构完整性"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        trades = [
            {"gross_pnl": 100.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459200000},
            {"gross_pnl": -50.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459201000},
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        original_metrics = {
            "total_trades": 2,
            "total_pnl": 50.0,  # 原始引擎计算的
            "win_rate": 0.5,
        }
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump(original_metrics, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        data = generator.load_data()
        
        by_hour = generator.analyze_by_hour(data["trades"])
        by_scenario = generator.analyze_by_scenario(data["trades"])
        by_symbol = generator.analyze_by_symbol(data["trades"])
        cost_breakdown = generator.analyze_cost_breakdown(data["trades"])
        
        metrics_output = tmp_path / "reports" / "test_metrics.json"
        generator._generate_metrics_json(
            metrics_output,
            data["trades"],
            data["metrics"],
            by_hour,
            by_scenario,
            by_symbol,
            cost_breakdown,
        )
        
        with open(metrics_output, "r", encoding="utf-8") as f:
            result = json.load(f)
        
        # 验证：overall_computed应该有所有必需字段
        computed = result["overall_computed"]
        required_fields = [
            "total_trades",
            "total_gross_pnl",
            "total_net_pnl",
            "total_fee",
            "total_slippage",
            "total_cost",
            "win_rate",
            "risk_reward_ratio",
            "cost_ratio",
            "wins",
            "losses",
        ]
        
        for field in required_fields:
            assert field in computed, f"Missing field: {field}"
        
        # 验证：overall_from_engine应该保留原始指标
        assert result["overall_from_engine"] == original_metrics
        
        # 验证：overall_computed的指标应该基于统一口径
        assert computed["total_gross_pnl"] == cost_breakdown["total_gross_pnl"]
        assert computed["total_net_pnl"] == cost_breakdown["total_net_pnl"]
        assert computed["total_fee"] == cost_breakdown["total_fee"]
        assert computed["total_slippage"] == cost_breakdown["total_slippage"]
        assert computed["cost_ratio"] == cost_breakdown["cost_ratio"]


class TestDirectorySelectionRegression:
    """回归测试：目录选择策略"""
    
    def test_latest_directory_selected(self, tmp_path):
        """测试：应该选择最新的目录"""
        import time
        
        # 创建多个回测结果目录
        old_dir = tmp_path / "backtest_20250101_000000"
        old_dir.mkdir()
        time.sleep(0.1)
        
        new_dir = tmp_path / "backtest_20250101_120000"
        new_dir.mkdir()
        time.sleep(0.1)
        new_dir.touch()  # 更新修改时间
        
        # 创建必要的文件
        (old_dir / "trades.jsonl").write_text("")
        (old_dir / "metrics.json").write_text("{}")
        (new_dir / "trades.jsonl").write_text("")
        (new_dir / "metrics.json").write_text("{}")
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        
        # 验证：应该选择最新的目录
        assert generator.result_dir == new_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

