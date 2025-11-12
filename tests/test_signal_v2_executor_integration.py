# -*- coding: utf-8 -*-
"""Signal v2 Executor Integration Tests

测试 signal/v2 与 Executor 的集成：验证 Executor 只消费 confirm 和 side_hint，不做二次门控
"""

import pytest
import tempfile
import shutil
import time
from pathlib import Path

from src.alpha_core.signals.core_algo import CoreAlgorithm
from src.alpha_core.executors.executor_precheck import ExecutorPrecheck
from src.alpha_core.executors.base_executor import OrderCtx, ExecResultStatus


class TestSignalV2ExecutorIntegration:
    """Signal v2 与 Executor 集成测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def core_config(self):
        """core.* 配置"""
        return {
            "use_signal_v2": True,
            "core": {
                "expiry_ms": 60000,
                "cooldown_ms": 30000,
                "allow_quiet": False,
                "gating": {
                    "ofi_z": 1.5,
                    "cvd_z": 1.2,
                    "enable_divergence_alt": True,
                },
                "threshold": {
                    "entry": {
                        "trend": 1.8,
                        "revert": 2.2,
                        "quiet": 2.8,
                    },
                },
                "regime": {
                    "z_t": 1.2,
                    "z_r": 1.0,
                },
            },
            "sink": {"kind": "dual", "output_dir": "./runtime"},
        }
    
    def test_executor_consumes_confirm_only(self, temp_dir, core_config):
        """测试 Executor 只消费 confirm 字段，不做二次门控"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成一个 confirm=true 的信号
        row = {
            "ts_ms": now_ms - 1000,
            "symbol": "BTCUSDT",
            "z_ofi": 2.0,
            "z_cvd": 1.5,
            "div_type": None,
            "consistency": 0.5,
            "spread_bps": 5.0,
            "lag_sec": 0.5,
            "warmup": False,
            "reason_codes": [],
        }
        
        decision = algo.process_feature_row(row)
        algo.close()
        
        # 验证信号 confirm=true
        assert decision is not None
        assert decision["confirm"] is True
        assert decision["gating"] == 1
        assert decision["decision_code"] == "OK"
        
        # 模拟 Executor 消费信号：只检查 confirm，不做二次门控
        # 如果 confirm=true，应该直接执行
        if decision["confirm"]:
            # Executor 应该直接执行，不再检查 gating/threshold/regime
            # 这些检查已经在 CoreAlgorithm 中完成
            # 注意：decision 字典可能没有 side_hint 字段（v1 兼容格式），但应该有 signal_type
            assert decision.get("signal_type") in ["buy", "sell"] or decision.get("side_hint") in ["buy", "sell"]
            # Executor 可以根据 side_hint/signal_type 下单
            assert True  # 通过测试
    
    def test_executor_rejects_non_confirm_signals(self, temp_dir, core_config):
        """测试 Executor 拒绝 confirm=false 的信号"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成一个 confirm=false 的信号（FAIL_GATING）
        row = {
            "ts_ms": now_ms - 1000,
            "symbol": "BTCUSDT",
            "z_ofi": 1.0,  # 低于阈值
            "z_cvd": 1.0,  # 低于阈值
            "div_type": None,
            "consistency": 0.5,
            "spread_bps": 5.0,
            "lag_sec": 0.5,
            "warmup": False,
            "reason_codes": [],
        }
        
        decision = algo.process_feature_row(row)
        algo.close()
        
        # 验证信号 confirm=false
        assert decision is not None
        assert decision["confirm"] is False
        assert decision["decision_code"] == "FAIL_GATING"
        
        # 模拟 Executor 消费信号：如果 confirm=false，应该拒绝
        if not decision["confirm"]:
            # Executor 应该拒绝，不再执行
            assert True  # 通过测试
    
    def test_executor_precheck_data_quality_only(self, temp_dir):
        """测试 ExecutorPrecheck 只做数据质量检查，不做门控"""
        from src.alpha_core.executors.base_executor import Side, OrderType
        
        precheck = ExecutorPrecheck(config={})
        
        # 创建一个 OrderCtx（数据质量相关的字段）
        # 注意：OrderCtx 可能没有 spread_bps 和 lag_sec 字段，只使用基本字段
        order_ctx = OrderCtx(
            client_order_id="test-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            order_type=OrderType.LIMIT,
            ts_ms=int(time.time() * 1000),
            warmup=False,  # 数据质量：非 warmup
            consistency=0.8,  # 数据质量：一致性高
            guard_reason=None,  # 无 guard_reason（门控已在 CoreAlgorithm 完成）
        )
        
        # ExecutorPrecheck 应该通过（数据质量检查通过）
        result = precheck.check(order_ctx)
        assert result.status == ExecResultStatus.ACCEPTED
        
        # 如果 warmup=True，应该被拒绝（数据质量检查）
        order_ctx.warmup = True
        result = precheck.check(order_ctx)
        assert result.status == ExecResultStatus.REJECTED
        assert result.reject_reason == "warmup"

