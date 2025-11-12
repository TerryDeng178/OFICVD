# -*- coding: utf-8 -*-
"""执行层日志采样模块

复用A1的"通过1% / 失败100%"采样策略到执行层
关键字段：guard_reason, warmup, scenario, rounding_applied, reject_reason
"""
import logging
import random
from typing import Optional, Dict, Any

from .base_executor import OrderCtx, ExecResult, ExecResultStatus

logger = logging.getLogger(__name__)


class ExecutorLogger:
    """执行层日志记录器
    
    实现"通过1% / 失败100%"采样策略
    """
    
    def __init__(self, sample_rate: float = 0.01, enabled: bool = True):
        """初始化执行层日志记录器
        
        Args:
            sample_rate: 通过订单的采样率（0.01表示1%）
            enabled: 是否启用日志记录
        """
        self.sample_rate = sample_rate
        self.enabled = enabled
        
        # 统计信息
        self._logged_count = 0
        self._sampled_count = 0
        self._failed_count = 0
        
        logger.info(
            f"[ExecutorLogger] Initialized: sample_rate={sample_rate}, "
            f"enabled={enabled}"
        )
    
    def should_log(self, exec_result: ExecResult, order_ctx: Optional[OrderCtx] = None) -> bool:
        """判断是否应该记录日志
        
        Args:
            exec_result: 执行结果
            order_ctx: 订单上下文（可选）
            
        Returns:
            是否应该记录日志
        """
        if not self.enabled:
            return False
        
        # 失败订单100%记录
        if exec_result.status == ExecResultStatus.REJECTED:
            return True
        
        # 通过订单按采样率记录
        if exec_result.status == ExecResultStatus.ACCEPTED:
            return random.random() < self.sample_rate
        
        return False
    
    def log_order_submitted(
        self,
        order_ctx: OrderCtx,
        exec_result: ExecResult,
    ) -> None:
        """记录订单提交日志
        
        Args:
            order_ctx: 订单上下文
            exec_result: 执行结果
        """
        if not self.should_log(exec_result, order_ctx):
            return
        
        self._logged_count += 1
        
        if exec_result.status == ExecResultStatus.REJECTED:
            self._failed_count += 1
            # 失败订单：100%记录，包含详细信息
            logger.warning(
                f"[EXEC] Order rejected: client_order_id={order_ctx.client_order_id}, "
                f"symbol={order_ctx.symbol}, side={order_ctx.side.value}, "
                f"reject_reason={exec_result.reject_reason}, "
                f"warmup={order_ctx.warmup}, guard_reason={order_ctx.guard_reason}, "
                f"consistency={order_ctx.consistency}, scenario={order_ctx.scenario}, "
                f"latency_ms={exec_result.latency_ms}"
            )
        else:
            self._sampled_count += 1
            # 通过订单：1%采样记录
            logger.debug(
                f"[EXEC] Order accepted: client_order_id={order_ctx.client_order_id}, "
                f"symbol={order_ctx.symbol}, side={order_ctx.side.value}, "
                f"exchange_order_id={exec_result.exchange_order_id}, "
                f"warmup={order_ctx.warmup}, guard_reason={order_ctx.guard_reason}, "
                f"scenario={order_ctx.scenario}, "
                f"rounding_applied={exec_result.rounding_applied}, "
                f"latency_ms={exec_result.latency_ms}"
            )
    
    def log_order_filled(
        self,
        order_ctx: OrderCtx,
        exec_result: ExecResult,
        fill_price: float,
        fill_qty: float,
    ) -> None:
        """记录订单成交日志
        
        Args:
            order_ctx: 订单上下文
            exec_result: 执行结果
            fill_price: 成交价格
            fill_qty: 成交数量
        """
        if not self.enabled:
            return
        
        # 成交订单：100%记录（重要事件）
        logger.info(
            f"[EXEC] Order filled: client_order_id={order_ctx.client_order_id}, "
            f"symbol={order_ctx.symbol}, side={order_ctx.side.value}, "
            f"fill_price={fill_price}, fill_qty={fill_qty}, "
            f"slippage_bps={exec_result.slippage_bps}, "
            f"rounding_applied={exec_result.rounding_applied}"
        )
    
    def log_order_canceled(
        self,
        order_ctx: OrderCtx,
        cancel_reason: Optional[str] = None,
    ) -> None:
        """记录订单撤销日志
        
        Args:
            order_ctx: 订单上下文
            cancel_reason: 撤销原因（可选）
        """
        if not self.enabled:
            return
        
        # 撤销订单：100%记录（重要事件）
        logger.info(
            f"[EXEC] Order canceled: client_order_id={order_ctx.client_order_id}, "
            f"symbol={order_ctx.symbol}, reason={cancel_reason}"
        )
    
    def log_schema_validation_failed(
        self,
        symbol: str,
        schema_errors: list,
    ) -> None:
        """记录Schema校验失败日志
        
        Args:
            symbol: 交易对
            schema_errors: Schema错误列表
        """
        if not self.enabled:
            return
        
        # Schema校验失败：100%记录
        logger.error(
            f"[EXEC] Schema validation failed: symbol={symbol}, "
            f"errors={schema_errors}"
        )
    
    def log_shadow_alert(
        self,
        parity_ratio: float,
        threshold: float = 0.99,
    ) -> None:
        """记录影子执行告警日志
        
        Args:
            parity_ratio: 一致性比率
            threshold: 阈值
        """
        if not self.enabled:
            return
        
        # 影子告警：100%记录
        logger.warning(
            f"[EXEC] Shadow parity alert: parity_ratio={parity_ratio:.4f}, "
            f"threshold={threshold}"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "logged_count": self._logged_count,
            "sampled_count": self._sampled_count,
            "failed_count": self._failed_count,
            "sample_rate": self.sample_rate,
        }


def get_executor_logger(sample_rate: float = 0.01, enabled: bool = True) -> ExecutorLogger:
    """获取执行层日志记录器（单例模式）
    
    Args:
        sample_rate: 采样率
        enabled: 是否启用
        
    Returns:
        ExecutorLogger实例
    """
    # 使用模块级变量实现单例
    if not hasattr(get_executor_logger, '_instance'):
        get_executor_logger._instance = ExecutorLogger(sample_rate=sample_rate, enabled=enabled)
    return get_executor_logger._instance

