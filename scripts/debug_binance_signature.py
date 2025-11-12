# -*- coding: utf-8 -*-
"""Binance API签名调试脚本

用于调试POST请求的签名问题
"""
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

# 从环境变量获取API密钥
api_key = os.getenv("BINANCE_API_KEY", "5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO")
secret_key = os.getenv("BINANCE_API_SECRET", "xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg")

base_url = "https://testnet.binancefuture.com"

def test_signature_methods():
    """测试不同的签名方法"""
    symbol = "BTCUSDT"
    side = "BUY"
    order_type = "MARKET"
    quantity = "0.001"
    
    timestamp = int(time.time() * 1000)
    
    # 方法1：签名基于body + timestamp（当前方法）
    body_params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
    }
    
    sig_params_1 = body_params.copy()
    sig_params_1["timestamp"] = timestamp
    query_1 = urlencode(sorted(sig_params_1.items()))
    signature_1 = hmac.new(secret_key.encode(), query_1.encode(), hashlib.sha256).hexdigest()
    
    print("=== 方法1：签名基于body + timestamp ===")
    print(f"Body: {body_params}")
    print(f"Signature params: {sig_params_1}")
    print(f"Query string: {query_1}")
    print(f"Signature: {signature_1}")
    
    # 测试请求
    try:
        r1 = requests.post(
            f"{base_url}/fapi/v1/order",
            json=body_params,
            params={"timestamp": timestamp, "signature": signature_1},
            headers={"X-MBX-APIKEY": api_key, "Content-Type": "application/json"},
            timeout=10
        )
        print(f"Status: {r1.status_code}")
        print(f"Response: {r1.text[:200]}")
        if r1.status_code == 200:
            print("✅ 方法1成功！")
            return True
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # 方法2：签名只基于body（不包括timestamp）
    sig_params_2 = body_params.copy()
    query_2 = urlencode(sorted(sig_params_2.items()))
    signature_2 = hmac.new(secret_key.encode(), query_2.encode(), hashlib.sha256).hexdigest()
    
    print("=== 方法2：签名只基于body（不包括timestamp）===")
    print(f"Body: {body_params}")
    print(f"Signature params: {sig_params_2}")
    print(f"Query string: {query_2}")
    print(f"Signature: {signature_2}")
    
    # 测试请求
    try:
        r2 = requests.post(
            f"{base_url}/fapi/v1/order",
            json=body_params,
            params={"timestamp": timestamp, "signature": signature_2},
            headers={"X-MBX-APIKEY": api_key, "Content-Type": "application/json"},
            timeout=10
        )
        print(f"Status: {r2.status_code}")
        print(f"Response: {r2.text[:200]}")
        if r2.status_code == 200:
            print("✅ 方法2成功！")
            return True
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # 方法3：所有参数都在query string中（GET方式）
    all_params = body_params.copy()
    all_params["timestamp"] = timestamp
    query_3 = urlencode(sorted(all_params.items()))
    signature_3 = hmac.new(secret_key.encode(), query_3.encode(), hashlib.sha256).hexdigest()
    all_params["signature"] = signature_3
    
    print("=== 方法3：所有参数都在query string中（GET方式）===")
    print(f"All params: {all_params}")
    print(f"Query string: {query_3}")
    print(f"Signature: {signature_3}")
    
    # 测试请求（使用form-data）
    try:
        r3 = requests.post(
            f"{base_url}/fapi/v1/order",
            data=all_params,
            headers={"X-MBX-APIKEY": api_key},
            timeout=10
        )
        print(f"Status: {r3.status_code}")
        print(f"Response: {r3.text[:200]}")
        if r3.status_code == 200:
            print("✅ 方法3成功！")
            return True
    except Exception as e:
        print(f"Error: {e}")
    
    return False

if __name__ == "__main__":
    print("=== Binance API签名调试 ===")
    print(f"Base URL: {base_url}")
    print(f"API Key: {api_key[:20]}...")
    print(f"Secret Key: [HIDDEN]")
    print("")
    
    success = test_signature_methods()
    
    if not success:
        print("\n❌ 所有方法都失败了")
        print("请检查：")
        print("1. API密钥是否正确")
        print("2. API密钥是否有交易权限")
        print("3. 测试网账户是否有足够的余额")
        print("4. 网络连接是否正常")

