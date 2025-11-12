# -*- coding: utf-8 -*-
"""诊断E4/E5/E6无交易问题"""
import json
import sys
from pathlib import Path
from collections import Counter

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def analyze_signals(signal_file: Path):
    """分析信号文件"""
    if not signal_file.exists():
        return None
    
    signals = []
    with open(signal_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                signals.append(json.loads(line))
    
    if not signals:
        return None
    
    scores = [abs(s.get("score", 0)) for s in signals]
    confirmed = [s for s in signals if s.get("confirm") == True]
    gating_blocked = [s for s in signals if s.get("gating_blocked") == True]
    gate_reasons = [s.get("gate_reason", "") for s in signals if s.get("gate_reason")]
    
    return {
        "total": len(signals),
        "confirmed": len(confirmed),
        "gating_blocked": len(gating_blocked),
        "score_range": (min(scores), max(scores)) if scores else (0, 0),
        "score_avg": sum(scores) / len(scores) if scores else 0,
        "score_above_0_7": sum(1 for s in scores if s > 0.7),
        "score_above_0_78": sum(1 for s in scores if s > 0.78),
        "gate_reason_counts": Counter(gate_reasons),
    }


def main():
    """主函数"""
    print("="*80)
    print("E4/E5/E6无交易问题诊断")
    print("="*80 + "\n")
    
    # 检查E4/E5/E6的信号
    experiments = {
        "E4": "runtime/optimizer/group_e4_validation/backtest_20251110_222934",
        "E5": "runtime/optimizer/group_e5_validation/backtest_20251110_223018",
        "E6": "runtime/optimizer/group_e6_validation/backtest_20251110_223108",
    }
    
    # 对比E1（有交易）
    e1_dir = project_root / "runtime/optimizer/group_e1_validation/backtest_20251110_220402"
    
    for exp_key, exp_dir in experiments.items():
        exp_path = project_root / exp_dir
        print(f"\n{exp_key}组:")
        print("-" * 80)
        
        # 检查信号文件
        signal_files = list(exp_path.glob("signals/ready/signal/*/signals_*.jsonl"))
        if not signal_files:
            print("  [ERROR] 未找到信号文件")
            continue
        
        # 分析第一个信号文件
        signal_file = signal_files[0]
        result = analyze_signals(signal_file)
        
        if result:
            print(f"  信号文件: {signal_file.name}")
            print(f"  总信号数: {result['total']}")
            print(f"  确认信号数: {result['confirmed']}")
            print(f"  被门控阻止: {result['gating_blocked']}")
            print(f"  Score范围: {result['score_range'][0]:.4f} - {result['score_range'][1]:.4f}")
            print(f"  Score平均值: {result['score_avg']:.4f}")
            print(f"  Score>0.70的数量: {result['score_above_0_7']}")
            print(f"  Score>0.78的数量: {result['score_above_0_78']}")
            print(f"  门控原因统计:")
            for reason, count in result['gate_reason_counts'].most_common(5):
                print(f"    {reason}: {count}")
        
        # 检查trades.jsonl
        trades_file = exp_path / "trades.jsonl"
        if trades_file.exists():
            with open(trades_file, "r", encoding="utf-8") as f:
                trades = [line for line in f if line.strip()]
            print(f"  交易数量: {len(trades)}")
        else:
            print(f"  [WARN] trades.jsonl不存在")
    
    # 对比E1
    print(f"\n\nE1组（有交易）:")
    print("-" * 80)
    e1_signal_files = list(e1_dir.glob("signals/ready/signal/*/signals_*.jsonl"))
    if e1_signal_files:
        e1_result = analyze_signals(e1_signal_files[0])
        if e1_result:
            print(f"  总信号数: {e1_result['total']}")
            print(f"  确认信号数: {e1_result['confirmed']}")
            print(f"  Score范围: {e1_result['score_range'][0]:.4f} - {e1_result['score_range'][1]:.4f}")
            print(f"  Score平均值: {e1_result['score_avg']:.4f}")
            print(f"  Score>0.78的数量: {e1_result['score_above_0_78']}")
    
    e1_trades_file = e1_dir / "trades.jsonl"
    if e1_trades_file.exists():
        with open(e1_trades_file, "r", encoding="utf-8") as f:
            e1_trades = [line for line in f if line.strip()]
        print(f"  交易数量: {len(e1_trades)}")
    
    print("\n" + "="*80)
    print("诊断结论")
    print("="*80)
    print("如果E4/E5/E6的信号score都很低且被weak_signal过滤，说明参数设置太严格。")
    print("如果E5（weak_signal_threshold=0.70）也没有交易，可能是其他参数问题。")
    print("建议检查：")
    print("1. weak_signal_threshold是否过高")
    print("2. consistency_min是否过高")
    print("3. min_consecutive是否过高")
    print("4. 代码修改是否引入了bug（特别是effective_spread_bps的计算）")


if __name__ == "__main__":
    main()

