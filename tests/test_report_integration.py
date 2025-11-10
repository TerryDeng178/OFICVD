# -*- coding: utf-8 -*-
"""TASK-09: 报表生成器集成测试"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.report.summary import ReportGenerator


class TestReportGenerationIntegration:
    """集成测试：完整的报表生成流程"""
    
    def test_full_report_generation(self, tmp_path):
        """测试完整的报表生成流程"""
        # 创建回测结果目录结构
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        # 创建测试交易数据
        trades = [
            {
                "ts_ms": 1609459200000,  # 2021-01-01 00:00:00 UTC
                "symbol": "BTCUSDT",
                "side": "buy",
                "px": 50000.0,
                "qty": 0.02,
                "gross_pnl": 10.0,
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
                "scenario_2x2": "A_H",
                "reason": "entry",
            },
            {
                "ts_ms": 1609459201000,
                "symbol": "BTCUSDT",
                "side": "sell",
                "px": 50050.0,
                "qty": 0.02,
                "net_pnl": 8.0,  # 只有net_pnl
                "fee": 0.2,
                "slippage_bps": 1.0,
                "notional": 1000.0,
                "scenario_2x2": "A_L",
                "reason": "exit",
            },
        ]
        
        # 写入trades.jsonl
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        # 写入pnl_daily.jsonl
        pnl_daily_file = result_dir / "pnl_daily.jsonl"
        with open(pnl_daily_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "date": "2021-01-01",
                "symbol": "BTCUSDT",
                "gross_pnl": 18.0,
                "fee": 0.4,
                "slippage": 0.2,
                "net_pnl": 17.4,
                "trades": 2,
            }) + "\n")
        
        # 写入metrics.json
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({
                "total_trades": 2,
                "total_pnl": 18.0,
                "total_fee": 0.4,
                "total_slippage": 0.2,
                "win_rate": 1.0,
                "sharpe_ratio": 1.5,
                "max_drawdown": 0.0,
            }, f)
        
        # 写入run_manifest.json
        manifest_file = result_dir / "run_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump({
                "config": {
                    "backtest": {
                        "fee_model": "taker_static",
                        "slippage_model": "static",
                        "taker_fee_bps": 2.0,
                        "slippage_bps": 1.0,
                        "notional_per_trade": 1000.0,
                    },
                    "strategy": {
                        "mode": "active",
                        "direction": "both",
                        "entry_threshold": 0.0,
                        "exit_threshold": 0.0,
                    },
                },
            }, f)
        
        # 生成报表
        output_dir = tmp_path / "reports"
        generator = ReportGenerator(tmp_path, output_dir)
        report_file = generator.generate_report()
        
        # 验证：报表文件存在
        assert report_file is not None
        assert report_file.exists()
        
        # 验证：metrics.json存在
        metrics_output = output_dir / f"{result_dir.name}_metrics.json"
        assert metrics_output.exists()
        
        # 验证：图表文件存在（如果matplotlib可用）
        chart_files = list(output_dir.glob("fig_*.png"))
        # 图表文件是可选的，不强制要求
        
        # 验证：报表内容
        report_content = report_file.read_text(encoding="utf-8")
        assert "复盘报表" in report_content
        assert "总体表现" in report_content
        assert "按时段分析" in report_content
        assert "按场景分析" in report_content
        assert "按交易对分析" in report_content
        
        # 验证：metrics.json结构
        with open(metrics_output, "r", encoding="utf-8") as f:
            metrics_data = json.load(f)
        
        assert "overall_computed" in metrics_data
        assert "overall_from_engine" in metrics_data
        assert "by_hour" in metrics_data
        assert "by_scenario" in metrics_data
        assert "by_symbol" in metrics_data
        assert "cost_breakdown" in metrics_data
        
        # 验证：PnL口径一致性
        overall_computed = metrics_data["overall_computed"]
        assert "total_gross_pnl" in overall_computed
        assert "total_net_pnl" in overall_computed
        assert overall_computed["total_net_pnl"] == (
            overall_computed["total_gross_pnl"] -
            overall_computed["total_fee"] -
            overall_computed["total_slippage"]
        )
    
    def test_report_with_mixed_pnl_fields(self, tmp_path):
        """测试混合PnL字段的情况"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        # 创建混合字段的交易数据
        trades = [
            {"gross_pnl": 100.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459200000},
            {"net_pnl": 95.0, "fee": 2.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459201000},
            {"gross_pnl": 50.0, "net_pnl": 48.0, "fee": 1.0, "slippage_bps": 1.0, "notional": 1000.0, "ts_ms": 1609459202000},
        ]
        
        trades_file = result_dir / "trades.jsonl"
        with open(trades_file, "w", encoding="utf-8") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
        
        metrics_file = result_dir / "metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump({"total_trades": 3}, f)
        
        generator = ReportGenerator(tmp_path, tmp_path / "reports")
        cost_breakdown = generator.analyze_cost_breakdown(trades)
        
        # 验证：所有交易都能正确处理
        assert cost_breakdown["total_gross_pnl"] > 0
        assert cost_breakdown["total_net_pnl"] < cost_breakdown["total_gross_pnl"]
        assert cost_breakdown["total_net_pnl"] == (
            cost_breakdown["total_gross_pnl"] -
            cost_breakdown["total_fee"] -
            cost_breakdown["total_slippage"]
        )


class TestScenarioNormalizationIntegration:
    """集成测试：场景标准化"""
    
    def test_scenario_normalization_in_report(self, tmp_path):
        """测试报表中的场景标准化"""
        result_dir = tmp_path / "backtest_20250101_000000"
        result_dir.mkdir()
        
        trades = [
            {"scenario_2x2": "A_H", "gross_pnl": 10.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459200000},
            {"scenario_2x2": "A_H_unknown", "gross_pnl": 20.0, "fee": 1.0, "slippage_bps": 0, "notional": 1000, "ts_ms": 1609459201000},
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
        
        # 验证：A_H应该包含前两个交易
        assert "A_H" in by_scenario
        assert by_scenario["A_H"]["count"] == 2
        
        # 验证：INVALID应该被标准化为unknown
        assert "unknown" in by_scenario
        assert by_scenario["unknown"]["count"] == 1
        
        # 验证：报表中不应该有"unknown_unknown"
        assert "unknown_unknown" not in by_scenario


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

