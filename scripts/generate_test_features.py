#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate test features data for backtest smoke test"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def generate_test_features(output_dir: Path, symbol: str = "BTCUSDT", minutes: int = 2):
    """Generate test features data"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create symbol directory
    symbol_dir = output_dir / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate features for the last N minutes
    now = datetime.now(timezone.utc)
    start_ts = int((now.timestamp() - minutes * 60) * 1000)
    
    features = []
    for i in range(minutes * 60):  # 1 feature per second
        ts_ms = start_ts + i * 1000
        second_ts = ts_ms // 1000
        
        # Simulate some variation
        base_price = 50000.0
        price_variation = (i % 100) / 100.0 - 0.5  # -0.5 to 0.5
        mid = base_price + price_variation * 100
        
        feature = {
            "second_ts": second_ts,
            "ts_ms": ts_ms,
            "symbol": symbol,
            "mid": mid,
            "return_1s": price_variation / 100.0,
            "z_ofi": (i % 50) / 10.0 - 2.5,  # -2.5 to 2.5
            "z_cvd": (i % 60) / 10.0 - 3.0,  # -3.0 to 3.0
            "fusion_score": (i % 40) / 10.0 - 2.0,  # -2.0 to 2.0
            "spread_bps": 1.0 + (i % 10) / 10.0,  # 1.0 to 2.0
            "scenario_2x2": "A_H" if i % 4 == 0 else ("A_L" if i % 4 == 1 else ("Q_H" if i % 4 == 2 else "Q_L")),
            "best_bid": mid - 0.5,
            "best_ask": mid + 0.5,
            "lag_ms_price": 10 + (i % 20),
            "lag_ms_orderbook": 15 + (i % 25),
            "lag_sec": (10 + (i % 20)) / 1000.0,
            "consistency": 0.2 + (i % 80) / 100.0,  # 0.2 to 1.0
            "warmup": i < 10,  # First 10 seconds are warmup
        }
        
        features.append(feature)
    
    # Write to JSONL file
    filename = f"features_{datetime.fromtimestamp(start_ts/1000, tz=timezone.utc).strftime('%Y%m%d_%H%M')}.jsonl"
    filepath = symbol_dir / filename
    
    with filepath.open("w", encoding="utf-8") as f:
        for feature in features:
            f.write(json.dumps(feature, ensure_ascii=False) + "\n")
    
    print(f"Generated {len(features)} features to {filepath}")
    return filepath


if __name__ == "__main__":
    output_dir = Path("./deploy/data/ofi_cvd/ready/features")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    
    generate_test_features(output_dir, symbol, minutes)
    print(f"Test features generated for {symbol} ({minutes} minutes)")

