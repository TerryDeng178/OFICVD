# -*- coding: utf-8 -*-
"""Risk Metrics HTTP Endpoint

提供HTTP端点导出Prometheus格式的风险指标
支持：/metrics（Prometheus指标）、/healthz（健康检查）、/readyz（就绪检查）
特性：gzip压缩、请求限流
"""

import gzip
import logging
import time
from collections import deque
from threading import Lock, Thread
from typing import Optional
from http.server import BaseHTTPRequestHandler, HTTPServer

from .metrics import get_metrics
from .precheck import _risk_manager

logger = logging.getLogger(__name__)


class MetricsHandler(BaseHTTPRequestHandler):
    """Prometheus指标HTTP处理器（支持healthz/readyz/gzip/限流）"""
    
    # 请求限流：每个IP的请求时间戳队列（滑动窗口）
    _request_history: dict = {}
    _rate_limit_lock = Lock()
    _rate_limit_window_seconds = 60  # 时间窗口（秒）
    _rate_limit_max_requests = 100  # 每个窗口最大请求数
    
    def _check_rate_limit(self, client_ip: str) -> bool:
        """检查请求限流
        
        Args:
            client_ip: 客户端IP地址
            
        Returns:
            是否允许请求
        """
        current_time = time.time()
        
        with self._rate_limit_lock:
            if client_ip not in self._request_history:
                self._request_history[client_ip] = deque()
            
            # 清理过期请求
            request_queue = self._request_history[client_ip]
            while request_queue and current_time - request_queue[0] > self._rate_limit_window_seconds:
                request_queue.popleft()
            
            # 检查是否超过限制
            if len(request_queue) >= self._rate_limit_max_requests:
                return False
            
            # 记录本次请求
            request_queue.append(current_time)
            return True
    
    def _get_client_ip(self) -> str:
        """获取客户端IP地址"""
        return self.client_address[0]
    
    def _check_health(self) -> bool:
        """健康检查（轻量本地探活）
        
        Returns:
            是否健康
        """
        # 检查RiskManager是否已初始化
        return _risk_manager is not None
    
    def _check_readiness(self) -> tuple[bool, str]:
        """就绪检查（依赖就绪检查）
        
        Returns:
            (是否就绪, 原因)
        """
        # 检查RiskManager是否已初始化
        if _risk_manager is None:
            return False, "RiskManager not initialized"
        
        # 检查是否启用内联风控（如果未启用，可能回退到legacy）
        if not _risk_manager.enabled:
            return True, "RiskManager disabled (fallback to legacy)"  # 未启用也算就绪
        
        # 可以添加更多依赖检查，例如：
        # - SQLite连接检查
        # - JSONL文件写入权限检查
        # - 配置有效性检查
        
        return True, "ready"
    
    def _send_gzip_response(self, status_code: int, content: bytes, content_type: str = "text/plain; charset=utf-8"):
        """发送gzip压缩响应
        
        Args:
            status_code: HTTP状态码
            content: 响应内容（bytes）
            content_type: Content-Type头
        """
        # 压缩内容
        compressed_content = gzip.compress(content)
        
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(compressed_content)))
        self.end_headers()
        self.wfile.write(compressed_content)
    
    def do_GET(self):
        """处理GET请求"""
        client_ip = self._get_client_ip()
        
        # 请求限流检查
        if not self._check_rate_limit(client_ip):
            self.send_response(429)  # Too Many Requests
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Retry-After", str(self._rate_limit_window_seconds))
            self.end_headers()
            self.wfile.write(b"Rate limit exceeded")
            logger.warning(f"[MetricsEndpoint] Rate limit exceeded for {client_ip}")
            return
        
        # 路由处理
        if self.path == "/metrics":
            self._handle_metrics()
        elif self.path == "/healthz":
            self._handle_healthz()
        elif self.path == "/readyz":
            self._handle_readyz()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")
    
    def _handle_metrics(self):
        """处理/metrics请求"""
        try:
            metrics = get_metrics()
            prometheus_output = metrics.export_prometheus_format()
            content = prometheus_output.encode("utf-8")
            
            # 检查客户端是否支持gzip
            accept_encoding = self.headers.get("Accept-Encoding", "")
            if "gzip" in accept_encoding:
                self._send_gzip_response(200, content, "text/plain; version=0.0.4; charset=utf-8")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        except Exception as e:
            logger.error(f"[MetricsEndpoint] Failed to export metrics: {e}")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Internal Server Error: {e}".encode("utf-8"))
    
    def _handle_healthz(self):
        """处理/healthz请求（轻量本地探活）"""
        is_healthy = self._check_health()
        
        if is_healthy:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(503)  # Service Unavailable
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"unhealthy")
    
    def _handle_readyz(self):
        """处理/readyz请求（依赖就绪检查）"""
        is_ready, reason = self._check_readiness()
        
        if is_ready:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"ready: {reason}".encode("utf-8"))
        else:
            self.send_response(503)  # Service Unavailable
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"not ready: {reason}".encode("utf-8"))
    
    def log_message(self, format, *args):
        """重写日志方法，使用logger"""
        logger.debug(f"[MetricsEndpoint] {format % args}")


class MetricsServer:
    """指标服务器"""
    
    def __init__(self, host: str = "localhost", port: int = 9090):
        """初始化指标服务器
        
        Args:
            host: 监听地址
            port: 监听端口
        """
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None
    
    def start(self):
        """启动指标服务器（后台线程）"""
        if self.server is not None:
            logger.warning("[MetricsEndpoint] Server already started")
            return
        
        self.server = HTTPServer((self.host, self.port), MetricsHandler)
        self.thread = Thread(target=self._run_server, daemon=True)
        self.thread.start()
        logger.info(f"[MetricsEndpoint] Started metrics server on http://{self.host}:{self.port}/metrics")
    
    def _run_server(self):
        """运行服务器（在后台线程中）"""
        if self.server:
            self.server.serve_forever()
    
    def stop(self):
        """停止指标服务器"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            self.thread = None
            logger.info("[MetricsEndpoint] Stopped metrics server")


# 全局服务器实例
_metrics_server: Optional[MetricsServer] = None


def start_metrics_server(host: str = "localhost", port: int = 9090):
    """启动全局指标服务器
    
    Args:
        host: 监听地址
        port: 监听端口
    """
    global _metrics_server
    if _metrics_server is None:
        _metrics_server = MetricsServer(host, port)
        _metrics_server.start()


def stop_metrics_server():
    """停止全局指标服务器"""
    global _metrics_server
    if _metrics_server:
        _metrics_server.stop()
        _metrics_server = None

