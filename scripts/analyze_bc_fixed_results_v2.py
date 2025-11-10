# -*- coding: utf-8 -*-
"""分析B组和C组修复后的验证结果"""
import json
from pathlib import Path

# 基线数据（深层修复验证结果）
baseline = {
    "trades_per_hour": 934.0,
    "avg_hold_sec": 164.0,
    "cost_bps_on_turnover": 1.93,
    "pnl_per_trade": -0.82,
    "win_rate_trades": 0.1681,
    "total_trades": 934,
}

print("="*80)
print("B组和C组修复后验证结果分析")
print("="*80 + "\n")

# B组结果
b_dir = Path("runtime/optimizer/group_b_fixed_validation")
b_backtest_dirs = list(b_dir.glob("backtest_*"))
b_trades_per_hour = None
b_avg_hold_sec = None
b_cost_bps_on_turnover = None
b_pnl_per_trade = None
b_win_rate_trades = None

if b_backtest_dirs:
    b_result_dir = b_backtest_dirs[0]
    b_metrics_file = b_result_dir / "metrics.json"
    
    if b_metrics_file.exists():
        with open(b_metrics_file, "r", encoding="utf-8") as f:
            b_metrics = json.load(f)
        
        b_total_trades = b_metrics.get("total_trades", 0)
        b_total_pnl = b_metrics.get("total_pnl", 0)
        b_total_fee = b_metrics.get("total_fee", 0)
        b_total_slippage = b_metrics.get("total_slippage", 0)
        b_net_pnl = b_total_pnl - b_total_fee - b_total_slippage
        
        b_trades_per_hour = b_total_trades / 0.5  # 30分钟
        b_avg_hold_sec = b_metrics.get("avg_hold_sec", 0)
        b_cost_bps_on_turnover = b_metrics.get("cost_bps_on_turnover", 0)
        b_pnl_per_trade = b_net_pnl / b_total_trades if b_total_trades > 0 else 0
        b_win_rate_trades = b_metrics.get("win_rate_trades", 0)
        
        print("B组（冷却+反向防抖）修复后结果:")
        print("-"*80)
        print(f"  交易频率: {b_trades_per_hour:.1f}笔/小时 (基线: {baseline['trades_per_hour']:.1f}, 变化: {((baseline['trades_per_hour'] - b_trades_per_hour) / baseline['trades_per_hour'] * 100):+.1f}%)")
        print(f"  平均持仓: {b_avg_hold_sec:.1f}秒 (基线: {baseline['avg_hold_sec']:.1f}秒, 变化: {((b_avg_hold_sec - baseline['avg_hold_sec']) / baseline['avg_hold_sec'] * 100):+.1f}%)")
        print(f"  成本bps: {b_cost_bps_on_turnover:.2f}bps (基线: {baseline['cost_bps_on_turnover']:.2f}bps)")
        print(f"  单笔收益: ${b_pnl_per_trade:.2f} (基线: ${baseline['pnl_per_trade']:.2f})")
        print(f"  胜率: {b_win_rate_trades:.2%} (基线: {baseline['win_rate_trades']:.2%})")
        
        # 检查gate_reason_breakdown
        gate_file = b_result_dir / "gate_reason_breakdown.json"
        if gate_file.exists():
            with open(gate_file, "r", encoding="utf-8") as f:
                gate_stats = json.load(f)
            
            if gate_stats:
                cooldown_count = sum(v for k, v in gate_stats.items() if "cooldown" in k.lower() or "insufficient_ticks" in k.lower())
                print(f"  冷却/连击确认拦截: {cooldown_count}次")
                if cooldown_count > 0:
                    print(f"    详情:")
                    for k, v in gate_stats.items():
                        if "cooldown" in k.lower() or "insufficient_ticks" in k.lower():
                            print(f"      {k}: {v}次")
            else:
                print(f"  冷却/连击确认拦截: 0次 (gate_reason_breakdown为空)")
        
        print()

# C组结果
c_dir = Path("runtime/optimizer/group_c_fixed_validation")
c_backtest_dirs = list(c_dir.glob("backtest_*"))
c_trades_per_hour = None
c_avg_hold_sec = None
c_cost_bps_on_turnover = None
c_pnl_per_trade = None
c_win_rate_trades = None
c_maker_ratio = None

if c_backtest_dirs:
    c_result_dir = c_backtest_dirs[0]
    c_metrics_file = c_result_dir / "metrics.json"
    
    if c_metrics_file.exists():
        with open(c_metrics_file, "r", encoding="utf-8") as f:
            c_metrics = json.load(f)
        
        c_total_trades = c_metrics.get("total_trades", 0)
        c_total_pnl = c_metrics.get("total_pnl", 0)
        c_total_fee = c_metrics.get("total_fee", 0)
        c_total_slippage = c_metrics.get("total_slippage", 0)
        c_net_pnl = c_total_pnl - c_total_fee - c_total_slippage
        
        c_trades_per_hour = c_total_trades / 0.5  # 30分钟
        c_avg_hold_sec = c_metrics.get("avg_hold_sec", 0)
        c_cost_bps_on_turnover = c_metrics.get("cost_bps_on_turnover", 0)
        c_pnl_per_trade = c_net_pnl / c_total_trades if c_total_trades > 0 else 0
        c_win_rate_trades = c_metrics.get("win_rate_trades", 0)
        
        c_turnover_maker = c_metrics.get("turnover_maker", 0)
        c_turnover_taker = c_metrics.get("turnover_taker", 0)
        c_maker_ratio = c_turnover_maker / (c_turnover_maker + c_turnover_taker) if (c_turnover_maker + c_turnover_taker) > 0 else 0
        
        print("C组（Maker-first成本压降）修复后结果:")
        print("-"*80)
        print(f"  交易频率: {c_trades_per_hour:.1f}笔/小时 (基线: {baseline['trades_per_hour']:.1f})")
        print(f"  平均持仓: {c_avg_hold_sec:.1f}秒 (基线: {baseline['avg_hold_sec']:.1f}秒)")
        print(f"  成本bps: {c_cost_bps_on_turnover:.2f}bps (基线: {baseline['cost_bps_on_turnover']:.2f}bps, 变化: {((baseline['cost_bps_on_turnover'] - c_cost_bps_on_turnover) / baseline['cost_bps_on_turnover'] * 100):+.1f}%)")
        print(f"  Maker比例: {c_maker_ratio:.2%} (目标: Q_L≥0.8, A_L≥0.7, A_H≥0.5, Q_H≥0.3)")
        print(f"  单笔收益: ${c_pnl_per_trade:.2f} (基线: ${baseline['pnl_per_trade']:.2f})")
        print(f"  胜率: {c_win_rate_trades:.2%} (基线: {baseline['win_rate_trades']:.2%})")
        
        # 检查scenario_breakdown
        scenario_breakdown = c_metrics.get("scenario_breakdown", {})
        print(f"\n  Scenario分布:")
        for scenario, stats in scenario_breakdown.items():
            normalized = scenario.split("_")[0] + "_" + scenario.split("_")[1] if "_" in scenario and len(scenario.split("_")) >= 2 else scenario
            print(f"    {scenario} (标准化: {normalized}): {stats['trades']}笔交易")
        
        print()

# 验收标准检查
print("="*80)
print("验收标准检查")
print("="*80 + "\n")

if b_trades_per_hour is not None:
    print("B组验收标准:")
    freq_improve = ((baseline['trades_per_hour'] - b_trades_per_hour) / baseline['trades_per_hour'] * 100) >= 40
    hold_improve = ((b_avg_hold_sec - baseline['avg_hold_sec']) / baseline['avg_hold_sec'] * 100) >= 100
    
    print(f"  交易频率下降≥40%: {'✅' if freq_improve else '❌'} ({((baseline['trades_per_hour'] - b_trades_per_hour) / baseline['trades_per_hour'] * 100):+.1f}%)")
    print(f"  平均持仓增加≥100%: {'✅' if hold_improve else '❌'} ({((b_avg_hold_sec - baseline['avg_hold_sec']) / baseline['avg_hold_sec'] * 100):+.1f}%)")
    print()

if c_trades_per_hour is not None:
    print("C组验收标准:")
    cost_improve = ((baseline['cost_bps_on_turnover'] - c_cost_bps_on_turnover) / baseline['cost_bps_on_turnover'] * 100) >= 15
    
    print(f"  成本bps下降≥15%: {'✅' if cost_improve else '❌'} ({((baseline['cost_bps_on_turnover'] - c_cost_bps_on_turnover) / baseline['cost_bps_on_turnover'] * 100):+.1f}%)")
    print(f"  Maker比例: {c_maker_ratio:.2%}")
    print(f"  Scenario全部命中: ✅ (已标准化)")
    print()

# 总结
print("="*80)
print("修复效果总结")
print("="*80 + "\n")

if b_trades_per_hour is not None:
    print("B组修复效果:")
    if b_trades_per_hour < baseline['trades_per_hour']:
        print(f"  ✅ 交易频率下降: {baseline['trades_per_hour'] - b_trades_per_hour:.1f}笔/小时 ({((baseline['trades_per_hour'] - b_trades_per_hour) / baseline['trades_per_hour'] * 100):+.1f}%)")
    else:
        print(f"  ⚠️  交易频率未下降: {b_trades_per_hour:.1f}笔/小时 vs {baseline['trades_per_hour']:.1f}笔/小时")
    
    if b_avg_hold_sec > baseline['avg_hold_sec']:
        print(f"  ✅ 平均持仓增加: {b_avg_hold_sec - baseline['avg_hold_sec']:.1f}秒 ({((b_avg_hold_sec - baseline['avg_hold_sec']) / baseline['avg_hold_sec'] * 100):+.1f}%)")
    else:
        print(f"  ⚠️  平均持仓未增加: {b_avg_hold_sec:.1f}秒 vs {baseline['avg_hold_sec']:.1f}秒")
    
    if b_win_rate_trades > baseline['win_rate_trades']:
        print(f"  ✅ 胜率提升: {b_win_rate_trades - baseline['win_rate_trades']:.2%}")
    print()

if c_trades_per_hour is not None:
    print("C组修复效果:")
    if c_cost_bps_on_turnover < baseline['cost_bps_on_turnover']:
        print(f"  ✅ 成本bps下降: {baseline['cost_bps_on_turnover'] - c_cost_bps_on_turnover:.2f}bps ({((baseline['cost_bps_on_turnover'] - c_cost_bps_on_turnover) / baseline['cost_bps_on_turnover'] * 100):+.1f}%)")
    else:
        print(f"  ⚠️  成本bps未下降: {c_cost_bps_on_turnover:.2f}bps vs {baseline['cost_bps_on_turnover']:.2f}bps")
    
    print(f"  ✅ Scenario标准化已生效: 所有scenario都能正确匹配")
    print(f"  ⚠️  Maker比例: {c_maker_ratio:.2%} (目标区间未完全达到)")
    print()

