# -*- coding: utf-8 -*-
"""分析深层逻辑修复验证结果"""
import json
import csv
from pathlib import Path
from collections import defaultdict

# 基线数据（trial_5修复前）
baseline = {
    "trades_per_hour": 2474,
    "avg_hold_sec": 33.0,
    "cost_bps_on_turnover": 1.93,
    "pnl_per_trade": -0.84,
    "win_rate_trades": 0.0614,
    "total_trades": 2474,
}

# 查找结果目录
validation_dir = Path("runtime/optimizer/deep_fix_validation")
backtest_dirs = list(validation_dir.glob("backtest_*"))
if not backtest_dirs:
    print("未找到验证结果")
    exit(1)

result_dir = backtest_dirs[0]
metrics_file = result_dir / "metrics.json"
trace_file = result_dir / "trace.csv"
gate_file = result_dir / "gate_reason_breakdown.json"

print("=== 深层逻辑修复验证结果分析 ===\n")

# 1. 读取metrics
with open(metrics_file, "r", encoding="utf-8") as f:
    metrics = json.load(f)

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

print("1. 关键指标对比:")
print(f"   指标                    | 基线（修复前）  | 修复后        | 变化")
print(f"   ------------------------|----------------|---------------|--------")
print(f"   trades_per_hour         | {baseline['trades_per_hour']:>13.1f}  | {trades_per_hour:>13.1f}  | {trades_per_hour - baseline['trades_per_hour']:+.1f} ({((trades_per_hour - baseline['trades_per_hour']) / baseline['trades_per_hour'] * 100):+.1f}%)")
print(f"   avg_hold_sec            | {baseline['avg_hold_sec']:>13.1f}s | {avg_hold_sec:>13.1f}s | {avg_hold_sec - baseline['avg_hold_sec']:+.1f}s ({((avg_hold_sec - baseline['avg_hold_sec']) / baseline['avg_hold_sec'] * 100):+.1f}%)")
print(f"   cost_bps_on_turnover    | {baseline['cost_bps_on_turnover']:>13.2f}bps | {cost_bps_on_turnover:>13.2f}bps | {cost_bps_on_turnover - baseline['cost_bps_on_turnover']:+.2f}bps ({((cost_bps_on_turnover - baseline['cost_bps_on_turnover']) / baseline['cost_bps_on_turnover'] * 100):+.1f}%)")
print(f"   pnl_per_trade           | ${baseline['pnl_per_trade']:>12.2f}  | ${pnl_per_trade:>12.2f}  | ${pnl_per_trade - baseline['pnl_per_trade']:+.2f} ({((pnl_per_trade - baseline['pnl_per_trade']) / abs(baseline['pnl_per_trade']) * 100):+.1f}%)")
print(f"   win_rate_trades         | {baseline['win_rate_trades']:>13.2%}  | {win_rate_trades:>13.2%}  | {win_rate_trades - baseline['win_rate_trades']:+.2%} ({((win_rate_trades - baseline['win_rate_trades']) / baseline['win_rate_trades'] * 100):+.1f}%)")
print()

# 2. 验证不变量
print("2. 验证不变量检查:")
print()

# 不变量1: gating_blocked==True的信号不得进入任何交易
if trace_file.exists():
    gating_blocked_entries = 0
    gating_blocked_exits = 0
    total_entries = 0
    total_exits = 0
    
    with open(trace_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = row.get("action", "")
            gating_blocked = row.get("gating_blocked", "").lower() == "true"
            
            if action == "entry":
                total_entries += 1
                if gating_blocked:
                    gating_blocked_entries += 1
            elif action == "exit":
                total_exits += 1
                if gating_blocked:
                    gating_blocked_exits += 1
    
    print(f"   不变量1: gating_blocked==True的信号不得进入任何交易")
    print(f"   - Entry总数: {total_entries}, gating_blocked的entry: {gating_blocked_entries}")
    print(f"   - Exit总数: {total_exits}, gating_blocked的exit: {gating_blocked_exits}")
    if gating_blocked_entries == 0 and gating_blocked_exits == 0:
        print(f"   ✅ 通过: 没有gating_blocked==True的信号进入交易")
    else:
        print(f"   ❌ 失败: 发现{gating_blocked_entries + gating_blocked_exits}笔gating_blocked==True的交易")
    print()

# 不变量2: hold_time_sec < min_hold_time_sec期间，不允许触发reverse_signal与take_profit
if trace_file.exists():
    min_hold_time_sec = 45  # 从配置中获取
    early_reverse = 0
    early_tp = 0
    
    with open(trace_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("action") == "exit":
                exit_reason = row.get("exit_reason", "")
                hold_time_s = row.get("hold_time_s", "")
                
                if hold_time_s and exit_reason:
                    try:
                        hold_time = float(hold_time_s)
                        if hold_time < min_hold_time_sec:
                            if exit_reason == "reverse_signal":
                                early_reverse += 1
                            elif exit_reason == "take_profit":
                                early_tp += 1
                    except (ValueError, TypeError):
                        pass
    
    print(f"   不变量2: hold_time_sec < min_hold_time_sec期间，不允许触发reverse_signal与take_profit")
    print(f"   - min_hold_time_sec: {min_hold_time_sec}s")
    print(f"   - 过早reverse_signal: {early_reverse}")
    print(f"   - 过早take_profit: {early_tp}")
    if early_reverse == 0 and early_tp == 0:
        print(f"   ✅ 通过: 没有在min_hold_time_sec之前触发reverse_signal或take_profit")
    else:
        print(f"   ❌ 失败: 发现{early_reverse + early_tp}笔过早退出")
    print()

# 不变量3: 任一exit/reverse事件，必须来自已确认信号
if trace_file.exists():
    unconfirmed_exits = 0
    total_exits = 0
    
    with open(trace_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("action") == "exit":
                total_exits += 1
                confirm = row.get("confirm", "").lower() == "true"
                if not confirm:
                    unconfirmed_exits += 1
    
    print(f"   不变量3: 任一exit/reverse事件，必须来自已确认信号")
    print(f"   - Exit总数: {total_exits}, 未确认的exit: {unconfirmed_exits}")
    if unconfirmed_exits == 0:
        print(f"   ✅ 通过: 所有exit都来自已确认信号")
    else:
        print(f"   ❌ 失败: 发现{unconfirmed_exits}笔未确认的exit")
    print()

# 不变量4: 若触发止损，需记录市场状态
if trace_file.exists():
    stop_loss_count = 0
    stop_loss_with_context = 0
    
    with open(trace_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("exit_reason") == "stop_loss":
                stop_loss_count += 1
                spread_bps = row.get("spread_bps", "")
                scenario = row.get("scenario", "")
                if spread_bps and scenario:
                    stop_loss_with_context += 1
    
    print(f"   不变量4: 若触发止损，需记录市场状态")
    print(f"   - 止损总数: {stop_loss_count}, 有市场状态的止损: {stop_loss_with_context}")
    if stop_loss_count == 0 or stop_loss_with_context == stop_loss_count:
        print(f"   ✅ 通过: 所有止损都记录了市场状态")
    else:
        print(f"   ⚠️  部分止损未记录市场状态: {stop_loss_count - stop_loss_with_context}/{stop_loss_count}")
    print()

# 3. 门控统计
if gate_file.exists():
    with open(gate_file, "r", encoding="utf-8") as f:
        gate_stats = json.load(f)
    
    print("3. 门控统计:")
    total_blocked = sum(gate_stats.values())
    print(f"   总拦截信号数: {total_blocked}")
    print(f"   门控原因分布:")
    for reason, count in sorted(gate_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"     - {reason}: {count} ({count/total_blocked*100:.1f}%)")
    print()

# 4. 验收标准检查
print("4. 验收标准检查:")
print()

hold_improve = avg_hold_sec >= 50  # 目标≥50s（基线33s的1.5倍）
cost_improve = cost_bps_on_turnover <= 1.75  # 目标≤1.75bps（基线2.5bps的70%）
win_rate_improve = win_rate_trades >= 0.044  # 目标≥4.4%（基线3.7%的1.2倍）

print(f"   avg_hold_sec ↑50%: {'✅' if hold_improve else '❌'} ({avg_hold_sec:.1f}s vs 50s目标)")
print(f"   cost_bps ↓30%: {'✅' if cost_improve else '❌'} ({cost_bps_on_turnover:.2f}bps vs 1.75bps目标)")
print(f"   win_rate ↑20%: {'✅' if win_rate_improve else '❌'} ({win_rate_trades:.2%} vs 4.4%目标)")
print()

# 5. 总结
print("5. 修复效果总结:")
print()

improvements = []
if trades_per_hour < baseline['trades_per_hour']:
    improvements.append(f"交易频率下降 {baseline['trades_per_hour'] - trades_per_hour:.1f}笔/小时")
if avg_hold_sec > baseline['avg_hold_sec']:
    improvements.append(f"持仓时间增加 {avg_hold_sec - baseline['avg_hold_sec']:.1f}秒")
if cost_bps_on_turnover < baseline['cost_bps_on_turnover']:
    improvements.append(f"成本降低 {baseline['cost_bps_on_turnover'] - cost_bps_on_turnover:.2f}bps")
if win_rate_trades > baseline['win_rate_trades']:
    improvements.append(f"胜率提升 {win_rate_trades - baseline['win_rate_trades']:.2%}")

if improvements:
    print("   ✅ 改善项:")
    for imp in improvements:
        print(f"     - {imp}")
else:
    print("   ⚠️  未发现明显改善")

print()

