# -*- coding: utf-8 -*-
"""BaseAdapter Unit Tests

BaseAdapter 基础单元测试
"""

import pytest
import time
from pathlib import Path
import tempfile
import shutil

from src.alpha_core.adapters import (
    BaseAdapter,
    AdapterOrder,
    AdapterResp,
    AdapterErrorCode,
    BacktestAdapter,
)
from src.alpha_core.utils import RateLimiter, RetryPolicy, RulesCache


class TestAdapterErrorCode:
    """测试错误码枚举"""
    
    def test_error_codes(self):
        """测试错误码值"""
        assert AdapterErrorCode.OK == "OK"
        assert AdapterErrorCode.E_PARAMS == "E.PARAMS"
        assert AdapterErrorCode.E_RATE_LIMIT == "E.RATE.LIMIT"
        assert AdapterErrorCode.E_NETWORK == "E.NETWORK"


class TestAdapterOrder:
    """测试适配器订单数据结构"""
    
    def test_create_order(self):
        """测试创建订单"""
        order = AdapterOrder(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side="buy",
            qty=0.01,
            price=50000.0,
            order_type="limit",
            tif="GTC",
            ts_ms=int(time.time() * 1000),
        )
        
        assert order.client_order_id == "test-123"
        assert order.symbol == "BTCUSDT"
        assert order.side == "buy"
        assert order.qty == 0.01
        assert order.price == 50000.0
        assert order.order_type == "limit"
        assert order.tif == "GTC"


class TestAdapterResp:
    """测试适配器响应数据结构"""
    
    def test_create_success_resp(self):
        """测试创建成功响应"""
        resp = AdapterResp(
            ok=True,
            code=AdapterErrorCode.OK,
            msg="Order submitted",
            broker_order_id="123456",
        )
        
        assert resp.ok is True
        assert resp.code == AdapterErrorCode.OK
        assert resp.msg == "Order submitted"
        assert resp.broker_order_id == "123456"
    
    def test_create_error_resp(self):
        """测试创建错误响应"""
        resp = AdapterResp(
            ok=False,
            code=AdapterErrorCode.E_PARAMS,
            msg="Invalid quantity",
        )
        
        assert resp.ok is False
        assert resp.code == AdapterErrorCode.E_PARAMS
        assert resp.msg == "Invalid quantity"


class TestBacktestAdapter:
    """测试回测适配器"""
    
    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def config(self, temp_dir):
        """创建测试配置"""
        return {
            "adapter": {
                "impl": "backtest",
                "rate_limit": {
                    "place": {"rps": 8, "burst": 16},
                    "cancel": {"rps": 5, "burst": 10},
                    "query": {"rps": 10, "burst": 20},
                },
                "max_inflight_orders": 32,
                "rules_ttl_sec": 300,
                "idempotency_ttl_sec": 600,
            },
            "sink": {
                "kind": "jsonl",
                "output_dir": str(temp_dir),
            },
            "backtest": {
                "ignore_gating": False,
            },
        }
    
    def test_kind(self, config):
        """测试适配器类型"""
        adapter = BacktestAdapter(config)
        assert adapter.kind() == "backtest"
    
    def test_load_rules(self, config):
        """测试加载交易规则"""
        adapter = BacktestAdapter(config)
        rules = adapter.load_rules("BTCUSDT")
        
        assert "qty_step" in rules
        assert "qty_min" in rules
        assert "price_tick" in rules
        assert "min_notional" in rules
        assert "precision" in rules
    
    def test_normalize(self, config):
        """测试数量/价格规范化"""
        adapter = BacktestAdapter(config)
        
        # 测试规范化
        normalized = adapter.normalize("BTCUSDT", 0.0105, 50000.5)
        
        assert "qty" in normalized
        assert "notional" in normalized
        assert normalized["qty"] > 0
    
    def test_submit_order(self, config):
        """测试提交订单"""
        adapter = BacktestAdapter(config)
        
        order = AdapterOrder(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side="buy",
            qty=0.01,
            ts_ms=int(time.time() * 1000),
        )
        
        resp = adapter.submit(order)
        
        assert resp.ok is True
        assert resp.code == AdapterErrorCode.OK
        assert resp.broker_order_id is not None
    
    def test_cancel_order(self, config):
        """测试撤销订单"""
        adapter = BacktestAdapter(config)
        
        resp = adapter.cancel("BTCUSDT", "test-123")
        
        assert resp.ok is True
        assert resp.code == AdapterErrorCode.OK
    
    def test_is_retriable(self, config):
        """测试可重试判断"""
        adapter = BacktestAdapter(config)
        
        assert adapter.is_retriable(AdapterErrorCode.E_NETWORK) is True
        assert adapter.is_retriable(AdapterErrorCode.E_RATE_LIMIT) is True
        assert adapter.is_retriable(AdapterErrorCode.E_PARAMS) is False
        assert adapter.is_retriable(AdapterErrorCode.E_BROKER_REJECT) is False


class TestRateLimiter:
    """测试速率限制器"""
    
    def test_token_bucket(self):
        """测试令牌桶"""
        from src.alpha_core.utils.rate_limiter import TokenBucket
        
        bucket = TokenBucket(capacity=10, fill_rate=2.0)
        
        # 初始应该能获取10个令牌
        assert bucket.acquire(10) is True
        assert bucket.acquire(1) is False
        
        # 等待一段时间后应该能获取更多令牌
        time.sleep(0.6)  # 应该填充约1.2个令牌
        assert bucket.acquire(1) is True
    
    def test_rate_limiter(self):
        """测试速率限制器"""
        limiter = RateLimiter(place_rps=2.0, place_burst=4)
        
        # 应该能获取4个令牌
        for _ in range(4):
            assert limiter.acquire_place() is True
        
        # 第5个应该被限制
        assert limiter.acquire_place(timeout=0.1) is False


class TestRetryPolicy:
    """测试重试策略"""
    
    def test_retry_policy(self):
        """测试重试策略"""
        policy = RetryPolicy(max_retries=3, base_delay_ms=100, factor=2.0)
        
        assert policy.should_retry(0) is True
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True
        assert policy.should_retry(3) is False
        
        # 测试延迟计算
        delay1 = policy.get_delay_ms(0)
        delay2 = policy.get_delay_ms(1)
        delay3 = policy.get_delay_ms(2)
        
        assert delay1 > 0
        assert delay2 > delay1  # 指数退避
        assert delay3 > delay2


class TestRulesCache:
    """测试规则缓存"""
    
    def test_rules_cache(self):
        """测试规则缓存"""
        cache = RulesCache(ttl_sec=1, max_size=10)
        
        # 存储规则
        cache.put("BTCUSDT", {"qty_step": 0.0001})
        
        # 获取规则
        rules = cache.get("BTCUSDT")
        assert rules is not None
        assert rules["qty_step"] == 0.0001
        
        # 等待过期
        time.sleep(1.1)
        rules = cache.get("BTCUSDT")
        assert rules is None
    
    def test_rules_cache_lru(self):
        """测试LRU淘汰"""
        cache = RulesCache(ttl_sec=3600, max_size=2)
        
        cache.put("BTCUSDT", {"qty_step": 0.0001})
        cache.put("ETHUSDT", {"qty_step": 0.001})
        cache.put("BNBUSDT", {"qty_step": 0.01})  # 应该淘汰BTCUSDT
        
        assert cache.get("BTCUSDT") is None
        assert cache.get("ETHUSDT") is not None
        assert cache.get("BNBUSDT") is not None

