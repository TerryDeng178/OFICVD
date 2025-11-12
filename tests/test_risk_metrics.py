# -*- coding: utf-8 -*-
"""Risk Metrics Unit Tests

测试 mcp/strategy_server/risk/metrics.py 模块
"""

import pytest
import time

from mcp.strategy_server.risk.metrics import RiskMetrics, get_metrics, reset_metrics
from mcp.strategy_server.risk.schemas import OrderCtx, RiskDecision


class TestRiskMetrics:
    """测试风险指标收集器"""
    
    def test_record_precheck_pass(self):
        """测试记录通过的风控检查"""
        metrics = RiskMetrics()
        metrics.record_precheck(True, [])
        
        precheck_total = metrics.get_precheck_total()
        assert precheck_total[("pass", "none")] == 1
    
    def test_record_precheck_deny_single_reason(self):
        """测试记录拒绝的风控检查（单个原因）"""
        metrics = RiskMetrics()
        metrics.record_precheck(False, ["spread_too_wide"])
        
        precheck_total = metrics.get_precheck_total()
        assert precheck_total[("deny", "spread_too_wide")] == 1
    
    def test_record_precheck_deny_multiple_reasons(self):
        """测试记录拒绝的风控检查（多个原因）"""
        metrics = RiskMetrics()
        metrics.record_precheck(False, ["spread_too_wide", "lag_exceeds_cap"])
        
        precheck_total = metrics.get_precheck_total()
        assert precheck_total[("deny", "spread_too_wide")] == 1
        assert precheck_total[("deny", "lag_exceeds_cap")] == 1
    
    def test_record_latency(self):
        """测试记录耗时"""
        metrics = RiskMetrics()
        metrics.record_latency(1.5)
        metrics.record_latency(2.0)
        metrics.record_latency(3.0)
        
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["count"] == 3
        assert latency_stats["min"] == 1.5
        assert latency_stats["max"] == 3.0
        assert latency_stats["avg"] == 2.1666666666666665  # (1.5 + 2.0 + 3.0) / 3
    
    def test_record_latency_empty(self):
        """测试空耗时统计"""
        metrics = RiskMetrics()
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["count"] == 0
        assert latency_stats["min"] == 0.0
        assert latency_stats["max"] == 0.0
    
    def test_record_shadow_parity(self):
        """测试记录影子对比结果"""
        metrics = RiskMetrics()
        metrics.record_shadow_parity(True)
        metrics.record_shadow_parity(True)
        metrics.record_shadow_parity(False)
        
        parity_ratio = metrics.get_shadow_parity_ratio()
        assert parity_ratio == 2.0 / 3.0
    
    def test_record_shadow_parity_empty(self):
        """测试空影子对比统计"""
        metrics = RiskMetrics()
        parity_ratio = metrics.get_shadow_parity_ratio()
        assert parity_ratio == 1.0  # 默认返回1.0
    
    def test_export_prometheus_format(self):
        """测试导出 Prometheus 格式"""
        metrics = RiskMetrics()
        metrics.record_precheck(True, [])
        metrics.record_precheck(False, ["spread_too_wide"])
        metrics.record_latency(1.5)
        metrics.record_latency(2.0)
        metrics.record_shadow_parity(True)
        metrics.record_shadow_parity(False)
        
        prometheus_output = metrics.export_prometheus_format()
        
        # 检查是否包含预期的指标
        assert "risk_precheck_total" in prometheus_output
        assert "risk_check_latency_ms" in prometheus_output
        assert "risk_shadow_parity_ratio" in prometheus_output
        
        # 检查具体值
        assert 'risk_precheck_total{result="pass",reason="none"}' in prometheus_output
        assert 'risk_precheck_total{result="deny",reason="spread_too_wide"}' in prometheus_output
        assert "risk_shadow_parity_ratio" in prometheus_output
    
    def test_reset(self):
        """测试重置指标"""
        metrics = RiskMetrics()
        metrics.record_precheck(True, [])
        metrics.record_latency(1.5)
        metrics.record_shadow_parity(True)
        
        metrics.reset()
        
        precheck_total = metrics.get_precheck_total()
        assert len(precheck_total) == 0
        
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["count"] == 0
        
        parity_ratio = metrics.get_shadow_parity_ratio()
        assert parity_ratio == 1.0


class TestGlobalMetrics:
    """测试全局指标实例"""
    
    def test_get_metrics_singleton(self):
        """测试全局指标实例是单例"""
        metrics1 = get_metrics()
        metrics2 = get_metrics()
        assert metrics1 is metrics2
    
    def test_reset_metrics(self):
        """测试重置全局指标"""
        metrics = get_metrics()
        metrics.record_precheck(True, [])
        
        reset_metrics()
        
        precheck_total = metrics.get_precheck_total()
        assert len(precheck_total) == 0

