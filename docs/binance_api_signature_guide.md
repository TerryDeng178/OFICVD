# Binance Futures API 签名指南

**参考文档**：https://developers.binance.com/docs/derivatives/  
**最后更新**：2025-11-12

---

## 概述

本文档基于Binance官方衍生品API文档，说明如何正确生成和使用API签名。

---

## API密钥配置

### 1. 创建API密钥

1. 登录Binance账户（测试网：https://testnet.binancefuture.com/）
2. 进入"API管理"页面
3. 创建新的API密钥
4. 妥善保存API Key和Secret Key（Secret Key只显示一次）

### 2. 设置API权限

**重要**：新创建的API密钥默认仅具有"只读"权限。

**必须启用的权限**：
- ✅ **期货交易**：必须启用才能通过API提交订单
- ✅ **读取**：查询账户信息、持仓等
- ⚠️ **提现**：仅在需要提现时启用（建议禁用以提高安全性）

**设置步骤**：
1. 在API管理页面，找到您的API密钥
2. 点击"编辑权限"
3. 勾选"期货交易"权限
4. 保存更改

**参考链接**：https://developers.binance.com/docs/zh-CN/derivatives/quick-start

---

## 签名生成规则

### 1. 基本规则

1. **签名算法**：HMAC SHA256
2. **参数排序**：按字母顺序排序
3. **签名内容**：所有请求参数（不包括signature本身）

### 2. GET/DELETE请求

**格式**：所有参数（包括timestamp和signature）都在URL query string中

```python
import hmac
import hashlib
from urllib.parse import urlencode

params = {
    "symbol": "BTCUSDT",
    "timestamp": 1234567890000
}

# 1. 按字母顺序排序
sorted_params = sorted(params.items())

# 2. 生成query string
query_string = urlencode(sorted_params)

# 3. 生成签名
signature = hmac.new(
    secret_key.encode("utf-8"),
    query_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()

# 4. 添加签名到参数
params["signature"] = signature

# 5. 发送请求
response = requests.get(url, params=params, headers=headers)
```

### 3. POST请求

**格式**：参数在request body中（JSON格式），timestamp和signature在query string中

```python
import hmac
import hashlib
from urllib.parse import urlencode
import time

# 1. 准备body参数（不包括timestamp）
body_params = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "MARKET",
    "quantity": "0.001"
}

# 2. 添加timestamp（用于签名计算）
timestamp = int(time.time() * 1000)
signature_params = body_params.copy()
signature_params["timestamp"] = timestamp

# 3. 生成签名（基于body参数 + timestamp）
sorted_params = sorted(signature_params.items())
query_string = urlencode(sorted_params)
signature = hmac.new(
    secret_key.encode("utf-8"),
    query_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()

# 4. 发送请求
# Body: JSON格式，包含订单参数（不包括timestamp）
# Query string: 包含timestamp和signature
response = requests.post(
    url,
    json=body_params,  # body中不包含timestamp
    params={"timestamp": timestamp, "signature": signature},  # query string中包含timestamp和signature
    headers={
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/json"
    }
)
```

---

## 常见错误码

### -1022: Signature for this request is not valid

**可能原因**：
1. 签名算法错误
2. 参数排序错误
3. 参数格式错误（如数量/价格未转换为字符串）
4. timestamp格式错误

**解决方法**：
1. 检查签名生成逻辑
2. 确保参数按字母顺序排序
3. 确保数量/价格为字符串格式
4. 确保timestamp为整数（毫秒）

### -1102: Mandatory parameter 'timestamp' was not sent

**可能原因**：
1. timestamp未包含在请求中
2. timestamp格式错误

**解决方法**：
1. 确保timestamp在query string中（POST请求）
2. 确保timestamp为整数（毫秒）

### -2015: Invalid API-key, IP, or permissions for action

**可能原因**：
1. API密钥无效
2. IP地址不在白名单中
3. API密钥权限不足

**解决方法**：
1. 检查API密钥是否正确
2. 检查IP白名单设置
3. **启用"期货交易"权限**

---

## 测试网配置

### 测试网域名

- **期货测试网**：`https://testnet.binancefuture.com`
- **注意**：`https://demo.binance.com/` 不是期货测试网的正确端点

### 测试网特点

- 仅支持通过API进行交易
- 使用虚拟资金，不会造成真实损失
- 需要单独的测试网API密钥

---

## 官方SDK推荐

Binance提供了官方的Python和Java连接器：

### Python连接器

**GitHub**：https://github.com/binance/binance-connector-python

**安装**：
```bash
pip install binance-connector-python
```

**使用示例**：
```python
from binance.um_futures import UMFutures

client = UMFutures(
    key='YOUR_API_KEY',
    secret='YOUR_SECRET_KEY',
    base_url='https://testnet.binancefuture.com'  # 测试网
)

# 提交订单
response = client.new_order(
    symbol='BTCUSDT',
    side='BUY',
    type='MARKET',
    quantity=0.001
)
```

### Java连接器

**GitHub**：https://github.com/binance/binance-connector-java

---

## 最佳实践

1. **安全性**：
   - 使用环境变量存储API密钥
   - 不要将API密钥硬编码到代码中
   - 设置IP白名单以提高安全性
   - 仅授予必要的权限

2. **错误处理**：
   - 实现重试机制
   - 处理常见的错误码
   - 记录详细的错误日志

3. **时间同步**：
   - 确保系统时间准确
   - Binance要求timestamp与服务器时间的偏差不超过1000毫秒

4. **参数格式**：
   - 数量/价格必须为字符串格式
   - timestamp必须为整数（毫秒）
   - 确保参数值符合交易所要求（最小数量、步长等）

---

## 相关链接

- **官方文档**：https://developers.binance.com/docs/derivatives/
- **快速开始**：https://developers.binance.com/docs/zh-CN/derivatives/quick-start
- **Python连接器**：https://github.com/binance/binance-connector-python
- **测试网**：https://testnet.binancefuture.com/
- **API参考**：https://binance-docs.github.io/apidocs/futures/en/

---

**注意**：本文档基于Binance官方文档编写，如有更新，请参考官方文档获取最新信息。

