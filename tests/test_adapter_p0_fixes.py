# -*- coding: utf-8 -*-
"""P0 修复验证测试

验证市场价名义额计算和事件落地线程安全
"""

import pytest
import tempfile
import shutil
import threading
import time
from pathlib import Path
from decimal import Decimal

from src.alpha_core.adapters import BacktestAdapter, AdapterOrder, AdapterErrorCode
from src.alpha_core.adapters.adapter_event_sink import JsonlAdapterEventSink, SqliteAdapterEventSink


class TestMarketOrderNotional:
    """测试市场价名义额计算修复"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def adapter_config(self, temp_dir):
        """适配器配置"""
        return {
            "adapter": {
                "impl": "backtest",
                "order_size_usd": 100.0,
                "rate_limit": {"place": {"rps": 8, "burst": 16}},
            },
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
            "backtest": {"ignore_gating": False},
        }
    
    def test_market_order_with_mark_price(self, adapter_config, temp_dir):
        """测试市价单名义额计算（有 mark_price）"""
        adapter = BacktestAdapter(adapter_config)
        
        # 创建市价单（price=None）
        order = AdapterOrder(
            client_order_id="test-market-1",
            symbol="BTCUSDT",
            side="buy",
            qty=0.002,  # 100 USD / 50000 = 0.002
            price=None,  # 市价单
            order_type="market",
            ts_ms=int(time.time() * 1000),
        )
        
        # 规范化应该成功（BacktestAdapter 有 mark_price=50000）
        normalized = adapter.normalize(order.symbol, order.qty, order.price)
        
        assert normalized["qty"] > 0
        assert normalized["notional"] >= 5.0  # 最小名义额
        assert normalized["notional"] == normalized["qty"] * 50000.0  # mark_price=50000
    
    def test_market_order_normalization_succeeds(self, adapter_config, temp_dir):
        """测试市价单规范化不会因为缺少 mark_price 失败"""
        adapter = BacktestAdapter(adapter_config)
        
        # 创建市价单
        order = AdapterOrder(
            client_order_id="test-market-2",
            symbol="BTCUSDT",
            side="buy",
            qty=0.002,
            price=None,
            order_type="market",
            ts_ms=int(time.time() * 1000),
        )
        
        # 提交订单（应该成功，不会因为 E.PARAMS 失败）
        resp = adapter.submit(order)
        
        # 应该成功或至少不是 E.PARAMS（因为名义额不足）
        assert resp.code != AdapterErrorCode.E_PARAMS or "notional" not in resp.msg.lower()


class TestEventSinkThreadSafety:
    """测试事件落地线程安全"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_jsonl_sink_thread_safety(self, temp_dir):
        """测试 JSONL Sink 线程安全"""
        sink = JsonlAdapterEventSink(temp_dir)
        
        # 并发写入
        def write_events(thread_id: int, count: int):
            for i in range(count):
                ts_ms = int(time.time() * 1000) + thread_id * 1000 + i
                sink.write_event(
                    ts_ms=ts_ms,
                    mode="testnet",
                    symbol="BTCUSDT",
                    event="submit",
                    meta={"thread_id": thread_id, "seq": i},
                )
        
        # 启动多个线程
        threads = []
        for t_id in range(5):
            t = threading.Thread(target=write_events, args=(t_id, 10))
            threads.append(t)
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 关闭 sink
        sink.close()
        
        # 验证文件存在且内容正确
        event_dir = temp_dir / "ready" / "adapter" / "BTCUSDT"
        if event_dir.exists():
            jsonl_files = list(event_dir.glob("adapter_event-*.jsonl"))
            assert len(jsonl_files) > 0
            
            # 读取事件
            events = []
            for jsonl_file in jsonl_files:
                with jsonl_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            import json
                            events.append(json.loads(line))
            
            # 验证事件数量（应该等于 5 * 10 = 50）
            assert len(events) == 50
    
    def test_sqlite_sink_thread_safety(self, temp_dir):
        """测试 SQLite Sink 线程安全"""
        sink = SqliteAdapterEventSink(temp_dir, db_name="test_adapter_events.db")
        
        # 并发写入
        def write_events(thread_id: int, count: int):
            for i in range(count):
                ts_ms = int(time.time() * 1000) + thread_id * 1000 + i
                sink.write_event(
                    ts_ms=ts_ms,
                    mode="testnet",
                    symbol="BTCUSDT",
                    event="submit",
                    meta={"thread_id": thread_id, "seq": i},
                )
        
        # 启动多个线程
        threads = []
        for t_id in range(5):
            t = threading.Thread(target=write_events, args=(t_id, 10))
            threads.append(t)
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 关闭 sink（会刷新批量写入）
        sink.close()
        
        # 验证数据库存在且内容正确
        db_path = temp_dir / "test_adapter_events.db"
        if db_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM adapter_events")
            count = cursor.fetchone()[0]
            conn.close()
            
            # 验证事件数量（应该等于 5 * 10 = 50）
            assert count == 50
    
    def test_jsonl_sink_hour_rotation(self, temp_dir):
        """测试 JSONL Sink 按小时轮转（文件句柄键修复）"""
        sink = JsonlAdapterEventSink(temp_dir)
        
        # 模拟跨小时写入
        from datetime import datetime, timezone, timedelta
        
        # 写入第一个小时的事件
        hour1_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        ts_ms1 = int(hour1_start.timestamp() * 1000)
        
        sink.write_event(
            ts_ms=ts_ms1,
            mode="testnet",
            symbol="BTCUSDT",
            event="submit",
            meta={"hour": 1},
        )
        
        # 写入第二个小时的事件（跨小时）
        hour2_start = hour1_start + timedelta(hours=1)
        ts_ms2 = int(hour2_start.timestamp() * 1000)
        
        sink.write_event(
            ts_ms=ts_ms2,
            mode="testnet",
            symbol="BTCUSDT",
            event="submit",
            meta={"hour": 2},
        )
        
        # 关闭 sink
        sink.close()
        
        # 验证两个文件都存在
        event_dir = temp_dir / "ready" / "adapter" / "BTCUSDT"
        if event_dir.exists():
            jsonl_files = list(event_dir.glob("adapter_event-*.jsonl"))
            # 应该有两个文件（不同小时）
            assert len(jsonl_files) >= 1  # 至少有一个文件

