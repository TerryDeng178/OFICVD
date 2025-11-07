#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# FeaturePipe 演示脚本
# 用于本地测试特征计算接线

set -euo pipefail

# 获取脚本所在目录，并切换到项目根目录
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=========================================="
echo "FeaturePipe 演示"
echo "=========================================="
echo "项目根目录: $ROOT"
echo ""

# 检查 Python 环境
if ! command -v python &> /dev/null; then
    echo "错误: 未找到 python 命令"
    echo "请确保已安装 Python >= 3.10"
    exit 1
fi

# 设置默认参数（可通过环境变量覆盖）
INPUT_DIR="${INPUT_DIR:-./deploy/data/ofi_cvd}"
SINK="${SINK:-jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-./runtime}"
SYMBOLS="${SYMBOLS:-BTCUSDT}"
CONFIG_FILE="${CONFIG_FILE:-./config/defaults.yaml}"

echo "配置参数:"
echo "  - 输入目录: $INPUT_DIR"
echo "  - Sink类型: $SINK"
echo "  - 输出目录: $OUTPUT_DIR"
echo "  - 交易对: $SYMBOLS"
echo "  - 配置文件: $CONFIG_FILE"
echo ""

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "启动 FeaturePipe..."
echo "=========================================="
echo ""

# 启动 FeaturePipe
python -m alpha_core.microstructure.feature_pipe \
  --input "$INPUT_DIR" \
  --sink "$SINK" \
  --out "$OUTPUT_DIR/features.$([ "$SINK" = "jsonl" ] && echo "jsonl" || echo "db")" \
  --symbols $SYMBOLS \
  --config "$CONFIG_FILE"

EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "FeaturePipe 正常退出"
    echo "输出文件: $OUTPUT_DIR/features.$([ "$SINK" = "jsonl" ] && echo "jsonl" || echo "db")"
else
    echo "FeaturePipe 异常退出 (退出码: $EXIT_CODE)"
fi
echo "=========================================="

exit $EXIT_CODE

