# -*- coding: utf-8 -*-
"""Signal v2 End-to-End Smoke Tests

测试 signal/v2 与 A2/A3 的端到端集成：CoreAlgorithm → Executor → BaseAdapter
"""

import pytest
import tempfile
import shutil
import time
import json
import sqlite3
from pathlib import Path

from src.alpha_core.signals.core_algo import CoreAlgorithm
from src.alpha_core.executors.executor_precheck import ExecutorPrecheck
from src.alpha_core.executors.base_executor import OrderCtx, ExecResultStatus, Side, OrderType


class TestSignalV2E2ESmoke:
    """Signal v2 端到端冒烟测试"""
    
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
    
    def test_e2e_signal_to_executor_flow(self, temp_dir, core_config):
        """测试端到端流程：信号生成 → Executor 消费 → 订单提交"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 1. 生成 confirm=true 的信号
        row = {
            "ts_ms": now_ms - 1000,
            "symbol": "BTCUSDT",
            "z_ofi": 2.0,
            "z_cvd": 1.5,
            "div_type": None,
            "consistency": 0.8,
            "spread_bps": 5.0,
            "lag_sec": 0.5,
            "warmup": False,
            "reason_codes": [],
        }
        
        decision = algo.process_feature_row(row)
        algo.close()
        
        # 2. 验证信号 confirm=true
        assert decision is not None
        assert decision["confirm"] is True
        assert decision["gating"] == 1
        assert decision["decision_code"] == "OK"
        
        # 3. 模拟 Executor 消费信号：只检查 confirm，不做二次门控
        if decision["confirm"]:
            # Executor 应该直接执行，不再检查 gating/threshold/regime
            # 这些检查已经在 CoreAlgorithm 中完成
            
            # 4. 创建 OrderCtx（基于信号）
            signal_type = decision.get("signal_type", "buy" if decision.get("score", 0) > 0 else "sell")
            side = Side.BUY if signal_type == "buy" else Side.SELL
            
            order_ctx = OrderCtx(
                client_order_id=f"test-{now_ms}",
                symbol=decision["symbol"],
                side=side,
                qty=0.001,
                price=50000.0,
                order_type=OrderType.MARKET,
                ts_ms=now_ms,
                warmup=row.get("warmup", False),
                consistency=row.get("consistency"),
                guard_reason=None,  # 门控已在 CoreAlgorithm 完成
            )
            
            # 5. ExecutorPrecheck 应该通过（数据质量检查通过）
            precheck = ExecutorPrecheck(config={})
            result = precheck.check(order_ctx)
            assert result.status == ExecResultStatus.ACCEPTED
            
            # 6. 验证信号已写入 JSONL 和 SQLite
            jsonl_dir = temp_dir / "ready" / "signal"
            jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
            assert len(jsonl_files) > 0
            
            db_path = temp_dir / "signals_v2.db"
            assert db_path.exists()
            
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM signals WHERE confirm=1")
            confirm_count = cursor.fetchone()[0]
            conn.close()
            
            assert confirm_count >= 1
    
    def test_e2e_signal_v2_dual_sink_consistency(self, temp_dir, core_config):
        """测试端到端双 Sink 一致性：JSONL 和 SQLite 数据一致"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成多条信号
        test_signals = []
        for i in range(5):
            row = {
                "ts_ms": now_ms - (5 - i) * 1000,
                "symbol": "BTCUSDT",
                "z_ofi": 2.0 if i % 2 == 0 else 1.0,
                "z_cvd": 1.5 if i % 2 == 0 else 1.0,
                "div_type": None,
                "consistency": 0.8,
                "spread_bps": 5.0,
                "lag_sec": 0.5,
                "warmup": False,
                "reason_codes": [],
            }
            decision = algo.process_feature_row(row)
            if decision:
                test_signals.append(decision)
        
        algo.close()
        
        # 验证 JSONL 数据
        jsonl_dir = temp_dir / "ready" / "signal"
        jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
        
        jsonl_signals = {}
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        signal = json.loads(line)
                        signal_id = signal.get("signal_id")
                        if signal_id:
                            jsonl_signals[signal_id] = signal
        
        # 验证 SQLite 数据（v2 使用 signals_v2.db）
        db_path = temp_dir / "signals_v2.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT signal_id, symbol, ts_ms, confirm, decision_code FROM signals")
        sqlite_signals = {}
        for row in cursor.fetchall():
            signal_id = row[0]
            sqlite_signals[signal_id] = {
                "signal_id": row[0],
                "symbol": row[1],
                "ts_ms": row[2],
                "confirm": bool(row[3]),
                "decision_code": row[4],
            }
        conn.close()
        
        # 验证数据一致性
        assert len(jsonl_signals) == len(sqlite_signals)
        assert len(jsonl_signals) == len(test_signals)
        
        # 验证每个信号在两个 Sink 中都存在且一致
        for signal_id in jsonl_signals:
            assert signal_id in sqlite_signals
            jsonl_signal = jsonl_signals[signal_id]
            sqlite_signal = sqlite_signals[signal_id]
            
            assert jsonl_signal["symbol"] == sqlite_signal["symbol"]
            assert jsonl_signal["ts_ms"] == sqlite_signal["ts_ms"]
            assert jsonl_signal["confirm"] == sqlite_signal["confirm"]
            assert jsonl_signal["decision_code"] == sqlite_signal["decision_code"]

        # 契约断言：confirm=true ⇒ gating=1 && decision_code=OK
        per_key_scores = {}
        for signal in jsonl_signals.values():
            if signal.get("confirm"):
                assert signal.get("gating") == 1
                assert signal.get("decision_code") == "OK"

            key = (signal.get("symbol"), signal.get("ts_ms"))
            score_val = signal.get("score")
            try:
                abs_score = abs(float(score_val)) if score_val is not None else 0.0
            except (TypeError, ValueError):
                abs_score = 0.0
            if key in per_key_scores:
                pytest.fail(
                    f"Detected multiple signals for key={key} (scores {per_key_scores[key]} vs {abs_score})"
                )
            per_key_scores[key] = abs_score
    
    def test_e2e_signal_v2_config_hash_consistency(self, temp_dir, core_config):
        """测试端到端 config_hash 一致性：所有信号应该有相同的 config_hash"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成多条信号
        for i in range(3):
            row = {
                "ts_ms": now_ms - (3 - i) * 1000,
                "symbol": "BTCUSDT",
                "z_ofi": 2.0,
                "z_cvd": 1.5,
                "div_type": None,
                "consistency": 0.8,
                "spread_bps": 5.0,
                "lag_sec": 0.5,
                "warmup": False,
                "reason_codes": [],
            }
            algo.process_feature_row(row)
        
        algo.close()
        
        # 验证所有信号的 config_hash 一致
        jsonl_dir = temp_dir / "ready" / "signal"
        jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
        
        config_hashes = set()
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        signal = json.loads(line)
                        config_hash = signal.get("config_hash")
                        if config_hash:
                            config_hashes.add(config_hash)
        
        # 所有信号应该有相同的 config_hash
        assert len(config_hashes) == 1, f"Expected 1 config_hash, got {len(config_hashes)}: {config_hashes}"
        
        # 验证 run_id 也一致
        run_ids = set()
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        signal = json.loads(line)
                        run_id = signal.get("run_id")
                        if run_id:
                            run_ids.add(run_id)
        
        assert len(run_ids) == 1, f"Expected 1 run_id, got {len(run_ids)}: {run_ids}"

