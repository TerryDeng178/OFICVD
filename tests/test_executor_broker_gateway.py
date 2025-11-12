# -*- coding: utf-8 -*-
"""Broker Gateway MCP Integration Tests

测试TestnetExecutor和LiveExecutor与Broker Gateway MCP的集成
"""

import json
import pytest
import tempfile
from pathlib import Path

from alpha_core.executors import TestnetExecutor, LiveExecutor, Order, Side, OrderType
from alpha_core.executors.broker_gateway_client import BrokerGatewayClient


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def broker_config():
    """Broker配置"""
    return {
        "name": "binance-futures",
        "testnet": True,
        "dry_run": True,
        "mock_enabled": True,
        "mock_output_path": "./runtime/mock_orders.jsonl",
        "mock_sample_rate": 0.2,
    }


class TestBrokerGatewayClient:
    """测试Broker Gateway客户端"""
    
    def test_client_init(self, broker_config, temp_output_dir):
        """测试客户端初始化"""
        broker_config["mock_output_path"] = str(temp_output_dir / "mock_orders.jsonl")
        client = BrokerGatewayClient(broker_config)
        
        assert client.name == "binance-futures"
        assert client.testnet is True
        assert client.dry_run is True
        assert client.mock_enabled is True
    
    def test_submit_order_mock(self, broker_config, temp_output_dir):
        """测试Mock模式提交订单"""
        broker_config["mock_output_path"] = str(temp_output_dir / "mock_orders.jsonl")
        client = BrokerGatewayClient(broker_config)
        
        order = Order(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        
        broker_order_id = client.submit_order(order)
        
        assert broker_order_id.startswith("MOCK-")
        assert order.client_order_id in client.order_map
        
        # 检查Mock订单文件
        mock_file = temp_output_dir / "mock_orders.jsonl"
        assert mock_file.exists()
        
        # 读取并验证订单
        with mock_file.open("r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            assert len(lines) == 1
            
            mock_order = json.loads(lines[0])
            assert mock_order["order_id"] == broker_order_id
            assert mock_order["symbol"] == "BTCUSDT"
            assert mock_order["side"] == "BUY"
            assert mock_order["status"] == "FILLED"
    
    def test_fetch_fills(self, broker_config, temp_output_dir):
        """测试获取成交记录"""
        broker_config["mock_output_path"] = str(temp_output_dir / "mock_orders.jsonl")
        client = BrokerGatewayClient(broker_config)
        
        order = Order("test-456", "BTCUSDT", Side.BUY, 0.1, ts_ms=1731379200000, metadata={"mid_price": 50000.0})
        client.submit_order(order)
        
        fills = client.fetch_fills()
        assert len(fills) == 1
        assert fills[0].client_order_id == "test-456"
        assert fills[0].qty == 0.1
    
    def test_get_position(self, broker_config, temp_output_dir):
        """测试获取持仓"""
        broker_config["mock_output_path"] = str(temp_output_dir / "mock_orders.jsonl")
        client = BrokerGatewayClient(broker_config)
        
        # 买入
        buy_order = Order("buy-1", "BTCUSDT", Side.BUY, 0.1, ts_ms=1731379200000, metadata={"mid_price": 50000.0})
        client.submit_order(buy_order)
        
        position = client.get_position("BTCUSDT")
        assert position > 0
        
        # 卖出
        sell_order = Order("sell-1", "BTCUSDT", Side.SELL, 0.05, ts_ms=1731379201000, metadata={"mid_price": 51000.0})
        client.submit_order(sell_order)
        
        position = client.get_position("BTCUSDT")
        assert position > 0  # 仍然多头（0.1 - 0.05 = 0.05）


class TestTestnetExecutorWithBrokerGateway:
    """测试TestnetExecutor与Broker Gateway集成"""
    
    def test_submit_with_broker_gateway(self, temp_output_dir):
        """测试通过Broker Gateway提交订单"""
        executor_cfg = {
            "mode": "testnet",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
        }
        
        broker_cfg = {
            "name": "binance-futures",
            "testnet": True,
            "dry_run": True,
            "mock_enabled": True,
            "mock_output_path": str(temp_output_dir / "mock_orders.jsonl"),
        }
        
        executor = TestnetExecutor()
        executor.prepare({
            "executor": executor_cfg,
            "broker": broker_cfg,
            "sink": {"kind": "jsonl", "output_dir": str(temp_output_dir)},
        })
        
        order = Order(
            client_order_id="testnet-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        
        broker_order_id = executor.submit(order)
        
        assert broker_order_id.startswith("MOCK-")
        
        # 检查exec_log.jsonl
        exec_log_dir = temp_output_dir / "ready" / "execlog" / "BTCUSDT"
        if exec_log_dir.exists():
            jsonl_files = list(exec_log_dir.glob("exec_log_*.jsonl"))
            assert len(jsonl_files) > 0
        
        executor.close()
    
    def test_cancel_with_broker_gateway(self, temp_output_dir):
        """测试通过Broker Gateway撤销订单"""
        executor_cfg = {
            "mode": "testnet",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
        }
        
        broker_cfg = {
            "name": "binance-futures",
            "testnet": True,
            "dry_run": True,
            "mock_enabled": True,
            "mock_output_path": str(temp_output_dir / "mock_orders.jsonl"),
        }
        
        executor = TestnetExecutor()
        executor.prepare({
            "executor": executor_cfg,
            "broker": broker_cfg,
            "sink": {"kind": "jsonl", "output_dir": str(temp_output_dir)},
        })
        
        # Mock模式下订单立即成交，无法撤销
        order = Order("testnet-cancel", "BTCUSDT", Side.BUY, 0.1, ts_ms=1731379200000, metadata={"mid_price": 50000.0})
        executor.submit(order)
        
        result = executor.cancel("testnet-cancel")
        assert result is False  # 已成交订单无法撤销
        
        executor.close()


class TestLiveExecutorWithBrokerGateway:
    """测试LiveExecutor与Broker Gateway集成"""
    
    def test_submit_with_broker_gateway(self, temp_output_dir):
        """测试通过Broker Gateway提交订单"""
        executor_cfg = {
            "mode": "live",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
            "max_parallel_orders": 4,
        }
        
        broker_cfg = {
            "name": "binance-futures",
            "testnet": False,
            "dry_run": False,
            "mock_enabled": True,  # 测试时使用Mock
            "mock_output_path": str(temp_output_dir / "live_orders.jsonl"),
        }
        
        executor = LiveExecutor()
        executor.prepare({
            "executor": executor_cfg,
            "broker": broker_cfg,
            "sink": {"kind": "jsonl", "output_dir": str(temp_output_dir)},
            "system": {"run_id": "test-run"},
        })
        
        order = Order(
            client_order_id="live-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        
        broker_order_id = executor.submit(order)
        
        assert broker_order_id.startswith("MOCK-")
        
        # 检查exec_log.jsonl
        exec_log_dir = temp_output_dir / "ready" / "execlog" / "BTCUSDT"
        if exec_log_dir.exists():
            jsonl_files = list(exec_log_dir.glob("exec_log_*.jsonl"))
            assert len(jsonl_files) > 0
        
        executor.close()
    
    def test_max_parallel_orders(self, temp_output_dir):
        """测试并发订单限制"""
        executor_cfg = {
            "mode": "live",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
            "max_parallel_orders": 2,  # 限制为2个
        }
        
        broker_cfg = {
            "name": "binance-futures",
            "mock_enabled": True,
            "mock_output_path": str(temp_output_dir / "live_orders.jsonl"),
        }
        
        executor = LiveExecutor()
        executor.prepare({
            "executor": executor_cfg,
            "broker": broker_cfg,
            "sink": {"kind": "jsonl", "output_dir": str(temp_output_dir)},
            "system": {"run_id": "test-run"},
        })
        
        # 提交2个订单（应该成功）
        order1 = Order("live-1", "BTCUSDT", Side.BUY, 0.1, ts_ms=1731379200000, metadata={"mid_price": 50000.0})
        order2 = Order("live-2", "BTCUSDT", Side.SELL, 0.1, ts_ms=1731379201000, metadata={"mid_price": 51000.0})
        
        executor.submit(order1)
        executor.submit(order2)
        
        # 第3个订单应该失败（超过并发限制）
        order3 = Order("live-3", "BTCUSDT", Side.BUY, 0.1, ts_ms=1731379202000, metadata={"mid_price": 52000.0})
        
        with pytest.raises(RuntimeError, match="Max parallel orders"):
            executor.submit(order3)
        
        executor.close()

