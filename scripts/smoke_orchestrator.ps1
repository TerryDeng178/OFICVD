# -*- coding: utf-8 -*-
# Orchestrator 端到端冒烟测试脚本 (PowerShell)

param(
    [string]$Config = "./config/defaults.smoke.yaml",
    [int]$Minutes = 30,
    [string]$Sink = "jsonl"
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Orchestrator 端到端冒烟测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "配置: $Config" -ForegroundColor Yellow
Write-Host "运行时长: $Minutes 分钟" -ForegroundColor Yellow
Write-Host "Sink 类型: $Sink" -ForegroundColor Yellow
Write-Host ""

# 设置环境变量
$env:PYTHONUTF8 = "1"

# 运行 JSONL 模式
if ($Sink -eq "jsonl" -or $Sink -eq "both") {
    Write-Host "----------------------------------------" -ForegroundColor Green
    Write-Host "运行 JSONL 模式..." -ForegroundColor Green
    Write-Host "----------------------------------------" -ForegroundColor Green
    
    python -m orchestrator.run `
        --config $Config `
        --enable harvest,signal,broker,report `
        --sink jsonl `
        --minutes $Minutes `
        --debug
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "JSONL 模式测试失败！" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    
    # 断言检查：读取最新的日报文件
    Write-Host ""
    Write-Host "验证 JSONL 模式结果..." -ForegroundColor Yellow
    $reportDir = "./logs/report"
    if (Test-Path $reportDir) {
        $latestReport = Get-ChildItem $reportDir -Filter "summary_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latestReport) {
            $report = Get-Content $latestReport.FullName | ConvertFrom-Json
            $failed = $false
            
            if ($report.total -le 0) {
                Write-Host "  [FAIL] total > 0 断言失败: total=$($report.total)" -ForegroundColor Red
                $failed = $true
            } else {
                Write-Host "  [OK] total=$($report.total)" -ForegroundColor Green
            }
            
            if ($report.total -gt 0) {
                if ($report.strong_ratio -le 0 -or $report.strong_ratio -ge 1) {
                    Write-Host "  [FAIL] strong_ratio 应在 (0, 1) 范围内: strong_ratio=$($report.strong_ratio)" -ForegroundColor Red
                    $failed = $true
                } else {
                    Write-Host "  [OK] strong_ratio=$($report.strong_ratio)" -ForegroundColor Green
                }
                
                if ($null -eq $report.per_minute -or $report.per_minute.Count -eq 0) {
                    Write-Host "  [FAIL] per_minute 应为非空数组" -ForegroundColor Red
                    $failed = $true
                } else {
                    Write-Host "  [OK] per_minute 包含 $($report.per_minute.Count) 个条目" -ForegroundColor Green
                }
            }
            
            if ($failed) {
                Write-Host "JSONL 模式断言检查失败！" -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "  [WARN] 未找到日报文件" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "JSONL 模式测试完成" -ForegroundColor Green
    Write-Host ""
}

# 运行 SQLite 模式
if ($Sink -eq "sqlite" -or $Sink -eq "both") {
    Write-Host "----------------------------------------" -ForegroundColor Green
    Write-Host "运行 SQLite 模式..." -ForegroundColor Green
    Write-Host "----------------------------------------" -ForegroundColor Green
    
    python -m orchestrator.run `
        --config $Config `
        --enable harvest,signal,broker,report `
        --sink sqlite `
        --minutes $Minutes `
        --debug
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "SQLite 模式测试失败！" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    
    # 断言检查：读取最新的日报文件，并与 JSONL 模式对比
    Write-Host ""
    Write-Host "验证 SQLite 模式结果..." -ForegroundColor Yellow
    $reportDir = "./logs/report"
    if (Test-Path $reportDir) {
        $latestReport = Get-ChildItem $reportDir -Filter "summary_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latestReport) {
            $reportSqlite = Get-Content $latestReport.FullName | ConvertFrom-Json
            $failed = $false
            
            if ($reportSqlite.total -le 0) {
                Write-Host "  [FAIL] total > 0 断言失败: total=$($reportSqlite.total)" -ForegroundColor Red
                $failed = $true
            } else {
                Write-Host "  [OK] total=$($reportSqlite.total)" -ForegroundColor Green
            }
            
            # 如果同时运行了 JSONL 模式，对比总量（允许一定误差）
            if ($Sink -eq "both") {
                $jsonlReports = Get-ChildItem $reportDir -Filter "summary_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 1 -First 1
                if ($jsonlReports) {
                    $reportJsonl = Get-Content $jsonlReports.FullName | ConvertFrom-Json
                    $diff = [Math]::Abs($reportSqlite.total - $reportJsonl.total)
                    $maxDiff = [Math]::Max($reportSqlite.total, $reportJsonl.total) * 0.1  # 允许 10% 误差
                    if ($diff -gt $maxDiff) {
                        Write-Host "  [FAIL] SQLite 与 JSONL 总量差异过大: SQLite=$($reportSqlite.total), JSONL=$($reportJsonl.total), diff=$diff" -ForegroundColor Red
                        $failed = $true
                    } else {
                        Write-Host "  [OK] SQLite 与 JSONL 总量一致: SQLite=$($reportSqlite.total), JSONL=$($reportJsonl.total)" -ForegroundColor Green
                    }
                }
            }
            
            if ($failed) {
                Write-Host "SQLite 模式断言检查失败！" -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "  [WARN] 未找到日报文件" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "SQLite 模式测试完成" -ForegroundColor Green
    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "所有测试完成！" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

