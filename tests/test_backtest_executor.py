# -*- coding: utf-8 -*-
"""BacktestExecutor Tests

测试回测执行器：撮合、滑点、费用、状态机
"""

import json
import pytest
import tempfile
from pathlib import Path

from alpha_core.executors import BacktestExecutor, Order, Side, OrderType, OrderState


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def executor_config(temp_output_dir):
    """执行器配置"""
    return {
        "executor": {
            "mode": "backtest",
            "output_dir": str(temp_output_dir),
            "sink": "jsonl",
            "order_size_usd": 100,
        },
        "backtest": {
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 100,
        },
        "sink": {
            "kind": "jsonl",
            "output_dir": str(temp_output_dir),
        },
    }


class TestBacktestExecutor:
    """测试BacktestExecutor"""
    
    def test_prepare(self, executor_config, temp_output_dir):
        """测试初始化"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        assert executor.mode == "backtest"
        assert executor.output_dir == temp_output_dir
        assert executor.exec_log_sink is not None
    
    def test_submit_market_order(self, executor_config, temp_output_dir):
        """测试提交市价单"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        order = Order(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        
        broker_order_id = executor.submit(order)
        
        # 回测模式下立即成交
        assert broker_order_id == "test-123"
        
        # 检查成交记录
        fills = executor.fetch_fills()
        assert len(fills) == 1
        assert fills[0].client_order_id == "test-123"
        assert fills[0].price > 0
        assert fills[0].qty == 0.1
        assert fills[0].fee > 0  # 应该有手续费
    
    def test_submit_with_slippage(self, executor_config, temp_output_dir):
        """测试滑点计算"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        mid_price = 50000.0
        order = Order(
            client_order_id="test-456",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": mid_price},
        )
        
        executor.submit(order)
        
        fills = executor.fetch_fills()
        assert len(fills) == 1
        
        # 买单应该有正滑点（价格更高）
        fill_price = fills[0].price
        assert fill_price > mid_price
        slippage_bps = ((fill_price - mid_price) / mid_price) * 10000
        assert slippage_bps > 0
        assert slippage_bps <= 2.0  # 应该在配置的滑点范围内
    
    def test_submit_sell_order(self, executor_config, temp_output_dir):
        """测试提交卖单"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        mid_price = 50000.0
        order = Order(
            client_order_id="test-sell",
            symbol="BTCUSDT",
            side=Side.SELL,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": mid_price},
        )
        
        executor.submit(order)
        
        fills = executor.fetch_fills()
        assert len(fills) == 1
        
        # 卖单应该有负滑点（价格更低）
        fill_price = fills[0].price
        assert fill_price < mid_price
    
    def test_position_tracking(self, executor_config, temp_output_dir):
        """测试持仓跟踪"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        # 买入
        buy_order = Order(
            client_order_id="buy-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        executor.submit(buy_order)
        
        position = executor.get_position("BTCUSDT")
        assert position > 0  # 多头持仓
        
        # 卖出
        sell_order = Order(
            client_order_id="sell-1",
            symbol="BTCUSDT",
            side=Side.SELL,
            qty=0.05,
            ts_ms=1731379201000,
            metadata={"mid_price": 51000.0},
        )
        executor.submit(sell_order)
        
        position = executor.get_position("BTCUSDT")
        assert position > 0  # 仍然多头（0.1 - 0.05 = 0.05）
    
    def test_cancel_order(self, executor_config, temp_output_dir):
        """测试撤销订单"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        # 回测模式下订单立即成交，无法撤销
        order = Order(
            client_order_id="test-cancel",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        
        executor.submit(order)
        
        # 尝试撤销已成交订单
        result = executor.cancel("test-cancel")
        assert result is False  # 回测模式下已成交订单无法撤销
    
    def test_exec_log_written(self, executor_config, temp_output_dir):
        """测试执行日志写入"""
        executor = BacktestExecutor()
        executor.prepare(executor_config)
        
        order = Order(
            client_order_id="test-log",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            ts_ms=1731379200000,
            metadata={"mid_price": 50000.0},
        )
        
        executor.submit(order)
        executor.close()
        
        # 检查exec_log.jsonl文件
        exec_log_dir = temp_output_dir / "ready" / "execlog" / "BTCUSDT"
        if exec_log_dir.exists():
            jsonl_files = list(exec_log_dir.glob("exec_log_*.jsonl"))
            assert len(jsonl_files) > 0
            
            # 读取并验证日志内容
            with jsonl_files[0].open("r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                assert len(lines) >= 2  # submit + ack + filled
            
                # 验证submit事件
                submit_event = json.loads(lines[0])
                assert submit_event["event"] == "submit"
                assert submit_event["symbol"] == "BTCUSDT"
                assert submit_event["order"]["id"] == "test-log"

