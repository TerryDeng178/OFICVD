#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.0.8改进项验证脚本

验证所有改进项是否生效：
- P0-1: Harness场景上下文补齐
- P0-2: ready优先顺序
- P0-3: Maker/Taker统计口径一致
- P1-1: Aligner场景判定微调
- P1-2: Reader去重桶保留时长参数化
- P1-3: Metrics场景分解补完
- P1-4: PnL切日用例（通过pytest）
- P1-5: Pushgateway健康度指标
- P2-1: Config Schema import json
- P2-3: 运行清单可复现性
"""
import json
import subprocess
import sys
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


def verify_p0_1_harness_context():
    """验证P0-1: Harness场景上下文补齐"""
    print("\n" + "=" * 80)
    print("验证 P0-1: Harness场景上下文补齐")
    print("=" * 80)
    
    # 检查replay_harness.py中是否包含场景上下文字段
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    required_fields = ["spread_bps", "scenario_2x2", "fee_tier", "session"]
    found_fields = [field for field in required_fields if field in content and "_feature_data" in content]
    
    if len(found_fields) == len(required_fields):
        print(f"[PASS] P0-1: 场景上下文字段已补齐: {found_fields}")
        return True
    else:
        print(f"[FAIL] P0-1: 缺少字段: {set(required_fields) - set(found_fields)}")
        return False


def verify_p0_2_ready_priority():
    """验证P0-2: ready优先顺序"""
    print("\n" + "=" * 80)
    print("验证 P0-2: ready优先顺序")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否有固定ready优先的逻辑
    if 'source_priority = ["ready", "preview"]' in content or '"ready", "preview"' in content:
        print("[PASS] P0-2: ready优先顺序已固定")
        return True
    else:
        print("[FAIL] P0-2: ready优先顺序未固定")
        return False


def verify_p0_3_maker_taker_stats():
    """验证P0-3: Maker/Taker统计口径一致"""
    print("\n" + "=" * 80)
    print("验证 P0-3: Maker/Taker统计口径一致")
    print("=" * 80)
    
    trade_sim_file = project_root / "src" / "alpha_core" / "backtest" / "trade_sim.py"
    content = trade_sim_file.read_text(encoding="utf-8")
    
    # 检查是否有return_prob参数和maker_probability
    checks = [
        "return_prob" in content,
        "maker_probability" in content,
        "turnover_maker += entry_notional * entry_maker_prob" in content or "turnover_maker += entry_notional * entry_maker_prob" in content.replace(" ", ""),
    ]
    
    if all(checks):
        print("[PASS] P0-3: Maker/Taker统计使用概率期望口径")
        return True
    else:
        print(f"[FAIL] P0-3: 检查失败: {checks}")
        return False


def verify_p1_1_aligner_scenario():
    """验证P1-1: Aligner场景判定微调"""
    print("\n" + "=" * 80)
    print("验证 P1-1: Aligner场景判定微调")
    print("=" * 80)
    
    aligner_file = project_root / "src" / "alpha_core" / "backtest" / "aligner.py"
    content = aligner_file.read_text(encoding="utf-8")
    
    # 检查is_active和is_high_vol是否解耦
    if "is_active = spread_bps > self.spread_threshold" in content and "is_high_vol = abs(return_1s) >= self.volatility_threshold" in content:
        print("[PASS] P1-1: Aligner场景判定已解耦（A/Q轴用spread，H/L轴用return_1s）")
        return True
    else:
        print("[FAIL] P1-1: Aligner场景判定未解耦")
        return False


def verify_p1_2_reader_bucket_hours():
    """验证P1-2: Reader去重桶保留时长参数化"""
    print("\n" + "=" * 80)
    print("验证 P1-2: Reader去重桶保留时长参数化")
    print("=" * 80)
    
    reader_file = project_root / "src" / "alpha_core" / "backtest" / "reader.py"
    content = reader_file.read_text(encoding="utf-8")
    
    # 检查是否有从config/env读取keep_hours的逻辑
    checks = [
        "READER_DEDUP_KEEP_HOURS" in content or "dedup_keep_hours" in content,
        "keep_hours: Optional[int] = None" in content,
    ]
    
    config_file = project_root / "config" / "backtest.yaml"
    config_content = config_file.read_text(encoding="utf-8")
    checks.append("dedup_keep_hours" in config_content)
    
    if all(checks):
        print("[PASS] P1-2: Reader去重桶保留时长已参数化")
        return True
    else:
        print(f"[FAIL] P1-2: 检查失败: {checks}")
        return False


def verify_p1_3_metrics_scenario_breakdown():
    """验证P1-3: Metrics场景分解补完"""
    print("\n" + "=" * 80)
    print("验证 P1-3: Metrics场景分解补完")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    # 检查是否有scenario_entry_map和avg_hold_sec计算
    checks = [
        "scenario_entry_map" in content,
        "scenario_hold_times" in content,
        "avg_hold_sec" in content,
    ]
    
    if all(checks):
        print("[PASS] P1-3: Metrics场景分解已补完（包含持有时长计算）")
        return True
    else:
        print(f"[FAIL] P1-3: 检查失败: {checks}")
        return False


def verify_p1_4_pnl_ci_cases():
    """验证P1-4: PnL切日用例入CI"""
    print("\n" + "=" * 80)
    print("验证 P1-4: PnL切日用例入CI")
    print("=" * 80)
    
    # 运行pytest测试
    result = run_command(
        "python -m pytest tests/test_pnl_rollover_boundaries.py -v",
        check=False,
    )
    
    if result and result.returncode == 0:
        print("[PASS] P1-4: PnL切日用例测试通过")
        return True
    else:
        print(f"[FAIL] P1-4: PnL切日用例测试失败")
        if result:
            print(result.stdout)
            print(result.stderr)
        return False


def verify_p1_5_pushgateway_health():
    """验证P1-5: Pushgateway健康度指标"""
    print("\n" + "=" * 80)
    print("验证 P1-5: Pushgateway健康度指标")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    # 检查是否有reader_stats和feeder_stats参数
    checks = [
        "reader_stats: Optional[Dict[str, Any]] = None" in content,
        "feeder_stats: Optional[Dict[str, Any]] = None" in content,
        "backtest_reader_dedup_rate" in content,
        "backtest_sink_health" in content,
    ]
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    harness_content = harness_file.read_text(encoding="utf-8")
    checks.append("_export_to_pushgateway(metrics, reader_stats=" in harness_content)
    
    if all(checks):
        print("[PASS] P1-5: Pushgateway健康度指标已添加")
        return True
    else:
        print(f"[FAIL] P1-5: 检查失败: {checks}")
        return False


def verify_p2_1_config_json():
    """验证P2-1: Config Schema补import json"""
    print("\n" + "=" * 80)
    print("验证 P2-1: Config Schema补import json")
    print("=" * 80)
    
    config_schema_file = project_root / "src" / "alpha_core" / "backtest" / "config_schema.py"
    content = config_schema_file.read_text(encoding="utf-8")
    
    # 检查__main__块中是否有import json
    if "__main__" in content and "import json" in content:
        print("[PASS] P2-1: Config Schema已补import json")
        return True
    else:
        print("[FAIL] P2-1: Config Schema未补import json")
        return False


def verify_p2_3_manifest_reproducibility():
    """验证P2-3: 运行清单可复现性"""
    print("\n" + "=" * 80)
    print("验证 P2-3: 运行清单可复现性")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否有git_commit和data_fingerprint
    checks = [
        '"git_commit"' in content or "'git_commit'" in content,
        '"data_fingerprint"' in content or "'data_fingerprint'" in content,
        "rev-parse" in content or "git rev-parse" in content,
    ]
    
    if all(checks):
        print("[PASS] P2-3: 运行清单可复现性已添加（git_commit和data_fingerprint）")
        return True
    else:
        print(f"[FAIL] P2-3: 检查失败: {checks}")
        return False


def run_backtest_verification():
    """运行回测并验证输出"""
    print("\n" + "=" * 80)
    print("运行回测验证（使用preview数据）")
    print("=" * 80)
    
    # 使用preview数据运行一个小回测
    input_dir = project_root / "deploy" / "data" / "ofi_cvd"
    output_dir = project_root / "deploy" / "output" / "v408_verification"
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
        manifest_file = output_dir / "run_manifest.json"
        if not manifest_file.exists():
            # 尝试查找所有可能的manifest文件
            manifest_files = list(output_dir.rglob("run_manifest.json"))
            if manifest_files:
                manifest_file = manifest_files[0]
                print(f"[INFO] 找到manifest文件: {manifest_file}")
        
        if manifest_file.exists():
            with manifest_file.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            # 验证manifest包含改进项
            checks = {
                "git_commit": "git_commit" in manifest,
                "data_fingerprint": "data_fingerprint" in manifest,
                "reader_stats": "reader_stats" in manifest,
                "feeder_stats": "feeder_stats" in manifest,
                "metrics": "metrics" in manifest,
            }
            
            print("\n[验证] run_manifest.json内容:")
            for key, value in checks.items():
                status = "[PASS]" if value else "[FAIL]"
                print(f"  {status} {key}: {value}")
            
            # 检查metrics是否包含场景分解
            if "metrics" in manifest:
                metrics = manifest["metrics"]
                if "scenario_breakdown" in metrics:
                    print(f"\n[PASS] Metrics包含场景分解: {len(metrics.get('scenario_breakdown', {}))} 个场景")
                else:
                    print("[FAIL] Metrics不包含场景分解")
            
            return all(checks.values())
        else:
            print("[FAIL] run_manifest.json不存在")
            return False
    else:
        print("[FAIL] 回测运行失败")
        if result:
            print(result.stdout)
            print(result.stderr)
        return False


def main():
    """主函数"""
    print("=" * 80)
    print("v4.0.8 改进项验证")
    print("=" * 80)
    
    results = {}
    
    # P0项验证
    results["P0-1"] = verify_p0_1_harness_context()
    results["P0-2"] = verify_p0_2_ready_priority()
    results["P0-3"] = verify_p0_3_maker_taker_stats()
    
    # P1项验证
    results["P1-1"] = verify_p1_1_aligner_scenario()
    results["P1-2"] = verify_p1_2_reader_bucket_hours()
    results["P1-3"] = verify_p1_3_metrics_scenario_breakdown()
    results["P1-4"] = verify_p1_4_pnl_ci_cases()
    results["P1-5"] = verify_p1_5_pushgateway_health()
    
    # P2项验证
    results["P2-1"] = verify_p2_1_config_json()
    results["P2-3"] = verify_p2_3_manifest_reproducibility()
    
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

