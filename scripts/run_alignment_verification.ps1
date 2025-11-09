# -*- coding: utf-8 -*-
# Complete Alignment Verification Script
# Run backtest with historical data and verify alignment

param(
    [string]$Date = "2025-11-08",
    [int]$Minutes = 60,
    [string]$Symbols = "BTCUSDT",
    [string]$InputDir = "deploy\data\ofi_cvd"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Complete Alignment Verification" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Run backtest with historical data
Write-Host "`nStep 1: Running backtest with historical data..." -ForegroundColor Yellow
Write-Host "  Date: $Date" -ForegroundColor Gray
Write-Host "  Minutes: $Minutes" -ForegroundColor Gray
Write-Host "  Symbols: $Symbols" -ForegroundColor Gray

$runId = "alignment_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$outputDir = "runtime\backtest\$runId"

Write-Host "  Run ID: $runId" -ForegroundColor Gray
Write-Host "  Output: $outputDir" -ForegroundColor Gray

python scripts\replay_harness.py `
  --input $InputDir `
  --kinds features `
  --date $Date `
  --minutes $Minutes `
  --symbols $Symbols `
  --output $outputDir

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] Backtest failed" -ForegroundColor Red
    exit 1
}

Write-Host "  [OK] Backtest completed" -ForegroundColor Green

# Step 2: Check backtest signals
Write-Host "`nStep 2: Checking backtest signals..." -ForegroundColor Yellow
$signalDir = "$outputDir\signals\ready\signal"
if (-not (Test-Path $signalDir)) {
    Write-Host "  [FAIL] Signal directory not found: $signalDir" -ForegroundColor Red
    exit 1
}

$signalFiles = Get-ChildItem $signalDir -Recurse -Filter "*.jsonl"
if ($signalFiles.Count -eq 0) {
    Write-Host "  [FAIL] No signal files found" -ForegroundColor Red
    exit 1
}

Write-Host "  [OK] Found $($signalFiles.Count) signal files" -ForegroundColor Green

# Get time range from backtest signals
$firstFile = $signalFiles[0]
$firstLine = Get-Content $firstFile.FullName -First 1 -Encoding UTF8 | ConvertFrom-Json
$lastLine = Get-Content $firstFile.FullName -Tail 1 -Encoding UTF8 | ConvertFrom-Json
$startMs = $firstLine.ts_ms
$endMs = $lastLine.ts_ms

$startTime = [DateTimeOffset]::FromUnixTimeMilliseconds($startMs).ToString("yyyy-MM-dd HH:mm:ss")
$endTime = [DateTimeOffset]::FromUnixTimeMilliseconds($endMs).ToString("yyyy-MM-dd HH:mm:ss")

Write-Host "  Time range: $startTime - $endTime" -ForegroundColor Gray
Write-Host "  Timestamps: $startMs - $endMs" -ForegroundColor Gray

# Step 3: Run alignment test
Write-Host "`nStep 3: Running alignment test..." -ForegroundColor Yellow
$alignmentOutputDir = "runtime\backtest\alignment_final_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

python scripts\test_backtest_alignment.py `
  --backtest-signals $signalDir `
  --production-signals "runtime\ready\signal" `
  --start-ms $startMs `
  --end-ms $endMs `
  --output $alignmentOutputDir

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] Alignment test failed" -ForegroundColor Red
    exit 1
}

Write-Host "  [OK] Alignment test completed" -ForegroundColor Green

# Step 4: Check results
Write-Host "`nStep 4: Checking alignment results..." -ForegroundColor Yellow
$resultFile = "$alignmentOutputDir\alignment_comparison.json"
if (-not (Test-Path $resultFile)) {
    Write-Host "  [FAIL] Result file not found: $resultFile" -ForegroundColor Red
    exit 1
}

$result = Get-Content $resultFile -Encoding UTF8 | ConvertFrom-Json

Write-Host "`n=== Alignment Results ===" -ForegroundColor Cyan
Write-Host "`nSignal Count:" -ForegroundColor Yellow
Write-Host "  Backtest: $($result.backtest_total)" -ForegroundColor Gray
Write-Host "  Production: $($result.production_total)" -ForegroundColor Gray
Write-Host "  Difference: $([math]::Round($result.count_diff_pct, 2))% (threshold: 5%)" -ForegroundColor $(if ($result.count_diff_passed) { "Green" } else { "Red" })
Write-Host "  Status: $(if ($result.count_diff_passed) { '[PASS]' } else { '[FAIL]' })" -ForegroundColor $(if ($result.count_diff_passed) { "Green" } else { "Red" })

Write-Host "`nStrongRatio:" -ForegroundColor Yellow
Write-Host "  Backtest: $([math]::Round($result.backtest_strong_ratio, 2))%" -ForegroundColor Gray
Write-Host "  Production: $([math]::Round($result.production_strong_ratio, 2))%" -ForegroundColor Gray
Write-Host "  Difference: $([math]::Round($result.strong_ratio_diff, 2))% (threshold: 10%)" -ForegroundColor $(if ($result.strong_ratio_diff_passed) { "Green" } else { "Red" })
Write-Host "  Status: $(if ($result.strong_ratio_diff_passed) { '[PASS]' } else { '[FAIL]' })" -ForegroundColor $(if ($result.strong_ratio_diff_passed) { "Green" } else { "Red" })

Write-Host "`nWindow Alignment:" -ForegroundColor Yellow
$wa = $result.window_alignment
Write-Host "  Backtest minutes: $($wa.backtest_minutes)" -ForegroundColor Gray
Write-Host "  Production minutes: $($wa.production_minutes)" -ForegroundColor Gray
Write-Host "  Overlap minutes: $($wa.overlap_minutes)" -ForegroundColor Gray
Write-Host "  Alignment: $([math]::Round($wa.alignment_pct, 2))% (threshold: 80%)" -ForegroundColor $(if ($wa.alignment_pct -ge 80) { "Green" } else { "Yellow" })

if ($result.diff_reasons -and $result.diff_reasons.Count -gt 0) {
    Write-Host "`nDifference Reasons:" -ForegroundColor Yellow
    foreach ($reason in $result.diff_reasons) {
        Write-Host "  - $reason" -ForegroundColor Gray
    }
}

# Final verdict
$allPassed = $result.count_diff_passed -and $result.strong_ratio_diff_passed -and $wa.alignment_pct -ge 80

Write-Host "`n=== Final Verdict ===" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "  [PASS] All alignment checks passed!" -ForegroundColor Green
    Write-Host "  - Signal count difference: PASS" -ForegroundColor Green
    Write-Host "  - StrongRatio difference: PASS" -ForegroundColor Green
    Write-Host "  - Window alignment: PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  [FAIL] Some alignment checks failed" -ForegroundColor Red
    if (-not $result.count_diff_passed) {
        Write-Host "  - Signal count difference: FAIL" -ForegroundColor Red
    }
    if (-not $result.strong_ratio_diff_passed) {
        Write-Host "  - StrongRatio difference: FAIL" -ForegroundColor Red
    }
    if ($wa.alignment_pct -lt 80) {
        Write-Host "  - Window alignment: FAIL ($([math]::Round($wa.alignment_pct, 2))% < 80%)" -ForegroundColor Red
    }
    exit 1
}

