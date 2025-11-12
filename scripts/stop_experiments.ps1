# 停止所有正在运行的实验
# 用法: .\scripts\stop_experiments.ps1

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "停止正在运行的实验" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 查找所有实验相关的Python进程
$experimentProcs = @()
$allPythonProcs = Get-Process python -ErrorAction SilentlyContinue | 
    Where-Object { $_.StartTime -gt (Get-Date).AddHours(-2) }

foreach ($proc in $allPythonProcs) {
    try {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmd) {
            if ($cmd -like "*replay_harness*" -or 
                $cmd -like "*run_f_experiments*" -or 
                $cmd -like "*run_stage*optimization*") {
                $experimentProcs += $proc
            }
        }
    } catch {
        # 忽略错误
    }
}

if ($experimentProcs.Count -eq 0) {
    Write-Host "[INFO] 未找到正在运行的实验进程" -ForegroundColor Green
    exit 0
}

Write-Host "找到 $($experimentProcs.Count) 个实验进程:" -ForegroundColor Yellow
Write-Host ""

foreach ($proc in $experimentProcs) {
    try {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
        $shortCmd = if ($cmd) { $cmd.Substring(0, [Math]::Min(100, $cmd.Length)) } else { "N/A" }
        Write-Host "  进程ID: $($proc.Id)" -ForegroundColor Cyan
        Write-Host "  启动时间: $($proc.StartTime)" -ForegroundColor Gray
        Write-Host "  命令: $shortCmd" -ForegroundColor Gray
        Write-Host ""
    } catch {
        Write-Host "  进程ID: $($proc.Id) (无法获取详细信息)" -ForegroundColor Yellow
    }
}

Write-Host "准备停止这些进程..." -ForegroundColor Yellow
Write-Host ""

$stoppedCount = 0
$failedCount = 0

foreach ($proc in $experimentProcs) {
    try {
        Write-Host "停止进程 $($proc.Id)..." -ForegroundColor Cyan -NoNewline
        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        Write-Host " [OK]" -ForegroundColor Green
        $stoppedCount++
    } catch {
        Write-Host " [失败: $($_.Exception.Message)]" -ForegroundColor Red
        $failedCount++
    }
}

Write-Host ""
Write-Host "等待进程完全停止..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

# 验证进程是否已停止
$remainingProcs = @()
foreach ($procId in $experimentProcs.Id) {
    $stillRunning = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($stillRunning) {
        $remainingProcs += $procId
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "停止结果" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "成功停止: $stoppedCount" -ForegroundColor Green
Write-Host "停止失败: $failedCount" -ForegroundColor $(if ($failedCount -eq 0) { "Green" } else { "Red" })

if ($remainingProcs.Count -gt 0) {
    Write-Host ""
    Write-Host "警告: 以下进程仍在运行:" -ForegroundColor Red
    foreach ($procId in $remainingProcs) {
        Write-Host "  进程ID: $procId" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "可能需要手动停止这些进程" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "所有实验进程已成功停止" -ForegroundColor Green
}

Write-Host "========================================" -ForegroundColor Cyan

