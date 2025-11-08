#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TASK-07A 功能验证脚本
检查所有新实现的功能是否正常工作
"""

import json
from pathlib import Path
from typing import Dict, List

def check_manifest_fields(manifest_path: Path) -> Dict[str, bool]:
    """检查manifest文件中的新字段"""
    results = {}
    
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        # 检查timeseries_export
        results["timeseries_export"] = "timeseries_export" in manifest
        if results["timeseries_export"]:
            ts_export = manifest["timeseries_export"]
            results["timeseries_export_count"] = ts_export.get("export_count", 0) >= 0
            results["timeseries_export_error"] = "error_count" in ts_export
        
        # 检查alerts
        results["alerts"] = "alerts" in manifest
        if results["alerts"]:
            alerts = manifest["alerts"]
            results["alerts_triggered"] = "triggered" in alerts
            results["alerts_recovered"] = "recovered" in alerts
            results["alerts_total"] = "total_triggered" in alerts
        
        # 检查harvester_metrics
        results["harvester_metrics"] = "harvester_metrics" in manifest
        if results["harvester_metrics"]:
            metrics = manifest["harvester_metrics"]
            results["harvester_queue_dropped"] = "queue_dropped" in metrics
            results["harvester_reconnect"] = "reconnect_count" in metrics
            results["harvester_timeout"] = "substream_timeout_detected" in metrics
        
        # 检查resource_usage
        results["resource_usage"] = "resource_usage" in manifest
        if results["resource_usage"]:
            resource = manifest["resource_usage"]
            results["resource_rss"] = "max_rss_mb" in resource
            results["resource_files"] = "max_open_files" in resource
        
        # 检查shutdown_order
        results["shutdown_order"] = "shutdown_order" in manifest
        if results["shutdown_order"]:
            order = manifest["shutdown_order"]
            results["shutdown_order_valid"] = len(order) > 0
        
        return results
    except Exception as e:
        print(f"[ERROR] 检查manifest失败: {e}")
        return {}

def check_source_manifest(source_manifest_path: Path) -> Dict[str, bool]:
    """检查source_manifest.json文件"""
    results = {}
    
    if not source_manifest_path.exists():
        results["file_exists"] = False
        return results
    
    results["file_exists"] = True
    
    try:
        with source_manifest_path.open("r", encoding="utf-8") as f:
            source_manifest = json.load(f)
        
        required_fields = [
            "run_id", "session_start", "session_end", 
            "symbols", "ws_endpoint", "ws_region",
            "config_snapshot", "input_mode", "replay_mode"
        ]
        
        for field in required_fields:
            results[field] = field in source_manifest
        
        return results
    except Exception as e:
        print(f"[ERROR] 检查source_manifest失败: {e}")
        return {}

def main():
    """主函数"""
    print("=" * 80)
    print("TASK-07A 功能验证")
    print("=" * 80)
    print()
    
    artifacts_dir = Path("deploy/artifacts/ofi_cvd")
    
    # 查找最新的manifest文件
    run_logs_dir = artifacts_dir / "run_logs"
    manifests = sorted(run_logs_dir.glob("run_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not manifests:
        print("[ERROR] 未找到run_manifest文件")
        return 1
    
    latest_manifest = manifests[0]
    print(f"[INFO] 检查manifest: {latest_manifest.name}")
    
    # 检查manifest字段
    manifest_results = check_manifest_fields(latest_manifest)
    
    print("\n=== Manifest字段检查 ===")
    for key, value in manifest_results.items():
        status = "[PASS]" if value else "[FAIL]"
        color_code = "\033[92m" if value else "\033[91m"
        reset_code = "\033[0m"
        print(f"{color_code}{status}{reset_code} {key}")
    
    # 查找source_manifest
    source_manifests = sorted(artifacts_dir.glob("source_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if source_manifests:
        latest_source = source_manifests[0]
        print(f"\n[INFO] 检查source_manifest: {latest_source.name}")
        
        source_results = check_source_manifest(latest_source)
        
        print("\n=== Source Manifest字段检查 ===")
        for key, value in source_results.items():
            status = "[PASS]" if value else "[FAIL]"
            color_code = "\033[92m" if value else "\033[91m"
            reset_code = "\033[0m"
            print(f"{color_code}{status}{reset_code} {key}")
    else:
        print("\n[WARNING] 未找到source_manifest.json文件")
        source_results = {}
    
    # 汇总
    print("\n" + "=" * 80)
    all_manifest_pass = all(manifest_results.values()) if manifest_results else False
    all_source_pass = all(source_results.values()) if source_results else False
    
    if all_manifest_pass and all_source_pass:
        print("[SUCCESS] 所有功能验证通过！")
        return 0
    else:
        print("[WARNING] 部分功能验证未通过")
        return 1

if __name__ == "__main__":
    exit(main())

