# -*- coding: utf-8 -*-
"""时间源提供器

支持wall-clock和sim-time两种时间源，确保回测determinism
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class TimeProvider(ABC):
    """时间源抽象接口"""
    
    @abstractmethod
    def now_ms(self) -> int:
        """获取当前时间戳（毫秒）
        
        Returns:
            时间戳（毫秒）
        """
        pass
    
    @abstractmethod
    def now_sec(self) -> float:
        """获取当前时间戳（秒，浮点数）
        
        Returns:
            时间戳（秒）
        """
        pass
    
    @abstractmethod
    def sleep(self, seconds: float) -> None:
        """睡眠指定时间
        
        Args:
            seconds: 睡眠时间（秒）
        """
        pass


class WallClockTimeProvider(TimeProvider):
    """墙钟时间提供器（实时交易使用）"""
    
    def __init__(self):
        """初始化墙钟时间提供器"""
        logger.info("[WallClockTimeProvider] Initialized")
    
    def now_ms(self) -> int:
        """获取当前墙钟时间（毫秒）"""
        return int(time.time() * 1000)
    
    def now_sec(self) -> float:
        """获取当前墙钟时间（秒）"""
        return time.time()
    
    def sleep(self, seconds: float) -> None:
        """真实睡眠"""
        time.sleep(seconds)


class SimTimeProvider(TimeProvider):
    """模拟时间提供器（回测使用，确保determinism）"""
    
    def __init__(self, initial_ts_ms: int = 0):
        """初始化模拟时间提供器
        
        Args:
            initial_ts_ms: 初始时间戳（毫秒）
        """
        self._current_ts_ms = initial_ts_ms
        logger.info(f"[SimTimeProvider] Initialized with initial_ts_ms={initial_ts_ms}")
    
    def now_ms(self) -> int:
        """获取当前模拟时间（毫秒）"""
        return self._current_ts_ms
    
    def now_sec(self) -> float:
        """获取当前模拟时间（秒）"""
        return self._current_ts_ms / 1000.0
    
    def set_time(self, ts_ms: int) -> None:
        """设置模拟时间
        
        Args:
            ts_ms: 时间戳（毫秒）
        """
        self._current_ts_ms = ts_ms
    
    def advance(self, delta_ms: int) -> None:
        """推进模拟时间
        
        Args:
            delta_ms: 时间增量（毫秒）
        """
        self._current_ts_ms += delta_ms
    
    def sleep(self, seconds: float) -> None:
        """模拟睡眠（只推进时间，不实际等待）
        
        Args:
            seconds: 睡眠时间（秒）
        """
        delta_ms = int(seconds * 1000)
        self.advance(delta_ms)


class DeterministicRng:
    """确定性随机数生成器（基于种子，确保可复现）"""
    
    def __init__(self, seed: Optional[int] = None):
        """初始化确定性随机数生成器
        
        Args:
            seed: 随机种子（None表示使用系统时间）
        """
        import random
        self._rng = random.Random(seed)
        self._seed = seed
        logger.info(f"[DeterministicRng] Initialized with seed={seed}")
    
    def random(self) -> float:
        """生成[0.0, 1.0)区间的随机浮点数"""
        return self._rng.random()
    
    def uniform(self, a: float, b: float) -> float:
        """生成[a, b)区间的均匀分布随机数
        
        Args:
            a: 下界
            b: 上界
            
        Returns:
            随机数
        """
        return self._rng.uniform(a, b)
    
    def randint(self, a: int, b: int) -> int:
        """生成[a, b]区间的随机整数
        
        Args:
            a: 下界
            b: 上界
            
        Returns:
            随机整数
        """
        return self._rng.randint(a, b)
    
    def choice(self, seq):
        """从序列中随机选择一个元素
        
        Args:
            seq: 序列
            
        Returns:
            随机选择的元素
        """
        return self._rng.choice(seq)
    
    def gauss(self, mu: float, sigma: float) -> float:
        """生成高斯分布随机数
        
        Args:
            mu: 均值
            sigma: 标准差
            
        Returns:
            随机数
        """
        return self._rng.gauss(mu, sigma)
    
    def get_seed(self) -> Optional[int]:
        """获取随机种子"""
        return self._seed
    
    def reset(self, seed: Optional[int] = None) -> None:
        """重置随机数生成器（使用新种子）
        
        Args:
            seed: 新种子（None表示使用当前种子）
        """
        import random
        if seed is not None:
            self._seed = seed
        self._rng = random.Random(self._seed)
        logger.info(f"[DeterministicRng] Reset with seed={self._seed}")


def create_time_provider(provider_type: str, initial_ts_ms: Optional[int] = None) -> TimeProvider:
    """创建时间提供器
    
    Args:
        provider_type: 提供器类型（wall_clock/sim_time）
        initial_ts_ms: 初始时间戳（仅sim_time使用）
        
    Returns:
        TimeProvider实例
    """
    if provider_type == "wall_clock":
        return WallClockTimeProvider()
    elif provider_type == "sim_time":
        return SimTimeProvider(initial_ts_ms or 0)
    else:
        raise ValueError(f"Unknown time provider type: {provider_type}")


def create_rng(seed: Optional[int] = None) -> DeterministicRng:
    """创建确定性随机数生成器
    
    Args:
        seed: 随机种子
        
    Returns:
        DeterministicRng实例
    """
    return DeterministicRng(seed)

