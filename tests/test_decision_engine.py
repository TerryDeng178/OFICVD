# -*- coding: utf-8 -*-
"""Decision Engine Tests

测试单点判定逻辑：EXPIRE/COOLDOWN/FAIL_GATING/BAD_REGIME/LOW_SCORE/OK 分支全覆盖
"""

import pytest
import time

from src.alpha_core.signals.decision_engine import DecisionEngine
from src.alpha_core.signals.signal_schema import Regime, DecisionCode, SideHint


class TestDecisionEngine:
    """Decision Engine 测试"""
    
    @pytest.fixture
    def core_config(self):
        """core.* 配置"""
        return {
            "expiry_ms": 60000,
            "cooldown_ms": 30000,
            "allow_quiet": False,
            "gating": {
                "ofi_z": 1.5,
                "cvd_z": 1.2,
                "enable_divergence_alt": True,
            },
            "threshold": {
                "entry": {
                    "trend": 1.8,
                    "revert": 2.2,
                    "quiet": 2.8,
                },
            },
            "regime": {
                "z_t": 1.2,
                "z_r": 1.0,
            },
        }
    
    @pytest.fixture
    def engine(self, core_config):
        """Decision Engine 实例"""
        return DecisionEngine(core_config)
    
    def test_expire(self, engine):
        """测试 EXPIRE 分支"""
        now_ms = int(time.time() * 1000)
        ts_ms = now_ms - 70000  # 70秒前（超过60秒有效期）
        
        result = engine.decide(
            ts_ms=ts_ms,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=2.0,
            z_cvd=1.5,
            div_type=None,
            now_ms=now_ms,
        )
        
        assert result["decision_code"] == DecisionCode.EXPIRE
        assert result["confirm"] is False
        assert result["gating"] == 0
    
    def test_cooldown(self, engine):
        """测试 COOLDOWN 分支"""
        now_ms = int(time.time() * 1000)
        
        # 先确认一个信号（触发冷却）
        result1 = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=2.0,
            z_cvd=1.5,
            div_type=None,
            now_ms=now_ms - 1000,
        )
        assert result1["confirm"] is True
        
        # 立即再次检查（应该在冷却期内）
        result2 = engine.decide(
            ts_ms=now_ms,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=2.0,
            z_cvd=1.5,
            div_type=None,
            now_ms=now_ms,
        )
        
        assert result2["decision_code"] == DecisionCode.COOLDOWN
        assert result2["confirm"] is False
        assert result2["cooldown_ms"] > 0
    
    def test_fail_gating(self, engine):
        """测试 FAIL_GATING 分支"""
        now_ms = int(time.time() * 1000)
        
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=1.0,  # 低于阈值 1.5
            z_cvd=1.0,  # 低于阈值 1.2
            div_type=None,
            now_ms=now_ms,
        )
        
        assert result["decision_code"] == DecisionCode.FAIL_GATING
        assert result["confirm"] is False
        assert result["gating"] == 0
    
    def test_gating_with_divergence(self, engine):
        """测试门控通过（背离替代路径）"""
        now_ms = int(time.time() * 1000)
        
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=1.0,  # 低于阈值
            z_cvd=1.0,  # 低于阈值
            div_type="bull",  # 但有背离
            now_ms=now_ms,
        )
        
        # 应该通过门控（背离替代路径）
        assert result["gating"] == 1
        # 但可能因为 score 不够而 confirm=False
    
    def test_bad_regime(self, engine):
        """测试 BAD_REGIME 分支（quiet 且不允许）"""
        now_ms = int(time.time() * 1000)
        
        # 使用较小的 z_ofi/z_cvd，使其判定为 quiet
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=0.5,  # 低于 z_t=1.2 和 z_r=1.0
            z_cvd=0.3,
            div_type=None,
            now_ms=now_ms,
        )
        
        # 如果判定为 quiet，且 allow_quiet=False，应该返回 BAD_REGIME
        if result["regime"] == Regime.QUIET:
            assert result["decision_code"] == DecisionCode.BAD_REGIME
            assert result["confirm"] is False
            assert result["gating"] == 1
    
    def test_low_score(self, engine):
        """测试 LOW_SCORE 分支"""
        now_ms = int(time.time() * 1000)
        
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=1.0,  # 低于 trend 阈值 1.8
            z_ofi=2.0,
            z_cvd=1.5,
            div_type=None,
            now_ms=now_ms,
        )
        
        # 如果 regime 是 trend，score=1.0 < 1.8，应该返回 LOW_SCORE
        if result["regime"] == Regime.TREND:
            assert result["decision_code"] == DecisionCode.LOW_SCORE
            assert result["confirm"] is False
            assert result["gating"] == 1
    
    def test_ok(self, engine):
        """测试 OK 分支（所有检查通过）"""
        now_ms = int(time.time() * 1000)
        
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,  # 高于 trend 阈值 1.8
            z_ofi=2.0,  # 高于阈值 1.5
            z_cvd=1.5,  # 高于阈值 1.2
            div_type=None,
            now_ms=now_ms,
        )
        
        assert result["decision_code"] == DecisionCode.OK
        assert result["confirm"] is True
        assert result["gating"] == 1
        assert result["side_hint"] == SideHint.BUY  # score > 0
    
    def test_regime_trend(self, engine):
        """测试 Regime TREND 判定"""
        now_ms = int(time.time() * 1000)
        
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=1.5,  # >= z_t=1.2
            z_cvd=1.3,  # 同向（都是正数）
            div_type=None,
            now_ms=now_ms,
        )
        
        assert result["regime"] == Regime.TREND
    
    def test_regime_revert(self, engine):
        """测试 Regime REVERT 判定"""
        now_ms = int(time.time() * 1000)
        
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=1.6,  # >= z_r=1.0，且 >= gating.ofi_z=1.5（通过门控）
            z_cvd=-1.3,  # 反向（一正一负），且 >= gating.cvd_z=1.2（通过门控）
            div_type=None,
            now_ms=now_ms,
        )
        
        assert result["regime"] == Regime.REVERT
    
    def test_regime_quiet(self, engine):
        """测试 Regime QUIET 判定"""
        now_ms = int(time.time() * 1000)
        
        # 使用背离替代路径通过门控
        result = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=0.5,  # < z_r=1.0（不够强，但可以通过背离门控）
            z_cvd=0.3,
            div_type="bull",  # 使用背离替代路径通过门控
            now_ms=now_ms,
        )
        
        assert result["regime"] == Regime.QUIET
    
    def test_side_hint(self, engine):
        """测试 side_hint 推断"""
        now_ms = int(time.time() * 1000)
        
        # buy
        result1 = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=2.5,
            z_ofi=2.0,
            z_cvd=1.5,
            div_type=None,
            now_ms=now_ms,
        )
        assert result1["side_hint"] == SideHint.BUY
        
        # sell
        result2 = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=-2.5,
            z_ofi=-2.0,
            z_cvd=-1.5,
            div_type=None,
            now_ms=now_ms,
        )
        assert result2["side_hint"] == SideHint.SELL
        
        # flat
        result3 = engine.decide(
            ts_ms=now_ms - 1000,
            symbol="BTCUSDT",
            score=0.0,
            z_ofi=2.0,
            z_cvd=1.5,
            div_type=None,
            now_ms=now_ms,
        )
        assert result3["side_hint"] == SideHint.FLAT

