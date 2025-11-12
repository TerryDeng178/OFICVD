# -*- coding: utf-8 -*-
"""TASK-09: 参数优化器"""
import copy
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class ParameterOptimizer:
    """参数优化器
    
    功能：
    - 网格搜索
    - 随机搜索
    - 批量试参
    - 输出对比表和推荐参数
    """
    
    def __init__(
        self,
        base_config_path: Path,
        search_space: Dict[str, List[Any]],
        output_dir: Optional[Path] = None,
        runner: str = "replay_harness",  # Fix 8: 可配置runner
        scoring_weights: Optional[Dict[str, float]] = None,  # 阶段1/阶段2自定义权重
        symbols: Optional[List[str]] = None,  # 多品种公平权重：交易对列表
    ):
        """
        Args:
            base_config_path: 基础配置文件路径
            search_space: 搜索空间，格式：{"config.path.to.param": [value1, value2, ...]}
            output_dir: 输出目录（默认：runtime/optimizer/）
            symbols: 交易对列表（用于多品种公平权重评分）
        """
        self.base_config_path = Path(base_config_path)
        if not self.base_config_path.exists():
            raise ValueError(f"配置文件不存在: {self.base_config_path}")
        
        # 过滤掉非参数字段（note, description等）
        self.search_space = {k: v for k, v in search_space.items() if k not in ("note", "description", "target")}
        self.output_dir = Path(output_dir) if output_dir else Path("runtime/optimizer")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Fix 8: 自动探测runner
        self.runner = runner
        if runner == "auto":
            # 自动探测：优先使用replay_harness，如果不存在则使用orchestrator
            replay_harness = Path("scripts/replay_harness.py")
            if replay_harness.exists():
                self.runner = "replay_harness"
            else:
                self.runner = "orchestrator"
        
        # 保存评分权重（用于阶段1/阶段2）
        self.scoring_weights = scoring_weights
        
        # 多品种公平权重：保存symbols信息
        self.symbols = symbols or []
        self.use_multi_symbol_scoring = len(self.symbols) > 1
        
        # 口径参数：保存用于manifest记录
        self.backtest_config = None  # 将在optimize时从base_config加载
        
        self.trial_results = []
        
        logger.info(f"[ParameterOptimizer] 基础配置: {self.base_config_path}")
        logger.info(f"[ParameterOptimizer] 搜索空间: {len(search_space)} 个参数")
        logger.info(f"[ParameterOptimizer] 输出目录: {self.output_dir}")
        logger.info(f"[ParameterOptimizer] Runner: {self.runner}")
        if self.use_multi_symbol_scoring:
            logger.info(f"[ParameterOptimizer] 多品种公平权重: {len(self.symbols)} 个交易对 - {self.symbols}")
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        import yaml
        
        with open(self.base_config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def _save_config(self, config: Dict[str, Any], output_path: Path):
        """保存配置文件"""
        import yaml
        
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    def _set_nested_value(self, config: Dict[str, Any], path: str, value: Any):
        """设置嵌套配置值"""
        keys = path.split(".")
        current = config
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
    
    def _get_nested_value(self, config: Dict[str, Any], path: str) -> Any:
        """获取嵌套配置值"""
        keys = path.split(".")
        current = config
        
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        
        return current
    
    def generate_trials(self, method: str = "grid", max_trials: Optional[int] = None) -> List[Dict[str, Any]]:
        """生成试验配置
        
        Args:
            method: 搜索方法（grid/random）
            max_trials: 最大试验次数（random模式）
        
        Returns:
            试验配置列表
        """
        import itertools
        import random
        
        base_config = self._load_config()
        trials = []
        
        if method == "grid":
            # 网格搜索：所有参数组合
            param_names = list(self.search_space.keys())
            param_values = [self.search_space[name] for name in param_names]
            
            all_combinations = list(itertools.product(*param_values))
            total_combinations = len(all_combinations)
            
            # 如果设置了max_trials，限制组合数量（随机选择前N个）
            if max_trials is not None and max_trials < total_combinations:
                import random
                random.shuffle(all_combinations)
                all_combinations = all_combinations[:max_trials]
                logger.info(f"[ParameterOptimizer] Grid搜索限制为前{max_trials}个组合（共{total_combinations}个）")
            elif max_trials is not None:
                logger.info(f"[ParameterOptimizer] Grid搜索: {total_combinations}个组合（max_trials={max_trials}，未限制）")
            else:
                logger.info(f"[ParameterOptimizer] Grid搜索: {total_combinations}个组合（未设置max_trials限制）")
            
            for combination in all_combinations:
                trial_config = copy.deepcopy(base_config)
                trial_params = {}
                
                for name, value in zip(param_names, combination):
                    self._set_nested_value(trial_config, name, value)
                    trial_params[name] = value
                
                # F2修复: 确保w_ofi + w_cvd = 1.0约束
                # 如果search_space中包含w_ofi，自动调整w_cvd使其和为1.0
                if "components.fusion.w_ofi" in trial_params:
                    w_ofi = trial_params["components.fusion.w_ofi"]
                    # 获取当前w_cvd（可能来自trial_params或基线配置）
                    w_cvd = trial_params.get("components.fusion.w_cvd")
                    if w_cvd is None:
                        w_cvd = self._get_nested_value(trial_config, "components.fusion.w_cvd")
                    
                    # 如果w_cvd存在但w_ofi + w_cvd != 1.0，调整w_cvd
                    # 如果w_cvd不存在，自动设置为1-w_ofi
                    if w_cvd is None or abs(w_ofi + w_cvd - 1.0) > 1e-6:
                        w_cvd_adjusted = 1.0 - w_ofi
                        self._set_nested_value(trial_config, "components.fusion.w_cvd", w_cvd_adjusted)
                        trial_params["components.fusion.w_cvd"] = w_cvd_adjusted
                        if w_cvd is not None:
                            logger.debug(f"[ParameterOptimizer] F2约束: 调整w_cvd {w_cvd} -> {w_cvd_adjusted} (w_ofi={w_ofi})")
                        else:
                            logger.debug(f"[ParameterOptimizer] F2约束: 自动设置w_cvd={w_cvd_adjusted} (w_ofi={w_ofi})")
                
                trials.append({
                    "config": trial_config,
                    "params": trial_params,
                })
        
        elif method == "random":
            # 随机搜索
            if max_trials is None:
                max_trials = 30
            
            for i in range(max_trials):
                trial_config = copy.deepcopy(base_config)
                trial_params = {}
                
                for name, values in self.search_space.items():
                    value = random.choice(values)
                    self._set_nested_value(trial_config, name, value)
                    trial_params[name] = value
                
                # F2修复: 确保w_ofi + w_cvd = 1.0约束
                # 如果search_space中包含w_ofi，自动调整w_cvd使其和为1.0
                if "components.fusion.w_ofi" in trial_params:
                    w_ofi = trial_params["components.fusion.w_ofi"]
                    # 获取当前w_cvd（可能来自trial_params或基线配置）
                    w_cvd = trial_params.get("components.fusion.w_cvd")
                    if w_cvd is None:
                        w_cvd = self._get_nested_value(trial_config, "components.fusion.w_cvd")
                    
                    # 如果w_cvd存在但w_ofi + w_cvd != 1.0，调整w_cvd
                    # 如果w_cvd不存在，自动设置为1-w_ofi
                    if w_cvd is None or abs(w_ofi + w_cvd - 1.0) > 1e-6:
                        w_cvd_adjusted = 1.0 - w_ofi
                        self._set_nested_value(trial_config, "components.fusion.w_cvd", w_cvd_adjusted)
                        trial_params["components.fusion.w_cvd"] = w_cvd_adjusted
                        if w_cvd is not None:
                            logger.debug(f"[ParameterOptimizer] F2约束: 调整w_cvd {w_cvd} -> {w_cvd_adjusted} (w_ofi={w_ofi})")
                        else:
                            logger.debug(f"[ParameterOptimizer] F2约束: 自动设置w_cvd={w_cvd_adjusted} (w_ofi={w_ofi})")
                
                trials.append({
                    "config": trial_config,
                    "params": trial_params,
                })
        
        logger.info(f"[ParameterOptimizer] 生成 {len(trials)} 个试验配置（方法: {method}）")
        return trials
    
    def run_trial(
        self,
        trial_config: Dict[str, Any],
        trial_id: int,
        backtest_args: Dict[str, Any],
        val_dates: Optional[List[str]] = None,  # Walk-forward验证：验证日期列表
        multi_window_dates: Optional[List[str]] = None,  # P1修复: 多窗口交叉验证：可用日期列表
    ) -> Dict[str, Any]:
        """运行单个试验"""
        logger.info(f"[ParameterOptimizer] 运行试验 {trial_id}...")
        
        # 保存试验配置
        trial_config_file = self.output_dir / f"trial_{trial_id}_config.yaml"
        self._save_config(trial_config, trial_config_file)
        
        # Fix 8: 根据runner选择命令
        if self.runner == "replay_harness":
            cmd = [
                sys.executable,
                "scripts/replay_harness.py",
                "--input", str(backtest_args.get("input", "deploy/data/ofi_cvd")),
                "--date", str(backtest_args.get("date", "2025-11-09")),
                "--symbols", ",".join(backtest_args.get("symbols", ["BTCUSDT"])),
                "--kinds", "features",
                "--config", str(trial_config_file),
                "--output", str(self.output_dir / f"trial_{trial_id}"),
            ]
            if backtest_args.get("minutes"):
                cmd.extend(["--minutes", str(backtest_args["minutes"])])
            # TASK-07B: 固定Sink类型（优化期必须固定）
            sink_type = backtest_args.get("sink", "sqlite")
            cmd.extend(["--sink", sink_type])
        elif self.runner == "orchestrator":
            trial_dir = self.output_dir / f"trial_{trial_id}"
            trial_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable,
                "-m", "orchestrator.run",
                "--config", str(trial_config_file),
                "--enable", "harvest,signal,broker",
                # 如果orchestrator支持--output参数，可添加：
                # "--output", str(trial_dir),
            ]
        else:
            raise ValueError(f"未知的runner: {self.runner}")
        
        logger.info(f"  运行命令: {' '.join(cmd)}")
        
        # 修复：为orchestrator统一输出路径（通过环境变量）
        # P1修复: 清理/显式注入时区和日切参数，避免环境变量误改
        env = os.environ.copy()
        # 从trial_config获取时区和日切参数，显式注入到环境变量（覆盖系统环境变量）
        backtest_config = trial_config.get("backtest", {})
        rollover_tz = backtest_config.get("rollover_timezone", "UTC")
        rollover_hour = backtest_config.get("rollover_hour", 0)
        env["ROLLOVER_TZ"] = str(rollover_tz)
        env["ROLLOVER_HOUR"] = str(rollover_hour)
        # 清理可能冲突的环境变量（如果存在）
        if "ROLLOVER_TIMEZONE" in env:
            del env["ROLLOVER_TIMEZONE"]
        if self.runner == "orchestrator":
            env["BACKTEST_OUTPUT_DIR"] = str(trial_dir)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        
        # Fix 10: 保存stderr到文件
        if result.returncode != 0:
            stderr_file = self.output_dir / f"trial_{trial_id}_stderr.txt"
            with open(stderr_file, "w", encoding="utf-8") as f:
                f.write(result.stderr)
            logger.error(f"  试验 {trial_id} 失败，退出码: {result.returncode}")
            logger.error(f"  错误信息已保存: {stderr_file}")
            return {
                "trial_id": trial_id,
                "success": False,
                "error": result.stderr[:500] if result.stderr else "Unknown error",
                "stderr_file": str(stderr_file),
                "command": " ".join(cmd),  # Fix 8: 记录实际使用的命令
            }
        
        # 加载结果
        trial_output_dir = self.output_dir / f"trial_{trial_id}"
        subdirs = list(trial_output_dir.glob("backtest_*"))
        if not subdirs:
            logger.error(f"  试验 {trial_id} 未找到结果目录")
            return {
                "trial_id": trial_id,
                "success": False,
                "error": "No result directory found",
            }
        
        result_dir = subdirs[0]
        metrics_file = result_dir / "metrics.json"
        
        if not metrics_file.exists():
            logger.error(f"  试验 {trial_id} 未找到metrics.json")
            return {
                "trial_id": trial_id,
                "success": False,
                "error": "No metrics.json found",
            }
        
        with open(metrics_file, "r", encoding="utf-8") as f:
            metrics = json.load(f)
        
        # P2修复: 读取run_manifest.json获取质量指标和sample_files
        run_manifest_file = result_dir / "run_manifest.json"
        aligner_stats = None
        reader_sample_files = []
        effective_params = {}
        if run_manifest_file.exists():
            try:
                with open(run_manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    # 获取aligner质量指标
                    aligner_stats = manifest.get("aligner_stats")
                    # 获取reader的sample_files
                    reader_stats_manifest = manifest.get("reader_stats", {})
                    reader_sample_files = reader_stats_manifest.get("sample_files", [])
                    # 获取生效参数快照
                    effective_params = manifest.get("effective_params", {})
            except Exception as e:
                logger.debug(f"  读取run_manifest.json失败: {e}")
        
        # P2修复: 将质量指标添加到metrics（用于质量→收益串联）
        if aligner_stats:
            metrics["aligner_gap_seconds_rate"] = aligner_stats.get("gap_seconds_rate", 0)
            metrics["aligner_lag_bad_rate"] = max(
                aligner_stats.get("lag_bad_price_rate", 0),
                aligner_stats.get("lag_bad_orderbook_rate", 0)
            )
        
        # B.3: 结果健壮性卫兵（unknown场景阈值 & 样本阈值）
        total_trades = metrics.get("total_trades", 0)
        unknown_ratio = metrics.get("unknown_scenario_ratio", 0)  # 需要从报表或metrics中获取
        
        # 检查unknown占比（如果metrics中没有，尝试从trades.jsonl计算）
        trades_file = result_dir / "trades.jsonl"
        if trades_file.exists():
            try:
                unknown_count = 0
                total_scenario_trades = 0
                with open(trades_file, "r", encoding="utf-8") as f:
                    for line in f:
                        trade = json.loads(line.strip())
                        scenario = trade.get("scenario_2x2")
                        if scenario:
                            total_scenario_trades += 1
                            from alpha_core.report.summary import _normalize_scenario
                            if _normalize_scenario(scenario) == "unknown":
                                unknown_count += 1
                if total_scenario_trades > 0:
                    unknown_ratio = unknown_count / total_scenario_trades
            except Exception as e:
                logger.debug(f"  计算unknown占比失败: {e}")
        
        # B.3: 健壮性检查
        robustness_warnings = []
        if unknown_ratio > 0.05:  # unknown占比 > 5%
            robustness_warnings.append(f"unknown_ratio_high:{unknown_ratio:.2%}")
        if total_trades < 10:  # 样本数 < 10
            robustness_warnings.append(f"low_sample:{total_trades}")
        
        logger.info(f"  试验 {trial_id} 完成: PnL=${metrics.get('total_pnl', 0):.2f}, 胜率={metrics.get('win_rate', 0)*100:.2f}%, 交易数={total_trades}")
        if robustness_warnings:
            logger.warning(f"  试验 {trial_id} 健壮性警告: {', '.join(robustness_warnings)}")
        
        result = {
            "trial_id": trial_id,
            "success": True,
            "metrics": metrics,
            "config_file": str(trial_config_file),
            "output_dir": str(result_dir),
            "command": " ".join(cmd),  # Fix 8: 记录实际使用的命令
            "unknown_ratio": unknown_ratio,  # B.3: 记录unknown占比
            "robustness_warnings": robustness_warnings,  # B.3: 记录健壮性警告
            # P2修复: 记录质量指标和诊断信息
            "reader_sample_files": reader_sample_files,  # P2: Reader命中样例文件（前3个）
            "effective_params": effective_params,  # P2: 生效参数快照
        }
        
        # Walk-forward验证：如果有验证日期，运行验证回测
        val_metrics = None
        if val_dates:
            val_metrics = self._run_validation_trial(
                trial_config,
                trial_id,
                backtest_args,
                val_dates,
            )
        
        # Walk-forward验证：添加验证指标
        if val_metrics:
            result["val_metrics"] = val_metrics
            # 多品种公平权重：传入trial_result
            train_score = self._calculate_score(metrics, metrics.get("total_pnl", 0) - metrics.get("total_fee", 0) - metrics.get("total_slippage", 0), self.scoring_weights, trial_result=result)
            # 验证集评分：创建临时的val_trial_result
            val_trial_result = {"metrics": val_metrics, "output_dir": result.get("output_dir")}
            val_score = self._calculate_score(val_metrics, val_metrics.get("total_pnl", 0) - val_metrics.get("total_fee", 0) - val_metrics.get("total_slippage", 0), self.scoring_weights, trial_result=val_trial_result)
            result["train_score"] = train_score
            result["val_score"] = val_score
            result["generalization_gap"] = train_score - val_score
        
        # P1修复: 生成smoke_diff.md（Trial烟雾对比）
        try:
            self._generate_smoke_diff(result_dir, metrics, trial_id)
        except Exception as e:
            logger.warning(f"  生成smoke_diff.md失败: {e}")
        
        return result
    
    def _run_single_window_trial(
        self,
        trial_config: Dict[str, Any],
        trial_id: int,
        window_backtest_args: Dict[str, Any],
        window_idx: int,
    ) -> Dict[str, Any]:
        """P1修复: 运行单个窗口的回测（用于多窗口交叉验证）
        
        Args:
            trial_config: 试验配置
            trial_id: 试验ID
            window_backtest_args: 窗口回测参数（包含date和minutes）
            window_idx: 窗口索引
        
        Returns:
            窗口回测结果（简化版，只包含success和metrics）
        """
        # 创建临时输出目录
        window_output_dir = self.output_dir / f"trial_{trial_id}_window_{window_idx}"
        window_output_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存试验配置
        trial_config_file = window_output_dir / "config.yaml"
        self._save_config(trial_config, trial_config_file)
        
        # 构建回测命令
        if self.runner == "replay_harness":
            cmd = [
                sys.executable,
                "scripts/replay_harness.py",
                "--input", str(window_backtest_args.get("input", "deploy/data/ofi_cvd")),
                "--date", str(window_backtest_args.get("date", "2025-11-09")),
                "--symbols", ",".join(window_backtest_args.get("symbols", ["BTCUSDT"])),
                "--kinds", "features",
                "--config", str(trial_config_file),
                "--output", str(window_output_dir),
            ]
            if window_backtest_args.get("minutes"):
                cmd.extend(["--minutes", str(window_backtest_args["minutes"])])
            sink_type = window_backtest_args.get("sink", "sqlite")
            cmd.extend(["--sink", sink_type])
        else:
            logger.warning(f"  [多窗口交叉验证] Runner {self.runner} 不支持窗口回测")
            return {"success": False, "error": f"Runner {self.runner} not supported"}
        
        # 运行回测
        env = os.environ.copy()
        backtest_config = trial_config.get("backtest", {})
        rollover_tz = backtest_config.get("rollover_timezone", "UTC")
        rollover_hour = backtest_config.get("rollover_hour", 0)
        env["ROLLOVER_TZ"] = str(rollover_tz)
        env["ROLLOVER_HOUR"] = str(rollover_hour)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=300,  # 5分钟超时（窗口回测应该很快）
        )
        
        if result.returncode != 0:
            logger.debug(f"  [多窗口交叉验证] 窗口 {window_idx} 回测失败: {result.stderr[:200]}")
            return {"success": False, "error": result.stderr[:200] if result.stderr else "Unknown error"}
        
        # 加载结果
        subdirs = list(window_output_dir.glob("backtest_*"))
        if not subdirs:
            return {"success": False, "error": "No result directory found"}
        
        result_dir = subdirs[0]
        metrics_file = result_dir / "metrics.json"
        
        if not metrics_file.exists():
            return {"success": False, "error": "No metrics.json found"}
        
        with open(metrics_file, "r", encoding="utf-8") as f:
            metrics = json.load(f)
        
        return {
            "success": True,
            "metrics": metrics,
            "output_dir": str(result_dir),
        }
    
    def _run_validation_trial(
        self,
        trial_config: Dict[str, Any],
        trial_id: int,
        backtest_args: Dict[str, Any],
        val_dates: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Walk-forward验证：在验证日期上运行回测（支持多日期合并）
        
        Args:
            trial_config: 试验配置
            trial_id: 试验ID
            backtest_args: 回测参数
            val_dates: 验证日期列表
        
        Returns:
            验证集metrics（如果成功）或None（合并多个日期的结果）
        """
        if not val_dates:
            return None
        
        logger.info(f"  [Walk-forward] 试验 {trial_id} 验证回测（日期: {val_dates}）...")
        
        # 保存试验配置（复用训练配置）
        trial_config_file = self.output_dir / f"trial_{trial_id}_config.yaml"
        
        # 分别运行每个验证日期，然后合并结果
        all_val_metrics = []
        
        for idx, val_date in enumerate(val_dates):
            logger.info(f"  [Walk-forward] 验证日期 {idx+1}/{len(val_dates)}: {val_date}")
            
            # 构建验证回测命令
            if self.runner == "replay_harness":
                val_output_dir = self.output_dir / f"trial_{trial_id}_val" / f"date_{val_date}"
                cmd = [
                    sys.executable,
                    "scripts/replay_harness.py",
                    "--input", str(backtest_args.get("input", "deploy/data/ofi_cvd")),
                    "--date", str(val_date),
                    "--symbols", ",".join(backtest_args.get("symbols", ["BTCUSDT"])),
                    "--kinds", "features",
                    "--config", str(trial_config_file),
                    "--output", str(val_output_dir),
                ]
                if backtest_args.get("minutes"):
                    cmd.extend(["--minutes", str(backtest_args["minutes"])])
            else:
                logger.warning(f"  [Walk-forward] Runner {self.runner} 不支持验证回测")
                return None
            
            # 运行验证回测
            import subprocess
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    timeout=600,  # 10分钟超时
                )
                
                if result.returncode != 0:
                    logger.warning(f"  [Walk-forward] 验证日期 {val_date} 回测失败: {result.stderr[:200]}")
                    continue
                
                # 查找验证结果目录
                val_backtest_dirs = list(val_output_dir.glob("backtest_*"))
                if not val_backtest_dirs:
                    logger.warning(f"  [Walk-forward] 验证日期 {val_date} 未找到结果目录")
                    continue
                
                val_result_dir = max(val_backtest_dirs, key=lambda p: p.stat().st_mtime)
                val_metrics_file = val_result_dir / "metrics.json"
                
                if not val_metrics_file.exists():
                    logger.warning(f"  [Walk-forward] 验证日期 {val_date} metrics.json不存在")
                    continue
                
                # 加载验证metrics
                with open(val_metrics_file, "r", encoding="utf-8") as f:
                    date_metrics = json.load(f)
                
                all_val_metrics.append(date_metrics)
                logger.info(f"  [Walk-forward] 验证日期 {val_date} 完成: PnL=${date_metrics.get('total_pnl', 0):.2f}, 胜率={date_metrics.get('win_rate', 0)*100:.2f}%")
            
            except subprocess.TimeoutExpired:
                logger.warning(f"  [Walk-forward] 验证日期 {val_date} 回测超时")
                continue
            except Exception as e:
                logger.warning(f"  [Walk-forward] 验证日期 {val_date} 回测异常: {e}")
                continue
        
        # 合并多个日期的metrics
        if not all_val_metrics:
            logger.warning(f"  [Walk-forward] 所有验证日期回测均失败")
            return None
        
        merged_metrics = self._merge_metrics(all_val_metrics)
        logger.info(f"  [Walk-forward] 验证完成（合并{len(all_val_metrics)}个日期）: PnL=${merged_metrics.get('total_pnl', 0):.2f}, 胜率={merged_metrics.get('win_rate', 0)*100:.2f}%")
        return merged_metrics
    
    def _merge_metrics(self, metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并多个日期的metrics
        
        Args:
            metrics_list: 多个日期的metrics列表
        
        Returns:
            合并后的metrics
        """
        if not metrics_list:
            return {}
        
        if len(metrics_list) == 1:
            return metrics_list[0]
        
        # 合并策略：累加数值指标，加权平均比率指标
        merged = {}
        
        # 累加指标
        sum_keys = [
            "total_pnl", "net_pnl", "total_fee", "total_slippage",
            "total_trades", "winning_trades", "losing_trades",
            "turnover", "max_profit", "max_loss",
        ]
        for key in sum_keys:
            merged[key] = sum(m.get(key, 0) for m in metrics_list)
        
        # 加权平均指标（基于交易数）
        total_trades = merged.get("total_trades", 0)
        if total_trades > 0:
            # 胜率：加权平均
            merged["win_rate"] = sum(
                m.get("win_rate", 0) * m.get("total_trades", 0)
                for m in metrics_list
            ) / total_trades
            
            # 每笔交易PnL：加权平均
            merged["pnl_per_trade"] = sum(
                m.get("pnl_per_trade", 0) * m.get("total_trades", 0)
                for m in metrics_list
            ) / total_trades
        
        # 其他指标：简单平均或取最值
        merged["sharpe_ratio"] = sum(m.get("sharpe_ratio", 0) for m in metrics_list) / len(metrics_list)
        merged["max_drawdown"] = min(m.get("max_drawdown", 0) for m in metrics_list)  # 取最差回撤
        
        # 每小时交易数：加权平均
        total_hours = sum(m.get("trades_per_hour", 0) * m.get("total_trades", 0) for m in metrics_list)
        if total_trades > 0:
            merged["trades_per_hour"] = total_trades / (total_hours / total_trades) if total_hours > 0 else 0
        else:
            merged["trades_per_hour"] = 0
        
        # 成本占比：重新计算
        total_pnl = merged.get("total_pnl", 0)
        if total_pnl != 0:
            merged["cost_ratio"] = (merged.get("total_fee", 0) + merged.get("total_slippage", 0)) / abs(total_pnl)
        else:
            merged["cost_ratio"] = 0
        
        # 保留其他字段（如果有）
        for key in metrics_list[0].keys():
            if key not in merged:
                merged[key] = metrics_list[0][key]
        
        return merged
    
    def optimize(
        self,
        backtest_args: Dict[str, Any],
        method: str = "grid",
        max_trials: Optional[int] = None,
        max_workers: int = 1,
        early_stop_rounds: Optional[int] = None,
        resume: bool = True,
        walk_forward_dates: Optional[List[str]] = None,  # Walk-forward验证：可用日期列表
        train_ratio: float = 0.5,  # Walk-forward验证：训练集比例
        walk_forward_step: int = 1,  # Walk-forward验证：走步大小
        multi_window_dates: Optional[List[str]] = None,  # P1修复: 多窗口交叉验证：可用日期列表
        use_successive_halving: bool = False,  # P1修复: 是否使用Successive Halving
        sh_eta: int = 3,  # P1修复: Successive Halving的eta参数（淘汰比例）
        sh_min_budget: int = 1,  # P1修复: Successive Halving的最小预算（分钟数）
    ) -> List[Dict[str, Any]]:
        """执行参数优化
        
        B.1改进: 并行化 + 早停 + 断点续跑
        - max_workers: 并行worker数（默认1，串行）
        - early_stop_rounds: 早停轮数（随机搜索时，N轮无提升则停止）
        - resume: 是否断点续跑（读取已有trial_results.json）
        
        P1修复: 多窗口交叉验证 + Successive Halving
        - multi_window_dates: 多窗口交叉验证的日期列表（≥3个时间片）
        - use_successive_halving: 是否使用Successive Halving逐级淘汰
        - sh_eta: Successive Halving的eta参数（淘汰比例，默认3）
        - sh_min_budget: Successive Halving的最小预算（分钟数，默认1）
        """
        logger.info("=" * 80)
        logger.info("参数优化")
        logger.info("=" * 80)
        
        # P1修复: 保存backtest_args到实例变量，用于manifest记录
        self.backtest_args = backtest_args
        
        # 多品种公平权重：验证口径一致性
        if self.use_multi_symbol_scoring:
            self._validate_multi_symbol_consistency(backtest_args)
        
        # B.1: 断点续跑
        existing_results = []
        if resume:
            results_file = self.output_dir / "trial_results.json"
            if results_file.exists():
                try:
                    with open(results_file, "r", encoding="utf-8") as f:
                        existing_results = json.load(f)
                    logger.info(f"[ParameterOptimizer] 读取已有结果: {len(existing_results)} 个trial")
                except Exception as e:
                    logger.warning(f"[ParameterOptimizer] 读取已有结果失败: {e}")
        
        # 生成试验配置
        trials = self.generate_trials(method=method, max_trials=max_trials)
        
        # B.1: 跳过已完成的trial
        completed_ids = {r.get("trial_id") for r in existing_results if r.get("success")}
        pending_trials = [(i, t) for i, t in enumerate(trials, 1) if i not in completed_ids]
        
        if not pending_trials:
            logger.info("[ParameterOptimizer] 所有trial已完成，无需重新运行")
            self.trial_results = existing_results
            self._print_recommendations()
            return existing_results
        
        logger.info(f"[ParameterOptimizer] 待运行trial数: {len(pending_trials)}/{len(trials)}")
        
        # P1修复: 多窗口交叉验证
        if multi_window_dates and len(multi_window_dates) >= 3:
            logger.info(f"[ParameterOptimizer] 启用多窗口交叉验证: {len(multi_window_dates)} 个时间片")
        elif multi_window_dates:
            logger.warning(f"[ParameterOptimizer] 多窗口交叉验证需要≥3个时间片，当前只有{len(multi_window_dates)}个，将禁用")
            multi_window_dates = None
        
        # P1修复: Successive Halving
        if use_successive_halving:
            logger.info(f"[ParameterOptimizer] 启用Successive Halving (eta={sh_eta}, min_budget={sh_min_budget}分钟)")
            if method != "random":
                logger.warning(f"[ParameterOptimizer] Successive Halving建议与random搜索配合使用")
        
        # Walk-forward验证：如果提供了日期列表，生成折叠
        walk_forward_folds = None
        val_dates_for_trials = None
        if walk_forward_dates and len(walk_forward_dates) >= 2:
            from alpha_core.report.walk_forward import WalkForwardValidator
            
            validator = WalkForwardValidator(
                dates=walk_forward_dates,
                train_ratio=train_ratio,
                step_size=walk_forward_step,
            )
            walk_forward_folds = validator.generate_folds()
            logger.info(f"[ParameterOptimizer] Walk-forward验证: {len(walk_forward_folds)} 个折叠")
            
            # 使用第一个折叠的验证日期（简化实现）
            if walk_forward_folds:
                _, val_dates_for_trials = walk_forward_folds[0]
                logger.info(f"[ParameterOptimizer] 使用验证日期: {val_dates_for_trials}")
        
        # B.1: 并行化运行
        if max_workers > 1:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            
            results = list(existing_results)
            best_score = -1e9
            stall = 0
            
            # 计算已有结果的最佳score
            for r in existing_results:
                if r.get("success"):
                    m = r.get("metrics", {})
                    tp = m.get("total_pnl", 0)
                    tf = m.get("total_fee", 0)
                    ts = m.get("total_slippage", 0)
                    np = tp - tf - ts
                    # 多品种公平权重：传入trial_result
                    s = self._calculate_score(m, np, self.scoring_weights, trial_result=r)
                    if s > best_score:
                        best_score = s
            
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有trial
                future_to_trial = {}
                for trial_id, trial in pending_trials:
                    # 注意：ProcessPoolExecutor需要可序列化的函数
                    # 这里简化处理，实际应该将run_trial提取为独立函数
                    # Walk-forward验证：传递验证日期
                    future = executor.submit(self._run_trial_wrapper, trial["config"], trial_id, backtest_args, val_dates_for_trials)
                    future_to_trial[future] = (trial_id, trial)
                
                # 收集结果
                for future in as_completed(future_to_trial):
                    trial_id, trial = future_to_trial[future]
                    try:
                        result = future.result()
                        result["params"] = trial["params"]
                        results.append(result)
                        
                        # 计算并保存score
                        if result.get("success"):
                            m = result.get("metrics", {})
                            tp = m.get("total_pnl", 0)
                            tf = m.get("total_fee", 0)
                            ts = m.get("total_slippage", 0)
                            np = tp - tf - ts
                            # 多品种公平权重：传入trial_result
                            result["score"] = self._calculate_score(m, np, self.scoring_weights, trial_result=result)
                        
                        # B.1: 增量保存
                        self.trial_results = results
                        self._save_results()
                        
                        # B.1: 早停检查（仅随机搜索）
                        if result.get("success") and method == "random" and early_stop_rounds:
                            m = result.get("metrics", {})
                            tp = m.get("total_pnl", 0)
                            tf = m.get("total_fee", 0)
                            ts = m.get("total_slippage", 0)
                            np = tp - tf - ts
                            # 多品种公平权重：传入trial_result
                            s = self._calculate_score(m, np, self.scoring_weights, trial_result=result)
                            if s > best_score:
                                best_score = s
                                stall = 0
                            else:
                                stall += 1
                            
                            if stall >= early_stop_rounds:
                                logger.info(f"[ParameterOptimizer] 早停触发: {early_stop_rounds}轮无提升")
                                break
                    except Exception as e:
                        logger.error(f"[ParameterOptimizer] Trial {trial_id} 执行失败: {e}")
                        results.append({
                            "trial_id": trial_id,
                            "success": False,
                            "error": str(e),
                            "params": trial["params"],
                        })
        else:
            # 串行运行（原有逻辑）
            results = list(existing_results)
            best_score = -1e9
            stall = 0
            
            # P1修复: Successive Halving逐级淘汰
            if use_successive_halving and method == "random":
                sh_results = self._run_successive_halving(
                    pending_trials,
                    backtest_args,
                    val_dates_for_trials,
                    multi_window_dates,
                    sh_eta,
                    sh_min_budget,
                )
                results.extend(sh_results)
            else:
                # 标准运行流程
                for trial_id, trial in pending_trials:
                    # Walk-forward验证：传递验证日期
                    # P1修复: 多窗口交叉验证：传递multi_window_dates
                    result = self.run_trial(
                        trial["config"],
                        trial_id,
                        backtest_args,
                        val_dates_for_trials,
                        multi_window_dates,  # P1修复: 传递多窗口日期
                    )
                    result["params"] = trial["params"]
                    results.append(result)
                    
                    # 计算并保存score
                    if result.get("success"):
                        m = result.get("metrics", {})
                        tp = m.get("total_pnl", 0)
                        tf = m.get("total_fee", 0)
                        ts = m.get("total_slippage", 0)
                        np = tp - tf - ts
                        # 多品种公平权重：传入trial_result
                        result["score"] = self._calculate_score(m, np, self.scoring_weights, trial_result=result)
                    
                    # B.1: 增量保存
                    self.trial_results = results
                    self._save_results()
                    
                    # B.1: 早停检查（仅随机搜索）
                    if result.get("success") and method == "random" and early_stop_rounds:
                        m = result.get("metrics", {})
                        tp = m.get("total_pnl", 0)
                        tf = m.get("total_fee", 0)
                        ts = m.get("total_slippage", 0)
                        np = tp - tf - ts
                        # 多品种公平权重：传入trial_result
                        s = self._calculate_score(m, np, self.scoring_weights, trial_result=result)
                        if s > best_score:
                            best_score = s
                            stall = 0
                        else:
                            stall += 1
                        
                        if stall >= early_stop_rounds:
                            logger.info(f"[ParameterOptimizer] 早停触发: {early_stop_rounds}轮无提升")
                            break  # 跳出for循环
        
        self.trial_results = results
        
        # 保存结果
        self._save_results()
        
        # 生成Pareto前沿（如果trial数量足够）
        if len(self.trial_results) >= 5:
            self._generate_pareto_front()
        
        # 输出推荐参数
        self._print_recommendations()
        
        return results
    
    def _run_successive_halving(
        self,
        pending_trials: List[tuple],
        backtest_args: Dict[str, Any],
        val_dates: Optional[List[str]],
        multi_window_dates: Optional[List[str]],
        eta: int = 3,
        min_budget: int = 1,
    ) -> List[Dict[str, Any]]:
        """P1修复: Successive Halving逐级淘汰
        
        Args:
            pending_trials: 待运行的trial列表
            backtest_args: 回测参数
            val_dates: 验证日期列表
            multi_window_dates: 多窗口日期列表
            eta: 淘汰比例（每轮保留1/eta）
            min_budget: 最小预算（分钟数）
        
        Returns:
            最终结果列表
        """
        logger.info(f"[Successive Halving] 开始逐级淘汰 (eta={eta}, min_budget={min_budget}分钟)")
        
        # 计算预算级别（从min_budget开始，逐步增加）
        original_minutes = backtest_args.get("minutes")
        if original_minutes:
            max_budget = original_minutes
        else:
            max_budget = 60  # 默认60分钟
        
        # 计算预算级别数量
        budget_levels = []
        budget = min_budget
        while budget <= max_budget:
            budget_levels.append(budget)
            budget = int(budget * eta)
        
        logger.info(f"[Successive Halving] 预算级别: {budget_levels}")
        
        # 当前保留的trial
        current_trials = list(pending_trials)
        all_results = []
        
        # 逐级运行
        for level_idx, budget_minutes in enumerate(budget_levels):
            logger.info(f"[Successive Halving] 级别 {level_idx+1}/{len(budget_levels)}: 预算={budget_minutes}分钟, trial数={len(current_trials)}")
            
            # 运行当前级别的trial
            level_results = []
            level_backtest_args = backtest_args.copy()
            level_backtest_args["minutes"] = budget_minutes
            
            for trial_id, trial in current_trials:
                result = self.run_trial(
                    trial["config"],
                    trial_id,
                    level_backtest_args,
                    val_dates,
                    multi_window_dates,
                )
                result["params"] = trial["params"]
                result["sh_level"] = level_idx + 1
                result["sh_budget"] = budget_minutes
                level_results.append((trial_id, trial, result))
                all_results.append(result)
            
            # 如果不是最后一级，进行淘汰
            if level_idx < len(budget_levels) - 1:
                # 计算每个trial的评分
                for trial_id, trial, result in level_results:
                    if result.get("success"):
                        m = result.get("metrics", {})
                        tp = m.get("total_pnl", 0)
                        tf = m.get("total_fee", 0)
                        ts = m.get("total_slippage", 0)
                        np = tp - tf - ts
                        result["score"] = self._calculate_score(m, np, self.scoring_weights, trial_result=result)
                
                # 按评分排序，保留前1/eta
                level_results.sort(key=lambda x: x[2].get("score", -1e9), reverse=True)
                keep_count = max(1, len(level_results) // eta)
                current_trials = [(tid, t) for tid, t, _ in level_results[:keep_count]]
                
                logger.info(f"[Successive Halving] 级别 {level_idx+1} 完成: 保留 {keep_count}/{len(level_results)} 个trial")
            else:
                logger.info(f"[Successive Halving] 最后级别完成: 所有 {len(level_results)} 个trial运行完成")
        
        return all_results
    
    def _validate_multi_symbol_consistency(self, backtest_args: Dict[str, Any]) -> None:
        """多品种公平权重：验证口径一致性
        
        检查多品种优化时的关键参数是否一致，确保"等权"的公平性
        """
        base_config = self._load_config()
        backtest_config = base_config.get("backtest", {})
        
        # 检查notional_per_trade
        notional_per_trade = backtest_config.get("notional_per_trade")
        if notional_per_trade is None:
            logger.warning("[ParameterOptimizer] 多品种优化: notional_per_trade未配置，建议固定为1000")
        else:
            logger.info(f"[ParameterOptimizer] 多品种优化: notional_per_trade={notional_per_trade}（所有品种使用相同名义）")
        
        # 检查rollover_timezone
        rollover_timezone = backtest_config.get("rollover_timezone", "UTC")
        if rollover_timezone != "UTC":
            logger.warning(f"[ParameterOptimizer] 多品种优化: rollover_timezone={rollover_timezone}，建议固定为UTC")
        else:
            logger.info(f"[ParameterOptimizer] 多品种优化: rollover_timezone={rollover_timezone}（统一时区）")
        
        # 检查rollover_hour
        rollover_hour = backtest_config.get("rollover_hour", 0)
        if rollover_hour != 0:
            logger.warning(f"[ParameterOptimizer] 多品种优化: rollover_hour={rollover_hour}，建议固定为0")
        else:
            logger.info(f"[ParameterOptimizer] 多品种优化: rollover_hour={rollover_hour}（统一切日时间）")
        
        # 检查ignore_gating_in_backtest
        ignore_gating = backtest_config.get("ignore_gating_in_backtest", True)
        if not ignore_gating:
            logger.warning(f"[ParameterOptimizer] 多品种优化: ignore_gating_in_backtest={ignore_gating}，建议固定为true")
        else:
            logger.info(f"[ParameterOptimizer] 多品种优化: ignore_gating_in_backtest={ignore_gating}（统一门控开关）")
    
    def _run_trial_wrapper(
        self,
        trial_config: Dict[str, Any],
        trial_id: int,
        backtest_args: Dict[str, Any],
        val_dates: Optional[List[str]] = None,
        multi_window_dates: Optional[List[str]] = None,  # P1修复: 多窗口交叉验证
    ) -> Dict[str, Any]:
        """B.1: Trial运行包装器（用于ProcessPoolExecutor）
        
        Walk-forward验证：支持传递验证日期
        P1修复: 多窗口交叉验证：支持传递多窗口日期
        """
        return self.run_trial(trial_config, trial_id, backtest_args, val_dates, multi_window_dates)
    
    def _save_results(self):
        """保存试验结果
        
        B.4改进: 添加可复现信息到manifest
        """
        results_file = self.output_dir / "trial_results.json"
        
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(self.trial_results, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[ParameterOptimizer] 结果已保存: {results_file}")
        
        # B.4: 保存可复现信息到manifest
        self._save_manifest()
        
        # 生成CSV对比表
        self._generate_comparison_csv()
    
    def _save_manifest(self):
        """B.4: 保存可复现信息到manifest"""
        import hashlib
        import subprocess
        
        manifest_file = self.output_dir / "trial_manifest.json"
        
        # 获取git commit hash
        git_sha = "unknown"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=Path(__file__).parent.parent.parent
            )
            if result.returncode == 0:
                git_sha = result.stdout.strip()
        except Exception:
            pass
        
        # 计算search_space的hash
        search_space_str = json.dumps(self.search_space, sort_keys=True, ensure_ascii=False)
        search_space_hash = hashlib.sha256(search_space_str.encode("utf-8")).hexdigest()[:8]
        
        # 加载base_config以获取口径参数
        base_config = self._load_config()
        backtest_config = base_config.get("backtest", {})
        
        # P1修复: 获取数据窗信息（确保一致性）
        data_window_info = {}
        if hasattr(self, "backtest_args") and self.backtest_args:
            data_window_info = {
                "input": self.backtest_args.get("input", "deploy/data/ofi_cvd"),
                "date": self.backtest_args.get("date"),
                "symbols": self.backtest_args.get("symbols", []),
                "minutes": self.backtest_args.get("minutes"),
                "kinds": "features",  # 固定为features（ready源）
            }
        
        manifest = {
            "git_sha": git_sha,
            "search_space_hash": search_space_hash,
            "search_space": self.search_space,
            "scoring_weights": self.scoring_weights,  # 记录评分权重
            "runner": self.runner,
            "base_config": str(self.base_config_path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_trials": len(self.trial_results),
            "successful_trials": sum(1 for r in self.trial_results if r.get("success")),
            # 多品种公平权重：记录symbols
            "symbols": self.symbols,
            "use_multi_symbol_scoring": self.use_multi_symbol_scoring,
            # P1修复: 数据窗一致性：记录数据来源和窗口（确保历史结果可横向对比）
            "data_window": data_window_info,
            # 口径一致性：记录关键参数（确保历史结果可横向对比）
            "backtest_config": {
                "notional_per_trade": backtest_config.get("notional_per_trade"),
                "rollover_timezone": backtest_config.get("rollover_timezone", "UTC"),
                "rollover_hour": backtest_config.get("rollover_hour", 0),
                "ignore_gating_in_backtest": backtest_config.get("ignore_gating_in_backtest", True),
                "taker_fee_bps": backtest_config.get("taker_fee_bps"),
                "slippage_bps": backtest_config.get("slippage_bps"),
            },
        }
        
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[ParameterOptimizer] Manifest已保存: {manifest_file}")
    
    def _generate_comparison_csv(self):
        """生成CSV对比表"""
        import csv
        
        csv_file = self.output_dir / "trial_results.csv"
        
        if not self.trial_results:
            return
        
        # 获取所有参数名
        param_names = set()
        for result in self.trial_results:
            if result.get("success") and "params" in result:
                param_names.update(result["params"].keys())
        
        param_names = sorted(param_names)
        
        # P2修复: 预先计算所有trial的评分，避免在循环中重复计算（O(n²) -> O(n)）
        # 如果使用多品种评分，需要预先计算所有trial的等权评分
        successful_results = [r for r in self.trial_results if r.get("success")]
        if self.use_multi_symbol_scoring and len(successful_results) >= 2:
            try:
                from alpha_core.report.multi_symbol_scorer import MultiSymbolScorer
                scorer = MultiSymbolScorer(self.symbols)
                # 预先计算所有trial的等权评分
                for r in successful_results:
                    if "equal_weight_score" not in r:
                        try:
                            multi_result = scorer.calculate_equal_weight_score(r)
                            if multi_result.get("symbol_count", 0) > 0:
                                r["equal_weight_score"] = multi_result.get("equal_weight_score", 0)
                                r["per_symbol_metrics"] = multi_result.get("per_symbol_metrics", {})
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"预计算多品种评分失败: {e}")
        
        # 写入CSV
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            
            # 表头（A.1/B.3改进：添加成交额口径成本占比和unknown占比；Walk-forward：添加训练/验证指标；多品种公平权重：添加等权评分；P0修复：添加交易口径胜率和成本bps；P2修复：添加质量指标）
            header = ["trial_id", "success"] + param_names + [
                "total_pnl", "net_pnl", "win_rate", "win_rate_trades", "sharpe_ratio", "max_drawdown", "total_trades",
                "total_fee", "total_slippage", "cost_ratio", "cost_ratio_notional", "cost_bps_on_turnover", "turnover",
                "trades_per_hour", "pnl_per_trade", "unknown_ratio", "robustness_warnings",
                "aligner_gap_seconds_rate", "aligner_lag_bad_rate",  # P2修复: 质量指标
                "score", "equal_weight_score", "per_symbol_metrics",  # 多品种公平权重
                "train_score", "val_score", "generalization_gap", "error"  # Walk-forward: 训练/验证指标
            ]
            writer.writerow(header)
            
            # 数据行
            for result in self.trial_results:
                row = [result.get("trial_id", ""), result.get("success", False)]
                
                # 参数值
                params = result.get("params", {})
                for param_name in param_names:
                    row.append(params.get(param_name, ""))
                
                # 指标值
                metrics = result.get("metrics", {})
                total_pnl = metrics.get("total_pnl", 0)
                total_fee = metrics.get("total_fee", 0)
                total_slippage = metrics.get("total_slippage", 0)
                net_pnl = total_pnl - total_fee - total_slippage
                
                # Fix 9: 计算多目标综合分（多品种公平权重：传入trial_result）
                # P2修复: 如果已经预计算了equal_weight_score，直接使用；否则计算
                score = result.get("score")  # 尝试使用已计算的score
                if score is None and result.get("success"):
                    score = self._calculate_score(metrics, net_pnl, self.scoring_weights, trial_result=result)
                
                # 计算额外指标
                total_trades = metrics.get("total_trades", 0)
                # 假设24小时回测（1440分钟），计算每小时交易数
                trades_per_hour = total_trades / 24.0 if total_trades > 0 else 0
                pnl_per_trade = net_pnl / total_trades if total_trades > 0 else 0
                
                # A.1: 计算成交额口径成本占比
                turnover = metrics.get("turnover", 0)
                cost_ratio = (total_fee + total_slippage) / abs(total_pnl) if total_pnl != 0 else 0
                cost_ratio_notional = (total_fee + total_slippage) / max(1.0, turnover) if turnover > 0 else 0
                # P0修复: 计算成本bps（稳定口径）
                cost_bps_on_turnover = metrics.get("cost_bps_on_turnover", 0)
                
                # B.3: 获取unknown占比和健壮性警告
                unknown_ratio = result.get("unknown_ratio", 0)
                robustness_warnings = result.get("robustness_warnings", [])
                robustness_warnings_str = "; ".join(robustness_warnings) if robustness_warnings else ""
                
                # 多品种公平权重：获取等权评分和per_symbol_metrics
                equal_weight_score = result.get("equal_weight_score", "")
                per_symbol_metrics = result.get("per_symbol_metrics", {})
                per_symbol_metrics_str = json.dumps(per_symbol_metrics, ensure_ascii=False) if per_symbol_metrics else ""
                
                row.extend([
                    total_pnl,
                    net_pnl,
                    metrics.get("win_rate", 0),  # 日口径（兼容保留）
                    metrics.get("win_rate_trades", 0),  # P0修复: 交易口径胜率
                    metrics.get("sharpe_ratio", 0),
                    metrics.get("max_drawdown", 0),
                    total_trades,
                    total_fee,
                    total_slippage,
                    cost_ratio,
                    cost_ratio_notional,  # A.1: 成交额口径成本占比
                    cost_bps_on_turnover,  # P0修复: 成本bps（稳定口径）
                    turnover,  # A.1: 成交额
                    trades_per_hour,
                    pnl_per_trade,
                    unknown_ratio,  # B.3: unknown占比
                    robustness_warnings_str,  # B.3: 健壮性警告
                    metrics.get("aligner_gap_seconds_rate", ""),  # P2修复: 质量指标
                    metrics.get("aligner_lag_bad_rate", ""),  # P2修复: 质量指标
                    score if score is not None else "",
                    equal_weight_score,  # 多品种公平权重: 等权评分
                    per_symbol_metrics_str,  # 多品种公平权重: per_symbol_metrics (JSON字符串)
                    result.get("train_score", ""),  # Walk-forward: 训练分数
                    result.get("val_score", ""),  # Walk-forward: 验证分数
                    result.get("generalization_gap", ""),  # Walk-forward: 泛化差距
                    result.get("error", ""),  # Fix 10: 添加error列
                ])
                
                writer.writerow(row)
        
        logger.info(f"[ParameterOptimizer] CSV对比表已保存: {csv_file}")
    
    def _generate_smoke_diff(self, result_dir: Path, metrics: Dict[str, Any], trial_id: int) -> None:
        """P1修复: 生成Trial烟雾对比（Smoke Diff）报告
        
        每个Trial结束后输出一页smoke_diff.md，包含：
        - 信号计数（buy/sell/quiet/strong*）
        - 进场/出场笔数、平均持有时长
        - Top场景（scenario_2x2）
        - 成本占比（两种口径）
        
        Args:
            result_dir: Trial结果目录
            metrics: Metrics字典
            trial_id: Trial ID
        """
        smoke_diff_file = result_dir / "smoke_diff.md"
        
        # 读取trades.jsonl统计信号和交易信息
        trades_file = result_dir / "trades.jsonl"
        signal_counts = {"buy": 0, "sell": 0, "strong_buy": 0, "strong_sell": 0, "quiet": 0, "neutral": 0}
        entry_count = 0
        exit_count = 0
        scenario_counts = {}
        
        if trades_file.exists():
            try:
                with open(trades_file, "r", encoding="utf-8") as f:
                    for line in f:
                        trade = json.loads(line.strip())
                        reason = trade.get("reason", "")
                        signal_type = trade.get("signal_type", "neutral")
                        
                        # 统计信号类型
                        if signal_type in signal_counts:
                            signal_counts[signal_type] += 1
                        elif signal_type not in ("entry", "exit"):
                            signal_counts["neutral"] += 1
                        
                        # 统计进场/出场
                        if reason == "entry":
                            entry_count += 1
                        elif reason in ["exit", "reverse", "reverse_signal", "stop_loss", "take_profit", "timeout", "rollover_close"]:
                            exit_count += 1
                        
                        # 统计场景分布
                        scenario = trade.get("scenario_2x2", "unknown")
                        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
            except Exception as e:
                logger.debug(f"  读取trades.jsonl失败: {e}")
        
        # 从metrics获取信息
        total_trades = metrics.get("total_trades", 0)
        avg_hold_sec = metrics.get("avg_hold_sec", 0)
        avg_hold_long = metrics.get("avg_hold_long", 0)
        avg_hold_short = metrics.get("avg_hold_short", 0)
        total_pnl = metrics.get("total_pnl", 0)
        total_fee = metrics.get("total_fee", 0)
        total_slippage = metrics.get("total_slippage", 0)
        turnover = metrics.get("turnover", 0)
        cost_ratio = (total_fee + total_slippage) / abs(total_pnl) if total_pnl != 0 else 0
        cost_bps_on_turnover = metrics.get("cost_bps_on_turnover", 0)
        
        # Top场景（按交易数排序）
        top_scenarios = sorted(scenario_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # 生成Markdown内容
        md_content = f"""# Trial {trial_id} Smoke Diff

**生成时间**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

## 信号统计

| 信号类型 | 计数 |
|---------|------|
| buy | {signal_counts['buy']} |
| sell | {signal_counts['sell']} |
| strong_buy | {signal_counts['strong_buy']} |
| strong_sell | {signal_counts['strong_sell']} |
| quiet | {signal_counts['quiet']} |
| neutral | {signal_counts['neutral']} |
| **总计** | **{sum(signal_counts.values())}** |

## 交易统计

| 指标 | 值 |
|------|-----|
| 进场笔数 | {entry_count} |
| 出场笔数 | {exit_count} |
| 总交易数 | {total_trades} |
| 平均持有时长（秒） | {avg_hold_sec:.2f} |
| 平均持有时长-多头（秒） | {avg_hold_long:.2f} |
| 平均持有时长-空头（秒） | {avg_hold_short:.2f} |

## Top场景分布（scenario_2x2）

| 场景 | 交易数 | 占比 |
|------|--------|------|
"""
        
        total_scenario_trades = sum(scenario_counts.values())
        for scenario, count in top_scenarios:
            pct = (count / total_scenario_trades * 100) if total_scenario_trades > 0 else 0
            md_content += f"| {scenario} | {count} | {pct:.2f}% |\n"
        
        md_content += f"""
## 成本分析

| 口径 | 值 |
|------|-----|
| 总费用 | ${total_fee:.2f} |
| 总滑点 | ${total_slippage:.2f} |
| 总成本 | ${total_fee + total_slippage:.2f} |
| 成本占比（毛利） | {cost_ratio*100:.2f}% |
| 成本bps（成交额） | {cost_bps_on_turnover:.2f} bps |
| 成交额 | ${turnover:.2f} |

## 关键指标

| 指标 | 值 |
|------|-----|
| 总PnL | ${total_pnl:.2f} |
| 净PnL | ${total_pnl - total_fee - total_slippage:.2f} |
| 胜率（交易口径） | {metrics.get('win_rate_trades', 0)*100:.2f}% |
| 胜率（日口径） | {metrics.get('win_rate', 0)*100:.2f}% |
| 最大回撤 | ${metrics.get('max_drawdown', 0):.2f} |
| Sharpe比率 | {metrics.get('sharpe_ratio', 0):.4f} |

---
*此报告用于快速对比不同Trial的执行路径差异*
"""
        
        # 写入文件
        try:
            with open(smoke_diff_file, "w", encoding="utf-8") as f:
                f.write(md_content)
            logger.debug(f"  Smoke diff已保存: {smoke_diff_file}")
        except Exception as e:
            logger.warning(f"  保存smoke_diff.md失败: {e}")
    
    def _generate_pareto_front(self):
        """生成Pareto前沿分析"""
        from alpha_core.report.pareto import ParetoAnalyzer
        
        # 使用win_rate、net_pnl、cost_ratio_notional作为目标
        analyzer = ParetoAnalyzer(
            objectives=["win_rate", "net_pnl", "cost_ratio_notional"]
        )
        
        pareto_front = analyzer.find_pareto_front(
            self.trial_results,
            maximize={
                "win_rate": True,
                "net_pnl": True,
                "cost_ratio_notional": False,
            }
        )
        
        if pareto_front:
            pareto_file = self.output_dir / "pareto_front.json"
            analyzer.save_pareto_front(pareto_front, pareto_file)
            
            logger.info(f"[ParameterOptimizer] Pareto前沿: {len(pareto_front)}/{len(self.trial_results)} 个trial")
            
            # 在CSV中标记Pareto前沿
            self._mark_pareto_in_csv(pareto_front)
    
    def _mark_pareto_in_csv(self, pareto_front: List[Dict[str, Any]]):
        """在CSV中标记Pareto前沿trial"""
        pareto_ids = {t.get("trial_id") for t in pareto_front}
        
        csv_file = self.output_dir / "trial_results.csv"
        if not csv_file.exists():
            return
        
        import csv
        
        # 读取CSV
        rows = []
        with open(csv_file, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows.append(header)
            
            for row in reader:
                if len(row) > 0:
                    trial_id = int(row[0]) if row[0].isdigit() else None
                    if trial_id in pareto_ids:
                        # 在最后添加Pareto标记
                        if len(row) == len(header):
                            row.append("Pareto")
                        else:
                            row[-1] = "Pareto"
                rows.append(row)
        
        # 如果header中没有pareto列，添加
        if "pareto" not in [h.lower() for h in header]:
            header.append("pareto")
            rows[0] = header
        
        # 写回CSV
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    
    def _calculate_score(
        self, 
        metrics: Dict[str, Any], 
        net_pnl: float,
        scoring_weights: Optional[Dict[str, float]] = None,
        trial_result: Optional[Dict[str, Any]] = None,  # 多品种公平权重：完整的trial结果
    ) -> float:
        """Fix 9: 计算多目标综合分（改进：稳健标准化 + 惩罚项）
        
        支持自定义评分权重（用于阶段1/阶段2）
        支持多品种公平权重评分（当有多个symbol时）
        
        默认权重：
        - net_pnl: 1.0
        - win_rate: 0.5
        - cost_ratio: -0.5
        - max_drawdown: -0.2
        
        阶段1权重（稳胜率+控回撤）：
        - win_rate: 0.4
        - max_drawdown: 0.3
        - cost_ratio_notional: 0.3
        
        阶段2权重（提收益+控成本）：
        - net_pnl: 0.3
        - pnl_per_trade: 0.3
        - trades_per_hour: 0.2
        - cost_ratio_notional: 0.2
        
        多品种公平权重：
        - 当有多个symbol时，使用MultiSymbolScorer进行等权评分
        - 避免单一高波动品种"带飞"
        """
        # 多品种公平权重：如果有多个symbol，使用MultiSymbolScorer
        if self.use_multi_symbol_scoring and trial_result:
            try:
                from alpha_core.report.multi_symbol_scorer import MultiSymbolScorer
                
                scorer = MultiSymbolScorer(self.symbols)
                multi_symbol_result = scorer.calculate_equal_weight_score(trial_result)
                
                if multi_symbol_result.get("symbol_count", 0) > 0:
                    # 使用多品种等权评分
                    equal_weight_score = multi_symbol_result.get("equal_weight_score", net_pnl)
                    
                    # 将等权评分标准化到[0,1]范围（与原有评分方法保持一致）
                    # P2修复: 避免重复计算，如果trial_result已经有equal_weight_score，直接使用
                    if trial_result and "equal_weight_score" in trial_result:
                        equal_weight_score = trial_result["equal_weight_score"]
                    else:
                        # 保存per_symbol_metrics到trial_result
                        if trial_result:
                            trial_result["per_symbol_metrics"] = multi_symbol_result.get("per_symbol_metrics", {})
                            trial_result["equal_weight_score"] = equal_weight_score
                    
                    # 标准化需要所有trial的等权评分，但这里避免重复计算
                    # 如果trial_result已经有equal_weight_score，说明已经预计算过，直接使用
                    # 否则，需要遍历所有trial（但这种情况应该很少，因为CSV生成时会预计算）
                    successful_results = [r for r in self.trial_results if r.get("success")]
                    if len(successful_results) >= 2:
                        # 收集所有trial的等权评分（如果已计算）
                        all_equal_weight_scores = []
                        for r in successful_results:
                            if "equal_weight_score" in r:
                                all_equal_weight_scores.append(r["equal_weight_score"])
                            else:
                                # 如果某个trial还没有计算，临时计算（避免阻塞）
                                try:
                                    r_scorer = MultiSymbolScorer(self.symbols)
                                    r_result = r_scorer.calculate_equal_weight_score(r)
                                    if r_result.get("symbol_count", 0) > 0:
                                        r_score = r_result.get("equal_weight_score", 0)
                                        r["equal_weight_score"] = r_score
                                        r["per_symbol_metrics"] = r_result.get("per_symbol_metrics", {})
                                        all_equal_weight_scores.append(r_score)
                                except Exception:
                                    pass
                        
                        if all_equal_weight_scores:
                            # 使用rank_score标准化
                            def rank_score(value, values):
                                if not values:
                                    return 0.0
                                rank = sum(1 for v in values if v < value)
                                return rank / len(values) if len(values) > 0 else 0.0
                            
                            normalized_score = rank_score(equal_weight_score, all_equal_weight_scores)
                            return normalized_score
                    
                    # 如果无法标准化，直接返回等权评分（需要后续调整）
                    logger.debug(f"使用多品种等权评分: {equal_weight_score}")
                    return equal_weight_score
            except Exception as e:
                logger.warning(f"多品种公平权重评分失败，回退到标准评分: {e}")
                # 回退到标准评分
        successful_results = [r for r in self.trial_results if r.get("success")]
        if len(successful_results) < 2:
            # 如果只有一个或没有成功结果，直接返回net_pnl
            return net_pnl
        
        # 收集所有成功结果的指标用于标准化
        net_pnls = []
        win_rates = []
        cost_ratios = []
        max_drawdowns = []
        total_trades_list = []
        
        for r in successful_results:
            m = r.get("metrics", {})
            tp = m.get("total_pnl", 0)
            tf = m.get("total_fee", 0)
            ts = m.get("total_slippage", 0)
            np = tp - tf - ts
            net_pnls.append(np)
            # P0修复: 使用交易口径胜率（win_rate_trades）替代日口径（win_rate）
            win_rates.append(m.get("win_rate_trades", m.get("win_rate", 0)))
            cr = (tf + ts) / abs(tp) if tp != 0 else 0
            cost_ratios.append(cr)
            max_drawdowns.append(abs(m.get("max_drawdown", 0)))
            total_trades_list.append(m.get("total_trades", 0))
        
        def rank_score(value, values):
            """Rank到[0,1]（更稳健的标准化方法）"""
            if not values:
                return 0.0
            rank = sum(1 for v in values if v < value)
            return rank / len(values) if len(values) > 0 else 0.0
        
        total_pnl = metrics.get("total_pnl", 0)
        total_fee = metrics.get("total_fee", 0)
        total_slippage = metrics.get("total_slippage", 0)
        cost_ratio = (total_fee + total_slippage) / abs(total_pnl) if total_pnl != 0 else 0
        total_trades = metrics.get("total_trades", 0)
        
        # 使用自定义权重或默认权重
        # STAGE-2优化: 显式把"降频/降成本"写进目标函数
        # score = 1.0*net_pnl + 0.6*pnl_per_trade - 0.4*trades_per_hour - 0.3*cost_bps_on_turnover
        if scoring_weights is None:
            scoring_weights = {
                "net_pnl": 1.0,
                "win_rate": 0.5,
                "cost_ratio": -0.5,
                "max_drawdown": -0.2,
            }
        
        # 计算各项指标的rank_score
        net_pnl_score = rank_score(net_pnl, net_pnls)
        # F系列实验: 支持pnl_net权重（等同于net_pnl）
        pnl_net_score = net_pnl_score if "pnl_net" in scoring_weights else 0.0
        
        # P0修复: 使用交易口径胜率（win_rate_trades）替代日口径（win_rate）
        # F系列实验: 支持win_rate_trades权重
        win_rate_trades_value = metrics.get("win_rate_trades", metrics.get("win_rate", 0))
        win_rate_score = rank_score(win_rate_trades_value, win_rates)
        win_rate_trades_score = win_rate_score if "win_rate_trades" in scoring_weights else 0.0
        
        cost_ratio_score = rank_score(cost_ratio, cost_ratios)
        max_drawdown_score = rank_score(abs(metrics.get("max_drawdown", 0)), max_drawdowns)
        
        # 计算成交额口径成本占比的rank_score（如果权重中包含）
        cost_ratio_notional_score = 0.0
        if "cost_ratio_notional" in scoring_weights:
            turnover = metrics.get("turnover", 0)
            cost_ratio_notional = (total_fee + total_slippage) / max(1.0, turnover) if turnover > 0 else 0
            cost_ratio_notionals = [
                (r.get("metrics", {}).get("total_fee", 0) + r.get("metrics", {}).get("total_slippage", 0)) / 
                max(1.0, r.get("metrics", {}).get("turnover", 0))
                for r in successful_results
                if r.get("metrics", {}).get("turnover", 0) > 0
            ]
            if cost_ratio_notionals:
                cost_ratio_notional_score = rank_score(cost_ratio_notional, cost_ratio_notionals)
        
        # 计算pnl_per_trade的rank_score（如果权重中包含）
        pnl_per_trade_score = 0.0
        if "pnl_per_trade" in scoring_weights or "avg_pnl_per_trade" in scoring_weights:
            # 优先使用metrics中的avg_pnl_per_trade，如果没有则计算
            avg_pnl_per_trade = metrics.get("avg_pnl_per_trade")
            if avg_pnl_per_trade is None:
                avg_pnl_per_trade = net_pnl / total_trades if total_trades > 0 else 0
            
            avg_pnl_per_trades = []
            for r in successful_results:
                m = r.get("metrics", {})
                r_avg_pnl = m.get("avg_pnl_per_trade")
                if r_avg_pnl is None:
                    r_tp = m.get("total_pnl", 0)
                    r_tf = m.get("total_fee", 0)
                    r_ts = m.get("total_slippage", 0)
                    r_net = r_tp - r_tf - r_ts
                    r_trades = m.get("total_trades", 1)
                    r_avg_pnl = r_net / r_trades if r_trades > 0 else 0
                avg_pnl_per_trades.append(r_avg_pnl)
            
            if avg_pnl_per_trades:
                pnl_per_trade_score = rank_score(avg_pnl_per_trade, avg_pnl_per_trades)
        
        # 计算pnl_net的rank_score（如果权重中包含）
        pnl_net_score = 0.0
        if "pnl_net" in scoring_weights:
            # pnl_net就是net_pnl（total_pnl - fee - slippage）
            pnl_nets = net_pnls  # 已经收集了所有net_pnl
            if pnl_nets:
                pnl_net_score = rank_score(net_pnl, pnl_nets)
        
        # 计算trades_per_hour的rank_score（如果权重中包含）
        # P1修复: 阶梯惩罚（线性→二次）
        trades_per_hour_score = 0.0
        if "trades_per_hour" in scoring_weights:
            trades_per_hour = total_trades / 24.0 if total_trades > 0 else 0  # 假设24小时回测
            trades_per_hours = [
                r.get("metrics", {}).get("total_trades", 0) / 24.0
                for r in successful_results
            ]
            if trades_per_hours:
                # STAGE-2优化: 惩罚交易频率过高（目标≤基线的20%）
                trades_per_hour_score = rank_score(trades_per_hour, trades_per_hours)
                # P1修复: 阶梯惩罚（阈值之上线性→二次）
                trades_per_hour_threshold = scoring_weights.get("trades_per_hour_threshold", 50)  # 默认阈值50
                if trades_per_hour > trades_per_hour_threshold:
                    # 线性惩罚段
                    excess = trades_per_hour - trades_per_hour_threshold
                    linear_penalty = -0.01 * excess  # 每超过1笔/小时，扣0.01分
                    # 二次惩罚段（超过阈值的2倍）
                    if trades_per_hour > trades_per_hour_threshold * 2:
                        excess2 = trades_per_hour - trades_per_hour_threshold * 2
                        quadratic_penalty = -0.02 * (excess2 ** 2)  # 二次惩罚
                        trades_per_hour_score += linear_penalty + quadratic_penalty
                    else:
                        trades_per_hour_score += linear_penalty
        
        # STAGE-2优化: 计算cost_bps_on_turnover的rank_score（如果权重中包含）
        # P1修复: 成本bps硬惩罚（阶梯惩罚）
        cost_bps_score = 0.0
        if "cost_bps_on_turnover" in scoring_weights:
            cost_bps_on_turnover = metrics.get("cost_bps_on_turnover", 0)
            cost_bps_list = [
                r.get("metrics", {}).get("cost_bps_on_turnover", 0)
                for r in successful_results
            ]
            if cost_bps_list:
                # 成本bps越低越好，所以使用反向rank_score
                cost_bps_score = rank_score(-cost_bps_on_turnover, [-cb for cb in cost_bps_list])
                # P1修复: 成本bps硬惩罚（阶梯惩罚）
                cost_bps_threshold = scoring_weights.get("cost_bps_threshold", 1.75)  # 默认阈值1.75bps
                if cost_bps_on_turnover > cost_bps_threshold:
                    # 线性惩罚段
                    excess = cost_bps_on_turnover - cost_bps_threshold
                    linear_penalty = -0.1 * excess  # 每超过0.1bps，扣0.1分
                    # 二次惩罚段（超过阈值的1.5倍）
                    if cost_bps_on_turnover > cost_bps_threshold * 1.5:
                        excess2 = cost_bps_on_turnover - cost_bps_threshold * 1.5
                        quadratic_penalty = -0.2 * (excess2 ** 2)  # 二次惩罚
                        cost_bps_score += linear_penalty + quadratic_penalty
                    else:
                        cost_bps_score += linear_penalty
        
        # P1修复: 添加taker_ratio和maker_ratio评分（如果权重中包含）
        taker_ratio_score = 0.0
        if "taker_ratio" in scoring_weights:
            # 尝试从metrics或scenario_breakdown中获取taker_ratio
            taker_ratio = metrics.get("taker_ratio", 0)
            if taker_ratio == 0:
                # 尝试从scenario_breakdown计算
                scenario_breakdown = metrics.get("scenario_breakdown", {})
                total_turnover = sum(s.get("turnover", 0) for s in scenario_breakdown.values())
                taker_turnover = sum(
                    s.get("turnover", 0) for s in scenario_breakdown.values()
                    if s.get("scenario", "").endswith("_T")  # Taker场景
                )
                taker_ratio = taker_turnover / total_turnover if total_turnover > 0 else 0
            
            # taker_ratio越低越好（maker优先），使用反向rank_score
            taker_ratios = [
                r.get("metrics", {}).get("taker_ratio", 0)
                for r in successful_results
            ]
            if taker_ratios:
                taker_ratio_score = rank_score(-taker_ratio, [-tr for tr in taker_ratios])
                # 硬惩罚：taker_ratio过高（>0.5表示超过50%是taker）
                if taker_ratio > 0.5:
                    taker_ratio_score -= 0.3  # 强惩罚
        
        maker_ratio_score = 0.0
        if "maker_ratio" in scoring_weights:
            maker_ratio = metrics.get("maker_ratio", 0)
            if maker_ratio == 0:
                # 尝试从taker_ratio计算
                taker_ratio = metrics.get("taker_ratio", 0)
                maker_ratio = 1.0 - taker_ratio
            
            # maker_ratio越高越好，使用正向rank_score
            maker_ratios = [
                r.get("metrics", {}).get("maker_ratio", 0)
                for r in successful_results
            ]
            if maker_ratios:
                maker_ratio_score = rank_score(maker_ratio, maker_ratios)
        
        # 加权求和
        # F系列实验: 支持win_rate_trades、avg_pnl_per_trade、pnl_net权重
        score = (
            scoring_weights.get("net_pnl", 1.0) * net_pnl_score +
            scoring_weights.get("pnl_net", 0) * pnl_net_score +  # F系列: pnl_net权重
            scoring_weights.get("win_rate", 0) * win_rate_score +
            scoring_weights.get("win_rate_trades", 0) * win_rate_trades_score +  # F系列: win_rate_trades权重
            scoring_weights.get("avg_pnl_per_trade", 0) * pnl_per_trade_score +  # F系列: avg_pnl_per_trade权重（使用pnl_per_trade_score）
            scoring_weights.get("pnl_per_trade", 0.6) * pnl_per_trade_score -
            scoring_weights.get("cost_ratio", 0) * cost_ratio_score -
            scoring_weights.get("max_drawdown", 0) * max_drawdown_score -
            scoring_weights.get("cost_ratio_notional", 0) * cost_ratio_notional_score -
            scoring_weights.get("trades_per_hour", 0.4) * trades_per_hour_score -
            scoring_weights.get("cost_bps_on_turnover", 0.3) * cost_bps_score -
            scoring_weights.get("taker_ratio", 0.2) * taker_ratio_score +  # P1修复: taker_ratio负权重
            scoring_weights.get("maker_ratio", 0.2) * maker_ratio_score  # P1修复: maker_ratio正权重
        )
        
        # 惩罚项：极端低样本（total_trades < 10）- 关键护栏：避免"高胜率=低出手"骗分
        if total_trades < 10:
            score -= 0.3  # 惩罚低样本
        elif total_trades < 20:
            score -= 0.15  # 中等样本轻微惩罚
        
        # 惩罚项：成本占比过高（>50%）
        if cost_ratio > 0.5:
            score -= 0.2  # 惩罚高成本
        
        # A.1/B.3: 惩罚项：成交额口径成本占比过高（>1%）
        # 计算成交额口径成本占比
        turnover = metrics.get("turnover", 0)
        if turnover > 0:
            cost_ratio_notional = (total_fee + total_slippage) / turnover
            if cost_ratio_notional > 0.01:  # 1%
                score -= 0.15  # 惩罚高成交额成本占比
        
        # P2修复: 惩罚项：质量指标过高（抑制"靠极端噪声碰运气"的参数）
        aligner_gap_rate = metrics.get("aligner_gap_seconds_rate", 0)
        aligner_lag_rate = metrics.get("aligner_lag_bad_rate", 0)
        if aligner_gap_rate > 0.1:  # gap秒数占比 > 10%
            score -= 0.05  # 轻微惩罚
        if aligner_lag_rate > 0.1:  # lag超阈值占比 > 10%
            score -= 0.05  # 轻微惩罚
        
        # B.3: 惩罚项：unknown场景占比过高（>5%）
        unknown_ratio = metrics.get("unknown_ratio", 0)
        if unknown_ratio > 0.05:
            score -= 0.1  # 惩罚高unknown占比
        
        # 高频-低Edge惩罚：交易密度过高和单笔收益过低
        # 计算交易频率（假设24小时回测，1440分钟）
        total_trades = metrics.get("total_trades", 0)
        trades_per_hour = total_trades / 24.0 if total_trades > 0 else 0
        
        # 计算单笔收益
        pnl_per_trade = net_pnl / total_trades if total_trades > 0 else 0
        
        # 获取平均持仓时间
        avg_hold_sec = metrics.get("avg_hold_sec", 0)
        
        # 惩罚交易频率过高（>50笔/小时）
        if trades_per_hour > 50:
            score -= 0.15  # 严重惩罚高频交易
        elif trades_per_hour > 30:
            score -= 0.08  # 中等惩罚
        elif trades_per_hour > 20:
            score -= 0.03  # 轻微惩罚
        
        # 惩罚单笔收益为负（毛利 < 费用+滑点）
        if pnl_per_trade < 0:
            score -= 0.10  # 惩罚负收益
        elif pnl_per_trade < 0.5:  # 单笔收益 < $0.5（接近成本）
            score -= 0.05  # 轻微惩罚
        
        # 惩罚持仓时间过短（<60秒）
        if avg_hold_sec > 0 and avg_hold_sec < 60:
            score -= 0.10  # 惩罚过短持仓
        elif avg_hold_sec > 0 and avg_hold_sec < 120:
            score -= 0.05  # 轻微惩罚
        
        return score
    
    def _print_recommendations(self):
        """输出推荐参数"""
        # Fix 9: 按多目标综合分排序
        successful_results = [r for r in self.trial_results if r.get("success")]
        if not successful_results:
            logger.warning("没有成功的试验")
            return
        
        # 计算净PnL和综合分
        for result in successful_results:
            metrics = result.get("metrics", {})
            total_pnl = metrics.get("total_pnl", 0)
            total_fee = metrics.get("total_fee", 0)
            total_slippage = metrics.get("total_slippage", 0)
            result["net_pnl"] = total_pnl - total_fee - total_slippage
            # 多品种公平权重：传入trial_result
            result["score"] = self._calculate_score(metrics, result["net_pnl"], self.scoring_weights, trial_result=result)
        
        sorted_results = sorted(successful_results, key=lambda x: x.get("score", 0), reverse=True)
        
        logger.info("\n" + "=" * 80)
        logger.info("推荐参数（TOP 5）")
        logger.info("=" * 80)
        
        for i, result in enumerate(sorted_results[:5], 1):
            metrics = result.get("metrics", {})
            logger.info(f"\n排名 {i}:")
            logger.info(f"  综合分: {result.get('score', 0):.4f}")
            
            # Walk-forward验证：显示训练/验证对比
            if "val_score" in result:
                logger.info(f"  训练分数: {result.get('train_score', 0):.4f}")
                logger.info(f"  验证分数: {result.get('val_score', 0):.4f}")
                logger.info(f"  泛化差距: {result.get('generalization_gap', 0):.4f}")
            
            logger.info(f"  净PnL: ${result.get('net_pnl', 0):.2f}")
            logger.info(f"  胜率: {metrics.get('win_rate', 0)*100:.2f}%")
            logger.info(f"  Sharpe: {metrics.get('sharpe_ratio', 0):.4f}")
            logger.info(f"  交易数: {metrics.get('total_trades', 0)}")
            logger.info(f"  参数:")
            for param_name, param_value in result.get("params", {}).items():
                logger.info(f"    {param_name}: {param_value}")
        
        # 保存推荐配置（修复：从config_file反读YAML）
        if sorted_results:
            best_result = sorted_results[0]
            best_config_file = self.output_dir / "recommended_config.yaml"
            
            # 修复：从config_file读取配置，而不是使用不存在的config字段
            best_cfg = {}
            if "config_file" in best_result:
                import yaml
                config_file_path = Path(best_result["config_file"])
                if config_file_path.exists():
                    with open(config_file_path, "r", encoding="utf-8") as f:
                        best_cfg = yaml.safe_load(f) or {}
            
            self._save_config(best_cfg, best_config_file)
            logger.info(f"\n推荐配置已保存: {best_config_file}")
        
        # 输出Pareto前沿摘要（如果存在）
        pareto_file = self.output_dir / "pareto_front.json"
        if pareto_file.exists():
            try:
                with open(pareto_file, "r", encoding="utf-8") as f:
                    pareto_front = json.load(f)
                
                logger.info(f"\n[ParameterOptimizer] Pareto前沿摘要（{len(pareto_front)} 个trial）:")
                for i, trial in enumerate(pareto_front[:5], 1):
                    logger.info(
                        f"  {i}. Trial {trial['trial_id']}: "
                        f"Net PnL=${trial['net_pnl']:.2f}, "
                        f"Win Rate={trial['win_rate']*100:.2f}%, "
                        f"Cost Ratio={trial['cost_ratio_notional']*100:.2f}%"
                    )
            except Exception as e:
                logger.debug(f"读取Pareto前沿失败: {e}")

