# -*- coding: utf-8 -*-
"""检查full path生成的features中的spread_bps"""
import json
import sys
from pathlib import Path

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def main():
    """主函数"""
    result_dir = project_root / "runtime/test_spread_bps_validation_full"
    
    print("="*80)
    print("Full Path spread_bps检查")
    print("="*80 + "\n")
    
    # 检查signals中的_feature_data
    signal_files = list(result_dir.rglob("signals/**/*.jsonl"))
    if signal_files:
        print(f"找到{len(signal_files)}个signal文件")
        signal_file = signal_files[0]
        
        print(f"\n检查文件: {signal_file.name}")
        
        signals_with_feature_data = 0
        signals_with_spread_bps = 0
        spread_bps_values = []
        
        with open(signal_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 100:  # 只检查前100条
                    break
                if not line.strip():
                    continue
                
                try:
                    signal = json.loads(line)
                    if "_feature_data" in signal:
                        signals_with_feature_data += 1
                        feature_data = signal["_feature_data"]
                        if "spread_bps" in feature_data:
                            signals_with_spread_bps += 1
                            spread_bps = feature_data.get("spread_bps")
                            if spread_bps is not None:
                                spread_bps_values.append(spread_bps)
                except Exception as e:
                    pass
        
        print(f"\nSignal统计:")
        print(f"  检查的信号数: 100")
        print(f"  有_feature_data: {signals_with_feature_data}")
        print(f"  有spread_bps: {signals_with_spread_bps}")
        
        if spread_bps_values:
            non_zero = [s for s in spread_bps_values if s != 0]
            print(f"\nspread_bps统计:")
            print(f"  总数: {len(spread_bps_values)}")
            print(f"  非0数量: {len(non_zero)}/{len(spread_bps_values)}")
            if non_zero:
                print(f"  范围: {min(non_zero):.4f} - {max(non_zero):.4f}bps")
                print(f"  平均值: {sum(non_zero)/len(non_zero):.4f}bps")
                print("✅ signal中的spread_bps非0")
            else:
                print("❌ signal中的spread_bps都是0")
        else:
            print("❌ signal中没有spread_bps字段")
    
    # 检查trades中的spread_bps
    trade_files = list(result_dir.rglob("trades.jsonl"))
    if trade_files:
        print(f"\n检查trades文件: {trade_files[0].name}")
        
        spreads = []
        with open(trade_files[0], "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    trade = json.loads(line)
                    if "spread_bps" in trade:
                        spreads.append(trade.get("spread_bps", 0))
        
        if spreads:
            non_zero = [s for s in spreads if s != 0]
            print(f"  总数: {len(spreads)}")
            print(f"  非0数量: {len(non_zero)}/{len(spreads)}")
            if non_zero:
                print(f"  范围: {min(non_zero):.4f} - {max(non_zero):.4f}bps")
                print("✅ trade中的spread_bps非0")
            else:
                print("❌ trade中的spread_bps都是0")
    else:
        print("\n未找到trades文件（可能没有交易）")

if __name__ == "__main__":
    main()

