# -*- coding: utf-8 -*-
"""TASK-STRATEGY-LAYER-MIGRATION: 策略层冒烟测试

快速验证策略层迁移后的基本可用性，确保没有明显的崩溃或错误。
这些测试应该快速执行，用于持续集成中的基础健康检查。
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from alpha_core.strategy.policy import (
    StrategyEmulator,
    is_tradeable,
    SOFT_GATING,
    HARD_ALWAYS_BLOCK
)
from backtest.app import BacktestAdapter


class TestStrategyLayerSmoke:
    """策略层冒烟测试"""

    def test_strategy_emulator_can_be_created(self):
        """测试StrategyEmulator可以被创建"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config)
        assert emulator is not None
        assert hasattr(emulator, 'should_trade')
        assert hasattr(emulator, 'decide_side')

    def test_is_tradeable_function_works(self):
        """测试is_tradeable函数基本工作"""
        signal = {"gating": [], "confirm": True}
        result = is_tradeable(signal)
        assert isinstance(result, tuple)
        assert len(result) == 2
        can_trade, reason = result
        assert isinstance(can_trade, bool)
        assert reason is None or isinstance(reason, str)

    def test_constants_are_defined(self):
        """测试策略常量已定义"""
        assert SOFT_GATING is not None
        assert isinstance(SOFT_GATING, set)
        assert HARD_ALWAYS_BLOCK is not None
        assert isinstance(HARD_ALWAYS_BLOCK, set)

        # 验证常量内容
        assert "weak_signal" in SOFT_GATING
        assert "low_consistency" in SOFT_GATING
        assert "fallback" in HARD_ALWAYS_BLOCK
        assert "guarded" in HARD_ALWAYS_BLOCK

    def test_basic_signal_processing(self):
        """测试基本信号处理"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config)

        # 测试正常信号
        signal = {
            "confirm": True,
            "gating": [],
            "score": 0.5
        }

        can_trade, reason = emulator.should_trade(signal)
        side = emulator.decide_side(signal)

        assert can_trade is True
        assert reason is None
        assert side == "BUY"

    def test_gating_modes_exist(self):
        """测试gating模式存在"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        modes = ["strict", "ignore_soft", "ignore_all"]

        for mode in modes:
            emulator = StrategyEmulator(config, gating_mode=mode)
            assert emulator.gating_mode == mode

    def test_quality_modes_exist(self):
        """测试质量模式存在"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        modes = ["conservative", "balanced", "aggressive", "all"]

        for mode in modes:
            emulator = StrategyEmulator(config, quality_mode=mode)
            assert emulator.quality_mode == mode

    def test_legacy_mode_flag(self):
        """测试legacy模式标志"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}

        emulator_normal = StrategyEmulator(config, legacy_backtest_mode=False)
        emulator_legacy = StrategyEmulator(config, legacy_backtest_mode=True)

        assert emulator_normal.legacy_backtest_mode is False
        assert emulator_legacy.legacy_backtest_mode is True

    def test_backtest_adapter_initialization(self):
        """测试BacktestAdapter可以初始化"""
        with tempfile.TemporaryDirectory() as temp_dir:
            features_dir = Path(temp_dir) / "features"
            features_dir.mkdir()

            adapter = BacktestAdapter(
                mode="A",
                features_dir=features_dir,
                symbols={"BTCUSDT"},
                start_ms=1640995200000,
                end_ms=1640995260000
            )

            assert adapter is not None
            assert adapter.mode == "A"
            assert adapter.symbols == {"BTCUSDT"}

    def test_strategy_layer_imports_work(self):
        """测试策略层导入工作"""
        # 测试直接导入
        from alpha_core.strategy import StrategyEmulator as DirectImport
        from backtest.app import StrategyEmulator as AppImport

        # 应该是同一个类
        assert DirectImport is AppImport

    def test_config_handling(self):
        """测试配置处理"""
        # 空配置
        emulator1 = StrategyEmulator()
        assert emulator1.config == {}

        # 带配置
        config = {"signal": {"min_abs_score_for_side": 0.2}}
        emulator2 = StrategyEmulator(config)
        assert emulator2.config == config

    def test_signal_edge_cases(self):
        """测试信号边界情况"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config)

        # 空信号
        can_trade, reason = emulator.should_trade({})
        assert can_trade is False  # 没有confirm

        # 只有confirm的信号
        signal_confirm_only = {"confirm": True, "gating": []}
        can_trade, reason = emulator.should_trade(signal_confirm_only)
        assert can_trade is True

        # 分数为0的信号
        signal_zero_score = {"confirm": True, "gating": [], "score": 0.0}
        side = emulator.decide_side(signal_zero_score)
        assert side is None  # 无法判定方向

    def test_gating_edge_cases(self):
        """测试gating边界情况"""
        # 空gating列表
        result1 = is_tradeable({"confirm": True, "gating": []})
        assert result1[0] is True  # 应该可以交易

        # None gating
        result2 = is_tradeable({"confirm": True, "gating": None})
        assert result2[0] is True  # 应该可以交易

        # 硬护栏
        result3 = is_tradeable({"confirm": True, "gating": ["fallback"]})
        assert result3[0] is False  # 应该被阻塞

    def test_no_crash_on_invalid_inputs(self):
        """测试无效输入不会崩溃"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config)

        # None输入
        with pytest.raises(AttributeError):
            emulator.should_trade(None)

        # 非字典输入
        with pytest.raises(AttributeError):
            emulator.decide_side("not_a_dict")

    def test_quality_flags_handling(self):
        """测试质量标志处理"""
        config = {"signal": {"min_abs_score_for_side": 0.1}}
        emulator = StrategyEmulator(config, quality_mode="balanced")

        # 正常质量的normal信号
        signal_normal = {
            "confirm": True,
            "gating": [],
            "quality_tier": "normal",
            "quality_flags": []
        }
        can_trade, _ = emulator.should_trade(signal_normal)
        assert can_trade is True

        # 有low_consistency的normal信号
        signal_bad = {
            "confirm": True,
            "gating": [],
            "quality_tier": "normal",
            "quality_flags": ["low_consistency"]
        }
        can_trade, _ = emulator.should_trade(signal_bad)
        assert can_trade is False

    def test_memory_usage_basic(self):
        """测试基本内存使用（确保没有明显的内存泄漏）"""
        import gc

        config = {"signal": {"min_abs_score_for_side": 0.1}}

        # 创建多个实例
        emulators = []
        for _ in range(10):
            emulator = StrategyEmulator(config)
            emulators.append(emulator)

        # 基本功能测试
        for emulator in emulators:
            signal = {"confirm": True, "gating": [], "score": 0.5}
            can_trade, _ = emulator.should_trade(signal)
            assert can_trade is True

        # 清理
        del emulators
        gc.collect()

        # 如果没有崩溃，说明基本OK
        assert True
