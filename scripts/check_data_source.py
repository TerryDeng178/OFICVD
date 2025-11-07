# -*- coding: utf-8 -*-
"""检查数据源脚本"""

import json
import time
from pathlib import Path

def check_data_source():
    """检查特征文件数据源"""
    preview_dir = Path("deploy/data/ofi_cvd/preview")
    
    print("=== Data Source Check ===")
    print("")
    
    # 1. 检查预览目录是否存在
    print(f"1. Preview directory exists: {preview_dir.exists()}")
    if not preview_dir.exists():
        print("   [FAIL] 预览目录不存在")
        return
    
    # 2. 查找所有 JSONL 和 Parquet 文件
    jsonl_files = list(preview_dir.rglob("*.jsonl"))
    parquet_files = list(preview_dir.rglob("*.parquet"))
    print(f"2. File types:")
    print(f"   JSONL files: {len(jsonl_files)}")
    print(f"   Parquet files: {len(parquet_files)}")
    
    # 3. 检查特征文件（kind=features）
    features_parquet = [f for f in parquet_files if "kind=features" in str(f)]
    features_jsonl = [f for f in jsonl_files if "kind=features" in str(f) or "features" in str(f)]
    print(f"3. Feature files:")
    print(f"   Parquet (kind=features): {len(features_parquet)}")
    print(f"   JSONL (features): {len(features_jsonl)}")
    
    files = features_jsonl if features_jsonl else features_parquet
    
    if not files:
        print("   [WARN] 未找到特征文件")
        return
    
    # 4. 检查最新文件
    latest = max(files, key=lambda p: p.stat().st_mtime)
    print(f"3. Latest file: {latest.name}")
    print(f"   Modified: {time.ctime(latest.stat().st_mtime)}")
    print(f"   Size: {latest.stat().st_size} bytes")
    
    # 5. 检查最近文件（10分钟内）
    current_time = time.time()
    recent = [f for f in files if current_time - f.stat().st_mtime < 600]
    print(f"5. Recent files (last 10 min): {len(recent)}")
    
    # 6. 文件年龄检查
    if files:
        ages = [(time.time() - f.stat().st_mtime) / 60 for f in files[:10]]
        print(f"6. File age check:")
        print(f"   Min age: {min(ages):.1f} minutes")
        print(f"   Max age: {max(ages):.1f} minutes")
    
    # 7. 目录结构
    print("7. Directory structure:")
    date_dirs = [d for d in preview_dir.iterdir() if d.is_dir() and d.name.startswith("date=")]
    print(f"   Date directories: {len(date_dirs)}")
    if date_dirs:
        latest_date = max(date_dirs, key=lambda d: d.stat().st_mtime)
        print(f"   Latest date: {latest_date.name}")
        hour_dirs = [h for h in latest_date.iterdir() if h.is_dir() and h.name.startswith("hour=")]
        print(f"   Hour directories: {len(hour_dirs)}")
        if hour_dirs:
            latest_hour = max(hour_dirs, key=lambda h: h.stat().st_mtime)
            print(f"   Latest hour: {latest_hour.name}")
            symbol_dirs = [s for s in latest_hour.iterdir() if s.is_dir() and s.name.startswith("symbol=")]
            print(f"   Symbol directories: {len(symbol_dirs)}")
            if symbol_dirs:
                for symbol_dir in symbol_dirs[:3]:
                    kind_dirs = [k for k in symbol_dir.iterdir() if k.is_dir() and k.name.startswith("kind=")]
                    print(f"   {symbol_dir.name}: {len(kind_dirs)} kinds")
    
    # 8. 数据格式验证
    print("8. Data format check:")
    if latest.suffix == ".jsonl":
        print("   [OK] File format: JSONL")
        try:
            with open(latest, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f.readlines()[:10]]
            print(f"   [OK] JSON format valid")
            print(f"   [INFO] Sample count: {len(lines)}")
            
            if lines:
                sample = lines[0]
                required = ["symbol", "ts_ms"]
                missing = [f for f in required if f not in sample]
                if missing:
                    print(f"   [WARN] Missing required fields: {missing}")
                else:
                    print(f"   [OK] Required fields present")
                
                print(f"   [INFO] Sample symbol: {sample.get('symbol')}")
                print(f"   [INFO] Sample timestamp: {sample.get('ts_ms')}")
                print(f"   [INFO] Available fields: {list(sample.keys())[:10]}...")
        except Exception as e:
            print(f"   [FAIL] Error reading JSONL: {e}")
    elif latest.suffix == ".parquet":
        print("   [OK] File format: Parquet")
        print("   [INFO] Signal Server now supports Parquet format")
        try:
            import pandas as pd
            df = pd.read_parquet(latest)
            print(f"   [OK] Parquet file readable")
            print(f"   [INFO] Rows: {len(df)}")
            print(f"   [INFO] Columns: {list(df.columns)[:10]}...")
            if len(df) > 0:
                sample = df.iloc[0].to_dict()
                required = ["symbol", "ts_ms"]
                missing = [f for f in required if f not in sample]
                if missing:
                    print(f"   [WARN] Missing required fields: {missing}")
                else:
                    print(f"   [OK] Required fields present")
                    print(f"   [INFO] Sample symbol: {sample.get('symbol')}")
                    print(f"   [INFO] Sample timestamp: {sample.get('ts_ms')}")
        except ImportError:
            print("   [WARN] pandas not available, cannot read Parquet")
        except Exception as e:
            print(f"   [FAIL] Error reading Parquet: {e}")
    
    # 9. Signal Server 输入路径检查
    print("9. Signal Server input path:")
    expected_path = Path("deploy/data/ofi_cvd/preview")
    print(f"   Expected: {expected_path}")
    print(f"   Exists: {expected_path.exists()}")
    if expected_path.exists():
        print("   [OK] Signal Server input path exists")
        print("   [INFO] Will recursively scan for Parquet/JSONL files")
    else:
        print("   [FAIL] Signal Server input path does not exist")
    
    print("")
    print("=== Check Complete ===")

if __name__ == "__main__":
    check_data_source()

