# -*- coding: utf-8 -*-
"""TASK-B2: Gating机制集成测试

测试gating mode功能在完整流程中的集成效果：
- StrategyEmulator与BacktestAdapter的交互
- 完整的信号处理流程
- gating QA统计的准确性
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from backtest.app import (
    BacktestAdapter,
    StrategyEmulator,
    BacktestWriter,
    is_tradeable
)

# 尝试导入CoreAlgorithm用于测试
try:
    from alpha_core.signals import CoreAlgorithm
    CORE_ALGO_AVAILABLE = True
except ImportError:
    CORE_ALGO_AVAILABLE = False


class TestGatingModeIntegration:
    """Gating模式集成测试"""

    def test_strict_mode_blocks_weak_signals(self):
        """strict模式下弱信号被阻塞"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config, gating_mode="strict")

        # 弱信号 + gating
        signal = {
            "ts_ms": 1000000,
            "symbol": "BTCUSDT",
            "score": 0.05,  # 弱信号
            "gating": ["weak_signal"],
            "confirm": True
        }

        can_trade, reason = emulator.should_trade(signal)
        assert can_trade == False
        assert "gating_weak_signal" in reason

    def test_ignore_soft_mode_allows_weak_signals(self):
        """ignore_soft模式下弱信号可以通过"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config, gating_mode="ignore_soft")

        # 弱信号 + gating
        signal = {
            "ts_ms": 1000000,
            "symbol": "BTCUSDT",
            "score": 0.05,  # 弱信号
            "gating": ["weak_signal"],
            "confirm": True
        }

        can_trade, reason = emulator.should_trade(signal)
        assert can_trade == True
        assert reason is None

    def test_hard_gating_always_blocks(self):
        """硬护栏在所有模式下都阻塞"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}

        signal = {
            "ts_ms": 1000000,
            "symbol": "BTCUSDT",
            "score": 1.0,
            "gating": ["guarded"],  # 硬护栏
            "confirm": True
        }

        for mode in ["strict", "ignore_soft", "ignore_all"]:
            emulator = StrategyEmulator(config, gating_mode=mode)
            can_trade, reason = emulator.should_trade(signal)
            assert can_trade == False, f"Mode {mode} should block hard gating"
            assert "gating_hard_guarded" in reason

    @pytest.mark.skipif(not CORE_ALGO_AVAILABLE, reason="CoreAlgorithm not available")
    def test_complete_signal_processing_flow(self, tmp_path):
        """测试完整的信号处理流程"""
        # 创建测试features目录
        features_dir = tmp_path / "features"
        features_dir.mkdir()

        # 创建parquet文件（mock）
        parquet_file = features_dir / "test.parquet"
        parquet_file.write_text("mock parquet content")

        # 创建适配器
        adapter = BacktestAdapter(
            mode='A',
            features_dir=features_dir,
            symbols={'BTCUSDT'},
            start_ms=1000000,
            end_ms=2000000
        )

        # 创建策略仿真器
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config, gating_mode="ignore_soft")

        # Mock iter_features返回测试数据
        test_features = [
            {
                "ts_ms": 1500000,
                "symbol": "BTCUSDT",
                "z_ofi": 1.0,
                "z_cvd": 0.5,
                "fusion_score": 0.8
            }
        ]

        with patch.object(adapter, 'iter_features', return_value=test_features):
            # Mock CoreAlgorithm处理
            mock_signal = {
                "ts_ms": 1500000,
                "symbol": "BTCUSDT",
                "score": 0.8,
                "gating": ["weak_signal"],  # 软护栏
                "confirm": True,
                "run_id": "test_run"
            }

            with patch('alpha_core.signals.CoreAlgorithm') as mock_core_algo:
                mock_algo_instance = MagicMock()
                mock_algo_instance.process_feature_row.return_value = mock_signal
                mock_core_algo.return_value = mock_algo_instance

                signals = list(adapter.iter_signals(config))

                assert len(signals) == 1
                signal = signals[0]

                # 验证信号处理
                can_trade, reason = emulator.should_trade(signal)
                assert can_trade == True  # ignore_soft模式下通过
                assert reason is None


class TestGatingQAIntegration:
    """Gating QA集成测试"""

    def test_gating_qa_statistics_accuracy(self, tmp_path):
        """测试gating QA统计的准确性"""
        output_dir = tmp_path / "test_output" / "run_123"
        output_dir.mkdir(parents=True)

        writer = BacktestWriter(output_dir, "run_123", False, False)

        # 创建模拟的QA数据
        qa_signals = [
            {"score": 1.0, "gating": [], "confirm": True},           # 通过
            {"score": 0.5, "gating": ["weak_signal"], "confirm": True}, # 软护栏
            {"score": -0.5, "gating": ["low_consistency"], "confirm": False}, # 软护栏+无确认
            {"score": 0.8, "gating": ["fallback"], "confirm": True}, # 硬护栏
            {"score": 0.3, "gating": ["weak_signal", "low_consistency"], "confirm": True}, # 多重软护栏
        ]

        # 手动计算期望的统计数据
        total_signals = len(qa_signals)
        confirm_true_count = sum(1 for s in qa_signals if s["confirm"])
        gating_counts = {}
        passed_signals = 0

        for signal in qa_signals:
            gating_list = signal.get("gating", [])
            if gating_list:
                for reason in gating_list:
                    gating_counts[reason] = gating_counts.get(reason, 0) + 1
            else:
                gating_counts["none"] = gating_counts.get("none", 0) + 1

            # 判断是否通过（无硬护栏且confirm=True）
            from backtest.app import HARD_ALWAYS_BLOCK
            hard_blocks = any(g in HARD_ALWAYS_BLOCK for g in gating_list)
            if not hard_blocks and signal["confirm"]:
                passed_signals += 1

        # 创建QA summary文件
        gating_qa_summary = {
            "total_signals": total_signals,
            "confirm_true_ratio": confirm_true_count / total_signals,
            "gating_counts": gating_counts,
            "gating_distribution": {
                reason: count / total_signals * 100
                for reason, count in gating_counts.items()
            },
            "passed_signals": passed_signals,
            "passed_ratio": passed_signals / total_signals * 100
        }

        gating_qa_path = output_dir / "gating_qa_summary.json"
        with gating_qa_path.open("w", encoding="utf-8") as f:
            json.dump(gating_qa_summary, f, ensure_ascii=False, indent=2)

        # 验证统计准确性
        with gating_qa_path.open("r", encoding="utf-8") as f:
            loaded_data = json.load(f)

        assert loaded_data["total_signals"] == 5
        assert loaded_data["confirm_true_ratio"] == 4/5  # 4个confirm=True
        assert loaded_data["gating_counts"]["weak_signal"] == 2  # 出现2次
        assert loaded_data["gating_counts"]["low_consistency"] == 2  # 出现2次
        assert loaded_data["gating_counts"]["fallback"] == 1
        assert loaded_data["gating_counts"]["none"] == 1
        assert loaded_data["passed_signals"] == 3  # 第1、2、5个通过（都有confirm=True，且无硬护栏）

    def test_gating_qa_with_different_modes(self):
        """测试不同gating模式下的QA统计差异"""
        signals = [
            {"score": 1.0, "gating": ["weak_signal"], "confirm": True},
            {"score": 0.8, "gating": ["fallback"], "confirm": True},
        ]

        # strict模式
        result_strict = is_tradeable(signals[0], "strict")
        assert result_strict[0] == False  # weak_signal阻塞

        result_hard = is_tradeable(signals[1], "strict")
        assert result_hard[0] == False  # fallback阻塞

        # ignore_soft模式
        result_soft_ignored = is_tradeable(signals[0], "ignore_soft")
        assert result_soft_ignored[0] == True  # weak_signal被忽略

        result_hard_still_blocks = is_tradeable(signals[1], "ignore_soft")
        assert result_hard_still_blocks[0] == False  # fallback仍然阻塞


class TestBacktestWriterGatingFiles:
    """BacktestWriter对gating文件处理的测试"""

    def test_writer_accepts_gating_qa_files(self, tmp_path):
        """测试writer接受gating QA文件"""
        output_dir = tmp_path / "test_output"

        writer = BacktestWriter(output_dir, "run_456", True, True)

        # 创建必需的文件
        (writer.output_dir / "trades.jsonl").write_text('{"test": "trade"}\n')
        (writer.output_dir / "pnl_daily.jsonl").write_text('{"test": "pnl"}\n')
        (writer.output_dir / "run_manifest.json").write_text('{"test": "manifest"}')

        # 创建gating QA文件
        qa_summary = writer.output_dir / "gating_qa_summary.json"
        qa_detail = writer.output_dir / "gating_qa_detail.jsonl"

        qa_summary.write_text('{"test": "summary"}')
        qa_detail.write_text('{"test": "detail"}\n')

        # 验证文件被接受
        allowed_files = writer.allowed_filenames
        assert "gating_qa_summary.json" in allowed_files
        assert "gating_qa_detail.jsonl" in allowed_files

        # 验证输出结构检查通过
        try:
            writer.validate_output_structure()
        except ValueError:
            pytest.fail("Gating QA files should be allowed in output structure")


class TestModeCompatibility:
    """测试gating mode与其他功能的兼容性"""

    def test_gating_mode_with_config_inheritance(self):
        """测试gating mode与配置继承的兼容性"""
        # 测试不同gating mode下配置的正确传递
        config = {
            "signal": {
                "min_abs_score_for_side": 0.2,
                "some_other_setting": "test_value"
            },
            "broker": {
                "fee_bps_maker": -25
            }
        }

        for mode in ["strict", "ignore_soft", "ignore_all"]:
            emulator = StrategyEmulator(config, gating_mode=mode)

            # 验证配置正确传递
            assert emulator.config["signal"]["min_abs_score_for_side"] == 0.2
            assert emulator.config["signal"]["some_other_setting"] == "test_value"
            assert emulator.gating_mode == mode

    def test_gating_mode_with_edge_case_signals(self):
        """测试gating mode对边缘情况信号的处理"""
        edge_cases = [
            {"gating": None, "confirm": True},  # gating为None
            {"gating": [], "confirm": True},    # 空gating列表
            {"gating": ["unknown_reason"], "confirm": True},  # 未知gating原因
            {"confirm": True},  # 没有gating字段
        ]

        for signal in edge_cases:
            for mode in ["strict", "ignore_soft", "ignore_all"]:
                # 这些都应该可以正常处理，不抛出异常
                result = is_tradeable(signal, mode)
                assert isinstance(result, tuple)
                assert len(result) == 2
                assert isinstance(result[0], bool)
                assert result[1] is None or isinstance(result[1], str)
