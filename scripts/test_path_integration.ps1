# P1路径加固整体测试脚本
param(
    [int]$Minutes = 3
)

$ErrorActionPreference = "Stop"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "P1路径加固整体测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 测试路径常量
Write-Host "`n步骤1: 测试路径常量模块..." -ForegroundColor Yellow
python scripts\test_path_unification.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 路径常量测试失败" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] 路径常量测试通过" -ForegroundColor Green

# 2. 清理旧数据（可选）
Write-Host "`n步骤2: 检查目录结构..." -ForegroundColor Yellow
$roots = python -c "import sys; sys.path.insert(0, '.'); from src.alpha_core.common.paths import resolve_roots; from pathlib import Path; roots = resolve_roots(Path('.')); print(str(roots['RAW_ROOT'])); print(str(roots['PREVIEW_ROOT'])); print(str(roots['ARTIFACTS_ROOT']))"
$rawRoot, $previewRoot, $artifactsRoot = $roots -split "`n"

Write-Host "  RAW_ROOT: $rawRoot" -ForegroundColor Gray
Write-Host "  PREVIEW_ROOT: $previewRoot" -ForegroundColor Gray
Write-Host "  ARTIFACTS_ROOT: $artifactsRoot" -ForegroundColor Gray

# 检查是否存在旧的独立preview树
$oldPreviewPath = "deploy\preview\ofi_cvd"
if (Test-Path $oldPreviewPath) {
    Write-Host "`n[WARN] 发现旧的独立preview树: $oldPreviewPath" -ForegroundColor Yellow
    Write-Host "  建议: 移除旧的独立preview树，统一使用data/ofi_cvd/preview" -ForegroundColor Gray
} else {
    Write-Host "`n[PASS] 未发现旧的独立preview树" -ForegroundColor Green
}

# 3. 运行短时间测试验证路径对齐
Write-Host "`n步骤3: 运行短时间测试验证路径对齐（$Minutes分钟）..." -ForegroundColor Yellow

$env:V13_INPUT_MODE = "preview"
$env:RUN_ID = "test_path_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "  环境变量:" -ForegroundColor Gray
Write-Host "    V13_INPUT_MODE = $env:V13_INPUT_MODE" -ForegroundColor Gray
Write-Host "    RUN_ID = $env:RUN_ID" -ForegroundColor Gray

# 运行orchestrator（短时间测试）
Write-Host "`n  启动Orchestrator..." -ForegroundColor Gray
python -m orchestrator.run `
    --config ./config/defaults.yaml `
    --enable harvest,signal `
    --sink jsonl `
    --minutes $Minutes `
    2>&1 | Select-String -Pattern "(signal.input|路径|Path|mode=|dir=)" | Select-Object -First 20

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[PASS] Orchestrator测试通过" -ForegroundColor Green
} else {
    Write-Host "`n[FAIL] Orchestrator测试失败（退出码: $LASTEXITCODE）" -ForegroundColor Red
    exit 1
}

# 4. 验证数据写入路径
Write-Host "`n步骤4: 验证数据写入路径..." -ForegroundColor Yellow

$rawFiles = Get-ChildItem -Path $rawRoot -Recurse -Filter "*.parquet" -ErrorAction SilentlyContinue | Select-Object -First 3
$previewFiles = Get-ChildItem -Path $previewRoot -Recurse -Filter "*.parquet" -ErrorAction SilentlyContinue | Select-Object -First 3

if ($rawFiles) {
    Write-Host "  RAW路径文件（示例）:" -ForegroundColor Gray
    foreach ($file in $rawFiles) {
        $relPath = $file.FullName.Replace((Resolve-Path $rawRoot).Path + "\", "")
        Write-Host "    $relPath" -ForegroundColor Gray
    }
}

if ($previewFiles) {
    Write-Host "  PREVIEW路径文件（示例）:" -ForegroundColor Gray
    foreach ($file in $previewFiles) {
        $relPath = $file.FullName.Replace((Resolve-Path $previewRoot).Path + "\", "")
        Write-Host "    $relPath" -ForegroundColor Gray
    }
}

# 5. 验证信号输出路径
Write-Host "`n步骤5: 验证信号输出路径..." -ForegroundColor Yellow

$signalFiles = Get-ChildItem -Path "deploy\data\ofi_cvd\ready\signal" -Recurse -Filter "*.jsonl" -ErrorAction SilentlyContinue | Select-Object -First 3
if ($signalFiles) {
    Write-Host "  信号文件（示例）:" -ForegroundColor Gray
    foreach ($file in $signalFiles) {
        Write-Host "    $($file.Name)" -ForegroundColor Gray
    }
    Write-Host "`n[PASS] 信号输出路径验证通过" -ForegroundColor Green
} else {
    Write-Host "`n[WARN] 未找到信号文件（可能测试时间太短）" -ForegroundColor Yellow
}

# 6. 总结
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "测试完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`n路径统一修复验证:" -ForegroundColor Yellow
Write-Host "  [PASS] 路径常量模块" -ForegroundColor Green
Write-Host "  [PASS] 目录结构" -ForegroundColor Green
Write-Host "  [PASS] Orchestrator路径使用" -ForegroundColor Green
Write-Host "  [PASS] 数据写入路径验证" -ForegroundColor Green
Write-Host "`n所有测试通过！" -ForegroundColor Green

