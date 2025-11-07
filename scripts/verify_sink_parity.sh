#!/bin/bash
# P1-G: 双 Sink 结果对齐的"自动回归"
# 同一窗口分别跑 JSONL/SQLite 两轮，对比统计结果（容忍 ≤10% 差）
# P0: 使用 REPLAY 模式固定输入，提高可重复性

set -e

CONFIG="${1:-./config/defaults.replay.yaml}"
MINUTES="${2:-2}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/runtime"

# P0: 强制使用 REPLAY 模式，固定输入数据窗口
export V13_REPLAY_MODE=1

echo "========================================"
echo "双 Sink 结果对齐回归测试"
echo "========================================"
echo ""
echo "配置: ${CONFIG}"
echo "运行时长: ${MINUTES} 分钟"
echo "输出目录: ${OUTPUT_DIR}"
echo ""

# 清理之前的输出
rm -rf "${OUTPUT_DIR}/ready/signal" "${OUTPUT_DIR}/signals.db" "${OUTPUT_DIR}/mock_orders.jsonl" 2>/dev/null || true

# 运行 JSONL 模式
echo "----------------------------------------"
echo "运行 JSONL 模式..."
echo "----------------------------------------"
python -m orchestrator.run \
    --config "${CONFIG}" \
    --enable signal,report \
    --sink jsonl \
    --minutes "${MINUTES}" \
    --debug

if [ $? -ne 0 ]; then
    echo "JSONL 模式测试失败！"
    exit 1
fi

# P1: 使用 Python glob+mtime 选文件，避免平台差异（macOS 不支持 GNU find -printf）
# 读取 JSONL 报表
JSONL_REPORT=$(python3 <<EOF
import glob
import os
reports = glob.glob("${PROJECT_ROOT}/logs/report/summary_*.json")
if reports:
    latest = max(reports, key=os.path.getmtime)
    print(latest)
EOF
)
if [ -z "$JSONL_REPORT" ]; then
    echo "未找到 JSONL 报表文件"
    exit 1
fi

echo ""
echo "JSONL 报表: ${JSONL_REPORT}"

# 清理输出（保留报表）
rm -rf "${OUTPUT_DIR}/ready/signal" "${OUTPUT_DIR}/mock_orders.jsonl" 2>/dev/null || true

# 运行 SQLite 模式
echo ""
echo "----------------------------------------"
echo "运行 SQLite 模式..."
echo "----------------------------------------"
python -m orchestrator.run \
    --config "${CONFIG}" \
    --enable signal,report \
    --sink sqlite \
    --minutes "${MINUTES}" \
    --debug

if [ $? -ne 0 ]; then
    echo "SQLite 模式测试失败！"
    exit 1
fi

# P1: 使用 Python glob+mtime 选文件，避免平台差异
# 读取 SQLite 报表（排除 JSONL 报表）
SQLITE_REPORT=$(python3 <<EOF
import glob
import os
reports = sorted(glob.glob("${PROJECT_ROOT}/logs/report/summary_*.json"), key=os.path.getmtime, reverse=True)
jsonl_report = "${JSONL_REPORT}"
for r in reports:
    if r != jsonl_report:
        print(r)
        break
EOF
)
if [ -z "$SQLITE_REPORT" ]; then
    echo "未找到 SQLite 报表文件"
    exit 1
fi

echo ""
echo "SQLite 报表: ${SQLITE_REPORT}"

# 对比统计结果
echo ""
echo "----------------------------------------"
echo "对比统计结果..."
echo "----------------------------------------"

python3 <<EOF
import json
import sys
from datetime import datetime

# 读取报表
with open("${JSONL_REPORT}", "r", encoding="utf-8") as f:
    jsonl_data = json.load(f)

with open("${SQLITE_REPORT}", "r", encoding="utf-8") as f:
    sqlite_data = json.load(f)

# 对比指标
metrics = [
    ("total", "总信号数"),
    ("buy_count", "买入信号"),
    ("sell_count", "卖出信号"),
    ("strong_buy_count", "强买入"),
    ("strong_sell_count", "强卖出"),
]

failed = False
# 调整对齐阈值：核心计数类 5%，比率类 10%
core_metrics = ["total", "buy_count", "sell_count", "strong_buy_count", "strong_sell_count"]
for key, name in metrics:
    jsonl_val = jsonl_data.get(key, 0)
    sqlite_val = sqlite_data.get(key, 0)
    
    if jsonl_val == 0 and sqlite_val == 0:
        diff_pct = 0.0
    elif jsonl_val == 0:
        diff_pct = 100.0
    else:
        diff_pct = abs(jsonl_val - sqlite_val) / jsonl_val * 100
    
    # 核心计数类使用 5% 阈值，其他使用 10%
    threshold = 5.0 if key in core_metrics else 10.0
    status = "✓" if diff_pct <= threshold else "✗"
    print(f"{status} {name}: JSONL={jsonl_val}, SQLite={sqlite_val}, 差异={diff_pct:.2f}% (阈值={threshold}%)")
    
    if diff_pct > threshold:
        failed = True

# 对比强信号比例
jsonl_strong_ratio = jsonl_data.get("strong_ratio", 0.0)
sqlite_strong_ratio = sqlite_data.get("strong_ratio", 0.0)
if jsonl_strong_ratio > 0:
    strong_ratio_diff_pct = abs(jsonl_strong_ratio - sqlite_strong_ratio) / jsonl_strong_ratio * 100
else:
    strong_ratio_diff_pct = 0.0

status = "✓" if strong_ratio_diff_pct <= 10.0 else "✗"
print(f"{status} 强信号比例: JSONL={jsonl_strong_ratio:.4f}, SQLite={sqlite_strong_ratio:.4f}, 差异={strong_ratio_diff_pct:.2f}%")

if strong_ratio_diff_pct > 10.0:
    failed = True

# P1: 扩充"双 Sink 对齐"核对维度 - 护栏分解一致性
print("")
print("对比护栏分解...")
jsonl_gating = jsonl_data.get("gating_breakdown", {})
sqlite_gating = sqlite_data.get("gating_breakdown", {})

if jsonl_gating and sqlite_gating:
    all_reasons = set(jsonl_gating.keys()) | set(sqlite_gating.keys())
    for reason in all_reasons:
        jsonl_val = jsonl_gating.get(reason, 0)
        sqlite_val = sqlite_gating.get(reason, 0)
        
        if jsonl_val == 0 and sqlite_val == 0:
            diff_pct = 0.0
        elif jsonl_val == 0:
            diff_pct = 100.0
        else:
            diff_pct = abs(jsonl_val - sqlite_val) / jsonl_val * 100
        
        # 护栏分解使用 10% 阈值（非核心计数类）
        threshold = 10.0
        status = "✓" if diff_pct <= threshold else "✗"
        print(f"{status} 护栏[{reason}]: JSONL={jsonl_val}, SQLite={sqlite_val}, 差异={diff_pct:.2f}% (阈值={threshold}%)")
        
        if diff_pct > threshold:
            failed = True

# P0: 扩充"双 Sink 对齐"核对维度 - 分钟节律一致性（重叠窗口对齐）
print("")
print("对比分钟节律（重叠窗口对齐）...")
jsonl_per_minute = jsonl_data.get("per_minute", [])
sqlite_per_minute = sqlite_data.get("per_minute", [])

if jsonl_per_minute and sqlite_per_minute:
    # P0: 取分钟键的交集，避免吞吐差导致的时间片不重叠
    jsonl_minute_keys = {item.get("minute") for item in jsonl_per_minute}
    sqlite_minute_keys = {item.get("minute") for item in sqlite_per_minute}
    overlap_keys = sorted(jsonl_minute_keys & sqlite_minute_keys)
    
    if overlap_keys:
        print(f"重叠窗口: {len(overlap_keys)} 个分钟（JSONL: {len(jsonl_minute_keys)}, SQLite: {len(sqlite_minute_keys)}）")
        
        # 构建分钟键到计数的映射
        jsonl_minute_map = {item.get("minute"): item.get("count", 0) for item in jsonl_per_minute}
        sqlite_minute_map = {item.get("minute"): item.get("count", 0) for item in sqlite_per_minute}
        
        # 对交集窗口求和
        jsonl_overlap_total = sum(jsonl_minute_map.get(k, 0) for k in overlap_keys)
        sqlite_overlap_total = sum(sqlite_minute_map.get(k, 0) for k in overlap_keys)
        
        # 对比交集窗口汇总值（使用核心计数类 5% 阈值）
        if jsonl_overlap_total == 0 and sqlite_overlap_total == 0:
            overlap_diff_pct = 0.0
        elif jsonl_overlap_total == 0:
            overlap_diff_pct = 100.0
        else:
            overlap_diff_pct = abs(jsonl_overlap_total - sqlite_overlap_total) / jsonl_overlap_total * 100
        
        threshold = 5.0  # 核心计数类使用 5% 阈值
        status = "✓" if overlap_diff_pct <= threshold else "✗"
        print(f"{status} 重叠窗口汇总: JSONL={jsonl_overlap_total}, SQLite={sqlite_overlap_total}, 差异={overlap_diff_pct:.2f}% (阈值={threshold}%)")
        
        if overlap_diff_pct > threshold:
            failed = True
        
        # P0: 逐分钟对比并计算差异，用于生成 Top N 差异分钟列表
        minute_diffs = []
        for minute_key in overlap_keys:
            jsonl_count = jsonl_minute_map.get(minute_key, 0)
            sqlite_count = sqlite_minute_map.get(minute_key, 0)
            
            if jsonl_count == 0 and sqlite_count == 0:
                diff_pct = 0.0
            elif jsonl_count == 0:
                diff_pct = 100.0
            else:
                diff_pct = abs(jsonl_count - sqlite_count) / jsonl_count * 100
            
            minute_human = next((item.get("minute_human", "") for item in jsonl_per_minute if item.get("minute") == minute_key), str(minute_key))
            minute_diffs.append({
                "minute": minute_key,
                "minute_human": minute_human,
                "jsonl_count": jsonl_count,
                "sqlite_count": sqlite_count,
                "diff_pct": diff_pct
            })
        
        # 按差异百分比排序
        minute_diffs.sort(key=lambda x: x["diff_pct"], reverse=True)
        
        # 逐分钟对比（使用 10% 阈值，非核心计数类）
        print("")
        print("逐分钟对比（重叠窗口，按差异排序）:")
        threshold = 10.0  # 分钟节律使用 10% 阈值（非核心计数类）
        for item in minute_diffs[:10]:  # 只显示前10个
            status = "✓" if item["diff_pct"] <= threshold else "✗"
            print(f"  {status} {item['minute_human']} [{item['minute']}]: JSONL={item['jsonl_count']}, SQLite={item['sqlite_count']}, 差异={item['diff_pct']:.2f}%")
        
        # P0: 收集阈值外的分钟列表
        threshold_exceeded_minutes = [item for item in minute_diffs if item["diff_pct"] > threshold]
    else:
        print("⚠️  警告: 无重叠窗口，无法进行分钟节律对比")
        failed = True
        minute_diffs = []
        threshold_exceeded_minutes = []

# P0: 将"重叠窗口对比"与"吞吐区间一致性"结合
# 校验两个报表的 first_minute/last_minute 差距是否在 1-2 分钟内
jsonl_first_minute = jsonl_data.get("first_minute")
jsonl_last_minute = jsonl_data.get("last_minute")
sqlite_first_minute = sqlite_data.get("first_minute")
sqlite_last_minute = sqlite_data.get("last_minute")

window_alignment_passed = True
window_alignment_warning = None
first_diff = None
last_diff = None

if jsonl_first_minute and sqlite_first_minute and jsonl_last_minute and sqlite_last_minute:
    # 计算分钟键差异（假设分钟键为整数，表示从某个基准时间开始的分钟数）
    if isinstance(jsonl_first_minute, int) and isinstance(sqlite_first_minute, int):
        first_diff = abs(jsonl_first_minute - sqlite_first_minute)
    if isinstance(jsonl_last_minute, int) and isinstance(sqlite_last_minute, int):
        last_diff = abs(jsonl_last_minute - sqlite_last_minute)
    
    # 如果差异超过 2 分钟，给出警告
    if first_diff is not None and first_diff > 2:
        window_alignment_passed = False
        window_alignment_warning = f"first_minute 差异过大: JSONL={jsonl_first_minute}, SQLite={sqlite_first_minute}, 差异={first_diff}分钟"
    if last_diff is not None and last_diff > 2:
        window_alignment_passed = False
        if window_alignment_warning:
            window_alignment_warning += f"; last_minute 差异过大: JSONL={jsonl_last_minute}, SQLite={sqlite_last_minute}, 差异={last_diff}分钟"
        else:
            window_alignment_warning = f"last_minute 差异过大: JSONL={jsonl_last_minute}, SQLite={sqlite_last_minute}, 差异={last_diff}分钟"
    
    if window_alignment_warning:
        print("")
        print(f"⚠️  警告: {window_alignment_warning}")
        print("   这可能是窗口未对齐导致的，而非吞吐差")

# P1-D: CI Job 通过与失败的"证据包"标准化
# 生成 parity_diff.json（含每项 diff、交集窗口范围、阈值与是否通过）
parity_diff = {
    "timestamp": datetime.now().isoformat(),
    "jsonl_report": "${JSONL_REPORT}",
    "sqlite_report": "${SQLITE_REPORT}",
    "core_metrics": {},
    "strong_ratio": {
        "jsonl": jsonl_strong_ratio,
        "sqlite": sqlite_strong_ratio,
        "diff_pct": strong_ratio_diff_pct if jsonl_strong_ratio > 0 else 0.0,
        "threshold": 10.0,
        "passed": strong_ratio_diff_pct <= 10.0 if jsonl_strong_ratio > 0 else True
    },
    "gating_breakdown": {},
    # P0: 窗口对齐检查
    "window_alignment": {
        "jsonl_first_minute": jsonl_first_minute,
        "jsonl_last_minute": jsonl_last_minute,
        "sqlite_first_minute": sqlite_first_minute,
        "sqlite_last_minute": sqlite_last_minute,
        "first_diff": first_diff,
        "last_diff": last_diff,
        "threshold_minutes": 2,
        "passed": window_alignment_passed,
        "warning": window_alignment_warning
    },
    "overlap_window": {
        "overlap_keys": overlap_keys if 'overlap_keys' in locals() else [],
        "overlap_count": len(overlap_keys) if 'overlap_keys' in locals() else 0,
        "jsonl_overlap_total": jsonl_overlap_total if 'jsonl_overlap_total' in locals() else 0,
        "sqlite_overlap_total": sqlite_overlap_total if 'sqlite_overlap_total' in locals() else 0,
        "overlap_diff_pct": overlap_diff_pct if 'overlap_diff_pct' in locals() else 0.0,
        "threshold": 5.0,
        "passed": overlap_diff_pct <= 5.0 if 'overlap_diff_pct' in locals() and 'overlap_keys' in locals() and len(overlap_keys) > 0 else True
    },
    # P0: Parity 证据包里新增"Top N 差异分钟"与"阈值外分钟列表"
    "top_minute_diffs": minute_diffs[:20] if 'minute_diffs' in locals() else [],  # Top 20 差异分钟
    "threshold_exceeded_minutes": threshold_exceeded_minutes if 'threshold_exceeded_minutes' in locals() else [],  # 阈值外分钟列表
    "overall_passed": not failed
}

# 填充核心指标
for key, name in metrics:
    jsonl_val = jsonl_data.get(key, 0)
    sqlite_val = sqlite_data.get(key, 0)
    if jsonl_val == 0 and sqlite_val == 0:
        diff_pct = 0.0
    elif jsonl_val == 0:
        diff_pct = 100.0
    else:
        diff_pct = abs(jsonl_val - sqlite_val) / jsonl_val * 100
    threshold = 5.0 if key in core_metrics else 10.0
    parity_diff["core_metrics"][key] = {
        "jsonl": jsonl_val,
        "sqlite": sqlite_val,
        "diff_pct": diff_pct,
        "threshold": threshold,
        "passed": diff_pct <= threshold
    }

# 填充护栏分解
if jsonl_gating and sqlite_gating:
    all_reasons = set(jsonl_gating.keys()) | set(sqlite_gating.keys())
    for reason in all_reasons:
        jsonl_val = jsonl_gating.get(reason, 0)
        sqlite_val = sqlite_gating.get(reason, 0)
        if jsonl_val == 0 and sqlite_val == 0:
            diff_pct = 0.0
        elif jsonl_val == 0:
            diff_pct = 100.0
        else:
            diff_pct = abs(jsonl_val - sqlite_val) / jsonl_val * 100
        threshold = 10.0
        parity_diff["gating_breakdown"][reason] = {
            "jsonl": jsonl_val,
            "sqlite": sqlite_val,
            "diff_pct": diff_pct,
            "threshold": threshold,
            "passed": diff_pct <= threshold
        }

# 保存证据包
import os
parity_diff_file = os.path.join("${PROJECT_ROOT}", "logs", "report", f"parity_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
os.makedirs(os.path.dirname(parity_diff_file), exist_ok=True)
with open(parity_diff_file, "w", encoding="utf-8") as f:
    json.dump(parity_diff, f, ensure_ascii=False, indent=2)

print("")
print(f"证据包已保存: {parity_diff_file}")

if failed:
    print("")
    print("❌ 部分指标差异超过阈值，请检查统计口径一致性")
    sys.exit(1)
else:
    print("")
    print("✅ 所有指标差异在容忍范围内，统计一致性验证通过")
    sys.exit(0)
EOF

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 双 Sink 结果对齐回归测试通过"
else
    echo "❌ 双 Sink 结果对齐回归测试失败"
fi

exit $EXIT_CODE

