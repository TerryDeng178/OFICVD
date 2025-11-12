# Binance API 快速参考

## 测试网 vs 实盘

### 测试网（Testnet）

- **API Key**: `5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO`
- **Secret Key**: `xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg`
- **用途**: 测试和开发
- **设置脚本**: `.\scripts\setup_binance_testnet_env.ps1`
- **文档**: `docs/binance_testnet_setup.md`

### 实盘（Live）

- **API Key**: `H3cNOsA3rWIQHTAGaCCC3fsyyGY8ZaqdKfBvvefImRN98kJyKVWrjic3uv42LWqx`
- **Secret Key**: `0qoMq4OiAYM5gyECzHL5Bi51ykp2w5gxyLx1TCeWbO0y3AjrNjGA04BXhpssJ1B3`
- **用途**: ⚠️ 真实交易（涉及真实资金）
- **设置脚本**: `.\scripts\setup_binance_live_env.ps1`
- **文档**: `docs/binance_live_setup.md`

## 快速切换

### 切换到测试网

```powershell
.\scripts\setup_binance_testnet_env.ps1
```

配置：
```yaml
broker:
  testnet: true
  mock_enabled: false  # 使用真实测试网API
```

### 切换到实盘

```powershell
# ⚠️ 警告：实盘交易！
.\scripts\setup_binance_live_env.ps1
```

配置：
```yaml
broker:
  testnet: false      # ⚠️ 实盘
  mock_enabled: false # ⚠️ 使用真实API
  dry_run: false     # ⚠️ 真实下单
```

## 安全提醒

1. ✅ **使用环境变量**（不要硬编码）
2. ✅ **不要提交密钥到Git**
3. ✅ **实盘密钥必须严格保密**
4. ✅ **建议使用密钥管理服务**

