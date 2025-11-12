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


def _perform_startup_path_check(features_dir: Path, input_mode: str, roots: Dict[str, Path]) -> None:
    """P1: 启动期路径自检
    
    Args:
        features_dir: 特征目录路径
        input_mode: 输入模式（raw/preview）
        roots: 路径根目录字典
    """
    if not features_dir.exists():
        logger.warning(
            f"[signal.input] 路径不存在: {features_dir}. "
            f"Harvester 兼容模式请确保写入 {roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']}"
        )
        logger.info(
            f"[signal.input] 建议: "
            f"1. 确认 Harvester 是否写入 {roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']}; "
            f"2. 若是历史回放，请先把数据放到 {roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']}; "
            f"3. 或设置 V13_INPUT_DIR 指向正确目录"
        )
        return
    
    # 列出前3个Parquet文件的相对路径和最近修改时间
    parquet_files = sorted(features_dir.rglob("*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    jsonl_files = sorted(features_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    
    if not parquet_files and not jsonl_files:
        logger.warning(
            f"[signal.input] 路径为空: {features_dir}. "
            f"确认 Harvester 是否写入 {roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']}"
        )
        logger.info(
            f"[signal.input] 建议: "
            f"1. 确认 Harvester 是否写入 {roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']}; "
            f"2. 若是历史回放，请先把数据放到 {roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']}; "
            f"3. 或设置 V13_INPUT_DIR 指向正确目录"
        )
        return
    
    # 显示前3个文件的相对路径和修改时间
    logger.info(f"[signal.input] 路径自检通过: {features_dir}")
    if parquet_files:
        logger.info(f"[signal.input] 找到 {len(list(features_dir.rglob('*.parquet')))} 个Parquet文件，示例:")
        for i, pf in enumerate(parquet_files, 1):
            rel_path = pf.relative_to(features_dir)
            mtime = datetime.fromtimestamp(pf.stat().st_mtime)
            logger.info(f"  {i}. {rel_path} (修改时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')})")
    if jsonl_files:
        logger.info(f"[signal.input] 找到 {len(list(features_dir.rglob('*.jsonl')))} 个JSONL文件，示例:")
        for i, jf in enumerate(jsonl_files[:3], 1):
            rel_path = jf.relative_to(features_dir)
            mtime = datetime.fromtimestamp(jf.stat().st_mtime)
            logger.info(f"  {i}. {rel_path} (修改时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')})")


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
        # TASK-07A: 关闭顺序记录
        self.shutdown_order = []
        # TASK-07A: 资源使用监控
        self.resource_usage = {
            "max_rss_mb": 0,
            "max_open_files": 0,
            "samples": []  # 定期采样记录
        }
        
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
        
        # 启动顺序：harvest -> signal -> strategy -> broker -> report
        order = ["harvest", "signal", "strategy", "broker", "report"]
        
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
            
            # P1: 就绪探针（log_keyword）读取尾部而非整文件
            # 同时检查 stdout 和 stderr（某些进程可能将日志输出到 stderr，如 Broker）
            log_files = []
            if state.stdout_log and state.stdout_log.exists():
                log_files.append(state.stdout_log)
            if state.stderr_log and state.stderr_log.exists():
                log_files.append(state.stderr_log)
            
            for log_file in log_files:
                if keywords:
                    try:
                        # 对于新启动的进程，同时检查日志开头和尾部
                        # 开头部分（前 32KB）：包含启动日志
                        # 尾部部分（后 64KB）：包含最新日志
                        with log_file.open("rb") as fp:
                            # 读取开头部分
                            head = fp.read(32 * 1024).decode("utf-8", errors="replace")
                            # 读取尾部部分
                            fp.seek(0, 2)  # 移动到文件末尾
                            size = fp.tell()
                            fp.seek(max(0, size - 64 * 1024), 0)  # 只读最后 64KB
                            tail = fp.read().decode("utf-8", errors="replace")
                        
                        # 合并开头和尾部内容进行搜索
                        content = head + tail
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
                        # P0: SQLite 就绪探针增加 schema 检测
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
                        if not cursor.fetchone():
                            conn.close()
                            return False
                        conn.close()
                        return True
                    except Exception:
                        pass
        
        return False
    
    async def tick_health(self, interval_secs: int = 10):
        """周期性健康检查"""
        self.running = True
        
        while self.running and not self.shutdown_event.is_set():
            # TASK-07A: 更新资源使用情况
            self._update_resource_usage()
            
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
                            
                            # P0: SQLite 健康探针 - 缺表/空表时给出明确信号
                            # 先检查 signals 表是否存在
                            try:
                                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='signals'")
                                if cursor.fetchone()[0] == 0:
                                    logger.warning("[health] signals 表不存在")
                                    conn.close()
                                    return False
                            except Exception as e:
                                logger.warning(f"[health] 检查 signals 表失败: {e}")
                                conn.close()
                                return False
                            
                            # 查询最近窗口内的行数（假设有 ts_ms 字段）
                            # Strategy 健康检查：检查总信号数增长（不要求 confirm=1）
                            # 因为 strategy 的健康应该反映"是否有新信号产生"，而不是"是否有确认信号"
                            try:
                                cursor.execute("""
                                    SELECT COUNT(*) FROM signals 
                                    WHERE ts_ms >= ?
                                """, (window_start_ms,))
                                recent_count = cursor.fetchone()[0]
                                
                                if recent_count < min_growth_count:
                                    conn.close()
                                    return False
                            except sqlite3.OperationalError as op_e:
                                # P0: 表或字段不存在，明确失败并告警
                                logger.warning(f"[health] SQLite 查询失败（表或字段缺失）: {op_e}")
                                conn.close()
                                return False
                        
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
        
        # TASK-07A: 记录关闭顺序：report -> broker -> strategy -> signal -> harvest
        order = ["report", "broker", "strategy", "signal", "harvest"]
        
        for name in order:
            if name in self.processes:
                state = self.processes[name]
                if state.process is not None:
                    logger.info(f"关闭 {name}...")
                    # TASK-07A: 记录关闭顺序
                    self.shutdown_order.append(name)
                    try:
                        # TASK-07A: 先发送SIGTERM，给进程时间执行清理
                        # Windows上terminate()发送SIGTERM，进程应该有时间执行atexit和信号处理
                        state.process.terminate()
                        # 等待最多 10 秒，让进程有时间执行清理（特别是SQLite队列刷新）
                        try:
                            state.process.wait(timeout=10)
                            logger.debug(f"{name} 已正常退出")
                        except subprocess.TimeoutExpired:
                            logger.warning(f"{name} 未在 10s 内退出，强制终止")
                            state.process.kill()
                            state.process.wait()
                    except Exception as e:
                        logger.error(f"关闭 {name} 时出错: {e}")
        
        logger.info("所有进程已关闭")
    
    def get_shutdown_order(self) -> List[str]:
        """TASK-07A: 获取关闭顺序"""
        return self.shutdown_order.copy()
    
    def get_resource_usage(self) -> Dict:
        """TASK-07A: 获取资源使用情况"""
        return self.resource_usage.copy()
    
    def get_harvester_metrics(self) -> Dict:
        """TASK-07A: 从harvester日志中提取SLO指标"""
        metrics = {
            "queue_dropped": 0,
            "substream_timeout_detected": False,
            "reconnect_count": 0
        }
        
        # 从harvest进程的日志中提取指标
        if "harvest" in self.processes:
            state = self.processes["harvest"]
            if state.stdout_log and state.stdout_log.exists():
                try:
                    # 读取日志文件（只读最后64KB）
                    with state.stdout_log.open("rb") as fp:
                        fp.seek(0, 2)  # 移动到文件末尾
                        size = fp.tell()
                        fp.seek(max(0, size - 64 * 1024), 0)  # 只读最后64KB
                        log_content = fp.read().decode("utf-8", errors="replace")
                    
                    # 提取queue_dropped
                    import re
                    queue_dropped_matches = re.findall(r'queue_dropped[:\s=]+(\d+)', log_content, re.IGNORECASE)
                    if queue_dropped_matches:
                        metrics["queue_dropped"] = max(int(m) for m in queue_dropped_matches)
                    
                    # 提取substream_timeout_detected
                    timeout_matches = re.findall(r'substream_timeout_detected[:\s=]+(true|false)', log_content, re.IGNORECASE)
                    if timeout_matches:
                        metrics["substream_timeout_detected"] = any(m.lower() == "true" for m in timeout_matches)
                    
                    # 提取reconnect_count
                    reconnect_matches = re.findall(r'reconnect[_\s]*count[:\s=]+(\d+)', log_content, re.IGNORECASE)
                    if reconnect_matches:
                        metrics["reconnect_count"] = max(int(m) for m in reconnect_matches)
                except Exception as e:
                    logger.warning(f"[harvester_metrics] 提取指标失败: {e}")
        
        return metrics
    
    def _update_resource_usage(self):
        """TASK-07A: 更新资源使用情况"""
        try:
            import psutil
            current_process = psutil.Process()
            
            # RSS (Resident Set Size) in MB
            rss_mb = current_process.memory_info().rss / 1024 / 1024
            
            # 打开文件数
            try:
                open_files = len(current_process.open_files())
            except (psutil.AccessDenied, AttributeError):
                # Windows 可能不支持，或需要权限
                open_files = 0
            
            # 更新最大值
            if rss_mb > self.resource_usage["max_rss_mb"]:
                self.resource_usage["max_rss_mb"] = rss_mb
            if open_files > self.resource_usage["max_open_files"]:
                self.resource_usage["max_open_files"] = open_files
            
            # 记录采样（保留最近100个）
            self.resource_usage["samples"].append({
                "timestamp": datetime.utcnow().isoformat(),
                "rss_mb": rss_mb,
                "open_files": open_files
            })
            if len(self.resource_usage["samples"]) > 100:
                self.resource_usage["samples"].pop(0)
        except ImportError:
            logger.warning("[resource] psutil 未安装，无法监控资源使用")
        except Exception as e:
            logger.warning(f"[resource] 资源监控失败: {e}")
    
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
    
    # P0: Reporter 规范化护栏原因（guard_reason）别名→规范名映射表
    GUARD_REASON_NORMALIZATION = {
        "weak_signal": "weak_signal",
        "weak_signal_throttle": "weak_signal",
        "warmup": "warmup",
        "component_warmup": "warmup",
        "low_consistency": "low_consistency",
        "spread": "spread",
        "lag": "lag",
        "activity": "activity",
        "other": "other",
    }
    
    def __init__(self, project_root: Path, output_dir: Path):
        self.project_root = project_root
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # P0: 统一 Reporter 时区与业务时区
        import pytz
        report_tz_str = os.getenv("REPORT_TZ", "UTC")
        try:
            self.tz = pytz.timezone(report_tz_str)
        except Exception:
            logger.warning(f"无效的时区配置 REPORT_TZ={report_tz_str}，使用 UTC")
            self.tz = pytz.UTC
        # TASK-07A: 时序库导出统计
        self.timeseries_export_count = 0
        self.timeseries_export_errors = 0
        # P1: 时序库导出失败跟踪（用于连续失败告警）
        self._export_failure_history = []  # List of {"timestamp": ..., "failed": True/False}
        # TASK-07A: 告警记录（触发/恢复时间）
        self.alerts_history = []  # List of {"triggered_at": ..., "recovered_at": ..., "alert": ...}
        
        # P0.5: 启动时打印所有关键环境变量，便于复现与比对
        self._print_startup_config()
        
        # P1: 启动期健康检查（时序库连接预检）
        self._check_timeseries_health()
    
    def _normalize_guard_reason(self, reason: str) -> str:
        """规范化护栏原因名称，统一别名到规范名"""
        reason_lower = reason.lower().strip()
        # 先尝试精确匹配
        if reason_lower in self.GUARD_REASON_NORMALIZATION:
            return self.GUARD_REASON_NORMALIZATION[reason_lower]
        # 尝试前缀匹配（如 "weak_signal_xxx" -> "weak_signal"）
        for key, normalized in self.GUARD_REASON_NORMALIZATION.items():
            if reason_lower.startswith(key):
                return normalized
        # 默认返回原值（小写）
        return reason_lower
    
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
            "gating_breakdown_by_minute": [],  # P1-E: 按分钟分组的护栏分解
            # P1-C: 报表补充"处理吞吐"与"重叠窗口摘要"
            "rows_processed": 0,  # 处理的总行数（包括未确认）
            "files_read": 0,  # 读取的文件数
            "first_minute": None,  # 第一个分钟键
            "last_minute": None  # 最后一个分钟键
        }
        
        # P1: 事件→信号联动数据准备
        report["event_signal_linkage"] = {
            "events": {},
            "linkage": {}
        }
        
        # P1: 时序库导出数据准备
        report["timeseries_data"] = {
            "total": 0,
            "gating_breakdown": {},
            "strong_ratio": 0.0,
            "per_minute": []
        }
        
        # P0: 读取RUN_ID用于对账（如果环境变量未设置，尝试从run_manifest读取）
        run_id = os.getenv("RUN_ID", "")
        if not run_id:
            # 尝试从run_manifest读取
            manifest_path = runtime_dir.parent / "run_logs" / f"run_manifest_*.json"
            manifest_files = sorted(Path(runtime_dir.parent / "run_logs").glob("run_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if manifest_files:
                try:
                    with open(manifest_files[0], "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                        run_id = manifest.get("run_id", "")
                except Exception:
                    pass
        
        # P0: 双 Sink 模式下，优先使用 JSONL 分析（SQLite 会在 Reporter 中单独验证）
        jsonl_count_with_run_id = 0
        jsonl_count_total = 0
        if sink_kind in ("jsonl", "dual"):
            jsonl_count_with_run_id, jsonl_count_total = self._analyze_jsonl(runtime_dir, report, run_id)
        elif sink_kind == "sqlite":
            self._analyze_sqlite(runtime_dir, report, run_id)
        
        # P0: 如果JSONL端未匹配到任何run_id行，追加兼容空串run_id的兜底统计（用于告警诊断）
        if run_id and jsonl_count_with_run_id == 0 and jsonl_count_total > 0:
            report["warnings"].append("JSONL_RUN_ID_MISSING")
            logger.warning(f"[Reporter] JSONL端未匹配到run_id={run_id}的数据，但总数据量={jsonl_count_total}，可能存在run_id字段缺失问题")
        
        # 计算比率
        if report["total"] > 0:
            report["buy_ratio"] = report["buy_count"] / report["total"]
            report["sell_ratio"] = report["sell_count"] / report["total"]
            report["strong_ratio"] = (report["strong_buy_count"] + report["strong_sell_count"]) / report["total"]
        else:
            report["sell_ratio"] = 0.0
        
        # P1: 准备时序库导出数据
        report["timeseries_data"]["total"] = report["total"]
        report["timeseries_data"]["gating_breakdown"] = report["gating_breakdown"]
        report["timeseries_data"]["strong_ratio"] = report["strong_ratio"]
        report["timeseries_data"]["per_minute"] = report["per_minute"]
        
        # P1: 导出到时序库（如果配置了）
        self._export_to_timeseries(report)
        
        return report
    
    def _analyze_jsonl(self, runtime_dir: Path, report: Dict, run_id: Optional[str] = None) -> Tuple[int, int]:
        """分析 JSONL 文件
        返回: (匹配run_id的数量, 总数量)
        """
        signal_dir = runtime_dir / "ready" / "signal"
        if not signal_dir.exists():
            report["warnings"].append("信号目录不存在")
            return (0, 0)
        
        # 收集所有 JSONL 文件
        jsonl_files = sorted(signal_dir.rglob("*.jsonl"))
        if not jsonl_files:
            report["warnings"].append("未找到信号文件")
            return (0, 0)
        
        # P1-C: 报表补充"处理吞吐"与"重叠窗口摘要"
        report["files_read"] = len(jsonl_files)
        
        # 按分钟统计
        minute_counts = defaultdict(int)
        minute_timestamps = []
        total_signals = 0  # 所有信号（包括未确认）
        confirmed_signals = 0  # 确认的信号
        bad_lines = 0  # P1: Reporter 增加"错误/丢弃计数"
        
        for jsonl_file in jsonl_files:
            try:
                with jsonl_file.open("r", encoding="utf-8") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            signal = json.loads(line)
                            
                            # P0: 如果提供了run_id，只统计匹配的run_id
                            if run_id and signal.get("run_id") != run_id:
                                continue
                            
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
                                
                                # P0: Reporter 规范化护栏原因（guard_reason）别名→规范名映射
                                # 统一命名，保证统计维度稳定
                                normalized_reasons = [self._normalize_guard_reason(r) for r in reasons if r]
                                
                                for reason in normalized_reasons:
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
                                # P1-C: 记录第一个和最后一个分钟键
                                if report["first_minute"] is None or minute_key < report["first_minute"]:
                                    report["first_minute"] = minute_key
                                if report["last_minute"] is None or minute_key > report["last_minute"]:
                                    report["last_minute"] = minute_key
                        except json.JSONDecodeError:
                            # P1: Reporter 增加"错误/丢弃计数"
                            bad_lines += 1
                            continue
            except Exception as e:
                report["warnings"].append(f"读取文件失败 {jsonl_file}: {e}")
        
        # P1-C: 记录处理的总行数
        report["rows_processed"] = total_signals
        
        # 计算最近5分钟的节律
        if minute_timestamps:
            latest_minute = max(m for m, _ in minute_timestamps)
            for i in range(5):
                minute_key = latest_minute - i
                count = minute_counts.get(minute_key, 0)
                # P1: 分钟键更友好（同时保存人类可读时间）
                # P0: 统一 Reporter 时区与业务时区
                try:
                    from datetime import datetime
                    minute_ts_ms = minute_key * 60000
                    dt = datetime.fromtimestamp(minute_ts_ms / 1000, tz=self.tz)
                    human_readable = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    human_readable = None
                report["per_minute"].append({
                    "minute": minute_key,
                    "minute_human": human_readable,  # P1: 人类可读时间
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
        
        # P0: Reporter 告警细分（定位更快）
        if report["total"] == 0:
            if not jsonl_files:
                report["warnings"].append("NO_INPUT_FILES")
            elif total_signals > 0:
                report["warnings"].append("ALL_GATED")
            else:
                report["warnings"].append("QUIET_RUN")
        
        if report["per_minute"] and all(item["count"] == 0 for item in report["per_minute"]):
            report["warnings"].append("QUIET_RUN")
        
        if confirmed_signals == 0 and total_signals > 0:
            report["warnings"].append("NO_CONFIRMED_SIGNALS")
        
        # P1: Reporter 增加"错误/丢弃计数"
        if bad_lines > 0:
            report["warnings"].append(f"BAD_JSON_LINES={bad_lines}")
            report["dropped_bad_json"] = bad_lines
        
        # P0: 返回匹配run_id的数量和总数量
        return (confirmed_signals, total_signals)
    
    def _analyze_sqlite(self, runtime_dir: Path, report: Dict, run_id: Optional[str] = None):
        """分析 SQLite 数据库"""
        db_path = runtime_dir / "signals.db"
        if not db_path.exists():
            report["warnings"].append("信号数据库不存在")
            return
        
        # P0: 构建WHERE条件（支持run_id过滤）
        where_clause = "WHERE confirm = 1"
        params = []
        if run_id:
            where_clause += " AND run_id = ?"
            params.append(run_id)
        
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            cursor = conn.cursor()
            
            # 查询总数（只统计 confirm=1 的信号，与 JSONL 口径一致）
            cursor.execute(f"SELECT COUNT(*) FROM signals {where_clause}", params)
            report["total"] = cursor.fetchone()[0]
            
            # 查询买卖分布（基于 signal_type）
            cursor.execute(f"""
                SELECT 
                    CASE 
                        WHEN signal_type LIKE '%buy%' THEN 'BUY'
                        WHEN signal_type LIKE '%sell%' THEN 'SELL'
                        ELSE 'UNKNOWN'
                    END AS side,
                    COUNT(*) 
                FROM signals 
                {where_clause}
                GROUP BY side
            """, params)
            for side, count in cursor.fetchall():
                if side == "BUY":
                    report["buy_count"] = count
                elif side == "SELL":
                    report["sell_count"] = count
            
            # 查询强信号
            strong_where = where_clause + " AND signal_type LIKE '%strong%'"
            cursor.execute(f"""
                SELECT 
                    CASE 
                        WHEN signal_type LIKE '%buy%' THEN 'BUY'
                        WHEN signal_type LIKE '%sell%' THEN 'SELL'
                        ELSE 'UNKNOWN'
                    END AS side,
                    COUNT(*) 
                FROM signals 
                {strong_where}
                GROUP BY side
            """, params)
            for side, count in cursor.fetchall():
                if side == "BUY":
                    report["strong_buy_count"] = count
                elif side == "SELL":
                    report["strong_sell_count"] = count
            
            # 查询最近5分钟的节律（只统计 confirm=1 的信号）
            cursor.execute(f"""
                SELECT CAST(ts_ms / 60000 AS INTEGER) AS minute, COUNT(*) 
                FROM signals 
                {where_clause}
                GROUP BY minute 
                ORDER BY minute DESC 
                LIMIT 5
            """, params)
            for minute_key, count in cursor.fetchall():
                # P1: 分钟键更友好（同时保存人类可读时间）
                # P0: 统一 Reporter 时区与业务时区
                try:
                    from datetime import datetime
                    minute_ts_ms = minute_key * 60000
                    dt = datetime.fromtimestamp(minute_ts_ms / 1000, tz=self.tz)
                    human_readable = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    human_readable = None
                report["per_minute"].append({
                    "minute": minute_key,
                    "minute_human": human_readable,  # P1: 人类可读时间
                    "count": count
                })
            report["per_minute"].reverse()
            
            # P0: 填充 files_read 和 rows_processed（SQLite 无法直接获取，但可以从数据库统计）
            # 统计总行数（包括未确认的信号）
            cursor.execute("SELECT COUNT(*) FROM signals")
            report["rows_processed"] = cursor.fetchone()[0]
            
            # 统计文件数（通过不同的 ts_ms 范围估算，或从数据库元数据获取）
            # 由于 SQLite 不直接记录文件信息，这里使用一个估算值
            # 实际应该从 run_manifest 或其他地方获取
            report["files_read"] = 0  # SQLite 模式下无法直接获取文件数
            
            # P0: 填充 first_minute 和 last_minute
            cursor.execute(f"SELECT MIN(ts_ms), MAX(ts_ms) FROM signals {where_clause}", params)
            result = cursor.fetchone()
            if result and result[0] and result[1]:
                min_ts_ms = result[0]
                max_ts_ms = result[1]
                report["first_minute"] = min_ts_ms // 60000
                report["last_minute"] = max_ts_ms // 60000
            else:
                report["first_minute"] = None
                report["last_minute"] = None
            
            # 查询总信号数（包括未确认）用于告警（如果提供了run_id，也按run_id过滤）
            total_where = "WHERE 1=1"
            total_params = []
            if run_id:
                total_where += " AND run_id = ?"
                total_params.append(run_id)
            cursor.execute(f"SELECT COUNT(*) FROM signals {total_where}", total_params)
            total_signals = cursor.fetchone()[0]
            
            # P0: 统计 gating breakdown（从 guard_reason 字段），并做规范化处理
            # 构建gating查询的WHERE条件（包含run_id过滤，但不要求confirm=1，因为gating统计包括所有信号）
            gating_where = "WHERE guard_reason IS NOT NULL AND guard_reason != ''"
            gating_params = []
            if run_id:
                gating_where += " AND run_id = ?"
                gating_params.append(run_id)
            cursor.execute(f"""
                SELECT guard_reason, COUNT(*) 
                FROM signals 
                {gating_where}
                GROUP BY guard_reason
            """, gating_params)
            for reason, count in cursor.fetchall():
                # P0: 处理多个原因（逗号分隔），并做规范化（与JSONL路径一致）
                if "," in reason:
                    reasons = [r.strip() for r in reason.split(",")]
                    # P0: 规范化护栏原因名称
                    normalized_reasons = [self._normalize_guard_reason(r) for r in reasons if r]
                    for r in normalized_reasons:
                        if r:
                            report["gating_breakdown"][r] = report["gating_breakdown"].get(r, 0) + count
                else:
                    # P0: 规范化单个原因
                    normalized_reason = self._normalize_guard_reason(reason)
                    report["gating_breakdown"][normalized_reason] = report["gating_breakdown"].get(normalized_reason, 0) + count
            
            # P0: Reporter 告警细分（定位更快）
            if report["total"] == 0:
                if total_signals == 0:
                    report["warnings"].append("NO_INPUT_FILES")
                elif total_signals > 0:
                    report["warnings"].append("ALL_GATED")
                else:
                    report["warnings"].append("QUIET_RUN")
            
            if report["per_minute"] and all(item["count"] == 0 for item in report["per_minute"]):
                report["warnings"].append("QUIET_RUN")
            
            if report["total"] == 0 and total_signals > 0:
                report["warnings"].append("NO_CONFIRMED_SIGNALS")
            
            conn.close()
        except Exception as e:
            report["warnings"].append(f"查询数据库失败: {e}")
        
        # P0.5: 如果时序库健康检查失败，添加到warnings
        if hasattr(self, '_timeseries_health_warning'):
            report["warnings"].append(f"时序库健康检查: {self._timeseries_health_warning}")
    
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
    
    def _export_to_timeseries(self, report: Dict):
        """P1: 导出数据到时序库（如果配置了）"""
        # 检查是否配置了时序库导出
        timeseries_enabled = os.getenv("TIMESERIES_ENABLED", "0") == "1"
        if not timeseries_enabled:
            return
        
        timeseries_type = os.getenv("TIMESERIES_TYPE", "prometheus").lower()
        timeseries_url = os.getenv("TIMESERIES_URL", "")
        
        if not timeseries_url:
            logger.warning("[timeseries] TIMESERIES_URL 未配置，跳过时序库导出")
            return
        
        try:
            ts_data = report.get("timeseries_data", {})
            timestamp = report.get("timestamp", datetime.utcnow().isoformat())
            
            # 推送指标
            if timeseries_type == "prometheus":
                self._export_to_prometheus(ts_data, timestamp, timeseries_url)
            elif timeseries_type == "influxdb":
                self._export_to_influxdb(ts_data, timestamp, timeseries_url)
            else:
                logger.warning(f"[timeseries] 不支持的时序库类型: {timeseries_type}")
                self.timeseries_export_errors += 1
                return
            
            # TASK-07A: 记录导出成功
            self.timeseries_export_count += 1
            # P1: 记录导出成功到历史
            self._export_failure_history.append({"timestamp": datetime.utcnow().isoformat(), "failed": False})
            # 只保留最近10分钟的历史（避免内存增长）
            if len(self._export_failure_history) > 10:
                self._export_failure_history.pop(0)
        except Exception as e:
            logger.warning(f"[timeseries] 导出失败: {e}")
            # TASK-07A: 记录导出错误
            self.timeseries_export_errors += 1
            # P1: 记录导出失败到历史
            self._export_failure_history.append({"timestamp": datetime.utcnow().isoformat(), "failed": True})
            # 只保留最近10分钟的历史（避免内存增长）
            if len(self._export_failure_history) > 10:
                self._export_failure_history.pop(0)
    
    def get_timeseries_export_stats(self) -> Dict:
        """TASK-07A: 获取时序库导出统计"""
        return {
            "export_count": self.timeseries_export_count,
            "error_count": self.timeseries_export_errors
        }
    
    def _print_startup_config(self) -> None:
        """P0.5/P1: 启动时打印所有关键环境变量，便于复现与比对"""
        logger.info("=" * 80)
        logger.info("[Reporter] 启动配置快照:")
        logger.info(f"  V13_SINK: {os.getenv('V13_SINK', '未设置')}")
        logger.info(f"  SQLITE_BATCH_N: {os.getenv('SQLITE_BATCH_N', '未设置（默认500）')}")
        logger.info(f"  SQLITE_FLUSH_MS: {os.getenv('SQLITE_FLUSH_MS', '未设置（默认500）')}")
        logger.info(f"  FSYNC_EVERY_N: {os.getenv('FSYNC_EVERY_N', '未设置（默认50）')}")
        logger.info(f"  TIMESERIES_ENABLED: {os.getenv('TIMESERIES_ENABLED', '未设置（默认0）')}")
        logger.info(f"  TIMESERIES_TYPE: {os.getenv('TIMESERIES_TYPE', '未设置（默认prometheus）')}")
        logger.info(f"  TIMESERIES_URL: {os.getenv('TIMESERIES_URL', '未设置')}")
        if os.getenv('TIMESERIES_TYPE', '').lower() == 'influxdb':
            logger.info(f"  INFLUX_URL: {os.getenv('INFLUX_URL', '未设置')}")
            logger.info(f"  INFLUX_ORG: {os.getenv('INFLUX_ORG', '未设置')}")
            logger.info(f"  INFLUX_BUCKET: {os.getenv('INFLUX_BUCKET', '未设置')}")
            logger.info(f"  INFLUX_TOKEN: {'已设置' if os.getenv('INFLUX_TOKEN') else '未设置'}")
        logger.info(f"  RUN_ID: {os.getenv('RUN_ID', '未设置')}")
        logger.info(f"  REPORT_TZ: {os.getenv('REPORT_TZ', '未设置（默认UTC）')}")
        logger.info(f"  V13_REPLAY_MODE: {os.getenv('V13_REPLAY_MODE', '未设置（默认0=LIVE）')}")
        logger.info(f"  V13_INPUT_MODE: {os.getenv('V13_INPUT_MODE', '未设置（默认preview）')}")
        logger.info("=" * 80)
    
    def _check_timeseries_health(self) -> None:
        """P1: 启动期健康检查（时序库连接预检）"""
        timeseries_enabled = os.getenv("TIMESERIES_ENABLED", "0") == "1"
        if not timeseries_enabled:
            return
        
        timeseries_type = os.getenv("TIMESERIES_TYPE", "prometheus").lower()
        timeseries_url = os.getenv("TIMESERIES_URL", "")
        
        if not timeseries_url:
            logger.warning("[timeseries.health] TIMESERIES_URL 未配置，跳过健康检查")
            return
        
        try:
            import requests
        except ImportError:
            logger.warning("[timeseries.health] requests 库未安装，跳过健康检查")
            return
        
        try:
            if timeseries_type == "prometheus":
                # Pushgateway健康检查
                response = requests.get(f"{timeseries_url}/metrics", timeout=5)
                if response.status_code == 200:
                    logger.info(f"[timeseries.health] Pushgateway可达: {timeseries_url}")
                else:
                    logger.warning(f"[timeseries.health] Pushgateway返回状态码: {response.status_code}")
            elif timeseries_type == "influxdb":
                # InfluxDB v2健康检查
                influx_url = os.getenv("INFLUX_URL", timeseries_url)
                influx_token = os.getenv("INFLUX_TOKEN", "")
                if influx_token:
                    headers = {"Authorization": f"Token {influx_token}"}
                    response = requests.get(f"{influx_url}/health", headers=headers, timeout=5)
                    if response.status_code == 200:
                        logger.info(f"[timeseries.health] InfluxDB可达: {influx_url}")
                    else:
                        logger.warning(f"[timeseries.health] InfluxDB返回状态码: {response.status_code}")
                else:
                    logger.warning("[timeseries.health] INFLUX_TOKEN 未配置，无法进行健康检查")
            else:
                logger.warning(f"[timeseries.health] 不支持的时序库类型: {timeseries_type}")
        except requests.exceptions.ConnectionError as e:
            warning_msg = f"[timeseries.health] 时序库连接失败（域名解析/连通性问题）: {e}"
            logger.warning(warning_msg)
            # P1: 添加重试/降级提示文案
            logger.warning("[timeseries.health] 提示: 时序库连接失败不会中断主流程，但指标将无法导出。请检查:")
            logger.warning(f"  1. TIMESERIES_URL是否正确: {timeseries_url}")
            logger.warning("  2. 时序库服务是否运行（Pushgateway/InfluxDB）")
            logger.warning("  3. 网络连接是否正常")
            logger.warning("  4. 防火墙/安全组是否允许访问")
            # P0.5: 连接失败时记录到warnings，便于日报诊断
            if not hasattr(self, '_timeseries_health_warning'):
                self._timeseries_health_warning = warning_msg
        except requests.exceptions.Timeout as e:
            warning_msg = f"[timeseries.health] 时序库连接超时: {e}"
            logger.warning(warning_msg)
            # P1: 添加重试/降级提示文案
            logger.warning("[timeseries.health] 提示: 时序库连接超时不会中断主流程，但指标将无法导出。请检查:")
            logger.warning(f"  1. TIMESERIES_URL是否可达: {timeseries_url}")
            logger.warning("  2. 网络延迟是否过高")
            logger.warning("  3. 时序库服务是否负载过高")
            if not hasattr(self, '_timeseries_health_warning'):
                self._timeseries_health_warning = warning_msg
        except Exception as e:
            warning_msg = f"[timeseries.health] 时序库健康检查失败: {e}"
            logger.warning(warning_msg)
            # P1: 添加重试/降级提示文案
            logger.warning("[timeseries.health] 提示: 时序库健康检查失败不会中断主流程，但指标将无法导出。")
            logger.warning("  请检查时序库配置和服务状态，或禁用时序库导出（TIMESERIES_ENABLED=0）")
            if not hasattr(self, '_timeseries_health_warning'):
                self._timeseries_health_warning = warning_msg
    
    def _export_to_prometheus(self, ts_data: Dict, timestamp: str, url: str):
        """导出到 Prometheus Pushgateway（带重试和指数退避）
        
        如果导出失败，抛出异常让调用者处理
        """
        try:
            import requests
        except ImportError:
            raise ImportError("requests 库未安装，无法导出到 Prometheus")
        
        # 构建指标
        metrics = []
        
        # total 指标
        total = ts_data.get("total", 0)
        metrics.append(f"signal_total {total}")
        
        # strong_ratio 指标
        strong_ratio = ts_data.get("strong_ratio", 0.0)
        metrics.append(f"signal_strong_ratio {strong_ratio}")
        
        # gating_breakdown 指标
        gating_breakdown = ts_data.get("gating_breakdown", {})
        for reason, count in gating_breakdown.items():
            reason_safe = reason.replace(".", "_").replace("-", "_")
            metrics.append(f'signal_gating_breakdown{{reason="{reason_safe}"}} {count}')
        
        # per_minute 指标（每分钟总量）
        per_minute = ts_data.get("per_minute", [])
        for minute_data in per_minute:
            minute = minute_data.get("minute", "")
            total_minute = minute_data.get("count", 0)
            metrics.append(f'signal_per_minute_total{{minute="{minute}"}} {total_minute}')
        
        # P1: 推送到 Pushgateway（带重试和指数退避）
        # P0.5: Prometheus格式要求：必须以换行符结尾，且每行格式为 <metric_name> <value> 或 <metric_name>{<labels>} <value>
        metrics_text = "\n".join(metrics)
        if metrics_text and not metrics_text.endswith("\n"):
            metrics_text += "\n"  # 确保以换行符结尾
        
        max_retries = 3
        retry_delays = [0.5, 1.0, 2.0]  # 指数退避：0.5s, 1s, 2s
        
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{url}/metrics/job/signal_reporter",
                    data=metrics_text,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                    timeout=5
                )
                response.raise_for_status()
                if attempt > 0:
                    logger.info(f"[timeseries] Prometheus导出成功（第{attempt + 1}次重试）")
                else:
                    logger.info(f"[timeseries] 已导出 {len(metrics)} 个指标到 Prometheus")
                return
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.warning(f"[timeseries] Prometheus导出失败（第{attempt + 1}次尝试）: {e}，{delay}秒后重试")
                    import time
                    time.sleep(delay)
                else:
                    logger.error(f"[timeseries] Prometheus导出失败（已重试{max_retries}次）: {e}")
        
        # 所有重试都失败，抛出最后一个异常
        raise last_exception
    
    def _export_to_influxdb(self, ts_data: Dict, timestamp: str, url: str):
        """导出到 InfluxDB v2（Line Protocol + API v2，带重试和指数退避）
        
        P0: 修正为v2标准写入：Line Protocol + POST {INFLUX_URL}/api/v2/write?org={ORG}&bucket={BUCKET}&precision=ns
        如果导出失败，抛出异常让调用者处理
        """
        try:
            import requests
        except ImportError:
            raise ImportError("requests 库未安装，无法导出到 InfluxDB")
        
        # P0: 读取InfluxDB v2必需的环境变量
        influx_url = os.getenv("INFLUX_URL", url)  # 兼容旧配置
        influx_org = os.getenv("INFLUX_ORG", "")
        influx_bucket = os.getenv("INFLUX_BUCKET", "")
        influx_token = os.getenv("INFLUX_TOKEN", "")
        
        if not influx_org or not influx_bucket or not influx_token:
            raise ValueError("InfluxDB v2 需要配置 INFLUX_ORG、INFLUX_BUCKET 和 INFLUX_TOKEN 环境变量")
        
        # P0: 构建Line Protocol格式的数据
        # 格式：measurement,tag1=value1,tag2=value2 field1=value1i,field2=value2 {timestamp_ns}
        lines = []
        
        # 解析timestamp为纳秒（InfluxDB v2要求）
        try:
            from datetime import datetime
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                dt = timestamp
            ts_ns = int(dt.timestamp() * 1e9)
        except Exception:
            import time
            ts_ns = int(time.time() * 1e9)
        
        # total 指标
        total = ts_data.get("total", 0)
        lines.append(f"signal_total value={total}i {ts_ns}")
        
        # strong_ratio 指标
        strong_ratio = ts_data.get("strong_ratio", 0.0)
        lines.append(f"signal_strong_ratio value={strong_ratio} {ts_ns}")
        
        # gating_breakdown 指标（带reason标签）
        gating_breakdown = ts_data.get("gating_breakdown", {})
        for reason, count in gating_breakdown.items():
            # 转义特殊字符（空格、逗号、等号）
            reason_escaped = reason.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")
            lines.append(f'signal_gating_breakdown,reason={reason_escaped} value={count}i {ts_ns}')
        
        # per_minute 指标（带minute标签）
        per_minute = ts_data.get("per_minute", [])
        for minute_data in per_minute:
            minute = minute_data.get("minute", "")
            total_minute = minute_data.get("count", 0)
            minute_escaped = minute.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")
            lines.append(f'signal_per_minute_total,minute={minute_escaped} value={total_minute}i {ts_ns}')
        
        # P0: 推送到 InfluxDB v2 API（Line Protocol格式）
        line_protocol_text = "\n".join(lines)
        endpoint = f"{influx_url}/api/v2/write"
        params = {
            "org": influx_org,
            "bucket": influx_bucket,
            "precision": "ns"
        }
        headers = {
            "Authorization": f"Token {influx_token}",
            "Content-Type": "text/plain; charset=utf-8"
        }
        
        # P1: 带重试和指数退避
        max_retries = 3
        retry_delays = [0.5, 1.0, 2.0]  # 指数退避：0.5s, 1s, 2s
        
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    endpoint,
                    params=params,
                    data=line_protocol_text,
                    headers=headers,
                    timeout=5
                )
                response.raise_for_status()
                if attempt > 0:
                    logger.info(f"[timeseries] InfluxDB导出成功（第{attempt + 1}次重试）")
                else:
                    logger.info(f"[timeseries] 已导出 {len(lines)} 个数据点到 InfluxDB v2")
                return
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.warning(f"[timeseries] InfluxDB导出失败（第{attempt + 1}次尝试）: {e}，{delay}秒后重试")
                    import time
                    time.sleep(delay)
                else:
                    logger.error(f"[timeseries] InfluxDB导出失败（已重试{max_retries}次）: {e}")
        
        # 所有重试都失败，抛出最后一个异常
        raise last_exception
    
    def _check_alerts(self, report: Dict):
        """P1: 检查告警规则"""
        current_time = datetime.utcnow().isoformat()
        alerts = []
        
        # 告警规则 1: 连续 2 分钟 total == 0
        per_minute = report.get("per_minute", [])
        if len(per_minute) >= 2:
            last_two_minutes = per_minute[-2:]
            if all(m.get("count", 0) == 0 for m in last_two_minutes):
                alert = {
                    "level": "critical",
                    "rule": "total_zero_2min",
                    "message": "连续 2 分钟信号总量为 0",
                    "triggered_at": current_time,
                    "recovered_at": None,
                    "details": {
                        "minutes": [m.get("minute") for m in last_two_minutes]
                    }
                }
                alerts.append(alert)
                # TASK-07A: 记录告警历史
                self._record_alert(alert)
        
        # 告警规则 2: low_consistency 占比单分钟 > 80%
        gating_by_minute = report.get("gating_breakdown_by_minute", [])
        for i, minute_data in enumerate(per_minute):
            if i < len(gating_by_minute):
                minute = minute_data.get("minute", "")
                gating_breakdown = gating_by_minute[i]
                total_minute = minute_data.get("count", 0)
                
                if total_minute > 0:
                    low_consistency_count = gating_breakdown.get("low_consistency", 0)
                    low_consistency_ratio = low_consistency_count / total_minute
                    
                    if low_consistency_ratio > 0.8:
                        alert = {
                            "level": "warning",
                            "rule": "low_consistency_high",
                            "message": f"分钟 {minute} low_consistency 占比 {low_consistency_ratio:.2%} > 80%",
                            "triggered_at": current_time,
                            "recovered_at": None,
                            "details": {
                                "minute": minute,
                                "ratio": low_consistency_ratio,
                                "count": low_consistency_count,
                                "total": total_minute
                            }
                        }
                        alerts.append(alert)
                        # TASK-07A: 记录告警历史
                        self._record_alert(alert)
        
        # 告警规则 3: strong_ratio 短时崩塌（较 7 日移动中位数偏差 > 3σ）
        # 注意：这需要历史数据，当前实现仅做示例
        current_strong_ratio = report.get("strong_ratio", 0.0)
        # TODO: 从时序库读取 7 日移动中位数和标准差
        # 这里仅做示例，实际需要从时序库查询
        if current_strong_ratio < 0.01:  # 示例阈值
            alert = {
                "level": "warning",
                "rule": "strong_ratio_collapse",
                "message": f"强信号比例异常低: {current_strong_ratio:.2%}",
                "triggered_at": current_time,
                "recovered_at": None,
                "details": {
                    "current_ratio": current_strong_ratio
                }
            }
            alerts.append(alert)
            # TASK-07A: 记录告警历史
            self._record_alert(alert)
        
        # P1: 告警规则 4: 时序库导出连续失败
        if self.timeseries_export_errors > 0:
            # 检查连续失败次数（简化实现：基于错误计数）
            # 实际应该跟踪每分钟的导出状态
            consecutive_failures = self._get_consecutive_export_failures()
            if consecutive_failures >= 3:  # 连续3分钟失败
                alert = {
                    "level": "warning",
                    "rule": "timeseries_export_failure",
                    "message": f"时序库导出连续失败{consecutive_failures}分钟（总错误数: {self.timeseries_export_errors}）",
                    "triggered_at": current_time,
                    "recovered_at": None,
                    "details": {
                        "consecutive_failures": consecutive_failures,
                        "total_errors": self.timeseries_export_errors,
                        "export_count": self.timeseries_export_count
                    }
                }
                alerts.append(alert)
                self._record_alert(alert)
        
        # P1: 告警规则 5: 数据丢包（dropped > 0）
        dropped = report.get("dropped", 0)
        if dropped > 0:
            alert = {
                "level": "warning",
                "rule": "data_dropped",
                "message": f"检测到数据丢失: {dropped}条",
                "triggered_at": current_time,
                "recovered_at": None,
                "details": {
                    "dropped": dropped,
                    "total": report.get("total", 0)
                }
            }
            alerts.append(alert)
            self._record_alert(alert)
        
        # TASK-07A: 检查告警恢复（如果之前有告警但现在没有了）
        self._check_alert_recovery(alerts, current_time)
        
        return alerts
    
    def _record_alert(self, alert: Dict):
        """TASK-07A: 记录告警（如果之前没有相同的告警）"""
        rule = alert.get("rule")
        # 检查是否已有相同规则的未恢复告警
        existing = None
        for a in self.alerts_history:
            if a["alert"]["rule"] == rule and a["recovered_at"] is None:
                existing = a
                break
        
        if existing is None:
            # 新告警
            self.alerts_history.append({
                "triggered_at": alert["triggered_at"],
                "recovered_at": None,
                "alert": alert
            })
    
    def _get_consecutive_export_failures(self) -> int:
        """P1: 获取连续导出失败次数"""
        if not self._export_failure_history:
            return 0
        
        # 从最近开始检查连续失败次数
        consecutive = 0
        for entry in reversed(self._export_failure_history):
            if entry.get("failed", False):
                consecutive += 1
            else:
                break
        
        return consecutive
    
    def _check_alert_recovery(self, current_alerts: List[Dict], current_time: str):
        """TASK-07A: 检查告警恢复"""
        current_rules = {a.get("rule") for a in current_alerts}
        
        # 标记已恢复的告警
        for alert_history in self.alerts_history:
            if alert_history["recovered_at"] is None:
                rule = alert_history["alert"].get("rule")
                if rule not in current_rules:
                    # 告警已恢复
                    alert_history["recovered_at"] = current_time
    
    def get_alerts_history(self) -> Dict:
        """TASK-07A: 获取告警历史记录"""
        triggered = []
        recovered = []
        
        for alert_history in self.alerts_history:
            alert = alert_history["alert"].copy()
            alert["triggered_at"] = alert_history["triggered_at"]
            alert["recovered_at"] = alert_history["recovered_at"]
            
            if alert_history["recovered_at"]:
                recovered.append(alert)
            else:
                triggered.append(alert)
        
        return {
            "triggered": triggered,
            "recovered": recovered,
            "total_triggered": len(self.alerts_history),
            "total_recovered": len(recovered),
            "active_count": len(triggered)
        }
    
    def _collect_runtime_state(self, report: Dict, supervisor):
        """P1: 汇总 StrategyMode 快照到 runtime_state"""
        runtime_state = {
            "snapshots": [],
            "summary": {}
        }
        
        # 查找 signal 进程的日志文件
        signal_state = supervisor.processes.get("signal")
        if not signal_state or not signal_state.stdout_log:
            report["runtime_state"] = runtime_state
            return
        
        log_file = signal_state.stdout_log
        if not log_file.exists():
            report["runtime_state"] = runtime_state
            return
        
        try:
            # 读取日志文件，提取 StrategyMode 快照
            import json
            snapshots = []
            
            with log_file.open("r", encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    line = line.strip()
                    if "[StrategyMode]" in line:
                        # 提取 JSON 部分
                        json_start = line.find("{")
                        if json_start >= 0:
                            try:
                                snapshot_json = line[json_start:]
                                snapshot = json.loads(snapshot_json)
                                snapshots.append(snapshot)
                            except json.JSONDecodeError:
                                continue
            
            # 汇总统计
            if snapshots:
                # 按 symbol 分组
                by_symbol = {}
                for snapshot in snapshots:
                    symbol = snapshot.get("symbol", "UNKNOWN")
                    if symbol not in by_symbol:
                        by_symbol[symbol] = []
                    by_symbol[symbol].append(snapshot)
                
                # 计算汇总统计
                all_trades_per_min = [s.get("trades_per_min", 0) for s in snapshots]
                all_quotes_per_sec = [s.get("quotes_per_sec", 0) for s in snapshots]
                all_spread_bps = [s.get("spread_bps", 0) for s in snapshots]
                
                runtime_state["summary"] = {
                    "total_snapshots": len(snapshots),
                    "symbols": list(by_symbol.keys()),
                    "avg_trades_per_min": sum(all_trades_per_min) / len(all_trades_per_min) if all_trades_per_min else 0.0,
                    "avg_quotes_per_sec": sum(all_quotes_per_sec) / len(all_quotes_per_sec) if all_quotes_per_sec else 0.0,
                    "avg_spread_bps": sum(all_spread_bps) / len(all_spread_bps) if all_spread_bps else 0.0,
                    "min_trades_per_min": min(all_trades_per_min) if all_trades_per_min else 0.0,
                    "max_trades_per_min": max(all_trades_per_min) if all_trades_per_min else 0.0,
                    "min_spread_bps": min(all_spread_bps) if all_spread_bps else 0.0,
                    "max_spread_bps": max(all_spread_bps) if all_spread_bps else 0.0,
                }
                
                # 保存最近的快照（每个 symbol 最多 5 个）
                recent_snapshots = []
                for symbol, symbol_snapshots in by_symbol.items():
                    recent_snapshots.extend(sorted(symbol_snapshots, key=lambda x: x.get("ts_ms", 0), reverse=True)[:5])
                
                runtime_state["snapshots"] = sorted(recent_snapshots, key=lambda x: x.get("ts_ms", 0), reverse=True)[:20]
            
            report["runtime_state"] = runtime_state
        except Exception as e:
            logger.warning(f"[runtime_state] 收集失败: {e}")
            report["runtime_state"] = runtime_state
    
    def _collect_event_signal_linkage(self, report: Dict, supervisor):
        """P1: 将 Harvester 的异常/背离/波动事件计数纳入 Reporter，建立"事件→信号确认率"的联动表"""
        event_signal_linkage = {
            "events": {},
            "linkage": {}
        }
        
        # 查找 harvest 进程的日志文件
        harvest_state = supervisor.processes.get("harvest")
        if not harvest_state or not harvest_state.stdout_log:
            report["event_signal_linkage"] = event_signal_linkage
            return
        
        log_file = harvest_state.stdout_log
        if not log_file.exists():
            report["event_signal_linkage"] = event_signal_linkage
            return
        
        try:
            from collections import defaultdict
            event_counts = defaultdict(int)
            
            with log_file.open("r", encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    line = line.strip()
                    # 示例：查找 Harvester 报告的事件
                    # 实际需要根据 Harvester 的日志格式进行精确匹配
                    if "event" in line.lower() and "harvester" in line.lower():
                        if "conflict" in line.lower():
                            event_counts["conflict"] += 1
                        if "divergence" in line.lower():
                            event_counts["divergence"] += 1
                        if "abnormal_volatility" in line.lower() or "volatility" in line.lower():
                            event_counts["abnormal_volatility"] += 1
                        if "price_anomaly" in line.lower() or "anomaly" in line.lower():
                            event_counts["price_anomaly"] += 1
                        if "alignment_issue" in line.lower() or "alignment" in line.lower():
                            event_counts["alignment_issue"] += 1
            
            event_signal_linkage["events"] = dict(event_counts)
            
            # 模拟事件→信号确认率联动（基础版本）
            # 实际需要更复杂的逻辑，例如：
            # 1. 匹配事件发生的时间窗口
            # 2. 统计该窗口内信号的 confirm=1 比例
            # 3. 对比无事件时的信号确认率
            
            for event_type, count in event_counts.items():
                # 假设事件发生会降低信号确认率，这里只是一个示例
                estimated_impact_ratio = 0.8 if count > 0 else 1.0  # 假设有事件时确认率降到 80%
                event_signal_linkage["linkage"][event_type] = {
                    "event_count": count,
                    "estimated_impact_ratio": estimated_impact_ratio
                }
            
            report["event_signal_linkage"] = event_signal_linkage
        except Exception as e:
            logger.warning(f"[event_signal_linkage] 收集失败: {e}")
            report["event_signal_linkage"] = event_signal_linkage
    
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
            fp.write(f"| 分钟（人类可读） | 分钟键 | 信号数 |\n")
            fp.write(f"|---------------|--------|--------|\n")
            for item in report['per_minute']:
                minute_key = item['minute']
                # P1: 分钟键更友好（人类可读时分）
                # P0: 统一 Reporter 时区与业务时区
                try:
                    from datetime import datetime
                    minute_ts_ms = minute_key * 60000
                    dt = datetime.fromtimestamp(minute_ts_ms / 1000, tz=self.tz)
                    human_readable = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    human_readable = f"minute_{minute_key}"
                fp.write(f"| {human_readable} | {minute_key} | {item['count']} |\n")
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
            
            # P1: 按 Regime 的护栏分解与分时展示
            # 在日报中把"Quiet vs Active"各自的 low_consistency / weak_signal / warmup 占比画出
            if report.get('gating_breakdown_by_regime'):
                fp.write(f"### 按 Regime 分组（Quiet vs Active 对比）\n\n")
                
                # 计算每个 regime 的总护栏数
                regime_totals = {}
                for regime, breakdown in report['gating_breakdown_by_regime'].items():
                    regime_totals[regime] = sum(breakdown.values())
                
                # 重点关注的护栏原因（用于对比展示）
                key_reasons = ["low_consistency", "weak_signal", "warmup", "spread", "lag"]
                
                # 生成对比表格
                fp.write(f"| Regime | 总护栏数 | ")
                for reason in key_reasons:
                    fp.write(f"{reason} | ")
                fp.write(f"\n")
                fp.write(f"|--------|---------|")
                for _ in key_reasons:
                    fp.write(f"--------|")
                fp.write(f"\n")
                
                for regime in ["active", "normal", "quiet"]:
                    if regime in report['gating_breakdown_by_regime']:
                        breakdown = report['gating_breakdown_by_regime'][regime]
                        regime_total = regime_totals.get(regime, 0)
                        fp.write(f"| {regime.upper()} | {regime_total} | ")
                        for reason in key_reasons:
                            count = breakdown.get(reason, 0)
                            pct = (count / regime_total * 100) if regime_total > 0 else 0.0
                            fp.write(f"{count} ({pct:.1f}%) | ")
                        fp.write(f"\n")
                fp.write(f"\n")
                
                # 详细分解（保留原有格式）
                fp.write(f"### 详细分解\n\n")
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
                fp.write(f"| 分钟（人类可读） | 分钟键 | 护栏原因 | 触发次数 |\n")
                fp.write(f"|---------------|--------|---------|---------|\n")
                for i, minute_item in enumerate(report['per_minute'][-5:]):
                    minute_key = minute_item['minute']
                    # P1: 分钟键更友好（人类可读时分）
                    # P0: 统一 Reporter 时区与业务时区
                    try:
                        from datetime import datetime
                        minute_ts_ms = minute_key * 60000
                        dt = datetime.fromtimestamp(minute_ts_ms / 1000, tz=self.tz)
                        human_readable = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        human_readable = f"minute_{minute_key}"
                    
                    if i < len(report['gating_breakdown_by_minute']):
                        minute_breakdown = report['gating_breakdown_by_minute'][i]
                        if minute_breakdown:
                            for reason, count in sorted(minute_breakdown.items(), key=lambda x: x[1], reverse=True):
                                fp.write(f"| {human_readable} | {minute_key} | {reason} | {count} |\n")
                        else:
                            fp.write(f"| {human_readable} | {minute_key} | (无) | 0 |\n")
                fp.write(f"\n")
        
        if report['warnings']:
            fp.write(f"## 警告\n\n")
            for warning in report['warnings']:
                fp.write(f"- {warning}\n")
            fp.write(f"\n")
        
        # P1: 告警信息
        if report.get('alerts'):
            fp.write(f"## 告警\n\n")
            for alert in report['alerts']:
                level = alert.get('level', 'unknown').upper()
                message = alert.get('message', '')
                fp.write(f"- **{level}**: {message}\n")
            fp.write(f"\n")
        
        # P1: 运行态（StrategyMode 快照汇总）
        if report.get('runtime_state'):
            runtime_state = report['runtime_state']
            fp.write(f"## 运行态（StrategyMode 快照汇总）\n\n")
            
            # P2: 报表可观测性补强 - 当检测到preview时，在日报加一行提示
            input_mode = os.getenv("V13_INPUT_MODE", "preview")
            snapshots = runtime_state.get('snapshots', [])
            if input_mode == "preview" and not snapshots:
                fp.write(f"> **提示**: StrategyMode 快照在回放模式（preview）下默认为空，这是正常现象。\n\n")
            
            summary = runtime_state.get('summary', {})
            if summary:
                fp.write(f"### 汇总统计\n\n")
                fp.write(f"- **快照总数**: {summary.get('total_snapshots', 0)}\n")
                fp.write(f"- **交易对**: {', '.join(summary.get('symbols', []))}\n")
                fp.write(f"- **平均 TPS**: {summary.get('avg_trades_per_min', 0):.1f} trades/min\n")
                fp.write(f"- **平均 Quotes/sec**: {summary.get('avg_quotes_per_sec', 0):.1f}\n")
                fp.write(f"- **平均 Spread**: {summary.get('avg_spread_bps', 0):.2f} bps\n")
                fp.write(f"- **TPS 范围**: {summary.get('min_trades_per_min', 0):.1f} - {summary.get('max_trades_per_min', 0):.1f} trades/min\n")
                fp.write(f"- **Spread 范围**: {summary.get('min_spread_bps', 0):.2f} - {summary.get('max_spread_bps', 0):.2f} bps\n")
                fp.write(f"\n")
            
            snapshots = runtime_state.get('snapshots', [])
            if snapshots:
                fp.write(f"### 最近快照（最多 20 个）\n\n")
                fp.write(f"| 时间 | 交易对 | Mode | TPS | Quotes/sec | Spread (bps) | Volatility (bps) | Volume (USD) |\n")
                fp.write(f"|------|--------|------|-----|------------|---------------|------------------|--------------|\n")
                for snapshot in snapshots[:20]:
                    ts_ms = snapshot.get('ts_ms', 0)
                    symbol = snapshot.get('symbol', 'UNKNOWN')
                    mode = snapshot.get('mode', 'unknown')
                    trades_per_min = snapshot.get('trades_per_min', 0)
                    quotes_per_sec = snapshot.get('quotes_per_sec', 0)
                    spread_bps = snapshot.get('spread_bps', 0)
                    volatility_bps = snapshot.get('volatility_bps', 0)
                    volume_usd = snapshot.get('volume_usd', 0)
                    
                    # 格式化时间
                    try:
                        from datetime import datetime
                        dt = datetime.fromtimestamp(ts_ms / 1000, tz=self.tz)
                        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        time_str = str(ts_ms)
                    
                    fp.write(f"| {time_str} | {symbol} | {mode} | {trades_per_min:.1f} | {quotes_per_sec:.1f} | {spread_bps:.2f} | {volatility_bps:.2f} | {volume_usd:.0f} |\n")
                fp.write(f"\n")
        
        # P1: 事件→信号联动表
        if report.get('event_signal_linkage'):
            linkage_data = report['event_signal_linkage']
            events = linkage_data.get('events', {})
            linkage = linkage_data.get('linkage', {})
            
            if events and any(events.values()):
                fp.write(f"## 事件→信号联动分析\n\n")
                
                fp.write(f"### 事件统计\n\n")
                fp.write(f"| 事件类型 | 计数 |\n")
                fp.write(f"|---------|------|\n")
                for event_type, count in sorted(events.items(), key=lambda x: x[1], reverse=True):
                    if count > 0:
                        fp.write(f"| {event_type} | {count} |\n")
                fp.write(f"\n")
                
                if linkage:
                    fp.write(f"### 事件→信号确认率联动\n\n")
                    fp.write(f"| 事件类型 | 事件计数 | 预估影响比例 |\n")
                    fp.write(f"|---------|---------|-------------|\n")
                    for event_type, link_info in linkage.items():
                        event_count = link_info.get('event_count', 0)
                        impact_ratio = link_info.get('estimated_impact_ratio', 0.0)
                        fp.write(f"| {event_type} | {event_count} | {impact_ratio:.2%} |\n")
                    fp.write(f"\n")
                
                fp.write(f"**说明**: 事件计数来自 Harvester 日志，事件→信号确认率的关联分析需要根据时间窗口和事件位置进行精确匹配。\n\n")


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
    
    # P1: 校验阈值单调性：|strong_buy| ≥ |buy|、|strong_sell| ≥ |sell|
    thresholds_cfg = signal_cfg.get("thresholds", {})
    if thresholds_cfg:
        for regime in ["base", "active", "normal", "quiet"]:
            regime_thresholds = thresholds_cfg.get(regime, {})
            if regime_thresholds:
                buy = regime_thresholds.get("buy")
                strong_buy = regime_thresholds.get("strong_buy")
                sell = regime_thresholds.get("sell")
                strong_sell = regime_thresholds.get("strong_sell")
                
                # 校验 strong_buy >= buy（绝对值）
                if buy is not None and strong_buy is not None:
                    if abs(strong_buy) < abs(buy):
                        warnings.append(f"signal.thresholds.{regime}: |strong_buy| ({abs(strong_buy)}) < |buy| ({abs(buy)})，违反单调性")
                
                # 校验 |strong_sell| >= |sell|
                if sell is not None and strong_sell is not None:
                    if abs(strong_sell) < abs(sell):
                        warnings.append(f"signal.thresholds.{regime}: |strong_sell| ({abs(strong_sell)}) < |sell| ({abs(sell)})，违反单调性")
    
    # P1: 校验 sink 合法性与互斥项（例如 SQLite 需要可写目录）
    sink_cfg = config.get("sink", {})
    if sink_cfg:
        sink_kind = sink_cfg.get("kind", "jsonl")
        output_dir = sink_cfg.get("output_dir", "./runtime")
        
        if sink_kind == "sqlite":
            # SQLite 需要可写目录
            try:
                output_path = Path(output_dir)
                if output_path.exists() and not output_path.is_dir():
                    warnings.append(f"sink.output_dir 应为目录路径，当前值: {output_dir}")
                elif not output_path.exists():
                    # 尝试创建目录以验证权限
                    try:
                        output_path.mkdir(parents=True, exist_ok=True)
                    except PermissionError:
                        warnings.append(f"sink.output_dir 目录不可写: {output_dir}")
            except Exception as e:
                warnings.append(f"sink.output_dir 路径无效: {output_dir}, 错误: {e}")
    
    # P1: 校验批量参数边界（用于异步 SQLite Sink）
    # 注意：这些参数可能通过环境变量设置，这里只校验配置文件中显式设置的
    sqlite_batch_n = os.getenv("SQLITE_BATCH_N")
    sqlite_flush_ms = os.getenv("SQLITE_FLUSH_MS")
    
    if sqlite_batch_n:
        try:
            batch_n = int(sqlite_batch_n)
            if batch_n <= 0:
                warnings.append(f"环境变量 SQLITE_BATCH_N 应为正整数，当前值: {batch_n}")
        except ValueError:
            warnings.append(f"环境变量 SQLITE_BATCH_N 应为整数，当前值: {sqlite_batch_n}")
    
    if sqlite_flush_ms:
        try:
            flush_ms = int(sqlite_flush_ms)
            if flush_ms < 0 or (flush_ms > 0 and flush_ms < 50) or flush_ms > 5000:
                if flush_ms == 0:
                    # P1: 验证期允许0（即时刷新），不报错
                    pass
                else:
                    warnings.append(f"环境变量 SQLITE_FLUSH_MS 推荐在线在 [50, 5000] 范围内（验证期允许0），当前值: {flush_ms}")
        except ValueError:
            warnings.append(f"环境变量 SQLITE_FLUSH_MS 应为整数，当前值: {sqlite_flush_ms}")
    
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
        ready_probe_args={"keywords": ["harvest.start", "已加载配置文件", "最终使用的交易对数量"]},  # 检查启动日志（支持 JSON 和文本格式）
        health_probe="file_count",
        health_probe_args={
            # 修复：harvester 输出的是 .parquet 文件，不是 .jsonl
            "pattern": "deploy/data/ofi_cvd/raw/**/*.parquet",
            "min_count": 1,
            # P0: 健康检查在 smoke/回放场景放宽时间窗口要求
            # 如果使用历史数据或回放模式，不要求文件在最近120秒内修改
            # LIVE 模式：要求文件在最近 120 秒内修改（确保数据流正常）
            "min_new_last_seconds": 0 if os.getenv("V13_REPLAY_MODE", "0") == "1" or config_path.name.startswith("smoke") else 120,
            "min_new_count": 0 if os.getenv("V13_REPLAY_MODE", "0") == "1" or config_path.name.startswith("smoke") else 1
        },
        restart_policy="on_failure",
        max_restarts=2
    )
    specs.append(harvest_spec)
    
    # P0: 生成统一的RUN_ID，用于按run_id对账，避免跨次运行数据混入
    # 如果环境变量中已有RUN_ID，优先使用（允许测试脚本预设）
    run_id = os.getenv("RUN_ID", "")
    if not run_id:
        # 如果环境变量未设置，生成新的RUN_ID
        run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        try:
            short_head = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=project_root,
                stderr=subprocess.DEVNULL
            ).decode().strip()
            run_id = f"{run_id}-{short_head}"
        except Exception:
            pass  # 如果git不可用，只使用时间戳
    
    # Signal Server
    signal_env = {
        "V13_SINK": sink_kind,
        "V13_OUTPUT_DIR": str(output_dir),
        "V13_DEV_PATHS": "1",  # 开发模式路径注入（harvester 白名单已允许）
        "RUN_ID": run_id  # P0: 注入RUN_ID用于对账
    }
    logger.info(f"[orchestrator] RUN_ID={run_id}")
    
    # 特征文件目录（支持 preview/raw 切换，优先环境变量，默认 preview）
    input_mode = os.getenv("V13_INPUT_MODE", "preview")  # preview | raw
    
    # P0: 验证 input_mode 只允许 raw 或 preview
    if input_mode not in ("raw", "preview"):
        logger.error(f"[signal.input] Invalid V13_INPUT_MODE: {input_mode}. Must be 'raw' or 'preview'")
        raise ValueError(f"V13_INPUT_MODE must be 'raw' or 'preview', got: {input_mode}")
    
    # P1: 使用集中式路径常量
    from alpha_core.common.paths import get_data_root, resolve_roots
    roots = resolve_roots(project_root)
    
    input_dir_env = os.getenv("V13_INPUT_DIR", "")
    if input_dir_env:
        features_dir = Path(input_dir_env)
    else:
        features_dir = get_data_root(input_mode)
    
    # P1: 启动期路径自检（列出前3个文件 + 诊断信息）
    _perform_startup_path_check(features_dir, input_mode, roots)
    
    logger.info(f"[signal.input] mode={input_mode} dir={features_dir}")
    
    # P0: 回放场景移除 --watch，改为批处理模式（跑到数据耗尽）
    # 根因：SQLite 落库比 JSONL 写文件慢，在相同时长内处理的条目数不同
    # 回放场景应处理完固定文件集后退出，而不是持续拉流
    # P0: 健康/就绪探针基线分环境配置
    # 实时场景：保持现有时间窗口检查
    # SMOKE/回放场景：min_new_last_seconds=0（历史数据友好化）
    is_replay_mode = os.getenv("V13_REPLAY_MODE", "0") == "1" or config_path.name.startswith("replay")
    
    # P0: 支持双 Sink 模式（dual = jsonl + sqlite）
    actual_sink_kind = sink_kind
    if sink_kind == "dual":
        actual_sink_kind = "dual"  # signal_server 需要支持 dual
    signal_cmd = ["mcp.signal_server.app", "--config", str(config_path), "--input", str(features_dir), "--sink", actual_sink_kind, "--out", str(output_dir)]
    if not is_replay_mode:
        # 实时场景：使用 --watch 持续监控新文件
        signal_cmd.insert(-2, "--watch")
    if symbols:
        signal_cmd.extend(["--symbols"] + symbols)
    
    # P0: 双 Sink 模式下，检查 JSONL 文件存在（SQLite 连接检查在健康探针中）
    if sink_kind == "dual":
        signal_ready_probe = "file_exists"  # 优先检查 JSONL（更快）
    else:
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
    
    # P0: 双 Sink 模式下，就绪探针检查 JSONL 文件
    if sink_kind == "dual":
        signal_ready_args = {"pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl")}
    elif sink_kind == "jsonl":
        signal_ready_args = {"pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl")}
    else:
        signal_ready_args = {"db_path": str(output_dir_rel / "signals.db")}
    
    # P0: 健康/就绪探针基线分环境配置
    # 实时场景：保持现有时间窗口检查
    # SMOKE/回放场景：min_new_last_seconds=0（历史数据友好化）
    is_replay_mode = os.getenv("V13_REPLAY_MODE", "0") == "1" or config_path.name.startswith("replay")
    min_new_last_seconds = 0 if is_replay_mode else 120
    
    # P0: 双 Sink 模式下，健康探针使用 file_count（JSONL）
    if sink_kind == "dual":
        signal_health_args = {
            "pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl"),
            "min_count": 1,
            "min_new_last_seconds": min_new_last_seconds,  # P0: 回放场景设为 0
            "min_new_count": 1,  # 至少1个新文件
            "max_idle_seconds": 60 if not is_replay_mode else None  # P0: 回放场景不检查最大空闲时间
        }
    elif sink_kind == "jsonl":
        signal_health_args = {
            "pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl"),
            "min_count": 1,
            "min_new_last_seconds": min_new_last_seconds,  # P0: 回放场景设为 0
            "min_new_count": 1,  # 至少1个新文件
            "max_idle_seconds": 60 if not is_replay_mode else None  # P0: 回放场景不检查最大空闲时间
        }
    else:
        signal_health_args = {
            "db_path": str(output_dir_rel / "signals.db"),
            # 修复：SQLite 健康探针在回放场景放宽或禁用增长校验
            "min_growth_window_seconds": None if is_replay_mode else 120,  # 回放场景禁用增长校验
            "min_growth_count": 0 if is_replay_mode else 1  # 回放场景不要求增长
        }
    
    signal_spec = ProcessSpec(
        name="signal",
        cmd=signal_cmd,
        env=signal_env,
        ready_probe=signal_ready_probe,
        ready_probe_args=signal_ready_args,
        # P0: 双 Sink 模式下，使用 file_count 健康探针（JSONL）
        health_probe="file_count" if sink_kind in ("jsonl", "dual") else "sqlite_query",
        health_probe_args=signal_health_args,
        restart_policy="on_failure",
        max_restarts=2
    )
    specs.append(signal_spec)
    
    # Broker Gateway Server (Mock)
    broker_output_path = output_dir_rel / "mock_orders.jsonl"
    # P0: Broker 参数外露：抽样率
    broker_sample_rate = os.getenv("BROKER_SAMPLE_RATE", "0.2")
    broker_spec = ProcessSpec(
        name="broker",
        cmd=["mcp.broker_gateway_server.app", "--mock", "1", "--output", str(broker_output_path), "--seed", "42", "--sample_rate", broker_sample_rate],
        env={"PAPER_ENABLE": "1", "RUN_ID": run_id},  # P0: 注入RUN_ID用于对账
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
    
    # Strategy Server (新增：策略执行服务，包含风控模块)
    strategy_env = {
        "RUN_ID": run_id,
        "RISK_INLINE_ENABLED": os.getenv("RISK_INLINE_ENABLED", "false"),  # 默认关闭，回退到legacy
    }
    # TASK-A4: 传递 Binance API 凭证给 strategy 进程（testnet/live 模式需要）
    if os.getenv("BINANCE_API_KEY"):
        strategy_env["BINANCE_API_KEY"] = os.getenv("BINANCE_API_KEY")
    if os.getenv("BINANCE_API_SECRET"):
        strategy_env["BINANCE_API_SECRET"] = os.getenv("BINANCE_API_SECRET")
    
    # 确定signals目录（单一事实来源）
    signals_dir = output_dir_rel / "ready" / "signal"
    
    # 确定executor模式（从环境变量或配置）
    executor_mode = os.getenv("EXECUTOR_MODE", "testnet")  # testnet | live | backtest
    
    strategy_cmd = [
        "mcp.strategy_server.app",
        "--mode", executor_mode,
        "--config", str(config_path),
        "--signals-source", "auto",  # 自动检测JSONL或SQLite
        "--output", str(output_dir_rel),
        "--watch",  # TASK-A4: 启用持续监听模式，避免进程退出重启
    ]
    
    # 如果sink不是dual，传递给strategy_server
    if sink_kind != "dual":
        strategy_cmd.extend(["--sink", sink_kind])
    
    if symbols:
        strategy_cmd.extend(["--symbols"] + symbols)
    
    # Strategy 健康检查：监控信号增长（而非 execlog）
    # 优先使用 signals_v2.db（v2 格式），回退到 signals.db（v1 格式）
    # 回放模式：使用 file_count 检查 JSONL 文件新增（因为 ts_ms 是历史时间）
    # 实时模式：使用 sqlite_query 检查信号增长（120秒窗口，至少1条增长）
    if is_replay_mode or sink_kind in ("jsonl", "dual"):
        # 回放模式或 JSONL 模式：检查 JSONL 文件新增（更可靠，不依赖 ts_ms）
        strategy_spec = ProcessSpec(
            name="strategy",
            cmd=strategy_cmd,
            env=strategy_env,
            ready_probe="log_keyword",
            ready_probe_args={"keywords": ["Strategy Server", "Creating", "executor", "Reading signals", "started and ready"]},
            health_probe="file_count",  # 回放/JSONL模式：检查文件新增
            health_probe_args={
                "pattern": str(output_dir_rel / "ready" / "signal" / "**" / "*.jsonl"),
                "min_count": 0,  # 允许初始为空
                "min_new_last_seconds": 0 if is_replay_mode else 120,  # 回放场景禁用时间窗口
                "min_new_count": 0 if is_replay_mode else 1  # 回放场景不要求新增
            },
            restart_policy="on_failure",
            max_restarts=2
        )
    else:
        # SQLite 模式（非回放）：检查 SQLite 信号增长
        strategy_db_path = str(output_dir_rel / "signals_v2.db")
        if not (output_dir / "signals_v2.db").exists():
            strategy_db_path = str(output_dir_rel / "signals.db")
        
        strategy_spec = ProcessSpec(
            name="strategy",
            cmd=strategy_cmd,
            env=strategy_env,
            ready_probe="log_keyword",
            ready_probe_args={"keywords": ["Strategy Server", "Creating", "executor", "Reading signals", "started and ready"]},
            health_probe="sqlite_query",  # SQLite模式：检查信号增长
            health_probe_args={
                "db_path": strategy_db_path,
                "min_growth_window_seconds": 120,  # 实时模式：120秒窗口
                "min_growth_count": 1  # 至少1条增长
            },
            restart_policy="on_failure",
            max_restarts=2
        )
    specs.append(strategy_spec)
    
    # Report Server (报表生成服务)
    report_cmd = [
        "mcp.report_server.app",
        "--config", str(config_path),
        "--input", str(output_dir_rel),
        "--output", str(output_dir_rel / "reports"),
    ]
    
    report_spec = ProcessSpec(
        name="report",
        cmd=report_cmd,
        env={"RUN_ID": run_id},
        ready_probe="log_keyword",
        ready_probe_args={"keyword": "Report Server started"},
        health_probe="file_count",
        health_probe_args={
            "pattern": str(output_dir_rel / "reports" / "*.jsonl"),
            "min_count": 0,  # 允许初始为空
        },
        restart_policy="on_failure",
        max_restarts=2
    )
    specs.append(report_spec)
    
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
            
            # P1: 汇总 StrategyMode 快照到 runtime_state
            reporter._collect_runtime_state(report, supervisor)
            
            # P1: 收集事件→信号联动数据
            reporter._collect_event_signal_linkage(report, supervisor)
            
            # P1: 检查告警规则
            alerts = reporter._check_alerts(report)
            if alerts:
                logger.warning(f"[alerts] 检测到 {len(alerts)} 个告警:")
                for alert in alerts:
                    logger.warning(f"[alerts] {alert['level'].upper()}: {alert['message']}")
                report["alerts"] = alerts
            
            # P1: 从signal日志中提取sink_used（同时解析stdout/stderr，提高鲁棒性）
            sink_used = None
            signal_state = supervisor.processes.get("signal")
            if signal_state:
                # 优先从stdout提取
                log_files = []
                if signal_state.stdout_log and signal_state.stdout_log.exists():
                    log_files.append(signal_state.stdout_log)
                if signal_state.stderr_log and signal_state.stderr_log.exists():
                    log_files.append(signal_state.stderr_log)
                
                for log_file in log_files:
                    try:
                        with log_file.open("r", encoding="utf-8", errors="replace") as f:
                            for line in f:
                                if "[CoreAlgorithm] sink_used=" in line or "[CoreAlgorithm] Sink选择:" in line:
                                    # 提取sink类名
                                    if "sink_used=" in line:
                                        parts = line.split("sink_used=")
                                        if len(parts) > 1:
                                            sink_used = parts[1].strip().split()[0]  # 取第一个词（类名）
                                            break
                                    elif "最终生效=" in line:
                                        parts = line.split("最终生效=")
                                        if len(parts) > 1:
                                            sink_used = parts[1].strip().split()[0]
                                            break
                        if sink_used:
                            break
                    except Exception as e:
                        logger.warning(f"提取sink_used失败（{log_file}）: {e}")
            
            reporter.save_report(report, format="both")
        
        # Fix 1: TASK-09 复盘报表生成（如果启用report且存在回测结果）
        if "report" in enabled_modules:
            try:
                # 查找回测结果目录
                backtest_dirs = list(output_dir.glob("backtest*"))
                if backtest_dirs:
                    # 选择最新的回测结果目录
                    latest_backtest_dir = max(backtest_dirs, key=lambda p: p.stat().st_mtime)
                    
                    # 检查是否有backtest_*子目录
                    subdirs = list(latest_backtest_dir.glob("backtest_*"))
                    if subdirs:
                        logger.info(f"[Report] 发现回测结果目录: {latest_backtest_dir}")
                        
                        try:
                            # 导入ReportGenerator
                            import sys
                            sys.path.insert(0, str(project_root / "src"))
                            from alpha_core.report.summary import ReportGenerator
                            
                            # 生成复盘报表
                            generator = ReportGenerator(latest_backtest_dir)
                            report_file = generator.generate_report()
                            
                            if report_file:
                                logger.info(f"[Report] 复盘报表已生成: {report_file}")
                            else:
                                logger.warning("[Report] 复盘报表生成失败")
                        except Exception as e:
                            # Fix 1: 异常降级，不中断主流程
                            logger.warning(f"[Report] 生成复盘报表时出错（已降级）: {e}", exc_info=True)
                    else:
                        logger.debug("[Report] 未找到回测结果子目录，跳过复盘报表生成")
                else:
                    logger.debug("[Report] 未找到回测结果目录，跳过复盘报表生成")
            except Exception as e:
                # Fix 1: 异常降级，不中断主流程
                logger.warning(f"[Report] 检查回测结果时出错（已降级）: {e}", exc_info=True)
            
            # 保存运行清单
            ended_at = datetime.utcnow()
            duration_s = (ended_at - started_at).total_seconds()
            
            # P1: run_manifest 增强可追溯性
            git_head = None
            git_dirty = False
            config_sha1 = None
            features_manifest = None
            env_overrides = {}
            
            try:
                import subprocess
                import hashlib
                
                # Git 信息
                git_head = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=project_root,
                    stderr=subprocess.DEVNULL
                ).decode("utf-8").strip()
                git_status = subprocess.check_output(
                    ["git", "status", "--porcelain"],
                    cwd=project_root,
                    stderr=subprocess.DEVNULL
                ).decode("utf-8").strip()
                git_dirty = bool(git_status)
                
                # P1: config_sha1（配置文件内容 hash）
                if config_path.exists():
                    with config_path.open("rb") as fp:
                        config_content = fp.read()
                        config_sha1 = hashlib.sha1(config_content).hexdigest()
                
                # P1: features_manifest（输入目录/文件指纹摘要）
                input_mode = os.getenv("V13_INPUT_MODE", "preview")
                
                # P0: 验证 input_mode
                if input_mode not in ("raw", "preview"):
                    logger.warning(f"[source_manifest] Invalid V13_INPUT_MODE: {input_mode}, using 'preview'")
                    input_mode = "preview"
                
                # P1: 使用集中式路径常量
                from alpha_core.common.paths import get_data_root, resolve_roots
                roots = resolve_roots(project_root)
                
                input_dir_env = os.getenv("V13_INPUT_DIR", "")
                if input_dir_env:
                    features_dir = Path(input_dir_env)
                else:
                    features_dir = get_data_root(input_mode)
                
                # P1: 启动期路径自检
                _perform_startup_path_check(features_dir, input_mode, roots)
                
                if features_dir.exists():
                    # 收集 Parquet 和 JSONL 文件的前几个作为指纹
                    parquet_files = sorted(features_dir.rglob("*.parquet"))[:5]
                    jsonl_files = sorted(features_dir.rglob("*.jsonl"))[:5]
                    features_manifest = {
                        "input_dir": str(features_dir),
                        "input_mode": input_mode,
                        "sample_files": {
                            "parquet": [str(f.name) for f in parquet_files],
                            "jsonl": [str(f.name) for f in jsonl_files]
                        }
                    }
                
                # P1: env_overrides（关键 env 的最终值）
                env_overrides = {
                    "V13_INPUT_MODE": os.getenv("V13_INPUT_MODE", "preview"),
                    "V13_REPLAY_MODE": os.getenv("V13_REPLAY_MODE", "0"),
                    "V13_SINK": os.getenv("V13_SINK", sink_kind),
                    "REPORT_TZ": os.getenv("REPORT_TZ", "UTC"),
                    "BROKER_SAMPLE_RATE": os.getenv("BROKER_SAMPLE_RATE", "0.2"),
                    "RUN_ID": os.getenv("RUN_ID", ""),  # P1: 记录RUN_ID用于对账
                    "SQLITE_BATCH_N": os.getenv("SQLITE_BATCH_N", ""),  # P1: 记录SQLite参数
                    "SQLITE_FLUSH_MS": os.getenv("SQLITE_FLUSH_MS", ""),
                    "FSYNC_EVERY_N": os.getenv("FSYNC_EVERY_N", "")
                }
            except Exception as e:
                logger.warning(f"获取版本指纹失败: {e}")
            
            # TASK-07A: 收集所有需要的数据
            timeseries_export_stats = reporter.get_timeseries_export_stats() if "report" in enabled_modules else {}
            alerts_history = reporter.get_alerts_history() if "report" in enabled_modules else {}
            resource_usage = supervisor.get_resource_usage()
            shutdown_order = supervisor.get_shutdown_order()
            harvester_metrics = supervisor.get_harvester_metrics()
            
            # P0: 获取RUN_ID（从环境变量或生成，与build_process_specs一致）
            run_id_for_manifest = os.getenv("RUN_ID", "")
            if not run_id_for_manifest:
                # 如果环境变量未设置，使用时间戳生成（与build_process_specs一致）
                run_id_for_manifest = started_at.strftime("%Y%m%d_%H%M%S")
                try:
                    short_head = subprocess.check_output(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=project_root,
                        stderr=subprocess.DEVNULL
                    ).decode().strip()
                    run_id_for_manifest = f"{run_id_for_manifest}-{short_head}"
                except Exception:
                    pass
            
            manifest = {
                "run_id": run_id_for_manifest,  # P0: 使用统一的RUN_ID
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_s": duration_s,
                "config": str(config_path),
                "config_sha1": config_sha1,  # P1: 配置文件内容 hash
                "sink": sink_kind,
                "enabled_modules": list(enabled_modules),
                "status": supervisor.get_status(),
                "report": report,
                # TASK-07A: 新增字段
                "timeseries_export": timeseries_export_stats,
                "alerts": alerts_history,
                "resource_usage": {
                    "max_rss_mb": resource_usage.get("max_rss_mb", 0),
                    "max_open_files": resource_usage.get("max_open_files", 0)
                },
                "shutdown_order": shutdown_order,
                "harvester_metrics": harvester_metrics,
                "source_versions": {
                    "git_head": git_head,
                    "git_dirty": git_dirty,
                    "python_version": sys.version.split()[0],
                    "config_sha1": config_sha1,  # P1: 配置文件内容 hash
                    "features_manifest": features_manifest,  # P1: 输入目录/文件指纹摘要
                    "env_overrides": env_overrides,  # P1: 关键 env 的最终值
                    "sink_used": sink_used  # P1: 实际使用的sink类名（从signal日志中提取）
                }
            }
            manifest_path = artifacts_dir / "run_logs" / f"run_manifest_{manifest['run_id']}.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("w", encoding="utf-8") as fp:
                json.dump(manifest, fp, ensure_ascii=False, indent=2)
            logger.info(f"运行清单已保存: {manifest_path}")
            
            # TASK-07A: 生成 source_manifest.json
            try:
                symbols = []
                config_snapshot = {}
                if config_path.exists():
                    symbols = _extract_symbols_from_config(config_path)
                    config_snapshot = _get_config_snapshot(config_path)
                
                # P1: LIVE/preview标识与输入目录收敛
                # 报告里把"数据源模式（raw/preview）、--watch开启与否、特征目录路径"三者一起写入source_manifest
                input_mode = env_overrides.get("V13_INPUT_MODE", "preview")
                
                # P0: 验证 input_mode
                if input_mode not in ("raw", "preview"):
                    logger.warning(f"[run_manifest] Invalid V13_INPUT_MODE: {input_mode}, using 'preview'")
                    input_mode = "preview"
                
                replay_mode = env_overrides.get("V13_REPLAY_MODE", "0") == "1"
                is_replay_mode = replay_mode or config_path.name.startswith("replay")
                # P1: 判断--watch是否开启（LIVE模式开启，回放模式关闭）
                watch_enabled = not is_replay_mode
                # P1: 使用集中式路径常量
                from alpha_core.common.paths import get_data_root, resolve_roots
                roots = resolve_roots(project_root)
                
                # P1: 获取特征目录路径
                input_dir_env = env_overrides.get("V13_INPUT_DIR")
                if input_dir_env:
                    features_dir = Path(input_dir_env)
                else:
                    features_dir = get_data_root(input_mode)
                
                # P1: 启动期路径自检
                _perform_startup_path_check(features_dir, input_mode, roots)
                
                source_manifest = {
                    "run_id": manifest["run_id"],
                    "session_start": started_at.isoformat(),
                    "session_end": ended_at.isoformat(),
                    "symbols": symbols,
                    "ws_endpoint": env_overrides.get("WS_ENDPOINT", os.getenv("WS_ENDPOINT", "wss://fstream.binance.com")),
                    "ws_region": env_overrides.get("WS_REGION", os.getenv("WS_REGION", "default")),
                    "config_snapshot": config_snapshot,
                    "input_mode": input_mode,  # raw | preview
                    "replay_mode": replay_mode,  # true | false
                    "watch_enabled": watch_enabled,  # P1: --watch开启与否
                    "features_dir": str(features_dir)  # P1: 特征目录路径
                }
                source_manifest_path = artifacts_dir / f"source_manifest_{manifest['run_id']}.json"
                with source_manifest_path.open("w", encoding="utf-8") as fp:
                    json.dump(source_manifest, fp, ensure_ascii=False, indent=2)
                logger.info(f"数据源清单已保存: {source_manifest_path}")
            except Exception as e:
                logger.warning(f"生成source_manifest失败: {e}")
        
        # 优雅关闭
        await supervisor.graceful_shutdown()
        
        # TASK-07A: 关闭后更新manifest，添加关闭顺序
        if "report" in enabled_modules and manifest_path.exists():
            try:
                # 重新读取manifest
                with manifest_path.open("r", encoding="utf-8") as fp:
                    manifest = json.load(fp)
                
                # 更新关闭顺序
                manifest["shutdown_order"] = supervisor.get_shutdown_order()
                
                # 保存更新后的manifest
                with manifest_path.open("w", encoding="utf-8") as fp:
                    json.dump(manifest, fp, ensure_ascii=False, indent=2)
                logger.info(f"运行清单已更新（添加关闭顺序）: {manifest_path}")
            except Exception as e:
                logger.warning(f"更新manifest失败: {e}")
        
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
        choices=["jsonl", "sqlite", "dual"],
        default="jsonl",
        help="信号输出格式（jsonl/sqlite/dual，dual=同时写入jsonl+sqlite，默认: jsonl）"
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


def _extract_symbols_from_config(config_path: Path) -> List[str]:
    """TASK-07A: 从配置文件中提取symbol列表"""
    try:
        with config_path.open("r", encoding="utf-8") as fp:
            config = yaml.safe_load(fp)
        
        # 尝试从不同位置提取symbols
        symbols = []
        
        # 从harvest配置中提取
        harvest_cfg = config.get("harvest", {})
        if "symbols" in harvest_cfg:
            symbols_list = harvest_cfg["symbols"]
            if isinstance(symbols_list, list):
                symbols.extend(symbols_list)
            elif isinstance(symbols_list, str):
                symbols.extend([s.strip() for s in symbols_list.split(",")])
        
        # 从signal配置中提取
        signal_cfg = config.get("signal", {})
        if "symbols" in signal_cfg:
            symbols_list = signal_cfg["symbols"]
            if isinstance(symbols_list, list):
                symbols.extend(symbols_list)
            elif isinstance(symbols_list, str):
                symbols.extend([s.strip() for s in symbols_list.split(",")])
        
        # 去重并排序
        return sorted(list(set(symbols)))
    except Exception as e:
        logger.warning(f"提取symbols失败: {e}")
        return []


def _get_config_snapshot(config_path: Path) -> Dict:
    """TASK-07A: 获取配置快照（敏感信息已脱敏）"""
    try:
        with config_path.open("r", encoding="utf-8") as fp:
            config = yaml.safe_load(fp)
        
        # 创建配置快照（移除敏感信息）
        snapshot = {}
        
        # 保留关键配置项
        if "harvest" in config:
            harvest_snapshot = config["harvest"].copy()
            # 移除可能的敏感信息
            harvest_snapshot.pop("api_key", None)
            harvest_snapshot.pop("api_secret", None)
            snapshot["harvest"] = harvest_snapshot
        
        if "signal" in config:
            snapshot["signal"] = config["signal"].copy()
        
        if "broker" in config:
            broker_snapshot = config["broker"].copy()
            broker_snapshot.pop("api_key", None)
            broker_snapshot.pop("api_secret", None)
            snapshot["broker"] = broker_snapshot
        
        return snapshot
    except Exception as e:
        logger.warning(f"获取配置快照失败: {e}")
        return {}


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
