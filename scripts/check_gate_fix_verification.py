#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查Gate统计修复验证结果"""
import json
import sys
from pathlib import Path

def check_gate_fix_verification(backtest_dir: Path):
    """检查Gate统计修复验证结果"""
    gate_file = backtest_dir / "gate_reason_breakdown.json"
    
    if not gate_file.exists():
        print(f"❌ gate_reason_breakdown.json不存在: {gate_file}")
        return False
    
    data = json.loads(gate_file.read_text(encoding="utf-8"))
    
    if not data:
        print(f"❌ gate_reason_breakdown.json为空")
        return False
    
    print(f"✅ Gate原因统计 (共{len(data)}类):")
    reasons = sorted(data.items(), key=lambda x: x[1], reverse=True)
    total = sum(data.values())
    
    for k, v in reasons[:10]:
        pct = v / total * 100 if total > 0 else 0
        print(f"  {k}: {v} ({pct:.2f}%)")
    
    if len(reasons) > 0:
        top1_name, top1_count = reasons[0]
        top1_pct = top1_count / total * 100 if total > 0 else 0
        print(f"\nTop-1: {top1_name} = {top1_pct:.2f}%")
        print(f"状态: {'✅ 通过' if top1_pct < 60 else '❌ 未通过'} (阈值<60%)")
        
        # 检查是否包含至少5类原因
        expected_reasons = ["weak_signal", "spread_bps_exceeded", "lag_sec_exceeded", "low_consistency", "warmup"]
        found_reasons = [r for r in expected_reasons if r in data]
        print(f"\n期望的5类原因: {len(found_reasons)}/{len(expected_reasons)}")
        for reason in expected_reasons:
            status = "✅" if reason in data else "❌"
            count = data.get(reason, 0)
            print(f"  {status} {reason}: {count}")
        
        return top1_pct < 60 and len(found_reasons) >= 3
    
    return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_gate_fix_verification.py <backtest_dir>")
        sys.exit(1)
    
    backtest_dir = Path(sys.argv[1])
    if not backtest_dir.exists():
        print(f"❌ 目录不存在: {backtest_dir}")
        sys.exit(1)
    
    success = check_gate_fix_verification(backtest_dir)
    sys.exit(0 if success else 1)

