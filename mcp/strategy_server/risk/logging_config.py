# -*- coding: utf-8 -*-
"""Logging Configuration Module

日志规范与抽样：通过单1%抽样，失败单100%记录
"""

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


class RiskLogger:
    """风险模块日志记录器（支持抽样）"""
    
    def __init__(self, sample_rate: float = 0.01):
        """初始化日志记录器
        
        Args:
            sample_rate: 通过单的抽样率（默认1%，即0.01）
        """
        self.sample_rate = sample_rate
        self.logger = logging.getLogger("mcp.strategy_server.risk")
    
    def log_order_passed(self, symbol: str, side: str, latency_ms: float, reason_codes: list = None):
        """记录通过单（1%抽样）
        
        Args:
            symbol: 交易对符号
            side: 订单方向
            latency_ms: 耗时（毫秒）
            reason_codes: 原因码列表（通常为空）
        """
        # 1%抽样
        if random.random() < self.sample_rate:
            self.logger.debug(
                f"[RISK] Order passed: symbol={symbol}, "
                f"side={side}, latency={latency_ms:.2f}ms"
            )
    
    def log_order_denied(self, symbol: str, side: str, reason_codes: list, latency_ms: float):
        """记录失败单（100%记录）
        
        Args:
            symbol: 交易对符号
            side: 订单方向
            reason_codes: 拒绝原因码列表
            latency_ms: 耗时（毫秒）
        """
        # 100%记录失败单
        self.logger.warning(
            f"[RISK] Order denied: symbol={symbol}, "
            f"side={side}, reasons={reason_codes}, latency={latency_ms:.2f}ms"
        )
    
    def log_schema_validation_failed(self, symbol: str, errors: list):
        """记录Schema校验失败（100%记录）
        
        Args:
            symbol: 交易对符号
            errors: 错误列表
        """
        # 100%记录校验失败
        self.logger.error(
            f"[RISK] Schema validation failed: symbol={symbol}, errors={errors}"
        )
    
    def log_shadow_parity_alert(self, parity_ratio: float, threshold: float, level: str):
        """记录Shadow一致性告警（100%记录）
        
        Args:
            parity_ratio: 当前一致率
            threshold: 告警阈值
            level: 告警级别（warn/critical）
        """
        # 100%记录告警
        if level == "critical":
            self.logger.error(
                f"[RISK] Shadow parity alert (CRITICAL): ratio={parity_ratio:.4f}, "
                f"threshold={threshold:.4f}"
            )
        else:
            self.logger.warning(
                f"[RISK] Shadow parity alert (WARN): ratio={parity_ratio:.4f}, "
                f"threshold={threshold:.4f}"
            )


# 全局日志记录器实例
_risk_logger: Optional[RiskLogger] = None


def get_risk_logger(sample_rate: float = 0.01) -> RiskLogger:
    """获取全局风险日志记录器
    
    Args:
        sample_rate: 通过单的抽样率（默认1%）
        
    Returns:
        日志记录器实例
    """
    global _risk_logger
    if _risk_logger is None:
        _risk_logger = RiskLogger(sample_rate)
    return _risk_logger

