# Test Custom Binance API Implementation (Testnet)

Write-Host "=== Testing Custom Binance API Implementation (Testnet) ==="
Write-Host ""

# 1. Set Binance Testnet API environment variables
Write-Host "[1/2] Setting Binance Testnet API environment variables..."
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
. "$scriptPath\setup_binance_testnet_env.ps1"

# 2. Run Python test script
Write-Host ""
Write-Host "[2/2] Running Python test script..."
$projectRoot = Split-Path -Parent $scriptPath
python "$projectRoot\scripts\test_custom_binance_api_live.py"

$lastExitCode = $LASTEXITCODE

if ($lastExitCode -eq 0) {
    Write-Host ""
    Write-Host "=== Test completed ==="
} else {
    Write-Host ""
    Write-Host "=== Test failed ==="
}

exit $lastExitCode

