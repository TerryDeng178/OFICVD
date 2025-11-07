# -*- coding: utf-8 -*-
"""CORE_ALGO MCP thin shell.

This CLI wires FeaturePipe output into `alpha_core.signals.CoreAlgorithm` and
supports JSONL / SQLite sinks for TASK-05.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

import yaml

from alpha_core.signals import CoreAlgorithm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def load_signal_config(config_path: Optional[str]) -> Dict:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    # Return signal config merged with strategy_mode (if present)
    signal_cfg = raw.get("signal", {})
    if "strategy_mode" in raw:
        signal_cfg["strategy_mode"] = raw["strategy_mode"]
    return signal_cfg


def iter_feature_rows(source: Optional[str], symbols: Optional[Iterable[str]]) -> Iterator[Dict]:
    allowed = set(s.upper() for s in symbols) if symbols else None

    if not source or source == "-":
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if allowed and payload.get("symbol") not in allowed:
                continue
            yield payload
        return

    path = Path(source)
    candidates: Iterable[Path]
    if path.is_dir():
        candidates = sorted(path.rglob("*.jsonl"))
    elif path.is_file():
        candidates = [path]
    else:
        candidates = sorted(Path(p) for p in path.parent.glob(path.name))

    for file_path in candidates:
        with file_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                record = json.loads(line)
                if allowed and record.get("symbol") not in allowed:
                    continue
                yield record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CORE_ALGO MCP thin shell")
    parser.add_argument("--config", help="Path to YAML configuration (defaults.yaml)")
    parser.add_argument("--input", default="-", help="Feature JSONL (file/dir/- for stdin)")
    parser.add_argument("--sink", choices=["jsonl", "sqlite", "null"], help="Override sink kind")
    parser.add_argument("--out", help="Override output directory (default ./runtime)")
    parser.add_argument("--symbols", nargs="*", help="Optional symbol whitelist (e.g. BTCUSDT ETHUSDT)")
    parser.add_argument("--print", action="store_true", help="Print emitted decisions for inspection")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_signal_config(args.config)

    algo = CoreAlgorithm(
        config=config,
        sink_kind=args.sink,
        output_dir=args.out,
    )

    try:
        for row in iter_feature_rows(args.input, args.symbols):
            decision = algo.process_feature_row(row)
            if args.print and decision:
                sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
    finally:
        algo.close()

    stats = algo.stats
    sys.stderr.write(
        f"[core_algo] processed={stats.processed} emitted={stats.emitted} "
        f"suppressed={stats.suppressed} deduped={stats.deduplicated} warmup_blocked={stats.warmup_blocked}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

