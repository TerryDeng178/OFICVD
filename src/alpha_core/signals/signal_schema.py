# -*- coding: utf-8 -*-
"""Signal Schema v2

统一信号输出契约（signal/v2）与强 Schema 校验
"""

from enum import Enum
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, model_validator, field_validator


class SideHint(str, Enum):
    """方向提示"""
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


class DivType(str, Enum):
    """背离类型"""
    NONE = "none"
    BULL = "bull"
    BEAR = "bear"


class Regime(str, Enum):
    """市场状态"""
    QUIET = "quiet"
    TREND = "trend"
    REVERT = "revert"
    UNKNOWN = "unknown"


class DecisionCode(str, Enum):
    """判定代码"""
    OK = "OK"
    COOLDOWN = "COOLDOWN"
    EXPIRE = "EXPIRE"
    LOW_SCORE = "LOW_SCORE"
    BAD_REGIME = "BAD_REGIME"
    FAIL_GATING = "FAIL_GATING"


class SignalV2(BaseModel):
    """Signal v2 Schema
    
    统一信号输出契约，所有判定逻辑收敛到 CoreAlgorithm 单点
    """
    
    schema_version: Literal["signal/v2"] = Field(default="signal/v2", description="契约版本")
    ts_ms: int = Field(..., description="UTC 毫秒级时间戳")
    symbol: str = Field(..., description="交易对（大写标准化，如 BTCUSDT）")
    
    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, v):
        """P1 修复2: 把 symbol 大写化下沉到 Schema，在契约层统一规范化"""
        if isinstance(v, str):
            return v.upper()
        return str(v).upper()
    signal_id: str = Field(..., description="幂等键：<run_id>-<symbol>-<ts_ms>-<seq>")
    score: float = Field(..., description="归一化打分（-inf..+inf，推荐范围 -5..+5）")
    side_hint: SideHint = Field(..., description="方向提示")
    z_ofi: Optional[float] = Field(None, description="OFI z-score（可选审计）")
    z_cvd: Optional[float] = Field(None, description="CVD z-score（可选审计）")
    div_type: Optional[DivType] = Field(None, description="背离类型（可选）")
    regime: Regime = Field(..., description="市场状态判定（单点产出）")
    gating: int = Field(..., ge=0, le=1, description="是否通过门控（单点产出）")
    confirm: bool = Field(..., description="是否形成可执行信号")
    cooldown_ms: int = Field(default=0, ge=0, description="当前信号需要执行的冷却时长（ms），0 表示不受限")
    expiry_ms: int = Field(..., ge=0, description="信号有效期（ms），到期仍未执行则无效")
    decision_code: DecisionCode = Field(..., description="判定代码")
    decision_reason: Optional[str] = Field(None, description="人类可读原因（简短）")
    config_hash: str = Field(..., description="core.* 参数哈希（稳定序列化+SHA1）")
    run_id: str = Field(..., description="本次运行指纹（回放可溯源）")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="其他审计字段")
    
    @field_validator("side_hint", mode="before")
    @classmethod
    def validate_side_hint(cls, v):
        """标准化 side_hint"""
        if isinstance(v, str):
            v = v.lower()
            if v in ["buy", "sell", "flat"]:
                return v
        raise ValueError(f"Invalid side_hint: {v}")
    
    @model_validator(mode="after")
    def validate_confirm_constraint(self):
        """约束：confirm=true ⇒ gating=1 && decision_code=OK"""
        if self.confirm:
            if self.gating != 1:
                raise ValueError("confirm=true requires gating=1")
            if self.decision_code != DecisionCode.OK:
                raise ValueError("confirm=true requires decision_code=OK")
        return self
    
    model_config = {
        "use_enum_values": True,
        "json_encoders": {
            Enum: lambda v: v.value if isinstance(v, Enum) else v,
        },
    }
    
    def dict_for_jsonl(self) -> Dict[str, Any]:
        """转换为 JSONL 格式（稳定序列化）"""
        data = self.model_dump(exclude_none=False, by_alias=False)
        # 确保枚举值序列化为字符串
        for key, value in data.items():
            if isinstance(value, Enum):
                data[key] = value.value
        return data
    
    def dict_for_sqlite(self) -> Dict[str, Any]:
        """转换为 SQLite 格式（meta 转为 JSON 字符串）"""
        data = self.dict_for_jsonl()
        if data.get("meta") is not None:
            import json
            data["meta"] = json.dumps(data["meta"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return data


def validate_signal_v2(data: Dict[str, Any]) -> SignalV2:
    """验证并创建 SignalV2 实例"""
    return SignalV2(**data)


def upgrade_v1_to_v2(v1_data: Dict[str, Any], core_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """v1→v2 只读升级器
    
    将 v1 格式的信号升级为 v2 格式，补全缺失字段
    """
    v2_data = v1_data.copy()
    
    # 补全 schema_version
    if "schema_version" not in v2_data:
        v2_data["schema_version"] = "signal/v2"
    
    # 补全 signal_id（如果缺失）
    if "signal_id" not in v2_data:
        run_id = v2_data.get("run_id", "unknown")
        symbol = v2_data.get("symbol", "UNKNOWN")
        ts_ms = v2_data.get("ts_ms", 0)
        seq = v2_data.get("seq", 0)
        v2_data["signal_id"] = f"{run_id}-{symbol}-{ts_ms}-{seq}"
    
    # 补全 side_hint（从 score 推断）
    if "side_hint" not in v2_data:
        score = v2_data.get("score", 0.0)
        if score > 0:
            v2_data["side_hint"] = "buy"
        elif score < 0:
            v2_data["side_hint"] = "sell"
        else:
            v2_data["side_hint"] = "flat"
    
    # 补全 regime（如果缺失，默认为 unknown）
    if "regime" not in v2_data:
        v2_data["regime"] = "unknown"
    
    # 补全 gating（如果缺失，从 confirm 推断）
    if "gating" not in v2_data:
        confirm = v2_data.get("confirm", False)
        v2_data["gating"] = 1 if confirm else 0
    
    # 补全 cooldown_ms/expiry_ms（如果缺失）
    if "cooldown_ms" not in v2_data:
        v2_data["cooldown_ms"] = 0
    if "expiry_ms" not in v2_data:
        if core_config:
            v2_data["expiry_ms"] = core_config.get("expiry_ms", 60000)
        else:
            v2_data["expiry_ms"] = 60000
    
    # 补全 decision_code/decision_reason（如果缺失）
    if "decision_code" not in v2_data:
        confirm = v2_data.get("confirm", False)
        gating = v2_data.get("gating", 0)
        if confirm and gating == 1:
            v2_data["decision_code"] = "OK"
            v2_data["decision_reason"] = "score>=entry"
        elif gating == 0:
            # P1 修复: v1→v2 升级器仅在 gating==0 时设置 gate_reason
            v2_data["decision_code"] = "FAIL_GATING"
            v2_data["decision_reason"] = v2_data.get("gate_reason", "gating failed")
        else:
            v2_data["decision_code"] = "LOW_SCORE"
            v2_data["decision_reason"] = "score<entry"
    
    # 补全 config_hash（如果缺失）
    if "config_hash" not in v2_data:
        v2_data["config_hash"] = "unknown"
    
    # 补全 meta（如果缺失）
    if "meta" not in v2_data:
        v2_data["meta"] = {}
    
    return v2_data

