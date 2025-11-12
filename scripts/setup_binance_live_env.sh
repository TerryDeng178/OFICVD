#!/bin/bash
# Binance Live (实盘) 环境变量设置脚本（Bash）

# ⚠️ 警告：这是实盘交易API密钥，请谨慎使用！
# ⚠️ WARNING: These are LIVE trading API keys, use with extreme caution!

# 设置Binance实盘API密钥
export BINANCE_API_KEY="H3cNOsA3rWIQHTAGaCCC3fsyyGY8ZaqdKfBvvefImRN98kJyKVWrjic3uv42LWqx"
export BINANCE_API_SECRET="0qoMq4OiAYM5gyECzHL5Bi51ykp2w5gxyLx1TCeWbO0y3AjrNjGA04BXhpssJ1B3"

echo "[Binance Live] ⚠️  WARNING: LIVE TRADING API KEYS SET!"
echo "[Binance Live] Environment variables set:"
echo "  BINANCE_API_KEY: $BINANCE_API_KEY"
echo "  BINANCE_API_SECRET: [HIDDEN]"
echo ""
echo "⚠️  IMPORTANT SECURITY NOTES:"
echo "  1. These keys are for LIVE trading - real money at risk!"
echo "  2. Never commit these keys to Git repository"
echo "  3. Use environment variables only (not config files)"
echo "  4. Consider using a secrets management service for production"
echo "  5. Review API key permissions (read-only vs trading enabled)"
echo ""
echo "To use live trading, set in config:"
echo "  broker:"
echo "    testnet: false"
echo "    mock_enabled: false"
echo "    dry_run: false"

# 注意：这些环境变量只在当前shell会话中有效
# 如需永久设置，请添加到 ~/.bashrc 或 ~/.zshrc（但不推荐，建议使用密钥管理服务）

