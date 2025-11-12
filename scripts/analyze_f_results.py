#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析F系列实验结果"""
import json
import statistics
from pathlib import Path

def analyze_results(results_file: Path):
    """分析实验结果"""
    with open(results_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    successful = [t for t in data if t.get('success')]
    failed = [t for t in data if not t.get('success')]
    
    print(f"总trial数: {len(data)}")
    print(f"成功: {len(successful)} ({len(successful)/len(data)*100:.1f}%)")
    print(f"失败: {len(failed)} ({len(failed)/len(data)*100:.1f}%)")
    
    if not successful:
        print("\n没有成功的trial")
        return
    
    # 提取指标
    metrics_list = [t.get('metrics', {}) for t in successful]
    win_rates = [m.get('win_rate_trades', 0) for m in metrics_list if 'win_rate_trades' in m]
    pnl_nets = [m.get('pnl_net', 0) for m in metrics_list if 'pnl_net' in m]
    avg_pnls = [m.get('avg_pnl_per_trade', 0) for m in metrics_list if 'avg_pnl_per_trade' in m]
    total_trades = [m.get('total_trades', 0) for m in metrics_list if 'total_trades' in m]
    scores = [t.get('score', 0) for t in successful if 'score' in t]
    
    print(f"\n成功trial的指标统计:")
    if win_rates:
        print(f"  win_rate_trades: 平均={statistics.mean(win_rates)*100:.2f}%, 中位数={statistics.median(win_rates)*100:.2f}%, 最大={max(win_rates)*100:.2f}%")
    if pnl_nets:
        print(f"  pnl_net: 平均=${statistics.mean(pnl_nets):.2f}, 中位数=${statistics.median(pnl_nets):.2f}, 最大=${max(pnl_nets):.2f}")
    if avg_pnls:
        print(f"  avg_pnl_per_trade: 平均=${statistics.mean(avg_pnls):.2f}, 中位数=${statistics.median(avg_pnls):.2f}, 最大=${max(avg_pnls):.2f}")
    if total_trades:
        print(f"  total_trades: 平均={statistics.mean(total_trades):.1f}, 中位数={statistics.median(total_trades):.1f}")
    if scores:
        print(f"  score: 平均={statistics.mean(scores):.2f}, 中位数={statistics.median(scores):.2f}, 最大={max(scores):.2f}")
    
    # 目标条件检查
    target_met = [
        t for t in successful 
        if t.get('metrics', {}).get('win_rate_trades', 0) >= 0.35 
        and t.get('metrics', {}).get('avg_pnl_per_trade', 0) >= 0 
        and t.get('metrics', {}).get('pnl_net', 0) >= 0
    ]
    
    print(f"\n目标条件检查:")
    print(f"  目标: win_rate_trades≥35%, avg_pnl_per_trade≥0, pnl_net≥0")
    print(f"  满足条件的trial数: {len(target_met)} / {len(successful)} ({len(target_met)/len(successful)*100:.1f}%)")
    
    # Top 5 trials
    if successful:
        top5 = sorted(successful, key=lambda x: x.get('score', 0), reverse=True)[:5]
        print(f"\nTop 5 trials by score:")
        for i, t in enumerate(top5, 1):
            m = t.get('metrics', {})
            print(f"  {i}. Trial {t.get('trial_id')}: score={t.get('score', 0):.4f}")
            print(f"     win_rate={m.get('win_rate_trades', 0)*100:.2f}%, pnl_net=${m.get('pnl_net', 0):.2f}, avg_pnl=${m.get('avg_pnl_per_trade', 0):.2f}, trades={m.get('total_trades', 0)}")
    
    # 满足目标条件的Top 5
    if target_met:
        top5_target = sorted(target_met, key=lambda x: x.get('score', 0), reverse=True)[:5]
        print(f"\n满足目标条件的Top 5 trials:")
        for i, t in enumerate(top5_target, 1):
            m = t.get('metrics', {})
            print(f"  {i}. Trial {t.get('trial_id')}: score={t.get('score', 0):.4f}")
            print(f"     win_rate={m.get('win_rate_trades', 0)*100:.2f}%, pnl_net=${m.get('pnl_net', 0):.2f}, avg_pnl=${m.get('avg_pnl_per_trade', 0):.2f}, trades={m.get('total_trades', 0)}")

if __name__ == "__main__":
    results_file = Path("runtime/optimizer/stage1_20251111_145408/trial_results.json")
    if results_file.exists():
        analyze_results(results_file)
    else:
        print(f"结果文件不存在: {results_file}")

