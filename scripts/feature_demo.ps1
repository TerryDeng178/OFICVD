# FeaturePipe Demo Script (PowerShell)
# Windows local test for feature calculation pipeline

# Set error handling
$ErrorActionPreference = "Stop"

# Get script directory and switch to project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "=========================================="
Write-Host "FeaturePipe Demo"
Write-Host "=========================================="
Write-Host "Project Root: $ProjectRoot"
Write-Host ""

# Check Python environment
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python Version: $pythonVersion"
} catch {
    Write-Host "Error: python command not found" -ForegroundColor Red
    Write-Host "Please ensure Python >= 3.10 is installed"
    exit 1
}

# Set default parameters (can be overridden by environment variables)
$InputDir = if ($env:INPUT_DIR) { $env:INPUT_DIR } else { "./deploy/data/ofi_cvd" }
$Sink = if ($env:SINK) { $env:SINK } else { "jsonl" }
$OutputDir = if ($env:OUTPUT_DIR) { $env:OUTPUT_DIR } else { "./runtime" }
$Symbols = if ($env:SYMBOLS) { $env:SYMBOLS } else { "BTCUSDT" }
$ConfigFile = if ($env:CONFIG_FILE) { $env:CONFIG_FILE } else { "./config/defaults.yaml" }

Write-Host "Configuration:"
Write-Host "  - Input Directory: $InputDir"
Write-Host "  - Sink Type: $Sink"
Write-Host "  - Output Directory: $OutputDir"
Write-Host "  - Symbols: $Symbols"
Write-Host "  - Config File: $ConfigFile"
Write-Host ""

# Create output directory
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "=========================================="
Write-Host "Starting FeaturePipe..."
Write-Host "=========================================="
Write-Host ""

# Determine output file extension
$OutputExt = if ($Sink -eq "jsonl") { "jsonl" } else { "db" }
$OutputFile = Join-Path $OutputDir "features.$OutputExt"

# Start FeaturePipe
try {
    python -m alpha_core.microstructure.feature_pipe `
        --input $InputDir `
        --sink $Sink `
        --out $OutputFile `
        --symbols $Symbols `
        --config $ConfigFile
    
    $ExitCode = $LASTEXITCODE
} catch {
    Write-Host "Error: Failed to start FeaturePipe" -ForegroundColor Red
    Write-Host $_.Exception.Message
    $ExitCode = 1
}

Write-Host ""
Write-Host "=========================================="
if ($ExitCode -eq 0) {
    Write-Host "FeaturePipe exited successfully" -ForegroundColor Green
    Write-Host "Output File: $OutputFile"
} else {
    Write-Host "FeaturePipe exited with error (Exit Code: $ExitCode)" -ForegroundColor Red
}
Write-Host "=========================================="

exit $ExitCode
