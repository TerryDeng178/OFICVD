#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速验证SQLite写入功能
构造1000条伪造信号，验证SqliteSink.close()是否正确刷新队列
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.signals import CoreAlgorithm

def generate_fake_signals(count: int = 1000):
    """生成伪造信号"""
    base_time = int(time.time() * 1000)
    signals = []
    
    for i in range(count):
        ts_ms = base_time + i * 1000  # 每秒一条
        signal = {
            "ts_ms": ts_ms,
            "symbol": "BTCUSDT" if i % 2 == 0 else "ETHUSDT",
            "score": 0.5 + (i % 10) * 0.1,
            "z_ofi": 0.3 + (i % 5) * 0.1,
            "z_cvd": 0.2 + (i % 5) * 0.1,
            "regime": "active" if i % 3 == 0 else "normal",
            "div_type": "divergence" if i % 7 == 0 else None,
            "signal_type": "buy" if i % 2 == 0 else "sell",
            "confirm": 1 if i % 3 == 0 else 0,
            "gating": 0 if i % 3 == 0 else 1,
            "guard_reason": None if i % 3 == 0 else "weak_signal"
        }
        signals.append(signal)
    
    return signals

def main():
    print("=" * 80)
    print("SQLite写入功能验证测试")
    print("=" * 80)
    print()
    
    # 清理旧的测试数据库
    test_db = Path("runtime/test_signals.db")
    if test_db.exists():
        test_db.unlink()
        print(f"[INFO] 已删除旧测试数据库: {test_db}")
    
    # 创建CoreAlgorithm实例，使用SQLite Sink
    print("[INFO] 创建CoreAlgorithm实例（SQLite Sink）...")
    algo = CoreAlgorithm(sink_kind="sqlite", output_dir=Path("runtime"))
    
    # 生成并发送信号
    print("[INFO] 生成1000条伪造信号...")
    signals = generate_fake_signals(1000)
    
    print("[INFO] 发送信号到SQLite Sink...")
    for i, signal in enumerate(signals):
        algo.process_feature_row({
            "ts_ms": signal["ts_ms"],
            "symbol": signal["symbol"],
            "z_ofi": signal["z_ofi"],
            "z_cvd": signal["z_cvd"],
            "spread_bps": 1.0,
            "lag_sec": 0.1,
            "consistency": 0.8,
            "warmup": False,
            "regime": signal["regime"],
            "div_type": signal["div_type"],
            "fusion_score": signal["score"]
        })
        if (i + 1) % 100 == 0:
            print(f"  已发送 {i + 1}/1000 条信号")
    
    print()
    print("[INFO] 调用close()关闭Sink...")
    algo.close()
    print("[INFO] Sink已关闭")
    print()
    
    # 验证数据库
    import sqlite3
    db_path = Path("runtime/signals.db")
    if not db_path.exists():
        print("[ERROR] SQLite数据库文件不存在！")
        return 1
    
    print(f"[INFO] 检查数据库: {db_path}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 查询总记录数
    cursor.execute("SELECT COUNT(*) FROM signals")
    total = cursor.fetchone()[0]
    print(f"  总记录数: {total}")
    
    # 查询本次测试的信号数（基于时间范围）
    test_start_ts = signals[0]["ts_ms"]
    test_end_ts = signals[-1]["ts_ms"]
    cursor.execute("SELECT COUNT(*) FROM signals WHERE ts_ms >= ? AND ts_ms <= ?", 
                   (test_start_ts, test_end_ts))
    test_count = cursor.fetchone()[0]
    print(f"  测试时间范围内的记录数: {test_count}")
    
    # 检查字段完整性
    cursor.execute("SELECT ts_ms, symbol, score, signal_type, confirm, guard_reason FROM signals WHERE ts_ms >= ? LIMIT 5", 
                   (test_start_ts,))
    samples = cursor.fetchall()
    print(f"\n  样本记录（前5条）:")
    for row in samples:
        print(f"    {row}")
    
    # 验证结果
    print()
    print("=" * 80)
    if test_count >= 1000:
        print("[SUCCESS] SQLite写入功能正常！")
        print(f"  期望: 1000条")
        print(f"  实际: {test_count}条")
        print(f"  差异: {abs(test_count - 1000)}条")
        conn.close()
        return 0
    else:
        print("[FAIL] SQLite写入功能异常！")
        print(f"  期望: 1000条")
        print(f"  实际: {test_count}条")
        print(f"  缺失: {1000 - test_count}条")
        print("  可能原因: close()未正确刷新队列")
        conn.close()
        return 1

if __name__ == "__main__":
    exit(main())

