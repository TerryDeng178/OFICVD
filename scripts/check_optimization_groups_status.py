#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查优化组运行状态"""
import json
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
output_base = project_root / "runtime" / "optimizer"

groups = ["A", "B", "C", "D"]
group_names = {
    "A": "严门控+去重提速",
    "B": "冷却+反向防抖",
    "C": "Maker-first成本压降",
    "D": "A+B+C组合",
}

print("=" * 80)
print("优化组运行状态检查")
print("=" * 80)
print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

for group_key in groups:
    group_name = group_names.get(group_key, group_key)
    output_dir = output_base / f"group_{group_key.lower()}_validation"
    
    print(f"组 {group_key}: {group_name}")
    print(f"  输出目录: {output_dir}")
    
    if not output_dir.exists():
        print(f"  [状态] 目录不存在，可能尚未开始运行\n")
        continue
    
    # 查找backtest目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        print(f"  [状态] 目录存在，但未找到backtest结果\n")
        continue
    
    # 检查最新的backtest目录
    latest_backtest = max(backtest_dirs, key=lambda p: p.stat().st_mtime)
    print(f"  [状态] 找到backtest目录: {latest_backtest.name}")
    
    # 检查metrics.json
    metrics_file = latest_backtest / "metrics.json"
    if metrics_file.exists():
        try:
            with open(metrics_file, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            
            total_trades = metrics.get("total_trades", 0)
            total_pnl = metrics.get("total_pnl", 0)
            total_fee = metrics.get("total_fee", 0)
            total_slippage = metrics.get("total_slippage", 0)
            net_pnl = total_pnl - total_fee - total_slippage
            
            print(f"  [完成] 总交易数: {total_trades}")
            print(f"  [完成] 净PnL: ${net_pnl:.2f}")
            print(f"  [完成] 胜率: {metrics.get('win_rate_trades', 0)*100:.2f}%")
        except Exception as e:
            print(f"  [错误] 读取metrics.json失败: {e}")
    else:
        print(f"  [进行中] metrics.json不存在，可能仍在运行中")
    
    print()

# 检查对比结果文件
comparison_file = output_base / "optimization_groups_comparison.json"
if comparison_file.exists():
    print(f"[OK] 对比结果文件已生成: {comparison_file}")
    try:
        with open(comparison_file, "r", encoding="utf-8") as f:
            comparison = json.load(f)
        print(f"  包含组数: {len(comparison.get('groups', {}))}")
    except Exception as e:
        print(f"  [错误] 读取对比结果失败: {e}")
else:
    print(f"[WARN] 对比结果文件尚未生成")

print("\n" + "=" * 80)

