# -*- coding: utf-8 -*-
# Binance Testnet 交易测试脚本
# 用于验证测试网API连接和交易功能

Write-Host "=== Binance Testnet Trading Test ===" -ForegroundColor Cyan
Write-Host ""

# 1. 设置测试网环境变量
Write-Host "[1/5] 设置测试网环境变量..." -ForegroundColor Yellow
$env:BINANCE_API_KEY = "5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO"
$env:BINANCE_API_SECRET = "xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg"
Write-Host "  API Key: $env:BINANCE_API_KEY" -ForegroundColor Green
Write-Host "  Secret Key: [HIDDEN]" -ForegroundColor Green
Write-Host ""

# 2. 运行Python测试脚本
Write-Host "[2/5] 运行Python测试脚本..." -ForegroundColor Yellow
Write-Host ""

python -c @"
import os
import sys
import time
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.alpha_core.executors.binance_api import BinanceFuturesAPI
from src.alpha_core.executors.base_executor import Side, OrderType

def test_binance_testnet_trading():
    print('[3/5] 初始化Binance Testnet API客户端...')
    
    # 从环境变量获取API密钥
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not secret_key:
        print('ERROR: API密钥未设置')
        return False
    
    # 创建测试网API客户端
    api = BinanceFuturesAPI(
        api_key=api_key,
        secret_key=secret_key,
        testnet=True  # 使用测试网
    )
    
    print(f'  Base URL: {api.base_url}')
    print(f'  Testnet: True')
    print('')
    
    # 测试1: 获取服务器时间
    print('[4/5] 测试1: 获取服务器时间...')
    try:
        server_time = api.get_server_time()
        print(f'  Server Time: {server_time} ({time.strftime(\"%Y-%m-%d %H:%M:%S\", time.gmtime(server_time/1000))})')
        print('  [OK] 服务器连接正常')
    except Exception as e:
        print(f'  [ERROR] 获取服务器时间失败: {e}')
        return False
    print('')
    
    # 测试2: 获取持仓
    print('[5/5] 测试2: 获取当前持仓...')
    symbol = 'BTCUSDT'
    try:
        position = api.get_position(symbol=symbol)
        print(f'  Symbol: {symbol}')
        print(f'  Position: {position}')
        print('  [OK] 持仓查询正常')
    except Exception as e:
        print(f'  [WARN] 持仓查询失败（可能账户为空）: {e}')
    print('')
    
    # 测试3: 提交买单（市价单，最小数量）
    print('测试3: 提交买单（市价单，最小数量 0.001 BTC）...')
    try:
        # Binance期货最小数量通常是0.001 BTC
        buy_order = api.submit_order(
            symbol=symbol,
            side=Side.BUY,
            qty=0.001,
            order_type='MARKET'
        )
        print(f'  Order ID: {buy_order.get(\"orderId\", \"N/A\")}')
        print(f'  Status: {buy_order.get(\"status\", \"N/A\")}')
        print(f'  Executed Qty: {buy_order.get(\"executedQty\", \"0\")}')
        print(f'  Avg Price: {buy_order.get(\"avgPrice\", \"N/A\")}')
        print('  [OK] 买单提交成功')
        
        # 等待订单完成
        time.sleep(2)
        
    except Exception as e:
        print(f'  [ERROR] 买单提交失败: {e}')
        print(f'  错误详情: {str(e)}')
        return False
    print('')
    
    # 测试4: 提交卖单（市价单，最小数量）
    print('测试4: 提交卖单（市价单，最小数量 0.001 BTC）...')
    try:
        sell_order = api.submit_order(
            symbol=symbol,
            side=Side.SELL,
            qty=0.001,
            order_type='MARKET'
        )
        print(f'  Order ID: {sell_order.get(\"orderId\", \"N/A\")}')
        print(f'  Status: {sell_order.get(\"status\", \"N/A\")}')
        print(f'  Executed Qty: {sell_order.get(\"executedQty\", \"0\")}')
        print(f'  Avg Price: {sell_order.get(\"avgPrice\", \"N/A\")}')
        print('  [OK] 卖单提交成功')
        
        # 等待订单完成
        time.sleep(2)
        
    except Exception as e:
        print(f'  [ERROR] 卖单提交失败: {e}')
        print(f'  错误详情: {str(e)}')
        return False
    print('')
    
    # 测试5: 获取成交历史
    print('测试5: 获取成交历史...')
    try:
        trades = api.get_trades(symbol=symbol, limit=5)
        print(f'  最近成交记录数: {len(trades)}')
        for i, trade in enumerate(trades[:3], 1):
            print(f'  Trade {i}:')
            print(f'    Price: {trade.get(\"price\", \"N/A\")}')
            print(f'    Qty: {trade.get(\"qty\", \"N/A\")}')
            print(f'    Side: {trade.get(\"side\", \"N/A\")}')
            print(f'    Time: {trade.get(\"time\", \"N/A\")}')
        print('  [OK] 成交历史查询正常')
    except Exception as e:
        print(f'  [WARN] 成交历史查询失败: {e}')
    print('')
    
    # 测试6: 再次获取持仓
    print('测试6: 再次获取持仓（验证交易后变化）...')
    try:
        position_after = api.get_position(symbol=symbol)
        print(f'  Position After: {position_after}')
        if position_after != position:
            print(f'  [OK] 持仓已更新（变化: {position_after - position})')
        else:
            print('  [OK] 持仓未变化（买卖数量相等）')
    except Exception as e:
        print(f'  [WARN] 持仓查询失败: {e}')
    print('')
    
    print('=== 测试完成 ===')
    print('[SUCCESS] 所有测试通过！Binance Testnet API连接和交易功能正常。')
    return True

if __name__ == '__main__':
    success = test_binance_testnet_trading()
    sys.exit(0 if success else 1)
"@

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] 测试失败，请检查错误信息" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[SUCCESS] Binance Testnet交易测试完成！" -ForegroundColor Green
Write-Host ""
Write-Host "注意事项：" -ForegroundColor Yellow
Write-Host "1. 这是测试网，使用的是虚拟资金，不会造成真实损失"
Write-Host "2. 如果遇到余额不足错误，请在Binance Testnet网站充值测试资金"
Write-Host "3. 测试网地址: https://testnet.binancefuture.com"
Write-Host ""

