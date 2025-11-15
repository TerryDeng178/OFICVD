# Signal v2 回测验证脚本（PowerShell）
# TASK-A4: 回测验证 - confirm率/decision_code分布/契约一致性

$ErrorActionPreference = "Stop"

# 设置环境变量
$env:V13_SIGNAL_V2 = "1"
$env:V13_SINK = "dual"
$env:V13_OUTPUT_DIR = "./runtime/backtest_verify_v2"
$env:PYTHONUTF8 = "1"
$env:RUN_ID = "backtest_verify_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# 创建输出目录
New-Item -ItemType Directory -Force -Path $env:V13_OUTPUT_DIR | Out-Null

Write-Host "========================================" -ForegroundColor Green
Write-Host "Signal v2 回测验证" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Run ID: $env:RUN_ID" -ForegroundColor Cyan
Write-Host "Output directory: $env:V13_OUTPUT_DIR" -ForegroundColor Cyan
Write-Host ""

# 检查数据目录是否存在
$dataDir = "./deploy/data/ofi_cvd/ready"
if (-not (Test-Path $dataDir)) {
    Write-Host "[ERROR] 数据目录不存在: $dataDir" -ForegroundColor Red
    Write-Host "请先运行数据采集（harvest）或使用已有数据" -ForegroundColor Yellow
    exit 1
}

# 查找可用的特征数据文件
Write-Host "[1/5] 查找特征数据..." -ForegroundColor Yellow
$featureFiles = Get-ChildItem -Path $dataDir -Filter "features-*.parquet" -Recurse | Select-Object -First 10
if ($featureFiles.Count -eq 0) {
    Write-Host "[ERROR] 未找到特征数据文件（features-*.parquet）" -ForegroundColor Red
    exit 1
}
Write-Host "找到 $($featureFiles.Count) 个特征文件" -ForegroundColor Cyan

# 运行回测验证脚本
Write-Host "`n[2/5] 运行回测验证..." -ForegroundColor Yellow
python scripts/backtest_verify_signal_v2.py `
    --data-dir $dataDir `
    --output-dir $env:V13_OUTPUT_DIR `
    --run-id $env:RUN_ID `
    --symbols BTCUSDT,ETHUSDT `
    --minutes 120

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] 回测验证失败" -ForegroundColor Red
    exit 1
}

Write-Host "`n[SUCCESS] 回测验证完成！" -ForegroundColor Green
Write-Host "查看详细报告: $env:V13_OUTPUT_DIR/report.json" -ForegroundColor Cyan

















