# TASK-A2 签名算法对比和自定义实现验证报告

**生成时间**：2025-11-12  
**状态**：部分完成

---

## 执行总结

### ✅ 已完成

1. **签名算法对比脚本**：`scripts/compare_binance_signature.py`
   - ✅ GET请求签名验证通过（账户查询、持仓查询）
   - ✅ 自定义实现与python-binance的GET请求签名一致

2. **自定义实现验证脚本**：`scripts/test_custom_binance_api_live.py`
   - ✅ GET请求功能正常（账户查询、持仓查询）
   - ✅ 签名算法正确（GET请求）

### ⚠️ 待解决问题

**POST请求签名验证失败**：
- ❌ 订单提交（POST请求）签名验证失败
- 错误代码：`-1022` (Signature for this request is not valid)
- 当前实现：Body参数 + timestamp在query string，签名基于body+timestamp
- python-binance：可以成功提交订单（已验证）

---

## 测试结果

### GET请求（✅ 通过）

**测试用例**：
1. 账户查询：`GET /fapi/v2/account`
2. 持仓查询：`GET /fapi/v2/positionRisk`

**结果**：
- ✅ python-binance：成功
- ✅ 自定义实现：成功
- ✅ 签名算法一致

### POST请求（❌ 失败）

**测试用例**：
1. 订单提交：`POST /fapi/v1/order`

**结果**：
- ✅ python-binance：成功（已验证）
- ❌ 自定义实现：失败（签名验证失败）

**错误信息**：
```
400 Client Error: Bad Request
{"code": -1022, "msg": "Signature for this request is not valid."}
```

---

## 签名算法实现对比

### 自定义实现（当前）

```python
def _generate_signature(self, params: Dict) -> str:
    params_clean = {k: v for k, v in params.items() if k != "signature"}
    params_str = {k: str(v) for k, v in params_clean.items()}
    query_string = urlencode(sorted(params_str.items()))
    signature = hmac.new(
        self.secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature

# POST请求
body_params = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.001"}
signature_params = body_params.copy()
signature_params["timestamp"] = timestamp
signature = self._generate_signature(signature_params)

# 请求
requests.post(url, json=body_params, params={"timestamp": timestamp, "signature": signature})
```

### python-binance（参考）

- ✅ 可以成功提交订单
- ⚠️ 不直接暴露签名方法（需要通过源码分析）

---

## 问题分析

### 可能的原因

1. **POST请求签名方式不同**：
   - Binance API可能对POST请求的签名有特殊要求
   - 可能需要使用不同的签名生成方式

2. **参数格式问题**：
   - 虽然已确保所有值为字符串，但可能还有其他格式要求
   - 可能需要检查参数名称的大小写

3. **时间戳格式问题**：
   - timestamp可能需要特定的格式或精度

### 下一步行动

1. **分析python-binance源码**：
   - 查看python-binance如何处理POST请求的签名
   - 对比签名生成的具体步骤

2. **查阅Binance官方文档**：
   - 确认POST请求签名的具体要求
   - 查看是否有特殊说明

3. **测试不同的签名方式**：
   - 尝试不同的参数组合
   - 测试不同的签名生成方法

---

## 建议

### 短期方案

1. **继续使用python-binance**：
   - 对于POST请求（订单提交），暂时使用python-binance
   - 自定义实现用于GET请求（查询类操作）

2. **混合方案**：
   - GET请求：使用自定义实现（已验证正确）
   - POST请求：使用python-binance（已验证可用）

### 长期方案

1. **深入分析python-binance源码**：
   - 理解POST请求签名的具体实现
   - 修复自定义实现的签名算法

2. **参考官方文档**：
   - 查阅Binance官方API文档
   - 确认POST请求签名的正确方式

---

## 相关文件

- **签名对比脚本**：`scripts/compare_binance_signature.py`
- **自定义实现测试脚本**：`scripts/test_custom_binance_api_live.py`
- **自定义实现**：`src/alpha_core/executors/binance_api.py`
- **官方SDK测试脚本**：`scripts/test_binance_futures_trading.py`

---

## 结论

1. ✅ **GET请求签名算法正确**：自定义实现与python-binance一致
2. ❌ **POST请求签名算法待修复**：需要进一步分析和调试
3. ✅ **临时解决方案可用**：使用python-binance处理POST请求

**建议**：在修复POST请求签名之前，可以继续使用python-binance进行订单提交操作。

