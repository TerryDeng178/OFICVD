# -*- coding: utf-8 -*-
"""
Orchestrator - 主控循环

模式：HOLD / PAPER / SHADOW / LIVE
一致性：实时与回放同接口；事件落地可重放可审计
"""

import argparse
import asyncio
import glob
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque

import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@dataclass
class ProcessSpec:
    """进程规格描述"""
    name: str
    cmd: List[str]
    env: Dict[str, str] = field(default_factory=dict)
    ready_probe: Optional[str] = None  # "log_keyword", "file_exists", "sqlite_connect"
    ready_probe_args: Dict = field(default_factory=dict)
    health_probe: Optional[str] = None  # "file_count", "log_keyword", "sqlite_query"
    health_probe_args: Dict = field(default_factory=dict)
    restart_policy: str = "never"  # "never", "on_failure", "always"
    max_restarts: int = 2
    restart_backoff_secs: int = 10


@dataclass
class ProcessState:
    """进程状态"""
    spec: ProcessSpec
    process: Optional[subprocess.Popen] = None
    started_at: Optional[float] = None
    ready_at: Optional[float] = None
    restart_count: int = 0
    last_health_check: Optional[float] = None
    health_status: str = "unknown"  # "healthy", "degraded", "unhealthy"
    stdout_log: Optional[Path] = None
    stderr_log: Optional[Path] = None


class Supervisor:
    """进程监管器"""
    
    def __init__(self, project_root: Path, log_dir: Path, artifacts_dir: Path):
        self.project_root = project_root
        self.log_dir = log_dir
        self.artifacts_dir = artifacts_dir
        self.processes: Dict[str, ProcessState] = {}
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # 确保目录存在
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        # 设置日志文件
        log_file = self.log_dir / "orchestrator" / "orchestrator.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 添加文件处理器
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(file_handler)
    
    def register_process(self, spec: ProcessSpec):
        """注册进程规格"""
        self.processes[spec.name] = ProcessState(spec=spec)
        logger.info(f"注册进程: {spec.name}")
    
    def start_all(self, enabled_modules: Set[str]):
        """启动所有启用的模块"""
        logger.info(f"开始启动模块: {enabled_modules}")
        
        # 启动顺序：harvest -> signal -> broker -> report
        order = ["harvest", "signal", "broker", "report"]
        
        for name in order:
            if name in enabled_modules and name in self.processes:
                self._start_process(name)
        
        logger.info("所有模块启动完成")
    
    def _start_process(self, name: str):
        """启动单个进程"""
        state = self.processes[name]
        spec = state.spec
        
        if state.process is not None:
            logger.warning(f"{name} 已在运行，跳过启动")
            return
        
        # 准备日志文件
        proc_log_dir = self.log_dir / name
        proc_log_dir.mkdir(parents=True, exist_ok=True)
        state.stdout_log = proc_log_dir / f"{name}_stdout.log"
        state.stderr_log = proc_log_dir / f"{name}_stderr.log"
        
        # 准备环境变量
        env = os.environ.copy()
        env.update(spec.env)
        env["PYTHONUTF8"] = "1"
        
        # 准备命令（使用项目根目录作为工作目录）
        cmd = [sys.executable, "-m"] + spec.cmd
        
        logger.info(f"启动进程: {name}")
        logger.info(f"  命令: {' '.join(cmd)}")
        logger.info(f"  环境变量: {spec.env}")
        
        try:
            with open(state.stdout_log, "w", encoding="utf-8") as stdout_fp, \
                 open(state.stderr_log, "w", encoding="utf-8") as stderr_fp:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(self.project_root),
                    env=env,
                    stdout=stdout_fp,
                    stderr=stderr_fp,
                    text=True,
                    encoding="utf-8"
                )
            
            state.process = process
            state.started_at = time.time()
            state.restart_count = 0
            
            logger.info(f"{name} 进程已启动 (PID: {process.pid})")
        except Exception as e:
            logger.error(f"启动 {name} 失败: {e}", exc_info=True)
            state.process = None
    
    async def wait_ready(self, timeout_secs: int = 120):
        """等待所有进程就绪"""
        logger.info("等待进程就绪...")
        
        start_time = time.time()
        ready_set = set()
        
        while time.time() - start_time < timeout_secs:
            for name, state in self.processes.items():
                if name in ready_set or state.process is None:
                    continue
                
                if state.ready_at is not None:
                    ready_set.add(name)
                    continue
                
                # 检查就绪条件
                if self._check_ready(name, state):
                    state.ready_at = time.time()
                    ready_set.add(name)
                    logger.info(f"{name} 已就绪 (耗时: {state.ready_at - state.started_at:.1f}s)")
            
            if len(ready_set) == len([p for p in self.processes.values() if p.process is not None]):
                logger.info("所有进程已就绪")
                return True
            
            await asyncio.sleep(2)
        
        # 超时检查
        not_ready = [name for name, state in self.processes.items() 
                     if state.process is not None and name not in ready_set]
        if not_ready:
            logger.warning(f"以下进程未在 {timeout_secs}s 内就绪: {not_ready}")
            return False
        
        return True
    
    def _check_ready(self, name: str, state: ProcessState) -> bool:
        """检查进程是否就绪"""
        spec = state.spec
        
        if not spec.ready_probe:
            # 无探针，默认就绪
            return True
        
        if spec.ready_probe == "log_keyword":
            # 支持 keywords 列表（任一命中即 ready）或单个 keyword
            keywords = spec.ready_probe_args.get("keywords", [])
            keyword = spec.ready_probe_args.get("keyword", "")
            if not keywords and keyword:
                keywords = [keyword]
            
            if keywords and state.stdout_log and state.stdout_log.exists():
                try:
                    content = state.stdout_log.read_text(encoding="utf-8", errors="replace")
                    for kw in keywords:
                        if kw in content:
                            return True
                except Exception:
                    pass
        
        elif spec.ready_probe == "file_exists":
            pattern = spec.ready_probe_args.get("pattern", "")
            if pattern:
                # 将模式转换为相对于 project_root 的路径
                pattern_path = Path(pattern)
                if pattern_path.is_absolute():
                    # 绝对路径：检查是否存在
                    if pattern_path.exists():
                        return True
                else:
                    # 相对路径：使用 glob
                    matches = list(self.project_root.glob(pattern))
                    if matches:
                        return True
        
        elif spec.ready_probe == "sqlite_connect":
            db_path = spec.ready_probe_args.get("db_path", "")
            if db_path:
                db_full_path = self.project_root / db_path
                if db_full_path.exists():
                    try:
                        conn = sqlite3.connect(str(db_full_path), timeout=1.0)
                        conn.close()
                        return True
                    except Exception:
                        pass
        
        return False
    
    async def tick_health(self, interval_secs: int = 10):
        """周期性健康检查"""
        self.running = True
        
        while self.running and not self.shutdown_event.is_set():
            for name, state in self.processes.items():
                if state.process is None:
                    continue
                
                # 检查进程是否还在运行
                if state.process.poll() is not None:
                    logger.warning(f"{name} 进程已退出 (退出码: {state.process.returncode})")
                    state.health_status = "unhealthy"
                    
                    # 根据重启策略处理
                    if state.spec.restart_policy != "never" and state.restart_count < state.spec.max_restarts:
                        await asyncio.sleep(state.spec.restart_backoff_secs * (state.restart_count + 1))
                        logger.info(f"重启 {name} (第 {state.restart_count + 1} 次)")
                        state.process = None
                        state.ready_at = None
                        state.restart_count += 1
                        self._start_process(name)
                    continue
                
                # 执行健康探针
                health_ok = self._check_health(name, state)
                state.last_health_check = time.time()
                
                if health_ok:
                    state.health_status = "healthy"
                else:
                    state.health_status = "degraded"
                    logger.warning(f"{name} 健康检查失败")
            
            await asyncio.sleep(interval_secs)
    
    def _check_health(self, name: str, state: ProcessState) -> bool:
        """执行健康检查"""
        spec = state.spec
        
        if not spec.health_probe:
            # 无探针，默认健康
            return True
        
        if spec.health_probe == "file_count":
            pattern = spec.health_probe_args.get("pattern", "")
            min_count = spec.health_probe_args.get("min_count", 1)
            min_new_last_seconds = spec.health_probe_args.get("min_new_last_seconds", None)
            min_new_count = spec.health_probe_args.get("min_new_count", 0)
            max_idle_seconds = spec.health_probe_args.get("max_idle_seconds", None)
            
            if pattern:
                current_time = time.time()
                recent_files = []
                all_files = []
                
                # 检测通配符：如果包含 *?[]，使用 glob.glob
                if any(ch in pattern for ch in "*?[]"):
                    matches = glob.glob(pattern, recursive=True)
                    all_files = [Path(m) for m in matches]
                else:
                    # 无通配符：按路径处理
                    pattern_path = Path(pattern)
                    if pattern_path.is_absolute():
                        if pattern_path.is_dir():
                            all_files = list(pattern_path.rglob("*"))
                        elif pattern_path.exists():
                            all_files = [pattern_path]
                    else:
                        all_files = [Path(m) for m in self.project_root.glob(pattern)]
                
                # P0-C: 仅统计文件（非目录），保证跨平台健壮性
                all_files = [f for f in all_files if f.is_file()]
                
                # 基础检查：文件数是否满足最小要求
                if len(all_files) < min_count:
                    return False
                
                # P0-B: 对历史文件场景友好化（如果 min_new_last_seconds=0，跳过时间窗口检查）
                if min_new_last_seconds == 0:
                    # 历史/回放场景：仅检查文件存在和数量，不检查时间窗口
                    return True
                
                # 时间窗口检查（如果配置了）
                if min_new_last_seconds is not None or max_idle_seconds is not None:
                    for file_path in all_files:
                        if not file_path.exists():
                            continue
                        try:
                            mtime = file_path.stat().st_mtime
                            age_seconds = current_time - mtime
                            
                            # 检查最近新增（在时间窗口内创建/修改）
                            if min_new_last_seconds is not None and age_seconds <= min_new_last_seconds:
                                recent_files.append(file_path)
                            
                            # 检查最大空闲时间（如果所有文件都太旧，判为不健康）
                            if max_idle_seconds is not None and age_seconds > max_idle_seconds:
                                # 如果所有文件都超过最大空闲时间，且没有新文件，判为不健康
                                if len(recent_files) == 0:
                                    continue
                        except Exception:
                            continue
                    
                    # 检查最近新增文件数
                    if min_new_last_seconds is not None and len(recent_files) < min_new_count:
                        return False
                    
                    # 检查是否有文件在最大空闲时间内更新
                    if max_idle_seconds is not None:
                        has_recent = any(
                            (current_time - f.stat().st_mtime) <= max_idle_seconds
                            for f in all_files if f.exists()
                        )
                        if not has_recent:
                            return False
                
                return True
        
        elif spec.health_probe == "log_keyword":
            keyword = spec.health_probe_args.get("keyword", "")
            if state.stderr_log and state.stderr_log.exists():
                try:
                    # 检查最近的内容
                    content = state.stderr_log.read_text(encoding="utf-8", errors="replace")
                    if keyword in content[-10000:]:  # 最近10KB
                        return False
                except Exception:
                    pass
        
        elif spec.health_probe == "sqlite_query":
            db_path = spec.health_probe_args.get("db_path", "")
            min_growth_window_seconds = spec.health_probe_args.get("min_growth_window_seconds", None)
            min_growth_count = spec.health_probe_args.get("min_growth_count", 0)
            
            if db_path:
                db_full_path = self.project_root / db_path
                if db_full_path.exists():
                    try:
                        conn = sqlite3.connect(str(db_full_path), timeout=1.0)
                        cursor = conn.cursor()
                        
                        # 基础检查：数据库可连接
                        cursor.execute("SELECT 1")
                        cursor.fetchone()
                        
                        # 检查最近行数增长（如果配置了）
                        if min_growth_window_seconds is not None:
                            # 检查最近时间窗口内的行数
                            current_time_ms = int(time.time() * 1000)
                            window_start_ms = current_time_ms - (min_growth_window_seconds * 1000)
                            
                            # 查询最近窗口内的行数（假设有 ts_ms 字段）
                            try:
                                cursor.execute("""
                                    SELECT COUNT(*) FROM signals 
                                    WHERE ts_ms >= ? AND confirm = 1
                                """, (window_start_ms,))
                                recent_count = cursor.fetchone()[0]
                                
                                if recent_count < min_growth_count:
                                    conn.close()
                                    return False
                            except sqlite3.OperationalError:
                                # 表或字段不存在，跳过增长检查
                                pass
                        
                        conn.close()
                        return True
                    except Exception:
                        return False
        
        return True
    
    async def graceful_shutdown(self):
        """优雅关闭所有进程"""
        logger.info("开始优雅关闭...")
        self.running = False
        self.shutdown_event.set()
        
        # 关闭顺序：report -> broker -> signal -> harvest（反向）
        order = ["report", "broker", "signal", "harvest"]
        
        for name in order:
            if name in self.processes:
                state = self.processes[name]
                if state.process is not None:
                    logger.info(f"关闭 {name}...")
                    try:
                        state.process.terminate()
                        # 等待最多 10 秒
                        try:
                            state.process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            logger.warning(f"{name} 未在 10s 内退出，强制终止")
                            state.process.kill()
                            state.process.wait()
                    except Exception as e:
                        logger.error(f"关闭 {name} 时出错: {e}")
        
        logger.info("所有进程已关闭")
    
    def get_status(self) -> Dict:
        """获取当前状态"""
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "processes": {}
        }
        
        for name, state in self.processes.items():
            proc_status = {
                "running": state.process is not None and state.process.poll() is None,
                "pid": state.process.pid if state.process else None,
                "started_at": datetime.fromtimestamp(state.started_at).isoformat() if state.started_at else None,
                "ready_at": datetime.fromtimestamp(state.ready_at).isoformat() if state.ready_at else None,
                "restart_count": state.restart_count,
                "health_status": state.health_status,
                "last_health_check": datetime.fromtimestamp(state.last_health_check).isoformat() if state.last_health_check else None,
            }
            status["processes"][name] = proc_status
        
        return status


class Reporter:
    """日报生成器"""
    
    def __init__(self, project_root: Path, output_dir: Path):
        self.project_root = project_root
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_report(self, sink_kind: str, runtime_dir: Path) -> Dict:
        """生成日报"""
        logger.info(f"生成日报 (sink: {sink_kind})...")
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "sink": sink_kind,
            "total": 0,
            "buy_count": 0,
            "sell_count": 0,
            "strong_buy_count": 0,
            "strong_sell_count": 0,
            "buy_ratio": 0.0,
            "strong_ratio": 0.0,
            "per_minute": [],
            "dropped": 0,
            "warnings": [],
            "gating_breakdown": {},  # 护栏分解统计（总体）
            "gating_breakdown_by_regime": {},  # P1-E: 按 regime 分组的护栏分解
            "gating_breakdown_by_minute": []  # P1-E: 按分钟分组的护栏分解
        }
        
        if sink_kind == "jsonl":
            self._analyze_jsonl(runtime_dir, report)
        elif sink_kind == "sqlite":
            self._analyze_sqlite(runtime_dir, report)
        
        # 计算比率
        if report["total"] > 0:
            report["buy_ratio"] = report["buy_count"] / report["total"]
            report["sell_ratio"] = report["sell_count"] / report["total"]
            report["strong_ratio"] = (report["strong_buy_count"] + report["strong_sell_count"]) / report["total"]
        else:
            report["sell_ratio"] = 0.0
        
        return report
    
    def _analyze_jsonl(self, runtime_dir: Path, report: Dict):
        """分析 JSONL 文件"""
        signal_dir = runtime_dir / "ready" / "signal"
        if not signal_dir.exists():
            report["warnings"].append("信号目录不存在")
            return
        
        # 收集所有 JSONL 文件
        jsonl_files = sorted(signal_dir.rglob("*.jsonl"))
        if not jsonl_files:
            report["warnings"].append("未找到信号文件")
            return
        
        # 按分钟统计
        minute_counts = defaultdict(int)
        minute_timestamps = []
        total_signals = 0  # 所有信号（包括未确认）
        confirmed_signals = 0  # 确认的信号
        
        for jsonl_file in jsonl_files:
            try:
                with jsonl_file.open("r", encoding="utf-8") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            signal = json.loads(line)
                            total_signals += 1
                            
                            # 统计 gating breakdown（所有信号，包括未确认）
                            guard_reason = signal.get("guard_reason", "")
                            regime = signal.get("regime", "unknown")
                            ts_ms = signal.get("ts_ms", 0)
                            
                            if guard_reason:
                                # 处理多个原因（逗号分隔或列表）
                                if isinstance(guard_reason, list):
                                    reasons = guard_reason
                                elif "," in guard_reason:
                                    reasons = [r.strip() for r in guard_reason.split(",")]
                                else:
                                    reasons = [guard_reason]
                                
                                for reason in reasons:
                                    if reason:
                                        # 总体统计
                                        report["gating_breakdown"][reason] = report["gating_breakdown"].get(reason, 0) + 1
                                        
                                        # P1-E: 按 regime 分组统计
                                        if regime not in report["gating_breakdown_by_regime"]:
                                            report["gating_breakdown_by_regime"][regime] = {}
                                        report["gating_breakdown_by_regime"][regime][reason] = report["gating_breakdown_by_regime"][regime].get(reason, 0) + 1
                                        
                                        # P1-E: 按分钟分组统计（简化实现：使用字典）
                                        if ts_ms:
                                            ts_sec = ts_ms / 1000
                                            minute_key = int(ts_sec / 60)
                                            # 使用字典存储，key 为 minute_key
                                            if not hasattr(self, '_minute_gating_dict'):
                                                self._minute_gating_dict = defaultdict(lambda: defaultdict(int))
                                            self._minute_gating_dict[minute_key][reason] += 1
                            
                            # 只统计确认的信号
                            if not signal.get("confirm", False):
                                continue
                            
                            confirmed_signals += 1
                            report["total"] += 1
                            
                            # 解析信号类型：signal_type 可能是 "strong_buy", "buy", "strong_sell", "sell", "pending", "neutral"
                            signal_type = signal.get("signal_type", "").lower()
                            
                            if "strong_buy" in signal_type:
                                report["buy_count"] += 1
                                report["strong_buy_count"] += 1
                            elif "buy" in signal_type:
                                report["buy_count"] += 1
                            elif "strong_sell" in signal_type:
                                report["sell_count"] += 1
                                report["strong_sell_count"] += 1
                            elif "sell" in signal_type:
                                report["sell_count"] += 1
                            
                            # 按分钟统计
                            if ts_ms:
                                ts_sec = ts_ms / 1000
                                minute_key = int(ts_sec / 60)
                                minute_counts[minute_key] += 1
                                minute_timestamps.append((minute_key, ts_sec))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                report["warnings"].append(f"读取文件失败 {jsonl_file}: {e}")
        
        # 计算最近5分钟的节律
        if minute_timestamps:
            latest_minute = max(m for m, _ in minute_timestamps)
            for i in range(5):
                minute_key = latest_minute - i
                count = minute_counts.get(minute_key, 0)
                report["per_minute"].append({
                    "minute": minute_key,
                    "count": count
                })
            report["per_minute"].reverse()
            
            # P1-E: 将按分钟分组的护栏分解转换为列表格式（对齐 per_minute）
            if hasattr(self, '_minute_gating_dict'):
                for minute_item in report["per_minute"]:
                    minute_key = minute_item["minute"]
                    if minute_key in self._minute_gating_dict:
                        report["gating_breakdown_by_minute"].append(dict(self._minute_gating_dict[minute_key]))
                    else:
                        report["gating_breakdown_by_minute"].append({})
                delattr(self, '_minute_gating_dict')
        
        # 添加告警
        if report["total"] == 0:
            report["warnings"].append("QUIET_RUN")
        
        if report["per_minute"] and all(item["count"] == 0 for item in report["per_minute"]):
            report["warnings"].append("QUIET_RUN")
        
        if confirmed_signals == 0 and total_signals > 0:
            report["warnings"].append("NO_CONFIRMED_SIGNALS")
    
    def _analyze_sqlite(self, runtime_dir: Path, report: Dict):
        """分析 SQLite 数据库"""
        db_path = runtime_dir / "signals.db"
        if not db_path.exists():
            report["warnings"].append("信号数据库不存在")
            return
        
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            cursor = conn.cursor()
            
            # 查询总数（只统计 confirm=1 的信号，与 JSONL 口径一致）
            cursor.execute("SELECT COUNT(*) FROM signals WHERE confirm = 1")
            report["total"] = cursor.fetchone()[0]
            
            # 查询买卖分布（基于 signal_type）
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN signal_type LIKE '%buy%' THEN 'BUY'
                        WHEN signal_type LIKE '%sell%' THEN 'SELL'
                        ELSE 'UNKNOWN'
                    END AS side,
                    COUNT(*) 
                FROM signals 
                WHERE confirm = 1
                GROUP BY side
            """)
            for side, count in cursor.fetchall():
                if side == "BUY":
                    report["buy_count"] = count
                elif side == "SELL":
                    report["sell_count"] = count
            
            # 查询强信号
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN signal_type LIKE '%buy%' THEN 'BUY'
                        WHEN signal_type LIKE '%sell%' THEN 'SELL'
                        ELSE 'UNKNOWN'
                    END AS side,
                    COUNT(*) 
                FROM signals 
                WHERE confirm = 1 AND signal_type LIKE '%strong%'
                GROUP BY side
            """)
            for side, count in cursor.fetchall():
                if side == "BUY":
                    report["strong_buy_count"] = count
                elif side == "SELL":
                    report["strong_sell_count"] = count
            
            # 查询最近5分钟的节律（只统计 confirm=1 的信号）
            cursor.execute("""
                SELECT CAST(ts_ms / 60000 AS INTEGER) AS minute, COUNT(*) 
                FROM signals 
                WHERE confirm = 1
                GROUP BY minute 
                ORDER BY minute DESC 
                LIMIT 5
            """)
            for minute_key, count in cursor.fetchall():
                report["per_minute"].append({
                    "minute": minute_key,
                    "count": count
                })
            report["per_minute"].reverse()
            
            # 查询总信号数（包括未确认）用于告警
            cursor.execute("SELECT COUNT(*) FROM signals")
            total_signals = cursor.fetchone()[0]
            
            # 统计 gating breakdown（从 guard_reason 字段）
            cursor.execute("""
                SELECT guard_reason, COUNT(*) 
                FROM signals 
                WHERE guard_reason IS NOT NULL AND guard_reason != ''
                GROUP BY guard_reason
            """)
            for reason, count in cursor.fetchall():
                # 处理多个原因（逗号分隔）
                if "," in reason:
                    reasons = [r.strip() for r in reason.split(",")]
                    for r in reasons:
                        if r:
                            report["gating_breakdown"][r] = report["gating_breakdown"].get(r, 0) + count
                else:
                    report["gating_breakdown"][reason] = report["gating_breakdown"].get(reason, 0) + count
            
            # 添加告警
            if report["total"] == 0:
                report["warnings"].append("QUIET_RUN")
            
            if report["per_minute"] and all(item["count"] == 0 for item in report["per_minute"]):
                report["warnings"].append("QUIET_RUN")
            
            if report["total"] == 0 and total_signals > 0:
                report["warnings"].append("NO_CONFIRMED_SIGNALS")
            
            conn.close()
        except Exception as e:
            report["warnings"].append(f"查询数据库失败: {e}")
    
    def save_report(self, report: Dict, format: str = "both"):
        """保存日报"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        if format in ("json", "both"):
            json_path = self.output_dir / f"summary_{timestamp}.json"
            with json_path.open("w", encoding="utf-8") as fp:
                json.dump(report, fp, ensure_ascii=False, indent=2)
            logger.info(f"日报已保存: {json_path}")
        
        if format in ("md", "both"):
            md_path = self.output_dir / f"summary_{timestamp}.md"
            with md_path.open("w", encoding="utf-8") as fp:
                self._write_markdown(report, fp)
            logger.info(f"日报已保存: {md_path}")
    
    def _write_markdown(self, report: Dict, fp):
        """写入 Markdown 格式"""
        fp.write(f"# 信号日报\n\n")
        fp.write(f"**生成时间**: {report['timestamp']}\n\n")
        fp.write(f"**Sink 类型**: {report['sink']}\n\n")
        fp.write(f"## 总体统计\n\n")
        fp.write(f"- **总信号数**: {report['total']}\n")
        fp.write(f"- **买入信号**: {report['buy_count']} ({report['buy_ratio']*100:.1f}%)\n")
        sell_ratio = report.get('sell_ratio', report['sell_count'] / report['total'] if report['total'] > 0 else 0.0)
        fp.write(f"- **卖出信号**: {report['sell_count']} ({sell_ratio*100:.1f}%)\n")
        fp.write(f"- **强信号数**: {report['strong_buy_count'] + report['strong_sell_count']} ({report['strong_ratio']*100:.1f}%)\n")
        fp.write(f"- **强买入**: {report['strong_buy_count']}\n")
        fp.write(f"- **强卖出**: {report['strong_sell_count']}\n\n")
        
        if report['per_minute']:
            fp.write(f"## 最近5分钟节律\n\n")
            fp.write(f"| 分钟 | 信号数 |\n")
            fp.write(f"|------|--------|\n")
            for item in report['per_minute']:
                fp.write(f"| {item['minute']} | {item['count']} |\n")
            fp.write(f"\n")
        
        if report.get('gating_breakdown'):
            fp.write(f"## 护栏分解\n\n")
            fp.write(f"### 总体统计\n\n")
            fp.write(f"| 护栏原因 | 触发次数 | 占比 |\n")
            fp.write(f"|---------|---------|------|\n")
            total_gated = sum(report['gating_breakdown'].values())
            for reason, count in sorted(report['gating_breakdown'].items(), key=lambda x: x[1], reverse=True):
                pct = (count / total_gated * 100) if total_gated > 0 else 0.0
                fp.write(f"| {reason} | {count} | {pct:.1f}% |\n")
            fp.write(f"\n")
            
            # P1-E: 按 regime 分组的护栏分解
            if report.get('gating_breakdown_by_regime'):
                fp.write(f"### 按 Regime 分组\n\n")
                for regime, breakdown in sorted(report['gating_breakdown_by_regime'].items()):
                    fp.write(f"#### {regime.upper()}\n\n")
                    fp.write(f"| 护栏原因 | 触发次数 | 占比 |\n")
                    fp.write(f"|---------|---------|------|\n")
                    regime_total = sum(breakdown.values())
                    for reason, count in sorted(breakdown.items(), key=lambda x: x[1], reverse=True):
                        pct = (count / regime_total * 100) if regime_total > 0 else 0.0
                        fp.write(f"| {reason} | {count} | {pct:.1f}% |\n")
                    fp.write(f"\n")
            
            # P1-E: 按分钟分组的护栏分解（最近5分钟）
            if report.get('gating_breakdown_by_minute') and report.get('per_minute'):
                fp.write(f"### 按分钟分组（最近5分钟）\n\n")
                fp.write(f"| 分钟 | 护栏原因 | 触发次数 |\n")
                fp.write(f"|------|---------|---------|\n")
                for i, minute_item in enumerate(report['per_minute'][-5:]):
                    minute_key = minute_item['minute']
                    if i < len(report['gating_breakdown_by_minute']):
                        minute_breakdown = report['gating_breakdown_by_minute'][i]
                        if minute_breakdown:
                            for reason, count in sorted(minute_breakdown.items(), key=lambda x: x[1], reverse=True):
                                fp.write(f"| {minute_key} | {reason} | {count} |\n")
                        else:
                            fp.write(f"| {minute_key} | (无) | 0 |\n")
                fp.write(f"\n")
        
        if report['warnings']:
            fp.write(f"## 警告\n\n")
            for warning in report['warnings']:
                fp.write(f"- {warning}\n")
            fp.write(f"\n")


def validate_config(config: Dict) -> List[str]:
    """P1-F: 配置校验器，返回警告列表"""
    warnings = []
    
    # 校验 consistency_min_per_regime
    signal_cfg = config.get("signal", {})
    consistency_min_per_regime = signal_cfg.get("consistency_min_per_regime", {})
    if consistency_min_per_regime:
        if not isinstance(consistency_min_per_regime, dict):
            warnings.append("signal.consistency_min_per_regime 应为字典类型，将使用默认值")
        else:
            for regime in ["active", "quiet"]:
                if regime in consistency_min_per_regime:
                    value = consistency_min_per_regime[regime]
                    if not isinstance(value, (int, float)) or value < 0 or value > 1:
                        warnings.append(f"signal.consistency_min_per_regime.{regime} 应为 0-1 之间的数值，当前值: {value}")
    
    # 校验 strategy_mode.triggers
    strategy_mode_cfg = config.get("strategy_mode", {})
    triggers_cfg = strategy_mode_cfg.get("triggers", {})
    if triggers_cfg:
        combine_logic = triggers_cfg.get("combine_logic", "OR")
        if combine_logic not in ["OR", "AND"]:
            warnings.append(f"strategy_mode.triggers.combine_logic 应为 OR 或 AND，当前值: {combine_logic}")
        
        schedule_cfg = triggers_cfg.get("schedule", {})
        if schedule_cfg.get("enabled", False):
            timezone = schedule_cfg.get("timezone", "UTC")
            try:
                import pytz
                pytz.timezone(timezone)
            except Exception:
                warnings.append(f"strategy_mode.triggers.schedule.timezone 无效: {timezone}，将使用默认值")
        
        market_cfg = triggers_cfg.get("market", {})
        if market_cfg.get("enabled", False):
            basic_gate_multiplier = market_cfg.get("basic_gate_multiplier", 0.5)
            if not isinstance(basic_gate_multiplier, (int, float)) or basic_gate_multiplier < 0:
                warnings.append(f"strategy_mode.triggers.market.basic_gate_multiplier 应为非负数值，当前值: {basic_gate_multiplier}")
    
    return warnings


def build_process_specs(
    project_root: Path,
    config_path: Path,
    sink_kind: str,
    output_dir: Path,
    symbols: Optional[List[str]] = None
) -> List[ProcessSpec]:
    """构建进程规格列表"""
    # P1-F: 加载并校验配置
    try:
        with open(config_path, "r", encoding="utf-8") as fp:
            config = yaml.safe_load(fp)
        config_warnings = validate_config(config)
        if config_warnings:
            for warning in config_warnings:
                logger.warning(f"[config.validation] {warning}")
    except Exception as e:
        logger.warning(f"[config.validation] 配置校验失败: {e}，将继续使用配置")
    
    specs = []
    
    # Harvest Server
    harvest_spec = ProcessSpec(
        name="harvest",
        cmd=["mcp.harvest_server.app", "--config", str(config_path)],
        env={},
        ready_probe="log_keyword",
        ready_probe_args={"keywords": ["event\": \"harvest.start", "成功导入所有核心组件"]},  # 检查启动日志
        health_probe="file_count",
        health_probe_args={
            "pattern": "deploy/data/ofi_cvd/raw/**/*.jsonl",
            "min_count": 1
        },
        restart_policy="on_failure",
        max_restarts=2
    )
    specs.append(harvest_spec)
    
    # Signal Server
    signal_env = {
        "V13_SINK": sink_kind,
        "V13_OUTPUT_DIR": str(output_dir),
        "V13_DEV_PATHS": "1"  # 开发模式路径注入（harvester 白名单已允许）
    }
    
    # 特征文件目录（支持 preview/raw 切换，优先环境变量，默认 preview）
    input_mode = os.getenv("V13_INPUT_MODE", "preview")  # preview | raw
    input_dir_env = os.getenv("V13_INPUT_DIR", "")
    
    if input_dir_env:
        features_dir = Path(input_dir_env)
    else:
        features_dir = project_root / "deploy" / "data" / "ofi_cvd" / input_mode
    
    logger.info(f"[signal.input] mode={input_mode} dir={features_dir}")
    
    signal_cmd = ["mcp.signal_server.app", "--config", str(config_path), "--input", str(features_dir), "--watch", "--sink", sink_kind, "--out", str(output_dir)]
    if symbols:
        signal_cmd.extend(["--symbols"] + symbols)
    
    signal_ready_probe = "file_exists" if sink_kind == "jsonl" else "sqlite_connect"
    # 使用相对路径（相对于 project_root）
    try:
        if output_dir.is_absolute():
            output_dir_rel = output_dir.relative_to(project_root)
        else:
            output_dir_rel = Path(output_dir)
    except ValueError:
        # 如果无法计算相对路径，使用绝对路径（会在探针中处理）
        output_dir_rel = output_dir
    
    signal_ready_args = (
        {"pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl")} if sink_kind == "jsonl"
        else {"db_path": str(output_dir_rel / "signals.db")}
    )
    
    signal_health_args = (
        {
            "pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl"),
            "min_count": 1,
            "min_new_last_seconds": 120,  # 最近120秒内
            "min_new_count": 1,  # 至少1个新文件
            "max_idle_seconds": 60  # 最近60秒内必须有文件更新
        } if sink_kind == "jsonl"
        else {
            "db_path": str(output_dir_rel / "signals.db"),
            "min_growth_window_seconds": 120,  # 最近2分钟
            "min_growth_count": 1  # 至少1行增长
        }
    )
    
    signal_spec = ProcessSpec(
        name="signal",
        cmd=signal_cmd,
        env=signal_env,
        ready_probe=signal_ready_probe,
        ready_probe_args=signal_ready_args,
        health_probe="file_count" if sink_kind == "jsonl" else "sqlite_query",
        health_probe_args=signal_health_args,
        restart_policy="on_failure",
        max_restarts=2
    )
    specs.append(signal_spec)
    
    # Broker Gateway Server (Mock)
    broker_output_path = output_dir_rel / "mock_orders.jsonl"
    broker_spec = ProcessSpec(
        name="broker",
        cmd=["mcp.broker_gateway_server.app", "--mock", "1", "--output", str(broker_output_path), "--seed", "42"],
        env={"PAPER_ENABLE": "1"},
        ready_probe="log_keyword",
        ready_probe_args={"keyword": "Mock Broker started"},
        health_probe="file_count",
        health_probe_args={
            "pattern": str(output_dir_rel / "mock_orders.jsonl"),
            "min_count": 1
        },
        restart_policy="on_failure",
        max_restarts=2
    )
    specs.append(broker_spec)
    
    # Report Server (可选，或由 Orchestrator 内置实现)
    # 这里我们由 Orchestrator 内置实现，不单独启动进程
    
    return specs


async def main_async(args):
    """异步主函数"""
    project_root = Path(__file__).resolve().parents[1]
    log_dir = project_root / "logs"
    artifacts_dir = project_root / "deploy" / "artifacts" / "ofi_cvd"
    runtime_dir = project_root / "runtime"
    
    # 记录开始时间
    started_at = datetime.utcnow()
    
    # 解析启用的模块
    enabled_modules = set(args.enable.split(",")) if args.enable else set()
    
    # 构建进程规格
    config_path = project_root / args.config if not Path(args.config).is_absolute() else Path(args.config)
    sink_kind = args.sink or "jsonl"
    output_dir = Path(args.output_dir) if args.output_dir else runtime_dir
    
    specs = build_process_specs(
        project_root=project_root,
        config_path=config_path,
        sink_kind=sink_kind,
        output_dir=output_dir,
        symbols=args.symbols.split(",") if args.symbols else None
    )
    
    # 创建 Supervisor
    supervisor = Supervisor(
        project_root=project_root,
        log_dir=log_dir,
        artifacts_dir=artifacts_dir
    )
    
    # 注册进程
    for spec in specs:
        if spec.name in enabled_modules:
            supervisor.register_process(spec)
    
    # 设置信号处理
    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，准备关闭...")
        asyncio.create_task(supervisor.graceful_shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 启动所有进程
        supervisor.start_all(enabled_modules)
        
        # 等待就绪
        ready = await supervisor.wait_ready(timeout_secs=120)
        if not ready:
            logger.warning("部分进程未就绪，但继续运行")
        
        # 启动健康检查
        health_task = asyncio.create_task(supervisor.tick_health(interval_secs=10))
        
        # 运行指定时长
        if args.minutes > 0:
            logger.info(f"运行 {args.minutes} 分钟...")
            await asyncio.sleep(args.minutes * 60)
        else:
            # 无限运行，直到收到信号
            logger.info("无限运行模式，等待信号...")
            await supervisor.shutdown_event.wait()
        
        # 停止健康检查
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        
        # 生成日报（只在启用 report 时输出）
        if "report" in enabled_modules:
            reporter = Reporter(
                project_root=project_root,
                output_dir=log_dir / "report"
            )
            report = reporter.generate_report(sink_kind, output_dir)
            reporter.save_report(report, format="both")
            
            # 保存运行清单
            ended_at = datetime.utcnow()
            duration_s = (ended_at - started_at).total_seconds()
            manifest = {
                "run_id": ended_at.strftime("%Y%m%d_%H%M%S"),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_s": duration_s,
                "config": str(config_path),
                "sink": sink_kind,
                "enabled_modules": list(enabled_modules),
                "status": supervisor.get_status(),
                "report": report
            }
            manifest_path = artifacts_dir / "run_logs" / f"run_manifest_{manifest['run_id']}.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("w", encoding="utf-8") as fp:
                json.dump(manifest, fp, ensure_ascii=False, indent=2)
            logger.info(f"运行清单已保存: {manifest_path}")
        
        # 优雅关闭
        await supervisor.graceful_shutdown()
        
    except KeyboardInterrupt:
        logger.info("收到中断信号")
        await supervisor.graceful_shutdown()
    except Exception as e:
        logger.exception("运行出错")
        await supervisor.graceful_shutdown()
        return 1
    
    return 0


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Orchestrator - 主控循环",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m orchestrator.run --config ./config/defaults.yaml --enable harvest,signal,broker,report --sink jsonl --minutes 30
  python -m orchestrator.run --config ./config/defaults.yaml --enable harvest,signal --sink sqlite --minutes 30 --symbols BTCUSDT,ETHUSDT
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="./config/defaults.yaml",
        help="主配置文件路径（默认: ./config/defaults.yaml）"
    )
    
    parser.add_argument(
        "--enable",
        type=str,
        default="",
        help="启用的模块（逗号分隔，可选: harvest,signal,broker,report）"
    )
    
    parser.add_argument(
        "--sink",
        type=str,
        choices=["jsonl", "sqlite"],
        default="jsonl",
        help="信号输出格式（jsonl/sqlite，默认: jsonl）"
    )
    
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="运行时长（分钟，默认: 30，0 表示无限运行）"
    )
    
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="交易对列表（逗号分隔，例如: BTCUSDT,ETHUSDT）"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="输出目录（默认: ./runtime）"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="打开详细日志"
    )
    
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        exitcode = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("收到中断信号")
        exitcode = 0
    except Exception as e:
        logger.exception("程序异常退出")
        exitcode = 1
    
    sys.exit(exitcode)


if __name__ == "__main__":
    main()
