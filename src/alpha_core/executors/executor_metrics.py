# -*- coding: utf-8 -*-
"""执行层Prometheus指标

实现executor_submit_total、executor_latency_seconds、executor_throttle_total等指标
"""
import logging
import time
from typing import Dict, Any, Optional
from collections import defaultdict

try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # 降级到简化实现
    Counter = None
    Histogram = None
    Gauge = None

logger = logging.getLogger(__name__)


class ExecutorMetrics:
    """执行层Prometheus指标收集器
    
    指标定义：
    - executor_submit_total{result,reason}: 订单提交总数（Counter）
    - executor_latency_seconds{result}: 执行延迟（Histogram，秒）
    - executor_throttle_total{reason}: 节流总数（Counter）
    """
    
    def __init__(self):
        """初始化指标收集器（P0: 幂等注册，避免重复注册错误）"""
        if PROMETHEUS_AVAILABLE:
            # P0: 检查并清理已存在的同名指标（幂等注册）
            import prometheus_client
            namespace_suffix = ""
            # 测试环境：添加随机后缀避免冲突
            import os
            if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("TEST_ENV"):
                import random
                namespace_suffix = f"_{random.randint(1000, 9999)}"
            
            # 清理已存在的同名指标
            collectors_to_remove = []
            for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
                try:
                    collector_name = None
                    if hasattr(collector, "_name"):
                        collector_name = collector._name
                    elif hasattr(collector, "name"):
                        collector_name = collector.name
                    
                    if collector_name and collector_name.startswith("executor_"):
                        collectors_to_remove.append(collector)
                except Exception:
                    pass
            
            for collector in collectors_to_remove:
                try:
                    prometheus_client.REGISTRY.unregister(collector)
                except Exception:
                    pass
            
            # 使用prometheus_client（幂等注册）
            self._submit_total = Counter(
                'executor_submit_total',
                'Total number of order submissions',
                ['result', 'reason']  # result: accepted/rejected, reason: warmup/low_consistency/etc
            )
            
            self._latency_seconds = Histogram(
                'executor_latency_seconds',
                'Order submission latency in seconds',
                ['result'],  # result: accepted/rejected
                buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
            )
            
            self._throttle_total = Counter(
                'executor_throttle_total',
                'Total number of throttled orders',
                ['reason']  # reason: rate_limit/weak_signal/etc
            )
            
            self._current_rate_limit = Gauge(
                'executor_current_rate_limit',
                'Current rate limit (orders per second)'
            )
            
            logger.info("[ExecutorMetrics] Initialized with prometheus_client (idempotent registration)")
        else:
            # 降级到简化实现（用于测试或开发环境）
            self._submit_total = None
            self._latency_seconds = None
            self._throttle_total = None
            self._current_rate_limit = None
            self._fallback_metrics = {
                'submit_total': defaultdict(lambda: defaultdict(int)),
                'latency_seconds': defaultdict(list),
                'throttle_total': defaultdict(int),
                'current_rate_limit': 0.0,
            }
            logger.warning("[ExecutorMetrics] prometheus_client not available, using fallback implementation")
    
    def record_submit(self, result: str, reason: Optional[str] = None, latency_seconds: Optional[float] = None):
        """记录订单提交
        
        Args:
            result: 结果（accepted/rejected）
            reason: 原因（warmup/low_consistency/exchange_rejected等，可选）
            latency_seconds: 延迟（秒，可选）
        """
        reason = reason or "none"
        
        if PROMETHEUS_AVAILABLE and self._submit_total:
            self._submit_total.labels(result=result, reason=reason).inc()
            if latency_seconds is not None:
                self._latency_seconds.labels(result=result).observe(latency_seconds)
        else:
            # 降级实现
            self._fallback_metrics['submit_total'][result][reason] += 1
            if latency_seconds is not None:
                self._fallback_metrics['latency_seconds'][result].append(latency_seconds)
    
    def record_throttle(self, reason: str):
        """记录节流
        
        Args:
            reason: 节流原因（rate_limit/weak_signal/low_consistency等）
        """
        if PROMETHEUS_AVAILABLE and self._throttle_total:
            self._throttle_total.labels(reason=reason).inc()
        else:
            # 降级实现
            self._fallback_metrics['throttle_total'][reason] += 1
    
    def set_rate_limit(self, rate_limit: float):
        """设置当前限速
        
        Args:
            rate_limit: 当前限速（每秒订单数）
        """
        if PROMETHEUS_AVAILABLE and self._current_rate_limit:
            self._current_rate_limit.set(rate_limit)
        else:
            # 降级实现
            self._fallback_metrics['current_rate_limit'] = rate_limit
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（用于测试或调试）
        
        Returns:
            统计信息字典
        """
        if PROMETHEUS_AVAILABLE:
            # prometheus_client的指标需要通过HTTP端点暴露，这里返回空字典
            return {}
        else:
            # 降级实现：返回统计信息
            stats = {
                'submit_total': dict(self._fallback_metrics['submit_total']),
                'throttle_total': dict(self._fallback_metrics['throttle_total']),
                'current_rate_limit': self._fallback_metrics['current_rate_limit'],
            }
            
            # 计算延迟统计
            latency_stats = {}
            for result, values in self._fallback_metrics['latency_seconds'].items():
                if values:
                    latency_stats[result] = {
                        'count': len(values),
                        'min': min(values),
                        'max': max(values),
                        'avg': sum(values) / len(values),
                        'p95': sorted(values)[int(len(values) * 0.95)] if len(values) > 0 else 0.0,
                    }
            stats['latency_seconds'] = latency_stats
            
            return stats


# 全局指标实例（单例模式）
_metrics_instance: Optional[ExecutorMetrics] = None


def get_executor_metrics() -> ExecutorMetrics:
    """获取全局ExecutorMetrics实例（单例）
    
    Returns:
        ExecutorMetrics实例
    """
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = ExecutorMetrics()
    return _metrics_instance

