# -*- coding: utf-8 -*-
"""JSON Schema Validator for Risk Module

OrderCtx输入强校验：在Strategy接入层对OrderCtx输入做schema校验（失败即拒单并打点），
形成"硬闸"，从源头杜绝字段/单位漂移导致的判定偏差。
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from .schemas import OrderCtx, RiskDecision

logger = logging.getLogger(__name__)


class RiskReasonCode(str, Enum):
    """风控拒绝原因码枚举（限定为枚举，避免自由字符串导致高基数）
    
    注意：严禁新增高基数标签（如symbol），以免TSDB膨胀
    """
    # 护栏相关
    SPREAD_TOO_WIDE = "spread_too_wide"
    LAG_EXCEEDS_CAP = "lag_exceeds_cap"
    MARKET_INACTIVE = "market_inactive"
    
    # 仓位相关
    NOTIONAL_EXCEEDS_LIMIT = "notional_exceeds_limit"
    SYMBOL_QTY_EXCEEDS_LIMIT = "symbol_qty_exceeds_limit"
    
    # Schema校验相关
    INVALID_SCHEMA = "invalid_schema"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_FIELD_TYPE = "invalid_field_type"
    INVALID_ENUM_VALUE = "invalid_enum_value"


class OrderCtxSchemaValidator:
    """OrderCtx Schema校验器"""
    
    REQUIRED_FIELDS = {
        "symbol": str,
        "side": str,
        "order_type": str,
        "qty": (int, float),
    }
    
    OPTIONAL_FIELDS = {
        "price": (int, float, type(None)),
        "account_mode": str,
        "max_slippage_bps": (int, float),
        "ts_ms": int,
        "regime": str,
        "guards": dict,
        "context": dict,
    }
    
    VALID_SIDES = {"buy", "sell"}
    VALID_ORDER_TYPES = {"market", "limit"}
    VALID_ACCOUNT_MODES = {"isolated", "cross"}
    
    def validate(self, order_ctx: Any) -> Tuple[bool, List[str], Optional[OrderCtx]]:
        """校验OrderCtx输入
        
        Args:
            order_ctx: 订单上下文（可能是dict或OrderCtx对象）
            
        Returns:
            (is_valid, errors, validated_order_ctx)
            - is_valid: 是否通过校验
            - errors: 错误列表（reason_codes）
            - validated_order_ctx: 校验后的OrderCtx对象（如果通过）
        """
        errors = []
        
        # 1. 类型检查
        if isinstance(order_ctx, dict):
            # 从dict创建OrderCtx前，先检查必填字段
            missing_fields = []
            for field in ["symbol", "side", "order_type", "qty"]:
                if field not in order_ctx or order_ctx[field] is None:
                    missing_fields.append(field)
            
            if missing_fields:
                errors.append(RiskReasonCode.MISSING_REQUIRED_FIELD.value)
                errors.extend(missing_fields)
                logger.warning(f"[RISK] Schema validation failed: missing required fields: {missing_fields}")
                return False, errors, None
            
            # 从dict创建OrderCtx
            try:
                order_ctx = OrderCtx(**order_ctx)
            except Exception as e:
                errors.append(RiskReasonCode.INVALID_SCHEMA.value)
                logger.warning(f"[RISK] Schema validation failed: {e}")
                return False, errors, None
        elif not isinstance(order_ctx, OrderCtx):
            errors.append(RiskReasonCode.INVALID_SCHEMA.value)
            logger.warning(f"[RISK] Schema validation failed: expected OrderCtx or dict, got {type(order_ctx)}")
            return False, errors, None
        
        # 2. 必填字段检查
        if not order_ctx.symbol:
            errors.append(RiskReasonCode.MISSING_REQUIRED_FIELD.value)
            errors.append("symbol")
        
        if not order_ctx.side:
            errors.append(RiskReasonCode.MISSING_REQUIRED_FIELD.value)
            errors.append("side")
        
        if not order_ctx.order_type:
            errors.append(RiskReasonCode.MISSING_REQUIRED_FIELD.value)
            errors.append("order_type")
        
        if order_ctx.qty is None or order_ctx.qty <= 0:
            errors.append(RiskReasonCode.INVALID_FIELD_TYPE.value)
            errors.append("qty")
        
        # 3. 枚举值检查
        if order_ctx.side not in self.VALID_SIDES:
            errors.append(RiskReasonCode.INVALID_ENUM_VALUE.value)
            errors.append(f"side={order_ctx.side}")
        
        if order_ctx.order_type not in self.VALID_ORDER_TYPES:
            errors.append(RiskReasonCode.INVALID_ENUM_VALUE.value)
            errors.append(f"order_type={order_ctx.order_type}")
        
        if order_ctx.account_mode and order_ctx.account_mode not in self.VALID_ACCOUNT_MODES:
            errors.append(RiskReasonCode.INVALID_ENUM_VALUE.value)
            errors.append(f"account_mode={order_ctx.account_mode}")
        
        # 4. 限价单价格检查
        if order_ctx.order_type == "limit" and order_ctx.price is None:
            errors.append(RiskReasonCode.MISSING_REQUIRED_FIELD.value)
            errors.append("price (required for limit orders)")
        
        if order_ctx.price is not None and order_ctx.price <= 0:
            errors.append(RiskReasonCode.INVALID_FIELD_TYPE.value)
            errors.append("price")
        
        # 5. Guards字段检查（如果存在）
        if order_ctx.guards:
            if not isinstance(order_ctx.guards, dict):
                errors.append(RiskReasonCode.INVALID_FIELD_TYPE.value)
                errors.append("guards")
            else:
                # 检查guards中的数值字段
                for key in ["spread_bps", "event_lag_sec", "activity_tpm"]:
                    if key in order_ctx.guards:
                        value = order_ctx.guards[key]
                        if not isinstance(value, (int, float)) or value < 0:
                            errors.append(RiskReasonCode.INVALID_FIELD_TYPE.value)
                            errors.append(f"guards.{key}")
        
        # 6. 返回结果
        if errors:
            # 记录校验失败
            logger.warning(
                f"[RISK] Schema validation failed: symbol={order_ctx.symbol}, "
                f"errors={errors}"
            )
            return False, [RiskReasonCode.INVALID_SCHEMA.value] + errors, None
        
        return True, [], order_ctx


# 全局校验器实例
_validator: Optional[OrderCtxSchemaValidator] = None


def get_validator() -> OrderCtxSchemaValidator:
    """获取全局校验器实例
    
    Returns:
        校验器实例
    """
    global _validator
    if _validator is None:
        _validator = OrderCtxSchemaValidator()
    return _validator


def validate_order_ctx(order_ctx: Any) -> Tuple[bool, List[str], Optional[OrderCtx]]:
    """校验OrderCtx输入（全局函数接口）
    
    Args:
        order_ctx: 订单上下文（可能是dict或OrderCtx对象）
        
    Returns:
        (is_valid, errors, validated_order_ctx)
    """
    validator = get_validator()
    return validator.validate(order_ctx)

