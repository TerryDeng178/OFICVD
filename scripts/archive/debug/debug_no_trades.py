#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调试：为什么没有交易"""
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
    logger.info("调试：为什么没有交易")
    logger.info("=" * 80)
    
    # 1. 读取数据
    logger.info("\n1. 读取数据...")
    reader = DataReader(
        input_dir=Path("deploy/data/ofi_cvd"),
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=5,
    )
    
    features = list(reader.read_features())
    logger.info(f"读取到 {len(features)} 条特征数据")
    
    if not features:
        logger.error("没有读取到任何数据！")
        return 1
    
    # 显示前几条数据的字段
    logger.info(f"\n第一条数据的字段: {list(features[0].keys())}")
    logger.info(f"第一条数据示例: {json.dumps(features[0], ensure_ascii=False, indent=2)[:500]}")
    
    # 2. 检查数据字段完整性
    logger.info("\n2. 检查数据字段完整性...")
    required_fields = ['z_ofi', 'z_cvd', 'lag_sec', 'consistency', 'warmup']
    missing_fields_count = {field: 0 for field in required_fields}
    
    for feat in features[:100]:  # 只检查前100条
        for field in required_fields:
            if field not in feat:
                missing_fields_count[field] += 1
    
    logger.info(f"字段缺失统计（前100条）:")
    for field, count in missing_fields_count.items():
        logger.info(f"  {field}: 缺失 {count} 次 ({count}%)")
    
    # 3. 检查信号生成
    logger.info("\n3. 检查信号生成...")
    config = load_backtest_config(Path("config/backtest.yaml"))
    signal_config = {"sink": {"kind": "null"}}  # 不保存信号，只测试生成
    
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
            if i < 5:  # 显示前5个信号
                logger.info(f"\n信号 #{signal_count}:")
                logger.info(f"  时间: {feature_row.get('ts_ms', 'N/A')}")
                logger.info(f"  方向: {signal.get('side', 'N/A')}")
                logger.info(f"  强度: {signal.get('strength', 'N/A')}")
                logger.info(f"  原因: {signal.get('reason', 'N/A')}")
        else:
            # 检查为什么没有生成信号
            if i < 10:
                # 检查是否因为字段缺失
                missing = [f for f in required_fields if f not in feature_row]
                if missing:
                    suppressed_count += 1
                    reason = f"missing_fields:{','.join(missing)}"
                    gate_reasons[reason] = gate_reasons.get(reason, 0) + 1
    
    logger.info(f"\n信号生成统计:")
    logger.info(f"  总数据行数: {len(features)}")
    logger.info(f"  生成信号数: {signal_count}")
    logger.info(f"  抑制信号数: {suppressed_count}")
    logger.info(f"  信号率: {signal_count / len(features) * 100:.2f}%")
    
    if gate_reasons:
        logger.info(f"\n闸门原因统计:")
        for reason, count in sorted(gate_reasons.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {reason}: {count}")
    
    # 4. 检查CoreAlgo配置
    logger.info("\n4. 检查CoreAlgo配置...")
    algo = feeder.algo
    logger.info(f"  mode: {algo.mode}")
    logger.info(f"  w_ofi: {algo.w_ofi}")
    logger.info(f"  w_cvd: {algo.w_cvd}")
    
    # 5. 检查数据质量
    logger.info("\n5. 检查数据质量...")
    valid_data_count = 0
    invalid_data_count = 0
    
    for feat in features:
        has_z_ofi = 'z_ofi' in feat and feat.get('z_ofi') is not None
        has_z_cvd = 'z_cvd' in feat and feat.get('z_cvd') is not None
        has_mid = 'mid' in feat and feat.get('mid', 0) > 0
        
        if has_z_ofi and has_z_cvd and has_mid:
            valid_data_count += 1
        else:
            invalid_data_count += 1
    
    logger.info(f"  有效数据: {valid_data_count} ({valid_data_count/len(features)*100:.1f}%)")
    logger.info(f"  无效数据: {invalid_data_count} ({invalid_data_count/len(features)*100:.1f}%)")
    
    # 6. 检查是否有价格数据
    logger.info("\n6. 检查价格数据...")
    prices = [f.get('mid', 0) for f in features if f.get('mid', 0) > 0]
    logger.info(f"  有价格的数据: {len(prices)} / {len(features)}")
    if prices:
        logger.info(f"  价格范围: {min(prices):.2f} - {max(prices):.2f}")
    
    # 7. 检查融合信号值
    logger.info("\n7. 检查融合信号值...")
    fusion_values = []
    for feat in features[:100]:
        z_ofi = feat.get('z_ofi', 0)
        z_cvd = feat.get('z_cvd', 0)
        if z_ofi is not None and z_cvd is not None:
            # 模拟融合计算
            fusion = algo.w_ofi * z_ofi + algo.w_cvd * z_cvd
            fusion_values.append(fusion)
    
    if fusion_values:
        logger.info(f"  融合信号值范围: {min(fusion_values):.4f} - {max(fusion_values):.4f}")
        logger.info(f"  融合信号值均值: {sum(fusion_values)/len(fusion_values):.4f}")
        logger.info(f"  融合信号值标准差: {(sum((x - sum(fusion_values)/len(fusion_values))**2 for x in fusion_values) / len(fusion_values))**0.5:.4f}")
    
    feeder.close()
    
    logger.info("\n" + "=" * 80)
    logger.info("调试完成")
    logger.info("=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

