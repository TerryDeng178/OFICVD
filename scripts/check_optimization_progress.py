#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查优化进度"""
import json
import sys
from pathlib import Path

def check_progress(output_dir: Path):
    """检查优化进度"""
    results_file = output_dir / "trial_results.json"
    if not results_file.exists():
        print(f"结果文件不存在: {results_file}")
        return
    
    with open(results_file, "r", encoding="utf-8") as f:
        results = json.load(f)
    
    total = len(results)
    successful = sum(1 for r in results if r.get("success"))
    failed = total - successful
    
    print(f"总trial数: {total}")
    print(f"成功: {successful}")
    print(f"失败: {failed}")
    
    if successful > 0:
        successful_results = [r for r in results if r.get("success")]
        scores = [r.get("score", -999) for r in successful_results]
        best_score = max(scores) if scores else None
        
        if best_score is not None:
            print(f"\n最佳score: {best_score:.4f}")
        else:
            print("\n最佳score: N/A")
        
        # 显示TOP 3
        sorted_results = sorted(successful_results, key=lambda x: x.get("score", -999), reverse=True)
        print("\nTOP 3:")
        for i, r in enumerate(sorted_results[:3], 1):
            metrics = r.get("metrics", {})
            score_val = r.get("score")
            if score_val is not None:
                score_str = f"{score_val:.4f}"
            else:
                score_str = "N/A"
            
            net_pnl = metrics.get('total_pnl', 0) - metrics.get('total_fee', 0) - metrics.get('total_slippage', 0)
            win_rate = metrics.get('win_rate', 0) * 100
            
            print(f"  {i}. Score: {score_str}, "
                  f"Net PnL: ${net_pnl:.2f}, "
                  f"Win Rate: {win_rate:.2f}%")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_optimization_progress.py <output_dir>")
        sys.exit(1)
    
    output_dir = Path(sys.argv[1])
    check_progress(output_dir)

