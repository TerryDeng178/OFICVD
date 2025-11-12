# -*- coding: utf-8 -*-
"""检查最新数据是否包含spread_bps"""
import sys
from pathlib import Path
from datetime import datetime

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False
    print("警告: pyarrow未安装，无法读取Parquet文件")


def check_latest_orderbook_data():
    """检查最新的orderbook数据"""
    data_dir = project_root / "deploy/data/ofi_cvd"
    
    print("="*80)
    print("检查最新orderbook数据中的spread_bps")
    print("="*80 + "\n")
    
    # 查找所有orderbook parquet文件
    ob_files = list(data_dir.rglob("*orderbook*.parquet"))
    
    if not ob_files:
        print("[ERROR] 未找到orderbook parquet文件")
        return
    
    print(f"找到{len(ob_files)}个orderbook文件\n")
    
    # 找到最新的文件
    latest_file = max(ob_files, key=lambda f: f.stat().st_mtime)
    mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
    
    print(f"最新文件:")
    print(f"  文件名: {latest_file.name}")
    print(f"  修改时间: {mtime}")
    print(f"  路径: {latest_file.parent}\n")
    
    if not PARQUET_AVAILABLE:
        print("❌ 无法读取Parquet文件（pyarrow未安装）")
        return
    
    # 读取文件
    try:
        table = pq.read_table(latest_file)
        
        print(f"数据统计:")
        print(f"  列数: {len(table.column_names)}")
        print(f"  行数: {len(table)}")
        print(f"  列名（前30个）: {table.column_names[:30]}\n")
        
        # 检查关键字段
        has_spread_bps = "spread_bps" in table.column_names
        has_best_bid = "best_bid" in table.column_names
        has_best_ask = "best_ask" in table.column_names
        has_bids = "bids" in table.column_names
        has_asks = "asks" in table.column_names
        
        print(f"字段检查:")
        print(f"  有spread_bps: {has_spread_bps}")
        print(f"  有best_bid: {has_best_bid}")
        print(f"  有best_ask: {has_best_ask}")
        print(f"  有bids数组: {has_bids}")
        print(f"  有asks数组: {has_asks}\n")
        
        # 检查spread_bps的值
        if has_spread_bps:
            rows = table.to_pylist()[:100]  # 检查前100条
            spreads = [r.get("spread_bps", 0) for r in rows if "spread_bps" in r]
            non_zero = [s for s in spreads if s != 0]
            
            print(f"spread_bps统计（前100条）:")
            print(f"  总数: {len(spreads)}")
            print(f"  非0数量: {len(non_zero)}/{len(spreads)}")
            
            if non_zero:
                print(f"  范围: {min(non_zero):.6f} - {max(non_zero):.6f}bps")
                print(f"  平均值: {sum(non_zero)/len(non_zero):.6f}bps")
                print(f"  中位数: {sorted(non_zero)[len(non_zero)//2]:.6f}bps")
                print("\n[OK] spread_bps字段存在且非0")
            else:
                print("[ERROR] 所有spread_bps都是0")
        else:
            print("[ERROR] 没有spread_bps字段")
        
        # 检查best_bid/best_ask
        if has_best_bid and has_best_ask:
            rows = table.to_pylist()[:10]
            print(f"\n前10条记录的best_bid/best_ask:")
            for i, row in enumerate(rows):
                bid = row.get("best_bid")
                ask = row.get("best_ask")
                if bid and ask:
                    mid = (bid + ask) / 2
                    computed_spread = ((ask - bid) / mid) * 10000 if mid > 0 else 0
                    print(f"  记录{i+1}: bid={bid:.2f}, ask={ask:.2f}, 计算spread={computed_spread:.4f}bps")
        
    except Exception as e:
        print(f"❌ 读取文件错误: {e}")
        import traceback
        traceback.print_exc()


def check_latest_features_data():
    """检查最新的features数据"""
    data_dir = project_root / "deploy/data/ofi_cvd"
    
    print("\n" + "="*80)
    print("检查最新features数据中的spread_bps")
    print("="*80 + "\n")
    
    # 查找所有features parquet文件
    feature_files = list(data_dir.rglob("*features*.parquet"))
    
    if not feature_files:
        print("[ERROR] 未找到features parquet文件")
        return
    
    print(f"找到{len(feature_files)}个features文件\n")
    
    # 找到最新的文件
    latest_file = max(feature_files, key=lambda f: f.stat().st_mtime)
    mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
    
    print(f"最新文件:")
    print(f"  文件名: {latest_file.name}")
    print(f"  修改时间: {mtime}")
    print(f"  路径: {latest_file.parent}\n")
    
    if not PARQUET_AVAILABLE:
        print("❌ 无法读取Parquet文件（pyarrow未安装）")
        return
    
    # 读取文件
    try:
        table = pq.read_table(latest_file)
        
        print(f"数据统计:")
        print(f"  列数: {len(table.column_names)}")
        print(f"  行数: {len(table)}")
        print(f"  有spread_bps: {'spread_bps' in table.column_names}\n")
        
        # 检查spread_bps的值
        if "spread_bps" in table.column_names:
            rows = table.to_pylist()[:100]  # 检查前100条
            spreads = [r.get("spread_bps", 0) for r in rows if "spread_bps" in r]
            non_zero = [s for s in spreads if s != 0]
            
            print(f"spread_bps统计（前100条）:")
            print(f"  总数: {len(spreads)}")
            print(f"  非0数量: {len(non_zero)}/{len(spreads)}")
            
            if non_zero:
                print(f"  范围: {min(non_zero):.6f} - {max(non_zero):.6f}bps")
                print(f"  平均值: {sum(non_zero)/len(non_zero):.6f}bps")
                print("\n[OK] features数据中spread_bps字段存在且非0")
            else:
                print("[ERROR] features数据中所有spread_bps都是0")
                print("  说明：历史features数据在生成时spread_bps就是0")
        else:
            print("[ERROR] features数据中没有spread_bps字段")
    
    except Exception as e:
        print(f"[ERROR] 读取文件错误: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    check_latest_orderbook_data()
    check_latest_features_data()
    
    print("\n" + "="*80)
    print("结论")
    print("="*80)
    print("1. 如果orderbook数据有spread_bps且非0 → 可以使用full path重跑E4/E5/E6")
    print("2. 如果features数据中spread_bps是0 → 需要使用full path（--kinds prices,orderbook）")
    print("3. 已修复run_e_experiments.py使用full path，确保spread_bps非0")


if __name__ == "__main__":
    main()

