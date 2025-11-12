# T2 Testnet Execution Script (PowerShell)
# TASK-A4: Run 30-60 minutes testnet, verify:
#   - Execution chain integrity and health probes
#   - Compare confirm rate/PnL distribution against backtest baseline
#   - Alert on threshold breaches

# Set UTF-8 encoding for PowerShell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

# Configuration parameters
$SYMBOLS = "BTCUSDT,ETHUSDT"
$MINUTES = 45  # 30-60 minutes
$RUN_ID = "t2_testnet_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$BASELINE_DIR = "./runtime/t1_backtest_signal_v2"  # T1 backtest baseline directory

# Set environment variables
$env:V13_SIGNAL_V2 = "1"
$env:V13_SINK = "dual"
$env:V13_OUTPUT_DIR = "./runtime/t2_testnet_signal_v2"
$env:PYTHONUTF8 = "1"
$env:RUN_ID = $RUN_ID

# Set feature version and rules version (for config_hash)
$env:CORE_FEATURES_VER = "ofi/cvd v3"
$env:CORE_RULES_VER = "core v1"

# Create output directory
$OUTPUT_DIR = $env:V13_OUTPUT_DIR
New-Item -ItemType Directory -Force -Path $OUTPUT_DIR | Out-Null

Write-Host "========================================" -ForegroundColor Green
Write-Host "T2 Testnet Execution - Signal v2" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Run ID: $RUN_ID" -ForegroundColor Cyan
Write-Host "Symbols: $SYMBOLS" -ForegroundColor Cyan
Write-Host "Minutes: $MINUTES" -ForegroundColor Cyan
Write-Host "Output directory: $OUTPUT_DIR" -ForegroundColor Cyan
Write-Host "Baseline directory: $BASELINE_DIR" -ForegroundColor Cyan
Write-Host ""

# Check baseline directory
if (-not (Test-Path $BASELINE_DIR)) {
    Write-Host "[WARN] Baseline directory not found: $BASELINE_DIR" -ForegroundColor Yellow
    Write-Host "[WARN] Will skip baseline comparison" -ForegroundColor Yellow
    $BASELINE_DIR = $null
}

# Step 1: Run orchestrator in testnet mode
Write-Host "[1/3] Running orchestrator in testnet mode..." -ForegroundColor Yellow
python -m orchestrator.run `
    --config ./config/defaults.testnet_signal_v2.yaml `
    --enable harvest,signal `
    --sink dual `
    --minutes $MINUTES `
    --symbols $SYMBOLS `
    --output-dir $OUTPUT_DIR `
    --debug

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] Orchestrator execution failed" -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] Orchestrator execution completed" -ForegroundColor Green
Write-Host ""

# Step 2: Run verification script
Write-Host "[2/3] Running verification script..." -ForegroundColor Yellow
python scripts/testnet_verify_signal_v2.py `
    --output-dir $OUTPUT_DIR `
    --baseline-dir $BASELINE_DIR `
    --symbols $SYMBOLS `
    --minutes $MINUTES

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] Verification failed" -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] Verification completed" -ForegroundColor Green
Write-Host ""

# Step 3: Display report summary
Write-Host "[3/3] Report summary..." -ForegroundColor Yellow
$REPORT_FILE = Join-Path $OUTPUT_DIR "testnet_report.json"
if (Test-Path $REPORT_FILE) {
    Write-Host "Detailed report: $REPORT_FILE" -ForegroundColor Cyan
    
    # Use Python to read and display summary
    $summaryScript = @'
import json
import sys
from pathlib import Path

report_file = Path(r'$REPORT_FILE')
if report_file.exists():
    with open(report_file, 'r', encoding='utf-8') as f:
        report = json.load(f)
    
    print("\n" + "="*80)
    print("T2 Testnet Verification Summary")
    print("="*80 + "\n")
    
    # Signal statistics
    if 'signal_stats' in report:
        stats = report['signal_stats']
        print("Signal Statistics:")
        print(f"  Total signals: {stats.get('total', 0)}")
        print(f"  Confirmed signals: {stats.get('confirm_count', 0)}")
        print(f"  Confirm rate: {stats.get('confirm_rate', 0):.2%}")
        print(f"  Decision Code Distribution:")
        for code, count in stats.get('decision_code_dist', {}).items():
            print(f"    {code}: {count}")
        print()
    
    # Baseline comparison
    if 'baseline_comparison' in report:
        comp = report['baseline_comparison']
        print("Baseline Comparison:")
        if comp.get('baseline_found', False):
            print(f"  Confirm rate diff: {comp.get('confirm_rate_diff', 0):.2%}")
            print(f"  Status: {comp.get('status', 'UNKNOWN')}")
            if comp.get('alerts'):
                print(f"  Alerts: {len(comp.get('alerts', []))}")
                for alert in comp.get('alerts', [])[:5]:
                    print(f"    - {alert}")
        else:
            print("  Baseline not found, skipping comparison")
        print()
    
    # Health checks
    if 'health_checks' in report:
        health = report['health_checks']
        print("Health Checks:")
        print(f"  JSONL files exist: {health.get('jsonl_exists', False)}")
        print(f"  SQLite database exists: {health.get('sqlite_exists', False)}")
        print(f"  Dual sink consistency: {health.get('dual_sink_consistent', False)}")
        print()
'@
    
    $summaryScript = $summaryScript -replace '\$REPORT_FILE', $REPORT_FILE
    python -c $summaryScript
} else {
    Write-Host "[WARN] Report file not found: $REPORT_FILE" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[SUCCESS] T2 Testnet completed!" -ForegroundColor Green
Write-Host "View detailed report: $REPORT_FILE" -ForegroundColor Cyan

