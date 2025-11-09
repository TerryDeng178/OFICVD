# -*- coding: utf-8 -*-
"""P2.3: 配置契约Pydantic Schema

定义backtest.yaml的Pydantic Schema，含默认值/枚举校验，与环境变量映射一致
"""
from typing import Dict, Any, Optional, Literal
from pathlib import Path
import os

try:
    from pydantic import BaseModel, Field, field_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # 如果没有pydantic，提供简单的fallback
    BaseModel = object


class BacktestConfig(BaseModel):
    """回测配置Schema"""
    
    # 费用和滑点
    taker_fee_bps: float = Field(default=2.0, ge=0.0, description="Taker fee in basis points")
    slippage_bps: float = Field(default=1.0, ge=0.0, description="Slippage in basis points")
    notional_per_trade: float = Field(default=1000.0, gt=0.0, description="Fixed notional per trade")
    
    # 交易规则
    reverse_on_signal: bool = Field(default=False, description="Reverse position on opposite signal")
    take_profit_bps: Optional[float] = Field(default=None, ge=0.0, description="Optional take profit (basis points)")
    stop_loss_bps: Optional[float] = Field(default=None, ge=0.0, description="Optional stop loss (basis points)")
    min_hold_time_sec: Optional[float] = Field(default=None, ge=0.0, description="Optional minimum hold time (seconds)")
    
    # 闸门控制
    ignore_gating_in_backtest: bool = Field(default=True, description="Ignore gating in backtest (for pure strategy evaluation)")
    
    # PnL切日配置
    rollover_timezone: str = Field(default="UTC", description="PnL日切口径时区（UTC vs 本地）")
    rollover_hour: int = Field(default=0, ge=0, le=23, description="自定义rollover小时（0-23），0表示使用日期边界")
    
    # 滑点/费用模型
    slippage_model: Literal["static", "linear", "piecewise"] = Field(
        default="static",
        description="Slippage model: static, linear, piecewise"
    )
    fee_model: Literal["taker_static", "tiered", "maker_taker"] = Field(
        default="taker_static",
        description="Fee model: taker_static, tiered, maker_taker"
    )
    
    @field_validator("rollover_timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """验证时区格式"""
        if v == "UTC":
            return v
        try:
            import pytz
            pytz.timezone(v)  # 验证时区是否存在
            return v
        except Exception:
            raise ValueError(f"Invalid timezone: {v}")
    
    @classmethod
    def from_env_and_config(cls, config: Dict[str, Any]) -> "BacktestConfig":
        """从环境变量和配置字典创建配置
        
        优先级：环境变量 > config字典 > 默认值
        """
        # P0-4: 环境变量映射（补全常用注入参数）
        env_mapping = {
            "ROLLOVER_TZ": "rollover_timezone",
            "ROLLOVER_HOUR": "rollover_hour",
            "SLIPPAGE_MODEL": "slippage_model",
            "FEE_MODEL": "fee_model",
            "TAKER_FEE_BPS": "taker_fee_bps",
            "SLIPPAGE_BPS": "slippage_bps",
            "NOTIONAL_PER_TRADE": "notional_per_trade",
            "IGNORE_GATING": "ignore_gating_in_backtest",
        }
        
        # 合并配置（环境变量优先）
        merged_config = dict(config)
        
        for env_key, config_key in env_mapping.items():
            env_value = os.getenv(env_key)
            if env_value is not None:
                # 类型转换
                if config_key in ("rollover_hour",):
                    merged_config[config_key] = int(env_value)
                elif config_key in ("taker_fee_bps", "slippage_bps", "notional_per_trade"):
                    merged_config[config_key] = float(env_value)
                elif config_key == "ignore_gating_in_backtest":
                    # 布尔值转换（支持true/false/1/0）
                    merged_config[config_key] = env_value.lower() in ("true", "1", "yes")
                else:
                    merged_config[config_key] = env_value
        
        if PYDANTIC_AVAILABLE:
            return cls(**merged_config)
        else:
            # Fallback: 返回字典
            return merged_config  # type: ignore
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        if PYDANTIC_AVAILABLE and isinstance(self, BaseModel):
            return self.model_dump()
        else:
            return dict(self) if isinstance(self, dict) else {}


def load_backtest_config(config_path: Optional[Path] = None, config_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """加载并验证回测配置
    
    Args:
        config_path: 配置文件路径（可选）
        config_dict: 配置字典（可选）
    
    Returns:
        验证后的配置字典
    """
    import yaml
    
    # 加载配置
    if config_path and config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
        backtest_config = file_config.get("backtest", {})
    elif config_dict:
        backtest_config = config_dict.get("backtest", {}) if isinstance(config_dict, dict) else config_dict or {}
    else:
        backtest_config = {}
    
    # 使用Pydantic验证（如果可用）
    if PYDANTIC_AVAILABLE:
        try:
            validated_config = BacktestConfig.from_env_and_config(backtest_config)
            return validated_config.to_dict()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Pydantic validation failed, using raw config: {e}")
            return backtest_config
    else:
        # Fallback: 直接返回配置
        return backtest_config


if __name__ == "__main__":
    # 测试配置加载
    import sys
    import json  # P2-1: 补import json
    
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
        config = load_backtest_config(config_path)
        print(json.dumps(config, indent=2, ensure_ascii=False))
    else:
        # 测试默认配置
        config = BacktestConfig.from_env_and_config({})
        print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))

