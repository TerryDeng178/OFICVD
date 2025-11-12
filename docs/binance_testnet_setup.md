# Binance Testnet API 集成指南

## 概述

本系统已集成Binance期货测试网API，支持真实订单提交、撤销和查询功能。

## API密钥配置

### 方式1：环境变量（推荐）

**Windows PowerShell:**
```powershell
# 设置环境变量
$env:BINANCE_API_KEY = "5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO"
$env:BINANCE_API_SECRET = "xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg"

# 或使用脚本
.\scripts\setup_binance_testnet_env.ps1
```

**Linux/macOS:**
```bash
# 设置环境变量
export BINANCE_API_KEY="5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO"
export BINANCE_API_SECRET="xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg"

# 或使用脚本
source ./scripts/setup_binance_testnet_env.sh
```

### 方式2：配置文件（不推荐，仅用于测试）

在`config/defaults.yaml`中直接配置（不推荐，密钥会暴露）：

```yaml
broker:
  name: binance-futures
  api_key: "5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO"
  secret_key: "xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg"
  testnet: true
  mock_enabled: false  # 设为false使用真实API
```

## 使用模式

### Mock模式（默认）

Mock模式用于测试，不调用真实API：

```yaml
broker:
  mock_enabled: true  # 默认值
```

### 真实API模式

启用真实API调用：

```yaml
broker:
  mock_enabled: false  # 使用真实API
  testnet: true        # 使用测试网
  dry_run: false       # 关闭dry-run模式
```

## 配置示例

### Testnet模式（真实API）

```yaml
executor:
  mode: testnet

broker:
  name: binance-futures
  api_key_env: BINANCE_API_KEY
  secret_env: BINANCE_API_SECRET
  testnet: true
  dry_run: false      # 关闭dry-run，使用真实API
  mock_enabled: false # 关闭Mock，使用真实API
```

### Live模式（真实API，谨慎使用）

```yaml
executor:
  mode: live

broker:
  name: binance-futures
  api_key_env: BINANCE_API_KEY
  secret_env: BINANCE_API_SECRET
  testnet: false      # 使用实盘
  dry_run: false      # 关闭dry-run
  mock_enabled: false # 关闭Mock，使用真实API
```

## 运行示例

### 1. 设置环境变量

```powershell
# Windows PowerShell
.\scripts\setup_binance_testnet_env.ps1
```

### 2. 运行Strategy Server（Testnet模式，真实API）

```powershell
python -m mcp.strategy_server.app `
  --config ./config/defaults.yaml `
  --mode testnet `
  --signals-source auto `
  --symbols BTCUSDT
```

### 3. 通过Orchestrator运行（Testnet模式，真实API）

```powershell
# 先设置环境变量
.\scripts\setup_binance_testnet_env.ps1

# 运行Orchestrator
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,strategy `
  --sink jsonl `
  --minutes 3
```

## API功能

### 已实现功能

- ✅ **订单提交**：支持市价单和限价单
- ✅ **订单撤销**：支持通过订单ID或客户端订单ID撤销
- ✅ **订单查询**：查询订单状态
- ✅ **成交查询**：获取成交历史
- ✅ **持仓查询**：获取当前持仓

### API端点

- `POST /fapi/v1/order` - 提交订单
- `DELETE /fapi/v1/order` - 撤销订单
- `GET /fapi/v1/order` - 查询订单
- `GET /fapi/v1/openOrders` - 获取挂单
- `GET /fapi/v2/account` - 获取账户信息
- `GET /fapi/v1/userTrades` - 获取成交历史

## 安全注意事项

1. **不要将API密钥提交到Git仓库**
2. **使用环境变量存储密钥**（推荐）
3. **测试网密钥可以用于测试，但也要妥善保管**
4. **实盘密钥必须严格保密，建议使用密钥管理服务**

## 错误处理

API调用失败时会记录错误日志并抛出异常：

```python
try:
    broker_order_id = executor.submit(order)
except Exception as e:
    logger.error(f"Failed to submit order: {e}")
    # 处理错误
```

## 测试

运行Broker Gateway集成测试：

```bash
python -m pytest tests/test_executor_broker_gateway.py -v
```

## 故障排查

### 1. API密钥未找到

**错误**：`API credentials not found`

**解决**：确保设置了环境变量`BINANCE_API_KEY`和`BINANCE_API_SECRET`

### 2. 请求失败

**错误**：`Request failed`或`401 Unauthorized`

**解决**：
- 检查API密钥是否正确
- 检查测试网/实盘配置是否匹配
- 检查网络连接

### 3. 订单被拒绝

**错误**：`Order rejected`或`Insufficient balance`

**解决**：
- 检查账户余额
- 检查订单数量是否符合交易所要求（最小数量、步长等）
- 检查交易对是否支持

## 相关文档

- [Binance Live (实盘) 设置指南](./binance_live_setup.md) - 实盘API配置
- [Binance Futures API文档](https://binance-docs.github.io/apidocs/futures/en/)
- [Binance Testnet](https://testnet.binancefuture.com/)
- [TASK-A2任务卡](../tasks/整合任务/TASK-A2-执行层抽象-IExecutor-Backtest-Live.md)

