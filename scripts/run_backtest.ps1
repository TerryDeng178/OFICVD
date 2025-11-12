# TASK-B2: 独立回测运行脚本 (PowerShell版本)
# 用法：
#   模式A（全量重算）：.\run_backtest.ps1 A .\data\features .\configs\backtest.yaml
#   模式B（信号复现）：.\run_backtest.ps1 B jsonl://.\runtime\signals .\configs\backtest.yaml

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("A", "B")]
    [string]$Mode,

    [Parameter(Mandatory=$true)]
    [string]$InputSrc,

    [Parameter(Mandatory=$true)]
    [string]$ConfigFile,

    [string]$Symbols = "BTCUSDT",
    [string]$StartTime = "2025-11-12T00:00:00Z",
    [string]$EndTime = "2025-11-13T00:00:00Z",
    [int]$Seed = 42,
    [string]$Timezone = "Asia/Tokyo"
)

# 生成运行ID
$RUN_ID = "bt_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")

# 设置输入参数
if ($Mode -eq "A") {
    $FeaturesDir = $InputSrc
    $SignalsSrc = ""
} else {
    $FeaturesDir = ""
    $SignalsSrc = $InputSrc
}

Write-Host "=== TASK-B2: Independent Backtest Runner ===" -ForegroundColor Cyan
Write-Host "Run ID: $RUN_ID"
Write-Host "Mode: $Mode"
if ($Mode -eq "A") {
    Write-Host "Features dir: $FeaturesDir"
} else {
    Write-Host "Signals src: $SignalsSrc"
}
Write-Host "Config: $ConfigFile"
Write-Host "Symbols: $Symbols"
Write-Host "Time range: $StartTime to $EndTime"
Write-Host "Seed: $Seed"
Write-Host "Timezone: $Timezone"
Write-Host ""

# 构建命令
$cmd = "python -m backtest.app"
$cmd += " --mode $Mode"
$cmd += " --config `"$ConfigFile`""
$cmd += " --run-id $RUN_ID"
$cmd += " --symbols $Symbols"
$cmd += " --start $StartTime"
$cmd += " --end $EndTime"
$cmd += " --seed $Seed"
$cmd += " --tz $Timezone"

if ($Mode -eq "A") {
    $cmd += " --features-dir `"$FeaturesDir`""
} else {
    $cmd += " --signals-src `"$SignalsSrc`""
}

# 执行回测
Write-Host "Executing: $cmd" -ForegroundColor Yellow
Write-Host ""

# 执行命令
Invoke-Expression $cmd

# 输出结果路径
$outputDir = "./backtest_out/$RUN_ID"
Write-Host ""
Write-Host "=== Backtest completed ===" -ForegroundColor Green
Write-Host "Output directory: $outputDir"
Write-Host ""

# 检查输出文件
if (Test-Path $outputDir) {
    Write-Host "Generated files:"
    Get-ChildItem $outputDir | ForEach-Object {
        Write-Host "  $($_.Name) ($("{0:N0}" -f $_.Length) bytes)"
    }
} else {
    Write-Host "Warning: Output directory not found" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done: $RUN_ID" -ForegroundColor Green
