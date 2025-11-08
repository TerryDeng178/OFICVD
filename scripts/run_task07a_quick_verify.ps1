# TASK-07A 3分钟快速验证脚本（使用短跑调参）
# 按照修复方案，使用SQLITE_BATCH_N=1和SQLITE_FLUSH_MS=0确保数据落盘

param(
    [int]$Minutes = 3
)

Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "TASK-07A 3分钟快速验证（短跑调参模式）" -ForegroundColor Cyan
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host ""

# 步骤1: 设置环境变量（短跑调参）
Write-Host "步骤1: 设置环境变量（短跑调参）" -ForegroundColor Yellow
Write-Host ""
$env:V13_REPLAY_MODE = "1"
$env:V13_INPUT_MODE = "preview"
$env:TIMESERIES_ENABLED = "0"
# TASK-07A: 短跑场景调参，确保批量队列立即刷新
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

# 步骤2: 运行测试
Write-Host "步骤2: 运行$Minutes分钟双Sink测试" -ForegroundColor Yellow
Write-Host ""
$startTime = Get-Date
Write-Host "测试开始时间: $startTime" -ForegroundColor Green
Write-Host ""

$logFile = "logs\task07a_quick_verify_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
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

# 步骤3: 查找最新的manifest
Write-Host "步骤3: 查找最新的manifest" -ForegroundColor Yellow
Write-Host ""
$manifestDir = "deploy\artifacts\ofi_cvd\run_logs"
$latestManifest = Get-ChildItem -Path $manifestDir -Filter "run_manifest_*.json" | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -First 1

if (-not $latestManifest) {
    Write-Host "[ERROR] 未找到manifest文件" -ForegroundColor Red
    exit 1
}

Write-Host "最新manifest: $($latestManifest.Name)" -ForegroundColor Cyan
Write-Host "  路径: $($latestManifest.FullName)" -ForegroundColor Gray
Write-Host ""

# 步骤4: 检查SQLite数据
Write-Host "步骤4: 检查SQLite数据" -ForegroundColor Yellow
Write-Host ""
python scripts/check_sqlite_test_data.py
Write-Host ""

# 步骤5: 运行等价性测试
Write-Host "步骤5: 运行等价性测试" -ForegroundColor Yellow
Write-Host ""
$parityOutput = "deploy\artifacts\ofi_cvd\parity_diff.json"
python scripts/test_dual_sink_parity.py `
    --jsonl-dir ./runtime/ready/signal `
    --sqlite-db ./runtime/signals.db `
    --output $parityOutput `
    --manifest $latestManifest.FullName

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[SUCCESS] 等价性测试完成" -ForegroundColor Green
    Write-Host "  结果文件: $parityOutput" -ForegroundColor Gray
    
    # 检查结果
    if (Test-Path $parityOutput) {
        $parityResult = Get-Content $parityOutput -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ""
        Write-Host "等价性测试结果:" -ForegroundColor Cyan
        Write-Host "  交集窗口数: $($parityResult.overlap_windows)" -ForegroundColor $(if ($parityResult.overlap_windows -gt 0) { "Green" } else { "Red" })
        if ($parityResult.overlap_windows -gt 0) {
            Write-Host "  total差异: $($parityResult.diff_pct.total.ToString('F2'))%" -ForegroundColor $(if ($parityResult.diff_pct.total -lt 0.5) { "Green" } else { "Yellow" })
            Write-Host "  strong_ratio差异: $($parityResult.diff_pct.strong_ratio.ToString('F2'))%" -ForegroundColor $(if ($parityResult.diff_pct.strong_ratio -lt 10) { "Green" } else { "Yellow" })
        }
    }
} else {
    Write-Host ""
    Write-Host "[WARNING] 等价性测试失败，请检查结果" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "验证完成" -ForegroundColor Cyan
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "DoD检查:" -ForegroundColor Yellow
Write-Host "  [ ] SQLite非空（测试时间范围内有数据）" -ForegroundColor White
Write-Host "  [ ] 有交集窗口（交集窗口数 > 0）" -ForegroundColor White
Write-Host "  [ ] 差异 < 0.5%（total）和 < 10%（strong_ratio）" -ForegroundColor White

