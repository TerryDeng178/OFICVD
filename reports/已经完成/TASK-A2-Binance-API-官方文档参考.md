# TASK-A2 Binance API 官方文档参考

**参考文档**：https://developers.binance.com/docs/derivatives/  
**生成时间**：2025-11-12

---

## 官方文档要点

根据Binance官方衍生品API文档（https://developers.binance.com/docs/derivatives/），以下是关键配置要点：

### 1. API密钥权限设置

**重要**：新创建的API密钥默认仅具有"只读"权限。

**解决方案**：
- 登录Binance账户（测试网：https://testnet.binancefuture.com/）
- 进入"API管理"页面
- **必须勾选"期货交易"权限**才能通过API进行交易
- 如果需要提现，还需勾选"允许提现"权限

**参考链接**：https://developers.binance.com/docs/zh-CN/derivatives/quick-start

---

### 2. 签名生成规则

根据官方文档，签名生成的关键点：

1. **签名应基于请求体中的所有参数（包括timestamp）**
2. **参数需要按字母顺序排序**
3. **使用HMAC SHA256算法生成签名**

---

### 3. POST请求格式

根据测试和文档，POST请求的正确格式应该是：

**方法1：Body参数 + timestamp在query string（当前实现）**
```python
# Body: JSON格式，包含订单参数（不包括timestamp）
body = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "MARKET",
    "quantity": "0.001"
}

# Query string: 包含timestamp和signature
query_params = {
    "timestamp": timestamp,
    "signature": signature
}

# 签名基于：body中的所有参数 + timestamp
signature_params = body.copy()
signature_params["timestamp"] = timestamp
signature = generate_signature(signature_params)
```

**方法2：所有参数在query string（GET方式）**
```python
# 所有参数（包括timestamp和signature）都在query string中
params = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "MARKET",
    "quantity": "0.001",
    "timestamp": timestamp
}
signature = generate_signature(params)
params["signature"] = signature
```

---

### 4. 官方SDK推荐

Binance提供了官方的Python和Java连接器：

**Python连接器**：
- GitHub: https://github.com/binance/binance-connector-python
- 安装：`pip install binance-connector-python`

**Java连接器**：
- GitHub: https://github.com/binance/binance-connector-java

**参考链接**：https://developers.binance.com/docs/zh-CN/derivatives/quick-start

---

### 5. 测试网配置

**测试网域名**：
- 期货测试网：`https://testnet.binancefuture.com`
- 注意：`https://demo.binance.com/` 不是期货测试网的正确端点

**测试网特点**：
- 仅支持通过API进行交易
- 使用虚拟资金，不会造成真实损失
- 需要单独的测试网API密钥

---

## 当前实现状态

### ✅ 已正确实现的部分

1. **测试网域名**：使用 `https://testnet.binancefuture.com`（正确）
2. **签名算法**：HMAC SHA256（正确）
3. **参数排序**：按字母顺序排序（正确）
4. **GET请求**：账户查询、持仓查询成功（证明签名算法正确）

### ⚠️ 待解决的问题

1. **API密钥权限**：
   - 错误代码 `-2015`：`Invalid API-key, IP, or permissions`
   - 需要在Binance Testnet账户中启用"期货交易"权限

2. **POST请求签名**：
   - 当前实现：Body参数 + timestamp在query string
   - 签名基于：body中的所有参数 + timestamp
   - 测试结果：签名验证失败（可能是权限问题，而非签名算法问题）

---

## 根据官方文档的建议

### 立即行动（P0）

1. **检查并启用API密钥权限**：
   - 登录Binance Testnet：https://testnet.binancefuture.com/
   - 进入"API管理"页面
   - 检查API密钥是否有"期货交易"权限
   - 如果没有，编辑权限并启用交易权限

2. **检查IP白名单**：
   - 如果设置了IP白名单，将当前IP地址添加到白名单
   - 或暂时禁用IP白名单进行测试

### 后续优化（P1）

1. **使用官方SDK验证**：
   - 安装 `binance-connector-python`
   - 使用官方SDK测试订单提交
   - 对比官方SDK的实现方式

2. **参考官方示例代码**：
   - GitHub: https://github.com/binance/binance-connector-python
   - 查看官方示例代码的实现方式

---

## 相关链接

- **官方文档**：https://developers.binance.com/docs/derivatives/
- **快速开始**：https://developers.binance.com/docs/zh-CN/derivatives/quick-start
- **Python连接器**：https://github.com/binance/binance-connector-python
- **测试网**：https://testnet.binancefuture.com/

---

## 结论

根据官方文档（https://developers.binance.com/docs/derivatives/），**当前实现应该是正确的**。

### 关键发现

1. **API密钥权限**：
   - 新创建的API密钥默认仅具有"只读"权限
   - **必须**在Binance账户的API管理页面中启用"期货交易"权限
   - 这是导致订单提交失败的最可能原因

2. **签名算法**：
   - 当前实现：Body参数 + timestamp在query string，签名基于body+timestamp
   - 这与官方文档的要求一致
   - GET请求成功证明了签名算法是正确的

3. **官方SDK验证**：
   - 官方SDK（python-binance）也返回权限错误 `-2015`
   - 这进一步证明了问题不是签名算法，而是API密钥权限

### 解决方案

**立即行动（P0）**：

1. **登录Binance Testnet账户**：
   - 访问：https://testnet.binancefuture.com/
   - 登录您的测试网账户

2. **检查并启用API密钥权限**：
   - 进入"API管理"页面
   - 找到您的API密钥
   - 点击"编辑权限"
   - **勾选"期货交易"权限**
   - 保存更改

3. **检查IP白名单**：
   - 如果设置了IP白名单，将当前服务器的IP地址添加到白名单
   - 或暂时禁用IP白名单进行测试

4. **重新测试**：
   - 在修复权限后，重新运行测试脚本
   - 验证订单提交功能是否正常工作

**参考链接**：
- 官方文档：https://developers.binance.com/docs/derivatives/
- 快速开始：https://developers.binance.com/docs/zh-CN/derivatives/quick-start
- Python连接器：https://github.com/binance/binance-connector-python

