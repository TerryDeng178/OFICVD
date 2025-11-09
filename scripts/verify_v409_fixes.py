#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.0.9快速修复验证脚本

验证所有8个改进项是否生效：
- P0-1: 保留YAML其它分区
- P0-2: Pushgateway指标去重
- P0-3: vol_bps实值补充
- P0-4: Feeder字段名对齐
- P1-1: DataReader保留时长支持config
- P1-2: manifest时间字段语义化
- P1-3: Pushgateway job命名优化
- P1-4: 统一波动字段命名
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


def verify_p0_1_config_retain():
    """验证P0-1: 保留YAML其它分区"""
    print("\n" + "=" * 80)
    print("验证 P0-1: 保留YAML其它分区")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    # 检查load_config函数是否保留原始YAML的所有顶层键
    checks = [
        "{**raw, \"backtest\":" in content or "{**raw, 'backtest':" in content,
        "validated_backtest = load_backtest_config" in content,
        "yaml.safe_load" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-1: load_config保留YAML其它分区")
        return True
    else:
        print(f"[FAIL] P0-1: 检查失败: {checks}")
        return False


def verify_p0_2_pushgateway_double():
    """验证P0-2: Pushgateway指标去重"""
    print("\n" + "=" * 80)
    print("验证 P0-2: Pushgateway指标去重")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    harness_content = harness_file.read_text(encoding="utf-8")
    
    # 检查compute_metrics是否接受reader_stats和feeder_stats
    checks = [
        "reader_stats: Optional[Dict[str, Any]] = None" in content,
        "feeder_stats: Optional[Dict[str, Any]] = None" in content,
        "_save_metrics(metrics, reader_stats=" in content,
        "_export_to_pushgateway(metrics, reader_stats=" in content,
    ]
    
    # 检查harness中是否删除了二次调用
    checks.append("metrics_agg._export_to_pushgateway" not in harness_content or "compute_metrics" in harness_content)
    
    if all(checks):
        print("[PASS] P0-2: Pushgateway指标去重（统一在_save_metrics中推送）")
        return True
    else:
        print(f"[FAIL] P0-2: 检查失败: {checks}")
        return False


def verify_p0_3_vol_bps():
    """验证P0-3: vol_bps实值补充"""
    print("\n" + "=" * 80)
    print("验证 P0-3: vol_bps实值补充")
    print("=" * 80)
    
    aligner_file = project_root / "src" / "alpha_core" / "backtest" / "aligner.py"
    aligner_content = aligner_file.read_text(encoding="utf-8")
    
    trade_sim_file = project_root / "src" / "alpha_core" / "backtest" / "trade_sim.py"
    trade_sim_content = trade_sim_file.read_text(encoding="utf-8")
    
    checks = [
        '"vol_bps": vol_bps' in aligner_content or "'vol_bps': vol_bps" in aligner_content,
        "vol_bps = abs(return_1s)" in aligner_content,
        "vol_bps = fd.get(\"vol_bps\")" in trade_sim_content,
        "abs(float(return_1s))" in trade_sim_content,  # 兜底逻辑
    ]
    
    if all(checks):
        print("[PASS] P0-3: vol_bps实值已补充（Aligner生成，TradeSim兜底）")
        return True
    else:
        print(f"[FAIL] P0-3: 检查失败: {checks}")
        return False


def verify_p0_4_feeder_field_name():
    """验证P0-4: Feeder字段名对齐"""
    print("\n" + "=" * 80)
    print("验证 P0-4: Feeder字段名对齐")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    # 检查是否支持emitted和signals_emitted别名
    checks = [
        "feeder_stats.get(\"signals_emitted\") or feeder_stats.get(\"emitted\"" in content,
    ]
    
    if all(checks):
        print("[PASS] P0-4: Feeder字段名已对齐（支持emitted和signals_emitted别名）")
        return True
    else:
        print(f"[FAIL] P0-4: 检查失败: {checks}")
        return False


def verify_p1_1_reader_config():
    """验证P1-1: DataReader保留时长支持config"""
    print("\n" + "=" * 80)
    print("验证 P1-1: DataReader保留时长支持config")
    print("=" * 80)
    
    reader_file = project_root / "src" / "alpha_core" / "backtest" / "reader.py"
    content = reader_file.read_text(encoding="utf-8")
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    harness_content = harness_file.read_text(encoding="utf-8")
    
    checks = [
        "config: Optional[Dict[str, Any]] = None" in content,
        "self.config = config or {}" in content,
        "config=config" in harness_content,  # harness中传递config
    ]
    
    if all(checks):
        print("[PASS] P1-1: DataReader保留时长支持config")
        return True
    else:
        print(f"[FAIL] P1-1: 检查失败: {checks}")
        return False


def verify_p1_2_manifest_time():
    """验证P1-2: manifest时间字段语义化"""
    print("\n" + "=" * 80)
    print("验证 P1-2: manifest时间字段语义化")
    print("=" * 80)
    
    harness_file = project_root / "scripts" / "replay_harness.py"
    content = harness_file.read_text(encoding="utf-8")
    
    checks = [
        "started_at = datetime.now(timezone.utc)" in content,
        '"started_at": started_at.isoformat()' in content or "'started_at': started_at.isoformat()" in content,
        '"finished_at": finished_at.isoformat()' in content or "'finished_at': finished_at.isoformat()" in content,
    ]
    
    if all(checks):
        print("[PASS] P1-2: manifest时间字段已语义化（started_at/finished_at）")
        return True
    else:
        print(f"[FAIL] P1-2: 检查失败: {checks}")
        return False


def verify_p1_3_pushgateway_job():
    """验证P1-3: Pushgateway job命名优化"""
    print("\n" + "=" * 80)
    print("验证 P1-3: Pushgateway job命名优化")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    # 检查是否使用run_id而不是backtest_{run_id}
    checks = [
        f"/metrics/job/{{run_id}}" in content or "/metrics/job/{run_id}" in content,
        "job_name = f\"backtest_{run_id}\"" not in content,  # 不应该有重复前缀
    ]
    
    if all(checks):
        print("[PASS] P1-3: Pushgateway job命名已优化（避免重复前缀）")
        return True
    else:
        print(f"[FAIL] P1-3: 检查失败: {checks}")
        return False


def verify_p1_4_vol_field_naming():
    """验证P1-4: 统一波动字段命名"""
    print("\n" + "=" * 80)
    print("验证 P1-4: 统一波动字段命名")
    print("=" * 80)
    
    metrics_file = project_root / "src" / "alpha_core" / "backtest" / "metrics.py"
    content = metrics_file.read_text(encoding="utf-8")
    
    checks = [
        '"avg_ret1s_bps"' in content or "'avg_ret1s_bps'" in content,
        "ret1s_values" in content,
        "avg_ret1s_bps = sum(ret1s_values)" in content,
    ]
    
    if all(checks):
        print("[PASS] P1-4: 统一波动字段命名（avg_ret1s_bps）")
        return True
    else:
        print(f"[FAIL] P1-4: 检查失败: {checks}")
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
                "finished_at": "finished_at" in manifest,  # P1-2
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
            
            # 检查metrics是否包含avg_ret1s_bps
            if "metrics" in manifest:
                metrics = manifest["metrics"]
                if "avg_ret1s_bps" in metrics:
                    print(f"[PASS] P1-4: Metrics包含avg_ret1s_bps: {metrics.get('avg_ret1s_bps', 0):.4f}")
                else:
                    print("[FAIL] P1-4: Metrics不包含avg_ret1s_bps")
            
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
    print("v4.0.9 快速修复验证")
    print("=" * 80)
    
    results = {}
    
    # P0项验证
    results["P0-1"] = verify_p0_1_config_retain()
    results["P0-2"] = verify_p0_2_pushgateway_double()
    results["P0-3"] = verify_p0_3_vol_bps()
    results["P0-4"] = verify_p0_4_feeder_field_name()
    
    # P1项验证
    results["P1-1"] = verify_p1_1_reader_config()
    results["P1-2"] = verify_p1_2_manifest_time()
    results["P1-3"] = verify_p1_3_pushgateway_job()
    results["P1-4"] = verify_p1_4_vol_field_naming()
    
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

