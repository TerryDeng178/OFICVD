# -*- coding: utf-8 -*-
"""Binance期货交易测试脚本

使用python-binance库测试BTC期货买卖功能
"""
import os
import sys
import time
import logging
from datetime import datetime

# 将项目根目录添加到Python路径
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_test():
    print("=== Binance期货交易测试（使用python-binance） ===")
    print("")
    
    # 获取API密钥
    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not secret_key:
        print("[ERROR] BINANCE_API_KEY or BINANCE_API_SECRET environment variables are not set.")
        print("请运行 scripts/setup_binance_testnet_env.ps1 (Windows) 或 .sh (Linux/macOS) 设置环境变量。")
        sys.exit(1)
    
    try:
        from binance.client import Client
    except ImportError:
        print("[ERROR] python-binance未安装")
        print("安装命令: pip install python-binance")
        sys.exit(1)
    
    # 1. 初始化Binance期货客户端（测试网）
    print("[1/7] 初始化Binance期货客户端（测试网）...")
    try:
        client = Client(api_key, secret_key, testnet=True)
        print(f"  [OK] 客户端初始化成功")
        print(f"  Base URL: {client.API_TESTNET_URL}")
    except Exception as e:
        print(f"  [ERROR] 客户端初始化失败: {e}")
        sys.exit(1)
    print("")
    
    # 2. 查询期货账户信息
    print("[2/7] 查询期货账户信息...")
    try:
        account_info = client.futures_account()
        total_balance = account_info.get('totalWalletBalance', '0')
        available_balance = account_info.get('availableBalance', '0')
        print(f"  总余额: {total_balance} USDT")
        print(f"  可用余额: {available_balance} USDT")
        print("  [OK] 账户查询成功")
    except Exception as e:
        print(f"  [ERROR] 账户查询失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
        sys.exit(1)
    print("")
    
    # 3. 查询当前持仓
    print("[3/7] 查询当前BTCUSDT持仓...")
    symbol = "BTCUSDT"
    try:
        positions = client.futures_position_information(symbol=symbol)
        initial_position = 0.0
        if positions:
            for pos in positions:
                if pos['symbol'] == symbol:
                    initial_position = float(pos['positionAmt'])
                    break
        print(f"  当前持仓: {initial_position} BTC")
        print("  [OK] 持仓查询成功")
    except Exception as e:
        print(f"  [ERROR] 持仓查询失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
        sys.exit(1)
    print("")
    
    # 4. 提交市价买单
    print("[4/7] 提交市价买单（0.001 BTC）...")
    buy_order_id = None
    buy_order_qty = 0.001
    try:
        buy_order = client.futures_create_order(
            symbol=symbol,
            side='BUY',
            type='MARKET',
            quantity=buy_order_qty
        )
        buy_order_id = buy_order.get('orderId')
        buy_status = buy_order.get('status')
        buy_executed_qty = buy_order.get('executedQty', '0')
        buy_avg_price = buy_order.get('avgPrice', 'N/A')
        
        print(f"  订单ID: {buy_order_id}")
        print(f"  状态: {buy_status}")
        print(f"  成交量: {buy_executed_qty} BTC")
        print(f"  平均价格: {buy_avg_price} USDT")
        print("  [OK] 买单提交成功")
        
        # 等待订单成交
        time.sleep(2)
    except Exception as e:
        print(f"  [ERROR] 买单提交失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
        
        # 检查是否是权限问题
        error_str = str(e)
        if '-2015' in error_str or 'permissions' in error_str.lower():
            print("  [WARN] 可能是API密钥权限不足")
            print("  请在Binance Testnet账户中启用'期货交易'权限")
        
        sys.exit(1)
    print("")
    
    # 5. 查询买单状态
    print("[5/7] 查询买单状态...")
    try:
        if buy_order_id:
            order_status = client.futures_get_order(symbol=symbol, orderId=buy_order_id)
            print(f"  订单状态: {order_status.get('status')}")
            print(f"  成交量: {order_status.get('executedQty', '0')} BTC")
            print(f"  平均价格: {order_status.get('avgPrice', 'N/A')} USDT")
            print("  [OK] 订单状态查询成功")
    except Exception as e:
        print(f"  [WARN] 订单状态查询失败: {e}")
    print("")
    
    # 6. 查询更新后的持仓
    print("[6/7] 查询更新后的持仓...")
    try:
        positions = client.futures_position_information(symbol=symbol)
        current_position = 0.0
        if positions:
            for pos in positions:
                if pos['symbol'] == symbol:
                    current_position = float(pos['positionAmt'])
                    break
        
        print(f"  更新后持仓: {current_position} BTC")
        position_change = current_position - initial_position
        print(f"  持仓变化: {position_change} BTC")
        
        if abs(position_change - buy_order_qty) < 0.0001:
            print("  [OK] 持仓变化正确（买单已成交）")
        else:
            print(f"  [WARN] 持仓变化异常（预期: {buy_order_qty}, 实际: {position_change}）")
    except Exception as e:
        print(f"  [ERROR] 持仓查询失败: {e}")
    print("")
    
    # 7. 提交市价卖单（平仓）
    print("[7/7] 提交市价卖单（平仓）...")
    try:
        # 获取当前持仓
        positions = client.futures_position_information(symbol=symbol)
        current_position = 0.0
        if positions:
            for pos in positions:
                if pos['symbol'] == symbol:
                    current_position = float(pos['positionAmt'])
                    break
        
        if current_position > 0:
            sell_order = client.futures_create_order(
                symbol=symbol,
                side='SELL',
                type='MARKET',
                quantity=abs(current_position)  # 平仓所有持仓
            )
            sell_order_id = sell_order.get('orderId')
            sell_status = sell_order.get('status')
            sell_executed_qty = sell_order.get('executedQty', '0')
            
            print(f"  订单ID: {sell_order_id}")
            print(f"  状态: {sell_status}")
            print(f"  成交量: {sell_executed_qty} BTC")
            print("  [OK] 卖单提交成功")
            
            # 等待订单成交
            time.sleep(2)
            
            # 查询最终持仓
            positions = client.futures_position_information(symbol=symbol)
            final_position = 0.0
            if positions:
                for pos in positions:
                    if pos['symbol'] == symbol:
                        final_position = float(pos['positionAmt'])
                        break
            
            print(f"  最终持仓: {final_position} BTC")
            if abs(final_position) < 0.00001:
                print("  [OK] 持仓已清零（平仓成功）")
            else:
                print(f"  [WARN] 持仓未完全清零（剩余: {final_position} BTC）")
        else:
            print("  [INFO] 无持仓可卖，跳过卖单测试")
    except Exception as e:
        print(f"  [ERROR] 卖单提交失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
    print("")
    
    print("=== Binance期货交易测试完成 ===")
    print("")
    print("测试总结：")
    print("1. [OK] 账户查询成功")
    print("2. [OK] 持仓查询成功")
    print("3. [OK] 买单提交成功")
    print("4. [OK] 卖单提交成功（如果执行）")
    print("")
    print("注意：如果遇到权限错误，请在Binance Testnet账户中启用'期货交易'权限")

if __name__ == "__main__":
    run_test()

