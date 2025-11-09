#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare gate baseline between enforce and ignore modes

P1.3增强: 添加数据指纹和工件固化
"""
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file"""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return {}

def compare_metrics(metrics_enforce: Dict, metrics_ignore: Dict, threshold_pct: float = 5.0) -> bool:
    """Compare metrics between enforce and ignore modes
    
    Returns:
        True if within threshold, False otherwise
    """
    passed = True
    
    # Key metrics to compare
    key_metrics = ["total_pnl", "total_trades", "win_rate"]
    
    for key in key_metrics:
        val_enforce = metrics_enforce.get(key, 0)
        val_ignore = metrics_ignore.get(key, 0)
        
        if val_enforce == 0 and val_ignore == 0:
            continue
        
        if val_enforce == 0:
            diff_pct = 100.0
        else:
            diff_pct = abs(val_ignore - val_enforce) / abs(val_enforce) * 100
        
        status = "PASS" if diff_pct <= threshold_pct else "FAIL"
        print(f"  {key}: enforce={val_enforce}, ignore={val_ignore}, diff={diff_pct:.2f}% [{status}]")
        
        if diff_pct > threshold_pct:
            passed = False
    
    return passed

def compare_gate_reasons(gate_enforce: Dict, gate_ignore: Dict, threshold_pct: float = 20.0) -> bool:
    """Compare gate reason breakdown
    
    Returns:
        True if within threshold, False otherwise
    """
    passed = True
    
    # Get top 5 reasons from enforce mode
    sorted_enforce = sorted(gate_enforce.items(), key=lambda x: x[1], reverse=True)[:5]
    
    print("\nGate reason breakdown comparison (Top 5):")
    for reason, count_enforce in sorted_enforce:
        count_ignore = gate_ignore.get(reason, 0)
        
        if count_enforce == 0:
            diff_pct = 100.0 if count_ignore > 0 else 0.0
        else:
            diff_pct = abs(count_ignore - count_enforce) / count_enforce * 100
        
        status = "PASS" if diff_pct <= threshold_pct else "FAIL"
        print(f"  {reason}: enforce={count_enforce}, ignore={count_ignore}, diff={diff_pct:.2f}% [{status}]")
        
        if diff_pct > threshold_pct:
            passed = False
    
    return passed

def compute_data_fingerprint(input_dir: Path) -> Dict[str, Any]:
    """P1.3: 计算输入数据集的数据指纹
    
    Returns:
        包含(path, size, mtime, sha1)的字典列表
    """
    fingerprint = {
        "input_dir": str(input_dir),
        "files": [],
        "total_size": 0,
        "file_count": 0,
        "computed_at": datetime.now().isoformat(),
    }
    
    if not input_dir.exists():
        return fingerprint
    
    # 扫描所有数据文件（jsonl, parquet）
    data_files = []
    for pattern in ["**/*.jsonl", "**/*.parquet"]:
        data_files.extend(input_dir.glob(pattern))
    
    for file_path in sorted(data_files):
        try:
            stat = file_path.stat()
            relative_path = str(file_path.relative_to(input_dir))
            
            # 计算SHA1（仅对前1MB计算，避免大文件）
            sha1_hash = None
            try:
                with file_path.open("rb") as f:
                    chunk = f.read(1024 * 1024)  # 1MB
                    sha1_hash = hashlib.sha1(chunk).hexdigest()
            except Exception:
                pass
            
            file_info = {
                "path": relative_path,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "sha1_prefix": sha1_hash,
            }
            
            fingerprint["files"].append(file_info)
            fingerprint["total_size"] += stat.st_size
            fingerprint["file_count"] += 1
        except Exception as e:
            print(f"Warning: Failed to process {file_path}: {e}")
    
    return fingerprint


def save_comparison_report(
    enforce_dir: Path,
    ignore_dir: Path,
    metrics_enforce: Dict,
    metrics_ignore: Dict,
    gate_enforce: Dict,
    gate_ignore: Dict,
    metrics_ok: bool,
    gate_ok: bool,
    data_fingerprint: Dict = None,
) -> Path:
    """P1.3: 保存比较报告到JSON工件"""
    report = {
        "comparison_timestamp": datetime.now().isoformat(),
        "enforce_dir": str(enforce_dir),
        "ignore_dir": str(ignore_dir),
        "data_fingerprint": data_fingerprint,
        "metrics_comparison": {
            "enforce": metrics_enforce,
            "ignore": metrics_ignore,
            "passed": metrics_ok,
        },
        "gate_reason_comparison": {
            "enforce": gate_enforce,
            "ignore": gate_ignore,
            "passed": gate_ok,
        },
        "overall_result": "PASS" if (metrics_ok and gate_ok) else "FAIL",
    }
    
    output_file = Path("compare_gate_baseline.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\nComparison report saved to: {output_file}")
    return output_file


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Compare gate baseline between enforce and ignore modes"
    )
    parser.add_argument("enforce_dir", help="Directory containing enforce mode results")
    parser.add_argument("ignore_dir", help="Directory containing ignore mode results")
    parser.add_argument(
        "--input-dir",
        help="Input data directory for fingerprinting (optional)",
    )
    parser.add_argument(
        "--output",
        default="compare_gate_baseline.json",
        help="Output report file (default: compare_gate_baseline.json)",
    )
    
    args = parser.parse_args()
    
    enforce_dir = Path(args.enforce_dir)
    ignore_dir = Path(args.ignore_dir)
    
    print("=" * 80)
    print("Gate Baseline Comparison")
    print("=" * 80)
    
    # P1.3: 计算数据指纹
    data_fingerprint = None
    if args.input_dir:
        input_dir = Path(args.input_dir)
        print(f"\nComputing data fingerprint for: {input_dir}")
        data_fingerprint = compute_data_fingerprint(input_dir)
        print(f"  Found {data_fingerprint['file_count']} files")
        print(f"  Total size: {data_fingerprint['total_size'] / 1024 / 1024:.2f} MB")
    
    # Load metrics
    metrics_enforce = load_json(enforce_dir / "metrics.json")
    metrics_ignore = load_json(ignore_dir / "metrics.json")
    
    # Load gate reason breakdown
    gate_enforce = load_json(enforce_dir / "gate_reason_breakdown.json")
    gate_ignore = load_json(ignore_dir / "gate_reason_breakdown.json")
    
    print("\nMetrics comparison (threshold: 5%):")
    metrics_ok = compare_metrics(metrics_enforce, metrics_ignore, threshold_pct=5.0)
    
    print("\nGate reason breakdown comparison (threshold: 20%):")
    gate_ok = compare_gate_reasons(gate_enforce, gate_ignore, threshold_pct=20.0)
    
    # P1.3: 保存比较报告
    report_file = save_comparison_report(
        enforce_dir=enforce_dir,
        ignore_dir=ignore_dir,
        metrics_enforce=metrics_enforce,
        metrics_ignore=metrics_ignore,
        gate_enforce=gate_enforce,
        gate_ignore=gate_ignore,
        metrics_ok=metrics_ok,
        gate_ok=gate_ok,
        data_fingerprint=data_fingerprint,
    )
    
    print("\n" + "=" * 80)
    if metrics_ok and gate_ok:
        print("RESULT: PASS - All comparisons within threshold")
        sys.exit(0)
    else:
        print("RESULT: FAIL - Some comparisons exceed threshold")
        sys.exit(1)

if __name__ == "__main__":
    main()

