#!/usr/bin/env bash
set -euo pipefail

# TASK-B2: 独立回测运行脚本
# 用法：
#   模式A（全量重算）：./run_backtest.sh A ./data/features ./configs/backtest.yaml
#   模式B（信号复现）：./run_backtest.sh B jsonl://./runtime/signals ./configs/backtest.yaml

if [ $# -lt 3 ]; then
    echo "Usage: $0 <mode> <input_src> <config_file> [options]"
    echo ""
    echo "Modes:"
    echo "  A    全量重算模式（features → signals → trades/pnl）"
    echo "  B    信号复现模式（signals → trades/pnl）"
    echo ""
    echo "Input sources:"
    echo "  Mode A: <features_dir> (e.g., ./data/features)"
    echo "  Mode B: jsonl://<signals_dir> 或 sqlite://<db_path>"
    echo ""
    echo "Examples:"
    echo "  $0 A ./data/features ./configs/backtest.yaml --symbols BTCUSDT,ETHUSDT"
    echo "  $0 B jsonl://./runtime/signals ./configs/backtest.yaml --start 2025-11-12T00:00:00Z"
    exit 1
fi

MODE="$1"
INPUT_SRC="$2"
CONFIG_FILE="$3"
shift 3

# 生成运行ID
RUN_ID="bt_$(date +%Y%m%d_%H%M%S)"

# 设置输入参数
if [ "$MODE" = "A" ]; then
    FEATURES_DIR="$INPUT_SRC"
    SIGNALS_SRC=""
else
    FEATURES_DIR=""
    SIGNALS_SRC="$INPUT_SRC"
fi

# 默认参数
SYMBOLS="BTCUSDT"
START_TIME="2025-11-12T00:00:00Z"
END_TIME="2025-11-13T00:00:00Z"
SEED=42
TIMEZONE="Asia/Tokyo"

# 解析额外参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --symbols)
            SYMBOLS="$2"
            shift 2
            ;;
        --start)
            START_TIME="$2"
            shift 2
            ;;
        --end)
            END_TIME="$2"
            shift 2
            ;;
        --seed)
            SEED="$2"
            shift 2
            ;;
        --tz|--timezone)
            TIMEZONE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== TASK-B2: Independent Backtest Runner ==="
echo "Run ID: $RUN_ID"
echo "Mode: $MODE"
if [ "$MODE" = "A" ]; then
    echo "Features dir: $FEATURES_DIR"
else
    echo "Signals src: $SIGNALS_SRC"
fi
echo "Config: $CONFIG_FILE"
echo "Symbols: $SYMBOLS"
echo "Time range: $START_TIME to $END_TIME"
echo "Seed: $SEED"
echo "Timezone: $TIMEZONE"
echo ""

# 构建命令
CMD="python -m backtest.app"
CMD="$CMD --mode $MODE"
CMD="$CMD --config $CONFIG_FILE"
CMD="$CMD --run-id $RUN_ID"
CMD="$CMD --symbols $SYMBOLS"
CMD="$CMD --start $START_TIME"
CMD="$CMD --end $END_TIME"
CMD="$CMD --seed $SEED"
CMD="$CMD --tz $TIMEZONE"

if [ "$MODE" = "A" ]; then
    CMD="$CMD --features-dir $FEATURES_DIR"
else
    CMD="$CMD --signals-src $SIGNALS_SRC"
fi

# 执行回测
echo "Executing: $CMD"
echo ""

eval "$CMD"

# 输出结果路径
OUTPUT_DIR="./backtest_out/$RUN_ID"
echo ""
echo "=== Backtest completed ==="
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Generated files:"
ls -la "$OUTPUT_DIR" 2>/dev/null || echo "Output directory not found"

echo ""
echo "Done: $RUN_ID"
