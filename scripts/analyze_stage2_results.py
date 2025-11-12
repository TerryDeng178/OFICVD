#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析STAGE-2实验结果"""
import json
import sys
from pathlib import Path
from collections import defaultdict

def analyze_results(results_file: Path):
    """分析实验结果"""
    with open(results_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    trials = [t for t in data if t.get('success')]
    
    print("=" * 100)
    print("STAGE-2实验结果统计")
    print("=" * 100)
    print(f"\n总trial数: {len(data)}")
    print(f"成功trial数: {len(trials)}")
    print(f"失败trial数: {len(data) - len(trials)}")
    
    if not trials:
        print("\n没有成功的trial，无法进行统计分析")
        return
    
    # 关键指标统计
    print("\n" + "=" * 100)
    print("关键指标统计（成功trial）")
    print("=" * 100)
    
    pnl_nets = [t['metrics']['pnl_net'] for t in trials]
    avg_pnls = [t['metrics']['avg_pnl_per_trade'] for t in trials]
    win_rates = [t['metrics']['win_rate_trades'] for t in trials]
    trades_counts = [t['metrics']['total_trades'] for t in trials]
    cost_bps = [t['metrics'].get('cost_bps_on_turnover', 0) for t in trials]
    scores = [t.get('score', 0) for t in trials]
    
    print(f"\npnl_net:")
    print(f"  平均: ${sum(pnl_nets)/len(pnl_nets):.2f}")
    print(f"  最大: ${max(pnl_nets):.2f}")
    print(f"  最小: ${min(pnl_nets):.2f}")
    print(f"  中位数: ${sorted(pnl_nets)[len(pnl_nets)//2]:.2f}")
    
    print(f"\navg_pnl_per_trade:")
    print(f"  平均: ${sum(avg_pnls)/len(avg_pnls):.2f}")
    print(f"  最大: ${max(avg_pnls):.2f}")
    print(f"  最小: ${min(avg_pnls):.2f}")
    print(f"  中位数: ${sorted(avg_pnls)[len(avg_pnls)//2]:.2f}")
    
    print(f"\nwin_rate_trades:")
    print(f"  平均: {sum(win_rates)/len(win_rates)*100:.2f}%")
    print(f"  最大: {max(win_rates)*100:.2f}%")
    print(f"  最小: {min(win_rates)*100:.2f}%")
    print(f"  中位数: {sorted(win_rates)[len(win_rates)//2]*100:.2f}%")
    
    print(f"\ntotal_trades:")
    print(f"  平均: {sum(trades_counts)/len(trades_counts):.1f}")
    print(f"  最大: {max(trades_counts)}")
    print(f"  最小: {min(trades_counts)}")
    print(f"  中位数: {sorted(trades_counts)[len(trades_counts)//2]}")
    
    print(f"\ncost_bps_on_turnover:")
    print(f"  平均: {sum(cost_bps)/len(cost_bps):.2f}")
    print(f"  最大: {max(cost_bps):.2f}")
    print(f"  最小: {min(cost_bps):.2f}")
    print(f"  中位数: {sorted(cost_bps)[len(cost_bps)//2]:.2f}")
    
    print(f"\nscore:")
    print(f"  平均: {sum(scores)/len(scores):.2f}")
    print(f"  最大: {max(scores):.2f}")
    print(f"  最小: {min(scores):.2f}")
    print(f"  中位数: {sorted(scores)[len(scores)//2]:.2f}")
    
    # 硬约束满足情况
    print("\n" + "=" * 100)
    print("硬约束满足情况")
    print("=" * 100)
    
    constraints_met = {
        'pnl_net>=0': 0,
        'avg_pnl_per_trade>=0': 0,
        'trades_per_hour<=20': 0,
        'cost_bps<=1.75': 0,
        'all': 0
    }
    
    for t in trials:
        m = t['metrics']
        met = True
        
        if m['pnl_net'] >= 0:
            constraints_met['pnl_net>=0'] += 1
        else:
            met = False
        
        if m['avg_pnl_per_trade'] >= 0:
            constraints_met['avg_pnl_per_trade>=0'] += 1
        else:
            met = False
        
        trades_per_hour = m.get('trades_per_hour', m['total_trades'] / 24.0)
        if trades_per_hour <= 20:
            constraints_met['trades_per_hour<=20'] += 1
        else:
            met = False
        
        cost_bps_val = m.get('cost_bps_on_turnover', 0)
        if cost_bps_val <= 1.75:
            constraints_met['cost_bps<=1.75'] += 1
        else:
            met = False
        
        if met:
            constraints_met['all'] += 1
    
    print(f"\npnl_net >= 0: {constraints_met['pnl_net>=0']}/{len(trials)} ({constraints_met['pnl_net>=0']/len(trials)*100:.1f}%)")
    print(f"avg_pnl_per_trade >= 0: {constraints_met['avg_pnl_per_trade>=0']}/{len(trials)} ({constraints_met['avg_pnl_per_trade>=0']/len(trials)*100:.1f}%)")
    print(f"trades_per_hour <= 20: {constraints_met['trades_per_hour<=20']}/{len(trials)} ({constraints_met['trades_per_hour<=20']/len(trials)*100:.1f}%)")
    print(f"cost_bps <= 1.75: {constraints_met['cost_bps<=1.75']}/{len(trials)} ({constraints_met['cost_bps<=1.75']/len(trials)*100:.1f}%)")
    print(f"\n满足所有硬约束: {constraints_met['all']}/{len(trials)} ({constraints_met['all']/len(trials)*100:.1f}%)")
    
    # Top 10 Trials
    print("\n" + "=" * 100)
    print("Top 10 Trials (按score排序)")
    print("=" * 100)
    
    top10 = sorted(trials, key=lambda x: x.get('score', 0), reverse=True)[:10]
    
    print(f"\n{'排名':<4} {'Trial':<6} {'Score':<10} {'PNL净':<10} {'单笔PNL':<10} {'胜率':<8} {'交易数':<8} {'成本bps':<10}")
    print("-" * 100)
    
    for i, t in enumerate(top10, 1):
        m = t['metrics']
        trial_id = t['trial_id']
        score = t.get('score', 0)
        pnl_net = m['pnl_net']
        avg_pnl = m['avg_pnl_per_trade']
        win_rate = m['win_rate_trades'] * 100
        trades = m['total_trades']
        cost = m.get('cost_bps_on_turnover', 0)
        
        print(f"{i:<4} {trial_id:<6} {score:<10.2f} ${pnl_net:<9.2f} ${avg_pnl:<9.2f} {win_rate:<7.1f}% {trades:<8} {cost:<10.2f}")
    
    # 满足所有硬约束的trial
    print("\n" + "=" * 100)
    print("满足所有硬约束的Trial")
    print("=" * 100)
    
    valid_trials = []
    for t in trials:
        m = t['metrics']
        if (m['pnl_net'] >= 0 and 
            m['avg_pnl_per_trade'] >= 0 and 
            m.get('trades_per_hour', m['total_trades'] / 24.0) <= 20 and
            m.get('cost_bps_on_turnover', 0) <= 1.75):
            valid_trials.append(t)
    
    if valid_trials:
        print(f"\n找到 {len(valid_trials)} 个满足所有硬约束的trial:")
        print(f"\n{'Trial':<6} {'Score':<10} {'PNL净':<10} {'单笔PNL':<10} {'胜率':<8} {'交易数':<8} {'成本bps':<10}")
        print("-" * 100)
        
        for t in sorted(valid_trials, key=lambda x: x.get('score', 0), reverse=True):
            m = t['metrics']
            trial_id = t['trial_id']
            score = t.get('score', 0)
            pnl_net = m['pnl_net']
            avg_pnl = m['avg_pnl_per_trade']
            win_rate = m['win_rate_trades'] * 100
            trades = m['total_trades']
            cost = m.get('cost_bps_on_turnover', 0)
            
            print(f"{trial_id:<6} {score:<10.2f} ${pnl_net:<9.2f} ${avg_pnl:<9.2f} {win_rate:<7.1f}% {trades:<8} {cost:<10.2f}")
    else:
        print("\n没有trial满足所有硬约束")
    
    # 参数分布分析
    print("\n" + "=" * 100)
    print("参数分布分析（所有trial）")
    print("=" * 100)
    
    param_dist = defaultdict(lambda: defaultdict(int))
    
    for t in trials:
        params = t.get('params', {})
        for key, value in params.items():
            param_dist[key][value] += 1
    
    for param_name in sorted(param_dist.keys()):
        print(f"\n{param_name}:")
        dist = param_dist[param_name]
        for value in sorted(dist.keys()):
            count = dist[value]
            pct = count / len(trials) * 100
            print(f"  {value}: {count} ({pct:.1f}%)")
    
    # 正PNL trial的参数分布
    positive_pnl_trials = [t for t in trials if t['metrics']['pnl_net'] >= 0]
    
    if positive_pnl_trials:
        print("\n" + "=" * 100)
        print(f"正PNL trial的参数分布（{len(positive_pnl_trials)}个trial）")
        print("=" * 100)
        
        positive_param_dist = defaultdict(lambda: defaultdict(int))
        
        for t in positive_pnl_trials:
            params = t.get('params', {})
            for key, value in params.items():
                positive_param_dist[key][value] += 1
        
        for param_name in sorted(positive_param_dist.keys()):
            print(f"\n{param_name}:")
            dist = positive_param_dist[param_name]
            for value in sorted(dist.keys()):
                count = dist[value]
                pct = count / len(positive_pnl_trials) * 100
                print(f"  {value}: {count} ({pct:.1f}%)")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        results_file = Path(sys.argv[1])
    else:
        # 查找最新的STAGE-2实验结果
        optimizer_dir = Path("runtime/optimizer")
        stage2_dirs = sorted(optimizer_dir.glob("stage2_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not stage2_dirs:
            print("未找到STAGE-2实验结果目录")
            sys.exit(1)
        
        results_file = stage2_dirs[0] / "trial_results.json"
        print(f"使用最新的实验结果: {results_file}")
    
    if not results_file.exists():
        print(f"结果文件不存在: {results_file}")
        sys.exit(1)
    
    analyze_results(results_file)

