# TASK-07A 双Sink测试监控脚本
# 监控60分钟LIVE模式测试进度

param(
    [int]$CheckInterval = 60,  # 检查间隔（秒）
    [switch]$WaitForCompletion  # 等待测试完成
)

$startTime = Get-Date
$testDuration = 60 * 60  # 60分钟 = 3600秒

Write-Host "=== TASK-07A 双Sink测试监控 ===" -ForegroundColor Green
Write-Host ""
Write-Host "测试开始时间: $startTime" -ForegroundColor Cyan
Write-Host "预计结束时间: $($startTime.AddSeconds($testDuration))" -ForegroundColor Cyan
Write-Host "检查间隔: $CheckInterval 秒" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    $elapsed = (Get-Date) - $startTime
    $remaining = $testDuration - $elapsed.TotalSeconds
    
    if ($remaining -le 0) {
        Write-Host "`n=== 测试时间已到 ===" -ForegroundColor Green
        break
    }
    
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 已运行: $([math]::Floor($elapsed.TotalMinutes)) 分钟 | 剩余: $([math]::Ceiling($remaining / 60)) 分钟" -ForegroundColor Yellow
    
    # 检查进程状态
    $pythonProcesses = Get-Process | Where-Object { $_.ProcessName -eq "python" -and $_.MainWindowTitle -eq "" }
    if ($pythonProcesses) {
        Write-Host "  Python进程数: $($pythonProcesses.Count)" -ForegroundColor Gray
    }
    
    # 检查最新数据文件
    $latestJsonl = Get-ChildItem -Path "runtime\ready\signal" -Recurse -Filter "*.jsonl" -ErrorAction SilentlyContinue | 
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestJsonl) {
        $fileAge = (Get-Date) - $latestJsonl.LastWriteTime
        Write-Host "  最新JSONL文件: $($latestJsonl.Name) (年龄: $([math]::Floor($fileAge.TotalSeconds))秒)" -ForegroundColor Gray
    }
    
    # 检查SQLite数据库
    if (Test-Path "runtime\signals.db") {
        $dbAge = (Get-Date) - (Get-Item "runtime\signals.db").LastWriteTime
        Write-Host "  SQLite数据库最后更新: $([math]::Floor($dbAge.TotalSeconds))秒前" -ForegroundColor Gray
    }
    
    # 检查最新日志
    $latestLog = Get-ChildItem -Path "logs" -Filter "task07a_dual_sink_*.log" -ErrorAction SilentlyContinue | 
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        $logLines = Get-Content $latestLog.FullName -Tail 3 -ErrorAction SilentlyContinue
        if ($logLines) {
            Write-Host "  最新日志: $($logLines[-1])" -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    
    if (-not $WaitForCompletion) {
        break
    }
    
    Start-Sleep -Seconds $CheckInterval
}

Write-Host "`n=== 监控结束 ===" -ForegroundColor Green
Write-Host ""
Write-Host "下一步操作:" -ForegroundColor Yellow
Write-Host "  1. 检查测试结果" -ForegroundColor White
Write-Host "  2. 运行等价性测试" -ForegroundColor White
Write-Host ""

