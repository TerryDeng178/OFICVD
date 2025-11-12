# F系列实验快速启动脚本
# 用法: .\scripts\run_f_experiments_quick.ps1 [--groups F1,F2,F3] [--date 2025-11-10]

param(
    [string]$Groups = "F1,F2,F3,F4,F5,F6",
    [string]$Date = "2025-11-10",
    [string]$Symbols = "BTCUSDT,ETHUSDT,BNBUSDT",
    [int]$Minutes = 60,
    [string]$Sink = "sqlite",
    [int]$MaxWorkers = 6
)

# 设置编码
$env:PYTHONUTF8 = "1"

# 切换到项目根目录
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptPath
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "F系列实验快速启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "实验组: $Groups"
Write-Host "回测日期: $Date"
Write-Host "交易对: $Symbols"
Write-Host "回测时长: $Minutes 分钟"
Write-Host "信号输出: $Sink"
Write-Host "最大并发: $MaxWorkers"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 运行实验
python scripts/run_f_experiments.py `
    --input deploy/data/ofi_cvd `
    --date $Date `
    --symbols $Symbols `
    --minutes $Minutes `
    --groups $Groups `
    --sink $Sink `
    --max-workers $MaxWorkers

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] F系列实验完成" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[ERROR] F系列实验失败" -ForegroundColor Red
    exit 1
}

