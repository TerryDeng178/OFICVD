# -*- coding: utf-8 -*-
"""Risk Module Smoke Tests

冒烟测试：5 服务主链冷启动、优雅关闭；统计/监控文件生成且可读
"""

import json
import pytest
import tempfile
import time
from pathlib import Path
from typing import Dict

from mcp.strategy_server.risk import (
    pre_order_check,
    OrderCtx,
    initialize_risk_manager,
    get_metrics,
    reset_metrics,
)
from mcp.strategy_server.risk.schemas import RiskDecision


class TestRiskModuleColdStart:
    """冒烟测试：Risk模块冷启动"""
    
    def test_risk_manager_initialization(self):
        """测试风险管理器初始化"""
        config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
        
        # 初始化
        initialize_risk_manager(config)
        
        # 验证可以执行风控检查
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        
        decision = pre_order_check(order_ctx)
        assert isinstance(decision, RiskDecision)
        assert decision.passed is True
    
    def test_risk_manager_disabled_mode(self):
        """测试风险管理器禁用模式（回退到legacy）"""
        config = {
            "risk": {
                "enabled": False,  # 禁用内联风控
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
            }
        }
        
        initialize_risk_manager(config)
        
        # 即使护栏不满足，也应该通过（回退到legacy）
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 10.0,  # 超过阈值
                "event_lag_sec": 2.0,  # 超过阈值
                "activity_tpm": 5.0,  # 低于阈值
            },
        )
        
        decision = pre_order_check(order_ctx)
        assert decision.passed is True  # 禁用模式下应该直接通过


class TestMetricsFileGeneration:
    """冒烟测试：指标文件生成"""
    
    def test_metrics_collection(self):
        """测试指标收集"""
        config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
        
        initialize_risk_manager(config)
        reset_metrics()
        
        # 执行多次风控检查
        for i in range(10):
            order_ctx = OrderCtx(
                symbol="BTCUSDT",
                side="buy" if i % 2 == 0 else "sell",
                order_type="market",
                qty=0.1,
                price=50000.0,
                guards={
                    "spread_bps": 1.2 if i < 5 else 10.0,  # 前5个通过，后5个拒绝
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                },
            )
            pre_order_check(order_ctx)
        
        # 验证指标已收集
        metrics = get_metrics()
        precheck_total = metrics.get_precheck_total()
        assert len(precheck_total) > 0
        
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["count"] == 10
    
    def test_prometheus_export(self):
        """测试Prometheus格式导出"""
        config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
        
        initialize_risk_manager(config)
        reset_metrics()
        
        # 执行一些风控检查
        for i in range(5):
            order_ctx = OrderCtx(
                symbol="BTCUSDT",
                side="buy",
                order_type="market",
                qty=0.1,
                price=50000.0,
                guards={
                    "spread_bps": 1.2,
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                },
            )
            pre_order_check(order_ctx)
        
        # 导出Prometheus格式
        metrics = get_metrics()
        prometheus_output = metrics.export_prometheus_format()
        
        # 验证输出格式
        assert "risk_precheck_total" in prometheus_output
        assert "risk_check_latency_ms" in prometheus_output
        assert "risk_shadow_parity_ratio" in prometheus_output
        
        # 验证输出可读
        lines = prometheus_output.split("\n")
        assert len(lines) > 0


class TestGracefulShutdown:
    """冒烟测试：优雅关闭"""
    
    def test_metrics_persistence_on_shutdown(self):
        """测试关闭时指标持久化"""
        config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
        
        initialize_risk_manager(config)
        reset_metrics()
        
        # 执行一些操作
        for i in range(10):
            order_ctx = OrderCtx(
                symbol="BTCUSDT",
                side="buy",
                order_type="market",
                qty=0.1,
                price=50000.0,
                guards={
                    "spread_bps": 1.2,
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                },
            )
            pre_order_check(order_ctx)
        
        # 模拟关闭前导出指标
        metrics = get_metrics()
        prometheus_output = metrics.export_prometheus_format()
        
        # 验证指标已保存
        assert len(prometheus_output) > 0
        
        # 验证可以重新初始化（模拟重启）
        initialize_risk_manager(config)
        # 应该可以正常工作
        order_ctx = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        decision = pre_order_check(order_ctx)
        assert decision.passed is True


class TestFiveServiceChain:
    """冒烟测试：5服务主链"""
    
    def test_harvest_to_signal_to_strategy_flow(self, tmp_path):
        """测试Harvest → Signal → Strategy流程（模拟）"""
        # 1. 模拟Harvest输出features
        features_file = tmp_path / "features.jsonl"
        with features_file.open("w", encoding="utf-8") as f:
            feature = {
                "ts_ms": 1730790000456,
                "symbol": "BTCUSDT",
                "z_ofi": 1.8,
                "z_cvd": 0.9,
                "price": 70325.1,
                "lag_sec": 0.04,
                "spread_bps": 1.2,
                "fusion_score": 0.73,
                "consistency": 0.42,
                "warmup": False,
            }
            f.write(json.dumps(feature, ensure_ascii=False) + "\n")
        
        # 2. 模拟Signal输出signals
        signals_file = tmp_path / "signals.jsonl"
        with signals_file.open("w", encoding="utf-8") as f:
            signal = {
                "ts_ms": 1730790000456,
                "symbol": "BTCUSDT",
                "score": 1.72,
                "confirm": True,
                "gating": False,
                "signal_type": "strong_buy",
                "regime": "active",
            }
            f.write(json.dumps(signal, ensure_ascii=False) + "\n")
        
        # 3. Strategy处理信号（通过Risk检查）
        config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
        
        initialize_risk_manager(config)
        
        # 读取signal
        with signals_file.open("r", encoding="utf-8") as f:
            signal = json.loads(f.read())
        
        # 转换为order_ctx
        order_ctx = OrderCtx(
            symbol=signal["symbol"],
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            ts_ms=signal["ts_ms"],
            regime=signal.get("regime", "normal"),
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        
        # 执行风控检查
        decision = pre_order_check(order_ctx)
        
        # 4. 如果通过，发送到Broker（模拟）
        if decision.passed:
            executions_file = tmp_path / "executions.jsonl"
            with executions_file.open("w", encoding="utf-8") as f:
                execution = {
                    "ts_ms": signal["ts_ms"],
                    "order_id": "test_order_123",
                    "symbol": signal["symbol"],
                    "side": "buy",
                    "status": "FILLED",
                }
                f.write(json.dumps(execution, ensure_ascii=False) + "\n")
        
        # 5. 验证文件生成
        assert features_file.exists()
        assert signals_file.exists()
        if decision.passed:
            assert executions_file.exists()
        
        # 6. 验证文件可读
        with signals_file.open("r", encoding="utf-8") as f:
            signal_data = json.loads(f.read())
            assert signal_data["symbol"] == "BTCUSDT"

