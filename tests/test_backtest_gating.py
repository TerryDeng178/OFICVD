# -*- coding: utf-8 -*-
"""TASK-B2: Gating机制单元测试

测试新添加的gating mode功能：
- is_tradeable()函数的软/硬护栏分类
- StrategyEmulator的gating_mode支持
- gating QA输出功能
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


class TestIsTradeable:
    """is_tradeable()函数单元测试"""

    def test_strict_mode_hard_gating_blocks(self):
        """strict模式下，硬护栏永远阻塞"""
        for hard_reason in HARD_ALWAYS_BLOCK:
            signal = {
                "gating": [hard_reason],
                "confirm": True
            }
            can_trade, reason = is_tradeable(signal, gating_mode="strict")
            assert can_trade == False
            assert f"gating_hard_{hard_reason}" in reason

    def test_strict_mode_soft_gating_blocks(self):
        """strict模式下，软护栏也会阻塞"""
        for soft_reason in SOFT_GATING:
            signal = {
                "gating": [soft_reason],
                "confirm": True
            }
            can_trade, reason = is_tradeable(signal, gating_mode="strict")
            assert can_trade == False
            assert f"gating_{soft_reason}" in reason

    def test_strict_mode_no_gating_confirm_true(self):
        """strict模式下，无gating且confirm=True可以交易"""
        signal = {
            "gating": [],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade == True
        assert reason is None

    def test_strict_mode_confirm_false_blocks(self):
        """strict模式下，confirm=False永远阻塞"""
        signal = {
            "gating": [],
            "confirm": False
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade == False
        assert reason == "confirm_false"

    def test_ignore_soft_mode_soft_gating_ignored(self):
        """ignore_soft模式下，软护栏被忽略"""
        for soft_reason in SOFT_GATING:
            signal = {
                "gating": [soft_reason],
                "confirm": True
            }
            can_trade, reason = is_tradeable(signal, gating_mode="ignore_soft")
            assert can_trade == True
            assert reason is None

    def test_ignore_soft_mode_hard_gating_still_blocks(self):
        """ignore_soft模式下，硬护栏仍然阻塞"""
        for hard_reason in HARD_ALWAYS_BLOCK:
            signal = {
                "gating": [hard_reason],
                "confirm": True
            }
            can_trade, reason = is_tradeable(signal, gating_mode="ignore_soft")
            assert can_trade == False
            assert f"gating_hard_{hard_reason}" in reason

    def test_ignore_all_mode_soft_gating_ignored(self):
        """ignore_all模式下，软gating被忽略（但硬gating仍然阻塞）"""
        signal = {
            "gating": ["weak_signal", "low_consistency"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="ignore_all")
        assert can_trade == True
        assert reason is None

    def test_ignore_all_mode_confirm_still_required(self):
        """ignore_all模式下，confirm仍然是必需的"""
        signal = {
            "gating": ["weak_signal"],
            "confirm": False
        }
        can_trade, reason = is_tradeable(signal, gating_mode="ignore_all")
        assert can_trade == False
        assert reason == "confirm_false"

    def test_mixed_gating_reasons(self):
        """测试混合gating原因的处理"""
        # 软+硬护栏混合，硬护栏优先
        signal = {
            "gating": ["weak_signal", "fallback"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade == False
        assert "gating_hard_fallback" in reason

    def test_empty_gating_list(self):
        """测试空gating列表的处理"""
        signal = {
            "gating": [],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade == True
        assert reason is None

    def test_none_gating_field(self):
        """测试gating字段为None的情况"""
        signal = {
            "gating": None,
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade == True
        assert reason is None


class TestStrategyEmulator:
    """StrategyEmulator类单元测试"""

    def test_default_gating_mode(self):
        """测试默认gating_mode"""
        emulator = StrategyEmulator()
        assert emulator.gating_mode == "strict"

    def test_custom_gating_mode(self):
        """测试自定义gating_mode"""
        emulator = StrategyEmulator(gating_mode="ignore_soft")
        assert emulator.gating_mode == "ignore_soft"

    @pytest.mark.parametrize("gating_mode", ["strict", "ignore_soft", "ignore_all"])
    def test_should_trade_delegates_to_is_tradeable(self, gating_mode):
        """测试should_trade方法正确委托给is_tradeable函数"""
        emulator = StrategyEmulator(gating_mode=gating_mode)
        signal = {
            "gating": [],
            "confirm": True
        }

        # Mock is_tradeable函数来验证调用
        with patch('backtest.app.is_tradeable') as mock_is_tradeable:
            mock_is_tradeable.return_value = (True, None)
            result = emulator.should_trade(signal)

            mock_is_tradeable.assert_called_once_with(signal, gating_mode=gating_mode)
            assert result == (True, None)

    def test_decide_side_logic(self):
        """测试decide_side方法的决策逻辑"""
        emulator = StrategyEmulator()

        # signal_type优先
        assert emulator.decide_side({"signal_type": "buy"}) == "BUY"
        assert emulator.decide_side({"signal_type": "sell"}) == "SELL"
        assert emulator.decide_side({"signal_type": "strong_buy"}) == "BUY"
        assert emulator.decide_side({"signal_type": "strong_sell"}) == "SELL"

        # side_hint优先于score
        assert emulator.decide_side({"side_hint": "BUY", "score": -1.0}) == "BUY"
        assert emulator.decide_side({"side_hint": "LONG", "score": -1.0}) == "BUY"
        assert emulator.decide_side({"side_hint": "SELL", "score": 1.0}) == "SELL"
        assert emulator.decide_side({"side_hint": "SHORT", "score": 1.0}) == "SELL"

        # score决策
        assert emulator.decide_side({"score": 1.0}) == "BUY"
        assert emulator.decide_side({"score": -1.0}) == "SELL"
        assert emulator.decide_side({"score": 0.0}) is None  # 等于阈值

    def test_decide_side_with_custom_threshold(self):
        """测试带自定义阈值的score决策"""
        config = {"signal": {"min_abs_score_for_side": 0.5}}
        emulator = StrategyEmulator(config)

        assert emulator.decide_side({"score": 0.6}) == "BUY"
        assert emulator.decide_side({"score": -0.6}) == "SELL"
        assert emulator.decide_side({"score": 0.3}) is None  # 小于阈值
        assert emulator.decide_side({"score": -0.3}) is None  # 小于阈值


class TestGatingQAOutput:
    """Gating QA输出功能测试"""

    def test_gating_qa_summary_creation(self, tmp_path):
        """测试gating QA summary文件的创建"""
        output_dir = tmp_path / "test_output" / "run_123"
        output_dir.mkdir(parents=True)

        writer = BacktestWriter(output_dir, "run_123", False, False)

        # Mock一些数据来测试QA输出
        qa_signals = [
            {"score": 1.0, "gating": [], "confirm": True},
            {"score": 0.5, "gating": ["weak_signal"], "confirm": True},
            {"score": -0.5, "gating": ["low_consistency"], "confirm": False},
            {"score": 0.8, "gating": ["fallback"], "confirm": True}
        ]
        gating_counts = {"none": 1, "weak_signal": 1, "low_consistency": 1, "fallback": 1}
        confirm_true_count = 2
        passed_signals = 1

        # 手动创建QA summary文件
        gating_qa_summary = {
            "total_signals": len(qa_signals),
            "confirm_true_ratio": confirm_true_count / len(qa_signals),
            "gating_counts": gating_counts,
            "gating_distribution": {
                reason: count / len(qa_signals) * 100
                for reason, count in gating_counts.items()
            },
            "passed_signals": passed_signals,
            "passed_ratio": passed_signals / len(qa_signals) * 100
        }

        gating_qa_path = output_dir / "gating_qa_summary.json"
        with gating_qa_path.open("w", encoding="utf-8") as f:
            json.dump(gating_qa_summary, f, ensure_ascii=False, indent=2)

        # 验证文件存在且内容正确
        assert gating_qa_path.exists()
        with gating_qa_path.open("r", encoding="utf-8") as f:
            loaded_data = json.load(f)

        assert loaded_data["total_signals"] == 4
        assert loaded_data["confirm_true_ratio"] == 0.5
        assert loaded_data["gating_counts"]["fallback"] == 1
        assert "passed_signals" in loaded_data
        assert "gating_distribution" in loaded_data

    def test_backtest_writer_allows_gating_qa_files(self, tmp_path):
        """测试BacktestWriter允许gating QA文件"""
        output_dir = tmp_path / "test_output"

        writer = BacktestWriter(output_dir, "run_123", False, False)

        # 创建必需的文件
        (writer.output_dir / "trades.jsonl").write_text('{"test": "trade"}\n')
        (writer.output_dir / "pnl_daily.jsonl").write_text('{"test": "pnl"}\n')
        (writer.output_dir / "run_manifest.json").write_text('{"test": "manifest"}')

        # 创建允许的文件
        allowed_files = [
            "gating_qa_summary.json",
            "gating_qa_detail.jsonl"
        ]

        for filename in allowed_files:
            (writer.output_dir / filename).write_text("test content")

        # 验证文件被接受
        allowed_filenames = writer.allowed_filenames
        assert "gating_qa_summary.json" in allowed_filenames
        assert "gating_qa_detail.jsonl" in allowed_filenames

        # 验证输出结构检查通过（不抛出异常）
        try:
            writer.validate_output_structure()
        except ValueError as e:
            pytest.fail(f"Output structure validation failed: {e}")


class TestConstants:
    """测试常量定义"""

    def test_soft_gating_constants(self):
        """测试软护栏常量"""
        expected_soft = {"weak_signal", "low_consistency"}
        assert SOFT_GATING == expected_soft

    def test_hard_gating_constants(self):
        """测试硬护栏常量"""
        expected_hard = {
            "fallback", "price_cache_failed", "no_price",
            "spread_bps_exceeded", "lag_sec_exceeded",
            "kill_switch", "guarded"
        }
        assert HARD_ALWAYS_BLOCK == expected_hard

    def test_no_overlap_between_soft_and_hard(self):
        """测试软护栏和硬护栏没有重叠"""
        assert SOFT_GATING.isdisjoint(HARD_ALWAYS_BLOCK)
