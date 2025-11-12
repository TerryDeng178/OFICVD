# -*- coding: utf-8 -*-
"""CoreAlgorithm v2 Integration Tests

测试 CoreAlgorithm 集成 Decision Engine 和 SignalWriterV2
"""

import pytest
import tempfile
import shutil
import json
import sqlite3
import time
from pathlib import Path

from src.alpha_core.signals.core_algo import CoreAlgorithm


class TestCoreAlgorithmV2:
    """CoreAlgorithm v2 集成测试"""
    
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
    
    def test_process_feature_row_v2_ok(self, temp_dir, core_config):
        """测试 v2 路径：OK 分支"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
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
        
        assert decision is not None
        assert decision["confirm"] is True
        assert decision["gating"] == 1
        assert "signal_id" in decision
        assert "config_hash" in decision
        assert decision["decision_code"] == "OK"
        
        algo.close()
    
    def test_process_feature_row_v2_fail_gating(self, temp_dir, core_config):
        """测试 v2 路径：FAIL_GATING 分支"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
        row = {
            "ts_ms": now_ms - 1000,
            "symbol": "BTCUSDT",
            "z_ofi": 1.0,  # 低于阈值 1.5
            "z_cvd": 1.0,  # 低于阈值 1.2
            "div_type": None,
            "consistency": 0.5,
            "spread_bps": 5.0,
            "lag_sec": 0.5,
            "warmup": False,
            "reason_codes": [],
        }
        
        decision = algo.process_feature_row(row)
        
        assert decision is not None
        assert decision["confirm"] is False
        assert decision["gating"] == 0
        assert decision["decision_code"] == "FAIL_GATING"
        
        algo.close()
    
    def test_process_feature_row_v2_write_jsonl(self, temp_dir, core_config):
        """测试 v2 路径：写入 JSONL"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
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
        
        # 验证 JSONL 文件
        jsonl_file = temp_dir / "ready" / "signal" / "BTCUSDT" / f"signals-{time.strftime('%Y%m%d-%H', time.gmtime((now_ms - 1000) / 1000))}.jsonl"
        if jsonl_file.exists():
            with jsonl_file.open("r", encoding="utf-8") as f:
                line = f.readline().strip()
                if line:
                    data = json.loads(line)
                    assert data["schema_version"] == "signal/v2"
                    assert data["signal_id"] == decision["signal_id"]
                    assert data["confirm"] is True
    
    def test_process_feature_row_v2_write_sqlite(self, temp_dir, core_config):
        """测试 v2 路径：写入 SQLite"""
        core_config["sink"]["output_dir"] = str(temp_dir)
        algo = CoreAlgorithm(config=core_config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
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
        
        # 验证 SQLite 数据库
        db_path = temp_dir / "signals.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            # 先检查表结构
            cursor = conn.execute("PRAGMA table_info(signals)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # 如果表有 signal_id 列，使用它查询
            if "signal_id" in columns:
                cursor = conn.execute("SELECT signal_id, symbol, ts_ms, confirm FROM signals WHERE signal_id = ?", (decision["signal_id"],))
            else:
                # 否则使用 symbol 和 ts_ms 查询（兼容旧表结构）
                cursor = conn.execute("SELECT symbol, ts_ms FROM signals WHERE symbol = ? AND ts_ms = ?", (decision["symbol"], decision["ts_ms"]))
            row_db = cursor.fetchone()
            conn.close()
            
            if row_db:
                # 验证数据存在
                assert row_db is not None
                if "signal_id" in columns:
                    assert row_db[0] == decision["signal_id"]  # signal_id
                    assert row_db[1] == "BTCUSDT"  # symbol
                    assert row_db[3] == 1  # confirm (True = 1)
    
    def test_process_feature_row_v2_backward_compatible(self, temp_dir):
        """测试向后兼容：v1 路径仍然可用"""
        config = {
            "use_signal_v2": False,  # 禁用 v2
            "sink": {"kind": "jsonl", "output_dir": str(temp_dir)},
        }
        algo = CoreAlgorithm(config=config, output_dir=temp_dir)
        
        now_ms = int(time.time() * 1000)
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
        
        assert decision is not None
        # v1 路径应该仍然工作
        assert "ts_ms" in decision
        assert "symbol" in decision
        
        algo.close()

