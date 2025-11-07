#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# M2 smoke test script for FeaturePipe + CORE_ALGO

set -euo pipefail

# locate project root
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
OUTPUT_ROOT="${OUTPUT_DIR:-./runtime}"
OUTPUT_DIR="$OUTPUT_ROOT/runs/$RUN_ID"
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "M2 Smoke Test - FeaturePipe + CORE_ALGO"
echo "=========================================="
echo "Project root: $ROOT"
echo "Run ID: $RUN_ID"
echo "Output root: $OUTPUT_ROOT"
echo "Run directory: $OUTPUT_DIR"
echo ""

# ensure python exists
if ! command -v python >/dev/null 2>&1; then
    echo "ERROR: python not found"
    echo "Please install Python >= 3.10"
    exit 1
fi

# parameters
if [ -n "${INPUT_DIR:-}" ]; then
  INPUT_DIR="$INPUT_DIR"
else
  if [ -d "./deploy/data/ofi_cvd/raw" ]; then
    INPUT_DIR="./deploy/data/ofi_cvd/raw"
  elif [ -d "./deploy/data/ofi_cvd/preview" ]; then
    INPUT_DIR="./deploy/data/ofi_cvd/preview"
  else
    INPUT_DIR="./deploy/data/ofi_cvd"
  fi
fi
SYMBOLS_DEFAULT="BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT DOGEUSDT"
SYMBOLS="${SYMBOLS:-$SYMBOLS_DEFAULT}"
CONFIG_FILE="${CONFIG_FILE:-./config/defaults.smoke.yaml}"

echo "Parameters:"
echo "  - input dir: $INPUT_DIR"
echo "  - symbols: $SYMBOLS"
echo "  - config: $CONFIG_FILE"
echo ""

mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Step 1: run FeaturePipe"
echo "=========================================="
echo ""

FEATURES_TMP="$OUTPUT_DIR/features.jsonl"
FEATURES_FILE="$OUTPUT_DIR/features_${RUN_ID}.jsonl"

python -m alpha_core.microstructure.feature_pipe \
  --input "$INPUT_DIR" \
  --sink jsonl \
  --out "$FEATURES_TMP" \
  --symbols $SYMBOLS \
  --config "$CONFIG_FILE"

EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "ERROR: FeaturePipe failed (exit $EXIT_CODE)"
    exit 1
fi

if [ -f "$FEATURES_TMP" ]; then
  mv "$FEATURES_TMP" "$FEATURES_FILE"
fi

if [ ! -f "$FEATURES_FILE" ]; then
    echo "ERROR: features file missing: $FEATURES_FILE"
    exit 1
fi

FEATURE_COUNT=$(wc -l < "$FEATURES_FILE" 2>/dev/null || echo 0)
echo "feature rows: $FEATURE_COUNT"

if [ "$FEATURE_COUNT" -eq 0 ]; then
  echo "Warning: zero feature rows, falling back to preview data"
  PREVIEW_ROOT="./deploy/data/ofi_cvd/preview"
  if [ -d "$PREVIEW_ROOT" ]; then
    python tools/convert_preview_features.py \
      --preview-root "$PREVIEW_ROOT" \
      --symbols $SYMBOLS \
      --output "$FEATURES_FILE"
    if [ $? -ne 0 ]; then
      echo "ERROR: preview conversion failed"
      exit 1
    fi
    FEATURE_COUNT=$(wc -l < "$FEATURES_FILE" 2>/dev/null || echo 0)
    if [ "$FEATURE_COUNT" -eq 0 ]; then
      echo "ERROR: preview fallback still produced zero rows"
      exit 1
    fi
    echo "preview fallback rows: $FEATURE_COUNT"
  else
    echo "ERROR: preview directory missing"
    exit 1
  fi
fi

echo ""
echo "=========================================="
echo "Step 1.5: prepend warmup history (optional)"
echo "=========================================="
echo ""

PREVIEW_ROOT="./deploy/data/ofi_cvd/preview"
if [ -d "$PREVIEW_ROOT" ] && [ -f "$FEATURES_FILE" ]; then
  python tools/prepend_warmup_features.py \
    --features "$FEATURES_FILE" \
    --preview-root "$PREVIEW_ROOT" \
    --symbols $SYMBOLS \
    --warmup-minutes 3 \
    --output "$FEATURES_FILE" || {
    echo "WARNING: warmup prepend failed, continuing without warmup"
  }
fi

echo ""
echo "=========================================="
echo "Step 2: validate feature schema"
echo "=========================================="
echo ""

python tools/validate_features.py --features "$FEATURES_FILE" --limit 5
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: feature validation failed"
    exit 1
fi

echo ""
echo "=========================================="
echo "Step 3: run CORE_ALGO"
echo "=========================================="
echo ""

export V13_REPLAY_MODE="${V13_REPLAY_MODE:-1}"

CORE_START=$(date +%s)
python -m mcp.signal_server.app \
  --config "$CONFIG_FILE" \
  --input "$FEATURES_FILE" \
  --sink jsonl \
  --out "$OUTPUT_DIR"
EXIT_CODE=$?
CORE_END=$(date +%s)

if [ $EXIT_CODE -ne 0 ]; then
  echo "WARNING: CORE_ALGO returned exit $EXIT_CODE"
  exit 1
fi

echo ""
echo "--- Signal output summary (JSONL) ---"
SIGNAL_DIR="$OUTPUT_DIR/ready/signal"
SUMMARY_JSON="$OUTPUT_DIR/smoke_summary.json"
CONFIRM_DIR="$OUTPUT_DIR/ready/signal_confirm"
SUMMARY_EXIT=0
if [ -d "$SIGNAL_DIR" ]; then
  python tools/summarize_signals.py --signal-dir "$SIGNAL_DIR" --summary-json "$SUMMARY_JSON" || {
    echo "WARNING: summarize_signals reported an issue"
  }
  if [ -f "$SUMMARY_JSON" ]; then
    SUMMARY_JSON_PATH="$SUMMARY_JSON" python - <<'PY'
import json, os, sys

path = os.environ.get('SUMMARY_JSON_PATH')
with open(path, 'r', encoding='utf-8') as fp:
    data = json.load(fp)
print("Summary metrics: confirm={} suppressed={} gated={}".format(data['confirm'], data['suppressed'], data['gated']))
if data.get('guard_reasons'):
    print('guard_reason top5:')
    for reason, count in data['guard_reasons'][:5]:
        print("  {}: {}".format(reason, count))
if data.get('guard_symbol_regime'):
    print('guard by symbol/regime top5:')
    for sym, regime, reason, count in data['guard_symbol_regime'][:5]:
        print("  {} / {} / {}: {}".format(sym, regime, reason, count))
regime_dist = data.get('regime_distribution')
if regime_dist:
    print('regime distribution:')
    for regime, count in sorted(regime_dist.items(), key=lambda x: -x[1])[:5]:
        print("  {}: {}".format(regime, count))
regime_by_sym = data.get('regime_by_symbol')
if regime_by_sym:
    print('regime by symbol (top3):')
    for sym in sorted(regime_by_sym.keys())[:3]:
        regimes = regime_by_sym[sym]
        top_regimes = sorted(regimes.items(), key=lambda x: -x[1])[:3]
        print("  {}: {}".format(sym, dict(top_regimes)))
sample = data.get('sample_record')
if sample:
    import json
    sample_str = json.dumps(sample, ensure_ascii=False, indent=2)
    print('sample record (first row):')
    for line in sample_str.split('\n')[:8]:
        print("  {}".format(line))
heatmap_data = data.get('heatmap')
if heatmap_data:
    print('guard heatmap (top5 symbol/regime combinations):')
    heatmap_items = []
    for key, reasons in heatmap_data.items():
        total = sum(reasons.values())
        top_reason = max(reasons.items(), key=lambda x: x[1]) if reasons else ('<none>', 0)
        heatmap_items.append((key, total, top_reason[0], top_reason[1]))
    heatmap_items.sort(key=lambda x: -x[1])
    for key, total, top_reason, top_count in heatmap_items[:5]:
        print("  {}: total={}, top_reason={}({})".format(key, total, top_reason, top_count))
min_ts = data.get('min_ts')
max_ts = data.get('max_ts')
if min_ts is not None and max_ts is not None:
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(min_ts / 1000.0, tz=timezone.utc)
    end = datetime.fromtimestamp(max_ts / 1000.0, tz=timezone.utc)
    print('time range (utc): {} -> {}'.format(start.isoformat(), end.isoformat()))
if data['confirm'] <= 0:
    sys.exit(2)
PY
    SUMMARY_EXIT=$?
    if [ $SUMMARY_EXIT -eq 2 ]; then
      echo "WARNING: no confirmed signals produced"
      EXIT_CODE=2
    else
      python tools/filter_confirm_signals.py --source "$SIGNAL_DIR" --target "$CONFIRM_DIR"
    fi
  else
    echo "WARNING: summary JSON not generated"
  fi
else
  echo "missing directory: $SIGNAL_DIR"
fi

DURATION=$(( CORE_END - CORE_START ))
if [ $DURATION -le 0 ]; then DURATION=1; fi
if [ $FEATURE_COUNT -gt 0 ]; then
  THROUGHPUT=$(( FEATURE_COUNT / DURATION ))
  echo "throughput: ${THROUGHPUT} rows/sec"
fi

echo ""
echo "--- SQLite sink verification (optional) ---"
if [ -f "$FEATURES_FILE" ]; then
  SQLITE_DB="$OUTPUT_DIR/signals.db"
  python -m mcp.signal_server.app \
    --config "$CONFIG_FILE" \
    --input "$FEATURES_FILE" \
    --sink sqlite \
    --out "$OUTPUT_DIR" 2>/dev/null || {
    echo "WARNING: SQLite sink test skipped or failed"
  }
  if [ -f "$SQLITE_DB" ]; then
    OUTPUT_DIR_VAR="$OUTPUT_DIR" python - <<'PY'
import sqlite3
import os
db_path = os.path.join(os.environ.get('OUTPUT_DIR_VAR', '.'), 'signals.db')
if os.path.exists(db_path):
    con = sqlite3.connect(db_path)
    journal_mode = con.execute('PRAGMA journal_mode;').fetchone()[0]
    confirm_count = con.execute('SELECT COUNT(*) FROM signals WHERE confirm=1;').fetchone()[0]
    total_count = con.execute('SELECT COUNT(*) FROM signals;').fetchone()[0]
    max_ts = con.execute('SELECT MAX(ts_ms) FROM signals;').fetchone()[0]
    recent_confirm = 0
    if max_ts:
        recent_confirm = con.execute('SELECT COUNT(*) FROM signals WHERE confirm=1 AND ts_ms>=?;', (max_ts - 3600000,)).fetchone()[0]
    print('SQLite verification:')
    print('  journal_mode: {}'.format(journal_mode))
    print('  total signals: {}'.format(total_count))
    print('  confirmed signals: {}'.format(confirm_count))
    print('  confirmed in last hour: {}'.format(recent_confirm))
    con.close()
PY
  fi
fi

echo ""
echo "=========================================="
echo "M2 smoke test finished"
echo "=========================================="
echo "features file: $FEATURES_FILE"
echo "feature rows: $FEATURE_COUNT"
echo "run directory: $OUTPUT_DIR"
echo ""

exit $EXIT_CODE

