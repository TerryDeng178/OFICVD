# -*- coding: utf-8 -*-
"""分析A组修复后的验证结果"""
import json
from pathlib import Path

# 基线数据（修复前A组结果）
baseline = {
    "trades_per_hour": 298.0,
    "avg_hold_sec": 17633.5,  # 异常值
    "cost_bps_on_turnover": 1.93,
    "win_rate_trades": 0.2953,
}

print("="*80)
print("A组修复后验证结果分析")
print("="*80 + "\n")

# A组结果
a_dir = Path("runtime/optimizer/group_a_fixed_validation")
a_backtest_dirs = list(a_dir.glob("backtest_*"))
if a_backtest_dirs:
    a_result_dir = a_backtest_dirs[0]
    a_metrics_file = a_result_dir / "metrics.json"
    
    if a_metrics_file.exists():
        with open(a_metrics_file, "r", encoding="utf-8") as f:
            a_metrics = json.load(f)
        
        a_total_trades = a_metrics.get("total_trades", 0)
        a_total_pnl = a_metrics.get("total_pnl", 0)
        a_total_fee = a_metrics.get("total_fee", 0)
        a_total_slippage = a_metrics.get("total_slippage", 0)
        a_net_pnl = a_total_pnl - a_total_fee - a_total_slippage
        
        a_trades_per_hour = a_total_trades / 1.0  # 60分钟
        a_avg_hold_sec = a_metrics.get("avg_hold_sec", 0)
        a_cost_bps_on_turnover = a_metrics.get("cost_bps_on_turnover", 0)
        a_pnl_per_trade = a_net_pnl / a_total_trades if a_total_trades > 0 else 0
        a_win_rate_trades = a_metrics.get("win_rate_trades", 0)
        
        # 检查timeout/rollover_close事件
        trades_file = a_result_dir / "trades.jsonl"
        timeout_count = 0
        rollover_count = 0
        if trades_file.exists():
            with open(trades_file, "r", encoding="utf-8") as f:
                for line in f:
                    trade = json.loads(line)
                    reason = trade.get("reason", "")
                    if reason == "timeout":
                        timeout_count += 1
                    elif reason == "rollover_close":
                        rollover_count += 1
        
        print("A组修复后结果:")
        print("-"*80)
        print(f"  交易频率: {a_trades_per_hour:.1f}笔/小时 (基线: {baseline['trades_per_hour']:.1f}, 变化: {((baseline['trades_per_hour'] - a_trades_per_hour) / baseline['trades_per_hour'] * 100):+.1f}%)")
        print(f"  平均持仓: {a_avg_hold_sec:.1f}秒 (基线: {baseline['avg_hold_sec']:.1f}秒*, 变化: {((a_avg_hold_sec - baseline['avg_hold_sec']) / baseline['avg_hold_sec'] * 100):+.1f}%)")
        print(f"  成本bps: {a_cost_bps_on_turnover:.2f}bps (基线: {baseline['cost_bps_on_turnover']:.2f}bps, 变化: {((baseline['cost_bps_on_turnover'] - a_cost_bps_on_turnover) / baseline['cost_bps_on_turnover'] * 100):+.1f}%)")
        print(f"  单笔收益: ${a_pnl_per_trade:.2f}")
        print(f"  胜率: {a_win_rate_trades:.2%} (基线: {baseline['win_rate_trades']:.2%})")
        print(f"\n  期末强制平仓事件:")
        print(f"    Timeout事件: {timeout_count}次")
        print(f"    Rollover close事件: {rollover_count}次")
        print(f"    总计: {timeout_count + rollover_count}次")
        print()

# 验收标准检查
print("="*80)
print("验收标准检查")
print("="*80 + "\n")

if a_backtest_dirs and a_metrics_file.exists():
    print("A组验收标准:")
    
    # 1. timeout或rollover_close事件计数 > 0
    exit_events_ok = (timeout_count + rollover_count) > 0
    print(f"  1. timeout/rollover_close事件计数>0: {'✅' if exit_events_ok else '❌'} ({timeout_count + rollover_count}次)")
    
    # 2. avg_hold_sec（事件对口径）≈ 300s
    hold_time_ok = 200 <= a_avg_hold_sec <= 400
    print(f"  2. avg_hold_sec（事件对口径）≈ 300s: {'✅' if hold_time_ok else '❌'} ({a_avg_hold_sec:.1f}秒)")
    
    # 3. trades_per_hour再下降≥40%（相对298/h）
    freq_improve = ((baseline['trades_per_hour'] - a_trades_per_hour) / baseline['trades_per_hour'] * 100) >= 40
    print(f"  3. trades_per_hour再下降≥40%: {'✅' if freq_improve else '❌'} ({((baseline['trades_per_hour'] - a_trades_per_hour) / baseline['trades_per_hour'] * 100):+.1f}%)")
    
    # 4. cost_bps_on_turnover明显低于1.93bps
    cost_improve = a_cost_bps_on_turnover < baseline['cost_bps_on_turnover']
    print(f"  4. cost_bps_on_turnover明显低于1.93bps: {'✅' if cost_improve else '❌'} ({a_cost_bps_on_turnover:.2f}bps)")
    
    print()
    
    # 总结
    all_passed = exit_events_ok and hold_time_ok and freq_improve and cost_improve
    print("="*80)
    print(f"验收结果: {'✅ 全部通过' if all_passed else '⚠️ 部分通过'}")
    print("="*80)

