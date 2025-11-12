# -*- coding: utf-8 -*-
"""执行前置决策模块

将上游状态（warmup/guard_reason/consistency）映射到执行决策
实现自适应节流器
"""
import logging
import time
from typing import Dict, Optional, Any
from collections import defaultdict, deque

from .base_executor import OrderCtx, ExecResult, ExecResultStatus
from .executor_metrics import get_executor_metrics

logger = logging.getLogger(__name__)


class ExecutorPrecheck:
    """执行前置决策器
    
    基于上游状态（warmup/guard_reason/consistency）进行执行决策
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化执行前置决策器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 一致性阈值配置
        self.consistency_min = self.config.get("consistency_min", 0.15)
        self.consistency_throttle_threshold = self.config.get("consistency_throttle_threshold", 0.20)
        
        # 统计信息
        self._deny_stats: Dict[str, int] = defaultdict(int)
        self._throttle_stats: Dict[str, int] = defaultdict(int)
        
        # Prometheus指标
        self._metrics = get_executor_metrics()
        
        logger.info(
            f"[ExecutorPrecheck] Initialized: consistency_min={self.consistency_min}, "
            f"consistency_throttle_threshold={self.consistency_throttle_threshold}"
        )
    
    def check(self, order_ctx: OrderCtx) -> ExecResult:
        """执行前置检查
        
        TASK-A4: 此检查是数据质量相关的（warmup、consistency、spread、lag），不是门控逻辑。
        门控逻辑（gating、threshold、regime）已在 CoreAlgorithm 中完成。
        如果信号 confirm=true，说明已经通过了所有门控检查，Executor 应该直接执行。
        
        Args:
            order_ctx: 订单上下文
            
        Returns:
            ExecResult: 执行结果（如果被拒绝，status=REJECTED）
        """
        import time as time_module
        check_start_time = time_module.perf_counter()
        sent_ts_ms = order_ctx.ts_ms or int(time_module.time() * 1000)
        
        # 1. 检查warmup
        if order_ctx.warmup:
            reason = "warmup"
            self._deny_stats[reason] += 1
            latency_seconds = time_module.perf_counter() - check_start_time
            self._metrics.record_submit(result="rejected", reason=reason, latency_seconds=latency_seconds)
            logger.debug(f"[ExecutorPrecheck] Order {order_ctx.client_order_id} denied: {reason}")
            return ExecResult(
                status=ExecResultStatus.REJECTED,
                client_order_id=order_ctx.client_order_id,
                reject_reason=reason,
                sent_ts_ms=sent_ts_ms,
            )
        
        # 2. 检查guard_reason
        if order_ctx.guard_reason:
            # 解析guard_reason（逗号分隔）
            reasons = [r.strip() for r in order_ctx.guard_reason.split(",")]
            # 如果包含关键原因，直接拒单
            critical_reasons = ["warmup", "spread_too_wide", "lag_exceeds_cap", "market_inactive"]
            for reason in reasons:
                if reason in critical_reasons:
                    self._deny_stats[reason] += 1
                    latency_seconds = time_module.perf_counter() - check_start_time
                    self._metrics.record_submit(result="rejected", reason=reason, latency_seconds=latency_seconds)
                    logger.debug(f"[ExecutorPrecheck] Order {order_ctx.client_order_id} denied: {reason}")
                    return ExecResult(
                        status=ExecResultStatus.REJECTED,
                        client_order_id=order_ctx.client_order_id,
                        reject_reason=reason,
                        sent_ts_ms=sent_ts_ms,
                    )
        
        # 3. 检查consistency
        if order_ctx.consistency is not None:
            if order_ctx.consistency < self.consistency_min:
                # 一致性低于最低阈值，直接拒单
                reason = "low_consistency"
                self._deny_stats[reason] += 1
                latency_seconds = time_module.perf_counter() - check_start_time
                self._metrics.record_submit(result="rejected", reason=reason, latency_seconds=latency_seconds)
                logger.debug(
                    f"[ExecutorPrecheck] Order {order_ctx.client_order_id} denied: {reason} "
                    f"(consistency={order_ctx.consistency:.3f} < {self.consistency_min})"
                )
                return ExecResult(
                    status=ExecResultStatus.REJECTED,
                    client_order_id=order_ctx.client_order_id,
                    reject_reason=reason,
                    sent_ts_ms=sent_ts_ms,
                )
            elif order_ctx.consistency < self.consistency_throttle_threshold:
                # 一致性低于节流阈值，降采样执行（这里简化处理，标记为节流）
                reason = "low_consistency_throttle"
                self._throttle_stats[reason] += 1
                self._metrics.record_throttle(reason=reason)
                latency_seconds = time_module.perf_counter() - check_start_time
                self._metrics.record_submit(result="rejected", reason=reason, latency_seconds=latency_seconds)
                logger.debug(
                    f"[ExecutorPrecheck] Order {order_ctx.client_order_id} throttled: {reason} "
                    f"(consistency={order_ctx.consistency:.3f} < {self.consistency_throttle_threshold})"
                )
                # 注意：这里返回REJECTED，实际实现中可以返回ACCEPTED但标记为节流
                # 为了简化，这里先返回REJECTED
                return ExecResult(
                    status=ExecResultStatus.REJECTED,
                    client_order_id=order_ctx.client_order_id,
                    reject_reason=reason,
                    sent_ts_ms=sent_ts_ms,
                )
        
        # 4. 检查weak_signal_throttle
        if order_ctx.weak_signal_throttle:
            reason = "weak_signal_throttle"
            self._throttle_stats[reason] += 1
            self._metrics.record_throttle(reason=reason)
            latency_seconds = time_module.perf_counter() - check_start_time
            self._metrics.record_submit(result="rejected", reason=reason, latency_seconds=latency_seconds)
            logger.debug(f"[ExecutorPrecheck] Order {order_ctx.client_order_id} throttled: {reason}")
            return ExecResult(
                status=ExecResultStatus.REJECTED,
                client_order_id=order_ctx.client_order_id,
                reject_reason=reason,
                sent_ts_ms=sent_ts_ms,
            )
        
        # 所有检查通过
        latency_seconds = time_module.perf_counter() - check_start_time
        self._metrics.record_submit(result="accepted", reason="none", latency_seconds=latency_seconds)
        return ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=order_ctx.client_order_id,
            sent_ts_ms=sent_ts_ms,
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "deny_stats": dict(self._deny_stats),
            "throttle_stats": dict(self._throttle_stats),
        }


class AdaptiveThrottler:
    """自适应节流器
    
    根据gate_reason_stats和市场活跃度（StrategyMode）联动限速
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化自适应节流器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 基础限速配置
        self.base_rate_limit = self.config.get("base_rate_limit", 10.0)  # 每秒最多10单
        self.min_rate_limit = self.config.get("min_rate_limit", 1.0)  # 最低限速
        self.max_rate_limit = self.config.get("max_rate_limit", 100.0)  # 最高限速
        
        # 时间窗口（秒）
        self.window_seconds = self.config.get("window_seconds", 60)
        
        # 请求历史（时间戳列表）
        self._request_history: deque = deque(maxlen=1000)
        
        # 当前限速
        self._current_rate_limit = self.base_rate_limit
        
        # Prometheus指标
        self._metrics = get_executor_metrics()
        self._metrics.set_rate_limit(self._current_rate_limit)
        
        logger.info(
            f"[AdaptiveThrottler] Initialized: base_rate_limit={self.base_rate_limit}, "
            f"window_seconds={self.window_seconds}"
        )
    
    def should_throttle(self, gate_reason_stats: Optional[Dict[str, int]] = None, 
                       market_activity: Optional[str] = None) -> bool:
        """判断是否应该节流
        
        Args:
            gate_reason_stats: 护栏原因统计（可选）
            market_activity: 市场活跃度（active/quiet，可选）
            
        Returns:
            是否应该节流
        """
        current_time = time.time()
        
        # 清理过期请求
        while self._request_history and self._request_history[0] < current_time - self.window_seconds:
            self._request_history.popleft()
        
        # 计算当前窗口内的请求数
        current_count = len(self._request_history)
        
        # 根据gate_reason_stats调整限速
        if gate_reason_stats:
            # 如果拒绝率过高，降低限速
            total_denies = sum(gate_reason_stats.values())
            if total_denies > 0:
                # 简化处理：拒绝率超过50%时降低限速
                deny_rate = total_denies / (current_count + total_denies) if current_count + total_denies > 0 else 0
                if deny_rate > 0.5:
                    self._current_rate_limit = max(self.min_rate_limit, self._current_rate_limit * 0.8)
                elif deny_rate < 0.1:
                    self._current_rate_limit = min(self.max_rate_limit, self._current_rate_limit * 1.1)
        
        # 根据市场活跃度调整限速
        if market_activity == "quiet":
            # 安静市场，降低限速
            self._current_rate_limit = max(self.min_rate_limit, self._current_rate_limit * 0.5)
        elif market_activity == "active":
            # 活跃市场，可以提高限速
            self._current_rate_limit = min(self.max_rate_limit, self._current_rate_limit * 1.2)
        
        # 更新Prometheus指标
        self._metrics.set_rate_limit(self._current_rate_limit)
        
        # 检查是否超过限速
        if current_count >= self._current_rate_limit * self.window_seconds:
            self._metrics.record_throttle(reason="rate_limit")
            return True
        
        # 记录请求
        self._request_history.append(current_time)
        return False
    
    def get_current_rate_limit(self) -> float:
        """获取当前限速
        
        Returns:
            当前限速（每秒请求数）
        """
        return self._current_rate_limit

