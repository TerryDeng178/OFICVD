# T3 Live Small Flow Test Monitor Script
# Monitor T3 test progress, process status, and order execution

param(
    [int]$CheckInterval = 30,
    [switch]$Continuous,
    [switch]$ShowLogs
)

# T3测试的输出目录：根据配置，executor使用runtime，但信号在runtime/t3_live_small_flow
$outputDir = "runtime"
$signalDir = "runtime\t3_live_small_flow"  # 信号目录
$logDir = "logs"

Write-Host "`n========== T3 Live Small Flow Test Monitor ==========" -ForegroundColor Cyan
Write-Host "Output Dir: $outputDir (exec logs)" -ForegroundColor Gray
Write-Host "Signal Dir: $signalDir (signals)" -ForegroundColor Gray
Write-Host "Check Interval: $CheckInterval seconds" -ForegroundColor Gray
Write-Host ""

function Check-ProcessStatus {
    Write-Host "[Process Status]" -ForegroundColor Yellow
    
    $processes = @("orchestrator", "harvest", "signal", "strategy", "broker", "report")
    
    foreach ($procName in $processes) {
        $proc = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
            $cmdline = (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
            $cmdline -like "*$procName*"
        } | Select-Object -First 1
        
        if ($proc) {
            $runtime = (Get-Date) - $proc.StartTime
            Write-Host "  [OK] $procName : PID=$($proc.Id), Runtime=$([math]::Floor($runtime.TotalMinutes))min" -ForegroundColor Green
        } else {
            Write-Host "  [X] $procName : Not running" -ForegroundColor Red
        }
    }
    Write-Host ""
}

function Check-SignalStatus {
    Write-Host "[Signal Status]" -ForegroundColor Yellow
    
    $signalDir = "$signalDir\ready\signal\BTCUSDT"
    if (Test-Path $signalDir) {
        $jsonlFiles = Get-ChildItem -Path $signalDir -Filter "*.jsonl" -ErrorAction SilentlyContinue | 
            Sort-Object LastWriteTime -Descending
        
        if ($jsonlFiles) {
            $latestFile = $jsonlFiles[0]
            $fileAge = (Get-Date) - $latestFile.LastWriteTime
            $fileSize = [math]::Round($latestFile.Length / 1KB, 2)
            
            Write-Host "  Latest JSONL: $($latestFile.Name)" -ForegroundColor Gray
            Write-Host "  File Size: $fileSize KB" -ForegroundColor Gray
            Write-Host "  Last Update: $([math]::Floor($fileAge.TotalSeconds))s ago" -ForegroundColor Gray
        } else {
            Write-Host "  No JSONL files found" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Signal directory not found" -ForegroundColor Yellow
    }
    
    $dbPath = "runtime\t3_live_small_flow\signals_v2.db"
    if (Test-Path $dbPath) {
        $dbAge = (Get-Date) - (Get-Item $dbPath).LastWriteTime
        $dbSize = [math]::Round((Get-Item $dbPath).Length / 1MB, 2)
        Write-Host "  SQLite DB: Updated $([math]::Floor($dbAge.TotalSeconds))s ago, Size=$dbSize MB" -ForegroundColor Gray
    } else {
        Write-Host "  SQLite DB: Not found" -ForegroundColor Yellow
    }
    
    Write-Host ""
}

function Check-OrderExecution {
    Write-Host "[Order Execution]" -ForegroundColor Yellow
    
    $execLogDir = "$outputDir\ready\execlog\BTCUSDT"
    if (Test-Path $execLogDir) {
        $execLogFiles = Get-ChildItem -Path $execLogDir -Filter "*.jsonl" -ErrorAction SilentlyContinue | 
            Sort-Object LastWriteTime -Descending
        
        if ($execLogFiles) {
            $latestExecLog = $execLogFiles[0]
            $fileAge = (Get-Date) - $latestExecLog.LastWriteTime
            
            Write-Host "  Latest Exec Log: $($latestExecLog.Name)" -ForegroundColor Gray
            Write-Host "  Last Update: $([math]::Floor($fileAge.TotalSeconds))s ago" -ForegroundColor Gray
            
            try {
                $lines = Get-Content $latestExecLog.FullName -Tail 50 -ErrorAction SilentlyContinue
                $submitCount = ($lines | Select-String -Pattern '"event":"submit"' | Measure-Object).Count
                $filledCount = ($lines | Select-String -Pattern '"status":"FILLED"|"event":"filled"' | Measure-Object).Count
                $rejectedCount = ($lines | Select-String -Pattern '"status":"REJECTED"|"event":"rejected"' | Measure-Object).Count
                
                Write-Host "  Last 50 records: Submit=$submitCount, Filled=$filledCount, Rejected=$rejectedCount" -ForegroundColor Gray
            } catch {
                Write-Host "  Cannot read exec log stats" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  No exec log files found" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Exec log directory not found" -ForegroundColor Yellow
    }
    
    Write-Host ""
}

function Check-SDKStatus {
    Write-Host "[SDK Status]" -ForegroundColor Yellow
    
    $strategyLog = Get-ChildItem -Path "$logDir\strategy" -Filter "*stderr*.log" -ErrorAction SilentlyContinue | 
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    
    if ($strategyLog) {
        try {
            # 检查最近的SDK启用日志
            $logContent = Get-Content $strategyLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue
            $sdkLog = $logContent | Select-String -Pattern "Using python-binance SDK" | Select-Object -Last 1
            
            if ($sdkLog) {
                Write-Host "  [OK] SDK Enabled: $($sdkLog.Line.Trim())" -ForegroundColor Green
            } else {
                # 检查是否有SDK订单提交成功
                $sdkOrders = $logContent | Select-String -Pattern "Order submitted \(SDK\)" | Measure-Object
                if ($sdkOrders.Count -gt 0) {
                    Write-Host "  [OK] SDK Active: $($sdkOrders.Count) orders submitted via SDK" -ForegroundColor Green
                } else {
                    Write-Host "  [WARN] SDK log not found" -ForegroundColor Yellow
                }
            }
        } catch {
            Write-Host "  Cannot read strategy log" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Strategy log file not found" -ForegroundColor Yellow
    }
    
    Write-Host ""
}

$iteration = 0
while ($true) {
    $iteration++
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    Write-Host "`n[$timestamp] Check #$iteration" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    
    Check-ProcessStatus
    Check-SignalStatus
    Check-OrderExecution
    Check-SDKStatus
    
    if (-not $Continuous) {
        Write-Host "`nTip: Use -Continuous to monitor continuously" -ForegroundColor Gray
        break
    }
    
    Write-Host "Waiting $CheckInterval seconds..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $CheckInterval
}

Write-Host "`n========== Monitor End ==========" -ForegroundColor Cyan
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Yellow
Write-Host "  View logs: Get-Content logs\strategy\strategy_stderr.log -Tail 50" -ForegroundColor White
Write-Host "  Verify test: python scripts\t3_live_small_flow_verify.py --output-dir runtime\t3_live_small_flow" -ForegroundColor White
Write-Host ""
