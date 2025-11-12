# -*- coding: utf-8 -*-
"""幂等性与重试模块

实现client_order_id幂等键生成和指数退避重试机制
"""
import hashlib
import logging
import time
import random
from typing import Optional, Dict, Set
from collections import deque

from .base_executor import OrderCtx, Order

logger = logging.getLogger(__name__)


def generate_idempotent_key(
    signal_row_id: Optional[str] = None,
    ts_ms: Optional[int] = None,
    side: Optional[str] = None,
    qty: Optional[float] = None,
    price: Optional[float] = None,
) -> str:
    """生成幂等键（client_order_id）
    
    格式：hash(signal_row_id|ts_ms|side|qty|px)
    
    Args:
        signal_row_id: 信号行ID
        ts_ms: 时间戳（ms）
        side: 方向（buy/sell）
        qty: 数量
        price: 价格
        
    Returns:
        幂等键（十六进制字符串，32字符）
    """
    # 构建键值字符串
    key_parts = []
    
    if signal_row_id:
        key_parts.append(str(signal_row_id))
    if ts_ms is not None:
        key_parts.append(str(ts_ms))
    if side:
        key_parts.append(str(side))
    if qty is not None:
        # 数量需要格式化以避免浮点精度问题
        key_parts.append(f"{qty:.8f}")
    if price is not None:
        # 价格需要格式化以避免浮点精度问题
        key_parts.append(f"{price:.8f}")
    
    # 如果所有字段都为空，使用时间戳和随机数
    if not key_parts:
        key_parts = [str(int(time.time() * 1000)), str(random.randint(0, 999999))]
    
    # 生成SHA256哈希
    key_string = "|".join(key_parts)
    hash_obj = hashlib.sha256(key_string.encode("utf-8"))
    hash_hex = hash_obj.hexdigest()
    
    # 返回前32字符（64位十六进制的前32字符）
    return hash_hex[:32]


def generate_idempotent_key_from_order_ctx(order_ctx: OrderCtx) -> str:
    """从OrderCtx生成幂等键
    
    Args:
        order_ctx: 订单上下文
        
    Returns:
        幂等键
    """
    return generate_idempotent_key(
        signal_row_id=order_ctx.signal_row_id,
        ts_ms=order_ctx.ts_ms or order_ctx.event_ts_ms,
        side=order_ctx.side.value if order_ctx.side else None,
        qty=order_ctx.qty,
        price=order_ctx.price,
    )


def generate_idempotent_key_from_order(order: Order) -> str:
    """从Order生成幂等键（向后兼容）
    
    Args:
        order: 订单对象
        
    Returns:
        幂等键
    """
    return generate_idempotent_key(
        signal_row_id=order.metadata.get("signal_row_id"),
        ts_ms=order.ts_ms,
        side=order.side.value if order.side else None,
        qty=order.qty,
        price=order.price,
    )


class RetryPolicy:
    """重试策略
    
    指数退避 + 抖动（上限3次）+ 只对网络/5xx重试
    """
    
    def __init__(self, max_retries: int = 3, base_delay: float = 0.1, max_delay: float = 5.0):
        """初始化重试策略
        
        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒）
            max_delay: 最大延迟（秒）
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def should_retry(self, attempt: int, error: Exception) -> bool:
        """判断是否应该重试
        
        Args:
            attempt: 当前尝试次数（0-based）
            error: 异常对象
            
        Returns:
            是否应该重试
        """
        # 超过最大重试次数
        if attempt >= self.max_retries:
            return False
        
        # 检查错误类型
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # 网络错误：应该重试
        network_errors = ["connection", "timeout", "network", "socket", "dns"]
        if any(keyword in error_str for keyword in network_errors):
            return True
        
        # 5xx错误：应该重试
        if "500" in error_str or "502" in error_str or "503" in error_str or "504" in error_str:
            return True
        
        # HTTP异常（5xx状态码）
        if hasattr(error, "response") and hasattr(error.response, "status_code"):
            status_code = error.response.status_code
            if 500 <= status_code < 600:
                return True
        
        # 本地参数/风控拒单：不重试
        if "rejected" in error_str or "denied" in error_str or "invalid" in error_str:
            return False
        
        # 其他错误：默认不重试
        return False
    
    def get_delay(self, attempt: int) -> float:
        """获取重试延迟（指数退避 + 抖动）
        
        Args:
            attempt: 当前尝试次数（0-based）
            
        Returns:
            延迟时间（秒）
        """
        # 指数退避：base_delay * 2^attempt
        exponential_delay = self.base_delay * (2 ** attempt)
        
        # 添加抖动（±20%）
        jitter = exponential_delay * 0.2 * (random.random() * 2 - 1)
        
        # 计算最终延迟
        delay = exponential_delay + jitter
        
        # 限制在max_delay内
        delay = min(delay, self.max_delay)
        
        return max(0.0, delay)


class IdempotencyTracker:
    """幂等性跟踪器
    
    跟踪已处理的订单，避免重复下单
    """
    
    def __init__(self, max_size: int = 10000):
        """初始化幂等性跟踪器
        
        Args:
            max_size: 最大跟踪数量（LRU）
        """
        self._processed_orders: Set[str] = set()
        self._order_queue: deque = deque(maxlen=max_size)
        self.max_size = max_size
    
    def is_processed(self, client_order_id: str) -> bool:
        """检查订单是否已处理
        
        Args:
            client_order_id: 客户端订单ID
            
        Returns:
            是否已处理
        """
        return client_order_id in self._processed_orders
    
    def mark_processed(self, client_order_id: str) -> None:
        """标记订单为已处理
        
        Args:
            client_order_id: 客户端订单ID
        """
        # 如果达到最大大小，移除最旧的订单
        if len(self._processed_orders) >= self.max_size:
            oldest = self._order_queue.popleft()
            self._processed_orders.discard(oldest)
        
        # 添加新订单
        self._processed_orders.add(client_order_id)
        self._order_queue.append(client_order_id)
    
    def clear(self) -> None:
        """清空跟踪器"""
        self._processed_orders.clear()
        self._order_queue.clear()


def retry_with_backoff(
    func,
    retry_policy: Optional[RetryPolicy] = None,
    *args,
    **kwargs
):
    """带指数退避的重试装饰器
    
    Args:
        func: 要执行的函数
        retry_policy: 重试策略（可选）
        *args: 函数位置参数
        **kwargs: 函数关键字参数
        
    Returns:
        函数返回值
        
    Raises:
        最后一次尝试的异常
    """
    if retry_policy is None:
        retry_policy = RetryPolicy()
    
    last_exception = None
    
    for attempt in range(retry_policy.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            # 检查是否应该重试
            if not retry_policy.should_retry(attempt, e):
                logger.debug(f"[Retry] Not retrying: {e}")
                raise
            
            # 计算延迟
            delay = retry_policy.get_delay(attempt)
            logger.debug(f"[Retry] Attempt {attempt + 1}/{retry_policy.max_retries + 1}, delay={delay:.3f}s: {e}")
            
            # 等待
            time.sleep(delay)
    
    # 所有重试都失败
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError("Retry failed without exception")

