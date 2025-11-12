# -*- coding: utf-8 -*-
"""运行F系列实验（F1-F6）"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# F组配置（纯STAGE1实验）
F_GROUPS = {
    "F1": {
        "name": "入口质量闸",
        "config": "runtime/optimizer/group_f1_entry_gating.yaml",
        "search_space": "tasks/TASK-09/search_space_f1.json",
        "method": "grid",
        "max_trials": 200,  # 限制组合数：8×11×3×3×3×3 = 7128，限制为200个
        "early_stop_rounds": 0,
        "description": "弱信号/一致性/连击 - win_rate_trades≥35%、avg_pnl_per_trade≥0、pnl_net≥0"
    },
    "F2": {
        "name": "融合权重与阈值",
        "config": "runtime/optimizer/group_f2_fusion_threshold.yaml",
        "search_space": "tasks/TASK-09/search_space_f2.json",
        "method": "grid",
        "max_trials": None,  # 计算组合数：3×3×3×3×3 = 243（需确保w_ofi+w_cvd=1.0）
        "early_stop_rounds": 0,
        "description": "提\"信号纯度\" - win_rate_trades≥35%、avg_pnl_per_trade≥0、pnl_net≥0"
    },
    "F3": {
        "name": "反向防抖 & 翻向重臂",
        "config": "runtime/optimizer/group_f3_reverse_prevention.yaml",
        "search_space": "tasks/TASK-09/search_space_f3.json",
        "method": "grid",
        "max_trials": None,  # 计算组合数：3×3 = 9
        "early_stop_rounds": 0,
        "description": "抑制亏损翻手 - win_rate_trades≥35%、avg_pnl_per_trade≥0、pnl_net≥0"
    },
    "F4": {
        "name": "场景化阈值",
        "config": "runtime/optimizer/group_f4_scenario_threshold.yaml",
        "search_space": "tasks/TASK-09/search_space_f4.json",
        "method": "grid",
        "max_trials": None,  # 计算组合数：1×1×1×1×1×1 = 1（固定偏移，需实现scenario_overrides）
        "early_stop_rounds": 0,
        "description": "活跃/安静分档 - win_rate_trades≥35%、avg_pnl_per_trade≥0、pnl_net≥0"
    }
}


def run_backtest(
    group_key: str,
    group_info: Dict,
    input_dir: str,
    date: str,
    symbols: List[str],
    minutes: int,
    sink: str = "sqlite",
    max_workers: int = 6
) -> bool:
    """运行单个组的回测"""
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
    
    # 确定使用哪个优化脚本
    with open(search_space_path, 'r', encoding='utf-8') as f:
        search_space = json.load(f)
    stage = search_space.get("stage", 2)
    
    if stage == 1:
        script = "run_stage1_optimization.py"
    else:
        script = "run_stage2_optimization.py"
    
    # 构建命令
    cmd = [
        sys.executable,
        f"scripts/{script}",
        "--config", str(config_path),
        "--search-space", str(search_space_path),
        "--input", input_dir,
        "--date", date,
        "--symbols", ",".join(symbols),
        "--minutes", str(minutes),
        "--method", group_info["method"],
        "--max-workers", str(max_workers),
        "--sink", sink,
    ]
    
    if group_info.get("max_trials"):
        cmd.extend(["--max-trials", str(group_info["max_trials"])])
    
    if group_info.get("early_stop_rounds", 0) > 0:
        cmd.extend(["--early-stop-rounds", str(group_info["early_stop_rounds"])])
    
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
    parser = argparse.ArgumentParser(description="运行F系列实验")
    parser.add_argument("--input", default="deploy/data/ofi_cvd", help="输入数据目录")
    parser.add_argument("--date", default="2025-11-10", help="回测日期")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=60, help="回测时长（分钟）")
    parser.add_argument("--groups", default="F1,F2,F3,F4,F5,F6", help="实验组（逗号分隔）")
    parser.add_argument("--sink", default="sqlite", help="信号输出类型")
    parser.add_argument("--max-workers", type=int, default=6, help="最大并发数")
    
    args = parser.parse_args()
    
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    groups = [g.strip().upper() for g in args.groups.split(",")]
    
    print("="*80)
    print("F系列实验启动")
    print("="*80)
    print(f"输入目录: {args.input}")
    print(f"回测日期: {args.date}")
    print(f"交易对: {', '.join(symbols)}")
    print(f"回测时长: {args.minutes}分钟")
    print(f"实验组: {', '.join(groups)}")
    print(f"信号输出: {args.sink}")
    print(f"最大并发: {args.max_workers}")
    print("="*80)
    
    # 验证组名
    invalid_groups = [g for g in groups if g not in F_GROUPS]
    if invalid_groups:
        print(f"[ERROR] 无效的组名: {', '.join(invalid_groups)}")
        print(f"可用组名: {', '.join(F_GROUPS.keys())}")
        return 1
    
    # 运行各组实验
    results = {}
    for group_key in groups:
        group_info = F_GROUPS[group_key]
        success = run_backtest(
            group_key,
            group_info,
            args.input,
            args.date,
            symbols,
            args.minutes,
            args.sink,
            args.max_workers
        )
        results[group_key] = {
            "success": success,
            "name": group_info["name"],
            "description": group_info["description"]
        }
    
    # 输出总结
    print("\n" + "="*80)
    print("F系列实验总结")
    print("="*80)
    for group_key, result in results.items():
        status = "[OK]" if result["success"] else "[ERROR]"
        print(f"{status} {group_key}: {result['name']} - {result['description']}")
    print("="*80)
    
    return 0 if all(r["success"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

