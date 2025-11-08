# P0.5 verification script
# Purpose: Execute timeseries export verification and 60-minute soak test

param(
    [string]$TestType = "timeseries",
    [int]$Minutes = 10,
    [string]$TimeseriesType = "prometheus",
    [string]$TimeseriesUrl = ""
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "P0.5 Verification Script" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Set base environment variables
$env:V13_REPLAY_MODE = "0"
$env:V13_INPUT_MODE = "preview"
$env:V13_SINK = "dual"
$env:REPORT_TZ = "Asia/Tokyo"

# Generate RUN_ID
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$env:RUN_ID = "p0p5_${TestType}_${timestamp}"

Write-Host "Test Type: $TestType" -ForegroundColor Yellow
Write-Host "Duration: $Minutes minutes" -ForegroundColor Yellow
Write-Host "RUN_ID: $env:RUN_ID" -ForegroundColor Yellow
Write-Host ""

if ($TestType -eq "timeseries") {
    Write-Host "Configuring timeseries export..." -ForegroundColor Green
    
    if (-not $TimeseriesUrl) {
        Write-Host "Error: TIMESERIES_URL is required for timeseries export test" -ForegroundColor Red
        Write-Host "Usage: .\run_p0p5_verification.ps1 -TestType timeseries -TimeseriesUrl http://localhost:9091" -ForegroundColor Yellow
        exit 1
    }
    
    $env:TIMESERIES_ENABLED = "1"
    $env:TIMESERIES_TYPE = $TimeseriesType
    $env:TIMESERIES_URL = $TimeseriesUrl
    
    if ($TimeseriesType -eq "influxdb") {
        $env:INFLUX_URL = $TimeseriesUrl
        $env:INFLUX_ORG = Read-Host "Enter INFLUX_ORG"
        $env:INFLUX_BUCKET = Read-Host "Enter INFLUX_BUCKET"
        $secureToken = Read-Host "Enter INFLUX_TOKEN" -AsSecureString
        $env:INFLUX_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken))
    }
    
    Write-Host "Timeseries Configuration:" -ForegroundColor Cyan
    Write-Host "  TIMESERIES_ENABLED: $env:TIMESERIES_ENABLED"
    Write-Host "  TIMESERIES_TYPE: $env:TIMESERIES_TYPE"
    Write-Host "  TIMESERIES_URL: $env:TIMESERIES_URL"
    Write-Host ""
}

Write-Host "Starting test..." -ForegroundColor Green
Write-Host ""

# Run Orchestrator
python -m orchestrator.run `
    --config ./config/defaults.yaml `
    --enable harvest,signal,broker,report `
    --sink dual `
    --minutes $Minutes

if ($LASTEXITCODE -ne 0) {
    Write-Host "Test failed with exit code: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Test completed, verifying results..." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Verify data consistency
Write-Host "Verifying data consistency..." -ForegroundColor Yellow
python scripts/verify_sink_parity.py --run-id $env:RUN_ID

Write-Host ""
Write-Host "Checking run_manifest..." -ForegroundColor Yellow
$manifestPath = "deploy/artifacts/ofi_cvd/run_logs/run_manifest_$($env:RUN_ID).json"
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath | ConvertFrom-Json
    Write-Host "  Duration: $($manifest.duration_s) seconds"
    Write-Host "  Timeseries Export: export_count=$($manifest.timeseries_export.export_count), error_count=$($manifest.timeseries_export.error_count)"
    
    if ($TestType -eq "timeseries") {
        if ($manifest.timeseries_export.export_count -gt 0 -and $manifest.timeseries_export.error_count -eq 0) {
            Write-Host "  [OK] Timeseries export verification passed" -ForegroundColor Green
        } else {
            Write-Host "  [FAIL] Timeseries export verification failed" -ForegroundColor Red
        }
    }
} else {
    Write-Host "  [WARN] run_manifest file not found" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Verification completed" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
