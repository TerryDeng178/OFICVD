#!/usr/bin/env python3
"""验证修复完成情况"""
import sys
import json
import sqlite3
from pathlib import Path

def main():
    print("=" * 80)
    print("TASK-07B 修复验证")
    print("=" * 80)
    print()
    
    # 1. 检查最新manifest的RUN_ID
    print("1. 检查RUN_ID注入:")
    print()
    manifests = sorted(
        Path("deploy/artifacts/ofi_cvd/run_logs").glob("run_manifest_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if manifests:
        with open(manifests[0], "r", encoding="utf-8") as f:
            manifest = json.load(f)
        run_id = manifest.get("run_id", "")
        env_overrides = manifest.get("source_versions", {}).get("env_overrides", {})
        print(f"  Manifest中的run_id: {run_id}")
        print(f"  env_overrides中的RUN_ID: {env_overrides.get('RUN_ID', 'N/A')}")
        print(f"  SQLITE_BATCH_N: {env_overrides.get('SQLITE_BATCH_N', 'N/A')}")
        print(f"  SQLITE_FLUSH_MS: {env_overrides.get('SQLITE_FLUSH_MS', 'N/A')}")
        print(f"  FSYNC_EVERY_N: {env_overrides.get('FSYNC_EVERY_N', 'N/A')}")
    else:
        print("  [!] 未找到manifest文件")
        run_id = ""
    print()
    
    # 2. 检查SQLite数据
    print("2. 检查SQLite数据:")
    print()
    db = Path("runtime/signals.db")
    if db.exists():
        conn = sqlite3.connect(str(db))
        cursor = conn.cursor()
        
        # 检查run_id分布
        cursor.execute("SELECT DISTINCT run_id, COUNT(*) FROM signals GROUP BY run_id ORDER BY COUNT(*) DESC LIMIT 5")
        results = cursor.fetchall()
        print("  run_id分布:")
        for r_id, count in results:
            print(f"    {r_id}: {count:,}条")
        
        # 如果提供了run_id，检查该run_id的数据
        if run_id:
            cursor.execute("SELECT COUNT(*) FROM signals WHERE run_id = ?", (run_id,))
            count = cursor.fetchone()[0]
            print(f"  {run_id}的数据量: {count:,}条")
        
        conn.close()
    else:
        print("  [!] SQLite数据库不存在")
    print()
    
    # 3. 检查JSONL数据
    print("3. 检查JSONL数据:")
    print()
    jsonl_files = sorted(Path("runtime/ready/signal").rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if jsonl_files:
        # 检查最新文件的run_id
        sample_file = jsonl_files[0]
        run_id_counts = {}
        total = 0
        with open(sample_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    total += 1
                    r_id = data.get("run_id", "")
                    run_id_counts[r_id] = run_id_counts.get(r_id, 0) + 1
                    if total >= 100:  # 只检查前100行
                        break
                except Exception:
                    continue
        
        print(f"  最新文件: {sample_file.name}")
        print(f"  前100行run_id分布:")
        for r_id, count in sorted(run_id_counts.items(), key=lambda x: x[1], reverse=True):
            pct = count / total * 100 if total > 0 else 0
            print(f"    {r_id}: {count} ({pct:.1f}%)")
    else:
        print("  [!] 未找到JSONL文件")
    print()
    
    # 4. 运行等价性测试
    print("4. 等价性测试:")
    print()
    if run_id:
        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                "scripts/test_dual_sink_parity.py",
                "--jsonl-dir", "./runtime/ready/signal",
                "--sqlite-db", "./runtime/signals.db",
                "--output", "deploy/artifacts/ofi_cvd/parity_verify.json",
                "--run-id", run_id
            ],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        
        if result.returncode == 0:
            # 读取结果
            parity_file = Path("deploy/artifacts/ofi_cvd/parity_verify.json")
            if parity_file.exists():
                with open(parity_file, "r", encoding="utf-8") as f:
                    parity_data = json.load(f)
                
                overall = parity_data.get("overall", {})
                total_diff = overall.get("total_diff_pct", 0)
                confirm_diff = overall.get("confirm_diff_pct", 0)
                strong_diff = overall.get("strong_ratio_diff_pct", 0)
                
                print(f"  总量差异: {total_diff:.2f}%")
                print(f"  确认量差异: {confirm_diff:.2f}%")
                print(f"  强信号占比差异: {strong_diff:.2f}%")
                print(f"  JSONL总量: {overall.get('jsonl_total', 0):,}")
                print(f"  SQLite总量: {overall.get('sqlite_total', 0):,}")
                print(f"  交集窗口数: {parity_data.get('overlap_minutes', 0)}")
                print()
                
                if total_diff < 0.2:
                    print("  [x] PASS: 总量差异 < 0.2%")
                    return 0
                else:
                    print(f"  [!] FAIL: 总量差异 {total_diff:.2f}% >= 0.2%")
                    return 1
            else:
                print("  [!] 等价性测试结果文件不存在")
                return 1
        else:
            print(f"  [!] 等价性测试失败: {result.stderr}")
            return 1
    else:
        print("  [!] 未找到run_id，跳过等价性测试")
        return 1

if __name__ == "__main__":
    sys.exit(main())
