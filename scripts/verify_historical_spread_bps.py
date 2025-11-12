# -*- coding: utf-8 -*-
"""验证历史数据的spread_bps处理能力"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_orderbook_data_format(input_dir: Path, date: str, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """检查orderbook数据格式"""
    result = {
        "has_spread_bps": False,
        "has_best_bid_ask": False,
        "has_bids_asks": False,
        "sample_spread_bps": None,
        "sample_best_bid": None,
        "sample_best_ask": None,
        "can_compute": False,
    }
    
    # 查找orderbook文件
    ob_files = list(input_dir.rglob(f"*orderbook*.jsonl"))
    if not ob_files:
        result["error"] = "未找到orderbook文件"
        return result
    
    # 读取第一行数据
    with open(ob_files[0], "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    # 检查字段
                    result["has_spread_bps"] = "spread_bps" in data and data.get("spread_bps") is not None
                    result["has_best_bid_ask"] = "best_bid" in data and "best_ask" in data
                    result["has_bids_asks"] = "bids" in data and "asks" in data
                    
                    if result["has_spread_bps"]:
                        result["sample_spread_bps"] = data.get("spread_bps")
                    
                    if result["has_best_bid_ask"]:
                        result["sample_best_bid"] = data.get("best_bid")
                        result["sample_best_ask"] = data.get("best_ask")
                    
                    # 判断是否能计算
                    if result["has_spread_bps"] and result["sample_spread_bps"] != 0:
                        result["can_compute"] = True
                    elif result["has_best_bid_ask"] and result["sample_best_bid"] > 0 and result["sample_best_ask"] > 0:
                        # 可以现算
                        mid = (result["sample_best_bid"] + result["sample_best_ask"]) / 2
                        computed_spread = ((result["sample_best_ask"] - result["sample_best_bid"]) / mid) * 10000
                        result["can_compute"] = True
                        result["computed_spread_bps"] = computed_spread
                    elif result["has_bids_asks"]:
                        bids = data.get("bids", [])
                        asks = data.get("asks", [])
                        if bids and asks and len(bids) > 0 and len(asks) > 0:
                            best_bid = bids[0][0] if isinstance(bids[0], (list, tuple)) else 0.0
                            best_ask = asks[0][0] if isinstance(asks[0], (list, tuple)) else 0.0
                            if best_bid > 0 and best_ask > 0:
                                mid = (best_bid + best_ask) / 2
                                computed_spread = ((best_ask - best_bid) / mid) * 10000
                                result["can_compute"] = True
                                result["computed_spread_bps"] = computed_spread
                    
                    break
                except Exception as e:
                    result["error"] = f"解析错误: {e}"
                    break
    
    return result


def simulate_aligner_logic(orderbook: Dict[str, Any]) -> Optional[float]:
    """模拟aligner的spread_bps计算逻辑"""
    # 优先从orderbook读取
    spread_bps = orderbook.get("spread_bps")
    if spread_bps is not None and spread_bps != 0.0:
        return float(spread_bps)
    
    # 获取best_bid/best_ask
    best_bid = orderbook.get("best_bid")
    if best_bid is None:
        best_bid = orderbook.get("bid_price")
    best_ask = orderbook.get("best_ask")
    if best_ask is None:
        best_ask = orderbook.get("ask_price")
    
    # 兜底：从bids/asks现算
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        if bids and len(bids) > 0 and bids[0][0] > 0:
            best_bid = bids[0][0]
        if asks and len(asks) > 0 and asks[0][0] > 0:
            best_ask = asks[0][0]
    
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return None
    
    # 计算mid
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return None
    
    # 计算spread_bps
    spread_bps = ((best_ask - best_bid) / mid) * 10000
    return spread_bps


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="验证历史数据的spread_bps处理能力")
    parser.add_argument("--input", type=str, default="deploy/data/ofi_cvd", help="输入数据目录")
    parser.add_argument("--date", type=str, help="日期（可选）")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对")
    
    args = parser.parse_args()
    
    input_dir = project_root / args.input
    
    print("="*80)
    print("历史数据spread_bps处理能力验证")
    print("="*80 + "\n")
    
    # 检查数据格式
    print("1. 检查orderbook数据格式...")
    result = check_orderbook_data_format(input_dir, args.date or "", args.symbol)
    
    print(f"   有spread_bps字段: {result['has_spread_bps']}")
    if result['has_spread_bps']:
        print(f"   spread_bps值: {result['sample_spread_bps']}")
    
    print(f"   有best_bid/best_ask字段: {result['has_best_bid_ask']}")
    if result['has_best_bid_ask']:
        print(f"   best_bid: {result['sample_best_bid']}")
        print(f"   best_ask: {result['sample_best_ask']}")
    
    print(f"   有bids/asks数组: {result['has_bids_asks']}")
    
    print(f"\n   能否计算spread_bps: {result['can_compute']}")
    if result.get('computed_spread_bps'):
        print(f"   计算出的spread_bps: {result['computed_spread_bps']:.4f}bps")
    
    if result.get('error'):
        print(f"   错误: {result['error']}")
    
    # 模拟aligner逻辑
    print("\n2. 模拟aligner的spread_bps计算逻辑...")
    ob_files = list(input_dir.rglob(f"*orderbook*.jsonl"))
    if ob_files:
        with open(ob_files[0], "r", encoding="utf-8") as f:
            count = 0
            success_count = 0
            spreads = []
            for line in f:
                if line.strip() and count < 100:  # 检查前100条
                    try:
                        data = json.loads(line)
                        computed = simulate_aligner_logic(data)
                        if computed is not None:
                            success_count += 1
                            spreads.append(computed)
                        count += 1
                    except Exception as e:
                        pass
            
            print(f"   检查了{count}条记录")
            print(f"   成功计算出spread_bps: {success_count}条")
            if spreads:
                print(f"   spread_bps范围: {min(spreads):.4f} - {max(spreads):.4f}bps")
                print(f"   spread_bps平均值: {sum(spreads)/len(spreads):.4f}bps")
                print(f"   非0记录数: {sum(1 for s in spreads if s != 0)}")
    
    print("\n" + "="*80)
    print("结论")
    print("="*80)
    
    if result['can_compute']:
        print("✅ 历史数据可以正确处理spread_bps（通过兜底逻辑现算）")
        print("   建议：运行短时间测试验证实际效果")
    else:
        print("❌ 历史数据无法计算spread_bps")
        print("   建议：检查数据格式，或重新harvest数据")
    
    if result['has_spread_bps'] and result['sample_spread_bps'] == 0:
        print("\n⚠️  警告：历史数据有spread_bps字段但值为0")
        print("   可能原因：数据收集时spread_bps计算有问题")
        print("   建议：使用兜底逻辑现算")


if __name__ == "__main__":
    main()

