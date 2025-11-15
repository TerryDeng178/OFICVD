# -*- coding: utf-8 -*-
"""
Unit tests for alpha_core.strategy.policy module
"""

import pytest
from alpha_core.strategy.policy import (
    SOFT_GATING,
    HARD_ALWAYS_BLOCK,
    is_tradeable,
    StrategyEmulator,
)


class TestIsTradeable:
    """测试is_tradeable函数"""

    def test_strict_mode_hard_block(self):
        """严格模式：硬护栏永远阻塞"""
        signal = {
            "gating": ["fallback"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade is False
        assert "gating_hard_fallback" in reason

    def test_strict_mode_soft_block(self):
        """严格模式：软护栏也会阻塞"""
        signal = {
            "gating": ["weak_signal"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade is False
        assert "gating_weak_signal" in reason

    def test_ignore_soft_mode(self):
        """ignore_soft模式：忽略软护栏"""
        signal = {
            "gating": ["weak_signal", "low_consistency"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="ignore_soft")
        assert can_trade is True
        assert reason is None

    def test_ignore_soft_mode_hard_still_blocks(self):
        """ignore_soft模式：硬护栏仍然阻塞"""
        signal = {
            "gating": ["weak_signal", "fallback"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="ignore_soft")
        assert can_trade is False
        assert "gating_hard_fallback" in reason

    def test_ignore_all_mode_soft_ignored(self):
        """ignore_all模式：忽略软护栏，但硬护栏仍然阻塞"""
        signal = {
            "gating": ["weak_signal", "low_consistency"],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="ignore_all")
        assert can_trade is True
        assert reason is None

    def test_confirm_false(self):
        """confirm=False时一定不交易"""
        signal = {
            "gating": [],
            "confirm": False
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade is False
        assert reason == "confirm_false"

    def test_no_gating_confirm_true(self):
        """无gating且confirm=True时可以交易"""
        signal = {
            "gating": [],
            "confirm": True
        }
        can_trade, reason = is_tradeable(signal, gating_mode="strict")
        assert can_trade is True
        assert reason is None


class TestStrategyEmulator:
    """测试StrategyEmulator类"""

    @pytest.fixture
    def config(self):
        """测试配置"""
        return {
            "signal": {
                "min_abs_score_for_side": 0.1
            }
        }

    def test_legacy_mode_true(self, config):
        """legacy模式：只看score绝对值"""
        emulator = StrategyEmulator(config, legacy_backtest_mode=True)

        # score >= 0.1 时应该交易
        signal = {"score": 0.2}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is True

        # score < 0.1 时不交易
        signal = {"score": 0.05}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is False
        assert "score_too_low_for_legacy_mode" in reason

    def test_decide_side_signal_type(self, config):
        """测试signal_type决策"""
        emulator = StrategyEmulator(config)

        assert emulator.decide_side({"signal_type": "buy"}) == "BUY"
        assert emulator.decide_side({"signal_type": "sell"}) == "SELL"
        assert emulator.decide_side({"signal_type": "strong_buy"}) == "BUY"
        assert emulator.decide_side({"signal_type": "strong_sell"}) == "SELL"

    def test_decide_side_side_hint(self, config):
        """测试side_hint决策"""
        emulator = StrategyEmulator(config)

        assert emulator.decide_side({"side_hint": "BUY"}) == "BUY"
        assert emulator.decide_side({"side_hint": "SELL"}) == "SELL"
        assert emulator.decide_side({"side_hint": "LONG"}) == "BUY"
        assert emulator.decide_side({"side_hint": "SHORT"}) == "SELL"

    def test_decide_side_score(self, config):
        """测试score决策"""
        emulator = StrategyEmulator(config)

        assert emulator.decide_side({"score": 0.5}) == "BUY"
        assert emulator.decide_side({"score": -0.5}) == "SELL"
        assert emulator.decide_side({"score": 0.05}) is None  # 小于阈值

    def test_quality_mode_conservative(self, config):
        """conservative模式：只允许strong档位"""
        emulator = StrategyEmulator(config, quality_mode="conservative")

        # strong档位应该允许
        signal = {"confirm": True, "quality_tier": "strong"}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is True

        # 其他档位应该拒绝
        signal = {"confirm": True, "quality_tier": "normal"}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is False
        assert "not_allowed_in_conservative_mode" in reason

    def test_quality_mode_balanced(self, config):
        """balanced模式：strong + normal（无low_consistency）"""
        emulator = StrategyEmulator(config, quality_mode="balanced")

        # strong档位允许
        signal = {"confirm": True, "quality_tier": "strong"}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is True

        # normal档位无low_consistency时允许
        signal = {"confirm": True, "quality_tier": "normal", "quality_flags": []}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is True

        # normal档位有low_consistency时拒绝
        signal = {"confirm": True, "quality_tier": "normal", "quality_flags": ["low_consistency"]}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is False
        assert "low_consistency_not_allowed_in_balanced_mode" in reason

        # weak档位拒绝
        signal = {"confirm": True, "quality_tier": "weak"}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is False

    def test_quality_mode_aggressive(self, config):
        """aggressive模式：所有confirm=True的信号都允许"""
        emulator = StrategyEmulator(config, quality_mode="aggressive")

        # 所有confirm=True的信号都应该允许
        signal = {"confirm": True, "quality_tier": "weak", "quality_flags": ["low_consistency"]}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is True

    def test_quality_mode_all(self, config):
        """all模式：无质量过滤"""
        emulator = StrategyEmulator(config, quality_mode="all")

        # 所有confirm=True的信号都应该允许
        signal = {"confirm": True}
        can_trade, reason = emulator.should_trade(signal)
        assert can_trade is True


class TestConstants:
    """测试常量定义"""

    def test_soft_gating_constants(self):
        """验证SOFT_GATING常量"""
        assert "weak_signal" in SOFT_GATING
        assert "low_consistency" in SOFT_GATING
        assert len(SOFT_GATING) == 2

    def test_hard_block_constants(self):
        """验证HARD_ALWAYS_BLOCK常量"""
        expected_hard = {
            "fallback", "price_cache_failed", "no_price",
            "spread_bps_exceeded", "lag_sec_exceeded",
            "kill_switch", "guarded"
        }
        assert HARD_ALWAYS_BLOCK == expected_hard
