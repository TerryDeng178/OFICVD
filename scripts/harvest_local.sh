#!/bin/bash
# -*- coding: utf-8 -*-
# 单机 HARVEST 启动脚本（可选）
# 用于本地测试和开发

# 设置默认值
CONFIG_FILE="${CONFIG_FILE:-./config/defaults.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-./data}"
FORMAT="${FORMAT:-parquet}"
MAX_ROWS="${MAX_ROWS:-200000}"
MAX_SEC="${MAX_SEC:-60}"

echo "Starting HARVEST server..."
echo "Config: $CONFIG_FILE"
echo "Output: $OUTPUT_DIR"
echo "Format: $FORMAT"

python -m mcp.harvest_server.app \
  --config "$CONFIG_FILE" \
  --output "$OUTPUT_DIR" \
  --format "$FORMAT" \
  --rotate.max_rows "$MAX_ROWS" \
  --rotate.max_sec "$MAX_SEC"

