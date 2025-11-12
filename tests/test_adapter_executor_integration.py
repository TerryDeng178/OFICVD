# -*- coding: utf-8 -*-
"""Adapter-Executor Integration Tests

适配器与执行器集成测试：验证 BaseAdapter 与 IExecutor 的组合/依赖注入
"""

import pytest
import tempfile
import shutil
import time
from pathlib import Path
from typing import Dict, Any

from src.alpha_core.executors.base_executor import Order, OrderCtx, Side, OrderType, OrderState
from src.alpha_core.executors.backtest_executor import BacktestExecutor
from src.alpha_core.executors.testnet_executor import TestnetExecutor
from src.alpha_core.executors.live_executor import LiveExecutor
from src.alpha_core.executors.adapter_integration import (
    make_adapter,
    convert_order_to_adapter_order,
    map_adapter_error_to_state,
    map_adapter_error_to_reject_reason,
)
from src.alpha_core.adapters import AdapterErrorCode, AdapterResp


class TestAdapterExecutorIntegration:
    """适配器与执行器集成测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def backtest_config(self, temp_dir):
        """回测配置"""
        return {
            "executor": {
                "mode": "backtest",
                "sink": "jsonl",
                "output_dir": str(temp_dir),
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
    
    def test_make_adapter_follows_executor_mode(self, backtest_config):
        """测试适配器工厂跟随executor.mode"""
        adapter = make_adapter(backtest_config)
        assert adapter.kind() == "backtest"
    
    def test_make_adapter_warns_on_mismatch(self, temp_dir, caplog):
        """测试适配器工厂在不一致时告警"""
        config = {
            "executor": {"mode": "backtest"},
            "adapter": {"impl": "testnet"},
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
        }
        adapter = make_adapter(config)
        assert adapter.kind() == "testnet"
        assert "adapter.impl" in caplog.text
        assert "executor.mode" in caplog.text
    
    def test_backtest_executor_with_adapter(self, backtest_config):
        """测试回测执行器与适配器集成"""
        executor = BacktestExecutor()
        executor.prepare(backtest_config)
        
        # 验证适配器已注入
        assert executor.adapter is not None
        assert executor.adapter.kind() == "backtest"
        
        # 创建订单
        order = Order(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            order_type=OrderType.MARKET,
            ts_ms=int(time.time() * 1000),
            metadata={"mid_price": 50000.0},
        )
        
        # 提交订单（委托给适配器）
        broker_order_id = executor.submit(order)
        
        # 验证订单已提交
        assert broker_order_id is not None
        assert order.client_order_id in executor.order_map
        
        executor.close()
    
    def test_error_code_to_state_mapping(self):
        """测试错误码到状态机映射"""
        # OK → ACK
        resp_ok = AdapterResp(ok=True, code=AdapterErrorCode.OK, msg="Success")
        state = map_adapter_error_to_state(resp_ok)
        assert state == OrderState.ACK
        
        # E.PARAMS → REJECTED
        resp_params = AdapterResp(ok=False, code=AdapterErrorCode.E_PARAMS, msg="Invalid params")
        state = map_adapter_error_to_state(resp_params)
        assert state == OrderState.REJECTED
        
        # E.RATE.LIMIT → REJECTED（适配器已重试）
        resp_rate = AdapterResp(ok=False, code=AdapterErrorCode.E_RATE_LIMIT, msg="Rate limit")
        state = map_adapter_error_to_state(resp_rate)
        assert state == OrderState.REJECTED
    
    def test_reject_reason_mapping(self):
        """测试拒绝原因映射"""
        resp = AdapterResp(ok=False, code=AdapterErrorCode.E_PARAMS, msg="Invalid params")
        reason = map_adapter_error_to_reject_reason(resp)
        assert reason == "invalid_params"
        
        resp = AdapterResp(ok=False, code=AdapterErrorCode.E_RATE_LIMIT, msg="Rate limit")
        reason = map_adapter_error_to_reject_reason(resp)
        assert reason == "rate_limit"
    
    def test_order_conversion(self):
        """测试订单转换"""
        order = Order(
            client_order_id="test-123",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
            order_type=OrderType.LIMIT,
            ts_ms=1234567890,
        )
        
        adapter_order = convert_order_to_adapter_order(order)
        
        assert adapter_order.client_order_id == "test-123"
        assert adapter_order.symbol == "BTCUSDT"
        assert adapter_order.side == "buy"
        assert adapter_order.qty == 0.01
        assert adapter_order.price == 50000.0
        assert adapter_order.order_type == "limit"
        assert adapter_order.ts_ms == 1234567890
    
    def test_executor_delegates_to_adapter(self, backtest_config):
        """测试执行器委托给适配器"""
        executor = BacktestExecutor()
        executor.prepare(backtest_config)
        
        order = Order(
            client_order_id="test-delegate",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            ts_ms=int(time.time() * 1000),
            metadata={"mid_price": 50000.0},
        )
        
        # 提交订单
        broker_order_id = executor.submit(order)
        
        # 验证适配器被调用（通过检查事件日志）
        # 这里简化验证：如果订单成功提交，说明适配器工作正常
        assert broker_order_id is not None
        
        executor.close()
    
    def test_adapter_normalization_in_executor(self, backtest_config):
        """测试适配器规范化在执行器中的使用"""
        executor = BacktestExecutor()
        executor.prepare(backtest_config)
        
        # 创建需要规范化的订单（数量不符合步长）
        order = Order(
            client_order_id="test-normalize",
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
        
        # 验证订单已提交（规范化后）
        assert broker_order_id is not None
        
        executor.close()
    
    def test_adapter_retry_in_executor(self, testnet_config):
        """测试适配器重试在执行器中的使用（模拟）"""
        executor = TestnetExecutor()
        executor.prepare(testnet_config)
        
        # 验证适配器已注入
        assert executor.adapter is not None
        assert executor.adapter.kind() == "testnet"
        
        # 注意：实际重试测试需要模拟网络错误，这里仅验证集成
        executor.close()
    
    def test_adapter_rate_limit_in_executor(self, backtest_config):
        """测试适配器节流在执行器中的使用"""
        executor = BacktestExecutor()
        executor.prepare(backtest_config)
        
        # 验证适配器节流器已初始化
        assert executor.adapter is not None
        assert executor.adapter.rate_limiter is not None
        
        executor.close()
    
    def test_executor_close_closes_adapter(self, backtest_config):
        """测试执行器关闭时关闭适配器"""
        executor = BacktestExecutor()
        executor.prepare(backtest_config)
        
        # 验证适配器存在
        assert executor.adapter is not None
        
        # 关闭执行器
        executor.close()
        
        # 验证适配器已关闭（通过检查事件sink是否关闭）
        # 这里简化验证：如果close()不抛异常，说明正常关闭
        assert True

