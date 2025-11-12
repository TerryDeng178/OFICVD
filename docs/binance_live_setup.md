# Binance Live (实盘) API 集成指南

## ⚠️ 重要安全警告

**这是实盘交易API密钥，涉及真实资金！请务必：**

1. ✅ **使用环境变量存储密钥**（不要硬编码到配置文件）
2. ✅ **不要将密钥提交到Git仓库**
3. ✅ **在生产环境使用密钥管理服务**（AWS Secrets Manager、Azure Key Vault等）
4. ✅ **检查API密钥权限**（建议先使用只读权限测试）
5. ✅ **设置IP白名单**（限制API密钥只能从特定IP访问）
6. ✅ **启用双因素认证**（2FA）
7. ✅ **定期轮换API密钥**

---

## API密钥配置

### 实盘API密钥

- **API Key**: `H3cNOsA3rWIQHTAGaCCC3fsyyGY8ZaqdKfBvvefImRN98kJyKVWrjic3uv42LWqx`
- **Secret Key**: `0qoMq4OiAYM5gyECzHL5Bi51ykp2w5gxyLx1TCeWbO0y3AjrNjGA04BXhpssJ1B3`

### 配置方式（仅环境变量）

**Windows PowerShell:**
```powershell
# ⚠️ 警告：实盘密钥，谨慎使用！
.\scripts\setup_binance_live_env.ps1

# 或手动设置
$env:BINANCE_API_KEY = "H3cNOsA3rWIQHTAGaCCC3fsyyGY8ZaqdKfBvvefImRN98kJyKVWrjic3uv42LWqx"
$env:BINANCE_API_SECRET = "0qoMq4OiAYM5gyECzHL5Bi51ykp2w5gxyLx1TCeWbO0y3AjrNjGA04BXhpssJ1B3"
```

**Linux/macOS:**
```bash
# ⚠️ 警告：实盘密钥，谨慎使用！
source ./scripts/setup_binance_live_env.sh

# 或手动设置
export BINANCE_API_KEY="H3cNOsA3rWIQHTAGaCCC3fsyyGY8ZaqdKfBvvefImRN98kJyKVWrjic3uv42LWqx"
export BINANCE_API_SECRET="0qoMq4OiAYM5gyECzHL5Bi51ykp2w5gxyLx1TCeWbO0y3AjrNjGA04BXhpssJ1B3"
```

**⚠️ 重要：不要在配置文件中直接写入实盘密钥！**

---

## 配置示例

### Live模式（实盘，真实API）

```yaml
# config/defaults.yaml
executor:
  mode: live

broker:
  name: binance-futures
  api_key_env: BINANCE_API_KEY      # 从环境变量读取
  secret_env: BINANCE_API_SECRET    # 从环境变量读取
  testnet: false      # ⚠️ 实盘模式
  dry_run: false      # ⚠️ 关闭dry-run，真实下单
  mock_enabled: false # ⚠️ 关闭Mock，使用真实API
```

---

## 使用流程

### 1. 设置环境变量

```powershell
# Windows PowerShell
.\scripts\setup_binance_live_env.ps1
```

### 2. 验证配置

```powershell
# 检查环境变量是否设置
echo $env:BINANCE_API_KEY
echo $env:BINANCE_API_SECRET
```

### 3. 运行Strategy Server（实盘模式）

```powershell
# ⚠️ 警告：这将进行真实交易！
python -m mcp.strategy_server.app `
  --config ./config/defaults.yaml `
  --mode live `
  --signals-source auto `
  --symbols BTCUSDT
```

### 4. 通过Orchestrator运行（实盘模式）

```powershell
# ⚠️ 警告：这将进行真实交易！
# 1. 设置环境变量
.\scripts\setup_binance_live_env.ps1

# 2. 运行Orchestrator
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,strategy `
  --sink jsonl `
  --minutes 3
```

---

## 安全最佳实践

### 1. API密钥权限

在Binance账户中设置API密钥权限：
- ✅ **只读权限**：用于测试和监控（推荐先使用）
- ⚠️ **交易权限**：用于实际下单（谨慎启用）
- ❌ **提现权限**：**永远不要启用**（防止资金被盗）

### 2. IP白名单

在Binance账户中设置IP白名单：
- 限制API密钥只能从特定IP地址访问
- 降低密钥泄露风险

### 3. 密钥管理

**开发环境：**
- 使用环境变量（当前会话）
- 使用`.env`文件（添加到`.gitignore`）

**生产环境：**
- 使用密钥管理服务（AWS Secrets Manager、Azure Key Vault、HashiCorp Vault等）
- 使用容器密钥注入（Kubernetes Secrets、Docker Secrets等）
- 使用CI/CD密钥管理（GitHub Secrets、GitLab CI/CD Variables等）

### 4. 监控和告警

- 设置账户余额告警
- 设置异常交易告警
- 监控API调用频率
- 记录所有交易日志

---

## 测试建议

### 阶段1：只读测试

1. 设置API密钥为**只读权限**
2. 使用`mock_enabled: false`和`testnet: false`
3. 测试账户信息查询、持仓查询等功能
4. **不要下单**

### 阶段2：小额测试

1. 设置API密钥为**交易权限**
2. 使用**最小订单量**进行测试
3. 监控订单执行情况
4. 验证成交记录和持仓更新

### 阶段3：逐步扩大

1. 逐步增加订单量
2. 监控系统稳定性
3. 验证风控规则
4. 确认日志和报表正常

---

## 故障排查

### 1. API密钥未找到

**错误**：`API credentials not found`

**解决**：确保设置了环境变量`BINANCE_API_KEY`和`BINANCE_API_SECRET`

### 2. 权限不足

**错误**：`-2010: API-key format invalid`或`-2015: Invalid API-key, IP, or permissions`

**解决**：
- 检查API密钥是否正确
- 检查IP白名单设置
- 检查API密钥权限（是否启用交易权限）

### 3. 余额不足

**错误**：`-2019: Margin is insufficient`

**解决**：
- 检查账户余额
- 检查杠杆设置
- 检查订单数量是否符合最小要求

### 4. 订单被拒绝

**错误**：`-1013: Filter failure: MIN_NOTIONAL`或`-1013: Filter failure: LOT_SIZE`

**解决**：
- 检查订单数量是否符合交易所要求
- 检查价格精度（tick_size）
- 检查数量精度（step_size）
- 检查最小名义额（min_notional）

---

## 风险控制

### 1. 订单大小限制

在`config/defaults.yaml`中设置：

```yaml
executor:
  order_size_usd: 100  # 每单名义额（USD），建议从小额开始
  max_parallel_orders: 1  # 最大并发订单数，建议从1开始
```

### 2. 风控模块

确保启用风控模块：

```yaml
components:
  strategy:
    risk:
      enabled: true  # 启用风控
      position:
        max_notional_usd: 1000  # 最大持仓名义额（USD）
        max_leverage: 1  # 最大杠杆，建议从1开始
```

### 3. 止损和止盈

在策略中设置止损和止盈：

```yaml
backtest:
  take_profit_bps: 50   # 止盈（bps）
  stop_loss_bps: 30     # 止损（bps）
```

---

## 相关文档

- [Binance Testnet设置指南](./binance_testnet_setup.md) - 测试网配置
- [TASK-A2任务卡](../tasks/整合任务/TASK-A2-执行层抽象-IExecutor-Backtest-Live.md)
- [Binance Futures API文档](https://binance-docs.github.io/apidocs/futures/en/)
- [Binance账户安全设置](https://www.binance.com/en/my/settings/api-management)

---

## 紧急情况处理

### 如果发现异常交易：

1. **立即撤销所有挂单**
2. **关闭所有持仓**（如果可能）
3. **禁用API密钥**
4. **检查账户余额和交易记录**
5. **联系Binance客服**

### 如果API密钥泄露：

1. **立即删除泄露的API密钥**
2. **创建新的API密钥**
3. **检查账户是否有异常交易**
4. **更改账户密码**
5. **启用双因素认证（2FA）**

---

**⚠️ 最后提醒：实盘交易涉及真实资金，请务必谨慎操作！**

