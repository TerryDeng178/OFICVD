# -*- coding: utf-8 -*-
"""Risk Management Module for Strategy Server

风控模块：合并ofi_risk_server逻辑，提供pre_order_check接口
"""

from .precheck import pre_order_check, RiskDecision, RiskManager, initialize_risk_manager
from .schemas import OrderCtx, RiskDecision as RiskDecisionSchema
from .metrics import get_metrics, RiskMetrics, reset_metrics
from .schema_validator import validate_order_ctx, OrderCtxSchemaValidator, RiskReasonCode
from .strategy_mode_integration import (
    StrategyModeRiskInjector,
    initialize_strategy_mode_injector,
    apply_strategy_mode_params,
)

__all__ = [
    "pre_order_check",
    "RiskDecision",
    "RiskManager",
    "initialize_risk_manager",
    "OrderCtx",
    "RiskDecisionSchema",
    "get_metrics",
    "reset_metrics",
    "RiskMetrics",
    "validate_order_ctx",
    "OrderCtxSchemaValidator",
    "RiskReasonCode",
    "StrategyModeRiskInjector",
    "initialize_strategy_mode_injector",
    "apply_strategy_mode_params",
]

