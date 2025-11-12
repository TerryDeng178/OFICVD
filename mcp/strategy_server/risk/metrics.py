# -*- coding: utf-8 -*-
"""Risk Metrics Module

风险检查指标收集：支持 Prometheus 格式导出
"""

import time
import logging
from typing import Dict, List, Optional
from collections import defaultdict, deque
from threading import Lock

logger = logging.getLogger(__name__)


class RiskMetrics:
    """风险检查指标收集器"""
    
    def __init__(self):
        """初始化指标收集器"""
        self._lock = Lock()
        
        # 计数器：risk_precheck_total{result=pass/deny,reason=*}
        self._precheck_total = defaultdict(int)  # (result, reason) -> count
        
        # 直方图：risk_check_latency_ms（兼容输出）
        self._latency_samples = deque(maxlen=10000)  # 保留最近10000个样本
        self._latency_sum = 0.0
        self._latency_count = 0
        
        # 直方图：risk_check_latency_seconds（Prometheus最佳实践，主推）
        self._latency_seconds_samples = deque(maxlen=10000)
        self._latency_seconds_sum = 0.0
        self._latency_seconds_count = 0
        
        # 仪表盘：risk_shadow_parity_ratio
        self._shadow_total = 0
        self._shadow_parity = 0
        
        # Shadow告警：risk_shadow_alert（瞬时Gauge）
        self._shadow_alert_level = "ok"  # ok/warn/critical
    
    def record_precheck(self, passed: bool, reason_codes: List[str]):
        """记录风控检查结果
        
        Args:
            passed: 是否通过
            reason_codes: 拒绝原因码列表（空列表表示通过）
        """
        with self._lock:
            result = "pass" if passed else "deny"
            if reason_codes:
                # 记录每个拒绝原因
                for reason in reason_codes:
                    key = (result, reason)
                    self._precheck_total[key] += 1
            else:
                # 通过的情况
                key = (result, "none")
                self._precheck_total[key] += 1
    
    def record_latency(self, latency_ms: float):
        """记录风控检查耗时（毫秒，兼容输出）
        
        Args:
            latency_ms: 耗时（毫秒）
        """
        with self._lock:
            self._latency_samples.append(latency_ms)
            self._latency_sum += latency_ms
            self._latency_count += 1
    
    def record_latency_seconds(self, latency_seconds: float):
        """记录风控检查耗时（秒，Prometheus最佳实践）
        
        Args:
            latency_seconds: 耗时（秒）
        """
        with self._lock:
            self._latency_seconds_samples.append(latency_seconds)
            self._latency_seconds_sum += latency_seconds
            self._latency_seconds_count += 1
    
    def record_shadow_parity(self, parity: bool):
        """记录影子对比结果
        
        Args:
            parity: 是否一致
        """
        with self._lock:
            self._shadow_total += 1
            if parity:
                self._shadow_parity += 1
    
    def get_precheck_total(self) -> Dict[str, int]:
        """获取风控检查计数器
        
        Returns:
            字典：{(result, reason): count}
        """
        with self._lock:
            return dict(self._precheck_total)
    
    def get_latency_stats(self) -> Dict[str, float]:
        """获取耗时统计（毫秒，兼容输出）
        
        Returns:
            字典：包含 min, max, avg, p50, p95, p99
        """
        with self._lock:
            if not self._latency_samples:
                return {
                    "min": 0.0,
                    "max": 0.0,
                    "avg": 0.0,
                    "p50": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                    "count": 0,
                }
            
            samples = sorted(self._latency_samples)
            count = len(samples)
            
            return {
                "min": samples[0],
                "max": samples[-1],
                "avg": self._latency_sum / self._latency_count if self._latency_count > 0 else 0.0,
                "p50": samples[int(count * 0.50)] if count > 0 else 0.0,
                "p95": samples[int(count * 0.95)] if count > 0 else 0.0,
                "p99": samples[int(count * 0.99)] if count > 0 else 0.0,
                "count": count,
            }
    
    def get_latency_seconds_stats(self) -> Dict[str, float]:
        """获取耗时统计（秒，Prometheus最佳实践）
        
        Returns:
            字典：包含 min, max, avg, p50, p95, p99
        """
        with self._lock:
            if not self._latency_seconds_samples:
                return {
                    "min": 0.0,
                    "max": 0.0,
                    "avg": 0.0,
                    "p50": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                    "count": 0,
                }
            
            samples = sorted(self._latency_seconds_samples)
            count = len(samples)
            
            return {
                "min": samples[0],
                "max": samples[-1],
                "avg": self._latency_seconds_sum / self._latency_seconds_count if self._latency_seconds_count > 0 else 0.0,
                "p50": samples[int(count * 0.50)] if count > 0 else 0.0,
                "p95": samples[int(count * 0.95)] if count > 0 else 0.0,
                "p99": samples[int(count * 0.99)] if count > 0 else 0.0,
                "count": count,
            }
    
    def get_shadow_parity_ratio(self) -> float:
        """获取影子对比一致率
        
        Returns:
            一致率（0.0-1.0）
        """
        with self._lock:
            if self._shadow_total == 0:
                return 1.0
            return self._shadow_parity / self._shadow_total
    
    def update_shadow_alert(self, parity_ratio: float, threshold: float = 0.99):
        """更新Shadow一致性告警
        
        Args:
            parity_ratio: 当前一致率（0.0-1.0）
            threshold: 告警阈值（默认0.99，即99%）
        """
        import logging
        logger = logging.getLogger(__name__)
        
        with self._lock:
            old_level = self._shadow_alert_level
            
            if parity_ratio < threshold * 0.95:  # 低于95%阈值时升级为critical
                self._shadow_alert_level = "critical"
            elif parity_ratio < threshold:
                self._shadow_alert_level = "warn"
            else:
                self._shadow_alert_level = "ok"
            
            # 如果告警级别变化，记录日志（100%记录）
            if old_level != self._shadow_alert_level and self._shadow_alert_level != "ok":
                from .logging_config import get_risk_logger
                risk_logger = get_risk_logger()
                risk_logger.log_shadow_parity_alert(
                    parity_ratio, threshold, self._shadow_alert_level
                )
    
    def get_shadow_alert_level(self) -> str:
        """获取Shadow告警级别
        
        Returns:
            告警级别：ok/warn/critical
        """
        with self._lock:
            return self._shadow_alert_level
    
    def export_prometheus_format(self) -> str:
        """导出 Prometheus 格式指标
        
        注意：保持低基数字段，严禁透出symbol等高基数标签，以免TSDB膨胀
        
        Returns:
            Prometheus 格式的指标字符串
        """
        lines = []
        
        # risk_precheck_total{result="pass|deny",reason="..."}
        # 注意：reason_codes应限定为枚举，避免自由字符串导致高基数
        precheck_total = self.get_precheck_total()
        for (result, reason), count in precheck_total.items():
            lines.append(f'risk_precheck_total{{result="{result}",reason="{reason}"}} {count}')
        
        # risk_check_latency_seconds（主推，Prometheus最佳实践）
        latency_seconds_stats = self.get_latency_seconds_stats()
        if latency_seconds_stats["count"] > 0:
            lines.append(f'risk_check_latency_seconds{{quantile="0.5"}} {latency_seconds_stats["p50"]}')
            lines.append(f'risk_check_latency_seconds{{quantile="0.95"}} {latency_seconds_stats["p95"]}')
            lines.append(f'risk_check_latency_seconds{{quantile="0.99"}} {latency_seconds_stats["p99"]}')
            lines.append(f'risk_check_latency_seconds_sum {self._latency_seconds_sum}')
            lines.append(f'risk_check_latency_seconds_count {latency_seconds_stats["count"]}')
        
        # risk_check_latency_ms（兼容输出，后续在Dashboard统一换成seconds）
        latency_stats = self.get_latency_stats()
        if latency_stats["count"] > 0:
            lines.append(f'# DEPRECATED: risk_check_latency_ms (use risk_check_latency_seconds instead)')
            lines.append(f'risk_check_latency_ms{{quantile="0.5"}} {latency_stats["p50"]}')
            lines.append(f'risk_check_latency_ms{{quantile="0.95"}} {latency_stats["p95"]}')
            lines.append(f'risk_check_latency_ms{{quantile="0.99"}} {latency_stats["p99"]}')
            lines.append(f'risk_check_latency_ms_sum {self._latency_sum}')
            lines.append(f'risk_check_latency_ms_count {latency_stats["count"]}')
        
        # risk_shadow_parity_ratio
        parity_ratio = self.get_shadow_parity_ratio()
        lines.append(f'risk_shadow_parity_ratio {parity_ratio}')
        
        # risk_shadow_alert（瞬时Gauge，便于接入报警器）
        alert_level = self.get_shadow_alert_level()
        alert_value = 1 if alert_level != "ok" else 0
        lines.append(f'risk_shadow_alert{{level="{alert_level}"}} {alert_value}')
        
        return "\n".join(lines)
    
    def reset(self):
        """重置所有指标（用于测试）"""
        with self._lock:
            self._precheck_total.clear()
            self._latency_samples.clear()
            self._latency_sum = 0.0
            self._latency_count = 0
            self._latency_seconds_samples.clear()
            self._latency_seconds_sum = 0.0
            self._latency_seconds_count = 0
            self._shadow_total = 0
            self._shadow_parity = 0
            self._shadow_alert_level = "ok"


# 全局指标实例
_metrics: Optional[RiskMetrics] = None


def get_metrics() -> RiskMetrics:
    """获取全局指标实例
    
    Returns:
        指标收集器实例
    """
    global _metrics
    if _metrics is None:
        _metrics = RiskMetrics()
    return _metrics


def reset_metrics():
    """重置全局指标（用于测试）"""
    global _metrics
    if _metrics is not None:
        _metrics.reset()

