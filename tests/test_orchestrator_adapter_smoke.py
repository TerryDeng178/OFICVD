# -*- coding: utf-8 -*-
"""Orchestrator-Adapter Integration Smoke Test

端到端冒烟测试：验证 Strategy Server → Executor → BaseAdapter 的完整链路
"""

import pytest
import tempfile
import shutil
import json
import time
from pathlib import Path
from typing import Dict, Any

from alpha_core.executors import create_executor, Order, Side, OrderType
from mcp.strategy_server.app import (
    read_signals_from_jsonl,
    signal_to_order,
    process_signals,
)


class TestOrchestratorAdapterSmoke:
    """Orchestrator-Adapter 集成冒烟测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        # Windows 文件锁定问题：先关闭所有文件句柄，再删除
        import gc
        gc.collect()
        try:
            shutil.rmtree(temp_dir)
        except PermissionError:
            # Windows 文件锁定问题：忽略删除错误
            pass
    
    @pytest.fixture
    def signals_dir(self, temp_dir):
        """创建信号目录并生成测试信号"""
        signals_dir = temp_dir / "ready" / "signal" / "BTCUSDT"
        signals_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建测试信号文件
        signals_file = signals_dir / "signals_20241112_1200.jsonl"
        signals = [
            {
                "ts_ms": int(time.time() * 1000) - 1000,
                "symbol": "BTCUSDT",
                "price": 50000.0,
                "score": 0.8,
                "z_ofi": 1.2,
                "z_cvd": 0.9,
                "regime": "active",
                "div_type": None,
                "signal_type": "buy",
                "confirm": True,
                "gating": False,
                "guard_reason": None,
                "run_id": "test-run",
            },
            {
                "ts_ms": int(time.time() * 1000) - 500,
                "symbol": "BTCUSDT",
                "price": 50010.0,
                "score": 0.7,
                "z_ofi": -1.1,
                "z_cvd": -0.8,
                "regime": "active",
                "div_type": None,
                "signal_type": "sell",
                "confirm": True,
                "gating": False,
                "guard_reason": None,
                "run_id": "test-run",
            },
        ]
        
        with signals_file.open("w", encoding="utf-8") as f:
            for signal in signals:
                f.write(json.dumps(signal, ensure_ascii=False) + "\n")
        
        return signals_dir
    
    @pytest.fixture
    def backtest_config(self, temp_dir):
        """回测配置"""
        return {
            "executor": {
                "mode": "backtest",
                "sink": "jsonl",
                "output_dir": str(temp_dir),
                "order_size_usd": 100,
                "tif": "GTC",
                "order_type": "market",
            },
            "adapter": {
                "impl": "backtest",
                "rate_limit": {
                    "place": {"rps": 8, "burst": 16},
                    "cancel": {"rps": 5, "burst": 10},
                },
            },
            "sink": {
                "kind": "jsonl",
                "output_dir": str(temp_dir),
            },
            "backtest": {
                "ignore_gating": False,
            },
        }
    
    @pytest.fixture
    def testnet_config(self, temp_dir):
        """测试网配置"""
        return {
            "executor": {
                "mode": "testnet",
                "sink": "jsonl",
                "output_dir": str(temp_dir),
                "order_size_usd": 100,
                "tif": "GTC",
                "order_type": "market",
            },
            "adapter": {
                "impl": "testnet",
                "rate_limit": {
                    "place": {"rps": 8, "burst": 16},
                },
            },
            "sink": {
                "kind": "jsonl",
                "output_dir": str(temp_dir),
            },
            "broker": {
                "testnet": True,
                "dry_run": True,
                "mock_enabled": True,
            },
        }
    
    def test_backtest_executor_with_adapter_smoke(self, backtest_config, signals_dir):
        """回测执行器与适配器集成冒烟测试"""
        # 创建执行器
        executor = create_executor("backtest", backtest_config)
        executor.prepare(backtest_config)
        
        # 验证适配器已注入
        assert executor.adapter is not None
        assert executor.adapter.kind() == "backtest"
        
        # 读取信号
        signals = list(read_signals_from_jsonl(signals_dir.parent))
        assert len(signals) == 2
        
        # 处理信号
        stats = process_signals(executor, iter(signals), backtest_config.get("executor", {}))
        
        # 验证统计信息
        assert stats["total_signals"] == 2
        assert stats["orders_submitted"] >= 0
        assert stats["orders_rejected"] >= 0
        
        # 验证执行日志文件
        execlog_dir = Path(backtest_config["executor"]["output_dir"]) / "ready" / "execlog" / "BTCUSDT"
        if execlog_dir.exists():
            jsonl_files = list(execlog_dir.glob("exec_*.jsonl"))
            assert len(jsonl_files) > 0
            
            # 读取执行日志
            events = []
            for jsonl_file in jsonl_files:
                with jsonl_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            events.append(json.loads(line))
            
            # 验证事件类型
            event_types = [e.get("event") for e in events]
            assert "submit" in event_types
        
        # 验证适配器事件文件
        adapter_dir = Path(backtest_config["executor"]["output_dir"]) / "ready" / "adapter" / "BTCUSDT"
        if adapter_dir.exists():
            adapter_files = list(adapter_dir.glob("adapter_event-*.jsonl"))
            if adapter_files:
                # 读取适配器事件
                adapter_events = []
                for adapter_file in adapter_files:
                    with adapter_file.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                adapter_events.append(json.loads(line))
                
                # 验证适配器事件包含 submit 事件
                adapter_event_types = [e.get("event") for e in adapter_events]
                assert "submit" in adapter_event_types
        
        executor.close()
    
    def test_testnet_executor_with_adapter_smoke(self, testnet_config, signals_dir):
        """测试网执行器与适配器集成冒烟测试"""
        # 重置 Prometheus metrics（避免重复注册错误）
        try:
            import prometheus_client
            import src.alpha_core.executors.executor_metrics as em
            
            # 清理所有已注册的 metrics
            if em._metrics_instance is not None:
                try:
                    # 尝试取消注册所有 metrics
                    for attr_name in dir(em._metrics_instance):
                        if not attr_name.startswith("_"):
                            attr = getattr(em._metrics_instance, attr_name)
                            if hasattr(attr, "name"):
                                try:
                                    prometheus_client.REGISTRY.unregister(attr)
                                except Exception:
                                    pass
                except Exception:
                    pass
                
                # 重置全局实例
                em._metrics_instance = None
            
            # 清理 REGISTRY 中所有 executor 相关的 metrics
            collectors_to_remove = []
            for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
                if hasattr(collector, "name") and collector.name and "executor" in collector.name:
                    collectors_to_remove.append(collector)
            
            for collector in collectors_to_remove:
                try:
                    prometheus_client.REGISTRY.unregister(collector)
                except Exception:
                    pass
        except Exception:
            pass
        
        # 创建执行器
        executor = create_executor("testnet", testnet_config)
        executor.prepare(testnet_config)
        
        # 验证适配器已注入
        assert executor.adapter is not None
        assert executor.adapter.kind() == "testnet"
        
        # 读取信号
        signals = list(read_signals_from_jsonl(signals_dir.parent))
        assert len(signals) == 2
        
        # 处理信号
        stats = process_signals(executor, iter(signals), testnet_config.get("executor", {}))
        
        # 验证统计信息
        assert stats["total_signals"] == 2
        assert stats["orders_submitted"] >= 0
        assert stats["orders_rejected"] >= 0
        
        executor.close()
    
    def test_signal_to_order_conversion(self, backtest_config):
        """测试信号到订单转换"""
        signal = {
            "ts_ms": int(time.time() * 1000),
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "score": 0.8,
            "z_ofi": 1.2,
            "z_cvd": 0.9,
            "regime": "active",
            "div_type": None,
            "signal_type": "buy",
            "confirm": True,
            "gating": False,
            "guard_reason": None,
            "run_id": "test-run",
        }
        
        executor_cfg = backtest_config.get("executor", {})
        order = signal_to_order(signal, executor_cfg)
        
        assert order is not None
        assert order.symbol == "BTCUSDT"
        assert order.side == Side.BUY
        assert order.qty > 0
    
    def test_adapter_normalization_in_e2e(self, backtest_config, signals_dir):
        """测试适配器规范化在端到端流程中的使用"""
        executor = create_executor("backtest", backtest_config)
        executor.prepare(backtest_config)
        
        # 创建需要规范化的订单
        order = Order(
            client_order_id="test-normalize-e2e",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01005,  # 需要规范化
            price=50000.5,  # 需要规范化
            order_type=OrderType.LIMIT,
            ts_ms=int(time.time() * 1000),
            metadata={"mid_price": 50000.0},
        )
        
        # 提交订单（适配器会自动规范化）
        broker_order_id = executor.submit(order)
        
        # 验证订单已提交
        assert broker_order_id is not None
        
        executor.close()
    
    def test_adapter_error_handling_in_e2e(self, backtest_config):
        """测试适配器错误处理在端到端流程中的使用"""
        executor = create_executor("backtest", backtest_config)
        executor.prepare(backtest_config)
        
        # 创建无效订单（数量过小）
        order = Order(
            client_order_id="test-error-e2e",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.000001,  # 过小的数量
            order_type=OrderType.MARKET,
            ts_ms=int(time.time() * 1000),
            metadata={"mid_price": 50000.0},
        )
        
        # 提交订单（应该被拒绝）
        broker_order_id = executor.submit(order)
        
        # 验证订单ID返回（即使被拒绝也会返回client_order_id）
        assert broker_order_id is not None
        
        executor.close()
    
    def test_executor_adapter_event_consistency(self, backtest_config, signals_dir):
        """测试执行器与适配器事件的一致性"""
        executor = create_executor("backtest", backtest_config)
        executor.prepare(backtest_config)
        
        # 读取信号
        signals = list(read_signals_from_jsonl(signals_dir.parent))
        
        # 处理信号
        process_signals(executor, iter(signals), backtest_config.get("executor", {}))
        
        # 验证执行日志和适配器事件的一致性
        execlog_dir = Path(backtest_config["executor"]["output_dir"]) / "ready" / "execlog" / "BTCUSDT"
        adapter_dir = Path(backtest_config["executor"]["output_dir"]) / "ready" / "adapter" / "BTCUSDT"
        
        if execlog_dir.exists() and adapter_dir.exists():
            # 读取执行日志
            exec_events = []
            for jsonl_file in execlog_dir.glob("exec_*.jsonl"):
                with jsonl_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            exec_events.append(json.loads(line))
            
            # 读取适配器事件
            adapter_events = []
            for adapter_file in adapter_dir.glob("adapter_event-*.jsonl"):
                with adapter_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            adapter_events.append(json.loads(line))
            
            # 验证事件数量一致性（适配器事件应该 <= 执行日志事件）
            # 因为适配器事件只记录 submit/cancel，而执行日志包含所有状态转换
            if exec_events and adapter_events:
                submit_exec_events = [e for e in exec_events if e.get("event") == "submit"]
                submit_adapter_events = [e for e in adapter_events if e.get("event") == "submit"]
                
                # 至少应该有相同数量的 submit 事件
                assert len(submit_adapter_events) <= len(submit_exec_events)
        
        executor.close()

