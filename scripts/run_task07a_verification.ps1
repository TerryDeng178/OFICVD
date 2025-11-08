# TASK-07A 修复验证脚本（PowerShell版本）
# 执行完整的验证流程

param(
    [int]$Minutes = 3,
    [switch]$SkipTest = $false
)

Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "TASK-07A 修复验证流程" -ForegroundColor Cyan
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host ""

# 步骤1: 验证修复点
Write-Host "步骤1: 验证修复点" -ForegroundColor Yellow
Write-Host ""
python scripts/verify_fix_complete.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 修复点验证失败，请先修复问题" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 步骤2: 设置环境变量（调优参数）
Write-Host "步骤2: 设置环境变量（调优参数）" -ForegroundColor Yellow
Write-Host ""
$env:FSYNC_EVERY_N = "100"
$env:SQLITE_BATCH_N = "1000"
$env:SQLITE_FLUSH_MS = "800"
Write-Host "  FSYNC_EVERY_N = $env:FSYNC_EVERY_N" -ForegroundColor Gray
Write-Host "  SQLITE_BATCH_N = $env:SQLITE_BATCH_N" -ForegroundColor Gray
Write-Host "  SQLITE_FLUSH_MS = $env:SQLITE_FLUSH_MS" -ForegroundColor Gray
Write-Host ""

if (-not $SkipTest) {
    # 步骤3: 运行测试
    Write-Host "步骤3: 运行$Minutes分钟双Sink测试" -ForegroundColor Yellow
    Write-Host ""
    $env:V13_REPLAY_MODE = "1"
    $env:V13_INPUT_MODE = "preview"
    $env:TIMESERIES_ENABLED = "0"
    
    $startTime = Get-Date
    Write-Host "测试开始时间: $startTime" -ForegroundColor Green
    Write-Host ""
    
    python -m orchestrator.run `
        --config ./config/defaults.yaml `
        --enable harvest,signal,broker,report `
        --sink dual `
        --minutes $Minutes
    
    $endTime = Get-Date
    $duration = $endTime - $startTime
    Write-Host ""
    Write-Host "测试结束时间: $endTime" -ForegroundColor Green
    Write-Host "测试时长: $($duration.TotalMinutes.ToString('F1')) 分钟" -ForegroundColor Green
    Write-Host ""
    
    # 步骤4: 查找最新的manifest
    Write-Host "步骤4: 查找最新的manifest" -ForegroundColor Yellow
    Write-Host ""
    $manifestDir = "deploy\artifacts\ofi_cvd\run_logs"
    $latestManifest = Get-ChildItem -Path $manifestDir -Filter "run_manifest_*.json" | 
        Sort-Object LastWriteTime -Descending | 
        Select-Object -First 1
    
    if ($latestManifest) {
        Write-Host "最新manifest: $($latestManifest.Name)" -ForegroundColor Cyan
        Write-Host "  路径: $($latestManifest.FullName)" -ForegroundColor Gray
        Write-Host ""
        
        # 步骤5: 运行DoD检查
        Write-Host "步骤5: 运行DoD检查" -ForegroundColor Yellow
        Write-Host ""
        python scripts/verify_fix_complete.py $latestManifest.FullName
        Write-Host ""
        
        # 步骤6: 运行等价性测试
        Write-Host "步骤6: 运行等价性测试" -ForegroundColor Yellow
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
        } else {
            Write-Host ""
            Write-Host "[WARNING] 等价性测试失败，请检查结果" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[WARNING] 未找到manifest文件" -ForegroundColor Yellow
    }
} else {
    Write-Host "[SKIP] 跳过测试执行（--SkipTest）" -ForegroundColor Gray
}

Write-Host ""
Write-Host "==================================================================================" -ForegroundColor Cyan
Write-Host "验证流程完成" -ForegroundColor Cyan
Write-Host "==================================================================================" -ForegroundColor Cyan

