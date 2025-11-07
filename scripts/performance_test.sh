#!/bin/bash
# FeaturePipe Performance Test Script (Bash)
# 性能测试：处理速度和 CPU 使用率

set -e

# Get script directory and switch to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "FeaturePipe Performance Test"
echo "=========================================="
echo ""

# Check Python environment
if ! command -v python &> /dev/null; then
    echo "Error: python command not found" >&2
    exit 1
fi

python --version

# Configuration
INPUT_DIR="${INPUT_DIR:-./deploy/data/ofi_cvd}"
OUTPUT_DIR="${OUTPUT_DIR:-./runtime/perf_test}"
SYMBOLS="${SYMBOLS:-BTCUSDT}"
CONFIG_FILE="${CONFIG_FILE:-./config/defaults.yaml}"
TEST_DURATION="${TEST_DURATION:-60}"  # Default 60 seconds

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "Configuration:"
echo "  - Input Directory: $INPUT_DIR"
echo "  - Output Directory: $OUTPUT_DIR"
echo "  - Symbols: $SYMBOLS"
echo "  - Test Duration: $TEST_DURATION seconds"
echo ""

# Check if input data exists
if [ ! -d "$INPUT_DIR" ]; then
    echo "Error: Input directory not found: $INPUT_DIR" >&2
    exit 1
fi

# Count input files
FILE_COUNT=$(find "$INPUT_DIR" -type f \( -name "*.parquet" -o -name "*.jsonl" \) | wc -l)
echo "Found $FILE_COUNT input files"
echo ""

# Check if psutil is installed
if ! python -c "import psutil" 2>/dev/null; then
    echo "Installing psutil for performance monitoring..."
    pip install psutil
fi

# Create and run performance test script
python3 << 'PYTHON_SCRIPT'
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

# Configuration (from environment)
input_dir = os.environ.get("INPUT_DIR", "./deploy/data/ofi_cvd")
output_dir = os.environ.get("OUTPUT_DIR", "./runtime/perf_test")
symbols_str = os.environ.get("SYMBOLS", "BTCUSDT")
symbols = symbols_str.split(",") if symbols_str else None
config_file = os.environ.get("CONFIG_FILE", "./config/defaults.yaml")
test_duration = int(os.environ.get("TEST_DURATION", "60"))

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
import pandas as pd

input_files = []
for pattern in ["*.parquet", "*.jsonl"]:
    input_files.extend(Path(input_dir).rglob(pattern))

input_files = sorted(input_files)[:100]  # Limit to 100 files for testing

print(f"Processing {len(input_files)} files...")
print(f"Test duration: {test_duration} seconds")
print("")

start_time = time.time()
end_time = start_time + test_duration

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
                        cpu_percent = process.cpu_percent(interval=0.1)
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        stats["cpu_samples"].append({
                            "time": time.time() - start_time,
                            "cpu_percent": cpu_percent,
                            "memory_mb": memory_mb
                        })
            
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
                                cpu_percent = process.cpu_percent(interval=0.1)
                                memory_mb = process.memory_info().rss / 1024 / 1024
                                stats["cpu_samples"].append({
                                    "time": time.time() - start_time,
                                    "cpu_percent": cpu_percent,
                                    "memory_mb": memory_mb
                                })
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

avg_cpu = sum(s["cpu_percent"] for s in stats["cpu_samples"]) / len(stats["cpu_samples"]) if stats["cpu_samples"] else 0
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
if rows_per_sec < 1000:
    print(f"\n[WARNING] Processing speed ({rows_per_sec:.2f} rows/s) is below requirement (1000 rows/s)")
    passed = False
else:
    print(f"\n[PASS] Processing speed ({rows_per_sec:.2f} rows/s) meets requirement (>= 1000 rows/s)")

if avg_cpu > 100:
    print(f"[WARNING] Average CPU usage ({avg_cpu:.2f}%) exceeds requirement (< 100% for 1 core)")
    passed = False
else:
    print(f"[PASS] Average CPU usage ({avg_cpu:.2f}%) meets requirement (< 100% for 1 core)")

sys.exit(0 if passed else 1)
PYTHON_SCRIPT

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "Performance test completed successfully"
else
    echo "Performance test failed or did not meet requirements"
fi

exit $EXIT_CODE

