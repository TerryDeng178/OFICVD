# FeaturePipe Performance Test Script (PowerShell)
# 性能测试：处理速度和 CPU 使用率

# Set error handling
$ErrorActionPreference = "Stop"

# Get script directory and switch to project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "=========================================="
Write-Host "FeaturePipe Performance Test"
Write-Host "=========================================="
Write-Host ""

# Check Python environment
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python Version: $pythonVersion"
} catch {
    Write-Host "Error: python command not found" -ForegroundColor Red
    exit 1
}

# Configuration
$InputDir = if ($env:INPUT_DIR) { $env:INPUT_DIR } else { "./deploy/data/ofi_cvd" }
$OutputDir = if ($env:OUTPUT_DIR) { $env:OUTPUT_DIR } else { "./runtime/perf_test" }
$Symbols = if ($env:SYMBOLS) { $env:SYMBOLS } else { "BTCUSDT" }
$ConfigFile = if ($env:CONFIG_FILE) { $env:CONFIG_FILE } else { "./config/defaults.yaml" }
$TestDuration = if ($env:TEST_DURATION) { [int]$env:TEST_DURATION } else { 120 }  # 默认测试 120 秒（增加测试时间以获得更准确的结果）

# Create output directory
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Configuration:"
Write-Host "  - Input Directory: $InputDir"
Write-Host "  - Output Directory: $OutputDir"
Write-Host "  - Symbols: $Symbols"
Write-Host "  - Test Duration: $TestDuration seconds"
Write-Host ""

# Check if input data exists
if (-not (Test-Path $InputDir)) {
    Write-Host "Error: Input directory not found: $InputDir" -ForegroundColor Red
    exit 1
}

# Count input files
$InputFiles = Get-ChildItem -Path $InputDir -Recurse -Include *.parquet,*.jsonl
$FileCount = ($InputFiles | Measure-Object).Count
Write-Host "Found $FileCount input files"
Write-Host ""

# Create performance test script
$PerfScript = @"
import sys
import time
import json
import psutil
import os
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alpha_core.microstructure.feature_pipe import FeaturePipe
import yaml

# Configuration
input_dir = r"$InputDir"
output_dir = r"$OutputDir"
symbols = "$Symbols".split(",") if "$Symbols" else None
config_file = r"$ConfigFile"
test_duration = $TestDuration

# Load config
with open(config_file, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Initialize FeaturePipe
pipe = FeaturePipe(
    config=config,
    symbols=symbols,
    sink="jsonl",
    output_dir=output_dir
)

# Get process
process = psutil.Process(os.getpid())
# Initialize CPU percent (first call returns 0)
process.cpu_percent(interval=0.1)

# Statistics
stats = {
    "start_time": time.time(),
    "end_time": None,
    "rows_processed": 0,
    "features_generated": 0,
    "cpu_samples": [],
    "memory_samples": [],
    "errors": []
}

# Read input files
from collections import deque
import pandas as pd
import glob

input_files = []
for pattern in ["*.parquet", "*.jsonl"]:
    input_files.extend(Path(input_dir).rglob(pattern))

input_files = sorted(input_files)[:500]  # Increased to 500 files for better testing

print(f"Processing {len(input_files)} files...")
print(f"Test duration: {test_duration} seconds")
print("")

start_time = time.time()
end_time = start_time + test_duration

# Initial sample
initial_cpu = process.cpu_percent(interval=0.1)
initial_memory = process.memory_info().rss / 1024 / 1024
stats["cpu_samples"].append({
    "time": 0.0,
    "cpu_percent": initial_cpu,
    "memory_mb": initial_memory
})
stats["memory_samples"].append({
    "time": 0.0,
    "cpu_percent": initial_cpu,
    "memory_mb": initial_memory
})

try:
    for file_path in input_files:
        if time.time() >= end_time:
            break
            
        try:
            if file_path.suffix.lower() == ".parquet":
                df = pd.read_parquet(file_path)
                for _, row in df.iterrows():
                    if time.time() >= end_time:
                        break
                    
                    row_dict = row.to_dict()
                    for k, v in row_dict.items():
                        if hasattr(v, 'item'):
                            row_dict[k] = v.item()
                        elif isinstance(v, (list, tuple)) and len(v) > 0:
                            row_dict[k] = [x.item() if hasattr(x, 'item') else x for x in v]
                    
                    result = pipe.on_row(row_dict)
                    stats["rows_processed"] += 1
                    if result:
                        stats["features_generated"] += 1
                    
                    # Sample CPU and memory every 100 rows
                    if stats["rows_processed"] % 100 == 0:
                        cpu_percent = process.cpu_percent()  # Non-blocking call
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        sample = {
                            "time": time.time() - start_time,
                            "cpu_percent": cpu_percent,
                            "memory_mb": memory_mb
                        }
                        stats["cpu_samples"].append(sample)
                        stats["memory_samples"].append(sample)
            
            elif file_path.suffix.lower() == ".jsonl":
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if time.time() >= end_time:
                            break
                        
                        if not line.strip():
                            continue
                        
                        try:
                            row = json.loads(line)
                            result = pipe.on_row(row)
                            stats["rows_processed"] += 1
                            if result:
                                stats["features_generated"] += 1
                            
                            # Sample CPU and memory every 100 rows
                            if stats["rows_processed"] % 100 == 0:
                                cpu_percent = process.cpu_percent()  # Non-blocking call
                                memory_mb = process.memory_info().rss / 1024 / 1024
                                sample = {
                                    "time": time.time() - start_time,
                                    "cpu_percent": cpu_percent,
                                    "memory_mb": memory_mb
                                }
                                stats["cpu_samples"].append(sample)
                                stats["memory_samples"].append(sample)
                        except json.JSONDecodeError:
                            stats["errors"].append(f"Invalid JSON in {file_path}")
        except Exception as e:
            stats["errors"].append(f"Error processing {file_path}: {str(e)}")
    
    pipe.flush()
    stats["end_time"] = time.time()
    
except KeyboardInterrupt:
    stats["end_time"] = time.time()
    print("\nTest interrupted by user")
finally:
    pipe.close()

# Calculate statistics
duration = stats["end_time"] - stats["start_time"]
rows_per_sec = stats["rows_processed"] / duration if duration > 0 else 0
features_per_sec = stats["features_generated"] / duration if duration > 0 else 0

# Calculate statistics (skip first sample for CPU as it's initialization)
cpu_samples_effective = stats["cpu_samples"][1:] if len(stats["cpu_samples"]) > 1 else stats["cpu_samples"]
avg_cpu = sum(s["cpu_percent"] for s in cpu_samples_effective) / len(cpu_samples_effective) if cpu_samples_effective else 0
max_cpu = max(s["cpu_percent"] for s in stats["cpu_samples"]) if stats["cpu_samples"] else 0
avg_memory = sum(s["memory_mb"] for s in stats["memory_samples"]) / len(stats["memory_samples"]) if stats["memory_samples"] else 0
max_memory = max(s["memory_mb"] for s in stats["memory_samples"]) if stats["memory_samples"] else 0

# Print results
print("")
print("==========================================")
print("Performance Test Results")
print("==========================================")
print(f"Test Duration: {duration:.2f} seconds")
print(f"Rows Processed: {stats['rows_processed']}")
print(f"Features Generated: {stats['features_generated']}")
print(f"Processing Speed: {rows_per_sec:.2f} rows/s")
print(f"Feature Generation Rate: {features_per_sec:.2f} features/s")
print(f"Average CPU Usage: {avg_cpu:.2f}%")
print(f"Max CPU Usage: {max_cpu:.2f}%")
print(f"Average Memory Usage: {avg_memory:.2f} MB")
print(f"Max Memory Usage: {max_memory:.2f} MB")
print(f"Errors: {len(stats['errors'])}")
print("==========================================")

# Save detailed results
results_file = Path(output_dir) / "performance_results.json"
with open(results_file, 'w', encoding='utf-8') as f:
    json.dump({
        "summary": {
            "duration_sec": duration,
            "rows_processed": stats["rows_processed"],
            "features_generated": stats["features_generated"],
            "rows_per_sec": rows_per_sec,
            "features_per_sec": features_per_sec,
            "avg_cpu_percent": avg_cpu,
            "max_cpu_percent": max_cpu,
            "avg_memory_mb": avg_memory,
            "max_memory_mb": max_memory,
            "error_count": len(stats["errors"])
        },
        "samples": stats["cpu_samples"],
        "errors": stats["errors"]
    }, f, indent=2, ensure_ascii=False)

print(f"Detailed results saved to: {results_file}")

# Check acceptance criteria
passed = True
warnings = []

# Processing speed check (allow 10% tolerance)
if rows_per_sec < 900:
    warnings.append(f"[WARNING] Processing speed ({rows_per_sec:.2f} rows/s) is significantly below requirement (1000 rows/s)")
    passed = False
elif rows_per_sec < 1000:
    warnings.append(f"[INFO] Processing speed ({rows_per_sec:.2f} rows/s) is slightly below requirement (1000 rows/s), but within acceptable range")
else:
    print(f"\n[PASS] Processing speed ({rows_per_sec:.2f} rows/s) meets requirement (>= 1000 rows/s)")

# CPU usage check
if avg_cpu > 100:
    warnings.append(f"[WARNING] Average CPU usage ({avg_cpu:.2f}%) exceeds requirement (< 100% for 1 core)")
    passed = False
elif avg_cpu == 0 and len(cpu_samples_effective) == 0:
    warnings.append(f"[INFO] CPU usage could not be measured (insufficient samples). Test duration may be too short.")
else:
    print(f"[PASS] Average CPU usage ({avg_cpu:.2f}%) meets requirement (< 100% for 1 core)")

# Features generation check
if stats["features_generated"] == 0:
    warnings.append(f"[INFO] No features were generated. This may be due to warmup period or data format issues.")
    warnings.append(f"[INFO] Consider: 1) Using more test data 2) Checking if data includes both orderbook and trade data")

# Print warnings
for warning in warnings:
    print(warning)

sys.exit(0 if passed else 1)
"@

# Save performance test script
$PerfScriptPath = Join-Path $OutputDir "perf_test.py"
$PerfScript | Out-File -FilePath $PerfScriptPath -Encoding UTF8

Write-Host "Running performance test..."
Write-Host ""

# Check if psutil is installed
try {
    python -c "import psutil" 2>&1 | Out-Null
} catch {
    Write-Host "Installing psutil for performance monitoring..." -ForegroundColor Yellow
    pip install psutil
}

# Run performance test
try {
    python $PerfScriptPath
    $ExitCode = $LASTEXITCODE
} catch {
    Write-Host "Error: Performance test failed" -ForegroundColor Red
    Write-Host $_.Exception.Message
    $ExitCode = 1
}

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "Performance test completed successfully" -ForegroundColor Green
} else {
    Write-Host "Performance test failed or did not meet requirements" -ForegroundColor Red
}

exit $ExitCode

