# -*- coding: utf-8 -*-
"""TASK-B1 P1: JSONL↔SQLite等价性回归测试

验证同一run_id下JSONL和SQLite的信号数量差异不超过5%
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from alpha_core.signals.signal_writer import SignalWriterV2
from alpha_core.signals.signal_schema import SignalV2, SideHint, Regime, DecisionCode


@pytest.mark.slow
@pytest.mark.equivalence
class TestSinkEquivalence:
    """JSONL↔SQLite等价性测试"""

    def test_jsonl_sqlite_signal_count_equivalence(self):
        """测试JSONL和SQLite信号数量等价性（差异≤5%）"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            # 创建测试信号数据
            run_id = "test_equiv_run"
            test_signals = []
            for i in range(100):  # 生成100个信号
                signal = SignalV2(
                    run_id=run_id,
                    symbol="BTCUSDT",
                    ts_ms=1731470000000 + i * 1000,
                    signal_id=f"{run_id}-BTCUSDT-{1731470000000 + i * 1000}-{i}",
                    score=2.0,
                    side_hint=SideHint.BUY,
                    regime=Regime.QUIET,
                    gating=1,
                    confirm=True,
                    expiry_ms=30000,
                    decision_code=DecisionCode.OK,
                    config_hash="test_hash_123"
                )
                test_signals.append(signal)

            # 初始化SignalWriterV2（dual sink模式）
            writer = SignalWriterV2(
                output_dir=str(output_dir),
                sink_kind="dual"
            )

            # 写入所有信号
            for signal in test_signals:
                writer.write(signal)

            # 关闭writer，确保数据刷新到磁盘
            writer.close()

            # 统计JSONL文件中的信号数量
            jsonl_count = 0
            signals_dir = output_dir / "ready" / "signal" / "BTCUSDT"
            if signals_dir.exists():
                for jsonl_file in signals_dir.glob("*.jsonl"):
                    try:
                        with jsonl_file.open("r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    jsonl_count += 1
                    except Exception as e:
                        pytest.fail(f"读取JSONL文件失败: {jsonl_file}, 错误: {e}")

            # 统计SQLite数据库中的信号数量
            sqlite_count = 0
            db_path = output_dir / "signals_v2.db"
            if db_path.exists():
                try:
                    conn = sqlite3.connect(str(db_path))
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM signals WHERE run_id = ?", (run_id,))
                    result = cursor.fetchone()
                    sqlite_count = result[0] if result else 0
                    conn.close()
                except Exception as e:
                    pytest.fail(f"查询SQLite数据库失败: {db_path}, 错误: {e}")

            # 验证等价性
            assert jsonl_count > 0, f"JSONL文件中没有找到信号 (run_id: {run_id})"
            assert sqlite_count > 0, f"SQLite数据库中没有找到信号 (run_id: {run_id})"

            # 计算差异百分比
            max_count = max(jsonl_count, sqlite_count)
            min_count = min(jsonl_count, sqlite_count)
            diff_percentage = abs(jsonl_count - sqlite_count) / max_count * 100

            # 断言差异不超过5%
            assert diff_percentage <= 5.0, (
                f"JSONL({jsonl_count}) vs SQLite({sqlite_count}) 信号数量差异过大: "
                f"{diff_percentage:.2f}% > 5.0%"
            )

            print(f"✅ Sink等价性验证通过: JSONL={jsonl_count}, SQLite={sqlite_count}, 差异={diff_percentage:.2f}%")

    def test_signals_v2_schema_consistency(self):
        """测试signals_v2数据库schema一致性"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            writer = SignalWriterV2(
                output_dir=str(output_dir),
                sink_kind="dual"
            )

            # 写入一个测试信号
            test_signal = SignalV2(
                run_id="schema_test",
                symbol="BTCUSDT",
                ts_ms=1731470000000,
                signal_id="schema_test-BTCUSDT-1731470000000-0",
                score=2.0,
                side_hint=SideHint.BUY,
                regime=Regime.QUIET,
                gating=1,
                confirm=True,
                expiry_ms=30000,
                decision_code=DecisionCode.OK,
                config_hash="test_hash_123"
            )

            writer.write(test_signal)
            writer.close()

            # 验证数据库schema
            db_path = output_dir / "signals_v2.db"
            assert db_path.exists(), "signals_v2.db 没有创建"

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
            assert cursor.fetchone(), "signals表不存在"

            # 检查必要的列
            cursor.execute("PRAGMA table_info(signals)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}

            required_columns = {
                "run_id": "TEXT",
                "symbol": "TEXT",
                "ts_ms": "INTEGER",
                "signal_id": "TEXT",
                "schema_version": "TEXT",
                "side_hint": "TEXT",
                "score": "REAL",
                "gating": "INTEGER",
                "confirm": "INTEGER",
                "cooldown_ms": "INTEGER",
                "expiry_ms": "INTEGER",
                "decision_code": "TEXT",
                "decision_reason": "TEXT",
                "config_hash": "TEXT",
                "meta": "TEXT"
            }

            for col_name, expected_type in required_columns.items():
                assert col_name in columns, f"缺少必需列: {col_name}"
                assert columns[col_name].upper() == expected_type, (
                    f"列 {col_name} 类型错误: 期望 {expected_type}, 实际 {columns[col_name]}"
                )

            conn.close()

            print("✅ signals_v2 schema一致性验证通过")
