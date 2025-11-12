# 检查F系列实验输出目录
# 用法: .\scripts\check_f_experiments_output.ps1

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "F系列实验输出目录检查" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查optimizer目录
$optimizerDir = Join-Path $projectRoot "runtime\optimizer"
if (Test-Path $optimizerDir) {
    Write-Host "优化器输出目录: $optimizerDir" -ForegroundColor Green
    Write-Host ""
    
    # 获取所有stage目录
    $stageDirs = Get-ChildItem $optimizerDir -Directory -ErrorAction SilentlyContinue | 
        Where-Object { $_.Name -like "stage*" } | 
        Sort-Object LastWriteTime -Descending
    
    if ($stageDirs.Count -eq 0) {
        Write-Host "[WARN] 未找到stage目录" -ForegroundColor Yellow
    } else {
        Write-Host "找到 $($stageDirs.Count) 个stage目录:" -ForegroundColor Green
        Write-Host ""
        
        foreach ($dir in $stageDirs) {
            Write-Host "目录: $($dir.Name)" -ForegroundColor Cyan
            Write-Host "  路径: $($dir.FullName)" -ForegroundColor Gray
            Write-Host "  修改时间: $($dir.LastWriteTime)" -ForegroundColor Gray
            
            # 检查trial目录
            $trialDirs = Get-ChildItem $dir.FullName -Directory -ErrorAction SilentlyContinue | 
                Where-Object { $_.Name -like "trial_*" }
            
            if ($trialDirs.Count -gt 0) {
                Write-Host "  Trial数量: $($trialDirs.Count)" -ForegroundColor Green
                
                # 检查最新的trial
                $latestTrial = $trialDirs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                Write-Host "  最新Trial: $($latestTrial.Name)" -ForegroundColor Gray
                
                # 检查trial下的backtest目录
                $backtestDirs = Get-ChildItem $latestTrial.FullName -Directory -ErrorAction SilentlyContinue | 
                    Where-Object { $_.Name -like "backtest_*" }
                
                if ($backtestDirs.Count -gt 0) {
                    Write-Host "  Backtest目录: $($backtestDirs.Count) 个" -ForegroundColor Gray
                }
            } else {
                Write-Host "  [WARN] 未找到trial目录" -ForegroundColor Yellow
            }
            
            # 检查结果文件
            $resultsFile = Join-Path $dir.FullName "trial_results.json"
            if (Test-Path $resultsFile) {
                Write-Host "  结果文件: trial_results.json (存在)" -ForegroundColor Green
            } else {
                Write-Host "  结果文件: trial_results.json (不存在)" -ForegroundColor Yellow
            }
            
            $csvFile = Join-Path $dir.FullName "trial_results.csv"
            if (Test-Path $csvFile) {
                Write-Host "  CSV文件: trial_results.csv (存在)" -ForegroundColor Green
            }
            
            Write-Host ""
        }
    }
} else {
    Write-Host "[ERROR] 优化器输出目录不存在: $optimizerDir" -ForegroundColor Red
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "检查完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

