# -*- coding: utf-8 -*-
"""Pre-Order Check Module

下单前置检查：统一入口pre_order_check(order_ctx) -> RiskDecision
"""

import time
import logging
from typing import Dict, Optional

from .schemas import OrderCtx, RiskDecision
from .guards import GuardChecker
from .position import PositionManager
from .stops import StopRulesManager
from .metrics import get_metrics
from .schema_validator import validate_order_ctx

logger = logging.getLogger(__name__)


class RiskManager:
    """风险管理器（合并ofi_risk_server逻辑）"""
    
    def __init__(self, config: Dict):
        """初始化风险管理器
        
        Args:
            config: 配置字典，包含risk配置段
        """
        risk_config = config.get("risk", {})
        self.enabled = risk_config.get("enabled", False)
        self.guard_checker = GuardChecker(risk_config)
        self.position_manager = PositionManager(risk_config)
        self.stop_rules_manager = StopRulesManager(risk_config)
        
        # Shadow模式配置
        shadow_config = risk_config.get("shadow_mode", {})
        self.shadow_enabled = shadow_config.get("compare_with_legacy", False)
        self.shadow_diff_alert = shadow_config.get("diff_alert", ">=1%")
    
    def pre_order_check(self, order_ctx: OrderCtx) -> RiskDecision:
        """下单前置检查
        
        Args:
            order_ctx: 订单上下文
            
        Returns:
            风控决策
        """
        start_time = time.perf_counter()
        
        # Schema强校验（硬闸）：在进入pre_order_check前校验输入
        is_valid, schema_errors, validated_order_ctx = validate_order_ctx(order_ctx)
        if not is_valid:
            latency_seconds = time.perf_counter() - start_time
            metrics = get_metrics()
            metrics.record_precheck(False, schema_errors)
            metrics.record_latency_seconds(latency_seconds)
            # 使用抽样日志记录器（Schema校验失败100%记录）
            risk_logger = get_risk_logger()
            risk_logger.log_schema_validation_failed(
                getattr(order_ctx, 'symbol', 'unknown'), schema_errors
            )
            return RiskDecision(
                passed=False,
                reason_codes=schema_errors,
                metrics={"check_latency_ms": latency_seconds * 1000, "check_latency_seconds": latency_seconds},
            )
        
        # 使用校验后的order_ctx
        order_ctx = validated_order_ctx
        
        # 如果未启用内联风控，直接通过（回退到legacy）
        if not self.enabled:
            latency_seconds = time.perf_counter() - start_time
            return RiskDecision(
                passed=True,
                reason_codes=[],
                metrics={"check_latency_ms": latency_seconds * 1000, "check_latency_seconds": latency_seconds},
            )
        
        reasons = []
        adjustments = {}
        
        # 1. 护栏检查
        guard_reasons = self.guard_checker.check_all(order_ctx.guards)
        reasons.extend(guard_reasons)
        
        # 2. 仓位检查（防御式写法：price为0.0时也应检查）
        # 包含：交易所Filter约束、名义额限制、单币种限制
        if order_ctx.price is not None:
            position_reasons, position_adjustments = self.position_manager.check_all(
                order_ctx.symbol, order_ctx.qty, order_ctx.price
            )
            reasons.extend(position_reasons)
            adjustments.update(position_adjustments)
            
            # 如果违反名义额上限，添加reason_code并给出建议可下数量
            if "notional_exceeds_limit" in position_reasons and "max_qty" in position_adjustments:
                # adjustments中已包含max_qty，无需额外处理
                pass
        
        # 3. 限价上限计算（如果有限价单）
        if order_ctx.order_type == "limit" and order_ctx.price is not None:
            price_cap = self.stop_rules_manager.calculate_price_cap(
                order_ctx.side, order_ctx.price, order_ctx.max_slippage_bps,
                align_to_tick=True  # 对齐到tick_size，避免Broker端再四舍五入
            )
            if price_cap:
                adjustments["price_cap"] = price_cap
                # 如果存在aligned_price，也添加到adjustments
                if "aligned_price" in adjustments:
                    # 取两者中的较小值（买单）或较大值（卖单）
                    if order_ctx.side == "buy":
                        adjustments["price_cap"] = min(price_cap, adjustments["aligned_price"])
                    else:
                        adjustments["price_cap"] = max(price_cap, adjustments["aligned_price"])
        
        # 4. 决策
        passed = len(reasons) == 0
        
        latency_seconds = time.perf_counter() - start_time
        check_latency_ms = latency_seconds * 1000
        
        decision = RiskDecision(
            passed=passed,
            reason_codes=reasons,
            adjustments=adjustments,
            metrics={"check_latency_ms": check_latency_ms, "check_latency_seconds": latency_seconds},
        )
        
        # 记录指标（同时记录seconds和ms，ms为兼容输出）
        metrics = get_metrics()
        metrics.record_precheck(passed, reasons)
        metrics.record_latency(check_latency_ms)  # 保持ms兼容
        metrics.record_latency_seconds(latency_seconds)  # 新增seconds版本
        
        # 记录日志（使用抽样日志记录器）
        from .logging_config import get_risk_logger
        risk_logger = get_risk_logger()
        
        if not passed:
            # 失败单100%记录
            risk_logger.log_order_denied(
                order_ctx.symbol, order_ctx.side, reasons, check_latency_ms
            )
        else:
            # 通过单1%抽样
            risk_logger.log_order_passed(
                order_ctx.symbol, order_ctx.side, check_latency_ms, reasons
            )
        
        return decision


# 全局实例（延迟初始化）
_risk_manager: Optional[RiskManager] = None


def initialize_risk_manager(config: Dict):
    """初始化全局风险管理器
    
    Args:
        config: 配置字典
    """
    global _risk_manager
    _risk_manager = RiskManager(config)


def pre_order_check(order_ctx: OrderCtx) -> RiskDecision:
    """下单前置检查（全局函数接口）
    
    Args:
        order_ctx: 订单上下文
        
    Returns:
        风控决策
    """
    if _risk_manager is None:
        raise RuntimeError("RiskManager not initialized. Call initialize_risk_manager() first.")
    
    return _risk_manager.pre_order_check(order_ctx)

