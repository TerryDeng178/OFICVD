#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全面回测测试脚本 - 找出BUGS并生成测试报告"""
import json
import logging
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# 设置UTF-8编码
import os
os.environ["PYTHONUTF8"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 测试结果收集
test_results = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "tests": [],
    "bugs": [],
    "warnings": [],
    "summary": {}
}


def log_test(name: str, status: str, message: str = "", details: Dict = None):
    """记录测试结果"""
    test_results["tests"].append({
        "name": name,
        "status": status,  # PASS, FAIL, WARN
        "message": message,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    status_symbol = {"PASS": "[OK]", "FAIL": "[FAIL]", "WARN": "[WARN]"}.get(status, "[?]")
    logger.info(f"{status_symbol} {name}: {message}")


def log_bug(name: str, description: str, error: str = "", fix_suggestion: str = ""):
    """记录BUG"""
    bug = {
        "name": name,
        "description": description,
        "error": error,
        "fix_suggestion": fix_suggestion,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    test_results["bugs"].append(bug)
    logger.error(f"[BUG] {name}: {description}")
    if error:
        logger.error(f"  错误: {error}")
    if fix_suggestion:
        logger.info(f"  建议修复: {fix_suggestion}")


def log_warning(name: str, message: str):
    """记录警告"""
    test_results["warnings"].append({
        "name": name,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    logger.warning(f"[WARN] {name}: {message}")


def test_config_validation():
    """测试1: 配置文件验证"""
    try:
        from alpha_core.backtest.config_schema import load_backtest_config
        config_path = Path("config/backtest.yaml")
        
        if not config_path.exists():
            log_test("配置验证", "FAIL", "配置文件不存在", {"path": str(config_path)})
            log_bug("CONFIG_MISSING", "配置文件不存在", "", "确保config/backtest.yaml存在")
            return False
        
        config = load_backtest_config(config_path)
        
        # 检查必需字段
        required_fields = [
            "taker_fee_bps", "slippage_bps", "notional_per_trade",
            "rollover_timezone", "rollover_hour"
        ]
        missing_fields = [f for f in required_fields if f not in config]
        
        if missing_fields:
            log_test("配置验证", "FAIL", f"缺少必需字段: {missing_fields}")
            log_bug("CONFIG_MISSING_FIELDS", "配置缺少必需字段", 
                   f"缺少字段: {missing_fields}",
                   "在backtest.yaml中添加缺失的字段")
            return False
        
        log_test("配置验证", "PASS", "配置文件格式正确，所有必需字段存在")
        return True
        
    except Exception as e:
        log_test("配置验证", "FAIL", f"配置验证失败: {str(e)}")
        log_bug("CONFIG_VALIDATION_ERROR", "配置验证异常", str(e), traceback.format_exc())
        return False


def test_data_directory():
    """测试2: 数据目录检查"""
    try:
        data_dir = Path("deploy/data/ofi_cvd")
        
        if not data_dir.exists():
            log_test("数据目录", "FAIL", "数据目录不存在", {"path": str(data_dir)})
            log_bug("DATA_DIR_MISSING", "数据目录不存在", "", "确保deploy/data/ofi_cvd目录存在")
            return False, None
        
        # 检查ready和preview目录
        ready_dir = data_dir / "ready"
        preview_dir = data_dir / "preview"
        
        ready_exists = ready_dir.exists()
        preview_exists = preview_dir.exists()
        
        if not ready_exists and not preview_exists:
            log_test("数据目录", "FAIL", "ready和preview目录都不存在")
            log_bug("DATA_SUBDIRS_MISSING", "数据子目录不存在", 
                   "", "确保至少存在ready或preview目录")
            return False, None
        
        # 查找可用日期
        available_dates = []
        if ready_exists:
            dates = [d.name.replace("date=", "") for d in ready_dir.iterdir() 
                    if d.is_dir() and d.name.startswith("date=")]
            available_dates.extend(dates)
        
        if preview_exists:
            dates = [d.name.replace("date=", "") for d in preview_dir.iterdir() 
                    if d.is_dir() and d.name.startswith("date=")]
            available_dates.extend(dates)
        
        available_dates = sorted(set(available_dates), reverse=True)
        
        if not available_dates:
            log_test("数据目录", "FAIL", "未找到可用数据日期")
            log_bug("NO_DATA_DATES", "未找到可用数据日期", "", "确保数据目录下有date=YYYY-MM-DD格式的子目录")
            return False, None
        
        log_test("数据目录", "PASS", f"找到{len(available_dates)}个可用日期", {
            "ready_exists": ready_exists,
            "preview_exists": preview_exists,
            "latest_date": available_dates[0],
            "all_dates": available_dates[:5]
        })
        return True, available_dates[0]
        
    except Exception as e:
        log_test("数据目录", "FAIL", f"数据目录检查失败: {str(e)}")
        log_bug("DATA_DIR_CHECK_ERROR", "数据目录检查异常", str(e), traceback.format_exc())
        return False, None


def test_replay_harness_import():
    """测试3: 回测模块导入"""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        
        from alpha_core.backtest import (
            DataReader, DataAligner, ReplayFeeder, 
            TradeSimulator, MetricsAggregator
        )
        from alpha_core.backtest.config_schema import load_backtest_config
        
        log_test("模块导入", "PASS", "所有回测模块导入成功")
        return True
        
    except ImportError as e:
        log_test("模块导入", "FAIL", f"模块导入失败: {str(e)}")
        log_bug("MODULE_IMPORT_ERROR", "模块导入失败", str(e), 
               "检查Python路径和模块依赖是否正确安装")
        return False
    except Exception as e:
        log_test("模块导入", "FAIL", f"模块导入异常: {str(e)}")
        log_bug("MODULE_IMPORT_EXCEPTION", "模块导入异常", str(e), traceback.format_exc())
        return False


def test_small_backtest(date: str):
    """测试4: 小规模回测（5分钟数据）"""
    try:
        output_dir = Path(f"runtime/backtest/test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            sys.executable,
            "scripts/replay_harness.py",
            "--input", "deploy/data/ofi_cvd",
            "--date", date,
            "--symbols", "BTCUSDT",
            "--kinds", "features",
            "--minutes", "5",  # 只测试5分钟
            "--config", "config/backtest.yaml",
            "--output", str(output_dir)
        ]
        
        logger.info(f"运行小规模回测: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300  # 5分钟超时
        )
        
        if result.returncode != 0:
            log_test("小规模回测", "FAIL", f"回测失败，退出码: {result.returncode}")
            log_bug("BACKTEST_RUNTIME_ERROR", "回测运行时错误", 
                   result.stderr[:500] if result.stderr else "无错误输出",
                   f"检查回测脚本输出: {result.stdout[:500]}")
            return False, output_dir
        
        # 检查输出文件
        subdirs = list(output_dir.glob("backtest_*"))
        actual_output = subdirs[0] if subdirs else output_dir
        
        required_files = [
            "run_manifest.json",
            "trades.jsonl",
            "pnl_daily.jsonl",
            "metrics.json"
        ]
        
        missing_files = []
        for f in required_files:
            if not (actual_output / f).exists():
                missing_files.append(f)
        
        if missing_files:
            log_test("小规模回测", "FAIL", f"缺少输出文件: {missing_files}")
            log_bug("BACKTEST_MISSING_OUTPUT", "回测缺少输出文件", 
                   f"缺少文件: {missing_files}",
                   "检查回测脚本是否正确生成所有输出文件")
            return False, actual_output
        
        # 验证输出文件格式
        try:
            with open(actual_output / "run_manifest.json", "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            if "run_id" not in manifest:
                log_bug("MANIFEST_MISSING_RUN_ID", "manifest缺少run_id字段", "", 
                       "确保manifest包含run_id字段")
            
            if "metrics" not in manifest:
                log_bug("MANIFEST_MISSING_METRICS", "manifest缺少metrics字段", "", 
                       "确保manifest包含metrics字段")
            
        except json.JSONDecodeError as e:
            log_bug("MANIFEST_JSON_ERROR", "manifest JSON格式错误", str(e), 
                   "检查manifest文件格式")
        
        log_test("小规模回测", "PASS", "回测成功完成，所有输出文件已生成", {
            "output_dir": str(actual_output),
            "files_generated": [f for f in required_files if (actual_output / f).exists()]
        })
        return True, actual_output
        
    except subprocess.TimeoutExpired:
        log_test("小规模回测", "FAIL", "回测超时（>5分钟）")
        log_bug("BACKTEST_TIMEOUT", "回测超时", "", "检查数据量是否过大或代码性能问题")
        return False, None
    except Exception as e:
        log_test("小规模回测", "FAIL", f"回测异常: {str(e)}")
        log_bug("BACKTEST_EXCEPTION", "回测异常", str(e), traceback.format_exc())
        return False, None


def test_output_validation(output_dir: Path):
    """测试5: 输出文件验证"""
    try:
        issues = []
        
        # 验证metrics.json
        metrics_file = output_dir / "metrics.json"
        if metrics_file.exists():
            try:
                with open(metrics_file, "r", encoding="utf-8") as f:
                    metrics = json.load(f)
                
                required_metrics = ["total_pnl", "total_trades"]
                missing_metrics = [m for m in required_metrics if m not in metrics]
                
                if missing_metrics:
                    issues.append(f"metrics.json缺少字段: {missing_metrics}")
                    log_bug("METRICS_MISSING_FIELDS", "metrics缺少必需字段", 
                           f"缺少: {missing_metrics}",
                           "检查MetricsAggregator是否正确计算所有指标")
                
            except json.JSONDecodeError as e:
                issues.append(f"metrics.json格式错误: {str(e)}")
                log_bug("METRICS_JSON_ERROR", "metrics JSON格式错误", str(e), 
                       "检查metrics.json文件格式")
        
        # 验证trades.jsonl
        trades_file = output_dir / "trades.jsonl"
        if trades_file.exists():
            try:
                trade_count = 0
                with open(trades_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            trade = json.loads(line)
                            trade_count += 1
                            # 检查必需字段
                            required_trade_fields = ["ts_ms", "symbol", "side", "px", "qty"]
                            missing_fields = [f for f in required_trade_fields if f not in trade]
                            if missing_fields:
                                issues.append(f"trade记录缺少字段: {missing_fields}")
                                break
                
                if trade_count == 0:
                    log_warning("TRADES_EMPTY", "trades.jsonl为空（可能没有生成交易）")
                
            except Exception as e:
                issues.append(f"trades.jsonl读取错误: {str(e)}")
                log_bug("TRADES_READ_ERROR", "trades.jsonl读取错误", str(e), 
                       "检查trades.jsonl文件格式")
        
        if issues:
            log_test("输出验证", "FAIL", f"发现{len(issues)}个问题", {"issues": issues})
            return False
        else:
            log_test("输出验证", "PASS", "所有输出文件格式正确")
            return True
            
    except Exception as e:
        log_test("输出验证", "FAIL", f"输出验证异常: {str(e)}")
        log_bug("OUTPUT_VALIDATION_ERROR", "输出验证异常", str(e), traceback.format_exc())
        return False


def test_config_fields_in_backtest():
    """测试6: 验证配置字段在回测中被正确使用"""
    try:
        from alpha_core.backtest.config_schema import load_backtest_config
        config = load_backtest_config(Path("config/backtest.yaml"))
        
        # 检查新增字段是否在配置中
        new_fields = {
            "strategy": ["direction", "entry_threshold", "exit_threshold"],
            "risk": ["max_position_notional", "max_drawdown_bps"]
        }
        
        issues = []
        try:
            import yaml
            with open("config/backtest.yaml", "r", encoding="utf-8") as f:
                full_config = yaml.safe_load(f)
            
            # 检查strategy字段
            strategy_config = full_config.get("strategy", {})
            for field in new_fields["strategy"]:
                if field not in strategy_config:
                    issues.append(f"strategy.{field}未在配置中")
            
            # 检查risk字段
            risk_config = full_config.get("risk", {})
            for field in new_fields["risk"]:
                if field not in risk_config:
                    issues.append(f"risk.{field}未在配置中")
        
        except Exception as e:
            issues.append(f"配置读取错误: {str(e)}")
        
        if issues:
            log_test("配置字段检查", "WARN", f"发现{len(issues)}个问题", {"issues": issues})
            for issue in issues:
                log_warning("CONFIG_FIELD_MISSING", issue)
            return False
        else:
            log_test("配置字段检查", "PASS", "所有新增配置字段都存在")
            return True
            
    except Exception as e:
        log_test("配置字段检查", "FAIL", f"配置字段检查异常: {str(e)}")
        return False


def generate_report():
    """生成测试报告"""
    test_results["finished_at"] = datetime.now(timezone.utc).isoformat()
    
    # 统计摘要
    total_tests = len(test_results["tests"])
    passed_tests = len([t for t in test_results["tests"] if t["status"] == "PASS"])
    failed_tests = len([t for t in test_results["tests"] if t["status"] == "FAIL"])
    warned_tests = len([t for t in test_results["tests"] if t["status"] == "WARN"])
    
    test_results["summary"] = {
        "total_tests": total_tests,
        "passed": passed_tests,
        "failed": failed_tests,
        "warned": warned_tests,
        "total_bugs": len(test_results["bugs"]),
        "total_warnings": len(test_results["warnings"]),
        "success_rate": f"{(passed_tests / total_tests * 100):.1f}%" if total_tests > 0 else "0%"
    }
    
    # 保存报告
    report_path = Path("reports/comprehensive_backtest_test_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(test_results, f, ensure_ascii=False, indent=2)
    
    # 生成Markdown报告
    md_report_path = Path("reports/comprehensive_backtest_test_report.md")
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write("# 回测系统全面测试报告\n\n")
        f.write(f"**测试时间**: {test_results['started_at']} - {test_results['finished_at']}\n\n")
        
        f.write("## 测试摘要\n\n")
        f.write(f"- **总测试数**: {total_tests}\n")
        f.write(f"- **通过**: {passed_tests} ✅\n")
        f.write(f"- **失败**: {failed_tests} ❌\n")
        f.write(f"- **警告**: {warned_tests} ⚠️\n")
        f.write(f"- **BUG数量**: {len(test_results['bugs'])}\n")
        f.write(f"- **警告数量**: {len(test_results['warnings'])}\n")
        f.write(f"- **成功率**: {test_results['summary']['success_rate']}\n\n")
        
        f.write("## 测试详情\n\n")
        for test in test_results["tests"]:
            status_icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(test["status"], "❓")
            f.write(f"### {status_icon} {test['name']}\n\n")
            f.write(f"- **状态**: {test['status']}\n")
            f.write(f"- **消息**: {test['message']}\n")
            if test.get("details"):
                f.write(f"- **详情**: `{json.dumps(test['details'], ensure_ascii=False)}`\n")
            f.write(f"- **时间**: {test['timestamp']}\n\n")
        
        if test_results["bugs"]:
            f.write("## BUG列表\n\n")
            for i, bug in enumerate(test_results["bugs"], 1):
                f.write(f"### BUG #{i}: {bug['name']}\n\n")
                f.write(f"- **描述**: {bug['description']}\n")
                if bug.get("error"):
                    f.write(f"- **错误**: ```\n{bug['error']}\n```\n")
                if bug.get("fix_suggestion"):
                    f.write(f"- **修复建议**: {bug['fix_suggestion']}\n")
                f.write(f"- **时间**: {bug['timestamp']}\n\n")
        
        if test_results["warnings"]:
            f.write("## 警告列表\n\n")
            for i, warning in enumerate(test_results["warnings"], 1):
                f.write(f"### 警告 #{i}: {warning['name']}\n\n")
                f.write(f"- **消息**: {warning['message']}\n")
                f.write(f"- **时间**: {warning['timestamp']}\n\n")
    
    logger.info(f"\n测试报告已保存:")
    logger.info(f"  JSON: {report_path}")
    logger.info(f"  Markdown: {md_report_path}")
    
    return md_report_path


def main():
    """主函数"""
    logger.info("=" * 80)
    logger.info("开始全面回测测试")
    logger.info("=" * 80)
    
    # 测试1: 配置验证
    if not test_config_validation():
        logger.error("配置验证失败，停止测试")
        generate_report()
        return 1
    
    # 测试2: 数据目录检查
    data_ok, test_date = test_data_directory()
    if not data_ok:
        logger.error("数据目录检查失败，停止测试")
        generate_report()
        return 1
    
    # 测试3: 模块导入
    if not test_replay_harness_import():
        logger.error("模块导入失败，停止测试")
        generate_report()
        return 1
    
    # 测试4: 小规模回测（修复：包含preview目录）
    backtest_ok, output_dir = test_small_backtest(test_date)
    
    # 测试5: 输出验证
    if backtest_ok and output_dir:
        test_output_validation(output_dir)
    
    # 测试6: 配置字段检查
    test_config_fields_in_backtest()
    
    # 生成报告
    report_path = generate_report()
    
    logger.info("=" * 80)
    logger.info("测试完成")
    logger.info("=" * 80)
    
    # 打印摘要
    summary = test_results["summary"]
    logger.info(f"总测试数: {summary['total_tests']}")
    logger.info(f"通过: {summary['passed']} ✅")
    logger.info(f"失败: {summary['failed']} ❌")
    logger.info(f"警告: {summary['warned']} ⚠️")
    logger.info(f"BUG数量: {summary['total_bugs']}")
    logger.info(f"成功率: {summary['success_rate']}")
    
    if summary['total_bugs'] > 0:
        logger.error(f"\n发现 {summary['total_bugs']} 个BUG，请查看报告: {report_path}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

