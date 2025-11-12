# -*- coding: utf-8 -*-
"""Schema Validator Unit Tests

测试 mcp/strategy_server/risk/schema_validator.py 模块
"""

import pytest

from mcp.strategy_server.risk.schema_validator import (
    validate_order_ctx,
    OrderCtxSchemaValidator,
    RiskReasonCode,
)
from mcp.strategy_server.risk.schemas import OrderCtx


class TestOrderCtxSchemaValidator:
    """测试OrderCtx Schema校验器"""
    
    def test_validate_valid_order_ctx_dict(self):
        """测试校验有效的dict格式OrderCtx"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "qty": 0.1,
            "price": 50000.0,
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is True
        assert len(errors) == 0
        assert validated_order_ctx is not None
        assert validated_order_ctx.symbol == "BTCUSDT"
    
    def test_validate_valid_order_ctx_object(self):
        """测试校验有效的OrderCtx对象"""
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
        )
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx)
        
        assert is_valid is True
        assert len(errors) == 0
        assert validated_order_ctx is not None
    
    def test_validate_missing_required_field(self):
        """测试校验缺失必填字段"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            # 缺少 side
            "order_type": "market",
            "qty": 0.1,
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.MISSING_REQUIRED_FIELD.value in errors
        assert validated_order_ctx is None
    
    def test_validate_invalid_side(self):
        """测试校验无效的side枚举值"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "invalid_side",  # 无效值
            "order_type": "market",
            "qty": 0.1,
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.INVALID_ENUM_VALUE.value in errors
        assert validated_order_ctx is None
    
    def test_validate_invalid_order_type(self):
        """测试校验无效的order_type枚举值"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "invalid_type",  # 无效值
            "qty": 0.1,
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.INVALID_ENUM_VALUE.value in errors
    
    def test_validate_limit_order_without_price(self):
        """测试校验限价单缺少price"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",  # 限价单
            "qty": 0.1,
            # 缺少 price
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.MISSING_REQUIRED_FIELD.value in errors
    
    def test_validate_invalid_qty(self):
        """测试校验无效的qty（<=0）"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "qty": 0,  # 无效值
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.INVALID_FIELD_TYPE.value in errors
    
    def test_validate_invalid_price(self):
        """测试校验无效的price（<=0）"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "qty": 0.1,
            "price": -100.0,  # 无效值
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.INVALID_FIELD_TYPE.value in errors
    
    def test_validate_invalid_guards(self):
        """测试校验无效的guards字段"""
        order_ctx_dict = {
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "qty": 0.1,
            "guards": "invalid",  # 应该是dict
        }
        
        is_valid, errors, validated_order_ctx = validate_order_ctx(order_ctx_dict)
        
        assert is_valid is False
        assert RiskReasonCode.INVALID_FIELD_TYPE.value in errors
    
    def test_validate_invalid_type(self):
        """测试校验无效的类型（不是dict或OrderCtx）"""
        is_valid, errors, validated_order_ctx = validate_order_ctx("invalid")
        
        assert is_valid is False
        assert RiskReasonCode.INVALID_SCHEMA.value in errors
        assert validated_order_ctx is None


class TestRiskReasonCode:
    """测试RiskReasonCode枚举"""
    
    def test_reason_code_enum_values(self):
        """测试reason_code枚举值"""
        assert RiskReasonCode.SPREAD_TOO_WIDE.value == "spread_too_wide"
        assert RiskReasonCode.LAG_EXCEEDS_CAP.value == "lag_exceeds_cap"
        assert RiskReasonCode.MARKET_INACTIVE.value == "market_inactive"
        assert RiskReasonCode.NOTIONAL_EXCEEDS_LIMIT.value == "notional_exceeds_limit"
        assert RiskReasonCode.SYMBOL_QTY_EXCEEDS_LIMIT.value == "symbol_qty_exceeds_limit"
        assert RiskReasonCode.INVALID_SCHEMA.value == "invalid_schema"

