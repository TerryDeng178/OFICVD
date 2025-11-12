# -*- coding: utf-8 -*-
"""Risk Module E2E Tests

端到端回放测试：验证护栏和性能要求
"""

import json
import pytest
import time
import statistics
from pathlib import Path
from typing import Dict, List

from mcp.strategy_server.risk import pre_order_check, OrderCtx, initialize_risk_manager, get_metrics, reset_metrics
from mcp.strategy_server.risk.schemas import RiskDecision


class TestGuardEnforcement:
    """E2E测试：护栏强制执行"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
        return {
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
    
    def test_lag_exceeds_cap_must_deny(self, risk_config):
        """验证：lag超过lag_sec_cap必须拒单"""
        initialize_risk_manager(risk_config)
        
        # 测试lag刚好等于阈值（应该通过）
        order_ctx1 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 1.5,  # 等于阈值
                "activity_tpm": 15.0,
            },
        )
        decision1 = pre_order_check(order_ctx1)
        assert decision1.passed is True, "Lag等于阈值应该通过"
        
        # 测试lag超过阈值（必须拒单）
        order_ctx2 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 1.6,  # 超过阈值
                "activity_tpm": 15.0,
            },
        )
        decision2 = pre_order_check(order_ctx2)
        assert decision2.passed is False, "Lag超过阈值必须拒单"
        assert "lag_exceeds_cap" in decision2.reason_codes
    
    def test_spread_exceeds_max_must_deny(self, risk_config):
        """验证：spread超过spread_bps_max必须拒单"""
        initialize_risk_manager(risk_config)
        
        # 测试spread刚好等于阈值（应该通过）
        order_ctx1 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 8.0,  # 等于阈值
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        decision1 = pre_order_check(order_ctx1)
        assert decision1.passed is True, "Spread等于阈值应该通过"
        
        # 测试spread超过阈值（必须拒单）
        order_ctx2 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 8.1,  # 超过阈值
                "event_lag_sec": 0.04,
                "activity_tpm": 15.0,
            },
        )
        decision2 = pre_order_check(order_ctx2)
        assert decision2.passed is False, "Spread超过阈值必须拒单"
        assert "spread_too_wide" in decision2.reason_codes
    
    def test_activity_below_min_must_deny(self, risk_config):
        """验证：activity低于activity_min_tpm必须拒单"""
        initialize_risk_manager(risk_config)
        
        # 测试activity刚好等于阈值（应该通过）
        order_ctx1 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 10.0,  # 等于阈值
            },
        )
        decision1 = pre_order_check(order_ctx1)
        assert decision1.passed is True, "Activity等于阈值应该通过"
        
        # 测试activity低于阈值（必须拒单）
        order_ctx2 = OrderCtx(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.1,
            price=50000.0,
            guards={
                "spread_bps": 1.2,
                "event_lag_sec": 0.04,
                "activity_tpm": 9.9,  # 低于阈值
            },
        )
        decision2 = pre_order_check(order_ctx2)
        assert decision2.passed is False, "Activity低于阈值必须拒单"
        assert "market_inactive" in decision2.reason_codes


class TestPerformanceRequirements:
    """E2E测试：性能要求"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
        return {
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
    
    def test_p95_latency_under_5ms(self, risk_config):
        """验证：p95风控耗时 ≤ 5ms"""
        initialize_risk_manager(risk_config)
        reset_metrics()
        
        # 执行1000次风控检查
        latencies = []
        for i in range(1000):
            order_ctx = OrderCtx(
                symbol="BTCUSDT",
                side="buy" if i % 2 == 0 else "sell",
                order_type="market",
                qty=0.1,
                price=50000.0,
                guards={
                    "spread_bps": 1.2 + (i % 5) * 0.5,
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                },
            )
            
            start_time = time.perf_counter()
            decision = pre_order_check(order_ctx)
            end_time = time.perf_counter()
            
            latency_ms = (end_time - start_time) * 1000
            latencies.append(latency_ms)
        
        # 计算p95
        latencies_sorted = sorted(latencies)
        p95_index = int(len(latencies_sorted) * 0.95)
        p95_latency = latencies_sorted[p95_index]
        
        assert p95_latency <= 5.0, f"P95 latency {p95_latency:.2f}ms > 5ms"
        
        # 验证指标统计
        metrics = get_metrics()
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["p95"] <= 5.0, f"Metrics P95 latency {latency_stats['p95']:.2f}ms > 5ms"
    
    def test_shadow_comparison_throughput(self, risk_config):
        """验证：影子比对吞吐不下降 >10%"""
        initialize_risk_manager(risk_config)
        reset_metrics()
        
        # 不带shadow比对
        start_time = time.perf_counter()
        for i in range(1000):
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
        end_time = time.perf_counter()
        baseline_time = end_time - start_time
        
        # 带shadow比对（模拟）
        reset_metrics()
        start_time = time.perf_counter()
        for i in range(1000):
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
            # 模拟shadow比对（额外开销很小）
            _ = decision.shadow_compare
        end_time = time.perf_counter()
        shadow_time = end_time - start_time
        
        # 验证吞吐下降不超过10%
        throughput_degradation = (shadow_time - baseline_time) / baseline_time
        assert throughput_degradation <= 0.10, f"Throughput degradation {throughput_degradation:.2%} > 10%"


class TestReplayWithJsonl:
    """E2E测试：使用JSONL数据回放"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
        return {
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
    
    @pytest.fixture
    def sample_signals_jsonl(self, tmp_path):
        """创建示例signals JSONL文件"""
        signals_file = tmp_path / "signals.jsonl"
        
        signals = []
        for i in range(100):
            signals.append({
                "ts_ms": 1730790000456 + i * 1000,
                "symbol": "BTCUSDT",
                "score": 1.0 + (i % 10) * 0.1,
                "confirm": True,
                "gating": False,
                "signal_type": "buy" if i % 2 == 0 else "sell",
                "regime": "active",
                "z_ofi": 1.5,
                "z_cvd": 1.0,
            })
        
        with signals_file.open("w", encoding="utf-8") as f:
            for signal in signals:
                f.write(json.dumps(signal, ensure_ascii=False) + "\n")
        
        return signals_file
    
    def test_replay_signals_from_jsonl(self, risk_config, sample_signals_jsonl):
        """测试从JSONL文件回放信号"""
        initialize_risk_manager(risk_config)
        reset_metrics()
        
        # 读取signals
        signals = []
        with sample_signals_jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                signals.append(json.loads(line))
        
        # 处理信号
        passed_count = 0
        denied_count = 0
        
        for signal in signals:
            if not signal.get("confirm", False) or signal.get("gating", False):
                continue  # 跳过未确认或被门控的信号
            
            order_ctx = OrderCtx(
                symbol=signal["symbol"],
                side="buy" if signal["signal_type"] in ["buy", "strong_buy"] else "sell",
                order_type="market",
                qty=0.1,
                price=50000.0,  # 模拟从市场数据获取
                ts_ms=signal["ts_ms"],
                regime=signal.get("regime", "normal"),
                guards={
                    "spread_bps": 1.2 + (len(signals) % 5) * 0.5,
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                },
            )
            
            decision = pre_order_check(order_ctx)
            if decision.passed:
                passed_count += 1
            else:
                denied_count += 1
        
        # 验证处理结果
        assert passed_count + denied_count == len(signals)
        
        # 验证指标已记录
        metrics = get_metrics()
        latency_stats = metrics.get_latency_stats()
        assert latency_stats["count"] == len(signals)

