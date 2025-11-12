# -*- coding: utf-8 -*-
"""检查aligner生成的features中的spread_bps"""
import sys
from pathlib import Path

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alpha_core.backtest import DataReader, DataAligner
import yaml

def main():
    """主函数"""
    # 读取配置
    config_path = project_root / "runtime/optimizer/group_e4_combined.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    
    # 初始化DataReader
    reader = DataReader(
        input_dir=project_root / "deploy/data/ofi_cvd",
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["prices", "orderbook"],
        minutes=10,
    )
    
    # 初始化Aligner
    aligner = DataAligner(max_lag_ms=5000, config=config)
    
    # 读取原始数据
    print("读取原始数据...")
    prices = list(reader.read_raw("prices"))
    orderbook = list(reader.read_raw("orderbook"))
    
    print(f"价格数据: {len(prices)}条")
    print(f"订单簿数据: {len(orderbook)}条")
    
    # 检查orderbook数据格式
    if orderbook:
        sample_ob = orderbook[0]
        print(f"\n订单簿数据字段: {list(sample_ob.keys())[:20]}")
        print(f"有spread_bps: {'spread_bps' in sample_ob}")
        print(f"有best_bid: {'best_bid' in sample_ob}")
        print(f"有best_ask: {'best_ask' in sample_ob}")
        print(f"有bids: {'bids' in sample_ob}")
        print(f"有asks: {'asks' in sample_ob}")
        
        if 'spread_bps' in sample_ob:
            print(f"spread_bps值: {sample_ob.get('spread_bps')}")
        if 'best_bid' in sample_ob and 'best_ask' in sample_ob:
            print(f"best_bid: {sample_ob.get('best_bid')}")
            print(f"best_ask: {sample_ob.get('best_ask')}")
            if sample_ob.get('best_bid') and sample_ob.get('best_ask'):
                mid = (sample_ob.get('best_bid') + sample_ob.get('best_ask')) / 2
                computed_spread = ((sample_ob.get('best_ask') - sample_ob.get('best_bid')) / mid) * 10000
                print(f"计算出的spread_bps: {computed_spread:.4f}bps")
    
    # 对齐数据
    print("\n对齐数据...")
    features = list(aligner.align_to_seconds(prices, orderbook))
    
    print(f"生成的features: {len(features)}条")
    
    # 检查features中的spread_bps
    if features:
        spread_bps_values = []
        for feature in features[:100]:  # 检查前100条
            spread_bps = feature.get("spread_bps")
            if spread_bps is not None:
                spread_bps_values.append(spread_bps)
        
        if spread_bps_values:
            non_zero = [s for s in spread_bps_values if s != 0]
            print(f"\nfeatures中的spread_bps:")
            print(f"  总数: {len(spread_bps_values)}")
            print(f"  非0数量: {len(non_zero)}/{len(spread_bps_values)}")
            if non_zero:
                print(f"  范围: {min(non_zero):.4f} - {max(non_zero):.4f}bps")
                print(f"  平均值: {sum(non_zero)/len(non_zero):.4f}bps")
                print("✅ spread_bps计算正常")
            else:
                print("❌ 所有spread_bps都是0")
        else:
            print("❌ features中没有spread_bps字段")

if __name__ == "__main__":
    main()

