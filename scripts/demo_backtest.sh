#!/bin/bash
# T08: Demo Backtest Script (Bash)
# Example usage of replay_harness.py

set -e

INPUT_DIR="${INPUT_DIR:-./deploy/data/ofi_cvd}"
DATE="${DATE:-2025-10-30}"
SYMBOLS="${SYMBOLS:-BTCUSDT}"
KINDS="${KINDS:-features}"
MINUTES="${MINUTES:-60}"
CONFIG="${CONFIG:-./config/backtest.yaml}"
OUTPUT="${OUTPUT:-./runtime/backtest}"

echo "================================================================================"
echo "T08: Backtest Demo"
echo "================================================================================"
echo ""
echo "Input: $INPUT_DIR"
echo "Date: $DATE"
echo "Symbols: $SYMBOLS"
echo "Kinds: $KINDS"
echo "Minutes: $MINUTES"
echo ""

# Run backtest
python scripts/replay_harness.py \
    --input "$INPUT_DIR" \
    --date "$DATE" \
    --symbols "$SYMBOLS" \
    --kinds "$KINDS" \
    --minutes "$MINUTES" \
    --config "$CONFIG" \
    --output "$OUTPUT"

if [ $? -eq 0 ]; then
    echo ""
    echo "Backtest completed successfully!"
    
    # Find latest run_id
    LATEST_RUN=$(ls -td "$OUTPUT"/*/ 2>/dev/null | head -1)
    if [ -n "$LATEST_RUN" ]; then
        RUN_ID=$(basename "$LATEST_RUN")
        echo ""
        echo "Output files:"
        echo "  Run ID: $RUN_ID"
        echo "  Metrics: $LATEST_RUN/metrics.json"
        echo "  Trades: $LATEST_RUN/trades.jsonl"
        echo "  PnL Daily: $LATEST_RUN/pnl_daily.jsonl"
        echo "  Manifest: $LATEST_RUN/run_manifest.json"
    fi
else
    echo ""
    echo "Backtest failed!"
    exit 1
fi

