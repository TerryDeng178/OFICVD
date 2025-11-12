# -*- coding: utf-8 -*-
"""测试时间源提供器

验证wall-clock和sim-time时间源，以及确定性随机数生成器
"""
import pytest
import time

from src.alpha_core.executors.time_provider import (
    WallClockTimeProvider,
    SimTimeProvider,
    DeterministicRng,
    create_time_provider,
    create_rng,
)


class TestWallClockTimeProvider:
    """测试墙钟时间提供器"""
    
    def test_now_ms(self):
        """测试获取当前时间（毫秒）"""
        provider = WallClockTimeProvider()
        
        ts1 = provider.now_ms()
        time.sleep(0.01)  # 等待10ms
        ts2 = provider.now_ms()
        
        assert ts2 > ts1
        assert ts2 - ts1 >= 10  # 至少10ms
    
    def test_now_sec(self):
        """测试获取当前时间（秒）"""
        provider = WallClockTimeProvider()
        
        ts1 = provider.now_sec()
        time.sleep(0.01)
        ts2 = provider.now_sec()
        
        assert ts2 > ts1
    
    def test_sleep(self):
        """测试真实睡眠"""
        provider = WallClockTimeProvider()
        
        start = time.time()
        provider.sleep(0.1)
        elapsed = time.time() - start
        
        assert elapsed >= 0.1


class TestSimTimeProvider:
    """测试模拟时间提供器"""
    
    def test_now_ms(self):
        """测试获取模拟时间（毫秒）"""
        provider = SimTimeProvider(initial_ts_ms=1000)
        
        assert provider.now_ms() == 1000
    
    def test_set_time(self):
        """测试设置模拟时间"""
        provider = SimTimeProvider(initial_ts_ms=1000)
        
        provider.set_time(2000)
        assert provider.now_ms() == 2000
    
    def test_advance(self):
        """测试推进模拟时间"""
        provider = SimTimeProvider(initial_ts_ms=1000)
        
        provider.advance(500)
        assert provider.now_ms() == 1500
        
        provider.advance(300)
        assert provider.now_ms() == 1800
    
    def test_sleep(self):
        """测试模拟睡眠（只推进时间）"""
        provider = SimTimeProvider(initial_ts_ms=1000)
        
        start = time.time()
        provider.sleep(0.1)  # 模拟睡眠100ms
        elapsed = time.time() - start
        
        assert provider.now_ms() == 1100  # 时间已推进
        assert elapsed < 0.01  # 实际没有等待


class TestDeterministicRng:
    """测试确定性随机数生成器"""
    
    def test_deterministic_with_seed(self):
        """测试相同种子生成相同序列"""
        rng1 = DeterministicRng(seed=42)
        rng2 = DeterministicRng(seed=42)
        
        # 生成相同序列
        seq1 = [rng1.random() for _ in range(10)]
        seq2 = [rng2.random() for _ in range(10)]
        
        assert seq1 == seq2
    
    def test_different_seeds_different_sequences(self):
        """测试不同种子生成不同序列"""
        rng1 = DeterministicRng(seed=42)
        rng2 = DeterministicRng(seed=43)
        
        seq1 = [rng1.random() for _ in range(10)]
        seq2 = [rng2.random() for _ in range(10)]
        
        assert seq1 != seq2
    
    def test_uniform(self):
        """测试均匀分布随机数"""
        rng = DeterministicRng(seed=42)
        
        for _ in range(100):
            value = rng.uniform(0.0, 1.0)
            assert 0.0 <= value < 1.0
    
    def test_randint(self):
        """测试随机整数"""
        rng = DeterministicRng(seed=42)
        
        for _ in range(100):
            value = rng.randint(1, 10)
            assert 1 <= value <= 10
    
    def test_choice(self):
        """测试随机选择"""
        rng = DeterministicRng(seed=42)
        
        seq = [1, 2, 3, 4, 5]
        for _ in range(100):
            value = rng.choice(seq)
            assert value in seq
    
    def test_gauss(self):
        """测试高斯分布"""
        rng = DeterministicRng(seed=42)
        
        values = [rng.gauss(0.0, 1.0) for _ in range(1000)]
        # 检查均值接近0
        mean = sum(values) / len(values)
        assert abs(mean) < 0.1
    
    def test_reset(self):
        """测试重置随机数生成器"""
        rng = DeterministicRng(seed=42)
        
        seq1 = [rng.random() for _ in range(5)]
        
        rng.reset(seed=42)
        seq2 = [rng.random() for _ in range(5)]
        
        assert seq1 == seq2


class TestFactoryFunctions:
    """测试工厂函数"""
    
    def test_create_time_provider_wall_clock(self):
        """测试创建墙钟时间提供器"""
        provider = create_time_provider("wall_clock")
        assert isinstance(provider, WallClockTimeProvider)
    
    def test_create_time_provider_sim_time(self):
        """测试创建模拟时间提供器"""
        provider = create_time_provider("sim_time", initial_ts_ms=1000)
        assert isinstance(provider, SimTimeProvider)
        assert provider.now_ms() == 1000
    
    def test_create_rng(self):
        """测试创建随机数生成器"""
        rng = create_rng(seed=42)
        assert isinstance(rng, DeterministicRng)
        assert rng.get_seed() == 42


class TestDeterminism:
    """测试可复现性"""
    
    def test_sim_time_determinism(self):
        """测试模拟时间确定性"""
        provider1 = SimTimeProvider(initial_ts_ms=1000)
        provider2 = SimTimeProvider(initial_ts_ms=1000)
        
        # 执行相同操作
        provider1.advance(100)
        provider2.advance(100)
        
        assert provider1.now_ms() == provider2.now_ms()
    
    def test_rng_determinism(self):
        """测试随机数生成器确定性"""
        rng1 = DeterministicRng(seed=42)
        rng2 = DeterministicRng(seed=42)
        
        # 执行相同操作序列
        values1 = [rng1.random() for _ in range(10)]
        values2 = [rng2.random() for _ in range(10)]
        
        assert values1 == values2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

