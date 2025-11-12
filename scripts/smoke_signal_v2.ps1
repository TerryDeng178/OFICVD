# Signal v2 冒烟脚本（PowerShell）
# 测试 signal/v2 端到端流程：CoreAlgorithm → SignalWriterV2 → JSONL/SQLite

$ErrorActionPreference = "Stop"

# 设置环境变量
$env:V13_SINK = "dual"
$env:V13_OUTPUT_DIR = "./runtime/smoke_signal_v2"
$env:PYTHONUTF8 = "1"

# 创建输出目录
New-Item -ItemType Directory -Force -Path $env:V13_OUTPUT_DIR | Out-Null

Write-Host "[Smoke Test] Signal v2 E2E Test" -ForegroundColor Green
Write-Host "Output directory: $env:V13_OUTPUT_DIR" -ForegroundColor Cyan

# 运行测试
Write-Host "`n[1/3] Running unit tests..." -ForegroundColor Yellow
python -m pytest tests/test_signal_schema.py tests/test_config_hash.py tests/test_signal_writer.py tests/test_decision_engine.py tests/test_core_algorithm_v2.py -v --tb=line -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] Unit tests failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/3] Running integration tests..." -ForegroundColor Yellow
python -m pytest tests/test_signal_v2_integration.py tests/test_signal_v2_executor_integration.py tests/test_signal_v2_e2e_smoke.py -v --tb=line -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAILED] Integration tests failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n[3/3] Verifying output files..." -ForegroundColor Yellow

# 验证 JSONL 文件
$jsonlDir = Join-Path $env:V13_OUTPUT_DIR "ready\signal"
if (Test-Path $jsonlDir) {
    $jsonlFiles = Get-ChildItem -Path $jsonlDir -Filter "*.jsonl" -Recurse
    Write-Host "Found $($jsonlFiles.Count) JSONL files" -ForegroundColor Cyan
    
    $totalSignals = 0
    foreach ($file in $jsonlFiles) {
        $lines = Get-Content $file.FullName | Where-Object { $_.Trim() -ne "" }
        $totalSignals += $lines.Count
    }
    Write-Host "Total signals in JSONL: $totalSignals" -ForegroundColor Cyan
} else {
    Write-Host "[WARNING] JSONL directory not found: $jsonlDir" -ForegroundColor Yellow
}

# 验证 SQLite 数据库
$dbPath = Join-Path $env:V13_OUTPUT_DIR "signals.db"
if (Test-Path $dbPath) {
    Write-Host "SQLite database found: $dbPath" -ForegroundColor Cyan
    
    # 使用 Python 查询数据库
    $queryScript = @"
import sqlite3
conn = sqlite3.connect(r'$dbPath')
cursor = conn.execute('SELECT COUNT(*) FROM signals')
count = cursor.fetchone()[0]
print(f'Total signals in SQLite: {count}')
conn.close()
"@
    $queryScript | python
} else {
    Write-Host "[WARNING] SQLite database not found: $dbPath" -ForegroundColor Yellow
}

Write-Host "`n[SUCCESS] All smoke tests passed!" -ForegroundColor Green

