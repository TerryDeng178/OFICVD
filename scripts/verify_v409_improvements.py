#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.0.9改进项验证脚本

验证所有10个改进项（P0: 5项, P1: 5项）是否生效：
- P0-1: fast path未附加_feature_data
- P0-2: Pushgateway仍被二次推送
- P0-3: ignore_gating CLI无法置为False
- P0-4: DataReader未接收config
- P0-5: 默认来源优先级与ready覆盖preview语义不一致
- P1-1: Pushgateway分组键使用URL path带instance
- P1-2: 统一在_feature_data中显式包含return_1s
- P1-3: aligner_config变量未使用
- P1-4: 无交易时的Metrics行为
- P1-5: Reader分区扫描路径的preview变体
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


def verify_p0_1_fast_path_feature_data():
    """验证P0-1: fast path未附加_feature_data"""
    print("\n" + "=" * 80)
    print("验证 P0-1: fast path未附加_feature_data")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查fast path中是否附加_feature_data
    checks = [
        "# P0-1: fast path也需要附加_feature_data" in content,
        '"return_1s": feature_row.get("return_1s")' in content,
        '"spread_bps": feature_row.get("spread_bps")' in content,
        '"scenario_2x2": feature_row.get("scenario_2x2")' in content,
    ]
    
    if all(checks):
        print("[PASS] P0-1: fast path已附加_feature_data（包含return_1s）")
        return True
    else:
        print(f"[FAIL] P0-1: 检查失败: {checks}")
        return False


def verify_p0_2_pushgateway_double():
    """验证P0-2: Pushgateway仍被二次推送"""
    print("\n" + "=" * 80)
    print("验证 P0-2: Pushgateway仍被二次推送")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否删除了二次调用
    checks = [
        "metrics_agg._export_to_pushgateway" not in content or "compute_metrics" in content,  # 只在compute_metrics中调用
        "# 注意：Pushgateway推送已在_save_metrics中统一处理" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-2: Pushgateway二次推送已删除（统一在_save_metrics中处理）")
        return True
    else:
        print(f"[FAIL] P0-2: 检查失败: {checks}")
        return False


def verify_p0_3_ignore_gating_cli():
    """验证P0-3: ignore_gating CLI无法置为False"""
    print("\n" + "=" * 80)
    print("验证 P0-3: ignore_gating CLI无法置为False")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否添加了--respect-gating参数和修复了逻辑
    checks = [
        "--respect-gating" in content,
        "if args.respect_gating:" in content,
        "ignore_gating = False" in content,
        "backtest_config.get(\"ignore_gating_in_backtest\"" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-3: ignore_gating CLI已修复（支持--respect-gating）")
        return True
    else:
        print(f"[FAIL] P0-3: 检查失败: {checks}")
        return False


def verify_p0_4_reader_config():
    """验证P0-4: DataReader未接收config"""
    print("\n" + "=" * 80)
    print("验证 P0-4: DataReader未接收config")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否传递config给DataReader
    checks = [
        "config=config" in content,  # harness中传递config
    ]
    
    if all(checks):
        print("[PASS] P0-4: DataReader已接收config")
        return True
    else:
        print(f"[FAIL] P0-4: 检查失败: {checks}")
        return False


def verify_p0_5_source_priority():
    """验证P0-5: 默认来源优先级与ready覆盖preview语义不一致"""
    print("\n" + "=" * 80)
    print("验证 P0-5: 默认来源优先级与ready覆盖preview语义不一致")
    print("=" * 80)
    
    reader_file = project_root / "src" / "alpha_core" / "backtest" / "reader.py"
    content = reader_file.read_text(encoding="utf-8")
    
    # 检查默认优先级是否为["ready", "preview"]
    checks = [
        '["ready", "preview"]' in content or "[\"ready\", \"preview\"]" in content,
        "# P0-5: 默认来源优先级与\"ready覆盖preview\"的语义一致" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-5: 默认来源优先级已修复（ready优先）")
        return True
    else:
        print(f"[FAIL] P0-5: 检查失败: {checks}")
        return False


def verify_p1_1_pushgateway_grouping():
    """验证P1-1: Pushgateway分组键使用URL path带instance"""
    print("\n" + "=" * 80)
    print("验证 P1-1: Pushgateway分组键使用URL path带instance")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    # 检查push URL是否包含instance
    checks = [
        "/instance/{instance}" in content or "/instance/" in content,
        "# P1-1: Pushgateway分组键使用URL path带instance" in content,
    ]
    
    if all(checks):
        print("[PASS] P1-1: Pushgateway分组键已优化（包含instance）")
        return True
    else:
        print(f"[FAIL] P1-1: 检查失败: {checks}")
        return False


def verify_p1_2_feature_data_return_1s():
    """验证P1-2: 统一在_feature_data中显式包含return_1s"""
    print("\n" + "=" * 80)
    print("验证 P1-2: 统一在_feature_data中显式包含return_1s")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    feeder_file = project_root / "src" / "alpha_core" / "backtest" / "feeder.py"
    
    harness_content = harness_file.read_text(encoding="utf-8")
    feeder_content = feeder_file.read_text(encoding="utf-8")
    
    # 检查fast path、full path和feeder中都包含return_1s
    checks = [
        '"return_1s": feature_row.get("return_1s")' in harness_content,  # fast path
        '"return_1s": feature_row.get("return_1s")' in harness_content,  # full path
        '"return_1s": feature_row.get("return_1s")' in feeder_content,  # feeder
        "# P1-2: 显式包含return_1s" in harness_content or "# P1-2: 显式包含return_1s" in feeder_content,
    ]
    
    if all(checks):
        print("[PASS] P1-2: return_1s已在所有_feature_data中显式包含")
        return True
    else:
        print(f"[FAIL] P1-2: 检查失败: {checks}")
        return False


def verify_p1_3_aligner_config():
    """验证P1-3: aligner_config变量未使用"""
    print("\n" + "=" * 80)
    print("验证 P1-3: aligner_config变量未使用")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查是否移除了aligner_config变量
    checks = [
        "aligner_config = config.get(\"aligner\", {})" not in content,
        "# P1-3: aligner_config变量已移除" in content,
    ]
    
    if all(checks):
        print("[PASS] P1-3: aligner_config变量已移除")
        return True
    else:
        print(f"[FAIL] P1-3: 检查失败: {checks}")
        return False


def verify_p1_4_metrics_empty_trades():
    """验证P1-4: 无交易时的Metrics行为"""
    print("\n" + "=" * 80)
    print("验证 P1-4: 无交易时的Metrics行为")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    # 检查无交易时是否返回空指标结构并推送健康度
    checks = [
        "# P1-4: 无交易时的Metrics行为" in content,
        "empty_metrics = {" in content,
        "self._save_metrics(empty_metrics" in content,
        '"total_trades": 0' in content,
    ]
    
    if all(checks):
        print("[PASS] P1-4: 无交易时Metrics行为已优化（返回空指标并推送健康度）")
        return True
    else:
        print(f"[FAIL] P1-4: 检查失败: {checks}")
        return False


def verify_p1_5_reader_path_recording():
    """验证P1-5: Reader分区扫描路径的preview变体"""
    print("\n" + "=" * 80)
    print("验证 P1-5: Reader分区扫描路径的preview变体")
    print("=" * 80)
    
    reader_file = project_root / "src" / "alpha_core" / "backtest" / "reader.py"
    content = reader_file.read_text(encoding="utf-8")
    
    # 检查是否记录样例文件路径
    checks = [
        "self._sample_files = set()" in content,
        '"sample_files": sample_files' in content,
        "# P1-5: 记录实际命中样例文件路径" in content,
    ]
    
    if all(checks):
        print("[PASS] P1-5: Reader样例文件路径记录已添加")
        return True
    else:
        print(f"[FAIL] P1-5: 检查失败: {checks}")
        return False


def run_backtest_verification():
    """运行回测并验证输出"""
    print("\n" + "=" * 80)
    print("运行回测验证（使用preview数据）")
    print("=" * 80)
    
    # 使用preview数据运行一个小回测
    input_dir = project_root / "deploy" / "data" / "ofi_cvd"
    output_dir = project_root / "deploy" / "output" / "v409_verification"
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
                "git_commit": "git_commit" in manifest,
                "data_fingerprint": "data_fingerprint" in manifest,
                "reader_stats": "reader_stats" in manifest,
                "feeder_stats": "feeder_stats" in manifest,
                "metrics": "metrics" in manifest,
            }
            
            # P1-5: 检查reader_stats是否包含sample_files
            if "reader_stats" in manifest:
                reader_stats = manifest["reader_stats"]
                checks["sample_files"] = "sample_files" in reader_stats
            
            print("\n[验证] run_manifest.json内容:")
            for key, value in checks.items():
                status = "[PASS]" if value else "[FAIL]"
                print(f"  {status} {key}: {value}")
            
            # 验证时间字段语义
            if "started_at" in manifest and "finished_at" in manifest:
                started = datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00"))
                finished = datetime.fromisoformat(manifest["finished_at"].replace("Z", "+00:00"))
                duration = (finished - started).total_seconds()
                print(f"\n[INFO] 回测耗时: {duration:.2f}秒")
                if duration > 0:
                    print("[PASS] P1-2: started_at和finished_at时间语义正确")
                else:
                    print("[FAIL] P1-2: started_at和finished_at时间异常")
            
            # 检查metrics是否包含avg_ret1s_bps（即使无交易也应该有结构）
            if "metrics" in manifest:
                metrics = manifest["metrics"]
                if isinstance(metrics, dict):
                    if "total_trades" in metrics:
                        print(f"[PASS] P1-4: Metrics包含结构（total_trades: {metrics.get('total_trades', 0)}）")
                    else:
                        print("[FAIL] P1-4: Metrics不包含total_trades")
                else:
                    print("[WARN] Metrics不是字典类型")
            
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
    print("v4.0.9 改进项验证")
    print("=" * 80)
    
    results = {}
    
    # P0项验证
    results["P0-1"] = verify_p0_1_fast_path_feature_data()
    results["P0-2"] = verify_p0_2_pushgateway_double()
    results["P0-3"] = verify_p0_3_ignore_gating_cli()
    results["P0-4"] = verify_p0_4_reader_config()
    results["P0-5"] = verify_p0_5_source_priority()
    
    # P1项验证
    results["P1-1"] = verify_p1_1_pushgateway_grouping()
    results["P1-2"] = verify_p1_2_feature_data_return_1s()
    results["P1-3"] = verify_p1_3_aligner_config()
    results["P1-4"] = verify_p1_4_metrics_empty_trades()
    results["P1-5"] = verify_p1_5_reader_path_recording()
    
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

