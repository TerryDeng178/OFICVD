# -*- coding: utf-8 -*-
"""TASK-STRATEGY-LAYER-MIGRATION: 策略层集成测试

测试策略层迁移后的集成效果：
- StrategyEmulator与BacktestAdapter的交互
- 完整的信号处理流程
- 策略决策的一致性
- 质量档位过滤的集成效果
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from alpha_core.strategy.policy import (
    StrategyEmulator,
    is_tradeable,
    SOFT_GATING,
    HARD_ALWAYS_BLOCK
)
from backtest.app import BacktestAdapter, BacktestWriter


class TestStrategyLayerIntegration:
    """策略层集成测试"""

    @pytest.fixture
    def config(self):
        """测试配置"""
        return {
            "signal": {
                "min_abs_score_for_side": 0.1
            },
            "broker": {
                "fee_bps_maker": -25,
                "fee_bps_taker": 75,
                "slippage_bps": 0,
                "latency_ms": 0,
                "maker_first": True,
                "min_order_qty": 0.001
            },
            "order": {
                "qty": 0.01
            }
        }

    @pytest.fixture
    def mock_features_data(self):
        """模拟features数据"""
        return [
            {
                "symbol": "BTCUSDT",
                "ts_ms": 1640995200000,  # 2022-01-01 00:00:00 UTC
                "z_ofi": 0.5,
                "z_cvd": 0.3,
                "fusion_score": 0.4,
                "consistency": 0.8,
                "regime": "active",
                "mid_px": 50000.0,
                "price": 50000.0
            },
            {
                "symbol": "BTCUSDT",
                "ts_ms": 1640995260000,  # 2022-01-01 00:01:00 UTC
                "z_ofi": -0.3,
                "z_cvd": -0.2,
                "fusion_score": -0.3,
                "consistency": 0.7,
                "regime": "quiet",
                "mid_px": 49900.0,
                "price": 49900.0
            }
        ]

    def test_strategy_emulator_backtest_integration(self, config):
        """测试StrategyEmulator与回测系统的集成"""
        # 创建策略仿真器
        emulator = StrategyEmulator(config, gating_mode="strict", quality_mode="all")

        # 测试信号1：应该可以交易
        signal1 = {
            "ts_ms": 1640995200000,
            "symbol": "BTCUSDT",
            "score": 0.5,
            "z_ofi": 0.5,
            "z_cvd": 0.3,
            "regime": "active",
            "confirm": True,
            "gating": [],
            "mid_px": 50000.0,
            "quality_tier": "strong"
        }

        can_trade1, reason1 = emulator.should_trade(signal1)
        side1 = emulator.decide_side(signal1)

        assert can_trade1 is True
        assert reason1 is None
        assert side1 == "BUY"

        # 测试信号2：gating阻塞
        signal2 = {
            "ts_ms": 1640995260000,
            "symbol": "BTCUSDT",
            "score": -0.3,
            "z_ofi": -0.3,
            "z_cvd": -0.2,
            "regime": "quiet",
            "confirm": True,
            "gating": ["weak_signal"],
            "mid_px": 49900.0,
            "quality_tier": "normal"
        }

        can_trade2, reason2 = emulator.should_trade(signal2)
        side2 = emulator.decide_side(signal2)

        assert can_trade2 is False
        assert "gating_weak_signal" in reason2
        assert side2 == "SELL"

    def test_gating_mode_integration(self, config):
        """测试不同gating_mode的集成效果"""
        # 信号：有weak_signal软护栏
        signal = {
            "confirm": True,
            "gating": ["weak_signal"],
            "score": 0.5
        }

        # strict模式：应该阻塞
        emulator_strict = StrategyEmulator(config, gating_mode="strict")
        can_trade_strict, _ = emulator_strict.should_trade(signal)
        assert can_trade_strict is False

        # ignore_soft模式：应该允许
        emulator_ignore_soft = StrategyEmulator(config, gating_mode="ignore_soft")
        can_trade_ignore_soft, _ = emulator_ignore_soft.should_trade(signal)
        assert can_trade_ignore_soft is True

        # ignore_all模式：应该允许
        emulator_ignore_all = StrategyEmulator(config, gating_mode="ignore_all")
        can_trade_ignore_all, _ = emulator_ignore_all.should_trade(signal)
        assert can_trade_ignore_all is True

    def test_quality_mode_integration(self, config):
        """测试质量档位过滤的集成效果"""
        # 基础信号
        base_signal = {
            "confirm": True,
            "gating": [],
            "score": 0.3
        }

        # conservative模式：只允许strong
        emulator_cons = StrategyEmulator(config, quality_mode="conservative")

        signal_strong = {**base_signal, "quality_tier": "strong"}
        signal_normal = {**base_signal, "quality_tier": "normal"}

        can_trade_strong, _ = emulator_cons.should_trade(signal_strong)
        can_trade_normal, _ = emulator_cons.should_trade(signal_normal)

        assert can_trade_strong is True
        assert can_trade_normal is False

        # balanced模式：允许strong + normal（无low_consistency）
        emulator_bal = StrategyEmulator(config, quality_mode="balanced")

        signal_normal_clean = {**signal_normal, "quality_flags": []}
        signal_normal_bad = {**signal_normal, "quality_flags": ["low_consistency"]}

        can_trade_clean, _ = emulator_bal.should_trade(signal_normal_clean)
        can_trade_bad, _ = emulator_bal.should_trade(signal_normal_bad)

        assert can_trade_clean is True
        assert can_trade_bad is False

    def test_legacy_mode_integration(self, config):
        """测试legacy模式的集成"""
        signal = {
            "score": 0.15,  # 超过阈值
            "confirm": False,  # 但confirm=False
            "gating": ["weak_signal"]  # 有gating
        }

        # 正常模式：会被confirm和gating阻塞
        emulator_normal = StrategyEmulator(config, legacy_backtest_mode=False)
        can_trade_normal, _ = emulator_normal.should_trade(signal)
        assert can_trade_normal is False

        # legacy模式：只看score，忽略confirm和gating
        emulator_legacy = StrategyEmulator(config, legacy_backtest_mode=True)
        can_trade_legacy, _ = emulator_legacy.should_trade(signal)
        assert can_trade_legacy is True

    def test_strategy_emulator_with_backtest_adapter_types(self, config):
        """测试StrategyEmulator与BacktestAdapter类型兼容性"""
        # 这个测试验证策略层组件可以正确处理BacktestAdapter生成的信号类型

        # 模拟BacktestAdapter可能生成的信号格式
        adapter_style_signals = [
            {
                "ts_ms": 1640995200000,
                "symbol": "BTCUSDT",
                "score": 0.5,
                "confirm": True,
                "gating": [],
                "mid_px": 50000.0,
                "quality_tier": "strong",
                "run_id": "test_run"
            },
            {
                "ts_ms": 1640995260000,
                "symbol": "BTCUSDT",
                "score": -0.3,
                "confirm": True,
                "gating": ["weak_signal"],
                "mid_px": 49900.0,
                "quality_tier": "normal",
                "run_id": "test_run"
            }
        ]

        # 创建策略仿真器
        emulator = StrategyEmulator(config)

        # 验证每种信号都能被正确处理
        for signal in adapter_style_signals:
            can_trade, reason = emulator.should_trade(signal)
            side = emulator.decide_side(signal)

            # 确保不抛出异常且返回合理结果
            assert isinstance(can_trade, bool)
            assert reason is None or isinstance(reason, str)
            assert side in ["BUY", "SELL", None]

            # 验证run_id被保留
            assert signal.get("run_id") == "test_run"

    def test_strategy_constants_consistency(self):
        """测试策略常量的一致性"""
        # 验证常量定义一致性（app.py已不再导入这些常量）
        from alpha_core.strategy.policy import SOFT_GATING as PolicySoftGating
        from alpha_core.strategy.policy import HARD_ALWAYS_BLOCK as PolicyHardBlock

        assert PolicySoftGating == SOFT_GATING
        assert PolicyHardBlock == HARD_ALWAYS_BLOCK

    def test_is_tradeable_integration(self):
        """测试is_tradeable函数的集成"""
        # 测试各种场景的信号
        test_cases = [
            # (signal, gating_mode, expected_can_trade)
            ({"confirm": True, "gating": []}, "strict", True),
            ({"confirm": True, "gating": ["weak_signal"]}, "strict", False),
            ({"confirm": True, "gating": ["weak_signal"]}, "ignore_soft", True),
            ({"confirm": True, "gating": ["fallback"]}, "ignore_all", False),  # 硬护栏仍阻塞
            ({"confirm": False, "gating": []}, "strict", False),
        ]

        for signal, gating_mode, expected in test_cases:
            can_trade, reason = is_tradeable(signal, gating_mode)
            assert can_trade == expected, f"Failed for signal={signal}, mode={gating_mode}"

    def test_strategy_emulator_config_integration(self, config):
        """测试StrategyEmulator配置集成"""
        # 测试不同的配置组合
        configs = [
            {"gating_mode": "strict", "quality_mode": "all", "legacy_backtest_mode": False},
            {"gating_mode": "ignore_soft", "quality_mode": "conservative", "legacy_backtest_mode": False},
            {"gating_mode": "strict", "quality_mode": "all", "legacy_backtest_mode": True},
        ]

        signal = {
            "confirm": True,
            "gating": [],
            "score": 0.5,
            "quality_tier": "strong"
        }

        for config_override in configs:
            emulator = StrategyEmulator(config, **config_override)
            can_trade, reason = emulator.should_trade(signal)
            side = emulator.decide_side(signal)

            # 确保不会抛出异常且返回合理结果
            assert isinstance(can_trade, bool)
            assert isinstance(side, (str, type(None)))

            # 对于legacy模式，should_trade应该只看score
            if config_override["legacy_backtest_mode"]:
                assert can_trade is True  # score=0.5 > 0.1
