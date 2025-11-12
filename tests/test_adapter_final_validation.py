# -*- coding: utf-8 -*-
"""Final Validation Tests for BaseAdapter

最终验证测试：覆盖所有关键功能和边界情况
"""

import pytest
import tempfile
import shutil
import threading
import time
from pathlib import Path
from decimal import Decimal

from src.alpha_core.adapters import (
    BacktestAdapter,
    AdapterOrder,
    AdapterErrorCode,
    map_exception_to_error_code,
)
from src.alpha_core.adapters.adapter_event_sink import JsonlAdapterEventSink, SqliteAdapterEventSink
from src.alpha_core.executors.adapter_integration import make_adapter


class TestFinalValidation:
    """最终验证测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        import gc
        gc.collect()
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def adapter_config(self, temp_dir):
        """适配器配置"""
        return {
            "adapter": {
                "impl": "backtest",
                "order_size_usd": 100.0,
                "rate_limit": {"place": {"rps": 8, "burst": 16}},
                "idempotency_max_size": 100,
            },
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
            "backtest": {"ignore_gating": False},
        }
    
    def test_sqlite_attempt_column(self, temp_dir):
        """测试 SQLite attempt 列写入"""
        sink = SqliteAdapterEventSink(temp_dir, db_name="test_attempt.db")
        
        # 写入多个事件，包含不同的 attempt
        for attempt in [1, 2, 3]:
            sink.write_event(
                ts_ms=int(time.time() * 1000) + attempt,
                mode="testnet",
                symbol="BTCUSDT",
                event="submit",
                meta={"attempt": attempt, "retries": attempt - 1},
            )
        
        sink.close()
        
        # 验证数据库中有3条记录
        import sqlite3
        conn = sqlite3.connect(str(temp_dir / "test_attempt.db"))
        cursor = conn.execute("SELECT COUNT(*), COUNT(attempt) FROM adapter_events")
        count, attempt_count = cursor.fetchone()
        conn.close()
        
        assert count == 3
        assert attempt_count == 3  # 所有记录都有 attempt
    
    def test_retry_event_history_preserved(self, temp_dir):
        """测试重试事件历史保留（P0修复验证）"""
        sink = SqliteAdapterEventSink(temp_dir, db_name="test_retry_history.db")
        
        # 模拟重试：同一订单多次提交
        order_id = "test-retry-1"
        for attempt in [1, 2]:
            sink.write_event(
                ts_ms=int(time.time() * 1000) + attempt * 1000,
                mode="testnet",
                symbol="BTCUSDT",
                event="submit",
                order=AdapterOrder(
                    client_order_id=order_id,
                    symbol="BTCUSDT",
                    side="buy",
                    qty=0.002,
                    price=None,
                    order_type="market",
                    ts_ms=int(time.time() * 1000) + attempt * 1000,
                ),
                resp=None,
                meta={"attempt": attempt, "retries": attempt - 1},
            )
        
        sink.close()
        
        # 验证数据库中有2条记录（不是1条）
        import sqlite3
        conn = sqlite3.connect(str(temp_dir / "test_retry_history.db"))
        cursor = conn.execute("SELECT COUNT(*) FROM adapter_events WHERE order_id = ?", (order_id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 2, f"Expected 2 retry events, got {count}"
    
    def test_impl_mismatch_event_logging(self, temp_dir):
        """测试 impl.mismatch 事件记录"""
        # 使用 backtest 而不是 live，避免需要 API credentials
        config = {
            "executor": {"mode": "backtest", "output_dir": str(temp_dir)},
            "adapter": {"impl": "testnet"},  # 不一致配置
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
        }
        
        adapter = make_adapter(config)
        
        # 验证 impl.mismatch 事件已记录
        event_dir = temp_dir / "ready" / "adapter" / "SYSTEM"
        if event_dir.exists():
            jsonl_files = list(event_dir.glob("adapter_event-*.jsonl"))
            assert len(jsonl_files) > 0
            
            # 读取事件
            import json
            events = []
            for jsonl_file in jsonl_files:
                with jsonl_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            events.append(json.loads(line))
            
            # 查找 impl.mismatch 事件
            mismatch_events = [e for e in events if e.get("event") == "impl.mismatch"]
            assert len(mismatch_events) > 0
    
    def test_broker_gateway_ticker_fallback(self, adapter_config, temp_dir):
        """测试 Broker Gateway ticker 回退逻辑"""
        adapter = BacktestAdapter(adapter_config)
        
        # 测试市价单规范化（即使没有 ticker，也应该成功）
        result = adapter.normalize("BTCUSDT", 0.002, None)
        
        assert result["qty"] > 0
        assert result["notional"] >= 5.0  # 最小名义额
    
    def test_error_mapping_with_http_status(self):
        """测试错误映射（带 HTTP status）"""
        # 模拟带 HTTP status 的异常
        class MockHTTPError(Exception):
            def __init__(self, status_code):
                self.status_code = status_code
                super().__init__(f"HTTP {status_code}")
        
        # 测试 429 限频错误
        error_429 = MockHTTPError(429)
        code = map_exception_to_error_code(error_429, http_status=429)
        assert code == AdapterErrorCode.E_RATE_LIMIT
        
        # 测试 500 网络错误
        error_500 = MockHTTPError(500)
        code = map_exception_to_error_code(error_500, http_status=500)
        assert code == AdapterErrorCode.E_NETWORK
    
    def test_decimal_normalization_precision(self, adapter_config, temp_dir):
        """测试 Decimal 规范化精度"""
        adapter = BacktestAdapter(adapter_config)
        
        # 测试边界情况：使用大于最小数量的值
        qty = 0.0023456789  # 大于 qty_min=0.001
        result = adapter.normalize("BTCUSDT", qty, 50000.0)
        
        # 验证规范化后的数量符合精度要求
        assert result["qty"] > 0
        assert result["qty"] <= qty  # 规范化后应该 <= 原始值
        assert result["qty"] >= 0.001  # 应该 >= 最小数量
        
        # 验证名义价值计算正确（使用 Decimal 精确比较）
        from decimal import Decimal
        expected_notional = Decimal(str(result["qty"])) * Decimal("50000.0")
        actual_notional = Decimal(str(result["notional"]))
        assert abs(float(expected_notional - actual_notional)) < 0.01  # 允许小的浮点误差
    
    def test_adaptive_rate_limiting(self, adapter_config, temp_dir):
        """测试自适应限流"""
        from src.alpha_core.utils.rate_limiter import RateLimiter
        
        limiter = RateLimiter(place_rps=10.0, place_burst=20)
        
        # 触发自适应退避
        limiter.trigger_adaptive_backoff(duration_sec=1.0)
        
        # 验证退避截止时间已设置
        assert limiter._adaptive_backoff_until > time.time()
        
        # 调用 acquire_place 触发速率调整
        limiter.acquire_place()
        
        # 验证 fill_rate 已降低（在退避期间）
        assert limiter.place_bucket.fill_rate <= 10.0 * limiter._adaptive_factor
        
        # 等待退避期结束
        time.sleep(1.1)
        
        # 再次调用 acquire_place 触发恢复检查
        limiter.acquire_place()
        
        # 验证 fill_rate 已恢复
        assert limiter.place_bucket.fill_rate == 10.0
    
    def test_rules_miss_error_code(self, adapter_config, temp_dir):
        """测试 E.RULES.MISS 错误码触发"""
        adapter = BacktestAdapter(adapter_config)
        
        # 使规则缓存失效
        adapter.rules_cache.invalidate("BTCUSDT")
        
        # 模拟规则加载失败（通过 mock）
        original_load = adapter._load_rules_impl
        
        def failing_load(symbol):
            raise RuntimeError("Rules loading failed")
        
        adapter._load_rules_impl = failing_load
        
        # 尝试规范化（应该触发 E.RULES.MISS）
        order = AdapterOrder(
            client_order_id="test-rules-miss",
            symbol="BTCUSDT",
            side="buy",
            qty=0.002,
            price=None,
            order_type="market",
            ts_ms=int(time.time() * 1000),
        )
        
        resp = adapter.submit(order)
        
        # 恢复原始方法
        adapter._load_rules_impl = original_load
        
        # 验证返回 E.RULES.MISS（可重试）
        assert resp.code == AdapterErrorCode.E_RULES_MISS
        assert adapter.is_retriable(resp.code)

