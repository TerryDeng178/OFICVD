# HARVEST 本地一键启动脚本 (PowerShell)
# 用于 Windows 本地测试和开发

# 设置错误处理
$ErrorActionPreference = "Stop"

# 获取脚本所在目录，并切换到项目根目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "=========================================="
Write-Host "HARVEST 本地采集启动"
Write-Host "=========================================="
Write-Host "项目根目录: $ProjectRoot"
Write-Host ""

# 检查 Python 环境
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python 版本: $pythonVersion"
} catch {
    Write-Host "错误: 未找到 python 命令" -ForegroundColor Red
    Write-Host "请确保已安装 Python >= 3.10"
    exit 1
}

# 检查配置文件是否存在
$ConfigFile = if ($env:CONFIG_FILE) { $env:CONFIG_FILE } else { "./config/defaults.yaml" }
if (-not (Test-Path $ConfigFile)) {
    Write-Host "警告: 配置文件不存在: $ConfigFile" -ForegroundColor Yellow
    Write-Host "将使用默认配置或环境变量"
}

# 设置默认参数（可通过环境变量覆盖）
$OutputDir = if ($env:OUTPUT_DIR) { $env:OUTPUT_DIR } else { "./deploy/data/ofi_cvd" }
$Format = if ($env:FORMAT) { $env:FORMAT } else { "parquet" }
$MaxRows = if ($env:MAX_ROWS) { $env:MAX_ROWS } else { "200000" }
$MaxSec = if ($env:MAX_SEC) { $env:MAX_SEC } else { "60" }

Write-Host "配置参数:"
Write-Host "  - 配置文件: $ConfigFile"
Write-Host "  - 输出目录: $OutputDir"
Write-Host "  - 输出格式: $Format"
Write-Host "  - 轮转最大行数: $MaxRows"
Write-Host "  - 轮转时间间隔: $MaxSec 秒"
Write-Host ""
Write-Host "提示: 可通过环境变量覆盖参数，例如:"
Write-Host "  `$env:OUTPUT_DIR='./custom/data'; `$env:FORMAT='jsonl'; .\scripts\harvest_local.ps1"
Write-Host ""
Write-Host "=========================================="
Write-Host "启动 HARVEST 采集器..."
Write-Host "=========================================="
Write-Host ""

# 启动 HARVEST（参数可按需覆盖）
try {
    python -m mcp.harvest_server.app `
        --config $ConfigFile `
        --output $OutputDir `
        --format $Format `
        --rotate.max_rows $MaxRows `
        --rotate.max_sec $MaxSec
    
    $ExitCode = $LASTEXITCODE
} catch {
    Write-Host "错误: 启动失败" -ForegroundColor Red
    Write-Host $_.Exception.Message
    $ExitCode = 1
}

Write-Host ""
Write-Host "=========================================="
if ($ExitCode -eq 0) {
    Write-Host "HARVEST 采集器正常退出" -ForegroundColor Green
} else {
    Write-Host "HARVEST 采集器异常退出 (退出码: $ExitCode)" -ForegroundColor Red
}
Write-Host "=========================================="

exit $ExitCode

