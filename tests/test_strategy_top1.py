from mcp.strategy_server.app import _select_top_signals


def test_select_top_signals_keeps_highest_abs_score():
    signals = [
        {"symbol": "BTCUSDT", "ts_ms": 1000, "score": 1.0, "signal_id": "s1"},
        {"symbol": "BTCUSDT", "ts_ms": 1000, "score": -2.5, "signal_id": "s2"},
        {"symbol": "BTCUSDT", "ts_ms": 1000, "score": 2.0, "signal_id": "s3"},
    ]

    filtered, removed = _select_top_signals(signals)

    assert removed == 2
    assert len(filtered) == 1
    assert filtered[0]["signal_id"] == "s2"


def test_select_top_signals_preserves_order_across_keys():
    signals = [
        {"symbol": "BTCUSDT", "ts_ms": 1000, "score": 1.0, "signal_id": "a"},
        {"symbol": "ETHUSDT", "ts_ms": 900, "score": 1.5, "signal_id": "b"},
        {"symbol": "BTCUSDT", "ts_ms": 1000, "score": 0.5, "signal_id": "c"},
        {"symbol": "ETHUSDT", "ts_ms": 900, "score": -2.0, "signal_id": "d"},
    ]

    filtered, removed = _select_top_signals(signals)

    assert removed == 2
    assert [s["signal_id"] for s in filtered] == ["a", "d"]
