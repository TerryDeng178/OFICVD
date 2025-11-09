# T08: Demo Backtest Script (PowerShell)
# Example usage of replay_harness.py

param(
    [string]$InputDir = "./deploy/data/ofi_cvd",
    [string]$Date = "2025-10-30",
    [string]$Symbols = "BTCUSDT",
    [string]$Kinds = "features",
    [int]$Minutes = 60,
    [string]$Config = "./config/backtest.yaml",
    [string]$Output = "./runtime/backtest"
)

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "T08: Backtest Demo" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Input: $InputDir" -ForegroundColor Yellow
Write-Host "Date: $Date" -ForegroundColor Yellow
Write-Host "Symbols: $Symbols" -ForegroundColor Yellow
Write-Host "Kinds: $Kinds" -ForegroundColor Yellow
Write-Host "Minutes: $Minutes" -ForegroundColor Yellow
Write-Host ""

# Run backtest
python scripts/replay_harness.py `
    --input $InputDir `
    --date $Date `
    --symbols $Symbols `
    --kinds $Kinds `
    --minutes $Minutes `
    --config $Config `
    --output $Output

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Backtest completed successfully!" -ForegroundColor Green
    
    # Find latest run_id
    $latestRun = Get-ChildItem -Path $Output -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestRun) {
        Write-Host ""
        Write-Host "Output files:" -ForegroundColor Cyan
        Write-Host "  Run ID: $($latestRun.Name)" -ForegroundColor Gray
        Write-Host "  Metrics: $($latestRun.FullName)\metrics.json" -ForegroundColor Gray
        Write-Host "  Trades: $($latestRun.FullName)\trades.jsonl" -ForegroundColor Gray
        Write-Host "  PnL Daily: $($latestRun.FullName)\pnl_daily.jsonl" -ForegroundColor Gray
        Write-Host "  Manifest: $($latestRun.FullName)\run_manifest.json" -ForegroundColor Gray
    }
} else {
    Write-Host ""
    Write-Host "Backtest failed!" -ForegroundColor Red
    exit 1
}

