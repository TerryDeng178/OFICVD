# 保存环境变量快照脚本
# 用途: 收集所有关键环境变量，与run_manifest一起归档

param(
    [string]$RunId = "",
    [string]$OutputDir = "deploy/artifacts/ofi_cvd"
)

$ErrorActionPreference = "Stop"

if (-not $RunId) {
    $RunId = $env:RUN_ID
    if (-not $RunId) {
        Write-Host "错误: 需要指定RUN_ID或设置环境变量RUN_ID" -ForegroundColor Red
        exit 1
    }
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# 收集环境变量
$env_snapshot = @{
    "timestamp" = $timestamp
    "run_id" = $RunId
    "V13_REPLAY_MODE" = $env:V13_REPLAY_MODE
    "V13_INPUT_MODE" = $env:V13_INPUT_MODE
    "V13_SINK" = $env:V13_SINK
    "SQLITE_BATCH_N" = $env:SQLITE_BATCH_N
    "SQLITE_FLUSH_MS" = $env:SQLITE_FLUSH_MS
    "FSYNC_EVERY_N" = $env:FSYNC_EVERY_N
    "TIMESERIES_ENABLED" = $env:TIMESERIES_ENABLED
    "TIMESERIES_TYPE" = $env:TIMESERIES_TYPE
    "TIMESERIES_URL" = $env:TIMESERIES_URL
    "INFLUX_URL" = $env:INFLUX_URL
    "INFLUX_ORG" = $env:INFLUX_ORG
    "INFLUX_BUCKET" = $env:INFLUX_BUCKET
    "INFLUX_TOKEN" = if ($env:INFLUX_TOKEN) { "已设置" } else { "未设置" }
    "RUN_ID" = $env:RUN_ID
    "REPORT_TZ" = $env:REPORT_TZ
}

# 确保输出目录存在
$outputPath = Join-Path $OutputDir "env_snapshots"
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

# 保存JSON文件
$jsonPath = Join-Path $outputPath "env_snapshot_${RunId}_${timestamp}.json"
$env_snapshot | ConvertTo-Json -Depth 10 | Out-File -FilePath $jsonPath -Encoding UTF8

Write-Host "环境变量快照已保存: $jsonPath" -ForegroundColor Green
Write-Host ""
Write-Host "快照内容:" -ForegroundColor Cyan
$env_snapshot | Format-List

