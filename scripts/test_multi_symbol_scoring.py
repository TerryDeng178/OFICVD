#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多品种公平权重功能测试脚本"""
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.report.optimizer import ParameterOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_test_search_space() -> dict:
    """创建测试用的简化搜索空间"""
    return {
        "search_space": {
            "signal.thresholds.active.buy": [0.8, 0.85],
            "signal.thresholds.active.sell": [-0.85, -0.8],
            "backtest.min_hold_time_sec": [90, 120],
        },
        "scoring_weights": None,
    }


def main():
    """主函数"""
    logger.info("=" * 80)
    logger.info("多品种公平权重功能测试")
    logger.info("=" * 80)
    
    # 创建测试搜索空间
    search_space_data = create_test_search_space()
    search_space = search_space_data["search_space"]
    scoring_weights = search_space_data["scoring_weights"]
    
    logger.info(f"测试搜索空间: {list(search_space.keys())}")
    
    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"runtime/optimizer/test_multisymbol_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"\n输出目录: {output_dir}")
    
    # 测试1: 单品种（应该使用标准评分）
    logger.info("\n" + "=" * 80)
    logger.info("测试1: 单品种（标准评分）")
    logger.info("=" * 80)
    
    symbols_single = ["BTCUSDT"]
    optimizer_single = ParameterOptimizer(
        base_config_path=Path("config/backtest.yaml"),
        search_space=search_space,
        output_dir=output_dir / "single_symbol",
        runner="replay_harness",
        scoring_weights=scoring_weights,
        symbols=symbols_single,
    )
    
    logger.info(f"Symbols: {symbols_single}")
    logger.info(f"使用多品种公平权重: {optimizer_single.use_multi_symbol_scoring}")
    
    if optimizer_single.use_multi_symbol_scoring:
        logger.warning("[WARN] 单品种时不应该启用多品种公平权重")
    else:
        logger.info("[OK] 单品种时正确使用标准评分")
    
    # 测试2: 多品种（应该使用等权评分）
    logger.info("\n" + "=" * 80)
    logger.info("测试2: 多品种（等权评分）")
    logger.info("=" * 80)
    
    # 注意：这里使用多个symbol，但实际数据可能只有BTCUSDT
    # 测试主要验证功能是否正常，即使某些symbol没有数据也会回退
    symbols_multi = ["BTCUSDT", "ETHUSDT"]
    optimizer_multi = ParameterOptimizer(
        base_config_path=Path("config/backtest.yaml"),
        search_space=search_space,
        output_dir=output_dir / "multi_symbol",
        runner="replay_harness",
        scoring_weights=scoring_weights,
        symbols=symbols_multi,
    )
    
    logger.info(f"Symbols: {symbols_multi}")
    logger.info(f"使用多品种公平权重: {optimizer_multi.use_multi_symbol_scoring}")
    
    if optimizer_multi.use_multi_symbol_scoring:
        logger.info("[OK] 多品种时正确启用多品种公平权重")
    else:
        logger.warning("[WARN] 多品种时应该启用多品种公平权重")
    
    # 运行一个trial进行实际测试
    logger.info("\n运行实际trial测试...")
    logger.info("注意：如果数据中只有BTCUSDT，MultiSymbolScorer会回退到整体指标")
    
    backtest_args = {
        "input": "deploy/data/ofi_cvd",
        "date": "2025-11-09",
        "symbols": symbols_multi,
    }
    
    try:
        # 只运行1个trial进行快速测试
        results = optimizer_multi.optimize(
            backtest_args=backtest_args,
            method="random",
            max_trials=1,
            max_workers=1,
            resume=False,
        )
        
        logger.info(f"\n优化完成，共 {len(results)} 个trial")
        
        # 检查结果
        successful_results = [r for r in results if r.get("success")]
        logger.info(f"成功trial数: {len(successful_results)}")
        
        if successful_results:
            result = successful_results[0]
            trial_id = result.get("trial_id")
            
            logger.info(f"\nTrial {trial_id} 结果检查:")
            
            # 检查多品种公平权重指标
            equal_weight_score = result.get("equal_weight_score")
            per_symbol_metrics = result.get("per_symbol_metrics", {})
            
            logger.info(f"  等权评分: {equal_weight_score}")
            logger.info(f"  Per-symbol指标数量: {len(per_symbol_metrics)}")
            
            if equal_weight_score is not None:
                logger.info(f"  [OK] 等权评分存在")
            else:
                logger.info(f"  [INFO] 等权评分为空（可能回退到标准评分）")
            
            if per_symbol_metrics:
                logger.info(f"  [OK] Per-symbol指标存在")
                for symbol, metrics in per_symbol_metrics.items():
                    logger.info(f"    {symbol}: net_pnl={metrics.get('net_pnl', 0):.2f}, "
                              f"win_rate={metrics.get('win_rate', 0):.2%}, "
                              f"total_trades={metrics.get('total_trades', 0)}")
            else:
                logger.info(f"  [INFO] Per-symbol指标为空（可能回退到标准评分）")
            
            # 检查CSV文件
            csv_file = output_dir / "multi_symbol" / "trial_results.csv"
            if csv_file.exists():
                logger.info(f"\n[OK] CSV文件已生成: {csv_file}")
                logger.info("  检查CSV是否包含多品种列...")
                with open(csv_file, "r", encoding="utf-8") as f:
                    header = f.readline().strip()
                    if "equal_weight_score" in header and "per_symbol_metrics" in header:
                        logger.info("  [OK] CSV包含多品种列")
                    else:
                        logger.warning(f"  [WARN] CSV缺少多品种列")
                        logger.warning(f"  表头: {header}")
            else:
                logger.warning(f"[WARN] CSV文件不存在: {csv_file}")
            
            logger.info(f"\n[OK] 多品种公平权重功能测试完成")
            logger.info(f"结果目录: {output_dir}")
            return 0
        else:
            logger.error("[ERROR] 没有成功的trial")
            return 1
    
    except Exception as e:
        logger.error(f"[ERROR] 测试失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

