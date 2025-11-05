#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# HARVEST 本地一键启动脚本
# 用于本地测试和开发

set -euo pipefail

# 获取脚本所在目录，并切换到项目根目录
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=========================================="
echo "HARVEST 本地采集启动"
echo "=========================================="
echo "项目根目录: $ROOT"
echo ""

# 检查 Python 环境
if ! command -v python &> /dev/null; then
    echo "错误: 未找到 python 命令"
    echo "请确保已安装 Python >= 3.10"
    exit 1
fi

# 检查配置文件是否存在
CONFIG_FILE="${CONFIG_FILE:-./config/defaults.yaml}"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "警告: 配置文件不存在: $CONFIG_FILE"
    echo "将使用默认配置或环境变量"
fi

# 设置默认参数（可通过环境变量覆盖）
# 统一使用 ./deploy/data/ofi_cvd 作为默认输出目录（与 README 一致）
OUTPUT_DIR="${OUTPUT_DIR:-./deploy/data/ofi_cvd}"
FORMAT="${FORMAT:-parquet}"
MAX_ROWS="${MAX_ROWS:-200000}"
MAX_SEC="${MAX_SEC:-60}"

echo "配置参数:"
echo "  - 配置文件: $CONFIG_FILE"
echo "  - 输出目录: $OUTPUT_DIR"
echo "  - 输出格式: $FORMAT"
echo "  - 轮转最大行数: $MAX_ROWS"
echo "  - 轮转时间间隔: $MAX_SEC 秒"
echo ""
echo "提示: 可通过环境变量覆盖参数，例如:"
echo "  OUTPUT_DIR=./custom/data FORMAT=jsonl bash scripts/harvest_local.sh"
echo ""
echo "=========================================="
echo "启动 HARVEST 采集器..."
echo "=========================================="
echo ""

# 启动 HARVEST（参数可按需覆盖）
python -m mcp.harvest_server.app \
  --config "$CONFIG_FILE" \
  --output "$OUTPUT_DIR" \
  --format "$FORMAT" \
  --rotate.max_rows "$MAX_ROWS" \
  --rotate.max_sec "$MAX_SEC"

# 捕获退出码
EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "HARVEST 采集器正常退出"
else
    echo "HARVEST 采集器异常退出 (退出码: $EXIT_CODE)"
fi
echo "=========================================="

exit $EXIT_CODE
