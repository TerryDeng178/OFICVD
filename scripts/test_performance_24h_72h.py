#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Performance test for 24h/72h data slices"""
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_backtest(input_dir: Path, kinds: str, date: str, minutes: int, symbols: str, output_dir: Path) -> Dict:
    """Run backtest and measure performance"""
    import subprocess
    
    start_time = time.time()
    
    cmd = [
        sys.executable,
        "scripts/replay_harness.py",
        "--input", str(input_dir),
        "--kinds", kinds,
        "--date", date,
        "--minutes", str(minutes),
        "--symbols", symbols,
        "--output", str(output_dir),
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3600,  # 1 hour timeout
        )
        
        elapsed_time = time.time() - start_time
        
        # Find output files
        run_dirs = sorted([d for d in output_dir.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
        if run_dirs:
            run_dir = run_dirs[0]
            signal_dir = run_dir / "signals" / "ready" / "signal"
            trades_file = run_dir / "trades.jsonl"
            metrics_file = run_dir / "metrics.json"
            
            signal_count = 0
            if signal_dir.exists():
                signal_files = list(signal_dir.rglob("*.jsonl"))
                for sf in signal_files:
                    try:
                        with sf.open("r", encoding="utf-8") as f:
                            signal_count += sum(1 for _ in f)
                    except:
                        pass
            
            trade_count = 0
            if trades_file.exists():
                try:
                    with trades_file.open("r", encoding="utf-8") as f:
                        trade_count = sum(1 for _ in f)
                except:
                    pass
            
            metrics = {}
            if metrics_file.exists():
                try:
                    with metrics_file.open("r", encoding="utf-8") as f:
                        metrics = json.load(f)
                except:
                    pass
            
            return {
                "success": result.returncode == 0,
                "elapsed_time": elapsed_time,
                "signal_count": signal_count,
                "trade_count": trade_count,
                "metrics": metrics,
                "output_dir": str(run_dir),
            }
        else:
            return {
                "success": False,
                "elapsed_time": elapsed_time,
                "error": "No output directory found",
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "elapsed_time": time.time() - start_time,
            "error": "Timeout",
        }
    except Exception as e:
        return {
            "success": False,
            "elapsed_time": time.time() - start_time,
            "error": str(e),
        }


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Performance test for 24h/72h data slices")
    parser.add_argument("--input", type=str, required=True, help="Input data directory")
    parser.add_argument("--date", type=str, required=True, help="Date (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, default="BTCUSDT", help="Comma-separated symbols")
    parser.add_argument("--kinds", type=str, default="features", help="Data kinds (features or prices,orderbook)")
    parser.add_argument("--hours", type=int, default=24, help="Number of hours to test (24 or 72)")
    parser.add_argument("--output", type=str, help="Output directory for test results")
    
    args = parser.parse_args()
    
    input_dir = Path(args.input)
    minutes = args.hours * 60
    
    output_base = Path(args.output or "runtime/backtest/performance_test")
    output_base.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Performance test: {args.hours}h ({minutes} minutes)")
    logger.info(f"Input: {input_dir}, Kinds: {args.kinds}, Date: {args.date}")
    
    test_output_dir = output_base / f"test_{args.hours}h_{args.kinds.replace(',', '_')}"
    
    logger.info("Starting backtest...")
    result = run_backtest(
        input_dir=input_dir,
        kinds=args.kinds,
        date=args.date,
        minutes=minutes,
        symbols=args.symbols,
        output_dir=test_output_dir,
    )
    
    # Print results
    print("\n" + "=" * 80)
    print(f"Performance Test Results: {args.hours}h")
    print("=" * 80)
    print(f"\nStatus: {'[PASS]' if result['success'] else '[FAIL]'}")
    print(f"Elapsed time: {result['elapsed_time']:.2f} seconds ({result['elapsed_time']/60:.2f} minutes)")
    
    if result['success']:
        print(f"\nOutput:")
        print(f"  Signals: {result.get('signal_count', 0)}")
        print(f"  Trades: {result.get('trade_count', 0)}")
        print(f"  Output directory: {result.get('output_dir', 'N/A')}")
        
        if result.get('metrics'):
            print(f"\nMetrics:")
            for key, value in result['metrics'].items():
                print(f"  {key}: {value}")
        
        # Performance metrics
        signals_per_sec = result.get('signal_count', 0) / max(result['elapsed_time'], 1)
        print(f"\nPerformance:")
        print(f"  Signals per second: {signals_per_sec:.2f}")
        print(f"  Processing speed: {minutes / (result['elapsed_time']/60):.2f}x real-time")
    else:
        print(f"\nError: {result.get('error', 'Unknown error')}")
    
    # Save results
    result_file = test_output_dir / "performance_result.json"
    with result_file.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"Results saved to {result_file}")
    
    return 0 if result['success'] else 1


if __name__ == "__main__":
    sys.exit(main())

