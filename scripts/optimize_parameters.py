#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-09: 参数优化CLI脚本"""
import argparse
import json
import logging
import sys
from pathlib import Path

# Fix 2: 添加src路径到sys.path
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
    """主函数"""
    parser = argparse.ArgumentParser(description="参数优化")
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="基础配置文件路径",
    )
    parser.add_argument(
        "--search-space",
        type=str,
        required=True,
        help="搜索空间JSON文件路径",
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
        default="grid",
        help="搜索方法（grid/random）",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="最大试验次数（random模式）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出目录（默认：runtime/optimizer/）",
    )
    parser.add_argument(
        "--runner",
        type=str,
        choices=["replay_harness", "orchestrator", "auto"],
        default="auto",
        help="回测运行器（replay_harness/orchestrator/auto）",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="并行worker数（默认1，串行）",
    )
    parser.add_argument(
        "--early-stop-rounds",
        type=int,
        default=None,
        help="早停轮数（随机搜索时，N轮无提升则停止）",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="禁用断点续跑（默认启用）",
    )
    parser.add_argument(  # Walk-forward验证
        "--walk-forward-dates",
        type=str,
        nargs="+",
        default=None,
        help="Walk-forward验证：可用日期列表（如果提供，启用walk-forward验证）",
    )
    parser.add_argument(  # Walk-forward验证
        "--train-ratio",
        type=float,
        default=0.5,
        help="Walk-forward验证：训练集比例（默认0.5，即训练:验证=1:1）",
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
    
    # 加载搜索空间
    with open(search_space_file, "r", encoding="utf-8") as f:
        search_space = json.load(f)
    
    logger.info("=" * 80)
    logger.info("参数优化")
    logger.info("=" * 80)
    logger.info(f"基础配置: {config_path}")
    logger.info(f"搜索空间: {len(search_space)} 个参数")
    logger.info(f"搜索方法: {args.method}")
    
    # 创建优化器
    optimizer = ParameterOptimizer(
        base_config_path=config_path,
        search_space=search_space,
        output_dir=Path(args.output) if args.output else None,
        runner=args.runner,  # Fix 8: 支持runner参数
    )
    
    # 准备回测参数
    backtest_args = {
        "input": args.input,
        "date": args.date,
        "symbols": args.symbols.split(","),
        "minutes": args.minutes,
    }
    
    # 执行优化（B.1改进：支持并行化、早停、断点续跑）
    try:
        results = optimizer.optimize(
            backtest_args=backtest_args,
            method=args.method,
            max_trials=args.max_trials,
            max_workers=args.max_workers,
            early_stop_rounds=args.early_stop_rounds,
            resume=not args.no_resume,
            walk_forward_dates=args.walk_forward_dates,  # Walk-forward验证
            train_ratio=args.train_ratio,  # Walk-forward验证
        )
        
        logger.info(f"\n优化完成，共运行 {len(results)} 个试验")
        logger.info(f"结果目录: {optimizer.output_dir}")
        
        return 0
    except Exception as e:
        logger.error(f"优化失败: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())

