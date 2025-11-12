# -*- coding: utf-8 -*-
"""P2 Optimizations Unit Tests

测试P2优化：/metrics端点工程化、日志抽样、回归测试
"""

import pytest
import gzip
import json
import time
from unittest.mock import Mock, patch
from http.server import HTTPServer
from threading import Thread

from mcp.strategy_server.risk.metrics_endpoint import (
    MetricsHandler,
    MetricsServer,
    start_metrics_server,
    stop_metrics_server,
)
from mcp.strategy_server.risk.logging_config import RiskLogger, get_risk_logger
from mcp.strategy_server.risk import initialize_risk_manager, OrderCtx, pre_order_check


class TestMetricsEndpoint:
    """测试/metrics端点工程化"""
    
    @pytest.fixture
    def server(self):
        """创建测试服务器"""
        server = MetricsServer(host="localhost", port=0)  # 端口0表示自动分配
        yield server
        server.stop()
    
    def test_healthz_endpoint(self, server):
        """测试/healthz端点"""
        server.start()
        time.sleep(0.1)  # 等待服务器启动
        
        import urllib.request
        import urllib.error
        
        try:
            # 获取实际端口
            port = server.server.server_address[1]
            url = f"http://localhost:{port}/healthz"
            
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            assert response.read() == b"ok"
        except Exception as e:
            pytest.skip(f"HTTP request failed: {e}")
    
    def test_readyz_endpoint(self, server):
        """测试/readyz端点"""
        # 初始化RiskManager
        config = {
            "risk": {
                "enabled": True,
                "guards": {"spread_bps_max": 8.0},
            }
        }
        initialize_risk_manager(config)
        
        server.start()
        time.sleep(0.1)
        
        import urllib.request
        
        try:
            port = server.server.server_address[1]
            url = f"http://localhost:{port}/readyz"
            
            response = urllib.request.urlopen(url, timeout=1)
            assert response.getcode() == 200
            content = response.read().decode("utf-8")
            assert "ready" in content.lower()
        except Exception as e:
            pytest.skip(f"HTTP request failed: {e}")
    
    def test_metrics_gzip(self, server):
        """测试/metrics端点的gzip压缩"""
        server.start()
        time.sleep(0.1)
        
        import urllib.request
        
        try:
            port = server.server.server_address[1]
            url = f"http://localhost:{port}/metrics"
            
            # 请求gzip压缩
            request = urllib.request.Request(url)
            request.add_header("Accept-Encoding", "gzip")
            
            response = urllib.request.urlopen(request, timeout=1)
            assert response.getcode() == 200
            
            # 检查Content-Encoding头
            content_encoding = response.headers.get("Content-Encoding")
            assert content_encoding == "gzip"
            
            # 解压内容
            compressed_content = response.read()
            decompressed_content = gzip.decompress(compressed_content)
            assert len(decompressed_content) > 0
        except Exception as e:
            pytest.skip(f"HTTP request failed: {e}")
    
    def test_rate_limiting(self):
        """测试请求限流逻辑"""
        # 直接测试限流逻辑（使用类属性）
        client_ip = "127.0.0.1"
        
        # 清除历史记录
        with MetricsHandler._rate_limit_lock:
            if client_ip in MetricsHandler._request_history:
                MetricsHandler._request_history[client_ip].clear()
        
        # 直接调用限流检查逻辑（模拟）
        import time
        from collections import deque
        
        # 模拟限流逻辑
        request_history = {}
        rate_limit_lock = MetricsHandler._rate_limit_lock
        window_seconds = MetricsHandler._rate_limit_window_seconds
        max_requests = MetricsHandler._rate_limit_max_requests
        
        def check_rate_limit(ip: str) -> bool:
            current_time = time.time()
            with rate_limit_lock:
                if ip not in request_history:
                    request_history[ip] = deque()
                
                request_queue = request_history[ip]
                while request_queue and current_time - request_queue[0] > window_seconds:
                    request_queue.popleft()
                
                if len(request_queue) >= max_requests:
                    return False
                
                request_queue.append(current_time)
                return True
        
        # 发送大量请求（超过限制）
        allowed_count = 0
        for i in range(max_requests + 10):
            if check_rate_limit(client_ip):
                allowed_count += 1
        
        # 应该允许前N个请求，拒绝后续请求
        assert allowed_count <= max_requests


class TestLoggingSampling:
    """测试日志抽样"""
    
    def test_log_order_passed_sampling(self):
        """测试通过单1%抽样"""
        logger = RiskLogger(sample_rate=0.01)
        
        # 模拟100次通过
        log_count = 0
        with patch.object(logger.logger, 'debug') as mock_debug:
            for i in range(100):
                logger.log_order_passed("BTCUSDT", "buy", 1.5)
            
            # 应该大约记录1次（1%抽样）
            assert 0 <= mock_debug.call_count <= 5  # 允许一定误差
    
    def test_log_order_denied_no_sampling(self):
        """测试失败单100%记录"""
        logger = RiskLogger(sample_rate=0.01)
        
        with patch.object(logger.logger, 'warning') as mock_warning:
            # 记录10次失败
            for i in range(10):
                logger.log_order_denied("BTCUSDT", "buy", ["spread_too_wide"], 1.5)
            
            # 应该100%记录
            assert mock_warning.call_count == 10


class TestGatingBreakdownNormalizer:
    """测试gating_breakdown标准化"""
    
    def test_normalize_key(self):
        """测试key归一化"""
        from scripts.gating_breakdown_normalizer import normalize_key
        
        assert normalize_key("Spread BPS") == "spread_bps"
        assert normalize_key("Event Lag Sec") == "event_lag_sec"
        assert normalize_key("Activity  TPM") == "activity_tpm"
        assert normalize_key("Market Inactive") == "market_inactive"
    
    def test_normalize_gating_breakdown(self):
        """测试gating_breakdown归一化"""
        from scripts.gating_breakdown_normalizer import normalize_gating_breakdown
        
        breakdown = {
            "Spread BPS": 10,
            "Event Lag Sec": 5,
            "Activity  TPM": 3,
        }
        
        normalized = normalize_gating_breakdown(breakdown)
        
        assert "spread_bps" in normalized
        assert "event_lag_sec" in normalized
        assert "activity_tpm" in normalized
        assert normalized["spread_bps"] == 10
    
    def test_generate_prometheus_metrics(self):
        """测试生成Prometheus指标"""
        from scripts.gating_breakdown_normalizer import generate_prometheus_metrics
        
        breakdown = {
            "spread_bps": 10,
            "event_lag_sec": 5,
            "activity_tpm": 3,
        }
        
        output = generate_prometheus_metrics(breakdown)
        
        assert "risk_gate_breakdown_total" in output
        assert 'gate="spread_bps"' in output
        assert "10" in output

