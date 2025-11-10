# -*- coding: utf-8 -*-
"""分析优化组实验结果"""
import json
from pathlib import Path

# 加载对比数据
comparison_file = Path("runtime/optimizer/optimization_groups_comparison.json")
with open(comparison_file, "r", encoding="utf-8") as f:
    data = json.load(f)

baseline = data["baseline"]
groups = data["groups"]

print("="*80)
print("优化组实验结果详细分析")
print("="*80 + "\n")

# A组详细分析
if "A" in groups:
    print("A组（严门控+去重提速）详细分析:")
    print("-"*80)
    a_metrics = groups["A"]["metrics"]
    a_dir = Path(groups["A"]["result_dir"])
    
    # 加载完整metrics
    metrics_file = a_dir / "metrics.json"
    with open(metrics_file, "r", encoding="utf-8") as f:
        full_metrics = json.load(f)
    
    print(f"总交易数: {full_metrics['total_trades']}")
    print(f"平均持仓时间: {full_metrics['avg_hold_sec']:.1f}秒 ({full_metrics['avg_hold_sec']/3600:.2f}小时)")
    print(f"平均持仓（long）: {full_metrics['avg_hold_long']:.1f}秒")
    print(f"平均持仓（short）: {full_metrics['avg_hold_short']:.1f}秒 ({full_metrics['avg_hold_short']/3600:.2f}小时)")
    print(f"胜率: {full_metrics['win_rate_trades']:.2%}")
    print(f"成本bps: {full_metrics['cost_bps_on_turnover']:.2f}")
    
    # 检查scenario breakdown
    if "scenario_breakdown" in full_metrics:
        print("\n场景分布:")
        for scenario, stats in full_metrics["scenario_breakdown"].items():
            print(f"  {scenario}:")
            print(f"    交易数: {stats['trades']}")
            print(f"    平均持仓: {stats['avg_hold_sec']:.1f}秒 ({stats['avg_hold_sec']/60:.1f}分钟)")
            print(f"    胜率: {stats['win_rate']:.2%}")
    
    # 检查trace文件
    trace_file = a_dir / "trace.csv"
    if trace_file.exists():
        import csv
        with open(trace_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            entries = []
            exits = []
            for row in reader:
                if row["action"] == "entry":
                    entries.append(row)
                elif row["action"] == "exit":
                    exits.append(row)
        
        print(f"\nTrace统计:")
        print(f"  Entry数: {len(entries)}")
        print(f"  Exit数: {len(exits)}")
        
        # 检查持仓时间分布
        hold_times = []
        for exit_row in exits:
            hold_time_s = exit_row.get("hold_time_s", "")
            if hold_time_s:
                try:
                    hold_times.append(float(hold_time_s))
                except:
                    pass
        
        if hold_times:
            hold_times.sort()
            print(f"\n持仓时间分布:")
            print(f"  最小值: {min(hold_times):.1f}秒 ({min(hold_times)/60:.1f}分钟)")
            print(f"  最大值: {max(hold_times):.1f}秒 ({max(hold_times)/3600:.2f}小时)")
            print(f"  中位数: {hold_times[len(hold_times)//2]:.1f}秒 ({hold_times[len(hold_times)//2]/60:.1f}分钟)")
            print(f"  平均值: {sum(hold_times)/len(hold_times):.1f}秒 ({sum(hold_times)/len(hold_times)/60:.1f}分钟)")
            
            # 检查是否有异常长的持仓
            long_holds = [t for t in hold_times if t > 3600]  # >1小时
            if long_holds:
                print(f"  异常持仓（>1小时）: {len(long_holds)}笔")
                print(f"  最长持仓: {max(long_holds):.1f}秒 ({max(long_holds)/3600:.2f}小时)")
    
    print()

# B组和C组分析
for group_key in ["B", "C"]:
    if group_key not in groups:
        continue
    
    print(f"{group_key}组分析:")
    print("-"*80)
    group_metrics = groups[group_key]["metrics"]
    
    # 检查是否与基线相同
    is_same_as_baseline = (
        abs(group_metrics["trades_per_hour"] - baseline["trades_per_hour"]) < 0.1 and
        abs(group_metrics["avg_hold_sec"] - baseline["avg_hold_sec"]) < 0.1 and
        abs(group_metrics["cost_bps_on_turnover"] - baseline["cost_bps_on_turnover"]) < 0.01
    )
    
    if is_same_as_baseline:
        print(f"⚠️  {group_key}组结果与基线完全相同，说明配置可能未生效")
        print(f"   请检查配置参数是否正确传递到CoreAlgorithm/TradeSimulator")
    else:
        print(f"✅ {group_key}组配置已生效")
        print(f"   交易频率: {group_metrics['trades_per_hour']:.1f}笔/小时")
        print(f"   平均持仓: {group_metrics['avg_hold_sec']:.1f}秒")
        print(f"   成本bps: {group_metrics['cost_bps_on_turnover']:.2f}")
    
    print()

# 总结
print("="*80)
print("关键发现")
print("="*80 + "\n")

print("1. A组（严门控+去重提速）:")
print("   ✅ 交易频率大幅下降: 934 → 264笔/小时 (-71.7%)")
print("   ✅ 胜率大幅提升: 16.81% → 32.58% (+93.8%)")
print("   ⚠️  平均持仓时间异常: 17241.5秒 (约4.8小时)")
print("   ❌ 成本bps未改善: 1.93bps")
print("   ❌ 交易频率仍高于目标: 264笔/小时 vs 20笔/小时目标")
print()

print("2. B组（冷却+反向防抖）:")
print("   ⚠️  结果与基线完全相同，配置可能未生效")
print("   可能原因: flip_rearm_margin和adaptive_cooldown_k参数未正确传递")
print()

print("3. C组（Maker-first成本压降）:")
print("   ⚠️  结果与基线完全相同，配置可能未生效")
print("   可能原因: fee_maker_taker参数未正确传递或maker概率计算未生效")
print()

print("="*80)
print("建议")
print("="*80 + "\n")

print("1. 检查A组平均持仓时间异常:")
print("   - 检查是否有持仓被强制持有到回测结束")
print("   - 检查force_timeout_exit是否正常工作")
print("   - 检查min_hold_time_sec=240是否导致持仓过长")
print()

print("2. 检查B组和C组配置传递:")
print("   - 验证components.fusion参数是否正确传递到CoreAlgorithm")
print("   - 验证fee_maker_taker参数是否正确传递到TradeSimulator")
print("   - 检查配置加载逻辑")
print()

print("3. 进一步优化A组:")
print("   - 继续提高weak_signal_threshold（0.45 → 0.6）")
print("   - 继续提高consistency_min（0.20 → 0.30）")
print("   - 继续提高去重窗口（1800ms → 3000ms）")
print("   - 调整min_hold_time_sec（240s可能过长，建议180s）")

