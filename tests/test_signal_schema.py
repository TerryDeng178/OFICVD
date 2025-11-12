# -*- coding: utf-8 -*-
"""Signal Schema v2 Tests

测试 signal/v2 schema 的字段/类型/枚举/约束
"""

import pytest
from pydantic import ValidationError

from src.alpha_core.signals.signal_schema import (
    SignalV2,
    SideHint,
    DivType,
    Regime,
    DecisionCode,
    validate_signal_v2,
    upgrade_v1_to_v2,
)


class TestSignalSchema:
    """Signal v2 Schema 测试"""
    
    def test_schema_basic_fields(self):
        """测试基本字段"""
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="r42-BTCUSDT-1731369600123-0",
            score=2.41,
            side_hint=SideHint.BUY,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            config_hash="9ef1d7ab",
            run_id="r42",
        )
        
        assert signal.schema_version == "signal/v2"
        assert signal.ts_ms == 1731369600123
        assert signal.symbol == "BTCUSDT"
        assert signal.score == 2.41
        assert signal.side_hint == SideHint.BUY
        assert signal.regime == Regime.TREND
        assert signal.gating == 1
        assert signal.confirm is True
        assert signal.decision_code == DecisionCode.OK
    
    def test_schema_constraint_confirm_requires_gating(self):
        """测试约束：confirm=true 需要 gating=1"""
        with pytest.raises(ValidationError) as exc_info:
            SignalV2(
                ts_ms=1731369600123,
                symbol="BTCUSDT",
                signal_id="test-1",
                score=2.41,
                side_hint=SideHint.BUY,
                regime=Regime.TREND,
                gating=0,  # gating=0
                confirm=True,  # 但 confirm=True
                expiry_ms=60000,
                decision_code=DecisionCode.OK,
                config_hash="test",
                run_id="r42",
            )
        assert "confirm=true requires gating=1" in str(exc_info.value)
    
    def test_schema_constraint_confirm_requires_ok(self):
        """测试约束：confirm=true 需要 decision_code=OK"""
        with pytest.raises(ValidationError) as exc_info:
            SignalV2(
                ts_ms=1731369600123,
                symbol="BTCUSDT",
                signal_id="test-1",
                score=2.41,
                side_hint=SideHint.BUY,
                regime=Regime.TREND,
                gating=1,
                confirm=True,  # confirm=True
                expiry_ms=60000,
                decision_code=DecisionCode.LOW_SCORE,  # 但 decision_code != OK
                config_hash="test",
                run_id="r42",
            )
        assert "confirm=true requires decision_code=OK" in str(exc_info.value)
    
    def test_schema_side_hint_enum(self):
        """测试 side_hint 枚举"""
        for side in ["buy", "sell", "flat"]:
            signal = SignalV2(
                ts_ms=1731369600123,
                symbol="BTCUSDT",
                signal_id="test-1",
                score=1.0 if side == "buy" else (-1.0 if side == "sell" else 0.0),
                side_hint=side,
                regime=Regime.TREND,
                gating=0,
                confirm=False,
                expiry_ms=60000,
                decision_code=DecisionCode.LOW_SCORE,
                config_hash="test",
                run_id="r42",
            )
            assert signal.side_hint == side
    
    def test_schema_regime_enum(self):
        """测试 regime 枚举"""
        for regime in ["quiet", "trend", "revert", "unknown"]:
            signal = SignalV2(
                ts_ms=1731369600123,
                symbol="BTCUSDT",
                signal_id="test-1",
                score=1.0,
                side_hint=SideHint.BUY,
                regime=regime,
                gating=0,
                confirm=False,
                expiry_ms=60000,
                decision_code=DecisionCode.LOW_SCORE,
                config_hash="test",
                run_id="r42",
            )
            assert signal.regime == regime
    
    def test_schema_decision_code_enum(self):
        """测试 decision_code 枚举"""
        for code in ["OK", "COOLDOWN", "EXPIRE", "LOW_SCORE", "BAD_REGIME", "FAIL_GATING"]:
            signal = SignalV2(
                ts_ms=1731369600123,
                symbol="BTCUSDT",
                signal_id="test-1",
                score=1.0,
                side_hint=SideHint.BUY,
                regime=Regime.TREND,
                gating=0,
                confirm=False,
                expiry_ms=60000,
                decision_code=code,
                config_hash="test",
                run_id="r42",
            )
            assert signal.decision_code == code
    
    def test_schema_optional_fields(self):
        """测试可选字段"""
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="test-1",
            score=2.41,
            side_hint=SideHint.BUY,
            z_ofi=1.8,
            z_cvd=1.5,
            div_type=DivType.BULL,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            decision_reason="score>=entry & trend",
            config_hash="9ef1d7ab",
            run_id="r42",
            meta={"window_ms": 120000, "features_ver": "ofi/cvd v3"},
        )
        
        assert signal.z_ofi == 1.8
        assert signal.z_cvd == 1.5
        assert signal.div_type == DivType.BULL
        assert signal.decision_reason == "score>=entry & trend"
        assert signal.meta == {"window_ms": 120000, "features_ver": "ofi/cvd v3"}
    
    def test_schema_dict_for_jsonl(self):
        """测试 JSONL 序列化"""
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="test-1",
            score=2.41,
            side_hint=SideHint.BUY,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            config_hash="test",
            run_id="r42",
        )
        
        data = signal.dict_for_jsonl()
        assert data["schema_version"] == "signal/v2"
        assert data["side_hint"] == "buy"  # 枚举值序列化为字符串
        assert data["regime"] == "trend"
        assert data["decision_code"] == "OK"
    
    def test_schema_dict_for_sqlite(self):
        """测试 SQLite 序列化（meta 转为 JSON 字符串）"""
        signal = SignalV2(
            ts_ms=1731369600123,
            symbol="BTCUSDT",
            signal_id="test-1",
            score=2.41,
            side_hint=SideHint.BUY,
            regime=Regime.TREND,
            gating=1,
            confirm=True,
            expiry_ms=60000,
            decision_code=DecisionCode.OK,
            config_hash="test",
            run_id="r42",
            meta={"window_ms": 120000},
        )
        
        data = signal.dict_for_sqlite()
        assert isinstance(data["meta"], str)  # meta 应该是 JSON 字符串
        import json
        assert json.loads(data["meta"]) == {"window_ms": 120000}
    
    def test_validate_signal_v2(self):
        """测试 validate_signal_v2 函数"""
        data = {
            "ts_ms": 1731369600123,
            "symbol": "BTCUSDT",
            "signal_id": "test-1",
            "score": 2.41,
            "side_hint": "buy",
            "regime": "trend",
            "gating": 1,
            "confirm": True,
            "expiry_ms": 60000,
            "decision_code": "OK",
            "config_hash": "test",
            "run_id": "r42",
        }
        
        signal = validate_signal_v2(data)
        assert isinstance(signal, SignalV2)
        assert signal.confirm is True
    
    def test_upgrade_v1_to_v2(self):
        """测试 v1→v2 升级器"""
        v1_data = {
            "ts_ms": 1731369600123,
            "symbol": "BTCUSDT",
            "score": 2.41,
            "z_ofi": 1.8,
            "z_cvd": 1.5,
            "confirm": True,
            "gating": 1,
            "run_id": "r42",
        }
        
        v2_data = upgrade_v1_to_v2(v1_data)
        
        assert v2_data["schema_version"] == "signal/v2"
        assert "signal_id" in v2_data
        assert "side_hint" in v2_data
        assert v2_data["side_hint"] == "buy"  # score > 0 → buy
        assert "regime" in v2_data
        assert "cooldown_ms" in v2_data
        assert "expiry_ms" in v2_data
        assert "decision_code" in v2_data
        assert "config_hash" in v2_data
        assert "meta" in v2_data
    
    def test_upgrade_v1_to_v2_with_core_config(self):
        """测试 v1→v2 升级器（带 core_config）"""
        v1_data = {
            "ts_ms": 1731369600123,
            "symbol": "BTCUSDT",
            "score": 2.41,
            "confirm": True,
            "run_id": "r42",
        }
        
        core_config = {
            "expiry_ms": 30000,
            "cooldown_ms": 15000,
        }
        
        v2_data = upgrade_v1_to_v2(v1_data, core_config)
        
        assert v2_data["expiry_ms"] == 30000
        assert v2_data["cooldown_ms"] == 0  # 默认值

