# T08: 24小时回测 + 详细报告生成脚本
# 使用真实历史24小时数据进行回测，并生成详细报告

param(
    [string]$InputDir = "./deploy/data/ofi_cvd",
    [string]$Date = "",  # 如果为空，自动查找最新日期
    [string]$Symbols = "BTCUSDT",  # 交易对，多个用逗号分隔
    [string]$Kinds = "features",  # 数据种类：features（快速路径）或 prices,orderbook（完整路径）
    [string]$Config = "./config/backtest.yaml",
    [string]$OutputBase = "./runtime/backtest",
    [switch]$ShowReport = $true  # 是否显示详细报告
)

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "T08: 24小时回测 + 详细报告" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. 查找可用数据日期
if ([string]::IsNullOrEmpty($Date)) {
    Write-Host "正在查找可用数据..." -ForegroundColor Yellow
    
    # 优先查找 ready 目录
    $readyDir = Join-Path $InputDir "ready"
    if (Test-Path $readyDir) {
        $dates = Get-ChildItem -Path $readyDir -Directory | 
            Where-Object { $_.Name -like "date=*" } | 
            ForEach-Object { $_.Name -replace "date=", "" } | 
            Sort-Object -Descending
        
        if ($dates) {
            $Date = $dates[0]
            Write-Host "找到最新数据日期: $Date" -ForegroundColor Green
        }
    }
    
    # 如果 ready 目录没有，查找 preview 目录
    if ([string]::IsNullOrEmpty($Date)) {
        $previewDir = Join-Path $InputDir "preview"
        if (Test-Path $previewDir) {
            $dates = Get-ChildItem -Path $previewDir -Directory | 
                Where-Object { $_.Name -like "date=*" } | 
                ForEach-Object { $_.Name -replace "date=", "" } | 
                Sort-Object -Descending
            
            if ($dates) {
                $Date = $dates[0]
                Write-Host "在preview目录找到数据日期: $Date" -ForegroundColor Yellow
            }
        }
    }
    
    if ([string]::IsNullOrEmpty($Date)) {
        Write-Host "错误: 未找到可用数据" -ForegroundColor Red
        Write-Host "请检查数据目录: $InputDir" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "回测配置:" -ForegroundColor Cyan
Write-Host "  输入目录: $InputDir" -ForegroundColor Gray
Write-Host "  数据日期: $Date" -ForegroundColor Gray
Write-Host "  交易对: $Symbols" -ForegroundColor Gray
Write-Host "  数据种类: $Kinds" -ForegroundColor Gray
Write-Host "  配置文件: $Config" -ForegroundColor Gray
Write-Host "  输出目录: $OutputBase" -ForegroundColor Gray
Write-Host "  时长: 24小时 (1440分钟)" -ForegroundColor Gray
Write-Host ""

# 2. 运行回测
Write-Host "开始运行24小时回测..." -ForegroundColor Yellow
Write-Host ""

$runId = "backtest_24h_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$outputDir = Join-Path $OutputBase $runId

# 构建回测命令
$backtestCmd = @(
    "python", "scripts/replay_harness.py",
    "--input", $InputDir,
    "--date", $Date,
    "--symbols", $Symbols,
    "--kinds", $Kinds,
    "--minutes", "1440",  # 24小时 = 1440分钟
    "--config", $Config,
    "--output", $outputDir
)

Write-Host "执行命令:" -ForegroundColor Cyan
Write-Host "  $($backtestCmd -join ' ')" -ForegroundColor Gray
Write-Host ""

# 运行回测
$startTime = Get-Date
$process = Start-Process -FilePath "python" -ArgumentList $backtestCmd[1..($backtestCmd.Length-1)] -NoNewWindow -Wait -PassThru
$endTime = Get-Date
$duration = $endTime - $startTime

if ($process.ExitCode -ne 0) {
    Write-Host ""
    Write-Host "回测失败！退出码: $($process.ExitCode)" -ForegroundColor Red
    exit $process.ExitCode
}

Write-Host ""
Write-Host "回测完成！耗时: $($duration.TotalSeconds.ToString('F2')) 秒" -ForegroundColor Green
Write-Host ""

# 3. 查找实际输出目录（replay_harness会在output下创建run_id子目录）
$actualOutputDir = $outputDir
$subdirs = Get-ChildItem -Path $outputDir -Directory | Where-Object { $_.Name -like "backtest_*" }
if ($subdirs) {
    $actualOutputDir = $subdirs[0].FullName
    Write-Host "实际输出目录: $actualOutputDir" -ForegroundColor Gray
}

Write-Host ""
Write-Host "输出文件:" -ForegroundColor Cyan
Write-Host "  Run ID: $runId" -ForegroundColor Gray
Write-Host "  运行清单: $actualOutputDir\run_manifest.json" -ForegroundColor Gray
Write-Host "  交易记录: $actualOutputDir\trades.jsonl" -ForegroundColor Gray
Write-Host "  每日PnL: $actualOutputDir\pnl_daily.jsonl" -ForegroundColor Gray
Write-Host "  性能指标: $actualOutputDir\metrics.json" -ForegroundColor Gray
Write-Host "  信号输出: $actualOutputDir\signals\" -ForegroundColor Gray
Write-Host ""

# 4. 生成详细报告
if ($ShowReport) {
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host "详细报告" -ForegroundColor Cyan
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host ""
    
    # 使用 show_backtest_results.py 生成报告
    python scripts/show_backtest_results.py $actualOutputDir
    
    Write-Host ""
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host "报告生成完成" -ForegroundColor Cyan
    Write-Host "========================================================================" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "提示: 可以使用以下命令查看报告:" -ForegroundColor Yellow
Write-Host "  python scripts/show_backtest_results.py `"$actualOutputDir`"" -ForegroundColor Gray
Write-Host ""

exit 0

