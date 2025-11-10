# -*- coding: utf-8 -*-
"""诊断B组和C组配置未生效的原因"""
import json
from pathlib import Path

print("="*80)
print("B组和C组配置未生效原因诊断")
print("="*80 + "\n")

# 检查B组配置
b_config = Path("runtime/optimizer/group_b_cooldown_anti_flip.yaml")
print("1. B组配置检查:")
print("-"*80)
if b_config.exists():
    import yaml
    with open(b_config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    print("配置中的components.fusion参数:")
    fusion_config = config.get("components", {}).get("fusion", {})
    print(f"  flip_rearm_margin: {fusion_config.get('flip_rearm_margin')}")
    print(f"  adaptive_cooldown_k: {fusion_config.get('adaptive_cooldown_k')}")
    print(f"  w_ofi: {fusion_config.get('w_ofi')}")
    print(f"  w_cvd: {fusion_config.get('w_cvd')}")
    
    print("\n问题分析:")
    print("  - flip_rearm_margin和adaptive_cooldown_k参数")
    print("  - 这些参数可能是在融合模块（OFI_CVD_Fusion）中使用的")
    print("  - 但融合模块是在数据生成阶段（FeaturePipe/Harvester）使用的")
    print("  - 在回测阶段，fusion_score已经计算好了，这些参数不会影响回测结果")
    print("  - CoreAlgorithm只是读取fusion_score，不会重新计算")
else:
    print("配置文件不存在")

print("\n" + "="*80)
print("2. C组配置检查:")
print("-"*80)

c_config = Path("runtime/optimizer/group_c_maker_first.yaml")
if c_config.exists():
    import yaml
    with open(c_config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    print("配置中的backtest.fee_maker_taker参数:")
    fee_config = config.get("backtest", {}).get("fee_maker_taker", {})
    print(f"  maker_fee_ratio: {fee_config.get('maker_fee_ratio')}")
    print(f"  scenario_probs: {fee_config.get('scenario_probs')}")
    
    print("\n问题分析:")
    print("  - fee_maker_taker参数应该在TradeSimulator中使用")
    print("  - 需要检查TradeSimulator是否正确读取和使用这些参数")
    print("  - 可能的原因：TradeSimulator的fee_model逻辑未正确实现")
else:
    print("配置文件不存在")

print("\n" + "="*80)
print("3. 结论和建议:")
print("="*80)
print("\nB组问题:")
print("  - flip_rearm_margin和adaptive_cooldown_k是融合模块的参数")
print("  - 这些参数在数据生成阶段使用，不在回测阶段使用")
print("  - 回测时fusion_score已经计算好了，这些参数不会影响结果")
print("  - 如果要使用这些参数，需要重新生成features数据")
print("\nC组问题:")
print("  - fee_maker_taker参数应该在TradeSimulator中使用")
print("  - 需要检查TradeSimulator的fee_model实现")
print("  - 可能需要检查maker概率计算逻辑是否正确")

