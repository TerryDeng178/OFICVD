# P0 StrategyMode 修复验证脚本
# 快速验证关键修复是否落地

Write-Host "=========================================="
Write-Host "P0 StrategyMode 修复验证"
Write-Host "=========================================="
Write-Host ""

# 1. 检查 CoreAlgo 默认值
Write-Host "[1/5] 检查 CoreAlgo Schedule 默认值..."
try {
    $result = python -c @"
from alpha_core.signals.core_algo import CoreAlgorithm
algo = CoreAlgorithm(config={})
if hasattr(algo, '_strategy_mode_config') and algo._strategy_mode_config:
    schedule = algo._strategy_mode_config.get('strategy', {}).get('triggers', {}).get('schedule', {})
    enabled = schedule.get('enabled', False)
    active_windows = schedule.get('active_windows', None)
    if enabled and active_windows == []:
        print('OK: Schedule 默认开启，空窗口=全天有效')
    else:
        print(f'FAIL: enabled={enabled}, active_windows={active_windows}')
else:
    print('SKIP: 无 strategy_mode 配置（可能未提供配置）')
"@
    Write-Host $result
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# 2. 检查 enabled_weekdays 空数组语义
Write-Host "[2/5] 检查 enabled_weekdays 空数组语义..."
try {
    $result = python -c @"
from alpha_core.risk.strategy_mode import StrategyModeManager
cfg = {
    'strategy': {
        'mode': 'auto',
        'triggers': {
            'schedule': {
                'enabled': True,
                'enabled_weekdays': [],
                'active_windows': []
            }
        }
    }
}
m = StrategyModeManager(runtime_cfg=cfg)
result = m.check_schedule_active()
if result:
    print('OK: enabled_weekdays=[] 视为所有星期启用')
else:
    print('FAIL: enabled_weekdays=[] 返回 False')
"@
    Write-Host $result
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# 3. 检查重复代码
Write-Host "[3/5] 检查重复代码..."
try {
    $content = Get-Content "src/alpha_core/signals/core_algo.py" -Raw
    $createCount = ([regex]::Matches($content, "def _create_market_activity")).Count
    $inferCount = ([regex]::Matches($content, "def _infer_regime")).Count
    if ($createCount -eq 1 -and $inferCount -eq 1) {
        Write-Host "OK: 无重复方法定义"
    } else {
        Write-Host "FAIL: _create_market_activity 出现 $createCount 次, _infer_regime 出现 $inferCount 次" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# 4. 检查 FeaturePipe 语法
Write-Host "[4/5] 检查 FeaturePipe 语法..."
try {
    $result = python -c @"
try:
    from alpha_core.microstructure.feature_pipe import FeaturePipe
    pipe = FeaturePipe()
    print('OK: FeaturePipe 能正常导入和实例化')
except SyntaxError as e:
    print(f'FAIL: 语法错误 - {e}')
except Exception as e:
    print(f'ERROR: {e}')
"@
    Write-Host $result
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# 5. 检查 MCP 薄壳使用包内 CoreAlgorithm
Write-Host "[5/5] 检查 MCP 薄壳导入..."
try {
    $content = Get-Content "mcp/signal_server/app.py" -Raw
    if ($content -match "from alpha_core.signals import CoreAlgorithm") {
        Write-Host "OK: 使用包内 alpha_core.signals.CoreAlgorithm"
    } else {
        Write-Host "FAIL: 未找到正确的导入语句" -ForegroundColor Red
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=========================================="
Write-Host "验证完成"
Write-Host "=========================================="

