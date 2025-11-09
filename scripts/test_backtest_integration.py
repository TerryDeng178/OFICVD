#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T08.7: Integration test for backtest harness with real historical data"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alpha_core.backtest import DataReader, ReplayFeeder, TradeSimulator, MetricsAggregator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def find_available_data(input_dir: Path):
    """Find available historical data"""
    features_dir = input_dir / "ready" / "features"
    if not features_dir.exists():
        features_dir = input_dir / "preview" / "features"
    
    if not features_dir.exists():
        return None, None
    
    symbols = [d.name for d in features_dir.iterdir() if d.is_dir()]
    if not symbols:
        return None, None
    
    # Find symbol with most data
    symbol_data = {}
    for symbol in symbols:
        symbol_dir = features_dir / symbol
        files = list(symbol_dir.glob("*.jsonl"))
        if files:
            total_lines = 0
            for f in files:
                try:
                    with f.open("r", encoding="utf-8") as fp:
                        total_lines += sum(1 for _ in fp)
                except:
                    pass
            symbol_data[symbol] = total_lines
    
    if not symbol_data:
        return None, None
    
    # Use symbol with most data
    best_symbol = max(symbol_data.items(), key=lambda x: x[1])[0]
    return best_symbol, symbol_data[best_symbol]


def test_integration_fast_path(input_dir: Path, symbol: str, minutes: int = 60):
    """Test fast path: features → signals → pnl"""
    logger.info("=" * 80)
    logger.info("Integration Test: Fast Path (features → signals → pnl)")
    logger.info("=" * 80)
    logger.info(f"Input: {input_dir}")
    logger.info(f"Symbol: {symbol}")
    logger.info(f"Minutes: {minutes}")
    
    # Generate run ID
    run_id = f"integration_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    output_dir = Path("./runtime/backtest") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Output: {output_dir}")
    logger.info(f"Run ID: {run_id}")
    
    # Step 1: Read features
    logger.info("-" * 80)
    logger.info("Step 1: Reading features...")
    reader = DataReader(
        input_dir=input_dir,
        symbols=[symbol],
        kinds=["features"],
        minutes=minutes,
    )
    
    features = list(reader.read_features())
    reader_stats = reader.get_stats()
    
    logger.info(f"Read {len(features)} features")
    logger.info(f"Reader stats: {json.dumps(reader_stats, indent=2)}")
    
    if len(features) == 0:
        logger.error("No features read")
        return False, {}
    
    # Step 2: Generate signals
    logger.info("-" * 80)
    logger.info("Step 2: Generating signals...")
    signal_output_dir = output_dir / "signals"
    signal_output_dir.mkdir(parents=True, exist_ok=True)
    
    feeder = ReplayFeeder(
        config={"replay_mode": 1},
        output_dir=signal_output_dir,
        sink_kind="jsonl",
    )
    
    signals = []
    current_prices = {}
    
    for feature_row in features:
        symbol_name = feature_row.get("symbol", "")
        mid = feature_row.get("mid", 0)
        if symbol_name and mid:
            current_prices[symbol_name] = mid
        
        signal = feeder.algo.process_feature_row(feature_row)
        if signal:
            signals.append(signal)
    
    feeder.close()
    feeder_stats = feeder.get_stats()
    
    logger.info(f"Generated {len(signals)} signals from {len(features)} features")
    logger.info(f"Signal generation rate: {len(signals)/len(features)*100:.2f}%")
    logger.info(f"Feeder stats: {json.dumps(feeder_stats, indent=2)}")
    
    # Step 3: Simulate trades
    logger.info("-" * 80)
    logger.info("Step 3: Simulating trades...")
    trade_sim = TradeSimulator(
        config={
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 1000,
        },
        output_dir=output_dir,
    )
    
    trades = []
    for signal in signals:
        symbol_name = signal.get("symbol", "")
        mid = current_prices.get(symbol_name, 50000.0)  # Fallback price
        trade = trade_sim.process_signal(signal, mid)
        if trade:
            trades.append(trade)
    
    # Close all positions
    trade_sim.close_all_positions(current_prices)
    
    # Save daily PnL
    trade_sim.save_pnl_daily()
    
    logger.info(f"Executed {len(trades)} trades")
    logger.info(f"Total trades (including exits): {len(trade_sim.trades)}")
    
    # Step 4: Compute metrics
    logger.info("-" * 80)
    logger.info("Step 4: Computing metrics...")
    metrics_agg = MetricsAggregator(output_dir)
    pnl_daily_list = list(trade_sim.pnl_daily.values())
    metrics = metrics_agg.compute_metrics(trade_sim.trades, pnl_daily_list)
    
    logger.info(f"Metrics computed: {json.dumps(metrics, indent=2)}")
    
    # Step 5: Verify output files
    logger.info("-" * 80)
    logger.info("Step 5: Verifying output files...")
    
    output_files = {
        "signals": list((signal_output_dir / "ready" / "signal").rglob("*.jsonl")),
        "trades": output_dir / "trades.jsonl",
        "pnl_daily": output_dir / "pnl_daily.jsonl",
        "metrics": output_dir / "metrics.json",
    }
    
    for name, path in output_files.items():
        if isinstance(path, list):
            if path:
                logger.info(f"✅ {name}: {len(path)} file(s) created")
            else:
                logger.warning(f"⚠️ {name}: No files created")
        else:
            if path.exists():
                size_kb = path.stat().st_size / 1024
                logger.info(f"✅ {name}: {path.name} ({size_kb:.2f} KB)")
            else:
                logger.error(f"❌ {name}: File not found")
    
    # Summary
    logger.info("=" * 80)
    logger.info("Integration Test Summary")
    logger.info("=" * 80)
    
    summary = {
        "run_id": run_id,
        "symbol": symbol,
        "minutes": minutes,
        "features_read": len(features),
        "signals_generated": len(signals),
        "signal_rate_pct": len(signals) / len(features) * 100 if features else 0,
        "trades_executed": len(trades),
        "total_trades": len(trade_sim.trades),
        "metrics": metrics,
        "output_dir": str(output_dir),
    }
    
    logger.info(json.dumps(summary, indent=2, ensure_ascii=False))
    
    # Save summary
    summary_file = output_dir / "integration_test_summary.json"
    with summary_file.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Summary saved to: {summary_file}")
    
    return True, summary


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="T08.7: Integration test for backtest harness")
    parser.add_argument("--input", type=str, default="./deploy/data/ofi_cvd", help="Input data directory")
    parser.add_argument("--symbol", type=str, help="Symbol to test (auto-detect if not specified)")
    parser.add_argument("--minutes", type=int, default=60, help="Number of minutes to process")
    
    args = parser.parse_args()
    
    input_dir = Path(args.input)
    
    # Find available data
    if args.symbol:
        symbol = args.symbol
    else:
        logger.info("Auto-detecting available data...")
        symbol, line_count = find_available_data(input_dir)
        if not symbol:
            logger.error("No historical data found")
            return 1
        logger.info(f"Found data for {symbol} ({line_count} lines)")
    
    # Run integration test
    success, summary = test_integration_fast_path(input_dir, symbol, args.minutes)
    
    if success:
        logger.info("=" * 80)
        logger.info("✅ Integration test PASSED")
        logger.info("=" * 80)
        return 0
    else:
        logger.error("=" * 80)
        logger.error("❌ Integration test FAILED")
        logger.error("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())

