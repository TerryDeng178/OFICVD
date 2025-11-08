# scripts/soak_test.ps1
# TASK-07A: LIVE 60 分钟端到端实测（Soak Test）

param(
    [string]$Config = "./config/defaults.yaml",
    [int]$Minutes = 60,
    [string]$Sink = "jsonl",
    [string]$TimeseriesType = "prometheus",
    [string]$TimeseriesUrl = "http://localhost:9091"
)

# 设置环境变量
$env:TIMESERIES_TYPE = $TimeseriesType
$env:TIMESERIES_URL = $TimeseriesUrl
$env:REPORT_TZ = "Asia/Tokyo"
$env:V13_REPLAY_MODE = "0"

Write-Host "=== TASK-07A: LIVE 60 分钟 Soak Test ===" -ForegroundColor Green
Write-Host ""
Write-Host "配置参数:" -ForegroundColor Yellow
Write-Host "  配置文件: $Config" -ForegroundColor Gray
Write-Host "  Sink: $Sink" -ForegroundColor Gray
Write-Host "  运行时长: $Minutes 分钟" -ForegroundColor Gray
Write-Host "  时序库类型: $TimeseriesType" -ForegroundColor Gray
Write-Host "  时序库地址: $TimeseriesUrl" -ForegroundColor Gray
Write-Host "  时区: $env:REPORT_TZ" -ForegroundColor Gray
Write-Host "  模式: LIVE (V13_REPLAY_MODE=0)" -ForegroundColor Gray
Write-Host ""

# 时序库可达性预检
Write-Host "执行时序库可达性预检..." -ForegroundColor Cyan
try {
    if ($TimeseriesType -eq "prometheus") {
        $response = Invoke-WebRequest -Uri $TimeseriesUrl -Method Get -TimeoutSec 5 -ErrorAction Stop
        Write-Host "  [OK] Prometheus Pushgateway 可达 ($TimeseriesUrl)" -ForegroundColor Green
    } elseif ($TimeseriesType -eq "influxdb") {
        # InfluxDB 健康检查端点通常是 /health
        $healthUrl = if ($TimeseriesUrl.EndsWith("/")) { "$TimeseriesUrl" } else { "$TimeseriesUrl/" }
        $healthUrl = $healthUrl + "health"
        $response = Invoke-WebRequest -Uri $healthUrl -Method Get -TimeoutSec 5 -ErrorAction Stop
        Write-Host "  [OK] InfluxDB 可达 ($TimeseriesUrl)" -ForegroundColor Green
    }
} catch {
    Write-Host "  [WARNING] 时序库预检失败: $_" -ForegroundColor Yellow
    Write-Host "  将继续运行，但时序库导出可能失败" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "启动 Orchestrator..." -ForegroundColor Cyan
Write-Host "  注意: 这将运行 $Minutes 分钟，请确保有足够时间" -ForegroundColor Yellow
Write-Host "  按 Ctrl+C 可提前终止（将执行优雅关闭）" -ForegroundColor Yellow
Write-Host ""

# 记录启动时间
$startTime = Get-Date
Write-Host "启动时间: $startTime" -ForegroundColor Gray
Write-Host ""

# 运行 Orchestrator
try {
    python -m orchestrator.run `
        --config $Config `
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
Write-Host "  - artifacts/parity_diff.json (如果使用双 Sink)" -ForegroundColor Gray
Write-Host "  - logs/report/summary_*.json|md" -ForegroundColor Gray
Write-Host "  - logs/orchestrator/orchestrator.log" -ForegroundColor Gray

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[WARNING] Orchestrator 非正常退出，请检查日志" -ForegroundColor Yellow
    exit $exitCode
}

