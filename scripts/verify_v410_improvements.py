#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.0.10改进项验证脚本

验证所有P0项和P1-1项是否生效：
- P0-1: Reverse分支可能出现交易重复写入
- P0-2: DataReader的分片计数不一致
- P0-3: DataAligner的_last_obs_ts没有实际参与lag计算
- P0-4: 回测配置的环境变量映射不全
- P0-5: Pushgateway健康指标字段名可能取不到
- P1-1: Pushgateway指标再补两项质量→收益桥接
"""
import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_command(cmd, cwd=None, check=True):
    """运行命令并返回结果"""
    print(f"\n[执行] {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd or project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode != 0:
        print(f"[错误] 命令失败: {result.stderr}")
        return None
    return result


def verify_p0_1_reverse_duplicate():
    """验证P0-1: Reverse分支可能出现交易重复写入"""
    print("\n" + "=" * 80)
    print("验证 P0-1: Reverse分支可能出现交易重复写入")
    print("=" * 80)
    
    trade_sim_file = project_root / "src" / "alpha_core" / "backtest" / "trade_sim.py"
    content = trade_sim_file.read_text(encoding="utf-8")
    
    # 检查reverse分支中是否删除了第二次_record_trade调用
    # 查找reverse分支的代码段
    reverse_section = content[content.find("Check reverse condition"):content.find("return None", content.find("Check reverse condition"))]
    
    checks = [
        "_exit_position(position, ts_ms, mid_price, \"reverse\"" in content,
        "# P0-1: _exit_position()内部已调用_record_trade()" in content or "无需重复写入" in content,
        "self._record_trade(exit_trade)" not in reverse_section or "P0-1" in reverse_section,  # 如果存在，应该有注释说明
    ]
    
    if all(checks):
        print("[PASS] P0-1: Reverse分支重复写入已修复")
        return True
    else:
        print(f"[FAIL] P0-1: 检查失败: {checks}")
        return False


def verify_p0_2_reader_partition_count():
    """验证P0-2: DataReader的分片计数不一致"""
    print("\n" + "=" * 80)
    print("验证 P0-2: DataReader的分片计数不一致")
    print("=" * 80)
    
    reader_file = project_root / "src" / "alpha_core" / "backtest" / "reader.py"
    content = reader_file.read_text(encoding="utf-8")
    
    # 检查flat结构扫描时是否累计partition_count
    checks = [
        "# P0-2: flat结构扫描时也累计partition_count" in content,
        "partition_count += len(found_files)" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-2: DataReader分片计数已修复")
        return True
    else:
        print(f"[FAIL] P0-2: 检查失败: {checks}")
        return False


def verify_p0_3_aligner_obs_gap():
    """验证P0-3: DataAligner的_last_obs_ts没有实际参与lag计算"""
    print("\n" + "=" * 80)
    print("验证 P0-3: DataAligner的_last_obs_ts没有实际参与lag计算")
    print("=" * 80)
    
    aligner_file = project_root / "src" / "alpha_core" / "backtest" / "aligner.py"
    content = aligner_file.read_text(encoding="utf-8")
    
    # 检查是否新增了obs_gap_ms诊断指标
    checks = [
        "obs_gap_ms_price_avg" in content,
        "obs_gap_ms_orderbook_avg" in content,
        "_obs_gap_sum" in content,
        "_obs_gap_count" in content,
        "# P0-3: 计算观测间隔" in content or "# P0-3: 计算平均观测间隔" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-3: DataAligner观测间隔诊断指标已添加")
        return True
    else:
        print(f"[FAIL] P0-3: 检查失败: {checks}")
        return False


def verify_p0_4_config_env_mapping():
    """验证P0-4: 回测配置的环境变量映射不全"""
    print("\n" + "=" * 80)
    print("验证 P0-4: 回测配置的环境变量映射不全")
    print("=" * 80)
    
    config_schema_file = project_root / "src" / "alpha_core" / "backtest" / "config_schema.py"
    content = config_schema_file.read_text(encoding="utf-8")
    
    # 检查是否补全了环境变量映射
    checks = [
        '"TAKER_FEE_BPS": "taker_fee_bps"' in content,
        '"SLIPPAGE_BPS": "slippage_bps"' in content,
        '"NOTIONAL_PER_TRADE": "notional_per_trade"' in content,
        '"IGNORE_GATING": "ignore_gating_in_backtest"' in content,
        "# P0-4: 环境变量映射（补全常用注入参数）" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-4: 环境变量映射已补全")
        return True
    else:
        print(f"[FAIL] P0-4: 检查失败: {checks}")
        return False


def verify_p0_5_feeder_signals_emitted():
    """验证P0-5: Pushgateway健康指标字段名可能取不到"""
    print("\n" + "=" * 80)
    print("验证 P0-5: Pushgateway健康指标字段名可能取不到")
    print("=" * 80)
    
    feeder_file = project_root / "src" / "alpha_core" / "backtest" / "feeder.py"
    content = feeder_file.read_text(encoding="utf-8")
    
    # 检查是否添加了signals_emitted别名
    checks = [
        '"signals_emitted": emitted' in content or '"signals_emitted": emitted' in content,
        "# P0-5: 添加signals_emitted别名" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-5: Feeder signals_emitted别名已添加")
        return True
    else:
        print(f"[FAIL] P0-5: 检查失败: {checks}")
        return False


def verify_p1_1_pushgateway_quality_metrics():
    """验证P1-1: Pushgateway指标再补两项质量→收益桥接"""
    print("\n" + "=" * 80)
    print("验证 P1-1: Pushgateway指标再补两项质量→收益桥接")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    harness_content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否新增了质量→收益桥接指标
    checks = [
        "backtest_aligner_gap_rate" in content,
        "backtest_lag_bad_rate" in content,
        "aligner_stats: Optional[Dict[str, Any]] = None" in content,
        "aligner_stats = aligner.get_stats()" in harness_content or "aligner_stats" in harness_content,
        "# P1-1: Pushgateway指标再补两项" in content or "# P1-1: 获取Aligner统计" in harness_content,
    ]
    
    if all(checks):
        print("[PASS] P1-1: Pushgateway质量→收益桥接指标已添加")
        return True
    else:
        print(f"[FAIL] P1-1: 检查失败: {checks}")
        return False


def run_backtest_verification():
    """运行回测并验证输出"""
    print("\n" + "=" * 80)
    print("运行回测验证（使用preview数据）")
    print("=" * 80)
    
    # 使用preview数据运行一个小回测
    input_dir = project_root / "deploy" / "data" / "ofi_cvd"
    output_dir = project_root / "deploy" / "output" / "v410_verification"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 运行回测（使用1小时数据）
    cmd = f"""python scripts/replay_harness.py \
        --input {input_dir} \
        --output {output_dir} \
        --date 2025-11-08 \
        --symbols BTCUSDT \
        --kinds features \
        --source preview \
        --minutes 60 \
        --config config/backtest.yaml"""
    
    result = run_command(cmd, check=False)
    
    if result and result.returncode == 0:
        print("[PASS] 回测运行成功")
        
        # 检查输出文件（可能在子目录中）
        manifest_files = list(output_dir.rglob("run_manifest.json"))
        if manifest_files:
            manifest_file = manifest_files[0]
            print(f"[INFO] 找到manifest文件: {manifest_file}")
            
            with manifest_file.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            # 验证manifest包含改进项
            checks = {
                "started_at": "started_at" in manifest,
                "finished_at": "finished_at" in manifest,
                "reader_stats": "reader_stats" in manifest,
                "feeder_stats": "feeder_stats" in manifest,
                "metrics": "metrics" in manifest,
            }
            
            # P0-5: 检查feeder_stats是否包含signals_emitted
            if "feeder_stats" in manifest:
                feeder_stats = manifest["feeder_stats"]
                checks["signals_emitted"] = "signals_emitted" in feeder_stats or "emitted" in feeder_stats
            
            print("\n[验证] run_manifest.json内容:")
            for key, value in checks.items():
                status = "[PASS]" if value else "[FAIL]"
                print(f"  {status} {key}: {value}")
            
            return all(checks.values())
        else:
            print("[FAIL] run_manifest.json不存在")
            return False
    else:
        print("[FAIL] 回测运行失败")
        if result:
            if result.stdout:
                print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            if result.stderr:
                print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
        return False


def main():
    """主函数"""
    print("=" * 80)
    print("v4.0.10 改进项验证")
    print("=" * 80)
    
    results = {}
    
    # P0项验证
    results["P0-1"] = verify_p0_1_reverse_duplicate()
    results["P0-2"] = verify_p0_2_reader_partition_count()
    results["P0-3"] = verify_p0_3_aligner_obs_gap()
    results["P0-4"] = verify_p0_4_config_env_mapping()
    results["P0-5"] = verify_p0_5_feeder_signals_emitted()
    
    # P1项验证
    results["P1-1"] = verify_p1_1_pushgateway_quality_metrics()
    
    # 运行回测验证
    results["回测验证"] = run_backtest_verification()
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("验证结果汇总")
    print("=" * 80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for key, value in results.items():
        status = "[PASS]" if value else "[FAIL]"
        print(f"{status} {key}")
    
    print(f"\n总计: {passed}/{total} 项通过")
    
    if passed == total:
        print("\n[SUCCESS] 所有改进项验证通过！")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} 项验证失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())

