# STAGE-2实验快速启动脚本（PowerShell）
# 基于Trial 5基线，运行F2-F5优化实验

$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "STAGE-2实验快速启动"
Write-Host "========================================"
Write-Host ""

# 配置参数
$inputDir = "deploy/data/ofi_cvd"
$date = "2025-11-10"
$symbols = "BTCUSDT,ETHUSDT,BNBUSDT"
$minutes = 1440  # 24小时
$sink = "sqlite"
$maxWorkers = 6

Write-Host "输入目录: $inputDir"
Write-Host "回测日期: $date"
Write-Host "交易对: $symbols"
Write-Host "回测时长: $minutes 分钟 ($($minutes/60) 小时)"
Write-Host "信号输出: $sink"
Write-Host "最大并发: $maxWorkers"
Write-Host ""

# 设置环境变量
$env:PYTHONUTF8 = "1"

# 运行实验
Write-Host "开始运行STAGE-2实验..."
Write-Host ""

python scripts/run_stage2_experiments.py `
  --input $inputDir `
  --date $date `
  --symbols $symbols `
  --minutes $minutes `
  --groups F2,F3,F4,F5,COMBINED `
  --sink $sink `
  --max-workers $maxWorkers

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "STAGE-2实验完成"
    Write-Host "========================================"
    Write-Host ""
    Write-Host "查看结果:"
    Write-Host "  Get-ChildItem runtime\optimizer\stage2_* | Sort-Object LastWriteTime -Descending | Select-Object -First 1"
} else {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "STAGE-2实验失败"
    Write-Host "========================================"
    exit 1
}

