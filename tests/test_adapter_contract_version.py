# -*- coding: utf-8 -*-
"""Contract Version Tests

测试契约版本显式化和配置决策快照功能
"""

import pytest
import tempfile
import shutil
import json
import time
from pathlib import Path

from src.alpha_core.adapters import BacktestAdapter
from src.alpha_core.executors.adapter_integration import make_adapter


class TestContractVersion:
    """契约版本测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_jsonl_contract_version(self, temp_dir):
        """测试 JSONL 事件包含契约版本"""
        from src.alpha_core.adapters.adapter_event_sink import JsonlAdapterEventSink
        
        sink = JsonlAdapterEventSink(temp_dir)
        sink.write_event(
            ts_ms=int(time.time() * 1000),
            mode="backtest",
            symbol="BTCUSDT",
            event="submit",
            meta={"contract_ver": "v1", "run_id": "test123"},
        )
        sink.close()
        
        # 读取事件
        event_dir = temp_dir / "ready" / "adapter" / "BTCUSDT"
        jsonl_files = list(event_dir.glob("*.jsonl"))
        assert len(jsonl_files) > 0
        
        with jsonl_files[0].open("r", encoding="utf-8") as f:
            event = json.loads(f.read().strip())
        
        # 验证契约版本
        assert event.get("contract_ver") == "v1"
        assert event.get("meta", {}).get("run_id") == "test123"
    
    def test_sqlite_contract_version(self, temp_dir):
        """测试 SQLite 事件包含契约版本"""
        from src.alpha_core.adapters.adapter_event_sink import SqliteAdapterEventSink
        
        sink = SqliteAdapterEventSink(temp_dir, db_name="test_contract.db")
        sink.write_event(
            ts_ms=int(time.time() * 1000),
            mode="backtest",
            symbol="BTCUSDT",
            event="submit",
            meta={"contract_ver": "v1", "run_id": "test123"},
        )
        sink.close()
        
        # 查询数据库
        import sqlite3
        conn = sqlite3.connect(str(temp_dir / "test_contract.db"))
        cursor = conn.execute("SELECT contract_ver FROM adapter_events WHERE symbol = ?", ("BTCUSDT",))
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        assert row[0] == "v1"
    
    def test_adapter_run_id_session_id(self, temp_dir):
        """测试适配器自动生成 run_id 和 session_id"""
        config = {
            "adapter": {"impl": "backtest"},
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
        }
        
        adapter = BacktestAdapter(config)
        
        # 验证追踪ID已生成
        assert hasattr(adapter, "_run_id")
        assert hasattr(adapter, "_session_id")
        assert len(adapter._run_id) == 8
        assert len(adapter._session_id) == 8
    
    def test_impl_decision_event(self, temp_dir):
        """测试配置决策快照事件"""
        # 测试一致配置
        config = {
            "executor": {"mode": "backtest", "output_dir": str(temp_dir)},
            "adapter": {"impl": "backtest"},
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
        }
        
        adapter = make_adapter(config)
        
        # 验证 impl.confirm 事件已记录
        event_dir = temp_dir / "ready" / "adapter" / "SYSTEM"
        if event_dir.exists():
            jsonl_files = list(event_dir.glob("*.jsonl"))
            assert len(jsonl_files) > 0
            
            events = []
            for jsonl_file in jsonl_files:
                with jsonl_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            events.append(json.loads(line))
            
            # 查找 impl.confirm 事件
            confirm_events = [e for e in events if e.get("event") == "impl.confirm"]
            assert len(confirm_events) > 0
            
            # 验证配置信息
            event = confirm_events[0]
            assert event.get("meta", {}).get("executor_mode") == "backtest"
            assert event.get("meta", {}).get("adapter_impl") == "backtest"
            assert event.get("contract_ver") == "v1"

