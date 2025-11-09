#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find production signal files"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def find_signal_files():
    """Find all signal files in various locations"""
    locations = [
        project_root / "runtime" / "ready" / "signal",
        project_root / "deploy" / "data" / "ofi_cvd" / "ready" / "signal",
        project_root / "deploy" / "data" / "ofi_cvd" / "preview" / "signal",
    ]
    
    all_files = []
    for loc in locations:
        if loc.exists():
            files = list(loc.rglob("*.jsonl"))
            if files:
                print(f"\n找到目录: {loc}")
                print(f"  文件数: {len(files)}")
                total_lines = 0
                for f in files[:5]:
                    try:
                        with f.open("r", encoding="utf-8") as fp:
                            lines = sum(1 for _ in fp)
                            total_lines += lines
                            print(f"  {f.name}: {lines} 行")
                    except:
                        pass
                if len(files) > 5:
                    print(f"  ... 还有 {len(files) - 5} 个文件")
                all_files.extend(files)
    
    if all_files:
        print(f"\n总共找到 {len(all_files)} 个信号文件")
        return all_files[0].parent if all_files else None
    else:
        print("\n未找到信号文件")
        return None

if __name__ == "__main__":
    signal_dir = find_signal_files()
    if signal_dir:
        print(f"\n信号目录: {signal_dir}")

