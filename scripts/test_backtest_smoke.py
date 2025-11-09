#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T08.7: Smoke test for backtest harness"""
import json
import logging
import sys
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


def test_reader():
    """Test DataReader"""
    logger.info("=" * 80)
    logger.info("Test 1: DataReader")
    logger.info("=" * 80)
    
    input_dir = Path("./deploy/data/ofi_cvd")
    if not input_dir.exists():
        logger.warning(f"Input directory not found: {input_dir}")
        return False
    
    # Find available symbols
    features_dir = input_dir / "ready" / "features"
    if not features_dir.exists():
        features_dir = input_dir / "preview" / "features"
    
    if not features_dir.exists():
        logger.error("Features directory not found")
        return False
    
    symbols = [d.name for d in features_dir.iterdir() if d.is_dir()]
    if not symbols:
        logger.error("No symbols found")
        return False
    
    test_symbol = symbols[0]
    logger.info(f"Testing with symbol: {test_symbol}")
    
    reader = DataReader(
        input_dir=input_dir,
        symbols=[test_symbol],
        kinds=["features"],
        minutes=2,  # 2 minutes smoke test
    )
    
    features = list(reader.read_features())
    stats = reader.get_stats()
    
    logger.info(f"Read {len(features)} features")
    logger.info(f"Stats: {json.dumps(stats, indent=2)}")
    
    if len(features) == 0:
        logger.error("No features read")
        return False
    
    # Check required fields
    required_fields = ["symbol", "ts_ms", "mid"]
    missing_fields = []
    for field in required_fields:
        if field not in features[0]:
            missing_fields.append(field)
    
    if missing_fields:
        logger.error(f"Missing required fields: {missing_fields}")
        return False
    
    logger.info("DataReader test: PASSED")
    return True, features


def test_feeder(features):
    """Test ReplayFeeder"""
    logger.info("=" * 80)
    logger.info("Test 2: ReplayFeeder")
    logger.info("=" * 80)
    
    output_dir = Path("./runtime/backtest/test_smoke")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    signal_output_dir = output_dir / "signals"
    signal_output_dir.mkdir(parents=True, exist_ok=True)
    
    feeder = ReplayFeeder(
        config={"replay_mode": 1},
        output_dir=signal_output_dir,
        sink_kind="jsonl",
    )
    
    signal_count = 0
    signals = []
    for feature_row in features[:100]:  # Limit to 100 rows for smoke test
        signal = feeder.algo.process_feature_row(feature_row)
        if signal:
            signal_count += 1
            signals.append(signal)
    
    feeder.close()
    stats = feeder.get_stats()
    
    logger.info(f"Generated {signal_count} signals from {len(features[:100])} features")
    logger.info(f"Feeder stats: {json.dumps(stats, indent=2)}")
    
    # Check signal files
    signal_files = list((signal_output_dir / "ready" / "signal").rglob("*.jsonl"))
    if signal_files:
        logger.info(f"Signal files created: {len(signal_files)}")
        logger.info(f"First file: {signal_files[0]}")
    else:
        logger.warning("No signal files created (may be normal if no signals generated)")
    
    logger.info("ReplayFeeder test: PASSED")
    return True, signals


def test_trade_sim(signals):
    """Test TradeSimulator"""
    logger.info("=" * 80)
    logger.info("Test 3: TradeSimulator")
    logger.info("=" * 80)
    
    if not signals:
        logger.warning("No signals to test TradeSimulator")
        return True
    
    output_dir = Path("./runtime/backtest/test_smoke")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    trade_sim = TradeSimulator(
        config={
            "taker_fee_bps": 2.0,
            "slippage_bps": 1.0,
            "notional_per_trade": 1000,
        },
        output_dir=output_dir,
    )
    
    # Use a fixed mid price for testing
    mid_price = 50000.0
    
    trade_count = 0
    for signal in signals[:20]:  # Limit to 20 signals
        trade = trade_sim.process_signal(signal, mid_price)
        if trade:
            trade_count += 1
    
    # Close all positions
    trade_sim.close_all_positions({"BTCUSDT": mid_price})
    
    # Save daily PnL
    trade_sim.save_pnl_daily()
    
    logger.info(f"Executed {trade_count} trades")
    logger.info(f"Total trades: {len(trade_sim.trades)}")
    
    # Check output files
    trades_file = output_dir / "trades.jsonl"
    pnl_file = output_dir / "pnl_daily.jsonl"
    
    if trades_file.exists():
        logger.info(f"Trades file created: {trades_file}")
        with trades_file.open("r", encoding="utf-8") as f:
            trade_lines = [line for line in f if line.strip()]
        logger.info(f"Trade records: {len(trade_lines)}")
    else:
        logger.warning("Trades file not created")
    
    if pnl_file.exists():
        logger.info(f"PnL file created: {pnl_file}")
        with pnl_file.open("r", encoding="utf-8") as f:
            pnl_lines = [line for line in f if line.strip()]
        logger.info(f"PnL records: {len(pnl_lines)}")
    else:
        logger.warning("PnL file not created")
    
    logger.info("TradeSimulator test: PASSED")
    return True, trade_sim.trades, list(trade_sim.pnl_daily.values())


def test_metrics(trades, pnl_daily):
    """Test MetricsAggregator"""
    logger.info("=" * 80)
    logger.info("Test 4: MetricsAggregator")
    logger.info("=" * 80)
    
    output_dir = Path("./runtime/backtest/test_smoke")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    metrics_agg = MetricsAggregator(output_dir)
    metrics = metrics_agg.compute_metrics(trades, pnl_daily)
    
    logger.info(f"Computed metrics: {json.dumps(metrics, indent=2)}")
    
    # Check metrics file
    metrics_file = output_dir / "metrics.json"
    if metrics_file.exists():
        logger.info(f"Metrics file created: {metrics_file}")
    else:
        logger.error("Metrics file not created")
        return False
    
    logger.info("MetricsAggregator test: PASSED")
    return True


def main():
    """Run all smoke tests"""
    logger.info("=" * 80)
    logger.info("T08.7: Backtest Harness Smoke Test")
    logger.info("=" * 80)
    
    results = []
    
    # Test 1: Reader
    try:
        result = test_reader()
        if isinstance(result, tuple):
            success, features = result
        else:
            success = result
            features = []
        results.append(("Reader", success))
        if not success:
            logger.error("Reader test failed, stopping")
            return 1
    except Exception as e:
        logger.error(f"Reader test failed: {e}", exc_info=True)
        return 1
    
    # Test 2: Feeder
    try:
        result = test_feeder(features)
        if isinstance(result, tuple):
            success, signals = result
        else:
            success = result
            signals = []
        results.append(("Feeder", success))
        if not success:
            logger.error("Feeder test failed, stopping")
            return 1
    except Exception as e:
        logger.error(f"Feeder test failed: {e}", exc_info=True)
        return 1
    
    # Test 3: TradeSim
    try:
        result = test_trade_sim(signals)
        if isinstance(result, tuple):
            success, trades, pnl_daily = result
        else:
            success = result
            trades = []
            pnl_daily = []
        results.append(("TradeSim", success))
    except Exception as e:
        logger.error(f"TradeSim test failed: {e}", exc_info=True)
        trades = []
        pnl_daily = []
        results.append(("TradeSim", False))
    
    # Test 4: Metrics
    try:
        success = test_metrics(trades, pnl_daily)
        results.append(("Metrics", success))
    except Exception as e:
        logger.error(f"Metrics test failed: {e}", exc_info=True)
        results.append(("Metrics", False))
    
    # Summary
    logger.info("=" * 80)
    logger.info("Test Summary")
    logger.info("=" * 80)
    
    all_passed = True
    for test_name, passed in results:
        status = "PASSED" if passed else "FAILED"
        logger.info(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        logger.info("All tests PASSED")
        return 0
    else:
        logger.error("Some tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

