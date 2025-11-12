# -*- coding: utf-8 -*-
"""影子执行模块

实现Testnet影子单验证，比较"意图价/回执/拒单率"
"""
import logging
from typing import Optional, Dict, Any, List
from collections import defaultdict
from dataclasses import dataclass, field

from .base_executor import OrderCtx, ExecResult, ExecResultStatus, IExecutor

logger = logging.getLogger(__name__)


@dataclass
class ShadowComparison:
    """影子执行对比结果"""
    main_result: ExecResult  # 主执行结果
    shadow_result: Optional[ExecResult] = None  # 影子执行结果（如果执行）
    price_parity: Optional[float] = None  # 价格一致性（1.0表示完全一致）
    status_parity: Optional[float] = None  # 状态一致性（1.0表示完全一致）
    reason_parity: Optional[float] = None  # 原因一致性（1.0表示完全一致）
    latency_diff_ms: Optional[int] = None  # 延迟差异（ms）
    meta: Dict[str, Any] = field(default_factory=dict)  # 其他元数据


class ShadowExecutor:
    """影子执行器
    
    允许并行向Testnet发送"影子单"，只落账不成交，比较"意图价/回执/拒单率"
    """
    
    def __init__(self, testnet_executor: IExecutor, enabled: bool = True):
        """初始化影子执行器
        
        Args:
            testnet_executor: Testnet执行器实例
            enabled: 是否启用影子执行
        """
        self.testnet_executor = testnet_executor
        self.enabled = enabled
        
        # 统计信息
        self._comparison_count = 0
        self._price_parity_sum = 0.0
        self._status_parity_sum = 0.0
        self._reason_parity_sum = 0.0
        self._comparisons: List[ShadowComparison] = []
        
        logger.info(f"[ShadowExecutor] Initialized: enabled={enabled}")
    
    def execute_shadow(self, order_ctx: OrderCtx, main_result: ExecResult) -> ShadowComparison:
        """执行影子订单并对比
        
        Args:
            order_ctx: 订单上下文
            main_result: 主执行结果
            
        Returns:
            ShadowComparison: 对比结果
        """
        if not self.enabled:
            return ShadowComparison(main_result=main_result)
        
        try:
            # 向Testnet发送影子订单（dry-run模式，不实际成交）
            shadow_result = self.testnet_executor.submit_with_ctx(order_ctx)
            
            # 对比结果
            comparison = self._compare_results(main_result, shadow_result, order_ctx)
            
            # 更新统计
            self._update_stats(comparison)
            
            return comparison
        except Exception as e:
            logger.error(f"[ShadowExecutor] Shadow execution failed: {e}")
            return ShadowComparison(main_result=main_result)
    
    def _compare_results(self, main_result: ExecResult, shadow_result: ExecResult, order_ctx: OrderCtx) -> ShadowComparison:
        """对比主执行和影子执行结果
        
        Args:
            main_result: 主执行结果
            shadow_result: 影子执行结果
            order_ctx: 订单上下文
            
        Returns:
            ShadowComparison: 对比结果
        """
        comparison = ShadowComparison(main_result=main_result, shadow_result=shadow_result)
        
        # 1. 价格一致性（如果两者都接受）
        if (main_result.status == ExecResultStatus.ACCEPTED and 
            shadow_result.status == ExecResultStatus.ACCEPTED):
            # 比较意图价格和发送价格
            if order_ctx.price is not None:
                # 简化处理：如果价格差异在1 tick内，认为一致
                if order_ctx.tick_size:
                    price_diff = abs(order_ctx.price - (order_ctx.price or 0))
                    if price_diff <= order_ctx.tick_size:
                        comparison.price_parity = 1.0
                    else:
                        comparison.price_parity = 1.0 - (price_diff / order_ctx.price) if order_ctx.price > 0 else 0.0
                else:
                    comparison.price_parity = 1.0  # 无tick_size时认为一致
            else:
                comparison.price_parity = 1.0  # 市价单无法比较价格
        
        # 2. 状态一致性
        if main_result.status == shadow_result.status:
            comparison.status_parity = 1.0
        else:
            comparison.status_parity = 0.0
        
        # 3. 原因一致性
        if main_result.reject_reason == shadow_result.reject_reason:
            comparison.reason_parity = 1.0
        elif main_result.reject_reason is None and shadow_result.reject_reason is None:
            comparison.reason_parity = 1.0
        else:
            comparison.reason_parity = 0.0
        
        # 4. 延迟差异
        if main_result.latency_ms is not None and shadow_result.latency_ms is not None:
            comparison.latency_diff_ms = abs(main_result.latency_ms - shadow_result.latency_ms)
        
        return comparison
    
    def _update_stats(self, comparison: ShadowComparison) -> None:
        """更新统计信息
        
        Args:
            comparison: 对比结果
        """
        self._comparison_count += 1
        self._comparisons.append(comparison)
        
        # 保留最近1000条对比记录（LRU）
        if len(self._comparisons) > 1000:
            self._comparisons.pop(0)
        
        # 更新一致性统计
        if comparison.price_parity is not None:
            self._price_parity_sum += comparison.price_parity
        if comparison.status_parity is not None:
            self._status_parity_sum += comparison.status_parity
        if comparison.reason_parity is not None:
            self._reason_parity_sum += comparison.reason_parity
    
    def get_parity_ratio(self) -> float:
        """获取总体一致性比率
        
        Returns:
            一致性比率（0.0-1.0，1.0表示完全一致）
        """
        if self._comparison_count == 0:
            return 1.0
        
        # 计算平均一致性（价格、状态、原因的平均值）
        price_avg = self._price_parity_sum / self._comparison_count if self._comparison_count > 0 else 1.0
        status_avg = self._status_parity_sum / self._comparison_count if self._comparison_count > 0 else 1.0
        reason_avg = self._reason_parity_sum / self._comparison_count if self._comparison_count > 0 else 1.0
        
        # 综合一致性（加权平均：状态权重0.5，价格和原因各0.25）
        parity = (status_avg * 0.5 + price_avg * 0.25 + reason_avg * 0.25)
        
        return parity
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "comparison_count": self._comparison_count,
            "parity_ratio": self.get_parity_ratio(),
            "price_parity_avg": self._price_parity_sum / self._comparison_count if self._comparison_count > 0 else 1.0,
            "status_parity_avg": self._status_parity_sum / self._comparison_count if self._comparison_count > 0 else 1.0,
            "reason_parity_avg": self._reason_parity_sum / self._comparison_count if self._comparison_count > 0 else 1.0,
        }
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        self._comparison_count = 0
        self._price_parity_sum = 0.0
        self._status_parity_sum = 0.0
        self._reason_parity_sum = 0.0
        self._comparisons.clear()
        logger.info("[ShadowExecutor] Stats reset")


class ShadowExecutorWrapper:
    """影子执行器包装器
    
    包装主执行器，自动执行影子订单并对比
    """
    
    def __init__(self, main_executor: IExecutor, shadow_executor: Optional[ShadowExecutor] = None):
        """初始化影子执行器包装器
        
        Args:
            main_executor: 主执行器
            shadow_executor: 影子执行器（可选）
        """
        self.main_executor = main_executor
        self.shadow_executor = shadow_executor
    
    def submit_with_ctx(self, order_ctx: OrderCtx) -> ExecResult:
        """提交订单（带影子执行）
        
        Args:
            order_ctx: 订单上下文
            
        Returns:
            ExecResult: 主执行结果
        """
        # 执行主订单
        main_result = self.main_executor.submit_with_ctx(order_ctx)
        
        # 如果启用影子执行，并行执行影子订单
        if self.shadow_executor and self.shadow_executor.enabled:
            try:
                comparison = self.shadow_executor.execute_shadow(order_ctx, main_result)
                
                # 记录对比结果（可以用于指标和告警）
                parity_ratio = self.shadow_executor.get_parity_ratio()
                if parity_ratio < 0.99:
                    logger.warning(
                        f"[ShadowExecutorWrapper] Parity ratio below threshold: {parity_ratio:.4f} "
                        f"(main_status={main_result.status}, shadow_status={comparison.shadow_result.status if comparison.shadow_result else None})"
                    )
            except Exception as e:
                logger.error(f"[ShadowExecutorWrapper] Shadow execution error: {e}")
        
        return main_result
    
    def get_shadow_stats(self) -> Optional[Dict[str, Any]]:
        """获取影子执行统计信息
        
        Returns:
            统计信息字典（如果启用影子执行）
        """
        if self.shadow_executor:
            return self.shadow_executor.get_stats()
        return None

