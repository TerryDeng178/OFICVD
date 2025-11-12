# -*- coding: utf-8 -*-
# Binance Live (实盘) 环境变量设置脚本（PowerShell）

# ⚠️ 警告：这是实盘交易API密钥，请谨慎使用！
# ⚠️ WARNING: These are LIVE trading API keys, use with extreme caution!

# 设置Binance实盘API密钥
$env:BINANCE_API_KEY = "H3cNOsA3rWIQHTAGaCCC3fsyyGY8ZaqdKfBvvefImRN98kJyKVWrjic3uv42LWqx"
$env:BINANCE_API_SECRET = "0qoMq4OiAYM5gyECzHL5Bi51ykp2w5gxyLx1TCeWbO0y3AjrNjGA04BXhpssJ1B3"

Write-Host "[Binance Live] ⚠️  WARNING: LIVE TRADING API KEYS SET!" -ForegroundColor Red
Write-Host "[Binance Live] Environment variables set:"
Write-Host "  BINANCE_API_KEY: $env:BINANCE_API_KEY"
Write-Host "  BINANCE_API_SECRET: [HIDDEN]"
Write-Host ""
Write-Host "⚠️  IMPORTANT SECURITY NOTES:" -ForegroundColor Yellow
Write-Host "  1. These keys are for LIVE trading - real money at risk!"
Write-Host "  2. Never commit these keys to Git repository"
Write-Host "  3. Use environment variables only (not config files)"
Write-Host "  4. Consider using a secrets management service for production"
Write-Host "  5. Review API key permissions (read-only vs trading enabled)"
Write-Host ""
Write-Host "To use live trading, set in config:"
Write-Host "  broker:"
Write-Host "    testnet: false"
Write-Host "    mock_enabled: false"
Write-Host "    dry_run: false"

# 注意：这些环境变量只在当前PowerShell会话中有效
# 如需永久设置，请使用系统环境变量设置（但不推荐，建议使用密钥管理服务）

