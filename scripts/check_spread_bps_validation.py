# -*- coding: utf-8 -*-
"""检查spread_bps验证结果"""
import json
import sys
from pathlib import Path
from typing import List, Dict, Any

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_trades(trade_file: Path) -> Dict[str, Any]:
    """检查trade记录中的spread_bps"""
    result = {
        "total_trades": 0,
        "spread_bps_count": 0,
        "spread_bps_non_zero": 0,
        "spread_bps_values": [],
        "effective_spread_bps_values": [],
        "maker_probability_values": [],
        "entry_count": 0,
        "exit_count": 0,
        "entry_maker_count": 0,
        "exit_maker_count": 0,
    }
    
    if not trade_file.exists():
        return result
    
    with open(trade_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            
            try:
                trade = json.loads(line)
                result["total_trades"] += 1
                
                # 检查spread_bps
                if "spread_bps" in trade:
                    result["spread_bps_count"] += 1
                    spread_bps = trade.get("spread_bps", 0)
                    result["spread_bps_values"].append(spread_bps)
                    if spread_bps != 0:
                        result["spread_bps_non_zero"] += 1
                
                # 检查effective_spread_bps
                if "effective_spread_bps" in trade:
                    result["effective_spread_bps_values"].append(trade.get("effective_spread_bps", 0))
                
                # 检查maker_probability
                if "maker_probability" in trade:
                    result["maker_probability_values"].append(trade.get("maker_probability", 0))
                
                # 统计entry/exit的maker比例
                reason = trade.get("reason", "")
                is_maker = trade.get("is_maker_actual", False)
                
                if reason == "entry":
                    result["entry_count"] += 1
                    if is_maker:
                        result["entry_maker_count"] += 1
                elif reason in ["exit", "stop_loss", "take_profit", "reverse", "reverse_signal", "timeout"]:
                    result["exit_count"] += 1
                    if is_maker:
                        result["exit_maker_count"] += 1
            
            except Exception as e:
                print(f"解析错误: {e}")
                continue
    
    return result


def main():
    """主函数"""
    result_dir = project_root / "runtime/test_spread_bps_validation"
    
    print("="*80)
    print("spread_bps验证结果检查")
    print("="*80 + "\n")
    
    # 查找trades.jsonl文件
    trade_files = list(result_dir.rglob("trades.jsonl"))
    if not trade_files:
        print("❌ 未找到trades.jsonl文件")
        return
    
    trade_file = trade_files[0]
    print(f"检查文件: {trade_file}\n")
    
    result = check_trades(trade_file)
    
    print(f"总交易数: {result['total_trades']}")
    print(f"有spread_bps字段的交易: {result['spread_bps_count']}/{result['total_trades']}")
    print(f"spread_bps非0数量: {result['spread_bps_non_zero']}/{result['spread_bps_count']}")
    
    if result['spread_bps_values']:
        non_zero_spreads = [s for s in result['spread_bps_values'] if s != 0]
        if non_zero_spreads:
            print(f"\n✅ spread_bps计算正常:")
            print(f"   spread_bps范围: {min(non_zero_spreads):.4f} - {max(non_zero_spreads):.4f}bps")
            print(f"   spread_bps平均值: {sum(non_zero_spreads)/len(non_zero_spreads):.4f}bps")
            print(f"   spread_bps中位数: {sorted(non_zero_spreads)[len(non_zero_spreads)//2]:.4f}bps")
        else:
            print(f"\n❌ 所有spread_bps都是0")
            print(f"   需要检查数据格式或aligner的兜底逻辑")
    
    if result['effective_spread_bps_values']:
        non_zero_effective = [s for s in result['effective_spread_bps_values'] if s != 0]
        if non_zero_effective:
            print(f"\neffective_spread_bps:")
            print(f"   非0数量: {len(non_zero_effective)}/{len(result['effective_spread_bps_values'])}")
            print(f"   范围: {min(non_zero_effective):.4f} - {max(non_zero_effective):.4f}bps")
    
    if result['maker_probability_values']:
        print(f"\nmaker_probability:")
        print(f"   范围: {min(result['maker_probability_values']):.4f} - {max(result['maker_probability_values']):.4f}")
        print(f"   平均值: {sum(result['maker_probability_values'])/len(result['maker_probability_values']):.4f}")
    
    if result['entry_count'] > 0:
        entry_maker_ratio = result['entry_maker_count'] / result['entry_count']
        print(f"\n入场交易:")
        print(f"   总数: {result['entry_count']}")
        print(f"   Maker: {result['entry_maker_count']}")
        print(f"   Maker比例: {entry_maker_ratio:.2%}")
    
    if result['exit_count'] > 0:
        exit_maker_ratio = result['exit_maker_count'] / result['exit_count']
        print(f"\n出场交易:")
        print(f"   总数: {result['exit_count']}")
        print(f"   Maker: {result['exit_maker_count']}")
        print(f"   Maker比例: {exit_maker_ratio:.2%}")
    
    print("\n" + "="*80)
    print("结论")
    print("="*80)
    
    if result['spread_bps_non_zero'] > 0:
        print("✅ spread_bps计算正常，可以重跑E4/E5/E6")
        print("   预期改进:")
        print("   - 成本可能降低（cost_bps从1.93降至1.75-1.85）")
        print("   - Maker比例可能提升（maker_ratio_actual从50%提升至60-70%）")
        print("   - 净PNL可能改善（pnl_per_trade从负值改善至接近0或正值）")
    else:
        print("❌ spread_bps仍为0，需要进一步检查:")
        print("   1. 检查历史数据格式（是否有bids/asks字段）")
        print("   2. 检查aligner的兜底逻辑是否正确执行")
        print("   3. 可能需要重新harvest数据")


if __name__ == "__main__":
    main()

