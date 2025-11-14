#!/bin/bash
# -*- coding: utf-8 -*-
# Backtest Runner Script (Linux/macOS)
# TASK-B2: Independent Backtest Runner

set -e  # Exit on any error

# Function to show usage
show_usage() {
    cat << EOF
TASK-B2: Independent Backtest Runner

USAGE:
    $0 [OPTIONS]

OPTIONS:
    --mode MODE              Mode: A (features→signals) or B (signals→trades) [required]
    --features-dir DIR       Features directory for mode A
    --signals-src SRC        Signals source for mode B (jsonl://path or sqlite://path)
    --symbols SYMBOLS        Trading symbols (default: BTCUSDT,ETHUSDT,BNBUSDT)
    --start TIME             Start time (ISO format) [required]
    --end TIME               End time (ISO format) [required]
    --config FILE            Config file (default: ./config/backtest.yaml)
    --out-dir DIR            Output directory (default: ./backtest_out)
    --run-id ID              Run ID (auto-generated if not specified)
    --seed INT               Random seed (default: 42)
    --tz TZ                  Timezone (default: Asia/Tokyo)
    --emit-sqlite            Emit SQLite signals file
    --strict-core            Strict CoreAlgorithm mode
    --reemit-signals         Re-emit signals in mode B

EXAMPLES:
    # Mode A: features → signals → trades
    $0 --mode A --features-dir ./deploy/data/ofi_cvd --symbols BTCUSDT --start 2025-11-08T18:00:00Z --end 2025-11-08T20:00:00Z

    # Mode B: signals → trades
    $0 --mode B --signals-src sqlite://./runtime/signals.db --symbols BTCUSDT,ETHUSDT --start 2025-11-08T18:00:00Z --end 2025-11-08T20:00:00Z

EOF
}

# Parse arguments
MODE=""
FEATURES_DIR=""
SIGNALS_SRC=""
SYMBOLS="BTCUSDT,ETHUSDT,BNBUSDT"
START=""
END=""
CONFIG="./config/backtest.yaml"
OUT_DIR="./backtest_out"
RUN_ID=""
SEED=42
TZ="Asia/Tokyo"
EMIT_SQLITE=""
STRICT_CORE=""
REEMIT_SIGNALS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --features-dir)
            FEATURES_DIR="$2"
            shift 2
            ;;
        --signals-src)
            SIGNALS_SRC="$2"
            shift 2
            ;;
        --symbols)
            SYMBOLS="$2"
            shift 2
            ;;
        --start)
            START="$2"
            shift 2
            ;;
        --end)
            END="$2"
            shift 2
            ;;
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --out-dir)
            OUT_DIR="$2"
            shift 2
            ;;
        --run-id)
            RUN_ID="$2"
            shift 2
            ;;
        --seed)
            SEED="$2"
            shift 2
            ;;
        --tz)
            TZ="$2"
            shift 2
            ;;
        --emit-sqlite)
            EMIT_SQLITE="--emit-sqlite"
            shift
            ;;
        --strict-core)
            STRICT_CORE="--strict-core"
            shift
            ;;
        --reemit-signals)
            REEMIT_SIGNALS="--reemit-signals"
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$MODE" ]]; then
    echo "ERROR: --mode is required"
    show_usage
    exit 1
fi

if [[ -z "$START" ]]; then
    echo "ERROR: --start is required"
    show_usage
    exit 1
fi

if [[ -z "$END" ]]; then
    echo "ERROR: --end is required"
    show_usage
    exit 1
fi

if [[ "$MODE" == "A" && -z "$FEATURES_DIR" ]]; then
    echo "ERROR: --features-dir is required for mode A"
    show_usage
    exit 1
fi

if [[ "$MODE" == "B" && -z "$SIGNALS_SRC" ]]; then
    echo "ERROR: --signals-src is required for mode B"
    show_usage
    exit 1
fi

# Build command
CMD="python -m backtest.app --mode $MODE --symbols $SYMBOLS --start $START --end $END --config $CONFIG --out-dir $OUT_DIR --seed $SEED --tz $TZ"

if [[ -n "$FEATURES_DIR" ]]; then
    CMD="$CMD --features-dir $FEATURES_DIR"
fi

if [[ -n "$SIGNALS_SRC" ]]; then
    CMD="$CMD --signals-src $SIGNALS_SRC"
fi

if [[ -n "$RUN_ID" ]]; then
    CMD="$CMD --run-id $RUN_ID"
fi

if [[ -n "$EMIT_SQLITE" ]]; then
    CMD="$CMD $EMIT_SQLITE"
fi

if [[ -n "$STRICT_CORE" ]]; then
    CMD="$CMD $STRICT_CORE"
fi

if [[ -n "$REEMIT_SIGNALS" ]]; then
    CMD="$CMD $REEMIT_SIGNALS"
fi

# Execute
echo "=========================================="
echo "TASK-B2: Independent Backtest Runner"
echo "=========================================="
echo "Command: $CMD"
echo "=========================================="

eval $CMD

if [[ $? -eq 0 ]]; then
    echo "=========================================="
    echo "Backtest completed successfully!"
    echo "=========================================="
else
    echo "=========================================="
    echo "Backtest failed with exit code: $?"
    echo "=========================================="
    exit 1
fi