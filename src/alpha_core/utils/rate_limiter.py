# -*- coding: utf-8 -*-
"""Rate Limiter (Token Bucket)

令牌桶节流器：线程安全的速率限制
"""

import time
import threading
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TokenBucket:
    """令牌桶节流器（线程安全）"""
    
    def __init__(self, capacity: int, fill_rate: float):
        """初始化令牌桶
        
        Args:
            capacity: 桶容量（burst）
            fill_rate: 填充速率（tokens per second）
        """
        self.capacity = capacity
        self.fill_rate = fill_rate
        self.tokens = float(capacity)
        self.last_update = time.time()
        self._lock = threading.Lock()
    
    def acquire(self, tokens: int = 1) -> bool:
        """获取令牌
        
        Args:
            tokens: 需要的令牌数量
            
        Returns:
            是否成功获取令牌
        """
        with self._lock:
            now = time.time()
            # 计算应该填充的令牌数
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            else:
                return False
    
    def try_acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """尝试获取令牌（带超时）
        
        Args:
            tokens: 需要的令牌数量
            timeout: 超时时间（秒），None表示立即返回
            
        Returns:
            是否成功获取令牌
        """
        if timeout is None:
            return self.acquire(tokens)
        
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.acquire(tokens):
                return True
            time.sleep(0.01)  # 短暂等待后重试
        
        return False
    
    def get_available_tokens(self) -> float:
        """获取当前可用令牌数"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            self.last_update = now
            return self.tokens


class RateLimiter:
    """速率限制器（管理多个令牌桶，支持自适应节流）"""
    
    def __init__(self, place_rps: float = 8.0, place_burst: int = 16,
                 cancel_rps: float = 5.0, cancel_burst: int = 10,
                 query_rps: float = 10.0, query_burst: int = 20):
        """初始化速率限制器
        
        Args:
            place_rps: 下单速率（每秒）
            place_burst: 下单突发容量
            cancel_rps: 撤单速率（每秒）
            cancel_burst: 撤单突发容量
            query_rps: 查询速率（每秒）
            query_burst: 查询突发容量
        """
        self.place_bucket = TokenBucket(place_burst, place_rps)
        self.cancel_bucket = TokenBucket(cancel_burst, cancel_rps)
        self.query_bucket = TokenBucket(query_burst, query_rps)
        
        # P2: 自适应节流配置
        self._base_place_rps = place_rps
        self._base_cancel_rps = cancel_rps
        self._base_query_rps = query_rps
        self._adaptive_backoff_until = 0.0  # 自适应退避截止时间
        self._adaptive_factor = 0.5  # 退避时降低到原速率的50%
    
    def acquire_place(self, timeout: Optional[float] = None) -> bool:
        """获取下单令牌（P2: 支持自适应节流）"""
        # P2: 检查是否需要自适应退避
        import time
        if time.time() < self._adaptive_backoff_until:
            # 退避期间，使用降低的速率
            if self.place_bucket.fill_rate > self._base_place_rps * self._adaptive_factor:
                self.place_bucket.fill_rate = self._base_place_rps * self._adaptive_factor
        else:
            # 恢复正常速率
            if self.place_bucket.fill_rate < self._base_place_rps:
                self.place_bucket.fill_rate = self._base_place_rps
        
        return self.place_bucket.try_acquire(1, timeout)
    
    def acquire_cancel(self, timeout: Optional[float] = None) -> bool:
        """获取撤单令牌"""
        return self.cancel_bucket.try_acquire(1, timeout)
    
    def acquire_query(self, timeout: Optional[float] = None) -> bool:
        """获取查询令牌"""
        return self.query_bucket.try_acquire(1, timeout)
    
    def get_available_tokens(self, operation: str = "place") -> float:
        """获取可用令牌数（P2: 用于观测）
        
        Args:
            operation: 操作类型（place|cancel|query）
            
        Returns:
            可用令牌数
        """
        if operation == "place":
            return self.place_bucket.get_available_tokens()
        elif operation == "cancel":
            return self.cancel_bucket.get_available_tokens()
        elif operation == "query":
            return self.query_bucket.get_available_tokens()
        else:
            return 0.0
    
    def trigger_adaptive_backoff(self, duration_sec: float = 10.0) -> None:
        """触发自适应退避（P2: 当捕获 E.RATE.LIMIT 时调用）
        
        Args:
            duration_sec: 退避持续时间（秒）
        """
        import time
        self._adaptive_backoff_until = time.time() + duration_sec
        logger.info(f"[RateLimiter] Adaptive backoff triggered, duration={duration_sec}s")

