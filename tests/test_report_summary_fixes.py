# -*- coding: utf-8 -*-
"""TASK-09: 报表生成器修复项单元测试"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

# 导入被测试的函数
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.summary import (
    _extract_gross_pnl,
    _extract_slippage_cost,
    _normalize_scenario,
    ReportGenerator,
)


class TestExtractGrossPnl:
    """测试Fix 3: _extract_gross_pnl函数"""
    
    def test_with_gross_pnl(self):
        """有gross_pnl字段时直接返回"""
        trade = {"gross_pnl": 100.0, "fee": 2.0, "slippage_bps": 1.0}
        assert _extract_gross_pnl(trade) == 100.0
    
    def test_with_net_pnl_only(self):
        """只有net_pnl时回推gross_pnl"""
        trade = {
            "net_pnl": 95.0,
            "fee": 2.0,
            "slippage_bps": 1.0,
            "notional": 1000.0
        }
        # gross_pnl = net_pnl + fee + slippage_cost
        # slippage_cost = 1.0 * 1000 / 10000 = 0.1
        # gross_pnl = 95.0 + 2.0 + 0.1 = 97.1
        expected = 95.0 + 2.0 + (1.0 * 1000 / 10000)
        assert abs(_extract_gross_pnl(trade) - expected) < 0.01
    
    def test_with_both_fields(self):
        """同时有gross_pnl和net_pnl时优先使用gross_pnl"""
        trade = {"gross_pnl": 100.0, "net_pnl": 95.0}
        assert _extract_gross_pnl(trade) == 100.0
    
    def test_with_no_pnl_fields(self):
        """没有PnL字段时返回0"""
        trade = {"symbol": "BTCUSDT"}
        assert _extract_gross_pnl(trade) == 0.0


class TestExtractSlippageCost:
    """测试Fix 6: _extract_slippage_cost函数"""
    
    def test_positive_slippage(self):
        """正滑点"""
        trade = {"slippage_bps": 1.0, "notional": 1000.0}
        assert _extract_slippage_cost(trade) == 0.1
    
    def test_negative_slippage(self):
        """负滑点（取绝对值）"""
        trade = {"slippage_bps": -1.0, "notional": 1000.0}
        assert _extract_slippage_cost(trade) == 0.1
    
    def test_no_slippage(self):
        """无滑点"""
        trade = {"notional": 1000.0}
        assert _extract_slippage_cost(trade) == 0.0
    
    def test_default_notional(self):
        """默认notional=200（保守默认值）"""
        trade = {"slippage_bps": 1.0}
        cost = _extract_slippage_cost(trade)
        assert cost == 0.02  # 1.0 * 200 / 10000
        assert trade.get("_slip_notional_estimated") is True  # 应该标记为估算


class TestNormalizeScenario:
    """测试Fix 5: _normalize_scenario函数"""
    
    def test_valid_scenarios(self):
        """有效场景"""
        assert _normalize_scenario("A_H") == "A_H"
        assert _normalize_scenario("A_L") == "A_L"
        assert _normalize_scenario("Q_H") == "Q_H"
        assert _normalize_scenario("Q_L") == "Q_L"
    
    def test_scenario_with_suffix(self):
        """带后缀的场景（如A_H_unknown）"""
        assert _normalize_scenario("A_H_unknown") == "A_H"
        assert _normalize_scenario("A_L_unknown") == "A_L"
        assert _normalize_scenario("Q_H_unknown") == "Q_H"
        assert _normalize_scenario("Q_L_unknown") == "Q_L"
    
    def test_invalid_scenarios(self):
        """无效场景"""
        assert _normalize_scenario("unknown_unknown") == "unknown"
        assert _normalize_scenario("INVALID") == "unknown"
        assert _normalize_scenario("A_X") == "unknown"
        assert _normalize_scenario("X_H") == "unknown"
    
    def test_none_or_empty(self):
        """None或空字符串"""
        assert _normalize_scenario(None) == "unknown"
        assert _normalize_scenario("") == "unknown"


class TestReportGeneratorPnLConsistency:
    """测试Fix 3: PnL口径一致性"""
    
    def test_analyze_by_hour_pnl_consistency(self, tmp_path):
        """测试按时段分析的PnL口径一致性"""
        # 创建测试数据
        trades = [
            {
                "ts_ms": 1609459200000,  # 2021-01-01 00:00:00 UTC
                "symbol": "BTCUSDT",
                "gross_pnl": 100.0,
                "fee": 2.0,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
            {
                "ts_ms": 1609459201000,  # 同一小时
                "symbol": "BTCUSDT",
                "net_pnl": 95.0,  # 只有net_pnl
                "fee": 2.0,
                "slippage_bps": 1.0,
                "notional": 1000.0,
            },
        ]
        
        # 创建回测结果目录结构
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        
        # 写入trades.jsonl
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        # 写入metrics.json
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 2}, f)
        
        # 创建ReportGenerator
        backtest_dir = tmp_path
        generator = ReportGenerator(backtest_dir, tmp_path / "reports")
        
        # 加载数据并分析
        data = generator.load_data()
        by_hour = generator.analyze_by_hour(data["trades"])
        
        # 验证：应该有两个PnL字段（gross和net）
        hour_0 = by_hour[0]
        assert "pnl_gross" in hour_0
        assert "pnl_net" in hour_0
        
        # 验证：net_pnl = gross_pnl - fee - slippage
        expected_gross = 100.0 + (95.0 + 2.0 + 0.1)  # 两个交易的gross_pnl
        expected_net = expected_gross - (2.0 + 2.0) - (0.1 + 0.1)  # 减去费用和滑点
        
        assert abs(hour_0["pnl_gross"] - expected_gross) < 0.01
        assert abs(hour_0["pnl_net"] - expected_net) < 0.01
    
    def test_cost_breakdown_consistency(self, tmp_path):
        """测试成本分解的PnL口径一致性"""
        # 创建回测结果目录结构
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        (result_dir / "trades.jsonl").write_text("")
        (result_dir / "metrics.json").write_text("{}")
        
        trades = [
            {"gross_pnl": 100.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0},
            {"net_pnl": 95.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0},
        ]
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        cost_breakdown = generator.analyze_cost_breakdown(trades)
        
        # 验证字段存在
        assert "total_gross_pnl" in cost_breakdown
        assert "total_net_pnl" in cost_breakdown
        
        # 验证：net_pnl = gross_pnl - fee - slippage
        expected_gross = 100.0 + (95.0 + 2.0 + 0.1)
        expected_net = expected_gross - 4.0 - 0.2
        
        assert abs(cost_breakdown["total_gross_pnl"] - expected_gross) < 0.01
        assert abs(cost_breakdown["total_net_pnl"] - expected_net) < 0.01
        
        # 验证成本占比基于gross_pnl
        total_cost = cost_breakdown["total_fee"] + cost_breakdown["total_slippage"]
        expected_ratio = total_cost / abs(expected_gross) if expected_gross != 0 else 0
        assert abs(cost_breakdown["cost_ratio"] - expected_ratio) < 0.01


class TestScenarioNormalization:
    """测试Fix 5: 场景标准化"""
    
    def test_analyze_by_scenario_normalization(self, tmp_path):
        """测试按场景分析时的场景标准化"""
        # 创建回测结果目录结构
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        (result_dir / "trades.jsonl").write_text("")
        (result_dir / "metrics.json").write_text("{}")
        
        trades = [
            {"scenario_2x2": "A_H", "gross_pnl": 10.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000},
            {"scenario_2x2": "A_H_unknown", "gross_pnl": 20.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000},
            {"scenario_2x2": "INVALID", "gross_pnl": 30.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000},
            {"scenario_2x2": None, "gross_pnl": 40.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000},
        ]
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        by_scenario = generator.analyze_by_scenario(trades)
        
        # 验证：A_H应该包含前两个交易
        assert "A_H" in by_scenario
        assert by_scenario["A_H"]["count"] == 2
        
        # 验证：INVALID和None应该被标准化为unknown
        assert "unknown" in by_scenario
        assert by_scenario["unknown"]["count"] == 2


class TestMetricsJsonStructure:
    """测试Fix 7: metrics.json结构"""
    
    def test_overall_computed_vs_from_engine(self, tmp_path):
        """测试overall_computed和overall_from_engine的分离"""
        result_dir = tmp_path / "backtest_20210101_000000"
        result_dir.mkdir()
        
        # 创建测试数据
        trades = [
            {"gross_pnl": 100.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459200000},
            {"gross_pnl": -50.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459201000},
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        # 写入原始metrics.json
        metrics_file = result_dir / "metrics.json"
        original_metrics = {
            "total_trades": 2,
            "total_pnl": 50.0,  # 原始引擎计算的（可能口径不一致）
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
        
        # 生成metrics.json
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
        
        # 验证结构
        with open(metrics_output, "r", encoding="utf-8") as f:
            result = json.load(f)
        
        # 验证：应该有overall_computed和overall_from_engine
        assert "overall_computed" in result
        assert "overall_from_engine" in result
        
        # 验证：overall_computed应该有统一口径的指标
        computed = result["overall_computed"]
        assert "total_gross_pnl" in computed
        assert "total_net_pnl" in computed
        assert "win_rate" in computed
        assert "cost_ratio" in computed
        
        # 验证：overall_from_engine保留原始指标
        assert result["overall_from_engine"] == original_metrics


class TestResultDirectorySelection:
    """测试Fix 4: 回测结果目录选择策略"""
    
    def test_select_latest_directory(self, tmp_path):
        """测试选择最新的目录"""
        # 创建多个回测结果目录
        old_dir = tmp_path / "backtest_20210101_000000"
        old_dir.mkdir()
        
        new_dir = tmp_path / "backtest_20210101_120000"
        new_dir.mkdir()
        
        # 修改时间（让new_dir更新）
        import time
        time.sleep(0.1)
        new_dir.touch()
        
        # 创建ReportGenerator
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        
        # 验证：应该选择最新的目录
        assert generator.result_dir == new_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

