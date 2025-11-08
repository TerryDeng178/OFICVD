# TASK-07A P0/P1修复验证测试脚本（PowerShell）
# 运行3分钟冒烟测试，验证所有修复

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "TASK-07A P0/P1修复验证测试" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""

# 步骤1: 设置环境变量
Write-Host "[1] 设置环境变量" -ForegroundColor Yellow
$env:V13_REPLAY_MODE = "0"
$env:V13_SINK = "dual"
$env:REPORT_TZ = "Asia/Tokyo"
$env:RUN_ID = "p0p1_verification_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# 可选：启用时序库导出（如果Pushgateway运行）
$enableTimeseries = Read-Host "是否启用时序库导出？(y/n)"
if ($enableTimeseries -eq "y") {
    $env:TIMESERIES_ENABLED = "1"
    $env:TIMESERIES_TYPE = "prometheus"
    $env:TIMESERIES_URL = "http://localhost:9091"
    Write-Host "  时序库导出已启用: $env:TIMESERIES_TYPE -> $env:TIMESERIES_URL" -ForegroundColor Green
} else {
    Write-Host "  时序库导出未启用" -ForegroundColor Gray
}

Write-Host ""
Write-Host "环境变量配置:" -ForegroundColor Yellow
Write-Host "  V13_REPLAY_MODE = $env:V13_REPLAY_MODE"
Write-Host "  V13_SINK = $env:V13_SINK"
Write-Host "  REPORT_TZ = $env:REPORT_TZ"
Write-Host "  RUN_ID = $env:RUN_ID"
Write-Host ""

# 步骤2: 清理旧数据（可选）
$cleanup = Read-Host "是否清理旧数据？(y/n)"
if ($cleanup -eq "y") {
    Write-Host "[2] 清理旧数据" -ForegroundColor Yellow
    if (Test-Path "runtime") { Remove-Item -Recurse -Force "runtime" }
    if (Test-Path "logs") { Remove-Item -Recurse -Force "logs" }
    if (Test-Path "deploy\artifacts\ofi_cvd") { Remove-Item -Recurse -Force "deploy\artifacts\ofi_cvd" }
    Write-Host "  清理完成" -ForegroundColor Green
    Write-Host ""
}

# 步骤3: 运行3分钟测试
Write-Host "[3] 运行3分钟冒烟测试" -ForegroundColor Yellow
Write-Host ""

$testStartTime = Get-Date
Write-Host "测试开始时间: $($testStartTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Cyan
Write-Host ""

$cmd = @(
    "python", "-m", "orchestrator.run",
    "--config", "./config/defaults.yaml",
    "--enable", "harvest,signal,broker,report",
    "--sink", "dual",
    "--minutes", "3"
)

Write-Host "执行命令: $($cmd -join ' ')" -ForegroundColor Gray
Write-Host ""

try {
    & $cmd[0] $cmd[1..($cmd.Length-1)]
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "测试执行失败: $_" -ForegroundColor Red
    exit 1
}

$testEndTime = Get-Date
$duration = $testEndTime - $testStartTime

Write-Host ""
Write-Host "测试结束时间: $($testEndTime.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Cyan
Write-Host "测试耗时: $($duration.TotalSeconds)秒" -ForegroundColor Cyan
Write-Host ""

# 步骤4: 验证结果
Write-Host "[4] 验证修复效果" -ForegroundColor Yellow
Write-Host ""

# 4.1 检查SQLite关闭日志
Write-Host "4.1 检查SQLite关闭日志" -ForegroundColor Cyan
$logFiles = Get-ChildItem -Path "logs\signal" -Filter "*stderr.log" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($logFiles) {
    $logContent = Get-Content $logFiles.FullName -Tail 50 -Encoding UTF-8
    $closeLog = $logContent | Select-String "关闭完成"
    if ($closeLog) {
        Write-Host "  ✅ 找到SQLite关闭日志" -ForegroundColor Green
        Write-Host "  $closeLog" -ForegroundColor Gray
    } else {
        Write-Host "  ⚠️  未找到SQLite关闭日志" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ⚠️  未找到日志文件" -ForegroundColor Yellow
}

# 4.2 检查健康检查日志
Write-Host ""
Write-Host "4.2 检查健康检查日志" -ForegroundColor Cyan
$orchestratorLog = Get-ChildItem -Path "logs\orchestrator" -Filter "orchestrator.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($orchestratorLog) {
    $logContent = Get-Content $orchestratorLog.FullName -Tail 100 -Encoding UTF-8
    $healthLog = $logContent | Select-String "timeseries.health"
    if ($healthLog) {
        Write-Host "  ✅ 找到健康检查日志" -ForegroundColor Green
        $healthLog | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
    } else {
        Write-Host "  ⚠️  未找到健康检查日志（可能未启用时序库导出）" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ⚠️  未找到orchestrator日志文件" -ForegroundColor Yellow
}

# 4.3 检查run_manifest
Write-Host ""
Write-Host "4.3 检查run_manifest" -ForegroundColor Cyan
$manifestFiles = Get-ChildItem -Path "deploy\artifacts\ofi_cvd\run_logs" -Filter "run_manifest_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($manifestFiles) {
    $manifest = Get-Content $manifestFiles.FullName -Encoding UTF-8 | ConvertFrom-Json
    Write-Host "  ✅ 找到run_manifest: $($manifestFiles.Name)" -ForegroundColor Green
    Write-Host "  RUN_ID: $($manifest.run_id)" -ForegroundColor Gray
    Write-Host "  运行时长: $($manifest.duration_seconds)秒" -ForegroundColor Gray
    
    if ($manifest.timeseries_export) {
        Write-Host "  时序库导出统计:" -ForegroundColor Gray
        Write-Host "    export_count: $($manifest.timeseries_export.export_count)" -ForegroundColor Gray
        Write-Host "    error_count: $($manifest.timeseries_export.error_count)" -ForegroundColor Gray
    }
} else {
    Write-Host "  ⚠️  未找到run_manifest文件" -ForegroundColor Yellow
}

# 4.4 检查数据一致性（JSONL vs SQLite）
Write-Host ""
Write-Host "4.4 检查数据一致性（JSONL vs SQLite）" -ForegroundColor Cyan
Write-Host "  运行parity检查脚本验证字段独立性" -ForegroundColor Gray
Write-Host "  命令: python scripts/verify_sink_parity.py --run-id $env:RUN_ID" -ForegroundColor Gray

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "测试完成" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步:" -ForegroundColor Yellow
Write-Host "  1. 检查日志文件，确认SQLite关闭日志和健康检查日志" -ForegroundColor White
Write-Host "  2. 运行parity检查，验证MultiSink数据一致性" -ForegroundColor White
Write-Host "  3. 检查JSONL文件，验证尾批fsync（minute切换时文件完整）" -ForegroundColor White
Write-Host "  4. 如果配置了时序库，检查导出统计" -ForegroundColor White
Write-Host ""

if ($exitCode -eq 0) {
    Write-Host "测试退出码: 0 (成功)" -ForegroundColor Green
} else {
    Write-Host "测试退出码: $exitCode (失败)" -ForegroundColor Red
}

exit $exitCode

