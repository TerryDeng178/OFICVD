# -*- coding: utf-8 -*-
"""Signal v2 Integration Tests

测试 signal/v2 端到端集成：CoreAlgorithm → SignalWriterV2 → JSONL/SQLite
"""

import pytest
import tempfile
import shutil
import json
import sqlite3
import time
from pathlib import Path

from src.alpha_core.signals.core_algo import CoreAlgorithm


class TestSignalV2Integration:
    """Signal v2 端到端集成测试"""
    
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
    
    def test_e2e_signal_v2_flow(self, temp_dir, core_config):
        """测试端到端流程：特征行 → CoreAlgorithm → signal/v2 → JSONL/SQLite"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 测试多个信号
        test_cases = [
            {
                "name": "OK signal",
                "row": {
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
                },
                "expected_confirm": True,
                "expected_decision_code": "OK",
            },
            {
                "name": "FAIL_GATING signal",
                "row": {
                    "ts_ms": now_ms - 500,
                    "symbol": "ETHUSDT",  # 使用不同的 symbol，避免触发冷却
                    "z_ofi": 1.0,  # 低于阈值
                    "z_cvd": 1.0,  # 低于阈值
                    "div_type": None,
                    "consistency": 0.5,
                    "spread_bps": 5.0,
                    "lag_sec": 0.5,
                    "warmup": False,
                    "reason_codes": [],
                },
                "expected_confirm": False,
                "expected_decision_code": "FAIL_GATING",
            },
            {
                "name": "COOLDOWN signal",
                "row": {
                    "ts_ms": now_ms,
                    "symbol": "BTCUSDT",  # 使用相同的 symbol，触发冷却
                    "z_ofi": 2.0,
                    "z_cvd": 1.5,
                    "div_type": None,
                    "consistency": 0.5,
                    "spread_bps": 5.0,
                    "lag_sec": 0.5,
                    "warmup": False,
                    "reason_codes": [],
                },
                "expected_confirm": False,
                "expected_decision_code": "COOLDOWN",
            },
        ]
        
        decisions = []
        for test_case in test_cases:
            decision = algo.process_feature_row(test_case["row"])
            assert decision is not None
            assert decision["confirm"] == test_case["expected_confirm"]
            assert decision["decision_code"] == test_case["expected_decision_code"]
            decisions.append(decision)
        
        algo.close()
        
        # 验证 JSONL 文件
        jsonl_dir = temp_dir / "ready" / "signal"
        jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
        assert len(jsonl_files) > 0
        
        jsonl_signals = []
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        jsonl_signals.append(json.loads(line))
        
        # 验证 SQLite 数据库
        db_path = temp_dir / "signals_v2.db"
        assert db_path.exists()
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM signals")
        sqlite_count = cursor.fetchone()[0]
        conn.close()
        
        # 验证数据一致性（JSONL 和 SQLite 应该有相同数量的信号）
        assert len(jsonl_signals) == sqlite_count
        assert len(jsonl_signals) == len(test_cases)
        
        # 验证每个信号都有必需的字段
        for signal in jsonl_signals:
            assert "schema_version" in signal
            assert signal["schema_version"] == "signal/v2"
            assert "signal_id" in signal
            assert "confirm" in signal
            assert "gating" in signal
            assert "decision_code" in signal
            assert "config_hash" in signal
            assert "run_id" in signal
    
    def test_signal_v2_schema_validation(self, temp_dir, core_config):
        """测试 Schema 校验：随机生成 100 条信号，验证 100% 通过"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        import random
        now_ms = int(time.time() * 1000)
        
        # 生成 100 条随机信号
        signals = []
        for i in range(100):
            row = {
                "ts_ms": now_ms - (100 - i) * 1000,
                "symbol": random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT"]),
                "z_ofi": random.uniform(-3.0, 3.0),
                "z_cvd": random.uniform(-3.0, 3.0),
                "div_type": random.choice([None, "bull", "bear"]),
                "consistency": random.uniform(0.0, 1.0),
                "spread_bps": random.uniform(0.0, 30.0),
                "lag_sec": random.uniform(0.0, 5.0),
                "warmup": random.choice([True, False]),
                "reason_codes": [],
            }
            
            decision = algo.process_feature_row(row)
            if decision:
                signals.append(decision)
        
        algo.close()
        
        # 验证所有信号都符合 Schema
        assert len(signals) > 0
        
        # 验证 JSONL 文件中的所有信号都符合 Schema
        jsonl_dir = temp_dir / "ready" / "signal"
        jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
        
        schema_errors = []
        for jsonl_file in jsonl_files:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    if line.strip():
                        try:
                            signal = json.loads(line)
                            # 验证必需字段
                            required_fields = [
                                "schema_version", "ts_ms", "symbol", "signal_id",
                                "score", "side_hint", "regime", "gating", "confirm",
                                "cooldown_ms", "expiry_ms", "decision_code",
                                "config_hash", "run_id",
                            ]
                            for field in required_fields:
                                if field not in signal:
                                    schema_errors.append(f"{jsonl_file}:{line_num} missing {field}")
                            
                            # 验证约束：confirm=true ⇒ gating=1 && decision_code=OK
                            if signal.get("confirm") is True:
                                if signal.get("gating") != 1:
                                    schema_errors.append(f"{jsonl_file}:{line_num} confirm=true but gating={signal.get('gating')}")
                                if signal.get("decision_code") != "OK":
                                    schema_errors.append(f"{jsonl_file}:{line_num} confirm=true but decision_code={signal.get('decision_code')}")
                        except json.JSONDecodeError as e:
                            schema_errors.append(f"{jsonl_file}:{line_num} JSON decode error: {e}")
        
        # 应该没有 Schema 错误
        assert len(schema_errors) == 0, f"Schema validation errors: {schema_errors}"
    
    def test_signal_v2_dual_sink_consistency(self, temp_dir, core_config):
        """测试双 Sink 一致性：JSONL 和 SQLite 数据应该一致"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        
        # 生成多条信号
        for i in range(10):
            row = {
                "ts_ms": now_ms - (10 - i) * 1000,
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
                        signal_id = signal["signal_id"]
                        jsonl_signals[signal_id] = signal
        
        # 读取 SQLite 数据
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
        
        # 验证每个信号在两个 Sink 中都存在且一致
        for signal_id in jsonl_signals:
            assert signal_id in sqlite_signals
            jsonl_signal = jsonl_signals[signal_id]
            sqlite_signal = sqlite_signals[signal_id]
            
            assert jsonl_signal["symbol"] == sqlite_signal["symbol"]
            assert jsonl_signal["ts_ms"] == sqlite_signal["ts_ms"]
            assert jsonl_signal["confirm"] == sqlite_signal["confirm"]
            assert jsonl_signal["decision_code"] == sqlite_signal["decision_code"]

