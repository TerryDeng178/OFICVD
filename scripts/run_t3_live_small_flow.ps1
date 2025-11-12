# T3 Live Small Flow Execution Script (PowerShell)
# TASK-A4: Run small flow testnet with trading execution, verify:
#   - Trading execution chain integrity
#   - System stability (busy_timeout/write amplification/fsync rotation)
#   - Failed batch compensation monitoring

# Set UTF-8 encoding for PowerShell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

# Configuration parameters
$SYMBOLS = "BTCUSDT"  # Single symbol for small flow
$MINUTES = 60  # 1 hour for stability observation
$RUN_ID = "t3_live_small_flow_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$BASELINE_DIR = "./runtime/t2_testnet_signal_v2"  # T2 testnet baseline directory

# Set environment variables
$env:V13_SIGNAL_V2 = "1"
$env:V13_SINK = "dual"
$env:V13_OUTPUT_DIR = "./runtime/t3_live_small_flow"
$env:PYTHONUTF8 = "1"
$env:RUN_ID = $RUN_ID

# Set feature version and rules version (for config_hash)
$env:CORE_FEATURES_VER = "ofi/cvd v3"
$env:CORE_RULES_VER = "core v1"

# Ensure testnet environment variables are set (if not already set)
if (-not $env:BINANCE_API_KEY) {
    Write-Host "[INFO] Setting Binance Testnet API credentials..." -ForegroundColor Yellow
    # Source the testnet setup script to set environment variables
    & .\scripts\setup_binance_testnet_env.ps1
}

# Create output directory
$OUTPUT_DIR = $env:V13_OUTPUT_DIR
New-Item -ItemType Directory -Force -Path $OUTPUT_DIR | Out-Null

Write-Host "========================================" -ForegroundColor Green
Write-Host "T3 Live Small Flow Execution - Signal v2" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Run ID: $RUN_ID" -ForegroundColor Cyan
Write-Host "Symbols: $SYMBOLS (Single symbol, small flow)" -ForegroundColor Cyan
Write-Host "Minutes: $MINUTES" -ForegroundColor Cyan
Write-Host "Output directory: $OUTPUT_DIR" -ForegroundColor Cyan
Write-Host "Baseline directory: $BASELINE_DIR" -ForegroundColor Cyan
Write-Host "Environment: Testnet (with trading execution)" -ForegroundColor Yellow
Write-Host ""

# Check baseline directory
if (-not (Test-Path $BASELINE_DIR)) {
    Write-Host "[WARN] Baseline directory not found: $BASELINE_DIR" -ForegroundColor Yellow
    Write-Host "[WARN] Will skip baseline comparison" -ForegroundColor Yellow
    $BASELINE_DIR = $null
}

# Step 1: Run orchestrator with trading execution
Write-Host "[1/3] Running orchestrator with trading execution..." -ForegroundColor Yellow
Write-Host "  Enabled modules: harvest,signal,strategy,broker" -ForegroundColor Gray
Write-Host "  Broker mode: testnet (dry_run=false, mock_enabled=false)" -ForegroundColor Gray
Write-Host ""

python -m orchestrator.run `
    --config ./config/defaults.t3_live_small_flow.yaml `
    --enable harvest,signal,strategy,broker `
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
python scripts/t3_live_small_flow_verify.py `
    --output-dir $OUTPUT_DIR `
    --baseline-dir $BASELINE_DIR `
    --symbols $SYMBOLS `
    --minutes $MINUTES `
    --run-id $RUN_ID

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] Verification failed" -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] Verification completed" -ForegroundColor Green
Write-Host ""

# Step 3: Display report summary
Write-Host "[3/3] Report summary..." -ForegroundColor Yellow
$REPORT_FILE = Join-Path $OUTPUT_DIR "t3_report.json"
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
    print("T3 Live Small Flow Verification Summary")
    print("="*80 + "\n")
    
    # Signal statistics
    if 'signal_stats' in report:
        stats = report['signal_stats']
        print("Signal Statistics:")
        print(f"  Total signals: {stats.get('total', 0):,}")
        print(f"  Confirmed signals: {stats.get('confirm_count', 0)}")
        print(f"  Confirm rate: {stats.get('confirm_rate', 0):.6%}")
        print()
    
    # Trading statistics
    if 'trading_stats' in report:
        trading = report['trading_stats']
        print("Trading Statistics:")
        print(f"  Total orders: {trading.get('total_orders', 0)}")
        print(f"  Filled orders: {trading.get('filled_orders', 0)}")
        print(f"  Rejected orders: {trading.get('rejected_orders', 0)}")
        print(f"  Fill rate: {trading.get('fill_rate', 0):.2%}")
        print()
    
    # System stability
    if 'system_stability' in report:
        stability = report['system_stability']
        print("System Stability:")
        print(f"  Dual sink consistent: {stability.get('dual_sink_consistent', False)}")
        print(f"  SQLite busy_timeout issues: {stability.get('sqlite_busy_timeout_issues', 0)}")
        print(f"  Write amplification ratio: {stability.get('write_amplification_ratio', 0):.2f}")
        print(f"  Fsync rotation stable: {stability.get('fsync_rotation_stable', False)}")
        print()
    
    # Baseline comparison
    if 'baseline_comparison' in report:
        comp = report['baseline_comparison']
        print("Baseline Comparison:")
        if comp.get('baseline_found', False):
            print(f"  Status: {comp.get('status', 'UNKNOWN')}")
            if comp.get('alerts'):
                print(f"  Alerts: {len(comp.get('alerts', []))}")
                for alert in comp.get('alerts', [])[:5]:
                    print(f"    - {alert}")
        else:
            print("  Baseline not found, skipping comparison")
        print()
'@
    
    $summaryScript = $summaryScript -replace '\$REPORT_FILE', $REPORT_FILE
    python -c $summaryScript
} else {
    Write-Host "[WARN] Report file not found: $REPORT_FILE" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[SUCCESS] T3 Live Small Flow completed!" -ForegroundColor Green
Write-Host "View detailed report: $REPORT_FILE" -ForegroundColor Cyan

