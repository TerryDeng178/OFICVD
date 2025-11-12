#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行STAGE-2实验（F2-F5）"""
import argparse
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent

# STAGE-2实验组配置
STAGE2_GROUPS = {
    "F2": {
        "name": "融合权重/阈值搜索",
        "config": "runtime/optimizer/group_stage2_baseline_trial5.yaml",
        "search_space": "tasks/TASK-09/search_space_stage2_f2_fusion_weights.yaml",
        "description": "提升有利波段命中率"
    },
    "F3": {
        "name": "反向防抖 & 连击/冷却联合",
        "config": "runtime/optimizer/group_stage2_baseline_trial5.yaml",
        "search_space": "tasks/TASK-09/search_space_stage2_f3_anti_flip.yaml",
        "description": "进一步降频、抑制亏损翻手"
    },
    "F4": {
        "name": "场景化阈值",
        "config": "runtime/optimizer/group_stage2_baseline_trial5.yaml",
        "search_space": "tasks/TASK-09/search_space_stage2_f4_regime_thresholds.yaml",
        "description": "Regime特定的更严入口、更宽持有"
    },
    "F5": {
        "name": "止盈/止损与时间中性退出",
        "config": "runtime/optimizer/group_stage2_baseline_trial5.yaml",
        "search_space": "tasks/TASK-09/search_space_stage2_f5_tp_sl.yaml",
        "description": "把单笔收益拉正"
    },
    "COMBINED": {
        "name": "组合矩阵（F2-F5联合）",
        "config": "runtime/optimizer/group_stage2_baseline_trial5.yaml",
        "search_space": "tasks/TASK-09/search_space_stage2_combined_matrix.yaml",
        "description": "2×2×2×2=16组联合优化"
    }
}


def run_experiment(
    group_key: str,
    group_info: dict,
    input_dir: str,
    date: str,
    symbols: list,
    minutes: int = 1440,  # 默认24小时
    sink: str = "sqlite",
    max_workers: int = 6,
    skip_dual_sink: bool = False
):
    """运行单个实验组"""
    print(f"\n{'='*80}")
    print(f"运行 {group_key}: {group_info['name']}")
    print(f"描述: {group_info['description']}")
    print(f"{'='*80}\n")
    
    config_path = project_root / group_info["config"]
    search_space_path = project_root / group_info["search_space"]
    
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}")
        return False
    
    if not search_space_path.exists():
        print(f"[ERROR] 搜索空间文件不存在: {search_space_path}")
        return False
    
    cmd = [
        sys.executable,
        "scripts/run_stage2_optimization.py",
        "--config", str(config_path),
        "--search-space", str(search_space_path),
        "--input", input_dir,
        "--date", date,
        "--symbols", ",".join(symbols),
        "--minutes", str(minutes),
        "--method", "grid",
        "--max-workers", str(max_workers),
        "--sink", sink,
    ]
    
    if skip_dual_sink:
        cmd.append("--skip-dual-sink-check")
    
    print(f"执行命令: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            check=True,
            encoding="utf-8",
            errors="replace"
        )
        print(f"\n[OK] {group_key} 完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] {group_key} 失败: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="运行STAGE-2实验（F2-F5）")
    parser.add_argument("--input", default="deploy/data/ofi_cvd", help="输入数据目录")
    parser.add_argument("--date", default="2025-11-10", help="回测日期（YYYY-MM-DD）")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=1440, help="回测时长（分钟，默认1440=24小时）")
    parser.add_argument("--groups", default="F2,F3,F4,F5,COMBINED", help="实验组（逗号分隔）")
    parser.add_argument("--sink", default="sqlite", help="信号输出类型")
    parser.add_argument("--max-workers", type=int, default=6, help="最大并发数")
    parser.add_argument("--skip-dual-sink", action="store_true", help="跳过双Sink检查")
    
    args = parser.parse_args()
    
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    groups = [g.strip().upper() for g in args.groups.split(",")]
    
    print("="*80)
    print("STAGE-2实验启动")
    print("="*80)
    print(f"输入目录: {args.input}")
    print(f"回测日期: {args.date}")
    print(f"交易对: {', '.join(symbols)}")
    print(f"回测时长: {args.minutes}分钟 ({args.minutes/60:.1f}小时)")
    print(f"实验组: {', '.join(groups)}")
    print(f"信号输出: {args.sink}")
    print(f"最大并发: {args.max_workers}")
    print("="*80)
    
    # 验证组名
    invalid_groups = [g for g in groups if g not in STAGE2_GROUPS]
    if invalid_groups:
        print(f"[ERROR] 无效的组名: {', '.join(invalid_groups)}")
        print(f"可用组名: {', '.join(STAGE2_GROUPS.keys())}")
        return 1
    
    # 运行各组实验
    results = {}
    for group_key in groups:
        group_info = STAGE2_GROUPS[group_key]
        success = run_experiment(
            group_key,
            group_info,
            args.input,
            args.date,
            symbols,
            args.minutes,
            args.sink,
            args.max_workers,
            args.skip_dual_sink
        )
        results[group_key] = {
            "success": success,
            "name": group_info["name"],
            "description": group_info["description"]
        }
    
    # 输出总结
    print("\n" + "="*80)
    print("STAGE-2实验总结")
    print("="*80)
    for group_key, result in results.items():
        status = "[OK]" if result["success"] else "[ERROR]"
        print(f"{status} {group_key}: {result['name']} - {result['description']}")
    print("="*80)
    
    return 0 if all(r["success"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

