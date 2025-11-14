# -*- coding: utf-8 -*-
# Backtest Runner Script (Windows PowerShell)
# TASK-B2: Independent Backtest Runner

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("A", "B")]
    [string]$Mode,

    [Parameter(Mandatory=$false)]
    [string]$FeaturesDir,

    [Parameter(Mandatory=$false)]
    [string]$SignalsSrc,

    [Parameter(Mandatory=$false)]
    [string]$Symbols = "BTCUSDT,ETHUSDT,BNBUSDT",

    [Parameter(Mandatory=$false)]
    [string]$Start,

    [Parameter(Mandatory=$false)]
    [string]$End,

    [Parameter(Mandatory=$false)]
    [string]$Config = "./config/backtest.yaml",

    [Parameter(Mandatory=$false)]
    [string]$OutDir = "./backtest_out",

    [Parameter(Mandatory=$false)]
    [string]$RunId,

    [Parameter(Mandatory=$false)]
    [int]$Seed = 42,

    [Parameter(Mandatory=$false)]
    [string]$Tz = "Asia/Tokyo",

    [Parameter(Mandatory=$false)]
    [switch]$EmitSqlite,

    [Parameter(Mandatory=$false)]
    [switch]$StrictCore,

    [Parameter(Mandatory=$false)]
    [switch]$ReemitSignals
)

# Build command arguments
$args = @()

if ($Mode) {
    $args += "--mode", $Mode
}

if ($FeaturesDir) {
    $args += "--features-dir", $FeaturesDir
}

if ($SignalsSrc) {
    $args += "--signals-src", $SignalsSrc
}

$args += "--symbols", $Symbols

if ($Start) {
    $args += "--start", $Start
}

if ($End) {
    $args += "--end", $End
}

$args += "--config", $Config
$args += "--out-dir", $OutDir

if ($RunId) {
    $args += "--run-id", $RunId
}

$args += "--seed", $Seed.ToString()
$args += "--tz", $Tz

if ($EmitSqlite) {
    $args += "--emit-sqlite"
}

if ($StrictCore) {
    $args += "--strict-core"
}

if ($ReemitSignals) {
    $args += "--reemit-signals"
}

# Execute backtest
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "TASK-B2: Independent Backtest Runner" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Command: python -m backtest.app $($args -join ' ')" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

try {
    & python -m backtest.app @args
    if ($LASTEXITCODE -eq 0) {
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host "Backtest completed successfully!" -ForegroundColor Green
        Write-Host "==========================================" -ForegroundColor Green
    } else {
        Write-Host "==========================================" -ForegroundColor Red
        Write-Host "Backtest failed with exit code: $LASTEXITCODE" -ForegroundColor Red
        Write-Host "==========================================" -ForegroundColor Red
        exit $LASTEXITCODE
    }
} catch {
    Write-Host "==========================================" -ForegroundColor Red
    Write-Host "Error executing backtest: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "==========================================" -ForegroundColor Red
    exit 1
}