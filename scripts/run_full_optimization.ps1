# TASK-09 完整优化执行脚本（阶段1 + 阶段2）
# 使用方法: .\scripts\run_full_optimization.ps1

Write-Host "========================================"
Write-Host "TASK-09 完整优化执行"
Write-Host "========================================"
Write-Host ""

# 阶段1优化
Write-Host "阶段1: 稳胜率 + 控回撤"
Write-Host "----------------------------------------"
$stage1Output = python scripts/run_stage1_optimization.py `
  --config config/backtest.yaml `
  --search-space tasks/TASK-09/search_space_stage1.json `
  --date 2025-11-09 `
  --symbols BTCUSDT `
  --method random `
  --max-trials 30 `
  --max-workers 2

if ($LASTEXITCODE -ne 0) {
    Write-Host "阶段1优化失败，退出码: $LASTEXITCODE"
    exit $LASTEXITCODE
}

# 找到最新的阶段1目录
$stage1Dirs = Get-ChildItem runtime/optimizer -Directory | Where-Object {$_.Name -like 'stage1_*'} | Sort-Object LastWriteTime -Descending
$latestStage1 = $stage1Dirs[0]

Write-Host ""
Write-Host "阶段1完成，最佳配置: $($latestStage1.FullName)\recommended_config.yaml"
Write-Host ""

# 检查推荐配置是否存在
$recommendedConfig = Join-Path $latestStage1.FullName "recommended_config.yaml"
if (-not (Test-Path $recommendedConfig)) {
    Write-Host "错误: 未找到推荐配置文件"
    exit 1
}

# 阶段2优化
Write-Host "阶段2: 提收益 + 控成本"
Write-Host "----------------------------------------"
$stage2Output = python scripts/run_stage2_optimization.py `
  --config $recommendedConfig `
  --search-space tasks/TASK-09/search_space_stage2.json `
  --date 2025-11-09 `
  --symbols BTCUSDT `
  --method random `
  --max-trials 20 `
  --max-workers 2 `
  --early-stop-rounds 10

if ($LASTEXITCODE -ne 0) {
    Write-Host "阶段2优化失败，退出码: $LASTEXITCODE"
    exit $LASTEXITCODE
}

# 找到最新的阶段2目录
$stage2Dirs = Get-ChildItem runtime/optimizer -Directory | Where-Object {$_.Name -like 'stage2_*'} | Sort-Object LastWriteTime -Descending
$latestStage2 = $stage2Dirs[0]

Write-Host ""
Write-Host "========================================"
Write-Host "优化完成！"
Write-Host "========================================"
Write-Host "阶段1结果: $($latestStage1.FullName)"
Write-Host "阶段2结果: $($latestStage2.FullName)"
Write-Host "最终推荐配置: $($latestStage2.FullName)\recommended_config.yaml"
Write-Host ""
Write-Host "下一步: 使用最终推荐配置运行完整回测"
Write-Host "  python scripts/replay_harness.py --config $($latestStage2.FullName)\recommended_config.yaml --date 2025-11-09 --symbols BTCUSDT,ETHUSDT --output runtime/backtest/final"

