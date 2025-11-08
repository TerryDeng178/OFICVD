# TASK-07B 3分钟双Sink冒烟测试脚本
# 使用短跑调参确保数据落盘，然后运行等价性测试

param(
    [int]$Minutes = 3
)

Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "TASK-07B 3分钟双Sink冒烟测试" -ForegroundColor Cyan
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host ""

# 步骤1: 设置环境变量（短跑调参）
Write-Host "步骤1: 设置环境变量（短跑调参）" -ForegroundColor Yellow
Write-Host ""
$env:V13_REPLAY_MODE = "1"
$env:V13_INPUT_MODE = "preview"
$env:TIMESERIES_ENABLED = "0"
# 短跑场景调参，确保批量队列立即刷新
$env:SQLITE_BATCH_N = "1"
$env:SQLITE_FLUSH_MS = "0"
$env:FSYNC_EVERY_N = "100"

Write-Host "  环境变量配置:" -ForegroundColor Cyan
Write-Host "    V13_REPLAY_MODE = $env:V13_REPLAY_MODE" -ForegroundColor Gray
Write-Host "    V13_INPUT_MODE = $env:V13_INPUT_MODE" -ForegroundColor Gray
Write-Host "    SQLITE_BATCH_N = $env:SQLITE_BATCH_N (短跑调参：立即刷新)" -ForegroundColor Green
Write-Host "    SQLITE_FLUSH_MS = $env:SQLITE_FLUSH_MS (短跑调参：立即刷新)" -ForegroundColor Green
Write-Host "    FSYNC_EVERY_N = $env:FSYNC_EVERY_N" -ForegroundColor Gray
Write-Host ""

# 步骤2: 运行双Sink测试
Write-Host "步骤2: 运行$Minutes分钟双Sink测试" -ForegroundColor Yellow
Write-Host ""
$startTime = Get-Date
Write-Host "测试开始时间: $startTime" -ForegroundColor Green
Write-Host ""

$logFile = "logs\task07b_smoke_3min_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
python -m orchestrator.run `
    --config ./config/defaults.yaml `
    --enable harvest,signal,broker,report `
    --sink dual `
    --minutes $Minutes 2>&1 | Tee-Object -FilePath $logFile

$endTime = Get-Date
$duration = $endTime - $startTime
Write-Host ""
Write-Host "测试结束时间: $endTime" -ForegroundColor Green
Write-Host "测试时长: $($duration.TotalMinutes.ToString('F1')) 分钟" -ForegroundColor Green
Write-Host ""

# 步骤3: 运行等价性测试
Write-Host "步骤3: 运行双Sink等价性测试" -ForegroundColor Yellow
Write-Host ""

$parityOutput = "deploy\artifacts\ofi_cvd\parity_diff_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
New-Item -ItemType Directory -Force -Path (Split-Path $parityOutput) | Out-Null

python scripts/test_dual_sink_parity.py `
    --jsonl-dir ./runtime/ready/signal `
    --sqlite-db ./runtime/signals.db `
    --output $parityOutput `
    --threshold 0.2

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[x] 等价性测试完成" -ForegroundColor Green
    Write-Host "    结果文件: $parityOutput" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "[!] 等价性测试失败 (退出码: $LASTEXITCODE)" -ForegroundColor Red
}

# 步骤4: 检查结果
Write-Host ""
Write-Host "步骤4: 检查测试结果" -ForegroundColor Yellow
Write-Host ""

if (Test-Path $parityOutput) {
    Write-Host "[x] 等价性测试结果文件存在" -ForegroundColor Green
    $parityData = Get-Content $parityOutput | ConvertFrom-Json
    
    Write-Host ""
    Write-Host "差异统计:" -ForegroundColor Cyan
    Write-Host "  总量差异: $($parityData.differences.total_diff_pct)%" -ForegroundColor $(if ($parityData.differences.total_diff_pct -lt 0.2) { "Green" } else { "Red" })
    Write-Host "  确认量差异: $($parityData.differences.confirm_diff_pct)%" -ForegroundColor $(if ($parityData.differences.confirm_diff_pct -lt 0.2) { "Green" } else { "Red" })
    Write-Host "  强信号占比差异: $($parityData.differences.strong_ratio_diff_pct)%" -ForegroundColor $(if ($parityData.differences.strong_ratio_diff_pct -lt 0.2) { "Green" } else { "Red" })
    
    Write-Host ""
    Write-Host "窗口对齐:" -ForegroundColor Cyan
    Write-Host "  状态: $($parityData.window_alignment.status)" -ForegroundColor $(if ($parityData.window_alignment.status -eq "aligned") { "Green" } else { "Yellow" })
    Write-Host "  交集分钟数: $($parityData.window_alignment.overlap_minutes)" -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "数据统计:" -ForegroundColor Cyan
    Write-Host "  JSONL - 总量: $($parityData.jsonl_stats.total), 确认: $($parityData.jsonl_stats.confirmed), 强信号: $($parityData.jsonl_stats.strong)" -ForegroundColor Gray
    Write-Host "  SQLite - 总量: $($parityData.sqlite_stats.total), 确认: $($parityData.sqlite_stats.confirmed), 强信号: $($parityData.sqlite_stats.strong)" -ForegroundColor Gray
} else {
    Write-Host "[!] 等价性测试结果文件不存在" -ForegroundColor Red
}

Write-Host ""
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "测试完成" -ForegroundColor Cyan
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "日志文件: $logFile" -ForegroundColor Gray
if (Test-Path $parityOutput) {
    Write-Host "等价性测试结果: $parityOutput" -ForegroundColor Gray
}
Write-Host ""

