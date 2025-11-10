# -*- coding: utf-8 -*-
"""检查trial_5验证结果"""
import json
from pathlib import Path

# 自动查找最新的metrics文件
validation_dir = Path("runtime/optimizer/trial_5_validation")
backtest_dirs = list(validation_dir.glob("backtest_*"))
if not backtest_dirs:
    print("未找到trial_5验证结果")
    exit(1)
metrics_file = backtest_dirs[0] / "metrics.json"

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

print("=== trial_5验证结果 ===")
print()
print("关键指标:")
print(f"  trades_per_hour: {trades_per_hour:.1f} (基线: 102)")
print(f"  avg_hold_sec: {avg_hold_sec:.1f}s (基线: 33s)")
print(f"  cost_bps_on_turnover: {cost_bps_on_turnover:.2f}bps (基线: 2.5bps)")
print(f"  pnl_per_trade: ${pnl_per_trade:.2f} (基线: -$1.07)")
print(f"  win_rate_trades: {win_rate_trades:.2%} (基线: 3.7%)")
print()

print("验收标准检查:")
hold_improve = avg_hold_sec >= 50
cost_improve = cost_bps_on_turnover <= 1.75
win_rate_improve = win_rate_trades >= 0.044  # 3.7% * 1.2 = 4.4%

print(f"  avg_hold_sec ↑50%: {'✅' if hold_improve else '❌'} ({avg_hold_sec:.1f}s vs 50s)")
print(f"  cost_bps ↓30%: {'✅' if cost_improve else '❌'} ({cost_bps_on_turnover:.2f}bps vs 1.75bps)")
print(f"  win_rate ↑20%: {'✅' if win_rate_improve else '❌'} ({win_rate_trades:.2%} vs 4.4%)")
print()

# 计算改善幅度
hold_improve_pct = ((avg_hold_sec - 33) / 33) * 100 if 33 > 0 else 0
cost_improve_pct = ((2.5 - cost_bps_on_turnover) / 2.5) * 100 if 2.5 > 0 else 0
win_rate_improve_pct = ((win_rate_trades - 0.037) / 0.037) * 100 if 0.037 > 0 else 0

print("改善幅度:")
print(f"  avg_hold_sec: {hold_improve_pct:+.1f}%")
print(f"  cost_bps: {cost_improve_pct:+.1f}%")
print(f"  win_rate_trades: {win_rate_improve_pct:+.1f}%")

