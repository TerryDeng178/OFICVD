# -*- coding: utf-8 -*-
"""收集所有组的测试数据"""
import json
from pathlib import Path
from collections import defaultdict
import glob

# 基线数据（深层修复验证结果）
baseline = {
    "trades_per_hour": 934.0,
    "avg_hold_sec": 164.0,
    "cost_bps_on_turnover": 1.93,
    "win_rate_trades": 0.1681,
    "pnl_per_trade": -0.82,
    "total_trades": 934,
}

groups_data = defaultdict(list)

# 收集所有metrics文件
for metrics_file in glob.glob("runtime/optimizer/group_*/backtest_*/metrics.json"):
    parts = Path(metrics_file).parts
    group_name = parts[2]  # group_a_validation, group_b_optimized_validation, etc.
    
    with open(metrics_file, "r", encoding="utf-8") as f:
        metrics = json.load(f)
    
    # 提取关键指标
    total_trades = metrics.get("total_trades", 0)
    total_pnl = metrics.get("total_pnl", 0)
    total_fee = metrics.get("total_fee", 0)
    total_slippage = metrics.get("total_slippage", 0)
    net_pnl = total_pnl - total_fee - total_slippage
    
    trades_per_hour = total_trades / 1.0  # 60分钟
    avg_hold_sec = metrics.get("avg_hold_sec", 0)
    cost_bps_on_turnover = metrics.get("cost_bps_on_turnover", 0)
    pnl_per_trade = net_pnl / total_trades if total_trades > 0 else 0
    win_rate_trades = metrics.get("win_rate_trades", 0)
    
    turnover_maker = metrics.get("turnover_maker", 0)
    turnover_taker = metrics.get("turnover_taker", 0)
    maker_ratio = turnover_maker / (turnover_maker + turnover_taker) if (turnover_maker + turnover_taker) > 0 else 0
    
    groups_data[group_name].append({
        "file": metrics_file,
        "trades_per_hour": trades_per_hour,
        "avg_hold_sec": avg_hold_sec,
        "cost_bps_on_turnover": cost_bps_on_turnover,
        "pnl_per_trade": pnl_per_trade,
        "win_rate_trades": win_rate_trades,
        "total_trades": total_trades,
        "net_pnl": net_pnl,
        "maker_ratio": maker_ratio,
        "max_drawdown": metrics.get("max_drawdown", 0),
    })

# 按组整理数据
group_summary = {}
for group_name, tests in groups_data.items():
    # 按时间排序，最新的在前
    tests.sort(key=lambda x: x["file"], reverse=True)
    
    # 提取组类型（a, b, c, d）
    if "group_a" in group_name:
        group_type = "A"
    elif "group_b" in group_name:
        group_type = "B"
    elif "group_c" in group_name:
        group_type = "C"
    elif "group_d" in group_name:
        group_type = "D"
    else:
        continue
    
    if group_type not in group_summary:
        group_summary[group_type] = {
            "tests": [],
            "latest": None,
            "best": None,
        }
    
    for test in tests:
        group_summary[group_type]["tests"].append(test)
    
    # 最新测试
    if tests:
        group_summary[group_type]["latest"] = tests[0]
    
    # 最佳测试（按综合评分）
    if tests:
        # 评分：胜率 + 单笔收益 + 交易频率下降 + 平均持仓提升
        for test in tests:
            freq_score = (baseline["trades_per_hour"] - test["trades_per_hour"]) / baseline["trades_per_hour"] * 100
            hold_score = (test["avg_hold_sec"] - baseline["avg_hold_sec"]) / baseline["avg_hold_sec"] * 100
            test["score"] = (
                test["win_rate_trades"] * 100 +
                test["pnl_per_trade"] * 10 +
                freq_score * 0.1 +
                hold_score * 0.1
            )
        
        group_summary[group_type]["best"] = max(tests, key=lambda x: x["score"])

# 输出JSON
output = {
    "baseline": baseline,
    "groups": {}
}

for group_type, data in group_summary.items():
    output["groups"][group_type] = {
        "test_count": len(data["tests"]),
        "latest": data["latest"],
        "best": data["best"],
        "all_tests": data["tests"],
    }

with open("runtime/optimizer/all_groups_summary.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print("数据收集完成，已保存到 runtime/optimizer/all_groups_summary.json")
print(f"\n各组测试数量:")
for group_type, data in group_summary.items():
    print(f"  {group_type}组: {len(data['tests'])}次测试")

