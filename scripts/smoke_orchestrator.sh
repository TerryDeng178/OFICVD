#!/usr/bin/env bash
# Orchestrator 端到端冒烟测试脚本 (Bash)

set -euo pipefail

CFG=${1:-./config/defaults.smoke.yaml}
MINUTES=${2:-30}
SINK=${3:-both}

echo "========================================"
echo "Orchestrator 端到端冒烟测试"
echo "========================================"
echo ""
echo "配置: $CFG"
echo "运行时长: $MINUTES 分钟"
echo "Sink 类型: $SINK"
echo ""

# 设置环境变量
export PYTHONUTF8=1

# 运行 JSONL 模式
if [ "$SINK" = "jsonl" ] || [ "$SINK" = "both" ]; then
    echo "----------------------------------------"
    echo "运行 JSONL 模式..."
    echo "----------------------------------------"
    
    python -m orchestrator.run \
        --config "$CFG" \
        --enable harvest,signal,broker,report \
        --sink jsonl \
        --minutes "$MINUTES" \
        --debug
    
    if [ $? -ne 0 ]; then
        echo "JSONL 模式测试失败！"
        exit 1
    fi
    
    echo ""
    echo "JSONL 模式测试完成"
    echo ""
fi

# 运行 SQLite 模式
if [ "$SINK" = "sqlite" ] || [ "$SINK" = "both" ]; then
    echo "----------------------------------------"
    echo "运行 SQLite 模式..."
    echo "----------------------------------------"
    
    python -m orchestrator.run \
        --config "$CFG" \
        --enable harvest,signal,broker,report \
        --sink sqlite \
        --minutes "$MINUTES" \
        --debug
    
    if [ $? -ne 0 ]; then
        echo "SQLite 模式测试失败！"
        exit 1
    fi
    
    echo ""
    echo "SQLite 模式测试完成"
    echo ""
fi

echo "========================================"
echo "所有测试完成！"
echo "========================================"

