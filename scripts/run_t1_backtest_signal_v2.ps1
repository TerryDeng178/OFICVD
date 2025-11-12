# T1 Backtest Execution Script (PowerShell)
# TASK-A4: Run fixed window (>=2 hours, 2 trading pairs), verify:
#   - confirm rate / decision_code distribution
#   - contract consistency (JSONL=SQLite)
#   - generate regression baseline (with config_hash/rules_ver/features_ver)

# Set UTF-8 encoding for PowerShell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

# Configuration parameters
$SYMBOLS = "BTCUSDT,ETHUSDT"
$MINUTES = 120  # 2 hours
$DATE = "2025-11-09"  # Use existing data date
$RUN_ID = "t1_backtest_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# Set environment variables
$env:V13_SIGNAL_V2 = "1"
$env:V13_SINK = "dual"
$env:V13_OUTPUT_DIR = "./runtime/t1_backtest_signal_v2"
$env:V13_REPLAY_MODE = "1"
$env:PYTHONUTF8 = "1"
$env:RUN_ID = $RUN_ID

# Set feature version and rules version (for config_hash)
$env:CORE_FEATURES_VER = "ofi/cvd v3"
$env:CORE_RULES_VER = "core v1"

# Create output directory
$OUTPUT_DIR = $env:V13_OUTPUT_DIR
New-Item -ItemType Directory -Force -Path $OUTPUT_DIR | Out-Null

Write-Host "========================================" -ForegroundColor Green
Write-Host "T1 Backtest Execution - Signal v2" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Run ID: $RUN_ID" -ForegroundColor Cyan
Write-Host "Symbols: $SYMBOLS" -ForegroundColor Cyan
Write-Host "Minutes: $MINUTES" -ForegroundColor Cyan
Write-Host "Date: $DATE" -ForegroundColor Cyan
Write-Host "Output directory: $OUTPUT_DIR" -ForegroundColor Cyan
Write-Host ""

# Check data directory (use parent directory to allow DataReader to scan both ready and preview)
$DATA_DIR = "./deploy/data/ofi_cvd"
if (-not (Test-Path $DATA_DIR)) {
    Write-Host "[ERROR] Data directory not found: $DATA_DIR" -ForegroundColor Red
    exit 1
}

# Step 1: Run backtest to generate signals
Write-Host "[1/3] Running backtest to generate signals..." -ForegroundColor Yellow
python scripts/replay_harness.py `
    --input $DATA_DIR `
    --date $DATE `
    --symbols $SYMBOLS `
    --kinds features `
    --config ./config/defaults.signal_v2.yaml `
    --output $OUTPUT_DIR `
    --sink dual `
    --minutes $MINUTES `
    --source preview

if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] Backtest execution failed" -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] Backtest execution completed" -ForegroundColor Green
Write-Host ""

# Step 2: Run verification script
# Note: Do not pass --run-id, let the verification script auto-detect from signals
Write-Host "[2/3] Running verification script..." -ForegroundColor Yellow
python scripts/backtest_verify_signal_v2.py `
    --data-dir $DATA_DIR `
    --output-dir $OUTPUT_DIR `
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
$REPORT_FILE = Join-Path $OUTPUT_DIR "report.json"
if (Test-Path $REPORT_FILE) {
    Write-Host "Detailed report: $REPORT_FILE" -ForegroundColor Cyan
    
    # Use Python to read and display summary
    $summaryScript = @"
import json
import sys

with open(r'$REPORT_FILE', 'r', encoding='utf-8') as f:
    report = json.load(f)

print("\n" + "=" * 80)
print("T1 Backtest Verification Summary")
print("=" * 80)

jsonl_stats = report.get('jsonl_statistics', {})
print(f"\nJSONL Statistics:")
print(f"  Total signals: {jsonl_stats.get('total', 0)}")
print(f"  Confirmed signals: {jsonl_stats.get('confirm_count', 0)}")
print(f"  Confirm rate: {jsonl_stats.get('confirm_rate', 0)}%")
print(f"\n  Decision Code Distribution:")
for code, count in jsonl_stats.get('decision_code_distribution', {}).items():
    print(f"    {code}: {count}")

sqlite_stats = report.get('sqlite_statistics', {})
print(f"\nSQLite Statistics:")
print(f"  Total signals: {sqlite_stats.get('total', 0)}")
print(f"  Confirmed signals: {sqlite_stats.get('confirm_count', 0)}")
print(f"  Confirm rate: {sqlite_stats.get('confirm_rate', 0)}%")

jsonl_contract = report.get('jsonl_contract_verification', {})
sqlite_contract = report.get('sqlite_contract_verification', {})
dual_sink = report.get('dual_sink_consistency', {})

print(f"\nContract Consistency Verification:")
print(f"  JSONL errors: {len(jsonl_contract.get('errors', []))}")
print(f"  SQLite errors: {len(sqlite_contract.get('errors', []))}")
print(f"  Dual Sink consistency errors: {len(dual_sink.get('errors', []))}")

if jsonl_contract.get('config_hash_count', 0) > 0:
    print(f"\nConfig Hash:")
    print(f"  Unique config_hash count: {jsonl_contract.get('config_hash_count', 0)}")
    print(f"  Config Hash values: {', '.join(jsonl_contract.get('config_hashes', []))}")

print("\n" + "=" * 80)
"@
    $summaryScript | python
} else {
    Write-Host "[WARNING] Report file not found: $REPORT_FILE" -ForegroundColor Yellow
}

Write-Host "`n[SUCCESS] T1 Backtest completed!" -ForegroundColor Green
Write-Host "View detailed report: $REPORT_FILE" -ForegroundColor Cyan

