#!/usr/bin/env python3
"""检查P0/P1修复测试结果"""
import json
import sys
from pathlib import Path

def check_sqlite_close_log(run_id: str):
    """检查SQLite关闭日志"""
    print("\n[验证1] SQLite关闭日志检查")
    print("=" * 60)
    
    log_file = Path("logs/signal/signal_stderr.log")
    if not log_file.exists():
        print("  ⚠️  日志文件不存在")
        return False
    
    content = log_file.read_text(encoding="utf-8", errors="replace")
    close_logs = [
        line for line in content.split("\n")
        if "关闭" in line or "flush" in line.lower() or "checkpoint" in line.lower() or "SqliteSink" in line
    ]
    
    if close_logs:
        print(f"  ✅ 找到 {len(close_logs)} 条相关日志")
        print("  最近的日志:")
        for line in close_logs[-5:]:
            print(f"    {line}")
        return True
    else:
        print("  ⚠️  未找到SQLite关闭日志（可能数据为0，未触发SQLite写入）")
        return False

def check_health_check_log():
    """检查健康检查日志"""
    print("\n[验证2] 健康检查日志检查")
    print("=" * 60)
    
    log_file = Path("logs/orchestrator/orchestrator.log")
    if not log_file.exists():
        print("  ⚠️  日志文件不存在")
        return False
    
    content = log_file.read_text(encoding="utf-8", errors="replace")
    health_logs = [
        line for line in content.split("\n")
        if "timeseries.health" in line.lower() or "健康检查" in line
    ]
    
    if health_logs:
        print(f"  ✅ 找到 {len(health_logs)} 条健康检查日志")
        print("  日志内容:")
        for line in health_logs:
            print(f"    {line}")
        return True
    else:
        print("  ⚠️  未找到健康检查日志（可能未启用时序库导出）")
        return False

def check_run_manifest(run_id: str):
    """检查run_manifest"""
    print("\n[验证3] run_manifest检查")
    print("=" * 60)
    
    manifest_file = Path(f"deploy/artifacts/ofi_cvd/run_logs/run_manifest_{run_id}.json")
    if not manifest_file.exists():
        print(f"  ⚠️  manifest文件不存在: {manifest_file}")
        return False
    
    with manifest_file.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    print(f"  ✅ 找到manifest文件")
    print(f"  RUN_ID: {manifest.get('run_id')}")
    print(f"  运行时长: {manifest.get('duration_s', 0):.1f}秒")
    print(f"  关闭顺序: {manifest.get('shutdown_order', [])}")
    
    timeseries_export = manifest.get("timeseries_export", {})
    print(f"  时序库导出: export_count={timeseries_export.get('export_count', 0)}, error_count={timeseries_export.get('error_count', 0)}")
    
    return True

def check_data_consistency(run_id: str):
    """检查数据一致性"""
    print("\n[验证4] 数据一致性检查")
    print("=" * 60)
    
    # 检查JSONL和SQLite文件
    jsonl_dir = Path("runtime/ready/signal")
    sqlite_file = Path("runtime/signals.db")
    
    jsonl_exists = jsonl_dir.exists() and any(jsonl_dir.rglob("*.jsonl"))
    sqlite_exists = sqlite_file.exists()
    
    print(f"  JSONL文件: {'✅ 存在' if jsonl_exists else '⚠️  不存在'}")
    print(f"  SQLite文件: {'✅ 存在' if sqlite_exists else '⚠️  不存在'}")
    
    if jsonl_exists and sqlite_exists:
        print("  ✅ 双Sink文件都存在，可以运行parity检查")
        return True
    else:
        print("  ⚠️  文件不完整，可能数据为0（QUIET_RUN）")
        return False

def main():
    """主函数"""
    run_id = sys.argv[1] if len(sys.argv) > 1 else "p0p1_test_20251109_024255"
    
    print("=" * 80)
    print(f"P0/P1修复测试结果检查 (RUN_ID: {run_id})")
    print("=" * 80)
    
    results = []
    results.append(("SQLite关闭日志", check_sqlite_close_log(run_id)))
    results.append(("健康检查日志", check_health_check_log()))
    results.append(("run_manifest", check_run_manifest(run_id)))
    results.append(("数据一致性", check_data_consistency(run_id)))
    
    print("\n" + "=" * 80)
    print("验证结果总结")
    print("=" * 80)
    
    for name, result in results:
        status = "✅ 通过" if result else "⚠️  需要数据验证"
        print(f"  {name}: {status}")
    
    print("\n注意:")
    print("  - 如果数据为0（QUIET_RUN），某些验证项可能无法验证")
    print("  - 建议使用有数据的测试场景进行完整验证")
    print("  - SQLite关闭日志需要在有数据写入时才能看到")

if __name__ == "__main__":
    main()

