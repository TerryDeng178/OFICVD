# E组实验快速启动脚本（PowerShell）
# 用途：一键启动E1/E2/E3三个实验

$env:PYTHONUTF8=1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "E组实验快速启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 默认参数
$inputDir = "deploy/data/ofi_cvd"
$date = "2025-11-09"
$symbols = "BTCUSDT,ETHUSDT,BNBUSDT"
$minutes = 60
$groups = "E1,E2,E3"

# 解析命令行参数（简单版本）
if ($args.Count -gt 0) {
    $inputDir = $args[0]
}
if ($args.Count -gt 1) {
    $date = $args[1]
}
if ($args.Count -gt 2) {
    $symbols = $args[2]
}
if ($args.Count -gt 3) {
    $minutes = [int]$args[3]
}

Write-Host "输入目录: $inputDir" -ForegroundColor Yellow
Write-Host "日期: $date" -ForegroundColor Yellow
Write-Host "交易对: $symbols" -ForegroundColor Yellow
Write-Host "时长: $minutes 分钟" -ForegroundColor Yellow
Write-Host "实验组: $groups" -ForegroundColor Yellow
Write-Host ""

# 切换到项目根目录
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptPath
Set-Location $projectRoot

Write-Host "项目根目录: $projectRoot" -ForegroundColor Green
Write-Host ""

# 运行实验
Write-Host "开始运行E组实验..." -ForegroundColor Cyan
Write-Host ""

python scripts/run_e_experiments.py `
    --input $inputDir `
    --date $date `
    --symbols $symbols `
    --minutes $minutes `
    --groups $groups

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] E组实验运行完成" -ForegroundColor Green
    Write-Host ""
    Write-Host "下一步：运行验收脚本" -ForegroundColor Yellow
    Write-Host "  python scripts/validate_e_experiments.py" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "[ERROR] E组实验运行失败" -ForegroundColor Red
    exit 1
}

