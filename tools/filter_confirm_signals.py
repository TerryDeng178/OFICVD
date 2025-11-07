#!/usr/bin/env python3
"""Copy confirm=true signals into a dedicated directory for smoke testing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def copy_confirm(source: Path, target: Path) -> int:
    count = 0
    for signal_file in sorted(source.rglob("signals_*.jsonl")):
        symbol = signal_file.parent.name
        dest_dir = target / symbol
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / signal_file.name
        with signal_file.open("r", encoding="utf-8") as src, dest_file.open("w", encoding="utf-8") as dst:
            for line in src:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if record.get("confirm") is True:
                    dst.write(line)
                    count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Filter confirm=true signals")
    parser.add_argument("--source", required=True, help="Source signal directory (ready/signal)")
    parser.add_argument("--target", required=True, help="Target directory for confirm-only signals")
    args = parser.parse_args(argv)

    source = Path(args.source)
    target = Path(args.target)
    if not source.exists():
        parser.error(f"source directory not found: {source}")
    target.mkdir(parents=True, exist_ok=True)
    copied = copy_confirm(source, target)
    print(f"confirm rows copied: {copied}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
