#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析为什么没有信号"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.backtest import DataReader
from alpha_core.signals.core_algo import CoreAlgorithm, build_sink

def main():
    print("=" * 80)
    print("分析为什么没有信号")
    print("=" * 80)
    
    # 读取数据
    reader = DataReader(
        input_dir=Path("deploy/data/ofi_cvd"),
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=60,
        include_preview=True,
        source_priority=["ready", "preview"],
    )
    
    features = list(reader.read_features())
    print(f"\n读取到 {len(features)} 条数据")
    
    # 初始化CoreAlgo
    config = {
        "replay_mode": 1,
        "dedupe_ms": 250,
        "weak_signal_threshold": 0.2,
        "consistency_min": 0.15,
        "spread_bps_cap": 20.0,
        "lag_cap_sec": 3.0,
        "weights": {"w_ofi": 0.6, "w_cvd": 0.4},
        "thresholds": {
            "base": {"buy": 0.6, "strong_buy": 1.2, "sell": -0.6, "strong_sell": -1.2},
            "active": {"buy": 0.5, "strong_buy": 1.0, "sell": -0.5, "strong_sell": -1.0},
            "quiet": {"buy": 0.7, "strong_buy": 1.4, "sell": -0.7, "strong_sell": -1.4},
        },
    }
    
    sink = build_sink("null", Path("runtime/debug"))
    algo = CoreAlgorithm(config=config, sink=sink, output_dir=Path("runtime/debug"))
    
    # 统计
    total = 0
    signals = 0
    gating_reasons = {}
    score_distribution = []
    consistency_distribution = []
    spread_distribution = []
    
    for i, row in enumerate(features):
        # 字段标准化
        normalized_row = dict(row)
        if "ofi_z" in normalized_row and "z_ofi" not in normalized_row:
            normalized_row["z_ofi"] = normalized_row["ofi_z"]
        if "cvd_z" in normalized_row and "z_cvd" not in normalized_row:
            normalized_row["z_cvd"] = normalized_row["cvd_z"]
        if "lag_sec" not in normalized_row:
            normalized_row["lag_sec"] = 0.0
        if "consistency" not in normalized_row:
            normalized_row["consistency"] = 1.0
        if "warmup" not in normalized_row:
            normalized_row["warmup"] = False  # 注意：False表示已完成warmup
        
        # 计算融合分数
        score = algo._resolve_score(normalized_row)
        score_distribution.append(score)
        
        consistency = normalized_row.get("consistency", 1.0)
        consistency_distribution.append(consistency)
        
        spread_bps = normalized_row.get("spread_bps", 0.0)
        spread_distribution.append(spread_bps)
        
        # 处理信号
        signal = algo.process_feature_row(normalized_row)
        total += 1
        
        if signal:
            if signal.get("confirm"):
                signals += 1
            else:
                # 记录闸门原因
                guard_reason = signal.get("guard_reason", "")
                if guard_reason:
                    gating_reasons[guard_reason] = gating_reasons.get(guard_reason, 0) + 1
    
    print(f"\n处理统计:")
    print(f"  总数据行数: {total}")
    print(f"  生成信号数: {signals}")
    print(f"  信号率: {signals / total * 100:.2f}%")
    
    print(f"\n融合分数分布:")
    if score_distribution:
        print(f"  范围: {min(score_distribution):.4f} - {max(score_distribution):.4f}")
        print(f"  均值: {sum(score_distribution)/len(score_distribution):.4f}")
        print(f"  标准差: {(sum((x - sum(score_distribution)/len(score_distribution))**2 for x in score_distribution) / len(score_distribution))**0.5:.4f}")
        # 统计超过阈值的数量
        buy_threshold = 0.5  # active模式
        sell_threshold = -0.5
        above_buy = sum(1 for s in score_distribution if s >= buy_threshold)
        below_sell = sum(1 for s in score_distribution if s <= sell_threshold)
        print(f"  超过buy阈值(0.5): {above_buy} ({above_buy/len(score_distribution)*100:.2f}%)")
        print(f"  超过sell阈值(-0.5): {below_sell} ({below_sell/len(score_distribution)*100:.2f}%)")
    
    print(f"\n一致性分布:")
    if consistency_distribution:
        print(f"  范围: {min(consistency_distribution):.4f} - {max(consistency_distribution):.4f}")
        print(f"  均值: {sum(consistency_distribution)/len(consistency_distribution):.4f}")
        consistency_min = 0.15
        below_min = sum(1 for c in consistency_distribution if c < consistency_min)
        print(f"  低于阈值(0.15): {below_min} ({below_min/len(consistency_distribution)*100:.2f}%)")
    
    print(f"\n点差分布:")
    if spread_distribution:
        print(f"  范围: {min(spread_distribution):.4f} - {max(spread_distribution):.4f} bps")
        print(f"  均值: {sum(spread_distribution)/len(spread_distribution):.4f} bps")
        spread_cap = 20.0
        above_cap = sum(1 for s in spread_distribution if s > spread_cap)
        print(f"  超过阈值(20.0 bps): {above_cap} ({above_cap/len(spread_distribution)*100:.2f}%)")
    
    print(f"\n闸门原因统计:")
    for reason, count in sorted(gating_reasons.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {reason}: {count} ({count/total*100:.2f}%)")
    
    sink.close()
    
    print("\n" + "=" * 80)
    return 0

if __name__ == "__main__":
    sys.exit(main())

