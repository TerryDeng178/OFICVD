# -*- coding: utf-8 -*-
"""Trading Rules Cache

交易规则缓存：LRU + TTL
"""

import time
import logging
from typing import Dict, Any, Optional
from collections import OrderedDict

logger = logging.getLogger(__name__)


class RulesCache:
    """交易规则缓存（LRU + TTL）"""
    
    def __init__(self, ttl_sec: int = 300, max_size: int = 100):
        """初始化规则缓存
        
        Args:
            ttl_sec: 缓存过期时间（秒）
            max_size: 最大缓存条目数
        """
        self.ttl_sec = ttl_sec
        self.max_size = max_size
        self._cache: OrderedDict[str, tuple[float, Dict[str, Any]]] = OrderedDict()
        # 格式：symbol -> (expire_time, rules_dict)
    
    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取规则
        
        Args:
            symbol: 交易对
            
        Returns:
            规则字典，如果过期或不存在则返回None
        """
        if symbol not in self._cache:
            return None
        
        expire_time, rules = self._cache[symbol]
        
        # 检查是否过期
        if time.time() > expire_time:
            logger.debug(f"[RulesCache] Rules expired for {symbol}")
            del self._cache[symbol]
            return None
        
        # 移动到末尾（LRU）
        self._cache.move_to_end(symbol)
        
        return rules
    
    def put(self, symbol: str, rules: Dict[str, Any]) -> None:
        """存储规则
        
        Args:
            symbol: 交易对
            rules: 规则字典
        """
        expire_time = time.time() + self.ttl_sec
        
        # 如果已存在，先删除
        if symbol in self._cache:
            del self._cache[symbol]
        
        # 如果超过最大大小，删除最旧的条目
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        
        # 添加新条目
        self._cache[symbol] = (expire_time, rules)
        logger.debug(f"[RulesCache] Cached rules for {symbol}, expires at {expire_time}")
    
    def invalidate(self, symbol: Optional[str] = None) -> None:
        """使规则失效
        
        Args:
            symbol: 交易对，None表示清除所有缓存
        """
        if symbol is None:
            self._cache.clear()
            logger.debug("[RulesCache] All rules invalidated")
        elif symbol in self._cache:
            del self._cache[symbol]
            logger.debug(f"[RulesCache] Rules invalidated for {symbol}")
    
    def clear(self) -> None:
        """清除所有缓存"""
        self._cache.clear()

