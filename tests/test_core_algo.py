# -*- coding: utf-8 -*-
import json
import sqlite3
from pathlib import Path

import pytest

from alpha_core.signals import CoreAlgorithm
from alpha_core.signals.core_algo import JsonlSink, NullSink, SqliteSink


@pytest.fixture()
def base_row() -> dict:
    return {
        "ts_ms": 1730790000000,
        "symbol": "BTCUSDT",
        "z_ofi": 1.2,
        "z_cvd": 1.0,
        "spread_bps": 4.5,
        "lag_sec": 0.05,
        "consistency": 0.5,
        "warmup": False,
        "fusion_score": 0.9,
        "activity": {"tps": 5.0},
        "div_type": None,
    }


def test_core_algorithm_confirms_signal(base_row: dict) -> None:
    algo = CoreAlgorithm(config={"sink": {"kind": "null"}}, sink=NullSink())
    decision = algo.process_feature_row(base_row)
    assert decision is not None
    assert decision["confirm"] is True
    assert decision["signal_type"] in {"buy", "strong_buy"}
    assert algo.stats.emitted == 1


def test_core_algorithm_blocks_warmup(base_row: dict) -> None:
    algo = CoreAlgorithm(config={"sink": {"kind": "null"}}, sink=NullSink())
    warmup_row = dict(base_row)
    warmup_row["ts_ms"] += 1000
    warmup_row["warmup"] = True
    decision = algo.process_feature_row(warmup_row)
    assert decision is not None
    assert decision["confirm"] is False
    assert decision["gating"] is True
    assert decision["guard_reason"] == "warmup"
    assert algo.stats.warmup_blocked == 1


def test_core_algorithm_deduplicates(base_row: dict) -> None:
    algo = CoreAlgorithm(config={"sink": {"kind": "null"}}, sink=NullSink())
    first = algo.process_feature_row(base_row)
    dup = algo.process_feature_row(base_row)
    assert first is not None
    assert dup is None
    assert algo.stats.deduplicated == 1


def test_jsonl_sink_writes(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path)
    entry = {
        "ts_ms": 1730790000000,
        "symbol": "BTCUSDT",
        "score": 0.9,
        "z_ofi": 1.2,
        "z_cvd": 1.0,
        "regime": "active",
        "div_type": None,
        "signal_type": "buy",
        "confirm": True,
        "gating": False,
        "guard_reason": None,
    }
    sink.emit(entry)
    files = list((tmp_path / "ready" / "signal" / "BTCUSDT").glob("signals_*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip()
    assert json.loads(content)["symbol"] == "BTCUSDT"


def test_sqlite_sink_writes(tmp_path: Path) -> None:
    sink = SqliteSink(tmp_path)
    entry = {
        "ts_ms": 1730790000000,
        "symbol": "BTCUSDT",
        "score": 0.9,
        "z_ofi": 1.2,
        "z_cvd": 1.0,
        "regime": "active",
        "div_type": None,
        "signal_type": "buy",
        "confirm": True,
        "gating": False,
        "guard_reason": None,
    }
    sink.emit(entry)
    sink.close()
    conn = sqlite3.connect(tmp_path / "signals.db")
    try:
        cursor = conn.execute("SELECT symbol, score, confirm, gating FROM signals")
        row = cursor.fetchone()
        assert row == ("BTCUSDT", 0.9, 1, 0)
    finally:
        conn.close()
