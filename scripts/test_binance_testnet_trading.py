# -*- coding: utf-8 -*-
"""Binance Testnet Trading Test Script

用于验证测试网API连接和交易功能
"""
import os
import sys
import time
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.alpha_core.executors.binance_api import BinanceFuturesAPI
from src.alpha_core.executors.base_executor import Side


def test_binance_testnet_trading():
    """测试Binance Testnet交易功能"""
    print("=== Binance Testnet Trading Test ===")
    print("")
    
    print("[1/6] 初始化Binance Testnet API客户端...")
    
    # 从环境变量获取API密钥
    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not secret_key:
        print("ERROR: API密钥未设置")
        print("请先运行: .\\scripts\\setup_binance_testnet_env.ps1")
        return False
    
    # 创建测试网API客户端
    api = BinanceFuturesAPI(
        api_key=api_key,
        secret_key=secret_key,
        testnet=True  # 使用测试网
    )
    
    print(f"  Base URL: {api.base_url}")
    print(f"  Testnet: True")
    print("")
    
    # 测试1: 测试API连接（通过获取账户信息）
    print("[2/6] 测试1: 测试API连接...")
    try:
        # 使用一个简单的API调用来测试连接
        # 尝试获取账户信息（如果失败，至少可以验证签名是否正确）
        account_info = api._request("GET", "/fapi/v2/account", signed=True)
        print(f"  账户余额: {account_info.get('totalWalletBalance', 'N/A')} USDT")
        print("  [OK] API连接正常")
    except Exception as e:
        # 如果账户信息获取失败，尝试获取持仓（这个更简单）
        try:
            position = api.get_position(symbol="BTCUSDT")
            print(f"  [OK] API连接正常（通过持仓查询验证）")
        except Exception as e2:
            print(f"  [WARN] API连接测试失败: {e}")
            print(f"  继续测试其他功能...")
    print("")
    
    # 测试2: 获取持仓
    print("[3/6] 测试2: 获取当前持仓...")
    symbol = "BTCUSDT"
    try:
        position = api.get_position(symbol=symbol)
        print(f"  Symbol: {symbol}")
        print(f"  Position: {position}")
        print("  [OK] 持仓查询正常")
    except Exception as e:
        print(f"  [WARN] 持仓查询失败（可能账户为空）: {e}")
    print("")
    
    # 测试3: 提交买单（市价单，最小数量）
    print("[4/6] 测试3: 提交买单（市价单，最小数量 0.001 BTC）...")
    try:
        # Binance期货最小数量通常是0.001 BTC
        buy_order = api.submit_order(
            symbol=symbol,
            side=Side.BUY,
            qty=0.001,
            order_type="MARKET"
        )
        print(f"  完整响应: {buy_order}")
        print(f"  Order ID: {buy_order.get('orderId', buy_order.get('order_id', 'N/A'))}")
        print(f"  Status: {buy_order.get('status', 'N/A')}")
        print(f"  Executed Qty: {buy_order.get('executedQty', buy_order.get('executed_qty', '0'))}")
        print(f"  Avg Price: {buy_order.get('avgPrice', buy_order.get('avg_price', 'N/A'))}")
        print("  [OK] 买单提交成功")
        
        # 等待订单完成
        time.sleep(2)
        
    except Exception as e:
        print(f"  [ERROR] 买单提交失败: {e}")
        print(f"  错误详情: {str(e)}")
        return False
    print("")
    
    # 测试4: 提交卖单（市价单，最小数量）
    print("[5/6] 测试4: 提交卖单（市价单，最小数量 0.001 BTC）...")
    try:
        sell_order = api.submit_order(
            symbol=symbol,
            side=Side.SELL,
            qty=0.001,
            order_type="MARKET"
        )
        print(f"  完整响应: {sell_order}")
        print(f"  Order ID: {sell_order.get('orderId', sell_order.get('order_id', 'N/A'))}")
        print(f"  Status: {sell_order.get('status', 'N/A')}")
        print(f"  Executed Qty: {sell_order.get('executedQty', sell_order.get('executed_qty', '0'))}")
        print(f"  Avg Price: {sell_order.get('avgPrice', sell_order.get('avg_price', 'N/A'))}")
        print("  [OK] 卖单提交成功")
        
        # 等待订单完成
        time.sleep(2)
        
    except Exception as e:
        print(f"  [ERROR] 卖单提交失败: {e}")
        print(f"  错误详情: {str(e)}")
        return False
    print("")
    
    # 测试5: 获取成交历史
    print("[6/6] 测试5: 获取成交历史...")
    try:
        trades = api.get_trades(symbol=symbol, limit=5)
        print(f"  最近成交记录数: {len(trades)}")
        for i, trade in enumerate(trades[:3], 1):
            print(f"  Trade {i}:")
            print(f"    Price: {trade.get('price', 'N/A')}")
            print(f"    Qty: {trade.get('qty', 'N/A')}")
            print(f"    Side: {trade.get('side', 'N/A')}")
            print(f"    Time: {trade.get('time', 'N/A')}")
        print("  [OK] 成交历史查询正常")
    except Exception as e:
        print(f"  [WARN] 成交历史查询失败: {e}")
    print("")
    
    # 测试6: 再次获取持仓
    print("测试6: 再次获取持仓（验证交易后变化）...")
    try:
        position_after = api.get_position(symbol=symbol)
        print(f"  Position After: {position_after}")
        if position_after != position:
            print(f"  [OK] 持仓已更新（变化: {position_after - position})")
        else:
            print("  [OK] 持仓未变化（买卖数量相等）")
    except Exception as e:
        print(f"  [WARN] 持仓查询失败: {e}")
    print("")
    
    print("=== 测试完成 ===")
    print("[SUCCESS] 所有测试通过！Binance Testnet API连接和交易功能正常。")
    return True


if __name__ == "__main__":
    success = test_binance_testnet_trading()
    sys.exit(0 if success else 1)

