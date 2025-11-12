# -*- coding: utf-8 -*-
"""检查price和orderbook数据的字段"""
import sys
from pathlib import Path

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False


def check_price_fields():
    """检查price数据字段"""
    print("="*80)
    print("检查Price数据字段")
    print("="*80 + "\n")
    
    price_dir = project_root / "deploy/data/ofi_cvd/raw/date=2025-11-09/hour=00/symbol=btcusdt/kind=prices"
    price_files = list(price_dir.glob("*.parquet"))
    
    if not price_files:
        print("[ERROR] 未找到price文件")
        return
    
    if not PARQUET_AVAILABLE:
        print("[ERROR] pyarrow未安装")
        return
    
    # 读取单个文件（避免schema合并问题）
    price_file = price_files[0]
    try:
        table = pq.read_table(price_file)
        
        print(f"文件: {price_file.name}")
        print(f"行数: {len(table)}")
        print(f"\n字段列表:")
        for i, col in enumerate(table.column_names, 1):
            print(f"  {i}. {col}")
        
        print(f"\n关键字段检查:")
        print(f"  有spread_bps: {'spread_bps' in table.column_names}")
        print(f"  有best_bid: {'best_bid' in table.column_names}")
        print(f"  有best_ask: {'best_ask' in table.column_names}")
        print(f"  有price: {'price' in table.column_names}")
        
        # 读取第一条记录
        if len(table) > 0:
            row = table.to_pylist()[0]
            print(f"\n第一条记录示例:")
            print(f"  ts_ms: {row.get('ts_ms')}")
            print(f"  symbol: {row.get('symbol')}")
            print(f"  price: {row.get('price')}")
            print(f"  spread_bps: {row.get('spread_bps', 'N/A')}")
            print(f"  best_bid: {row.get('best_bid', 'N/A')}")
            print(f"  best_ask: {row.get('best_ask', 'N/A')}")
    
    except Exception as e:
        print(f"[ERROR] 读取错误: {e}")


def check_orderbook_fields():
    """检查orderbook数据字段"""
    print("\n" + "="*80)
    print("检查Orderbook数据字段")
    print("="*80 + "\n")
    
    ob_dir = project_root / "deploy/data/ofi_cvd/raw/date=2025-11-09/hour=00/symbol=btcusdt/kind=orderbook"
    ob_files = list(ob_dir.glob("*.parquet"))
    
    if not ob_files:
        print("[ERROR] 未找到orderbook文件")
        return
    
    if not PARQUET_AVAILABLE:
        print("[ERROR] pyarrow未安装")
        return
    
    # 读取单个文件
    ob_file = ob_files[0]
    try:
        table = pq.read_table(ob_file)
        
        print(f"文件: {ob_file.name}")
        print(f"行数: {len(table)}")
        print(f"\n字段列表（前40个）:")
        for i, col in enumerate(table.column_names[:40], 1):
            print(f"  {i}. {col}")
        
        print(f"\n关键字段检查:")
        print(f"  有spread_bps: {'spread_bps' in table.column_names}")
        print(f"  有best_bid: {'best_bid' in table.column_names}")
        print(f"  有best_ask: {'best_ask' in table.column_names}")
        print(f"  有bids: {'bids' in table.column_names}")
        print(f"  有asks: {'asks' in table.column_names}")
        
        # 读取前几条记录检查spread_bps
        if len(table) > 0:
            rows = table.to_pylist()[:10]
            spreads = [r.get('spread_bps', 0) for r in rows if 'spread_bps' in r]
            non_zero = [s for s in spreads if s != 0]
            
            print(f"\n前10条记录的spread_bps:")
            print(f"  总数: {len(spreads)}")
            print(f"  非0数量: {len(non_zero)}/{len(spreads)}")
            if non_zero:
                print(f"  范围: {min(non_zero):.6f} - {max(non_zero):.6f}bps")
                print(f"  平均值: {sum(non_zero)/len(non_zero):.6f}bps")
                print("\n[OK] orderbook数据中有spread_bps字段且非0")
            else:
                print("  [WARN] 所有spread_bps都是0")
            
            # 显示第一条记录
            row = rows[0]
            print(f"\n第一条记录示例:")
            print(f"  ts_ms: {row.get('ts_ms')}")
            print(f"  symbol: {row.get('symbol')}")
            print(f"  spread_bps: {row.get('spread_bps', 'N/A')}")
            print(f"  best_bid: {row.get('best_bid', 'N/A')}")
            print(f"  best_ask: {row.get('best_ask', 'N/A')}")
            print(f"  mid: {row.get('mid', 'N/A')}")
    
    except Exception as e:
        print(f"[ERROR] 读取错误: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    check_price_fields()
    check_orderbook_fields()
    
    print("\n" + "="*80)
    print("结论")
    print("="*80)
    print("spread_bps在orderbook数据中，不在price数据中")
    print("数据位置: raw/date=*/hour=*/symbol=*/kind=orderbook/*.parquet")


if __name__ == "__main__":
    main()

