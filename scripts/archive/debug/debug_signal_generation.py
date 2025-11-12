#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调试信号生成问题"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.backtest import DataReader, ReplayFeeder
from alpha_core.backtest.config_schema import load_backtest_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def main():
    """调试主函数"""
    logger.info("=" * 80)
    logger.info("调试信号生成")
    logger.info("=" * 80)
    
    # 使用正确的方式读取数据（包含preview）
    logger.info("\n1. 读取数据（包含preview）...")
    reader = DataReader(
        input_dir=Path("deploy/data/ofi_cvd"),
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=5,
        include_preview=True,  # 关键：必须包含preview
        source_priority=["ready", "preview"],
    )
    
    features = list(reader.read_features())
    logger.info(f"读取到 {len(features)} 条特征数据")
    
    if not features:
        logger.error("没有读取到任何数据！")
        return 1
    
    # 显示数据字段
    logger.info(f"\n第一条数据的字段: {list(features[0].keys())[:20]}")
    
    # 检查关键字段
    logger.info("\n2. 检查关键字段...")
    required_fields = ['z_ofi', 'z_cvd', 'ofi_z', 'cvd_z', 'fusion_score', 'mid']
    for i, feat in enumerate(features[:5]):
        logger.info(f"\n数据 #{i+1}:")
        for field in required_fields:
            value = feat.get(field, "MISSING")
            logger.info(f"  {field}: {value}")
    
    # 检查信号生成
    logger.info("\n3. 检查信号生成...")
    config = load_backtest_config(Path("config/backtest.yaml"))
    signal_config = {"sink": {"kind": "null"}}
    
    feeder = ReplayFeeder(
        config=signal_config,
        output_dir=Path("runtime/debug"),
        sink_kind="null",
    )
    
    signal_count = 0
    suppressed_count = 0
    gate_reasons = {}
    
    for i, feature_row in enumerate(features):
        signal = feeder.algo.process_feature_row(feature_row)
        
        if signal:
            signal_count += 1
            if signal_count <= 5:  # 显示前5个信号
                logger.info(f"\n信号 #{signal_count}:")
                logger.info(f"  时间: {feature_row.get('ts_ms', 'N/A')}")
                logger.info(f"  方向: {signal.get('side', 'N/A')}")
                logger.info(f"  强度: {signal.get('strength', 'N/A')}")
                logger.info(f"  原因: {signal.get('reason', 'N/A')}")
                logger.info(f"  融合分数: {feature_row.get('fusion_score', 'N/A')}")
        else:
            # 检查为什么没有生成信号
            if i < 20:
                fusion_score = feature_row.get('fusion_score', 0)
                z_ofi = feature_row.get('z_ofi') or feature_row.get('ofi_z')
                z_cvd = feature_row.get('z_cvd') or feature_row.get('cvd_z')
                logger.debug(f"数据 #{i}: fusion_score={fusion_score}, z_ofi={z_ofi}, z_cvd={z_cvd}, 无信号")
    
    logger.info(f"\n信号生成统计:")
    logger.info(f"  总数据行数: {len(features)}")
    logger.info(f"  生成信号数: {signal_count}")
    logger.info(f"  信号率: {signal_count / len(features) * 100:.2f}%")
    
    # 检查融合分数分布
    logger.info("\n4. 检查融合分数分布...")
    fusion_scores = [f.get('fusion_score', 0) for f in features if f.get('fusion_score') is not None]
    if fusion_scores:
        logger.info(f"  融合分数范围: {min(fusion_scores):.4f} - {max(fusion_scores):.4f}")
        logger.info(f"  融合分数均值: {sum(fusion_scores)/len(fusion_scores):.4f}")
        logger.info(f"  融合分数标准差: {(sum((x - sum(fusion_scores)/len(fusion_scores))**2 for x in fusion_scores) / len(fusion_scores))**0.5:.4f}")
    
    feeder.close()
    
    logger.info("\n" + "=" * 80)
    logger.info("调试完成")
    logger.info("=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

