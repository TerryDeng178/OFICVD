# -*- coding: utf-8 -*-
"""Retry Utility

重试工具：指数退避 + 抖动
"""

import random
import time
import logging
from typing import Callable, Optional, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryPolicy:
    """重试策略（指数退避 + 抖动）"""
    
    def __init__(self, max_retries: int = 5, base_delay_ms: int = 200,
                 factor: float = 2.0, jitter_pct: float = 0.25):
        """初始化重试策略
        
        Args:
            max_retries: 最大重试次数
            base_delay_ms: 基础延迟（毫秒）
            factor: 退避因子（每次延迟乘以该值）
            jitter_pct: 抖动百分比（±25%）
        """
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.factor = factor
        self.jitter_pct = jitter_pct
    
    def get_delay_ms(self, attempt: int) -> int:
        """计算延迟时间（毫秒）
        
        Args:
            attempt: 当前尝试次数（0-based）
            
        Returns:
            延迟时间（毫秒）
        """
        # 指数退避：base * factor^attempt
        delay_ms = self.base_delay_ms * (self.factor ** attempt)
        
        # 添加抖动：±jitter_pct
        jitter = delay_ms * self.jitter_pct
        delay_ms = delay_ms + random.uniform(-jitter, jitter)
        
        # 确保非负
        return max(0, int(delay_ms))
    
    def should_retry(self, attempt: int) -> bool:
        """判断是否应该重试
        
        Args:
            attempt: 当前尝试次数（0-based）
            
        Returns:
            是否应该重试
        """
        return attempt < self.max_retries


def retry_with_backoff(func: Callable[[], T], policy: Optional[RetryPolicy] = None,
                       is_retriable: Optional[Callable[[Exception], bool]] = None) -> T:
    """带指数退避的重试装饰器
    
    Args:
        func: 要重试的函数
        policy: 重试策略，None使用默认策略
        is_retriable: 判断异常是否可重试的函数，None表示所有异常都可重试
        
    Returns:
        函数返回值
        
    Raises:
        最后一次尝试的异常
    """
    if policy is None:
        policy = RetryPolicy()
    
    last_exception = None
    
    for attempt in range(policy.max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            
            # 判断是否可重试
            if is_retriable and not is_retriable(e):
                logger.debug(f"[Retry] Non-retriable error: {e}")
                raise
            
            # 判断是否应该重试
            if not policy.should_retry(attempt):
                logger.debug(f"[Retry] Max retries ({policy.max_retries}) exceeded")
                raise
            
            # 计算延迟并等待
            delay_ms = policy.get_delay_ms(attempt)
            logger.debug(f"[Retry] Attempt {attempt + 1}/{policy.max_retries + 1} failed: {e}, "
                        f"retrying after {delay_ms}ms")
            time.sleep(delay_ms / 1000.0)
    
    # 理论上不会到达这里
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry failed without exception")

