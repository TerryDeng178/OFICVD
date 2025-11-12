# -*- coding: utf-8 -*-
"""Binance实盘账户余额查询脚本

[WARN] 警告：此脚本查询实盘账户余额，涉及真实资金！

使用方法：
    python scripts/query_binance_live_balance.py [--skip-confirm]
"""
import os
import sys
import logging
import argparse
from datetime import datetime

# 将项目根目录添加到Python路径
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def query_live_balance(skip_confirm=False):
    print("=" * 60)
    print("[WARN] 警告：此脚本查询Binance实盘账户余额")
    print("[WARN] 涉及真实资金，请谨慎操作！")
    print("=" * 60)
    print("")
    
    # 获取API密钥
    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not secret_key:
        print("[ERROR] BINANCE_API_KEY or BINANCE_API_SECRET environment variables are not set.")
        print("请运行 scripts/setup_binance_live_env.ps1 (Windows) 或 .sh (Linux/macOS) 设置环境变量。")
        sys.exit(1)
    
    # 确认操作（除非跳过）
    print("当前API Key: " + api_key[:20] + "...")
    print("")
    if not skip_confirm:
        try:
            confirm = input("确认查询实盘账户余额？(yes/no): ").strip().lower()
            if confirm != 'yes':
                print("操作已取消。")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n操作已取消。")
            sys.exit(0)
    else:
        print("[INFO] 跳过确认（使用 --skip-confirm 参数）")
    print("")
    
    try:
        from binance.client import Client
    except ImportError:
        print("[ERROR] python-binance未安装")
        print("安装命令: pip install python-binance")
        sys.exit(1)
    
    # 1. 初始化Binance客户端（实盘）
    print("[1/4] 初始化Binance客户端（实盘）...")
    try:
        # 实盘模式：testnet=False
        client = Client(api_key, secret_key, testnet=False)
        print(f"  [OK] 客户端初始化成功")
        print(f"  Base URL: {client.API_URL}")
        print(f"  [WARN] 实盘模式已启用")
    except Exception as e:
        print(f"  [ERROR] 客户端初始化失败: {e}")
        sys.exit(1)
    print("")
    
    # 2. 查询现货账户余额
    print("[2/4] 查询现货账户余额...")
    try:
        account = client.get_account()
        balances = account.get('balances', [])
        
        print("  现货账户余额：")
        non_zero_balances = []
        for balance in balances:
            free = float(balance.get('free', 0))
            locked = float(balance.get('locked', 0))
            total = free + locked
            if total > 0:
                asset = balance.get('asset', '')
                non_zero_balances.append({
                    'asset': asset,
                    'free': free,
                    'locked': locked,
                    'total': total
                })
        
        if non_zero_balances:
            for bal in sorted(non_zero_balances, key=lambda x: x['total'], reverse=True):
                print(f"    {bal['asset']:8s}: {bal['total']:>20.8f} (可用: {bal['free']:>20.8f}, 锁定: {bal['locked']:>20.8f})")
        else:
            print("    无余额")
        print("  [OK] 现货账户查询成功")
    except Exception as e:
        print(f"  [ERROR] 现货账户查询失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
    print("")
    
    # 3. 查询期货账户余额
    print("[3/4] 查询期货账户余额...")
    try:
        futures_account = client.futures_account()
        total_balance = futures_account.get('totalWalletBalance', '0')
        available_balance = futures_account.get('availableBalance', '0')
        margin_balance = futures_account.get('totalMarginBalance', '0')
        unrealized_pnl = futures_account.get('totalUnrealizedProfit', '0')
        
        print("  期货账户信息：")
        print(f"    总余额: {total_balance} USDT")
        print(f"    可用余额: {available_balance} USDT")
        print(f"    保证金余额: {margin_balance} USDT")
        print(f"    未实现盈亏: {unrealized_pnl} USDT")
        print("  [OK] 期货账户查询成功")
    except Exception as e:
        print(f"  [ERROR] 期货账户查询失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
        
        # 检查是否是权限问题
        error_str = str(e)
        if '-2015' in error_str or 'permissions' in error_str.lower():
            print("  [WARN] 可能是API密钥权限不足")
            print("  请在Binance账户中启用'期货交易'权限")
    print("")
    
    # 4. 查询期货持仓
    print("[4/4] 查询期货持仓...")
    try:
        positions = client.futures_position_information()
        active_positions = []
        
        for pos in positions:
            position_amt = float(pos.get('positionAmt', 0))
            if abs(position_amt) > 0.00001:  # 过滤掉接近0的持仓
                active_positions.append({
                    'symbol': pos.get('symbol', ''),
                    'positionAmt': position_amt,
                    'entryPrice': float(pos.get('entryPrice', 0)),
                    'markPrice': float(pos.get('markPrice', 0)),
                    'unRealizedProfit': float(pos.get('unRealizedProfit', 0)),
                    'leverage': pos.get('leverage', '1'),
                })
        
        if active_positions:
            print("  当前持仓：")
            for pos in active_positions:
                side = "多头" if pos['positionAmt'] > 0 else "空头"
                print(f"    {pos['symbol']:12s}: {abs(pos['positionAmt']):>15.8f} ({side})")
                print(f"      入场价格: {pos['entryPrice']:.2f}, 标记价格: {pos['markPrice']:.2f}")
                print(f"      未实现盈亏: {pos['unRealizedProfit']:.2f} USDT, 杠杆: {pos['leverage']}x")
        else:
            print("  无持仓")
        print("  [OK] 持仓查询成功")
    except Exception as e:
        print(f"  [ERROR] 持仓查询失败: {e}")
        print(f"  错误详情: {str(e)[:300]}")
    print("")
    
    print("=" * 60)
    print("查询完成")
    print("=" * 60)
    print("")
    print("[WARN] 注意：这是实盘账户，请妥善保管API密钥！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='查询Binance实盘账户余额')
    parser.add_argument('--skip-confirm', action='store_true', help='跳过确认提示（非交互式模式）')
    args = parser.parse_args()
    
    query_live_balance(skip_confirm=args.skip_confirm)

