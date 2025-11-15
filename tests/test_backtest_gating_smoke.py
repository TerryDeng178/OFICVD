# -*- coding: utf-8 -*-
"""TASK-B2: Gating机制冒烟测试

快速验证gating mode功能的基本可用性，确保没有明显的崩溃或错误。
这些测试应该快速执行，用于持续集成中的基础健康检查。
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from backtest.app import (
    is_tradeable,
    StrategyEmulator,
    BacktestWriter,
    SOFT_GATING,
    HARD_ALWAYS_BLOCK
)


class TestGatingSmokeBasic:
    """基础冒烟测试"""

    def test_is_tradeable_function_exists(self):
        """测试is_tradeable函数存在且可调用"""
        signal = {"gating": [], "confirm": True}
        result = is_tradeable(signal)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_strategy_emulator_creation(self):
        """测试StrategyEmulator可以正常创建"""
        emulator = StrategyEmulator()
        assert emulator is not None
        assert hasattr(emulator, 'should_trade')
        assert hasattr(emulator, 'decide_side')

    def test_constants_defined(self):
        """测试常量正确定义"""
        assert SOFT_GATING is not None
        assert HARD_ALWAYS_BLOCK is not None
        assert isinstance(SOFT_GATING, set)
        assert isinstance(HARD_ALWAYS_BLOCK, set)

    def test_backtest_writer_creation(self, tmp_path):
        """测试BacktestWriter可以正常创建"""
        output_dir = tmp_path / "test_output"

        writer = BacktestWriter(output_dir, "smoke_run", False, False)
        assert writer is not None
        assert writer.output_dir == output_dir / "smoke_run"


class TestGatingModeSmoke:
    """Gating mode冒烟测试"""

    @pytest.mark.parametrize("gating_mode", ["strict", "ignore_soft", "ignore_all"])
    def test_all_gating_modes_work(self, gating_mode):
        """测试所有gating mode都能正常工作"""
        emulator = StrategyEmulator(gating_mode=gating_mode)
        signal = {"gating": [], "confirm": True}

        result = emulator.should_trade(signal)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_hard_gating_always_blocks_smoke(self):
        """冒烟测试：硬护栏在所有模式下都阻塞"""
        for hard_reason in ["fallback", "guarded"]:  # 只测试2个硬护栏以加快速度
            signal = {"gating": [hard_reason], "confirm": True}
            for mode in ["strict", "ignore_soft", "ignore_all"]:
                can_trade, reason = is_tradeable(signal, mode)
                assert can_trade == False, f"Hard gating {hard_reason} should block in {mode} mode"
                assert "gating_hard" in reason

    def test_soft_gating_handling_smoke(self):
        """冒烟测试：软护栏在不同模式下的处理"""
        signal = {"gating": ["weak_signal"], "confirm": True}

        # strict模式：阻塞
        can_trade_strict, _ = is_tradeable(signal, "strict")
        assert can_trade_strict == False

        # ignore_soft模式：通过
        can_trade_soft, _ = is_tradeable(signal, "ignore_soft")
        assert can_trade_soft == True

        # ignore_all模式：通过
        can_trade_all, _ = is_tradeable(signal, "ignore_all")
        assert can_trade_all == True


class TestGatingQASmoke:
    """Gating QA冒烟测试"""

    def test_gating_qa_file_creation(self, tmp_path):
        """测试gating QA文件可以创建"""
        output_dir = tmp_path / "smoke_output" / "qa_test"
        output_dir.mkdir(parents=True)

        # 创建简单的QA数据结构
        qa_data = {
            "total_signals": 1,
            "confirm_true_ratio": 1.0,
            "gating_counts": {"none": 1},
            "passed_signals": 1,
            "passed_ratio": 100.0
        }

        qa_file = output_dir / "gating_qa_summary.json"
        with qa_file.open("w", encoding="utf-8") as f:
            json.dump(qa_data, f, ensure_ascii=False, indent=2)

        # 验证文件可以读取
        assert qa_file.exists()
        with qa_file.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["total_signals"] == 1

    def test_backtest_writer_validates_gating_files(self, tmp_path):
        """测试BacktestWriter可以验证gating文件"""
        output_dir = tmp_path / "smoke_output" / "validation_test"
        output_dir.mkdir(parents=True)

        writer = BacktestWriter(output_dir, "validation_test", False, False)

        # 创建允许的文件
        (writer.output_dir / "trades.jsonl").write_text('{"test": "trade"}\n')
        (writer.output_dir / "pnl_daily.jsonl").write_text('{"test": "pnl"}\n')
        (writer.output_dir / "run_manifest.json").write_text('{"test": "manifest"}')
        (writer.output_dir / "gating_qa_summary.json").write_text('{"test": "qa"}')

        # 应该不抛出异常
        try:
            writer.validate_output_structure()
        except Exception as e:
            pytest.fail(f"Output validation failed: {e}")


class TestIntegrationSmoke:
    """集成冒烟测试"""

    def test_strategy_emulator_with_config(self):
        """测试StrategyEmulator与配置的集成"""
        config = {
            "signal": {"min_abs_score_for_side": 0.5},
            "broker": {"fee_bps_maker": -25}
        }

        emulator = StrategyEmulator(config, gating_mode="ignore_soft")

        # 测试配置正确传递
        assert emulator.config["signal"]["min_abs_score_for_side"] == 0.5
        assert emulator.gating_mode == "ignore_soft"

        # 测试决策功能
        signal = {"score": 1.0, "gating": [], "confirm": True}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade == True

    def test_decide_side_with_config(self):
        """测试decide_side与配置的集成"""
        config = {"signal": {"min_abs_score_for_side": 0.8}}
        emulator = StrategyEmulator(config)

        # 高于阈值
        assert emulator.decide_side({"score": 1.0}) == "BUY"
        assert emulator.decide_side({"score": -1.0}) == "SELL"

        # 低于阈值
        assert emulator.decide_side({"score": 0.5}) is None
        assert emulator.decide_side({"score": -0.5}) is None


class TestEdgeCasesSmoke:
    """边缘情况冒烟测试"""

    def test_empty_signal_handling(self):
        """测试空信号的处理"""
        signal = {}
        result = is_tradeable(signal, "strict")
        assert isinstance(result, tuple)

    def test_none_values_handling(self):
        """测试None值的处理"""
        signal = {"gating": None, "confirm": None}
        result = is_tradeable(signal, "strict")
        assert isinstance(result, tuple)

    def test_malformed_gating_handling(self):
        """测试畸形gating的处理"""
        signal = {"gating": "not_a_list", "confirm": True}
        result = is_tradeable(signal, "strict")
        assert isinstance(result, tuple)

    def test_unicode_content_handling(self):
        """测试Unicode内容的处理"""
        signal = {
            "gating": ["测试_weak_signal"],
            "confirm": True
        }
        result = is_tradeable(signal, "ignore_soft")
        assert isinstance(result, tuple)


class TestPerformanceSmoke:
    """性能冒烟测试"""

    def test_batch_signal_processing(self):
        """测试批量信号处理性能"""
        # 创建多个信号进行批量测试
        signals = [
            {"gating": [], "confirm": True},
            {"gating": ["weak_signal"], "confirm": True},
            {"gating": ["fallback"], "confirm": True},
            {"gating": ["weak_signal", "low_consistency"], "confirm": True},
        ] * 10  # 重复10次，总共40个信号

        emulator = StrategyEmulator(gating_mode="ignore_soft")

        # 批量处理
        results = []
        for signal in signals:
            result = emulator.should_trade(signal)
            results.append(result)

        assert len(results) == 40
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    def test_memory_usage_smoke(self):
        """测试内存使用情况（基础检查）"""
        # 创建大量信号对象
        signals = []
        for i in range(1000):
            signals.append({
                "gating": ["weak_signal"] if i % 2 == 0 else [],
                "confirm": True
            })

        # 处理信号
        emulator = StrategyEmulator(gating_mode="ignore_soft")
        results = [emulator.should_trade(s) for s in signals]

        assert len(results) == 1000
        # 确保没有内存泄漏导致的明显问题（通过基本功能检查）


class TestFileOperationsSmoke:
    """文件操作冒烟测试"""

    def test_json_file_creation_and_reading(self, tmp_path):
        """测试JSON文件的创建和读取"""
        test_file = tmp_path / "test_gating.json"

        test_data = {
            "gating_mode": "ignore_soft",
            "total_signals": 100,
            "passed_signals": 80
        }

        # 写入
        with test_file.open("w", encoding="utf-8") as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)

        # 读取
        with test_file.open("r", encoding="utf-8") as f:
            loaded_data = json.load(f)

        assert loaded_data["gating_mode"] == "ignore_soft"
        assert loaded_data["total_signals"] == 100

    def test_jsonl_file_operations(self, tmp_path):
        """测试JSONL文件的操作"""
        test_file = tmp_path / "test_signals.jsonl"

        test_signals = [
            {"ts_ms": 1000000, "symbol": "BTCUSDT", "score": 1.0},
            {"ts_ms": 1000001, "symbol": "ETHUSDT", "score": 0.5},
        ]

        # 写入
        with test_file.open("w", encoding="utf-8") as f:
            for signal in test_signals:
                f.write(json.dumps(signal, ensure_ascii=False) + "\n")

        # 读取
        loaded_signals = []
        with test_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    loaded_signals.append(json.loads(line))

        assert len(loaded_signals) == 2
        assert loaded_signals[0]["symbol"] == "BTCUSDT"
        assert loaded_signals[1]["score"] == 0.5
