# -*- coding: utf-8 -*-
"""执行观测指标模块（Worker层）

提供Worker级别的观测指标收集和输出功能
专门用于ExecutionWorker的统计和监控
"""
import time
import logging
from typing import Dict, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class ExecutionMetrics:
    """执行观测指标收集器（Worker层）

    收集Worker级别的统计信息：信号处理、延迟、结果统计、并发数等
    """

    def __init__(self):
        self._stats = {
            'signals_processed': 0,
            'executions_success': 0,
            'executions_failed': 0,
            'executions_skip': 0,
            'current_concurrency': 0,
            'lag_ms_samples': [],  # 最近的延迟样本
            'start_time': time.time()
        }

    def increment_signals_processed(self) -> None:
        """增加信号处理计数"""
        self._stats['signals_processed'] += 1

    def observe_lag(self, lag_ms: float) -> None:
        """观察执行延迟"""
        self._stats['lag_ms_samples'].append(lag_ms)
        # 只保留最近100个样本
        if len(self._stats['lag_ms_samples']) > 100:
            self._stats['lag_ms_samples'] = self._stats['lag_ms_samples'][-100:]

    def increment_result(self, status: str) -> None:
        """增加执行结果计数"""
        if status == 'success':
            self._stats['executions_success'] += 1
        elif status == 'failed':
            self._stats['executions_failed'] += 1
        elif status == 'skip':
            self._stats['executions_skip'] += 1

    def inc_concurrency(self) -> None:
        """增加并发数"""
        self._stats['current_concurrency'] += 1

    def dec_concurrency(self) -> None:
        """减少并发数"""
        self._stats['current_concurrency'] = max(0, self._stats['current_concurrency'] - 1)

    def update_success_rate(self, success_count: int, total_count: int) -> None:
        """更新成功率（自动从stats计算）"""
        # 这个方法保留兼容性，实际通过get_summary计算
        pass

    def get_metric_value(self, name: str) -> Optional[float]:
        """获取指标值"""
        if name == 'signals_processed':
            return float(self._stats['signals_processed'])
        elif name == 'lag_ms':
            samples = self._stats['lag_ms_samples']
            return float(sum(samples) / len(samples)) if samples else 0.0
        elif name == 'concurrency':
            return float(self._stats['current_concurrency'])
        elif name == 'success_rate':
            total = self._stats['executions_success'] + self._stats['executions_failed']
            return float(self._stats['executions_success'] / total) if total > 0 else 0.0
        elif name.startswith('result_'):
            status = name.replace('result_', '')
            if status == 'success':
                return float(self._stats['executions_success'])
            elif status == 'failed':
                return float(self._stats['executions_failed'])
            elif status == 'skip':
                return float(self._stats['executions_skip'])
        return None

    def log_summary(self) -> None:
        """记录指标摘要到日志"""
        summary = self.get_summary()
        logger.info("执行指标摘要: " + " | ".join(f"{k}={v}" for k, v in summary.items()))

    def get_summary(self) -> Dict[str, Any]:
        """获取指标摘要"""
        runtime = time.time() - self._stats['start_time']
        return {
            "runtime_sec": round(runtime, 2),
            "signals_processed": self._stats['signals_processed'],
            "executions_success": self._stats['executions_success'],
            "executions_failed": self._stats['executions_failed'],
            "executions_skip": self._stats['executions_skip'],
            "current_concurrency": self._stats['current_concurrency'],
            "avg_lag_ms": round(self.get_metric_value('lag_ms') or 0, 2),
            "success_rate": round(self.get_metric_value('success_rate') or 0, 3),
        }

    def reset(self) -> None:
        """重置所有指标"""
        self._stats = {
            'signals_processed': 0,
            'executions_success': 0,
            'executions_failed': 0,
            'executions_skip': 0,
            'current_concurrency': 0,
            'lag_ms_samples': [],
            'start_time': time.time()
        }


# 全局指标实例
_default_metrics = None


def get_execution_metrics() -> ExecutionMetrics:
    """获取全局执行指标实例"""
    global _default_metrics
    if _default_metrics is None:
        _default_metrics = ExecutionMetrics()
    return _default_metrics