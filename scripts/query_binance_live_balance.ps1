# Binance Live Account Balance Query Script (PowerShell)

Write-Host "============================================================"
Write-Host "[WARN] Warning: This script queries Binance LIVE account balance"
Write-Host "[WARN] Real money involved, use with caution!"
Write-Host "============================================================"
Write-Host ""

# 1. Set Binance Live API environment variables
Write-Host "[1/2] Setting Binance Live API environment variables..."
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
. "$scriptPath\setup_binance_live_env.ps1"

# 2. Run Python query script
Write-Host ""
Write-Host "[2/2] Running Python query script..."
$projectRoot = Split-Path -Parent $scriptPath
python "$projectRoot\scripts\query_binance_live_balance.py" --skip-confirm

$lastExitCode = $LASTEXITCODE

if ($lastExitCode -eq 0) {
    Write-Host ""
    Write-Host "=== Query completed ==="
} else {
    Write-Host ""
    Write-Host "=== Query failed ==="
}

exit $lastExitCode
