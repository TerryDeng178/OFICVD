#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-09 阶段2优化：提收益 + 控成本"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.report.optimizer import ParameterOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    """阶段2优化主函数"""
    parser = argparse.ArgumentParser(description="阶段2优化：提收益 + 控成本")
    parser.add_argument(
        "--config",
        type=str,
        default="config/backtest.yaml",
        help="基础配置文件路径（建议使用阶段1的最佳配置）",
    )
    parser.add_argument(
        "--search-space",
        type=str,
        default="tasks/TASK-09/search_space_stage2.json",
        help="阶段2搜索空间JSON文件路径",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="deploy/data/ofi_cvd",
        help="输入数据目录",
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="回测日期（YYYY-MM-DD）",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT",
        help="交易对（逗号分隔）",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        help="回测时长（分钟，用于快速测试）",
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["grid", "random"],
        default="random",
        help="搜索方法（grid/random，阶段2建议random）",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=50,
        help="最大试验次数（random模式，默认50）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出目录（默认：runtime/optimizer/stage2/）",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="并行worker数（默认4）",
    )
    parser.add_argument(
        "--early-stop-rounds",
        type=int,
        default=10,
        help="早停轮数（默认10）",
    )
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        return 1
    
    search_space_file = Path(args.search_space)
    if not search_space_file.exists():
        logger.error(f"搜索空间文件不存在: {search_space_file}")
        return 1
    
    # 加载搜索空间（可能包含scoring_weights）
    # 优化：如果存在动态生成的搜索空间，优先使用
    dynamic_search_space = Path("tasks/TASK-09/search_space_stage2_dynamic.json")
    if dynamic_search_space.exists() and not args.search_space.endswith("dynamic.json"):
        logger.info(f"发现动态生成的搜索空间，使用: {dynamic_search_space}")
        search_space_file = dynamic_search_space
    
    with open(search_space_file, "r", encoding="utf-8") as f:
        search_space_data = json.load(f)
    
    search_space = search_space_data.get("search_space", {})
    scoring_weights = search_space_data.get("scoring_weights", None)
    
    # 记录基础参数（如果存在）
    base_params = search_space_data.get("base_params", {})
    if base_params:
        logger.info(f"基于阶段1最佳参数: {base_params}")
    
    logger.info("=" * 80)
    logger.info("阶段2优化：提收益 + 控成本")
    logger.info("=" * 80)
    logger.info(f"目标: {search_space_data.get('target', 'N/A')}")
    logger.info(f"基础配置: {config_path}")
    logger.info(f"搜索空间: {len(search_space)} 个参数")
    logger.info(f"搜索方法: {args.method}")
    if scoring_weights:
        logger.info(f"评分权重: {scoring_weights}")
    
    # 创建输出目录
    if args.output:
        output_dir = Path(args.output)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(f"runtime/optimizer/stage2_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建优化器（使用阶段2权重）
    # 解析symbols列表
    symbols_list = args.symbols.split(",") if args.symbols else []
    
    optimizer = ParameterOptimizer(
        base_config_path=config_path,
        search_space=search_space,
        output_dir=output_dir,
        runner="replay_harness",
        scoring_weights=scoring_weights,
        symbols=symbols_list,  # 多品种公平权重：传递symbols列表
    )
    
    # 准备回测参数
    backtest_args = {
        "input": args.input,
        "date": args.date,
        "symbols": args.symbols.split(","),
        "minutes": args.minutes,
    }
    
    # 执行优化
    try:
        results = optimizer.optimize(
            backtest_args=backtest_args,
            method=args.method,
            max_trials=args.max_trials,
            max_workers=args.max_workers,
            early_stop_rounds=args.early_stop_rounds,
            resume=True,
        )
        
        logger.info(f"\n阶段2优化完成，共运行 {len(results)} 个试验")
        logger.info(f"结果目录: {optimizer.output_dir}")
        logger.info(f"CSV对比表: {optimizer.output_dir / 'trial_results.csv'}")
        logger.info(f"推荐配置: {optimizer.output_dir / 'recommended_config.yaml'}")
        
        return 0
    except Exception as e:
        logger.error(f"优化失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

