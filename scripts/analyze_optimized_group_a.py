# -*- coding: utf-8 -*-
"""分析优化后的A组实验结果"""
import json
import csv
from pathlib import Path

# 基线数据（优化前）
baseline = {
    "trades_per_hour": 264.0,
    "avg_hold_sec": 17241.5,  # 异常值
    "avg_hold_sec_actual": 368.9,  # 实际平均值（排除异常值）
    "cost_bps_on_turnover": 1.93,
    "pnl_per_trade": -0.88,
    "win_rate_trades": 0.3258,
    "total_trades": 264,
}

# 深层修复验证基线
deep_fix_baseline = {
    "trades_per_hour": 934.0,
    "avg_hold_sec": 164.0,
    "cost_bps_on_turnover": 1.93,
    "pnl_per_trade": -0.82,
    "win_rate_trades": 0.1681,
    "total_trades": 934,
}

# 查找结果目录
validation_dir = Path("runtime/optimizer/group_a_optimized_validation")
backtest_dirs = list(validation_dir.glob("backtest_*"))
if not backtest_dirs:
    print("未找到验证结果")
    exit(1)

result_dir = backtest_dirs[0]
metrics_file = result_dir / "metrics.json"
trace_file = result_dir / "trace.csv"

print("="*80)
print("优化后的A组实验结果分析")
print("="*80 + "\n")

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
print(f"   指标                    | 优化前（异常）  | 优化后        | 变化")
print(f"   ------------------------|----------------|---------------|--------")
print(f"   trades_per_hour         | {baseline['trades_per_hour']:>13.1f}  | {trades_per_hour:>13.1f}  | {trades_per_hour - baseline['trades_per_hour']:+.1f} ({((trades_per_hour - baseline['trades_per_hour']) / baseline['trades_per_hour'] * 100):+.1f}%)")
print(f"   avg_hold_sec            | {baseline['avg_hold_sec']:>13.1f}s* | {avg_hold_sec:>13.1f}s | {avg_hold_sec - baseline['avg_hold_sec_actual']:+.1f}s ({((avg_hold_sec - baseline['avg_hold_sec_actual']) / baseline['avg_hold_sec_actual'] * 100):+.1f}%)")
print(f"   cost_bps_on_turnover    | {baseline['cost_bps_on_turnover']:>13.2f}bps | {cost_bps_on_turnover:>13.2f}bps | {cost_bps_on_turnover - baseline['cost_bps_on_turnover']:+.2f}bps ({((cost_bps_on_turnover - baseline['cost_bps_on_turnover']) / baseline['cost_bps_on_turnover'] * 100):+.1f}%)")
print(f"   pnl_per_trade           | ${baseline['pnl_per_trade']:>12.2f}  | ${pnl_per_trade:>12.2f}  | ${pnl_per_trade - baseline['pnl_per_trade']:+.2f} ({((pnl_per_trade - baseline['pnl_per_trade']) / abs(baseline['pnl_per_trade']) * 100):+.1f}%)")
print(f"   win_rate_trades         | {baseline['win_rate_trades']:>13.2%}  | {win_rate_trades:>13.2%}  | {win_rate_trades - baseline['win_rate_trades']:+.2%} ({((win_rate_trades - baseline['win_rate_trades']) / baseline['win_rate_trades'] * 100):+.1f}%)")
print(f"   *优化前avg_hold_sec为异常值，实际平均值约368.9秒")
print()

# 2. 对比深层修复验证基线
print("2. 相对深层修复验证基线的改善:")
print(f"   指标                    | 深层修复基线  | 优化后        | 改善幅度")
print(f"   ------------------------|--------------|---------------|--------")
print(f"   trades_per_hour         | {deep_fix_baseline['trades_per_hour']:>11.1f}  | {trades_per_hour:>13.1f}  | {((deep_fix_baseline['trades_per_hour'] - trades_per_hour) / deep_fix_baseline['trades_per_hour'] * 100):+.1f}%")
print(f"   avg_hold_sec            | {deep_fix_baseline['avg_hold_sec']:>11.1f}s | {avg_hold_sec:>13.1f}s | {((avg_hold_sec - deep_fix_baseline['avg_hold_sec']) / deep_fix_baseline['avg_hold_sec'] * 100):+.1f}%")
print(f"   win_rate_trades         | {deep_fix_baseline['win_rate_trades']:>11.2%}  | {win_rate_trades:>13.2%}  | {((win_rate_trades - deep_fix_baseline['win_rate_trades']) / deep_fix_baseline['win_rate_trades'] * 100):+.1f}%")
print()

# 3. 验证异常持仓修复
if trace_file.exists():
    print("3. 异常持仓修复验证:")
    print()
    
    hold_times = []
    exit_reasons = {}
    long_holds = []
    
    with open(trace_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("action") == "exit":
                hold_time_s = row.get("hold_time_s", "")
                exit_reason = row.get("exit_reason", "")
                
                if hold_time_s:
                    try:
                        hold_time = float(hold_time_s)
                        hold_times.append(hold_time)
                        
                        if exit_reason:
                            exit_reasons[exit_reason] = exit_reasons.get(exit_reason, 0) + 1
                        
                        if hold_time > 3600:  # >1小时
                            long_holds.append(hold_time)
                    except (ValueError, TypeError):
                        pass
    
    if hold_times:
        hold_times.sort()
        print(f"   持仓时间分布:")
        print(f"     最小值: {min(hold_times):.1f}秒 ({min(hold_times)/60:.1f}分钟)")
        print(f"     最大值: {max(hold_times):.1f}秒 ({max(hold_times)/3600:.2f}小时)")
        print(f"     中位数: {hold_times[len(hold_times)//2]:.1f}秒 ({hold_times[len(hold_times)//2]/60:.1f}分钟)")
        print(f"     平均值: {sum(hold_times)/len(hold_times):.1f}秒 ({sum(hold_times)/len(hold_times)/60:.1f}分钟)")
        
        if long_holds:
            print(f"     ⚠️  异常持仓（>1小时）: {len(long_holds)}笔")
            print(f"     最长持仓: {max(long_holds):.1f}秒 ({max(long_holds)/3600:.2f}小时)")
        else:
            print(f"     ✅ 无异常持仓（>1小时）")
        
        print(f"\n   退出原因分布:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"     {reason}: {count}笔 ({count/len(hold_times)*100:.1f}%)")
        
        # 检查timeout退出
        timeout_count = exit_reasons.get("timeout", 0)
        rollover_count = exit_reasons.get("rollover_close", 0)
        print(f"\n   force_timeout_exit验证:")
        print(f"     timeout退出: {timeout_count}笔")
        print(f"     rollover_close退出: {rollover_count}笔")
        if timeout_count > 0:
            print(f"     ✅ force_timeout_exit正常工作，有{timeout_count}笔持仓使用timeout退出")
        else:
            print(f"     ⚠️  无timeout退出，可能所有持仓都在回测结束前已退出")
    print()

# 4. 验收标准检查
print("4. 验收标准检查:")
print()

hold_improve = avg_hold_sec >= 180  # 目标≥180s
cost_improve = cost_bps_on_turnover <= 1.75  # 目标≤1.75bps
freq_improve = trades_per_hour <= 20  # 目标≤20笔/小时

print(f"   交易频率 ≤20笔/小时: {'✅' if freq_improve else '❌'} ({trades_per_hour:.1f}笔/小时 vs 20笔/小时目标)")
print(f"   平均持仓 ≥180秒: {'✅' if hold_improve else '❌'} ({avg_hold_sec:.1f}秒 vs 180秒目标)")
print(f"   成本bps ≤1.75bps: {'✅' if cost_improve else '❌'} ({cost_bps_on_turnover:.2f}bps vs 1.75bps目标)")
print()

# 5. 总结
print("5. 优化效果总结:")
print()

improvements = []
if trades_per_hour < baseline['trades_per_hour']:
    improvements.append(f"交易频率下降 {baseline['trades_per_hour'] - trades_per_hour:.1f}笔/小时 ({((baseline['trades_per_hour'] - trades_per_hour) / baseline['trades_per_hour'] * 100):+.1f}%)")
if avg_hold_sec < baseline['avg_hold_sec'] and avg_hold_sec > 0:
    improvements.append(f"平均持仓时间修复（从异常值{baseline['avg_hold_sec']:.1f}秒修复到{avg_hold_sec:.1f}秒）")
if avg_hold_sec >= 180:
    improvements.append(f"平均持仓时间达标（{avg_hold_sec:.1f}秒 ≥ 180秒目标）")
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

if not freq_improve:
    print(f"\n   ⚠️  交易频率仍高于目标: {trades_per_hour:.1f}笔/小时 vs 20笔/小时目标（需进一步优化）")

print()

