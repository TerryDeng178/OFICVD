# scripts/run_task07a.ps1
# TASK-07A: LIVE 60 分钟端到端实测（Soak Test）
# 修复后的完整测试命令

param(
    [int]$Minutes = 60,
    [string]$Sink = "jsonl",
    [string]$TimeseriesType = "prometheus",
    [string]$TimeseriesUrl = "http://localhost:9091",
    [switch]$SkipPreflight
)

Write-Host "=== TASK-07A: LIVE 60 分钟端到端实测（Soak Test）===" -ForegroundColor Green
Write-Host ""

# 设置环境变量
$env:TIMESERIES_TYPE = $TimeseriesType
$env:TIMESERIES_URL = $TimeseriesUrl
$env:REPORT_TZ = "Asia/Tokyo"
$env:V13_REPLAY_MODE = "0"  # LIVE 模式

Write-Host "环境变量:" -ForegroundColor Yellow
Write-Host "  TIMESERIES_TYPE = $env:TIMESERIES_TYPE"
Write-Host "  TIMESERIES_URL = $env:TIMESERIES_URL"
Write-Host "  REPORT_TZ = $env:REPORT_TZ"
Write-Host "  V13_REPLAY_MODE = $env:V13_REPLAY_MODE (LIVE 模式)"
Write-Host ""

# 时序库预检（可选）
if (-not $SkipPreflight) {
    Write-Host "执行时序库可达性预检..." -ForegroundColor Cyan
    try {
        if ($TimeseriesType -eq "prometheus") {
            $response = Invoke-WebRequest -Uri $TimeseriesUrl -Method Get -TimeoutSec 5 -ErrorAction Stop
            Write-Host "  [OK] Prometheus Pushgateway 可达" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [WARNING] 时序库预检失败: $_" -ForegroundColor Yellow
        Write-Host "  将继续运行，但时序库导出可能失败" -ForegroundColor Yellow
    }
    Write-Host ""
}

Write-Host "启动 Orchestrator..." -ForegroundColor Cyan
Write-Host "  运行时长: $Minutes 分钟" -ForegroundColor Yellow
Write-Host "  Sink: $Sink" -ForegroundColor Yellow
Write-Host "  模式: LIVE (WebSocket 实时数据)" -ForegroundColor Yellow
Write-Host ""
Write-Host "重要提示:" -ForegroundColor Red
Write-Host "  - 健康检查已修复：现在查找 *.parquet 文件" -ForegroundColor Yellow
Write-Host "  - LIVE 模式要求文件在最近120秒内更新" -ForegroundColor Yellow
Write-Host "  - 如果使用 preview 数据，健康检查会失败（预期行为）" -ForegroundColor Yellow
Write-Host "  - 按 Ctrl+C 可提前终止（将执行优雅关闭）" -ForegroundColor Yellow
Write-Host ""

# 记录启动时间
$startTime = Get-Date
Write-Host "启动时间: $startTime" -ForegroundColor Gray
Write-Host ""

# 运行 Orchestrator
try {
    python -m orchestrator.run `
        --config ./config/defaults.yaml `
        --enable harvest,signal,broker,report `
        --sink $Sink `
        --minutes $Minutes
    
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host ""
    Write-Host "[ERROR] Orchestrator 运行失败: $_" -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "=== Soak Test 完成 ===" -ForegroundColor Green
Write-Host "  结束时间: $endTime" -ForegroundColor Gray
Write-Host "  运行时长: $($duration.TotalMinutes.ToString('F2')) 分钟" -ForegroundColor Gray
Write-Host "  退出码: $exitCode" -ForegroundColor Gray
Write-Host ""
Write-Host "请检查以下产出物:" -ForegroundColor Cyan
Write-Host "  - artifacts/run_logs/run_manifest_*.json" -ForegroundColor Gray
Write-Host "  - artifacts/source_manifest.json" -ForegroundColor Gray
if ($Sink -eq "dual") {
    Write-Host "  - artifacts/parity_diff.json" -ForegroundColor Gray
}
Write-Host "  - logs/report/summary_*.json|md" -ForegroundColor Gray
Write-Host "  - logs/orchestrator/orchestrator.log" -ForegroundColor Gray
Write-Host "  - deploy/data/ofi_cvd/raw/**/*.parquet (harvest 输出)" -ForegroundColor Gray

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[WARNING] Orchestrator 非正常退出，请检查日志" -ForegroundColor Yellow
    exit $exitCode
}

