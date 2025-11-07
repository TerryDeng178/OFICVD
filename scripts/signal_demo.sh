#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_PATH="${1:-${ROOT_DIR}/runtime/features.jsonl}"
CONFIG_PATH="${2:-${ROOT_DIR}/config/defaults.yaml}"
OUTPUT_DIR="${3:-${ROOT_DIR}/runtime}"
SINK_KIND="${4:-jsonl}"

python -m mcp.signal_server.app \
  --config "${CONFIG_PATH}" \
  --input "${INPUT_PATH}" \
  --sink "${SINK_KIND}" \
  --out "${OUTPUT_DIR}" \
  --print
