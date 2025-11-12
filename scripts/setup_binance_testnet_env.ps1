# -*- coding: utf-8 -*-
# Binance Testnet环境变量设置脚本（PowerShell）

# 设置Binance测试网API密钥
$env:BINANCE_API_KEY = "5pepw8seV1k8iM657Vx27K5QOZmNMrBDYwRKEjWNkEPhPYT4S9iEcEP4zG4eaneO"
$env:BINANCE_API_SECRET = "xkPd7n4Yh5spIDik2WKLppOxn5TxcZgNzJvIiFswXw0kdY3ceGIfMSbndaffMggg"

Write-Host "[Binance Testnet] Environment variables set:"
Write-Host "  BINANCE_API_KEY: $env:BINANCE_API_KEY"
Write-Host "  BINANCE_API_SECRET: [HIDDEN]"

# 注意：这些环境变量只在当前PowerShell会话中有效
# 如需永久设置，请使用系统环境变量设置或.env文件

