# -*- coding: utf-8 -*-
"""测试Binance官方连接器

使用binance-connector测试订单提交功能
注意：binance-connector可能只支持现货，不支持期货
"""
import os
import sys

# 设置API密钥
api_key = os.getenv("BINANCE_API_KEY", "5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO")
secret_key = os.getenv("BINANCE_API_SECRET", "xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg")

print("=== 测试Binance官方连接器 (binance-connector) ===")
print("")

try:
    # 尝试导入binance-connector的Spot（现货）
    from binance.spot import Spot
    
    print("[OK] binance-connector已安装")
    print("[INFO] 注意：binance-connector主要支持现货交易，期货交易可能需要使用python-binance")
    print("")
    
    # 初始化客户端（测试网）
    print("[1/5] 初始化客户端（测试网）...")
    try:
        client = Spot(
            api_key=api_key,
            api_secret=secret_key,
            base_url='https://testnet.binance.com'  # 现货测试网
        )
        print(f"  Base URL: {client.base_url}")
        print("  [OK] 客户端初始化成功（现货）")
    except Exception as e:
        print(f"  [ERROR] 客户端初始化失败: {e}")
        sys.exit(1)
    print("")
    
    # 测试账户查询
    print("[2/5] 测试账户查询...")
    try:
        account = client.account()
        balance = account.get('totalWalletBalance', 'N/A')
        print(f"  账户余额: {balance} USDT")
        print("  [OK] 账户查询成功")
    except Exception as e:
        print(f"  [ERROR] 账户查询失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
    print("")
    
    print("[INFO] binance-connector主要支持现货交易")
    print("[INFO] 对于期货交易，建议使用python-binance库")
    print("")
    
    # 尝试使用python-binance（如果已安装）
    print("[3/5] 尝试使用python-binance（期货）...")
    try:
        from binance.client import Client
        
        futures_client = Client(api_key, secret_key, testnet=True)
        print("  [OK] python-binance已安装")
        
        # 测试期货账户查询
        try:
            account_info = futures_client.futures_account()
            balance = account_info.get('totalWalletBalance', 'N/A')
            print(f"  期货账户余额: {balance} USDT")
            print("  [OK] 期货账户查询成功")
        except Exception as e:
            print(f"  [ERROR] 期货账户查询失败: {e}")
            print(f"  错误详情: {str(e)[:300]}")
            
            # 检查是否是权限问题
            if '-2015' in str(e) or 'permissions' in str(e).lower():
                print("  [WARN] 可能是API密钥权限不足，请在Binance Testnet账户中启用'期货交易'权限")
    except ImportError:
        print("  [INFO] python-binance未安装，跳过期货测试")
        print("  安装命令: pip install python-binance")
    except Exception as e:
        print(f"  [ERROR] python-binance测试失败: {e}")
    print("")
    
    print("=== 测试完成 ===")
    print("")
    print("总结：")
    print("1. binance-connector已安装，主要用于现货交易")
    print("2. 对于期货交易，建议使用python-binance库")
    print("3. 如果遇到权限错误，请在Binance Testnet账户中启用'期货交易'权限")
    
except ImportError as e:
    print("[ERROR] binance-connector未安装")
    print("安装命令: pip install binance-connector")
    print(f"错误详情: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    print(f"错误详情: {str(e)[:500]}")
    sys.exit(1)
