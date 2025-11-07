# -*- coding: utf-8 -*-
# P1-G: 双 Sink 结果对齐的"自动回归" (PowerShell)
# 同一窗口分别跑 JSONL/SQLite 两轮，对比统计结果（容忍 ≤10% 差）
# P0: 使用 REPLAY 模式固定输入，提高可重复性

param(
    [string]$Config = "./config/defaults.replay.yaml",
    [int]$Minutes = 2
)

# P0: 强制使用 REPLAY 模式，固定输入数据窗口
$env:V13_REPLAY_MODE = "1"

# P0: 修复 PowerShell 编码问题
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "双 Sink 结果对齐回归测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "配置: $Config" -ForegroundColor Yellow
Write-Host "运行时长: $Minutes 分钟" -ForegroundColor Yellow
Write-Host ""

$ProjectRoot = (Get-Location).Path
$OutputDir = Join-Path $ProjectRoot "runtime"

# 清理之前的输出
if (Test-Path "$OutputDir\ready\signal") {
    Remove-Item -Recurse -Force "$OutputDir\ready\signal" -ErrorAction SilentlyContinue
}
if (Test-Path "$OutputDir\signals.db") {
    Remove-Item -Force "$OutputDir\signals.db" -ErrorAction SilentlyContinue
}
if (Test-Path "$OutputDir\mock_orders.jsonl") {
    Remove-Item -Force "$OutputDir\mock_orders.jsonl" -ErrorAction SilentlyContinue
}

# 运行 JSONL 模式
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host "运行 JSONL 模式..." -ForegroundColor Green
Write-Host "----------------------------------------" -ForegroundColor Green

python -m orchestrator.run `
    --config $Config `
    --enable signal,report `
    --sink jsonl `
    --minutes $Minutes `
    --debug

if ($LASTEXITCODE -ne 0) {
    Write-Host "JSONL 模式测试失败！" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 读取 JSONL 报表
$ReportDir = Join-Path $ProjectRoot "logs\report"
$JsonlReport = Get-ChildItem $ReportDir -Filter "summary_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $JsonlReport) {
    Write-Host "JSONL report file not found" -ForegroundColor Red
    exit 1
}

$JsonlReportPath = $JsonlReport.FullName
Write-Host ""
Write-Host "JSONL Report: $JsonlReportPath" -ForegroundColor Yellow

# 清理输出（保留报表）
if (Test-Path "$OutputDir\ready\signal") {
    Remove-Item -Recurse -Force "$OutputDir\ready\signal" -ErrorAction SilentlyContinue
}
if (Test-Path "$OutputDir\signals.db") {
    Remove-Item -Force "$OutputDir\signals.db" -ErrorAction SilentlyContinue
}
if (Test-Path "$OutputDir\mock_orders.jsonl") {
    Remove-Item -Force "$OutputDir\mock_orders.jsonl" -ErrorAction SilentlyContinue
}

# 运行 SQLite 模式
Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host "Running SQLite mode..." -ForegroundColor Green
Write-Host "----------------------------------------" -ForegroundColor Green

python -m orchestrator.run `
    --config $Config `
    --enable signal,report `
    --sink sqlite `
    --minutes $Minutes `
    --debug

if ($LASTEXITCODE -ne 0) {
    Write-Host "SQLite mode test failed!" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 等待报表生成（最多等待5秒）
Start-Sleep -Seconds 2

# 读取 SQLite 报表（排除 JSONL 报表）
$AllReports = Get-ChildItem $ReportDir -Filter "summary_*.json" | Sort-Object LastWriteTime -Descending
$SqliteReport = $AllReports | Where-Object { $_.FullName -ne $JsonlReportPath } | Select-Object -First 1

if (-not $SqliteReport) {
    Write-Host "SQLite report file not found" -ForegroundColor Red
    Write-Host "Available reports:" -ForegroundColor Yellow
    $AllReports | ForEach-Object { Write-Host "  $($_.FullName) (LastWrite: $($_.LastWriteTime))" }
    exit 1
}

Write-Host ""
Write-Host "SQLite Report: $($SqliteReport.FullName)" -ForegroundColor Yellow

# 对比统计结果
Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host "对比统计结果..." -ForegroundColor Green
Write-Host "----------------------------------------" -ForegroundColor Green

$jsonlData = Get-Content $JsonlReport.FullName | ConvertFrom-Json
$sqliteData = Get-Content $SqliteReport.FullName | ConvertFrom-Json

$failed = $false

# 对比指标
$metrics = @(
    @{Key="total"; Name="Total"},
    @{Key="buy_count"; Name="Buy"},
    @{Key="sell_count"; Name="Sell"},
    @{Key="strong_buy_count"; Name="StrongBuy"},
    @{Key="strong_sell_count"; Name="StrongSell"}
)

# 调整对齐阈值：核心计数类 5%，比率类 10%
$coreMetrics = @("total", "buy_count", "sell_count", "strong_buy_count", "strong_sell_count")

foreach ($metric in $metrics) {
    $jsonlVal = $jsonlData.$($metric.Key)
    $sqliteVal = $sqliteData.$($metric.Key)
    
    if ($jsonlVal -eq 0 -and $sqliteVal -eq 0) {
        $diffPct = 0.0
    } elseif ($jsonlVal -eq 0) {
        $diffPct = 100.0
    } else {
        $diffPct = [Math]::Abs($jsonlVal - $sqliteVal) / $jsonlVal * 100
    }
    
    # 核心计数类使用 5% 阈值，其他使用 10%
    $threshold = if ($coreMetrics -contains $metric.Key) { 5.0 } else { 10.0 }
    $status = if ($diffPct -le $threshold) { "[OK]" } else { "[FAIL]" }
    $color = if ($diffPct -le $threshold) { "Green" } else { "Red" }
    
    Write-Host "$status $($metric.Name): JSONL=$jsonlVal, SQLite=$sqliteVal, Diff=$([Math]::Round($diffPct, 2))% (Threshold=$threshold%)" -ForegroundColor $color
    
    if ($diffPct -gt $threshold) {
        $failed = $true
    }
}

# 对比强信号比例（比率类使用 10% 阈值）
$jsonlStrongRatio = $jsonlData.strong_ratio
$sqliteStrongRatio = $sqliteData.strong_ratio

if ($jsonlStrongRatio -gt 0) {
    $diffPct = [Math]::Abs($jsonlStrongRatio - $sqliteStrongRatio) / $jsonlStrongRatio * 100
} else {
    $diffPct = 0.0
}

$threshold = 10.0
$status = if ($diffPct -le $threshold) { "[OK]" } else { "[FAIL]" }
$color = if ($diffPct -le $threshold) { "Green" } else { "Red" }

Write-Host "$status StrongRatio: JSONL=$([Math]::Round($jsonlStrongRatio, 4)), SQLite=$([Math]::Round($sqliteStrongRatio, 4)), Diff=$([Math]::Round($diffPct, 2))% (Threshold=$threshold%)" -ForegroundColor $color

if ($diffPct -gt $threshold) {
    $failed = $true
}

# P1: 扩充"双 Sink 对齐"核对维度 - 护栏分解一致性
Write-Host ""
Write-Host "Comparing Gating Breakdown..." -ForegroundColor Yellow

$jsonlGating = $jsonlData.gating_breakdown
$sqliteGating = $sqliteData.gating_breakdown

if ($jsonlGating -and $sqliteGating) {
    $allReasons = @()
    if ($jsonlGating.PSObject.Properties) {
        $allReasons += $jsonlGating.PSObject.Properties.Name
    }
    if ($sqliteGating.PSObject.Properties) {
        $allReasons += $sqliteGating.PSObject.Properties.Name
    }
    $allReasons = $allReasons | Select-Object -Unique
    
    foreach ($reason in $allReasons) {
        $jsonlVal = if ($jsonlGating.$reason) { $jsonlGating.$reason } else { 0 }
        $sqliteVal = if ($sqliteGating.$reason) { $sqliteGating.$reason } else { 0 }
        
        if ($jsonlVal -eq 0 -and $sqliteVal -eq 0) {
            $diffPct = 0.0
        } elseif ($jsonlVal -eq 0) {
            $diffPct = 100.0
        } else {
            $diffPct = [Math]::Abs($jsonlVal - $sqliteVal) / $jsonlVal * 100
        }
        
        # 护栏分解使用 10% 阈值（非核心计数类）
        $threshold = 10.0
        $status = if ($diffPct -le $threshold) { "[OK]" } else { "[WARN]" }
        $color = if ($diffPct -le $threshold) { "Green" } else { "Yellow" }
        
        Write-Host "$status Gating[$reason]: JSONL=$jsonlVal, SQLite=$sqliteVal, Diff=$([Math]::Round($diffPct, 2))% (Threshold=$threshold%)" -ForegroundColor $color
        
        if ($diffPct -gt $threshold) {
            $failed = $true
        }
    }
}

# P1: 扩充"双 Sink 对齐"核对维度 - 分钟节律一致性
Write-Host ""
Write-Host "Comparing Per-Minute Rhythm..." -ForegroundColor Yellow

$jsonlPerMinute = $jsonlData.per_minute
$sqlitePerMinute = $sqliteData.per_minute

if ($jsonlPerMinute -and $sqlitePerMinute) {
    $minCount = [Math]::Min($jsonlPerMinute.Count, $sqlitePerMinute.Count)
    for ($i = 0; $i -lt $minCount; $i++) {
        $jsonlMin = $jsonlPerMinute[$i]
        $sqliteMin = $sqlitePerMinute[$i]
        
        $jsonlCount = $jsonlMin.count
        $sqliteCount = $sqliteMin.count
        
        if ($jsonlCount -eq 0 -and $sqliteCount -eq 0) {
            $diffPct = 0.0
        } elseif ($jsonlCount -eq 0) {
            $diffPct = 100.0
        } else {
            $diffPct = [Math]::Abs($jsonlCount - $sqliteCount) / $jsonlCount * 100
        }
        
        # 分钟节律使用 10% 阈值（非核心计数类）
        $threshold = 10.0
        $status = if ($diffPct -le $threshold) { "[OK]" } else { "[WARN]" }
        $color = if ($diffPct -le $threshold) { "Green" } else { "Yellow" }
        
        $minuteKey = $jsonlMin.minute
        Write-Host "$status Minute[$minuteKey]: JSONL=$jsonlCount, SQLite=$sqliteCount, Diff=$([Math]::Round($diffPct, 2))% (Threshold=$threshold%)" -ForegroundColor $color
        
        if ($diffPct -gt $threshold) {
            $failed = $true
        }
    }
}

Write-Host ""
if ($failed) {
    Write-Host "[FAIL] Some metrics differ by more than threshold, please check statistical consistency" -ForegroundColor Red
    exit 1
} else {
    Write-Host "[OK] All metrics differ within threshold, statistical consistency verified" -ForegroundColor Green
    exit 0
}

