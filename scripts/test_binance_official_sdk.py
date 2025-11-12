# -*- coding: utf-8 -*-
"""测试Binance官方SDK

用于对比官方SDK的实现方式
"""
import os
import sys

# 设置API密钥
os.environ['BINANCE_API_KEY'] = '5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO'
os.environ['BINANCE_API_SECRET'] = 'xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg'

print("=== 测试Binance官方SDK ===")
print("")

# 尝试导入python-binance
try:
    from binance.client import Client
    print("[OK] python-binance已安装")
    
    # 初始化客户端（测试网）
    client = Client(
        api_key=os.environ['BINANCE_API_KEY'],
        api_secret=os.environ['BINANCE_API_SECRET'],
        testnet=True
    )
    
    print("[OK] 客户端初始化成功")
    
    # 测试账户查询
    try:
        account = client.get_account()
        print(f"[OK] 账户查询成功，余额: {account.get('totalWalletBalance', 'N/A')}")
    except Exception as e:
        print(f"[ERROR] 账户查询失败: {e}")
    
    # 注意：python-binance可能不支持Futures API，需要python-binance-futures
    
except ImportError:
    print("[WARN] python-binance未安装")
    print("安装命令: pip install python-binance")

# 尝试导入ccxt（另一个流行的交易所库）
try:
    import ccxt
    print("[OK] ccxt已安装")
    
    exchange = ccxt.binance({
        'apiKey': os.environ['BINANCE_API_KEY'],
        'secret': os.environ['BINANCE_API_SECRET'],
        'sandbox': True,  # 测试网
        'options': {
            'defaultType': 'future',  # 期货
        }
    })
    
    print("[OK] ccxt Binance Futures客户端初始化成功")
    
    # 测试账户查询
    try:
        balance = exchange.fetch_balance()
        print(f"[OK] 账户查询成功，USDT余额: {balance.get('USDT', {}).get('free', 'N/A')}")
    except Exception as e:
        print(f"[ERROR] 账户查询失败: {e}")
    
    # 测试订单提交
    try:
        print("\n尝试提交测试订单...")
        order = exchange.create_market_order('BTC/USDT', 'buy', 0.001)
        print(f"[OK] 订单提交成功: {order}")
    except Exception as e:
        print(f"[ERROR] 订单提交失败: {e}")
        print(f"错误详情: {str(e)[:300]}")
    
except ImportError:
    print("[WARN] ccxt未安装")
    print("安装命令: pip install ccxt")

print("\n=== 测试完成 ===")

