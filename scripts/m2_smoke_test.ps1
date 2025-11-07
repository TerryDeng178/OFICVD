# M2 smoke test script (PowerShell)
# Validate FeaturePipe and CORE_ALGO end-to-end

# strict error handling
$ErrorActionPreference = "Stop"

# locate project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$RunId = if ($env:RUN_ID) { $env:RUN_ID } else { (Get-Date -Format 'yyyyMMdd_HHmmss') }
$OutputRoot = if ($env:OUTPUT_DIR) { $env:OUTPUT_DIR } else { "./runtime" }
$OutputDir = Join-Path $OutputRoot (Join-Path "runs" $RunId)
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

Write-Host "=========================================="
Write-Host "M2 Smoke Test - FeaturePipe + CORE_ALGO"
Write-Host "=========================================="
Write-Host "Project root: $ProjectRoot"
Write-Host "Run ID: $RunId"
Write-Host "Output root: $OutputRoot"
Write-Host "Run directory: $OutputDir"
Write-Host ""

# ensure python exists
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python version: $pythonVersion"
} catch {
    Write-Host "ERROR: python not found" -ForegroundColor Red
    Write-Host "Please install Python >= 3.10"
    exit 1
}

# set test parameters
function Resolve-InputDir {
    param(
        [string]$Override
    )

    if ($Override) {
        return $Override
    }

    $Candidates = @(
        (Join-Path $ProjectRoot "deploy/data/ofi_cvd/raw"),
        (Join-Path $ProjectRoot "deploy/data/ofi_cvd/preview"),
        (Join-Path $ProjectRoot "deploy/data/ofi_cvd")
    )

    foreach ($Candidate in $Candidates) {
        $Resolved = Resolve-Path -Path $Candidate -ErrorAction SilentlyContinue
        if ($Resolved) {
            return $Resolved.Path
        }
    }

    return (Join-Path $ProjectRoot "deploy/data/ofi_cvd/raw")
}

function Convert-PreviewFeatures {
    param(
        [string]$PreviewRoot,
        [string[]]$Symbols,
        [string]$OutputFile
    )

    if (-not (Test-Path $PreviewRoot)) {
        Write-Host "ERROR: preview root not found: $PreviewRoot" -ForegroundColor Red
        return $false
    }

    $ConvertScript = Join-Path $ProjectRoot "tools/convert_preview_features.py"
    if (-not (Test-Path $ConvertScript)) {
        Write-Host "ERROR: missing tool script $ConvertScript" -ForegroundColor Red
        return $false
    }

    $ArgsList = @($ConvertScript, "--preview-root", $PreviewRoot, "--output", $OutputFile, "--symbols") + $Symbols
    try {
        python @ArgsList | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: convert_preview_features failed (exit $LASTEXITCODE)" -ForegroundColor Red
            return $false
        }
        return $true
    } catch {
        Write-Host "ERROR: preview conversion failed: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

$InputDir = Resolve-InputDir -Override $env:INPUT_DIR
$Symbols = if ($env:SYMBOLS) {
    $env:SYMBOLS -split '[,\s]+' | Where-Object { $_ }
} else {
    @("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT")
}
$ConfigFile = if ($env:CONFIG_FILE) { $env:CONFIG_FILE } else { "./config/defaults.smoke.yaml" }

Write-Host "Parameters:"
Write-Host "  - input dir: $InputDir"
Write-Host "  - output dir: $OutputDir"
Write-Host "  - symbols: $($Symbols -join ', ')"
Write-Host "  - config: $ConfigFile"
Write-Host ""

# ensure output directory exists
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# Step 1
Write-Host "=========================================="
Write-Host "Step 1: run FeaturePipe"
Write-Host "=========================================="
Write-Host ""

$FeaturesSource = Join-Path $OutputDir "features.jsonl"
$FeaturesFile = Join-Path $OutputDir "features_$RunId.jsonl"

try {
    python -m alpha_core.microstructure.feature_pipe `
        --input $InputDir `
        --sink jsonl `
        --out $FeaturesSource `
        --symbols $Symbols `
        --config $ConfigFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: FeaturePipe failed (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: FeaturePipe execution failed" -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit 1
}

if ((Test-Path $FeaturesSource -PathType Leaf)) {
    Move-Item -Path $FeaturesSource -Destination $FeaturesFile -Force
}

if (-not (Test-Path $FeaturesFile -PathType Leaf)) {
    Write-Host "ERROR: Feature file not generated: $FeaturesFile" -ForegroundColor Red
    exit 1
}

$FeatureCount = (Get-Content $FeaturesFile | Measure-Object -Line).Lines
Write-Host "Feature rows: $FeatureCount"

if ($FeatureCount -eq 0) {
    Write-Host "Warning: no feature rows produced, attempting preview fallback" -ForegroundColor Yellow
    $PreviewRoot = Join-Path $ProjectRoot "deploy/data/ofi_cvd/preview"
    $Converted = Convert-PreviewFeatures -PreviewRoot $PreviewRoot -Symbols $Symbols -OutputFile $FeaturesFile
    if (-not $Converted) {
        Write-Host "ERROR: unable to obtain features from preview" -ForegroundColor Red
        exit 1
    }
    $FeatureCount = (Get-Content $FeaturesFile | Measure-Object -Line).Lines
    if ($FeatureCount -eq 0) {
        Write-Host "ERROR: preview fallback still produced zero rows" -ForegroundColor Red
        exit 1
    }
    Write-Host "Preview fallback produced rows: $FeatureCount" -ForegroundColor Green
}

# Step 1.5: prepend warmup history
Write-Host ""
Write-Host "=========================================="
Write-Host "Step 1.5: prepend warmup history (optional)"
Write-Host "=========================================="
Write-Host ""

$PreviewRoot = Join-Path $ProjectRoot "deploy/data/ofi_cvd/preview"
if ((Test-Path $PreviewRoot -PathType Container) -and (Test-Path $FeaturesFile -PathType Leaf)) {
    try {
        python (Join-Path $ProjectRoot "tools/prepend_warmup_features.py") `
            --features $FeaturesFile `
            --preview-root $PreviewRoot `
            --symbols $Symbols `
            --warmup-minutes 3 `
            --output $FeaturesFile
        if ($LASTEXITCODE -eq 0) {
            $FeatureCount = (Get-Content $FeaturesFile | Measure-Object -Line).Lines
            Write-Host "Warmup prepended, total rows: $FeatureCount" -ForegroundColor Cyan
        }
    } catch {
        Write-Host "WARNING: warmup prepend failed, continuing without warmup" -ForegroundColor Yellow
    }
}

# Step 2
Write-Host ""
Write-Host "=========================================="
Write-Host "Step 2: validate feature schema"
Write-Host "=========================================="
Write-Host ""

$ValidateScript = Join-Path $ProjectRoot "tools/validate_features.py"
try {
    python $ValidateScript --features $FeaturesFile --limit 5
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: feature validation failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: feature validation failed" -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit 1
}

# Step 3
Write-Host ""
Write-Host "=========================================="
Write-Host "Step 3: run CORE_ALGO"
Write-Host "=========================================="
Write-Host ""

if (-not $env:V13_REPLAY_MODE) {
    $env:V13_REPLAY_MODE = "1"
}

$coreStart = Get-Date
python -m mcp.signal_server.app `
        --config $ConfigFile `
        --input $FeaturesFile `
        --sink jsonl `
        --out $OutputDir
$coreEnd = Get-Date

# summarize outputs
Write-Host ""
Write-Host "--- Signal output summary (JSONL) ---"
$SignalDir = Join-Path $OutputDir "ready/signal"
$SummaryJson = Join-Path $OutputDir "smoke_summary.json"
$ConfirmDir = Join-Path $OutputDir "ready/signal_confirm"
$SummaryData = $null
if (Test-Path $SignalDir) {
    try {
        python (Join-Path $ProjectRoot "tools/summarize_signals.py") --signal-dir $SignalDir --summary-json $SummaryJson
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARNING: summarize_signals reported an issue (exit $LASTEXITCODE)" -ForegroundColor Yellow
        }
        if (Test-Path $SummaryJson -PathType Leaf) {
            $SummaryData = Get-Content $SummaryJson -Raw | ConvertFrom-Json
            Write-Host "Summary metrics: confirm=$($SummaryData.confirm) suppressed=$($SummaryData.suppressed) gated=$($SummaryData.gated)" -ForegroundColor Cyan
            if ($SummaryData.guard_reasons) {
                Write-Host "  guard_reason top5:" -ForegroundColor Cyan
                foreach ($item in $SummaryData.guard_reasons | Select-Object -First 5) {
                    Write-Host "    $($item[0]) : $($item[1])"
                }
            }
            if ($SummaryData.guard_symbol_regime) {
                Write-Host "  guard by symbol/regime top5:" -ForegroundColor Cyan
                foreach ($entry in $SummaryData.guard_symbol_regime | Select-Object -First 5) {
                    Write-Host "    $($entry[0]) / $($entry[1]) / $($entry[2]) : $($entry[3])"
                }
            }
            if ($SummaryData.regime_distribution) {
                Write-Host "  regime distribution:" -ForegroundColor Cyan
                $regimeDist = $SummaryData.regime_distribution.PSObject.Properties | Sort-Object Value -Descending | Select-Object -First 5
                foreach ($regime in $regimeDist) {
                    Write-Host "    $($regime.Name): $($regime.Value)"
                }
            }
            if ($SummaryData.regime_by_symbol) {
                Write-Host "  regime by symbol (top3):" -ForegroundColor Cyan
                $symbols = $SummaryData.regime_by_symbol.PSObject.Properties | Select-Object -First 3
                foreach ($symProp in $symbols) {
                    $sym = $symProp.Name
                    $regimes = $symProp.Value.PSObject.Properties | Sort-Object Value -Descending | Select-Object -First 3
                    $regimeDict = @{}
                    foreach ($r in $regimes) {
                        $regimeDict[$r.Name] = $r.Value
                    }
                    Write-Host "    $sym : $($regimeDict | ConvertTo-Json -Compress)"
                }
            }
            if ($SummaryData.sample_record) {
                Write-Host "  sample record (first row):" -ForegroundColor Cyan
                $sampleJson = $SummaryData.sample_record | ConvertTo-Json -Depth 3 -Compress
                $sampleLines = $sampleJson -split "`n" | Select-Object -First 8
                foreach ($line in $sampleLines) {
                    Write-Host "    $line"
                }
            }
            if ($SummaryData.heatmap) {
                Write-Host "  guard heatmap (top5 symbol/regime combinations):" -ForegroundColor Cyan
                $heatmapItems = @()
                foreach ($key in $SummaryData.heatmap.PSObject.Properties.Name) {
                    $reasons = $SummaryData.heatmap.$key
                    $total = ($reasons.PSObject.Properties.Value | Measure-Object -Sum).Sum
                    $topReason = $reasons.PSObject.Properties | Sort-Object Value -Descending | Select-Object -First 1
                    $heatmapItems += [PSCustomObject]@{Key=$key; Total=$total; TopReason=$topReason.Name; TopCount=$topReason.Value}
                }
                $heatmapItems | Sort-Object Total -Descending | Select-Object -First 5 | ForEach-Object {
                    Write-Host "    $($_.Key): total=$($_.Total), top_reason=$($_.TopReason)($($_.TopCount))"
                }
            }
            if ($SummaryData.min_ts -ne $null -and $SummaryData.max_ts -ne $null) {
                $min = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$SummaryData.min_ts).UtcDateTime
                $max = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$SummaryData.max_ts).UtcDateTime
                Write-Host "  time range (utc): $($min.ToString('o')) -> $($max.ToString('o'))" -ForegroundColor Cyan
            }
            if ([int]$SummaryData.confirm -le 0) {
                Write-Host "WARNING: no confirmed signals produced" -ForegroundColor Yellow
                $ExitCode = 2
            }
            elseif (-not (Test-Path $ConfirmDir -PathType Container)) {
                New-Item -ItemType Directory -Force -Path $ConfirmDir | Out-Null
                python (Join-Path $ProjectRoot "tools/filter_confirm_signals.py") --source $SignalDir --target $ConfirmDir
            } else {
                python (Join-Path $ProjectRoot "tools/filter_confirm_signals.py") --source $SignalDir --target $ConfirmDir
            }
        } else {
            Write-Host "WARNING: summary JSON not generated" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARNING: failed to summarize signals ($($_.Exception.Message))" -ForegroundColor Yellow
    }
} else {
    Write-Host "signal directory missing: $SignalDir" -ForegroundColor Yellow
}

$durationSec = [Math]::Max(($coreEnd - $coreStart).TotalSeconds, 1)
if ($FeatureCount -gt 0) {
    $throughput = [Math]::Round($FeatureCount / $durationSec, 2)
    Write-Host "throughput: $throughput rows/sec" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "--- SQLite sink verification (optional) ---"
if (Test-Path $FeaturesFile -PathType Leaf) {
    $SqliteDb = Join-Path $OutputDir "signals.db"
    try {
        python -m mcp.signal_server.app `
            --config $ConfigFile `
            --input $FeaturesFile `
            --sink sqlite `
            --out $OutputDir 2>&1 | Out-Null
        if (Test-Path $SqliteDb -PathType Leaf) {
            $dbPath = $SqliteDb
            python -c @"
import sqlite3
import os
db_path = r'$dbPath'
if os.path.exists(db_path):
    con = sqlite3.connect(db_path)
    journal_mode = con.execute('PRAGMA journal_mode;').fetchone()[0]
    confirm_count = con.execute('SELECT COUNT(*) FROM signals WHERE confirm=1;').fetchone()[0]
    total_count = con.execute('SELECT COUNT(*) FROM signals;').fetchone()[0]
    max_ts_result = con.execute('SELECT MAX(ts_ms) FROM signals;').fetchone()
    max_ts = max_ts_result[0] if max_ts_result and max_ts_result[0] else None
    recent_confirm = 0
    if max_ts:
        recent_confirm = con.execute('SELECT COUNT(*) FROM signals WHERE confirm=1 AND ts_ms>=?;', (max_ts - 3600000,)).fetchone()[0]
    print('SQLite verification:')
    print('  journal_mode: {}'.format(journal_mode))
    print('  total signals: {}'.format(total_count))
    print('  confirmed signals: {}'.format(confirm_count))
    print('  confirmed in last hour: {}'.format(recent_confirm))
    con.close()
else:
    print('WARNING: SQLite database not found at {}'.format(db_path))
"@
        } else {
            Write-Host "WARNING: SQLite database not generated at $SqliteDb" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARNING: SQLite sink test failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=========================================="
Write-Host "M2 smoke test finished"
Write-Host "=========================================="
Write-Host "features file: $FeaturesFile"
Write-Host "feature rows: $FeatureCount"
Write-Host "run directory: $OutputDir"
Write-Host ""

exit $ExitCode

