# 检查正在运行的实验
# 用法: .\scripts\check_running_experiments.ps1

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "检查正在运行的实验" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查Python进程
Write-Host "1. 检查Python进程（最近2小时内启动）" -ForegroundColor Yellow
Write-Host ""

$pythonProcs = Get-Process python -ErrorAction SilentlyContinue | 
    Where-Object { $_.StartTime -gt (Get-Date).AddHours(-2) }

if ($pythonProcs.Count -eq 0) {
    Write-Host "  [INFO] 没有找到最近2小时内启动的Python进程" -ForegroundColor Gray
} else {
    Write-Host "  找到 $($pythonProcs.Count) 个Python进程:" -ForegroundColor Green
    Write-Host ""
    
    $experimentProcs = @()
    foreach ($proc in $pythonProcs) {
        try {
            $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmd) {
                $isExperiment = $false
                $experimentType = "其他"
                
                if ($cmd -like "*run_f_experiments*") {
                    $isExperiment = $true
                    $experimentType = "F系列实验"
                } elseif ($cmd -like "*run_stage*optimization*") {
                    $isExperiment = $true
                    $experimentType = "优化实验"
                } elseif ($cmd -like "*replay_harness*") {
                    $isExperiment = $true
                    $experimentType = "回测"
                    
                    # 提取stage和trial信息
                    if ($cmd -match "stage(\d+)_(\d{8}_\d{6})") {
                        $stage = "Stage$($matches[1])"
                        $timestamp = $matches[2]
                    } elseif ($cmd -match "trial_(\d+)") {
                        $trial = $matches[1]
                    }
                }
                
                if ($isExperiment) {
                    $experimentProcs += [PSCustomObject]@{
                        Id = $proc.Id
                        StartTime = $proc.StartTime
                        Type = $experimentType
                        CommandLine = $cmd.Substring(0, [Math]::Min(100, $cmd.Length))
                    }
                }
            }
        } catch {
            # 忽略错误
        }
    }
    
    if ($experimentProcs.Count -gt 0) {
        $experimentProcs | Format-Table -AutoSize
    } else {
        Write-Host "  [INFO] 没有找到实验相关的Python进程" -ForegroundColor Gray
    }
}

Write-Host ""

# 2. 检查输出目录更新
Write-Host "2. 检查输出目录（最近10分钟内更新）" -ForegroundColor Yellow
Write-Host ""

$recentDirs = Get-ChildItem runtime\optimizer -Directory -ErrorAction SilentlyContinue | 
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-10) } | 
    Sort-Object LastWriteTime -Descending

if ($recentDirs.Count -eq 0) {
    Write-Host "  [INFO] 最近10分钟内没有更新的目录" -ForegroundColor Gray
} else {
    Write-Host "  找到 $($recentDirs.Count) 个最近更新的目录:" -ForegroundColor Green
    Write-Host ""
    
    foreach ($dir in $recentDirs) {
        Write-Host "  目录: $($dir.Name)" -ForegroundColor Cyan
        Write-Host "    路径: $($dir.FullName)" -ForegroundColor Gray
        Write-Host "    最后修改: $($dir.LastWriteTime)" -ForegroundColor Gray
        
        # 检查trial数量
        $trials = Get-ChildItem $dir.FullName -Directory -Filter "trial_*" -ErrorAction SilentlyContinue
        if ($trials) {
            Write-Host "    Trial数量: $($trials.Count)" -ForegroundColor Green
            
            # 检查最新trial
            $latestTrial = $trials | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latestTrial) {
                $timeSinceUpdate = (Get-Date) - $latestTrial.LastWriteTime
                Write-Host "    最新Trial: $($latestTrial.Name)" -ForegroundColor Yellow
                Write-Host "    最新更新: $($latestTrial.LastWriteTime) ($([math]::Round($timeSinceUpdate.TotalMinutes, 1)) 分钟前)" -ForegroundColor Gray
                
                # 检查是否有backtest目录
                $backtestDirs = Get-ChildItem $latestTrial.FullName -Directory -Filter "backtest_*" -ErrorAction SilentlyContinue
                if ($backtestDirs) {
                    Write-Host "    Backtest目录: $($backtestDirs.Count) 个" -ForegroundColor Green
                }
            }
        }
        Write-Host ""
    }
}

Write-Host ""

# 3. 检查F系列实验特定目录
Write-Host "3. 检查F系列实验目录" -ForegroundColor Yellow
Write-Host ""

$f2Dirs = Get-ChildItem runtime\optimizer -Directory -ErrorAction SilentlyContinue | 
    Where-Object { $_.Name -like "stage2_*" } | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -First 3

$f3Dirs = Get-ChildItem runtime\optimizer -Directory -ErrorAction SilentlyContinue | 
    Where-Object { $_.Name -like "stage1_*" } | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -First 3

if ($f2Dirs.Count -gt 0) {
    Write-Host "  最新Stage2目录（F2/F4）:" -ForegroundColor Green
    $f2Dirs | ForEach-Object {
        $timeSince = (Get-Date) - $_.LastWriteTime
        Write-Host "    $($_.Name) - $([math]::Round($timeSince.TotalMinutes, 1)) 分钟前" -ForegroundColor Gray
    }
} else {
    Write-Host "  [INFO] 未找到Stage2目录" -ForegroundColor Gray
}

Write-Host ""

if ($f3Dirs.Count -gt 0) {
    Write-Host "  最新Stage1目录（F3）:" -ForegroundColor Green
    $f3Dirs | ForEach-Object {
        $timeSince = (Get-Date) - $_.LastWriteTime
        Write-Host "    $($_.Name) - $([math]::Round($timeSince.TotalMinutes, 1)) 分钟前" -ForegroundColor Gray
    }
} else {
    Write-Host "  [INFO] 未找到Stage1目录" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "检查完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

