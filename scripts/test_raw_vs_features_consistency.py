#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test consistency between raw path and features path"""
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_signals_from_jsonl(signal_dir: Path) -> List[Dict]:
    """Load signals from JSONL files"""
    signals = []
    for jsonl_file in signal_dir.rglob("*.jsonl"):
        try:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        signals.append(json.loads(line))
        except Exception as e:
            logger.error(f"Error reading {jsonl_file}: {e}")
    return signals


def compare_signals(raw_signals: List[Dict], features_signals: List[Dict]) -> Dict:
    """Compare signals from raw path and features path"""
    # Group by (ts_ms, symbol)
    raw_by_key = {(s["ts_ms"], s["symbol"]): s for s in raw_signals}
    features_by_key = {(s["ts_ms"], s["symbol"]): s for s in features_signals}
    
    # Find common keys
    common_keys = set(raw_by_key.keys()) & set(features_by_key.keys())
    raw_only = set(raw_by_key.keys()) - set(features_by_key.keys())
    features_only = set(features_by_key.keys()) - set(raw_by_key.keys())
    
    # Compare common signals
    differences = []
    for key in common_keys:
        raw_sig = raw_by_key[key]
        features_sig = features_by_key[key]
        
        # Compare key fields
        diff_fields = []
        for field in ["score", "z_ofi", "z_cvd", "regime", "div_type", "confirm", "gating"]:
            if raw_sig.get(field) != features_sig.get(field):
                diff_fields.append({
                    "field": field,
                    "raw": raw_sig.get(field),
                    "features": features_sig.get(field),
                })
        
        if diff_fields:
            differences.append({
                "key": key,
                "differences": diff_fields,
            })
    
    # Calculate statistics
    total_raw = len(raw_signals)
    total_features = len(features_signals)
    common_count = len(common_keys)
    diff_count = len(differences)
    
    return {
        "raw_total": total_raw,
        "features_total": total_features,
        "common_count": common_count,
        "raw_only_count": len(raw_only),
        "features_only_count": len(features_only),
        "difference_count": diff_count,
        "consistency_rate": (common_count - diff_count) / max(common_count, 1) * 100,
        "differences": differences[:10],  # Limit to first 10
    }


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test consistency between raw and features paths")
    parser.add_argument("--raw-output", type=str, required=True, help="Output directory from raw path backtest")
    parser.add_argument("--features-output", type=str, required=True, help="Output directory from features path backtest")
    parser.add_argument("--output", type=str, help="Output directory for comparison results")
    
    args = parser.parse_args()
    
    raw_output_dir = Path(args.raw_output)
    features_output_dir = Path(args.features_output)
    
    # Find signal directories
    raw_signal_dir = raw_output_dir / "signals" / "ready" / "signal"
    features_signal_dir = features_output_dir / "signals" / "ready" / "signal"
    
    if not raw_signal_dir.exists():
        logger.error(f"Raw signal directory not found: {raw_signal_dir}")
        return 1
    
    if not features_signal_dir.exists():
        logger.error(f"Features signal directory not found: {features_signal_dir}")
        return 1
    
    logger.info("Loading signals from raw path...")
    raw_signals = load_signals_from_jsonl(raw_signal_dir)
    logger.info(f"Loaded {len(raw_signals)} signals from raw path")
    
    logger.info("Loading signals from features path...")
    features_signals = load_signals_from_jsonl(features_signal_dir)
    logger.info(f"Loaded {len(features_signals)} signals from features path")
    
    if not raw_signals or not features_signals:
        logger.warning("No signals to compare")
        return 1
    
    logger.info("Comparing signals...")
    comparison = compare_signals(raw_signals, features_signals)
    
    # Print results
    print("\n" + "=" * 80)
    print("Raw vs Features Path Consistency Test")
    print("=" * 80)
    print(f"\nSignal Counts:")
    print(f"  Raw path: {comparison['raw_total']}")
    print(f"  Features path: {comparison['features_total']}")
    print(f"  Common: {comparison['common_count']}")
    print(f"  Raw only: {comparison['raw_only_count']}")
    print(f"  Features only: {comparison['features_only_count']}")
    print(f"\nConsistency:")
    print(f"  Differences: {comparison['difference_count']}")
    print(f"  Consistency rate: {comparison['consistency_rate']:.2f}%")
    
    if comparison['differences']:
        print(f"\nSample Differences (first {len(comparison['differences'])}):")
        for diff in comparison['differences']:
            print(f"  Key: {diff['key']}")
            for field_diff in diff['differences']:
                print(f"    {field_diff['field']}: raw={field_diff['raw']}, features={field_diff['features']}")
    
    # Save results
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        result_file = output_dir / "consistency_comparison.json"
        with result_file.open("w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        logger.info(f"Results saved to {result_file}")
    
    # Determine pass/fail
    consistency_threshold = 99.0  # 99% consistency required
    if comparison['consistency_rate'] >= consistency_threshold:
        print(f"\n[PASS] Consistency rate {comparison['consistency_rate']:.2f}% >= {consistency_threshold}%")
        return 0
    else:
        print(f"\n[FAIL] Consistency rate {comparison['consistency_rate']:.2f}% < {consistency_threshold}%")
        return 1


if __name__ == "__main__":
    sys.exit(main())

