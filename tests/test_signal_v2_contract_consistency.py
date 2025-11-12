# -*- coding: utf-8 -*-
"""Signal v2 Contract Consistency Tests

TASK-A4 修复7: CI 守护 - 契约一致性断言用例
"""

import pytest
import tempfile
import shutil
import json
import sqlite3
import time
from pathlib import Path

from src.alpha_core.signals.core_algo import CoreAlgorithm
from src.alpha_core.signals.signal_schema import SignalV2, DecisionCode


class TestSignalV2ContractConsistency:
    """Signal v2 契约一致性测试"""
    
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
    
    def test_confirm_constraint_v2(self, temp_dir, core_config):
        """TASK-A4 修复7: 验证 confirm=true ⇒ gating=1 && decision_code=OK"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成 confirm=true 的信号
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
        
        # 验证约束
        assert decision is not None
        if decision.get("confirm") is True:
            assert decision.get("gating") == 1, f"confirm=true requires gating=1, got {decision.get('gating')}"
            assert decision.get("decision_code") == DecisionCode.OK.value, f"confirm=true requires decision_code=OK, got {decision.get('decision_code')}"
        
        # 验证 JSONL 文件中的约束
        jsonl_dir = temp_dir / "ready" / "signal"
        jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
        
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        signal = json.loads(line)
                        if signal.get("confirm") is True:
                            assert signal.get("gating") == 1, f"JSONL: confirm=true requires gating=1, got {signal.get('gating')}"
                            assert signal.get("decision_code") == DecisionCode.OK.value, f"JSONL: confirm=true requires decision_code=OK, got {signal.get('decision_code')}"
        
        # 验证 SQLite 数据库中的约束
        db_path = temp_dir / "signals_v2.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT confirm, gating, decision_code FROM signals WHERE confirm=1")
            for row in cursor.fetchall():
                confirm, gating, decision_code = row
                assert gating == 1, f"SQLite: confirm=true requires gating=1, got {gating}"
                assert decision_code == DecisionCode.OK.value, f"SQLite: confirm=true requires decision_code=OK, got {decision_code}"
            conn.close()
    
    def test_jsonl_sqlite_column_consistency(self, temp_dir, core_config):
        """TASK-A4 修复7: 验证 JSONL 和 SQLite 的列/枚举一致性"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成多条信号
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
            algo.process_feature_row(row)
        
        algo.close()
        
        # 读取 JSONL 数据
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
        
        # 读取 SQLite 数据
        db_path = temp_dir / "signals_v2.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT signal_id, symbol, ts_ms, confirm, gating, decision_code, regime FROM signals")
        sqlite_signals = {}
        for row in cursor.fetchall():
            signal_id = row[0]
            sqlite_signals[signal_id] = {
                "signal_id": row[0],
                "symbol": row[1],
                "ts_ms": row[2],
                "confirm": bool(row[3]),
                "gating": row[4],
                "decision_code": row[5],
                "regime": row[6],
            }
        conn.close()
        
        # 验证数据一致性
        assert len(jsonl_signals) == len(sqlite_signals), f"JSONL count ({len(jsonl_signals)}) != SQLite count ({len(sqlite_signals)})"
        
        # 验证每个信号在两个 Sink 中都存在且一致
        for signal_id in jsonl_signals:
            assert signal_id in sqlite_signals, f"Signal {signal_id} not found in SQLite"
            jsonl_signal = jsonl_signals[signal_id]
            sqlite_signal = sqlite_signals[signal_id]
            
            # 验证关键字段一致性
            assert jsonl_signal["symbol"] == sqlite_signal["symbol"]
            assert jsonl_signal["ts_ms"] == sqlite_signal["ts_ms"]
            assert jsonl_signal["confirm"] == sqlite_signal["confirm"]
            assert jsonl_signal["gating"] == sqlite_signal["gating"]
            assert jsonl_signal["decision_code"] == sqlite_signal["decision_code"]
            assert jsonl_signal["regime"] == sqlite_signal["regime"]
    
    def test_config_hash_consistency_same_run(self, temp_dir, core_config):
        """TASK-A4 修复7: 验证同 run_id 下 config_hash 不变"""
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
        run_ids = set()
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        signal = json.loads(line)
                        config_hash = signal.get("config_hash")
                        run_id = signal.get("run_id")
                        if config_hash:
                            config_hashes.add(config_hash)
                        if run_id:
                            run_ids.add(run_id)
        
        # 所有信号应该有相同的 config_hash 和 run_id
        assert len(config_hashes) == 1, f"Expected 1 config_hash, got {len(config_hashes)}: {config_hashes}"
        assert len(run_ids) == 1, f"Expected 1 run_id, got {len(run_ids)}: {run_ids}"

