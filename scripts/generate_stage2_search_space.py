#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据阶段1最佳结果生成阶段2搜索空间（缩空间→再随机）"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def generate_stage2_search_space(
    stage1_results_file: Path,
    stage1_search_space_file: Path,
    output_file: Path,
    margin: float = 0.15,  # ±15%范围
) -> None:
    """根据阶段1最佳结果生成阶段2搜索空间
    
    Args:
        stage1_results_file: 阶段1结果JSON文件
        stage1_search_space_file: 阶段1搜索空间JSON文件
        output_file: 输出文件路径
        margin: 搜索范围margin（默认0.15，即±15%）
    """
    # 加载阶段1结果
    with open(stage1_results_file, "r", encoding="utf-8") as f:
        stage1_results = json.load(f)
    
    # 找到最佳trial
    successful_results = [r for r in stage1_results if r.get("success")]
    if not successful_results:
        logger.error("阶段1没有成功的结果")
        return
    
    # 按score排序
    best_result = max(
        successful_results,
        key=lambda x: x.get("score", -999)
    )
    
    best_params = best_result.get("params", {})
    logger.info(f"阶段1最佳trial: {best_result.get('trial_id')}")
    logger.info(f"最佳参数: {best_params}")
    
    # 加载阶段1搜索空间（获取参数类型）
    with open(stage1_search_space_file, "r", encoding="utf-8") as f:
        stage1_data = json.load(f)
    
    stage1_search_space = stage1_data.get("search_space", {})
    
    # 生成阶段2搜索空间（基于最佳参数的±margin范围）
    stage2_search_space = {}
    
    for param_name, param_value in best_params.items():
        if param_name in stage1_search_space:
            # 获取原始搜索空间的值列表
            original_values = stage1_search_space[param_name]
            
            if isinstance(param_value, (int, float)):
                # 数值参数：生成±margin范围
                min_val = min(original_values)
                max_val = max(original_values)
                
                # 计算范围
                range_size = max_val - min_val
                new_min = max(min_val, param_value - range_size * margin)
                new_max = min(max_val, param_value + range_size * margin)
                
                # 生成候选值（3-5个值）
                import numpy as np
                if isinstance(param_value, int):
                    candidates = list(range(int(new_min), int(new_max) + 1, max(1, int((new_max - new_min) / 4))))
                else:
                    candidates = list(np.linspace(new_min, new_max, 5))
                
                # 确保包含最佳值
                if param_value not in candidates:
                    candidates.append(param_value)
                
                candidates = sorted(set(candidates))
                stage2_search_space[param_name] = candidates
                
                logger.info(f"{param_name}: {param_value} -> {candidates}")
            else:
                # 非数值参数：保持原值
                stage2_search_space[param_name] = [param_value]
        else:
            # 不在搜索空间中的参数：保持原值
            stage2_search_space[param_name] = [param_value]
    
    # 添加阶段2特有的参数（从stage2搜索空间文件）
    stage2_template_file = Path("tasks/TASK-09/search_space_stage2.json")
    if stage2_template_file.exists():
        with open(stage2_template_file, "r", encoding="utf-8") as f:
            stage2_template = json.load(f)
        
        stage2_specific = stage2_template.get("search_space", {})
        for param_name, param_values in stage2_specific.items():
            if param_name not in stage2_search_space:
                stage2_search_space[param_name] = param_values
    
    # 生成阶段2配置
    stage2_config = {
        "stage": 2,
        "description": "阶段2：提收益 + 控成本（基于阶段1最佳参数±15%范围）",
        "target": "net_pnl ↑、pnl_per_trade ↑，频次恢复到目标",
        "search_space": stage2_search_space,
        "scoring_weights": stage2_template.get("scoring_weights", {}) if stage2_template_file.exists() else {
            "net_pnl": 0.3,
            "pnl_per_trade": 0.3,
            "trades_per_hour": 0.2,
            "cost_ratio_notional": 0.2,
        },
        "base_params": best_params,  # 记录基础参数
        "margin": margin,  # 记录margin
    }
    
    # 保存
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(stage2_config, f, ensure_ascii=False, indent=2)
    
    logger.info(f"阶段2搜索空间已生成: {output_file}")
    logger.info(f"搜索空间大小: {sum(len(v) for v in stage2_search_space.values())} 个组合")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="根据阶段1最佳结果生成阶段2搜索空间")
    parser.add_argument(
        "--stage1-results",
        type=str,
        required=True,
        help="阶段1结果JSON文件路径",
    )
    parser.add_argument(
        "--stage1-search-space",
        type=str,
        default="tasks/TASK-09/search_space_stage1.json",
        help="阶段1搜索空间JSON文件路径",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径（默认：tasks/TASK-09/search_space_stage2_dynamic.json）",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=0.15,
        help="搜索范围margin（默认0.15，即±15%）",
    )
    
    args = parser.parse_args()
    
    stage1_results_file = Path(args.stage1_results)
    if not stage1_results_file.exists():
        logger.error(f"阶段1结果文件不存在: {stage1_results_file}")
        return 1
    
    stage1_search_space_file = Path(args.stage1_search_space)
    if not stage1_search_space_file.exists():
        logger.error(f"阶段1搜索空间文件不存在: {stage1_search_space_file}")
        return 1
    
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = Path("tasks/TASK-09/search_space_stage2_dynamic.json")
    
    generate_stage2_search_space(
        stage1_results_file,
        stage1_search_space_file,
        output_file,
        margin=args.margin,
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

