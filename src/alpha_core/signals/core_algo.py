#!/usr/bin/env python3
"""
Task 1.5 核心算法v1 - 信号层实现
直接调用成熟组件：OFI计算器、CVD计算器、融合指标、背离检测
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
import logging
import json
from pathlib import Path
import sys
import os
import time
import threading
import queue
import atexit
import sqlite3
import shutil
import uuid

# 导入成熟组件（使用 alpha_core 包路径）
from alpha_core.microstructure.ofi import RealOFICalculator, OFIConfig
from alpha_core.microstructure.cvd import RealCVDCalculator, CVDConfig
from alpha_core.microstructure.fusion import OFI_CVD_Fusion, OFICVDFusionConfig
from alpha_core.microstructure.divergence import DivergenceDetector, DivergenceConfig
from alpha_core.risk import StrategyModeManager, StrategyMode, MarketActivity

# TODO: 需要实现 config_loader 和 timestamp_normalizer
# from alpha_core.utils.config_loader import load_config
# from alpha_core.utils.timestamp_normalizer import normalize_ts_to_seconds

import argparse
from collections import deque

# 临时实现 normalize_ts_to_seconds（后续移至 utils 模块）
def normalize_ts_to_seconds(ts_ms: int) -> float:
    """将毫秒时间戳转换为秒（浮点数）"""
    return ts_ms / 1000.0

# 平台与环境读取工具
IS_WIN = (os.name == "nt")

def _get_int_env(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None and str(v).strip() != "" else int(default)
    except Exception:
        return int(default)

def _get_float_env(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None and str(v).strip() != "" else float(default)
    except Exception:
        return float(default)

# TODO: 实现 normalize_ts_to_seconds 函数
def normalize_ts_to_seconds(ts_ms: int) -> float:
    """将毫秒时间戳转换为秒（浮点数）"""
    return ts_ms / 1000.0

# ---- 可插拔 Sink 抽象 ----
class SignalSink:
    def emit(self, entry: dict): ...
    def close(self): ...

# ---- SafeJsonlWriter 安全I/O写入器 ----
class SafeJsonlWriter:
    def __init__(self, base_dir: Path, max_retries: int = 5, retry_sleep: float = 0.05):
        self.base_dir = Path(base_dir)
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def write_line(self, rel_path: Path, payload: dict):
        path = self.base_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False) + "\n"

        last_err = None
        for _ in range(self.max_retries):
            try:
                # 逐条追加 + 立刻冲刷，降低数据丢失
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                return
            except Exception as e:
                last_err = e
                time.sleep(self.retry_sleep)

        # 重试后仍失败：把错误丢到主 logger，但不让核心逻辑崩溃
        raise last_err

# ---- JSONL 分片 Sink：spool/.part 写 → 原子换名到 ready/.jsonl ----
class JsonlSink(SignalSink):
    def __init__(self, base_dir: Path, batch_n: int = 50, fsync_ms: int = 200):
        self.base_dir = Path(base_dir)
        self.spool = self.base_dir / "spool"
        self.ready = self.base_dir / "ready"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.ready.mkdir(parents=True, exist_ok=True)
        self.q = queue.Queue(maxsize=10000)
        self.batch_n = batch_n
        self.fsync_ms = fsync_ms
        self.state = {}  # symbol -> {"minute", "fh", "path", "count", "last_fsync"}
        self.dropped = 0  # 健康度上报：丢弃的消息数
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _atomic_move_with_retry(self, src: Path, dst: Path, attempts: int = 5, base_sleep: float = 0.05) -> Path:
        """在 Windows 上对可能的占用进行重试，最终保证数据发布成功。
        - 优先 os.replace 原子改名；
        - 若被占用/存在则线性退避重试 attempts 次；
        - 仍失败则落唯一名（pid+ts+随机后缀），或退化为 copy+remove。
        返回最终发布路径（可能是 dst，也可能是唯一名）。
        """
        last_err: Exception | None = None
        # 环境可配置（Windows 默认极速兜底）
        attempts_eff = _get_int_env("V13_JSONL_RENAME_ATTEMPTS", 1 if IS_WIN else int(attempts))
        sleep_eff = _get_float_env("V13_JSONL_RENAME_BASESLEEP", 0.0 if IS_WIN else float(base_sleep))
        for i in range(int(attempts_eff)):
            try:
                os.replace(src, dst)
                return dst
            except (PermissionError, FileExistsError) as e:
                last_err = e
                if sleep_eff > 0:
                    time.sleep(sleep_eff * (i + 1))

        # 唯一名兜底
        uniq = dst.with_name(f"{dst.stem}.{os.getpid()}.{int(time.time()*1000)}.{uuid.uuid4().hex[:6]}{dst.suffix}")
        # 抛光：在最终兜底前输出调试信息，便于定位长期占用
        try:
            if last_err is not None:
                logging.getLogger(__name__).debug(
                    f"[JsonlSink] atomic_move fallback: dst busy, last_err={last_err} -> publishing to {uniq}"
                )
        except Exception:
            pass
        try:
            os.replace(src, uniq)
            return uniq
        except Exception:
            # 最后手段：copy + remove，保证不丢数据
            shutil.copyfile(src, uniq)
            try:
                os.remove(src)
            except Exception:
                pass
            return uniq

    def emit(self, entry: dict):
        try:
            self.q.put(entry, timeout=0.2)
        except queue.Full:
            # 按需计数告警；这里丢弃以保障交易主路径
            self.dropped += 1

    def get_health(self):
        return {"queue_size": self.q.qsize(), "dropped": self.dropped, "open_files": len(self.state)}

    def _minute_key(self, ts_ms: int) -> str:
        # 用事件时间分片（UTC）；如需本地时间可改为 .fromtimestamp(..., tz=)
        dt = datetime.utcfromtimestamp((ts_ms or int(time.time()*1000)) / 1000.0)
        return dt.strftime("%Y%m%d_%H%M")

    def _open_state(self, symbol: str, minute: str):
        """打开分片文件，Windows 下增加重试与唯一名兜底，避免占用导致 PermissionError。
        支持通过环境变量调参：
        - V13_JSONL_OPEN_ATTEMPTS（默认：Win=2，否则=8）
        - V13_JSONL_OPEN_BASESLEEP（默认：Win=0.0，否则=0.05 秒）
        """
        pid = os.getpid()
        subdir = self.spool / "signal" / symbol
        subdir.mkdir(parents=True, exist_ok=True)

        base = subdir / f"signals_{minute}_{pid}.part"
        last: Exception | None = None
        open_attempts = _get_int_env("V13_JSONL_OPEN_ATTEMPTS", 2 if IS_WIN else 8)
        open_sleep = _get_float_env("V13_JSONL_OPEN_BASESLEEP", 0.0 if IS_WIN else 0.05)
        for i in range(int(open_attempts)):
            part = base if i == 0 else subdir / f"signals_{minute}_{pid}_{uuid.uuid4().hex[:6]}.part"
            try:
                fh = open(part, "a", encoding="utf-8", buffering=1)
                return {"minute": minute, "fh": fh, "path": part, "count": 0, "last_fsync": time.time()}
            except PermissionError as e:
                last = e
                if open_sleep > 0:
                    time.sleep(open_sleep * (i + 1))
        assert last is not None
        raise last

    def _rotate(self, symbol: str, st: dict):
        """将 spool/.part 发布到 ready/.jsonl，包含重试与唯一名兜底，失败不抛出。
        """
        try:
            st["fh"].flush(); os.fsync(st["fh"].fileno()); st["fh"].close()
        except Exception:
            pass
        # 原子换名到 ready 目录
        rel = st["path"].relative_to(self.spool)
        ready_path = (self.ready / rel).with_suffix(".jsonl")
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            published = self._atomic_move_with_retry(st["path"], ready_path)
            logging.getLogger(__name__).debug(f"[JsonlSink] rotated -> {published}")
        except Exception as e:
            logging.getLogger(__name__).warning(f"[JsonlSink] rotate failed: {e}")

    def _run(self):
        last_heartbeat_sec = -1
        while not self._stop.is_set():
            try:
                entry = self.q.get(timeout=0.1)
            except queue.Empty:
                # 周期性批量 fsync
                now = time.time()
                current_minute = self._minute_key(int(now * 1000))
                for sym, st in list(self.state.items()):
                    if st["fh"] and (now - st["last_fsync"]) * 1000 >= self.fsync_ms:
                        try:
                            st["fh"].flush(); os.fsync(st["fh"].fileno()); st["last_fsync"] = now
                        except Exception:
                            pass
                    # 若已跨分钟且该分片已有内容，及时换名到 ready/
                    if st["minute"] != current_minute and st["count"] > 0:
                        try:
                            self._rotate(sym, st)
                        except Exception as e:
                            logging.getLogger(__name__).warning(f"[JsonlSink] rotate failed (swallowed): {e}")
                        finally:
                            self.state.pop(sym, None)
                # 每分钟健康心跳（避免静默丢包难定位）
                sec = int(now)
                if sec % 60 == 0 and sec != last_heartbeat_sec:
                    last_heartbeat_sec = sec
                    import logging
                    logging.getLogger(__name__).info(f"[JsonlSink] qsize={self.q.qsize()} open={len(self.state)} dropped={self.dropped}")
                continue

            if entry is None:
                break

            symbol = entry.get("symbol", "UNKNOWN")
            ts_ms = entry.get("ts_ms", int(time.time() * 1000))
            minute = self._minute_key(ts_ms)
            st = self.state.get(symbol)

            if (st is None) or (st["minute"] != minute):
                if st is not None:
                    try:
                        self._rotate(symbol, st)
                    except Exception as e:
                        logging.getLogger(__name__).warning(f"[JsonlSink] rotate failed (swallowed): {e}")
                st = self._open_state(symbol, minute)
                self.state[symbol] = st

            line = json.dumps(entry, ensure_ascii=False) + "\n"
            try:
                st["fh"].write(line)
                st["count"] += 1
                if st["count"] % self.batch_n == 0:
                    st["fh"].flush(); os.fsync(st["fh"].fileno()); st["last_fsync"] = time.time()
            except Exception:
                pass

        # drain：关闭并换名所有打开文件
        for sym, st in list(self.state.items()):
            try:
                self._rotate(sym, st)
            except Exception as e:
                logging.getLogger(__name__).warning(f"[JsonlSink] drain rotate failed (swallowed): {e}")
        self.state.clear()

    def close(self):
        self._stop.set()
        try:
            self.q.put(None, timeout=0.2)
        except queue.Full:
            pass
        self.t.join(timeout=2.0)
        if self.t.is_alive():
            logging.getLogger(__name__).warning("[JsonlSink] background thread still alive after join timeout; pending work may be flushed in drain")
        # 二次兜底：线程已停时，确保文件都换名
        for sym, st in list(self.state.items()):
            try:
                self._rotate(sym, st)
            finally:
                self.state.pop(sym, None)

# ---- SQLite（WAL）Sink（可选，适合 Windows/并发读） ----
class SqliteSink(SignalSink):
    def __init__(self, base_dir: Path, batch_n: int = 200, flush_ms: int = 300):
        self.db_path = Path(base_dir) / "signals.db"
        self.batch_n = batch_n
        self.flush_ms = flush_ms
        self.q = queue.Queue(maxsize=20000)
        self.dropped = 0  # 健康度上报：丢弃的消息数
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)
        self._init_db()
        self.t.start()

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    ts_ms INTEGER,
                    symbol TEXT,
                    score REAL, z_ofi REAL, z_cvd REAL,
                    regime TEXT, div_type TEXT,
                    confirm INTEGER, gating INTEGER
                );
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_signals_sym_ts ON signals(symbol, ts_ms);")
            con.commit()
        finally:
            con.close()

    def emit(self, entry: dict):
        try:
            self.q.put(entry, timeout=0.2)
        except queue.Full:
            # 按需计数告警；这里丢弃以保障交易主路径
            self.dropped += 1

    def get_health(self):
        return {"queue_size": self.q.qsize(), "dropped": self.dropped, "open_files": 0}

    def _run(self):
        con = sqlite3.connect(self.db_path, timeout=5.0)
        try:
            buf, last = [], time.time()
            while not self._stop.is_set():
                timeout = max(0.0, self.flush_ms/1000 - (time.time()-last))
                try:
                    item = self.q.get(timeout=timeout)
                except queue.Empty:
                    item = None
                if item is not None:
                    buf.append((
                        item.get("ts_ms"), item.get("symbol"),
                        item.get("score"), item.get("z_ofi"), item.get("z_cvd"),
                        item.get("regime"), item.get("div_type"),
                        int(bool(item.get("confirm"))), int(bool(item.get("gating")))
                    ))
                if buf and (len(buf) >= self.batch_n or (time.time()-last)*1000 >= self.flush_ms or item is None):
                    con.executemany(
                        "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?);", buf
                    )
                    con.commit()
                    buf.clear(); last = time.time()
            if buf:
                con.executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?);", buf)
                con.commit()
        finally:
            con.close()

    def close(self):
        self._stop.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        self.t.join(timeout=2.0)

# ---- 空 Sink（S0 诊断用） ----
class NullSink(SignalSink):
    def emit(self, entry: dict): pass
    def close(self): pass

@dataclass
class SignalConfig:
    """信号配置"""
    # 融合权重
    w_ofi: float = 0.6
    w_cvd: float = 0.4
    
    # 裁剪范围
    score_clip_min: float = -5.0
    score_clip_max: float = 5.0
    
    # EMA平滑参数
    ema_alpha: float = 0.2
    
    # 背离检测参数
    swing_L: int = 12
    z_hi: float = 2.0
    z_mid: float = 1.0
    
    # 护栏参数
    spread_bps_cap: float = 15.0
    missing_msgs_rate_cap: float = 0.001
    resync_cooldown_sec: int = 120
    reconnect_cooldown_sec: int = 180
    cooldown_after_exit_sec: int = 60

@dataclass
class SignalData:
    """信号数据"""
    ts_ms: int
    symbol: str
    score: float
    z_ofi: Optional[float]
    z_cvd: Optional[float]
    regime: str
    div_type: Optional[str] = None
    confirm: bool = False
    gating: bool = False

class CoreAlgorithm:
    """核心算法类 - 直接调用成熟组件"""
    
    def __init__(self, symbol: str, config: SignalConfig = None, config_loader=None):
        self.symbol = symbol
        self.config = config or SignalConfig()
        self.config_loader = config_loader
        self.logger = logging.getLogger(__name__)
        
        # 调试开关 - 控制详细日志输出
        self.debug = os.getenv("V13_DEBUG", "false").lower() == "true"
        
        # 加载统一配置（支持严格运行时模式）
        if config_loader is None:
            # 默认使用严格运行时模式
            use_strict_mode = os.getenv('V13_STRICT_RUNTIME', 'true').lower() in ('true', '1', 'yes')
            compat_global = os.getenv('V13_COMPAT_GLOBAL_CONFIG', 'false').lower() in ('true', '1', 'yes')
            
            if use_strict_mode and not compat_global:
                # 严格模式：从运行时包加载
                # TODO: 实现严格模式配置加载
                try:
                    # from v13conf.strict_mode import load_strict_runtime_config
                    # runtime_pack_path = os.getenv(
                    #     'V13_CORE_ALGO_RUNTIME_PACK',
                    #     str(Path(__file__).parent.parent / 'dist' / 'config' / 'core_algo.runtime.current.yaml')
                    # )
                    # self.system_config = load_strict_runtime_config(runtime_pack_path, compat_global_config=False, verify_scenarios_snapshot=True)
                    # self.logger.info(f"[严格模式] 从运行时包加载配置: {runtime_pack_path}")
                    self.logger.warning("[配置加载] 严格模式暂未实现，使用空配置")
                    self.system_config = {}
                except Exception as e:
                    self.logger.warning(f"[配置加载] 严格模式加载失败，降级到兼容模式: {e}")
                    self.system_config = {}
            else:
                # 兼容模式：从全局配置加载
                # TODO: 实现 load_config
                # self.system_config = load_config()
                self.system_config = {}
        elif callable(config_loader):
            self.system_config = config_loader()
        else:
            self.system_config = config_loader  # 已是 dict-like
        
        # 直接初始化成熟组件
        self._init_components()
        
        # 状态变量 - 使用单调时钟避免系统时间跳变
        base = time.monotonic() - 1e9
        self.last_resync_time = base
        self.last_reconnect_time = base
        self.last_exit_time = base
        
        # 护栏状态
        self.guard_active = False
        self.guard_reason = ""
        
        # 去重逻辑
        self._last_signal_ts = None
        
        # 统计信息
        self.stats = {
            'total_updates': 0,
            'valid_signals': 0,
            'suppressed_signals': 0,
            'regime_changes': 0,
            'ofi_updates': 0,
            'cvd_updates': 0,
            'fusion_updates': 0,
            'divergence_events': 0
        }
        
        # 闸门原因统计 - 用于诊断信号被阻止的原因
        self.gate_reason_stats = {
            'warmup_guard': 0,
            'lag_exceeded': 0,
            'consistency_low': 0,
            'divergence_blocked': 0,
            'scenario_blocked': 0,
            'spread_too_high': 0,
            'missing_msgs_rate': 0,
            'resync_cooldown': 0,
            'reconnect_cooldown': 0,
            'component_warmup': 0,
            'weak_signal_throttle': 0,
            'low_consistency': 0,
            'reverse_cooldown': 0,
            'insufficient_hold_time': 0,
            'exit_cooldown': 0,
            'passed': 0,
            'lag_shadow': 0  # 影子模式：记录但不过滤
        }
        
        # Lag监控统计（滑窗，最多保留5000个样本）
        self._lag_window = deque(maxlen=5000)
        self._last_lag_stats_dump = time.time()
        
        
        # default regime to ensure fusion has a value before first determination
        self._current_regime = 'normal'
# 反向开仓防抖状态
        self._last_trade_time = {}  # symbol -> timestamp
        self._last_trade_direction = {}  # symbol -> direction
        self._consecutive_same_direction = {}  # symbol -> count
        
        # 从配置加载场景参数
        scenario_params = self.system_config.get('scenario_parameters', {})
        self._scenario_hold_times = {}
        self._scenario_consistency_thresholds = {}
        
        for scenario, params in scenario_params.items():
            self._scenario_hold_times[scenario] = params.get('min_hold_time_sec', 60)
            self._scenario_consistency_thresholds[scenario] = params.get('consistency_threshold', 0.6)
        
        # 初始化异步写入器（延迟初始化）
        self._async_writer = None
        self._output_dir = Path(os.getenv("V13_OUTPUT_DIR", "./runtime"))
        
        # 初始化SafeJsonlWriter
        self._safe_writer = SafeJsonlWriter(
            Path(os.getenv("V13_OUTPUT_DIR", "./runtime"))
        )
        
        # 可插拔Sink系统初始化
        base_dir = Path(os.getenv("V13_OUTPUT_DIR", "./runtime"))
        sink_type = os.getenv("V13_SINK", "jsonl").lower()
        if sink_type == "sqlite":
            self._sink = SqliteSink(base_dir)
        elif sink_type == "null":
            self._sink = NullSink()
        else:
            self._sink = JsonlSink(base_dir)

        # Replay mode: disable hard lag gating during offline playback (env driven)
        self.replay_mode = os.getenv("V13_REPLAY_MODE", "0").lower() in ("1", "true", "yes")

        # 优雅关闭（进程退出时 flush/close）
        atexit.register(lambda: getattr(self, "_sink", None) and self._sink.close())

        # BOOT 快照：打印回放与滞后护栏配置，便于自检
        try:
            lag_cap, lag_mode, outlier = self._get_lag_guard_cfg()
            self.logger.info(
                f"[BOOT] replay_mode={self.replay_mode} lag_cap={lag_cap}s lag_mode={lag_mode} outlier_drop={outlier}s"
            )
        except Exception:
            pass
    
    def _init_components(self):
        """初始化成熟组件 - 使用统一配置系统（优先库式注入，向后兼容旧路径）"""
        try:
            # 优先使用新的components子树（严格运行时模式）
            components_cfg = self.system_config.get('components', {})
            
            # 检查是否有新格式的配置（库式注入）
            has_new_format = components_cfg and any(components_cfg.values())
            
            if has_new_format:
                # 新格式：使用库式配置注入
                self.logger.info(f"[库式注入] 使用components子树初始化组件")
                
                # 1. OFI计算器（库式调用）
                ofi_cfg = components_cfg.get('ofi', {})
                self.ofi_calc = RealOFICalculator(
                    symbol=self.symbol,
                    runtime_cfg={'ofi': ofi_cfg}  # 库式调用
                )
                
                # 2. CVD计算器（库式调用）
                cvd_cfg = components_cfg.get('cvd', {})
                self.cvd_calc = RealCVDCalculator(
                    symbol=self.symbol,
                    runtime_cfg={'cvd': cvd_cfg}  # 库式调用
                )
                
                # 3. FUSION（库式调用）
                fusion_cfg = components_cfg.get('fusion', {})
                self.fusion = OFI_CVD_Fusion(
                    runtime_cfg={'fusion': fusion_cfg}  # 库式调用
                )
                
                # 4. DIVERGENCE（库式调用）
                divergence_cfg = components_cfg.get('divergence', {})
                self.divergence = DivergenceDetector(
                    runtime_cfg={'divergence': divergence_cfg}  # 库式调用
                )
                
                # 5. STRATEGY MODE（库式调用）
                strategy_cfg = components_cfg.get('strategy', {})
                self.strategy_manager = StrategyModeManager(
                    runtime_cfg={'strategy': strategy_cfg}  # 库式调用
                )
                
                self.logger.info(f"Core algorithm components initialized for {self.symbol} with runtime config (library-style)")
                return  # 新格式分支结束，不再执行旧格式逻辑
            else:
                # 旧格式：向后兼容逻辑（弃用警告）
                import warnings
                warnings.warn(
                    "使用旧配置路径（fusion_metrics, divergence_detection）已弃用。"
                    "请迁移到components子树格式。此路径将在下一大版本中移除。",
                    DeprecationWarning,
                    stacklevel=2
                )
                self.logger.warning("[弃用警告] 使用旧配置路径，建议迁移到components子树格式")
                
                fusion_config = self.system_config.get('fusion_metrics', {})
                divergence_config = self.system_config.get('divergence_detection', {})
                strategy_config = self.system_config.get('strategy', {})
                
                # 1. OFI计算器 - 使用优化后的参数
                ofi_config = OFIConfig(
                    levels=5,
                    z_window=150,  # 使用优化后的窗口大小
                    ema_alpha=self.config.ema_alpha
                )
                self.ofi_calc = RealOFICalculator(self.symbol, ofi_config, self.config_loader)
                
                # 2. CVD计算器 - 使用优化后的参数
                cvd_config = CVDConfig(
                    z_window=150,  # 使用优化后的窗口大小
                    ema_alpha=self.config.ema_alpha,
                    use_tick_rule=True,
                    warmup_min=3  # 使用优化后的暖启动阈值
                )
                self.cvd_calc = RealCVDCalculator(self.symbol, cvd_config, self.config_loader)
                
                # 3. 融合指标 - 使用统一配置
                fusion_weights = fusion_config.get('weights', {})
                fusion_thresholds = fusion_config.get('thresholds', {})
                fusion_config_obj = OFICVDFusionConfig(
                    w_ofi=fusion_weights.get('w_ofi', self.config.w_ofi),
                    w_cvd=fusion_weights.get('w_cvd', self.config.w_cvd),
                    fuse_buy=fusion_thresholds.get('fuse_buy', 1.0),
                    fuse_strong_buy=fusion_thresholds.get('fuse_strong_buy', 1.8),
                    fuse_sell=fusion_thresholds.get('fuse_sell', -1.0),
                    fuse_strong_sell=fusion_thresholds.get('fuse_strong_sell', -1.8)
                )
                self.fusion = OFI_CVD_Fusion(fusion_config_obj, self.config_loader)
                
                # 4. 背离检测器 - 使用统一配置
                divergence_default = divergence_config.get('default', {})
                divergence_config_obj = DivergenceConfig(
                    swing_L=divergence_default.get('swing_L', self.config.swing_L),
                    z_hi=divergence_default.get('z_hi', self.config.z_hi),
                    z_mid=divergence_default.get('z_mid', self.config.z_mid),
                    min_separation=divergence_default.get('min_separation', 6),
                    cooldown_secs=divergence_default.get('cooldown_secs', 1.0)
                )
                self.divergence = DivergenceDetector(divergence_config_obj, self.config_loader)
                
                # 5. 策略模式管理器 - 统一传入带 'strategy' 根的结构
                raw_strategy = strategy_config
                if not raw_strategy:
                    strategy_root = {'strategy': {
                        'mode': 'auto',
                        'hysteresis': {
                            'window_secs': 60,
                            'min_active_windows': 3,
                            'min_quiet_windows': 6
                        },
                        'triggers': {
                            'schedule': {
                                'enabled': True,
                                'timezone': 'Asia/Tokyo',
                                'calendar': 'CRYPTO',
                                'enabled_weekdays': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                                'holidays': [],
                                'active_windows': [],
                                'wrap_midnight': True
                            },
                            'market': {
                                'enabled': True,
                                'window_secs': 60,
                                'min_trades_per_min': 100.0,
                                'min_quote_updates_per_sec': 100,
                                'max_spread_bps': self.config.spread_bps_cap,
                                'min_volatility_bps': 0.02 * 10000,
                                'min_volume_usd': 1000000,
                                'use_median': True,
                                'winsorize_percentile': 95
                            }
                        }
                    }}  # 默认
                else:
                    strategy_root = {'strategy': raw_strategy}  # 已有配置时也包一层根
                self.strategy_manager = StrategyModeManager(strategy_root, self.config_loader)
                self.logger.info(f"Core algorithm components initialized for {self.symbol} with unified config (legacy mode)")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize components for {self.symbol}: {e}")
            raise
        
    def update_ofi(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]], 
                   event_time_ms: Optional[int] = None) -> Dict[str, Any]:
        """更新OFI计算器"""
        try:
            # 数据格式检查
            if not bids or not asks:
                self.logger.warning("OFI update: empty bids/asks data")
                return {}
            
            # 检查数据格式：[(price, size)...] 的浮点数组
            for i, (price, size) in enumerate(bids[:3]):  # 只检查前3个
                if not isinstance(price, (int, float)) or not isinstance(size, (int, float)):
                    self.logger.warning(f"OFI update: invalid bid format at index {i}: price={price}, size={size}")
                    return {}
            
            for i, (price, size) in enumerate(asks[:3]):  # 只检查前3个
                if not isinstance(price, (int, float)) or not isinstance(size, (int, float)):
                    self.logger.warning(f"OFI update: invalid ask format at index {i}: price={price}, size={size}")
                    return {}
            
            # 时间戳检查
            current_time = int(time.time() * 1000)
            if event_time_ms is None:
                event_time_ms = current_time
            elif abs(event_time_ms - current_time) > 5000:  # 5秒差异报警
                self.logger.warning(f"OFI update: timestamp mismatch - event={event_time_ms}, current={current_time}")
            
            result = self.ofi_calc.update_with_snapshot(bids, asks, event_time_ms)
            self.stats['ofi_updates'] += 1
            
            # 心跳检查：每分钟打印更新频率
            current_time_sec = time.time()
            if not hasattr(self, '_last_ofi_heartbeat'):
                self._last_ofi_heartbeat = current_time_sec
                self._ofi_count_since_heartbeat = 0
            
            self._ofi_count_since_heartbeat += 1
            
            # 每分钟打印一次OFI更新频率（并记录近5分钟中位数）
            if current_time_sec - self._last_ofi_heartbeat >= 60:
                ofi_updates_per_min = self._ofi_count_since_heartbeat
                self._ofi_hist = getattr(self, "_ofi_hist", [])
                self._ofi_hist.append(ofi_updates_per_min)
                if len(self._ofi_hist) > 5: self._ofi_hist.pop(0)
                median5 = sorted(self._ofi_hist)[len(self._ofi_hist)//2]
                self.logger.info(f"OFI heartbeat: {ofi_updates_per_min}/min (5-min median={median5}/min)")
                
                # 连续低频提示（不假定目标阈值）
                if ofi_updates_per_min == 0:
                    self.logger.warning("OFI low frequency: 0 updates in the last minute")
                
                self._last_ofi_heartbeat = current_time_sec
                self._ofi_count_since_heartbeat = 0
            
            # OFI质量诊断：检查数据质量指标
            meta = result.get('meta', {})
            bad_points = meta.get('bad_points', 0)
            std_zero = meta.get('std_zero', False)
            
            # 数据质量报警
            if bad_points > 10:
                self.logger.warning(f"OFI data quality: {bad_points} bad points detected")
            if std_zero:
                self.logger.warning("OFI data quality: std_zero detected - insufficient price variation")
            
            return result
            
        except Exception as e:
            self.logger.error(f"OFI update failed: {e}")
            return {}
    
    def update_cvd(self, price: Optional[float] = None, qty: float = 0.0, 
                  is_buy: Optional[bool] = None, event_time_ms: Optional[int] = None) -> Dict[str, Any]:
        """更新CVD计算器"""
        try:
            result = self.cvd_calc.update_with_trade(
                price=price, qty=qty, is_buy=is_buy, event_time_ms=event_time_ms
            )
            self.stats['cvd_updates'] += 1
            return result
        except Exception as e:
            self.logger.error(f"CVD calculation failed: {e}")
            return {"z_cvd": None, "cvd": 0.0, "meta": {"warmup": True}}
    
    def update_fusion(self, z_ofi: float, z_cvd: float, ts: float, 
                     price: Optional[float] = None, lag_sec: float = 0.0) -> Dict[str, Any]:
        """更新融合指标"""
        try:
            # 传递当前regime给融合指标
            # 注意：当前使用私有属性 _current_regime（技术债预防）
            # 若后续融合器接口更新，建议添加公开方法 set_regime(regime: str) 以避免私有属性耦合
            if hasattr(self, '_current_regime'):
                self.fusion._current_regime = self._current_regime
            result = self.fusion.update(z_ofi, z_cvd, ts, price, lag_sec)
            self.stats['fusion_updates'] += 1
            return result
        except Exception as e:
            self.logger.error(f"Fusion calculation failed: {e}")
            return {"fusion_score": 0.0, "signal": "neutral", "consistency": 0.0}
    
    def update_divergence(self, ts: float, price: float, z_ofi: float, z_cvd: float,
                         fusion_score: Optional[float] = None, consistency: Optional[float] = None,
                         warmup: bool = False, lag_sec: float = 0.0) -> Optional[Dict[str, Any]]:
        """更新背离检测器"""
        try:
            result = self.divergence.update(ts, price, z_ofi, z_cvd, fusion_score, 
                                           consistency, warmup, lag_sec)
            if result:
                self.stats['divergence_events'] += 1
            return result
        except Exception as e:
            self.logger.error(f"Divergence detection failed: {e}")
            return None
    
    def determine_regime(self, trade_rate: float, realized_vol: float, 
                        spread_bps: float = 5.0, volume_usd: float = 1000000.0) -> str:
        """确定市场状态 - 直接使用策略模式管理器"""
        try:
            # 创建市场活跃度数据
            activity = MarketActivity()
            
            # 场景切换诊断：每30秒打印一次状态
            current_time = time.time()
            if not hasattr(self, '_last_regime_heartbeat'):
                self._last_regime_heartbeat = current_time
                self._last_regime = None
            
            # 每30秒打印一次场景切换状态
            if current_time - self._last_regime_heartbeat >= 30:
                self.logger.info(f"Scenario diagnostics: trade_rate={trade_rate:.2f}, vol={realized_vol:.4f}, spread={spread_bps:.1f}bps, volume=${volume_usd/1000:.0f}k")
                self.logger.info(f"Strategy mode enabled: {getattr(self.strategy_manager, 'dynamic_mode_enabled', False)}")
                self.logger.info(f"Current mode: {getattr(self.strategy_manager, 'current_mode', 'unknown')}")
                self._last_regime_heartbeat = current_time
            activity.trades_per_min = trade_rate
            # 可配置的 quote_updates_per_sec（保持默认 100，但允许用配置覆盖）
            qos_cfg = self.system_config.get('components', {}).get('strategy', {}).get('triggers', {}).get('market', {})
            activity.quote_updates_per_sec = float(qos_cfg.get('min_quote_updates_per_sec', 100.0))
            activity.spread_bps = spread_bps
            activity.volatility_bps = realized_vol * 10000  # 转换为bps
            activity.volume_usd = volume_usd
            
            # 使用策略模式管理器确定状态
            if self.debug:
                self.logger.debug(f"[STRATEGY_MGR] Manager initialized: {self.strategy_manager is not None}")
                self.logger.debug(f"[STRATEGY_MGR] Dynamic mode enabled: {getattr(self.strategy_manager, 'dynamic_mode_enabled', False)}")
                self.logger.debug(f"[STRATEGY_MGR] Activity: trades={activity.trades_per_min}, quotes={activity.quote_updates_per_sec}, vol={activity.volatility_bps}")
            try:
                mode, trigger_reason, trigger_snapshot = self.strategy_manager.decide_mode(activity)
                regime = mode.value if hasattr(mode, 'value') else str(mode)
                if self.debug:
                    self.logger.debug(f"[STRATEGY_MGR] Mode decision: {regime}, trigger={trigger_reason}")
            except Exception as e:
                if self.debug:
                    self.logger.debug(f"[STRATEGY_MGR] Manager failed: {e}, using fallback")
                self.logger.warning(f"Strategy mode manager failed: {e}, using fallback")
                # 默认兜底：根据市场活跃度选择normal或quiet
                if trade_rate > 20 and realized_vol > 0.005:
                    regime = "normal"
                else:
                    regime = "quiet"
                if self.debug:
                    self.logger.debug(f"[STRATEGY_MGR] Fallback regime: {regime}")
            
            # 检测场景切换
            if self._last_regime is not None and self._last_regime != regime:
                self.logger.info(f"Scenario switch: {self._last_regime} -> {regime}")
                self.stats['regime_changes'] += 1
            
            self._last_regime = regime
            return regime
                
        except Exception as e:
            self.logger.error(f"Strategy mode manager failed: {e}")
            # 回退到简化逻辑
            if trade_rate > 100 and realized_vol > 0.02:
                return "active"
            elif trade_rate > 10 and realized_vol > 0.005:
                return "normal"
            else:
                return "quiet"
    
    def check_guards(self, spread_bps: float, missing_msgs_rate: float, 
                    resync_detected: bool, reconnect_detected: bool) -> Tuple[bool, str]:
        """检查护栏条件"""
        current_time = time.monotonic()
        
        # 检查价差
        if spread_bps > self.config.spread_bps_cap:
            self.gate_reason_stats['spread_too_high'] += 1
            return True, f"spread_too_high_{spread_bps:.1f}bps"
        
        # 检查缺失消息率
        if missing_msgs_rate > self.config.missing_msgs_rate_cap:
            self.gate_reason_stats['missing_msgs_rate'] += 1
            return True, f"missing_msgs_rate_{missing_msgs_rate:.4f}"
        
        # 检查重同步冷却期
        if resync_detected:
            self.last_resync_time = current_time
            self.gate_reason_stats['resync_cooldown'] += 1
            return True, "resync_cooldown"
        
        if current_time - self.last_resync_time < self.config.resync_cooldown_sec:
            self.gate_reason_stats['resync_cooldown'] += 1
            return True, "resync_cooldown"
        
        # 检查重连冷却期
        if reconnect_detected:
            self.last_reconnect_time = current_time
            self.gate_reason_stats['reconnect_cooldown'] += 1
            return True, "reconnect_cooldown"
        
        if current_time - self.last_reconnect_time < self.config.reconnect_cooldown_sec:
            self.gate_reason_stats['reconnect_cooldown'] += 1
            return True, "reconnect_cooldown"
        
        # 检查退出后冷却期
        if current_time - self.last_exit_time < self.config.cooldown_after_exit_sec:
            self.gate_reason_stats['exit_cooldown'] += 1
            return True, "exit_cooldown"
        
        return False, ""
    
    def check_reverse_prevention(self, symbol: str, fusion_score: float, scenario: str = None, update_state: bool = False) -> Tuple[bool, str]:
        """
        检查反向开仓防抖条件（无副作用版本：预判阶段不改内部状态）
        
        Args:
            symbol: 交易对符号
            fusion_score: 融合分数
            scenario: 场景标签 (A_H/A_L/Q_H/Q_L)
            update_state: 是否更新状态（仅在确认后设为True）
            
        Returns:
            (是否被阻止, 阻止原因)
        """
        current_time = time.monotonic()
        direction = 1 if fusion_score > 0 else -1
        
        # 读取当前状态（不修改）
        last_dir = self._last_trade_direction.get(symbol)
        consec = self._consecutive_same_direction.get(symbol, 0)
        
        blocked, reason = False, ""
        # 检查是否在最小持仓时间内
        if symbol in self._last_trade_time:
            time_since_last = current_time - self._last_trade_time[symbol]
            min_hold_time = self._scenario_hold_times.get(scenario, 60)  # 默认60秒
            
            if time_since_last < min_hold_time:
                self.gate_reason_stats['insufficient_hold_time'] += 1
                return True, f"insufficient_hold_time_{min_hold_time}s"
        
        # 仅用局部变量"试算"下一步计数（不修改内部状态）
        if last_dir is None:
            consec_next = 1
        elif last_dir == direction:
            consec_next = consec + 1
        else:
            # 反向信号，需要连续N=3个tick确认
            if consec < 3:
                self.gate_reason_stats['reverse_cooldown'] += 1
                blocked, reason = True, "reverse_cooldown_insufficient_ticks"
            consec_next = 1
        
        # 只有确认通过时才**落**状态（避免预判阶段污染计数器）
        if update_state and not blocked:
            self._last_trade_time[symbol] = current_time
            self._last_trade_direction[symbol] = direction
            self._consecutive_same_direction[symbol] = consec_next
        
        return blocked, reason
    
    def get_gate_reason_stats(self) -> Dict[str, int]:
        """获取闸门原因统计"""
        return self.gate_reason_stats.copy()
    
    def _get_fusion_cfg(self) -> Dict[str, Any]:
        """
        统一读取融合配置，兼容新旧格式。
        
        返回:
            Dict: 融合配置字典（新格式：components.fusion.*，旧格式：fusion_metrics）
        """
        comps = self.system_config.get('components', {})
        if isinstance(comps, dict):
            fx = comps.get('fusion', {})
            if isinstance(fx, dict) and fx:
                return fx  # 新格式：components.fusion.*
        return self.system_config.get('fusion_metrics', {})  # 旧格式兜底
    
    def _get_lag_guard_cfg(self) -> Tuple[float, str, float]:
        """
        统一读取lag护栏配置，避免多个地方配置不一致。
        
        返回:
            Tuple[lag_cap, lag_check_mode, outlier_drop_sec]:
            - lag_cap: 最大事件延迟（秒）
            - lag_check_mode: 检查模式 ('strict'/'shadow')
            - outlier_drop_sec: 极端延迟阈值（秒）
        """
        guards = self.system_config.get('components', {}).get('core_algo', {}).get('guards', {})
        if isinstance(guards, dict) and guards:
            return (
                float(guards.get('max_event_lag_sec', 3.0)),
                str(guards.get('lag_check_mode', 'strict')).lower(),
                float(guards.get('outlier_drop_sec', 600.0)),
            )
        # 兼容旧配置格式（直接在顶层）
        return (
            float(self.system_config.get('max_event_lag_sec', 3.0)),
            str(self.system_config.get('lag_check_mode', 'strict')).lower(),
            float(self.system_config.get('outlier_drop_sec', 600.0)),
        )
    
    def _dump_lag_stats(self) -> None:
        """输出lag统计信息（每30秒调用一次）"""
        if not self._lag_window:
            return
        import statistics
        
        def _q(arr, q: float) -> float:
            """安全的百分位计算，处理边界情况（避免负索引或越界）"""
            if not arr:
                return 0.0
            n = len(arr)
            idx = max(0, min(n - 1, int(q * n) - 1))
            return float(arr[idx])
        
        arr = list(self._lag_window)
        arr_sorted = sorted(arr)
        n = len(arr)
        p50 = statistics.median(arr) if n > 0 else 0.0
        p95 = _q(arr_sorted, 0.95)
        p99 = _q(arr_sorted, 0.99)
        max_lag = max(arr) if arr else 0.0
        
        lag_cap, _, _ = self._get_lag_guard_cfg()
        self.logger.info(
            f"[LAG_STATS] n={n} p50={p50:.3f}s p95={p95:.3f}s p99={p99:.3f}s max={max_lag:.3f}s "
            f"cap={lag_cap:.1f}s @ {time.strftime('%H:%M:%S')}"
        )
    
    def _log_gate_stats_to_jsonl(self):
        """记录闸门统计到JSONL文件"""
        try:
            import json
            from datetime import datetime
            from pathlib import Path
            
            # 统一口径：导出前做一次 alias 合并
            gr = self.gate_reason_stats.copy()
            if 'consistency_low' in gr:
                gr['low_consistency'] = gr.get('low_consistency', 0) + gr.pop('consistency_low')
            
            # 创建统计记录
            stats_record = {
                "timestamp": datetime.now().isoformat(),
                "type": "gate_stats_realtime",
                "symbol": self.symbol,
                "total_signals": self._gate_stats_counter,
                "gate_reasons": gr,
                "current_regime": getattr(self, '_current_regime', 'unknown'),
                "guard_active": self.guard_active,
                "guard_reason": self.guard_reason
            }
            # 追加运行态关键信息，便于诊断
            try:
                stats_record.update({
                    "replay_mode": bool(getattr(self, "replay_mode", False)),
                    "lag_guard": self._get_lag_guard_cfg()[1]
                })
            except Exception:
                pass
            
            # 写入JSONL文件（使用V13_OUTPUT_DIR环境变量）
            output_dir = os.getenv("V13_OUTPUT_DIR", "./runtime")
            log_file = Path(output_dir) / "artifacts" / "gate_stats.jsonl"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(stats_record, ensure_ascii=False) + '\n')
                
        except Exception as e:
            self.logger.warning(f"闸门统计记录失败: {e}")
    
    def check_gate_reason_thresholds(self) -> List[str]:
        """
        检查闸门原因阈值，返回建议调整的参数
        
        Returns:
            List[str]: 建议调整的参数列表
        """
        suggestions = []
        total_signals = self.stats['total_updates']
        suppressed_signals = sum(self.gate_reason_stats.values()) - self.gate_reason_stats.get('passed', 0)
        
        if total_signals == 0:
            return suggestions
        
        # 检查各原因占比（支持两种口径）
        for reason, count in self.gate_reason_stats.items():
            if reason == 'passed':
                continue
            percentage_total = (count / total_signals) * 100
            percentage_suppressed = (count / suppressed_signals) * 100 if suppressed_signals > 0 else 0
            if percentage_total > 60 or percentage_suppressed > 60:  # 超过60%的信号被同一原因阻止
                if reason == 'warmup_guard':
                    suggestions.append("降低min_warmup_samples参数")
                elif reason == 'lag_exceeded':
                    suggestions.append("增加max_event_lag_sec参数")
                elif reason in ('consistency_low', 'low_consistency'):
                    suggestions.append("降低min_consistency参数")
                elif reason == 'spread_too_high':
                    suggestions.append("增加spread_bps_cap参数")
                elif reason == 'component_warmup':
                    suggestions.append("检查OFI/CVD计算器warmup状态")
        
        return suggestions
    
    def process_signal(self, ts_ms: int, symbol: str, z_ofi: float, z_cvd: float,
                      price: float, trade_rate: float, realized_vol: float, 
                      spread_bps: float, missing_msgs_rate: float, 
                      resync_detected: bool = False, reconnect_detected: bool = False) -> Optional[SignalData]:
        """处理信号 - 直接使用成熟组件"""
        
        # === P0调用链日志 ===
        if self.debug:
            self.logger.debug(f"[CALL_CHAIN] process_signal called - ts={ts_ms}, symbol={symbol}")
            self.logger.debug(f"[CALL_CHAIN] OFI data: z_ofi={z_ofi}, CVD data: z_cvd={z_cvd}")
            self.logger.debug(f"[CALL_CHAIN] Market data: price={price}, trade_rate={trade_rate}, vol={realized_vol}")
        
        # 去重逻辑：丢弃同时间戳/配置窗口内重复信号（配置化去重窗口）
        guards = self.system_config.get('components', {}).get('core_algo', {}).get('guards', {})
        dedupe_ms = int(guards.get('dedupe_ms', 250)) if isinstance(guards, dict) else 250
        if self._last_signal_ts is not None and abs(ts_ms - self._last_signal_ts) < dedupe_ms:
            if self.debug:
                self.logger.debug(f"[CALL_CHAIN] Signal deduplicated - too close to last signal (window={dedupe_ms}ms)")
            return None  # 丢弃重复信号
        self._last_signal_ts = ts_ms
        
        self.stats['total_updates'] += 1
        
        # 模式快照记录（每30秒）
        ts_sec_for_snapshot = normalize_ts_to_seconds(ts_ms)
        if not hasattr(self, '_last_mode_snapshot'):
            self._last_mode_snapshot = ts_sec_for_snapshot
        if ts_sec_for_snapshot - self._last_mode_snapshot >= 30:
            # 读取配置的 qps baseline（语义化字段名，避免与观测值混淆）
            qos_cfg = self.system_config.get('components', {}).get('strategy', {}).get('triggers', {}).get('market', {})
            qps_baseline = float(qos_cfg.get('min_quote_updates_per_sec', 100.0))
            mode_snapshot = {
                'timestamp': ts_sec_for_snapshot,
                'mode': getattr(self, '_current_regime', 'unknown'),
                'trades_per_min': trade_rate,
                'qps_baseline': qps_baseline,  # 语义化：基线配置值（非观测值）
                'spread_bps': spread_bps,
                'volatility_bps': realized_vol * 10000,
                'volume_usd': 0.0,  # 默认值
                'z_ofi': z_ofi,
                'z_cvd': z_cvd
            }
            if self.debug:
                self.logger.debug(f"[MODE_SNAPSHOT] {mode_snapshot}")
            self._last_mode_snapshot = ts_sec_for_snapshot
        
        # 1. 确定市场状态（提前确定，用于分场景阈值）
        regime = self.determine_regime(trade_rate, realized_vol, spread_bps)
        self._current_regime = regime
        self._current_scenario = getattr(self, '_current_scenario', None) or regime
        
        # 2.0 提前计算lag（用于透传给融合器，支持滞后补偿/降权）
        ts_sec = normalize_ts_to_seconds(ts_ms)
        if getattr(self, "replay_mode", False):
            event_lag_sec = 0.0
        else:
            event_lag_sec = max(0.0, time.time() - ts_sec)
            # 离线兜底：历史数据远早于墙钟，直接视为shadow而非exceeded
            try:
                if event_lag_sec > 60.0:  # 兜底阈值，可按需配置
                    self.gate_reason_stats['lag_shadow'] += 1
                    event_lag_sec = 0.0
            except Exception:
                pass
        
        # 2. 使用融合指标计算融合分数（传递regime信息和lag信息）
        if self.debug:
            self.logger.debug(f"[CALL_CHAIN] Calling fusion.update() - z_ofi={z_ofi}, z_cvd={z_cvd}, ts={ts_sec}, lag={event_lag_sec:.3f}s")
        try:
            fusion_result = self.update_fusion(z_ofi, z_cvd, ts_sec, price, lag_sec=event_lag_sec)
            fusion_score = fusion_result.get('fusion_score', 0.0)
            fusion_signal = fusion_result.get('signal', 'neutral')
            consistency = fusion_result.get('consistency', 0.0)
            reason_codes = fusion_result.get('reason_codes', [])
            if self.debug:
                self.logger.debug(f"[CALL_CHAIN] Fusion result: score={fusion_score}, signal={fusion_signal}, consistency={consistency}")
                self.logger.debug(f"[CALL_CHAIN] Fusion reason_codes: {reason_codes}")
        except Exception as e:
            if self.debug:
                self.logger.debug(f"[CALL_CHAIN] Fusion update failed: {e}")
                self.logger.debug(f"[CALL_CHAIN] Input snapshot: z_ofi={z_ofi}, z_cvd={z_cvd}, ts={ts_sec}, price={price}")
            self.logger.error(f"Fusion update failed: {e}, input: z_ofi={z_ofi}, z_cvd={z_cvd}, ts={ts_sec}, price={price}")
            fusion_result = {'fusion_score': 0.0, 'signal': 'neutral', 'consistency': 0.0}
            fusion_score = 0.0
            fusion_signal = 'neutral'
            consistency = 0.0
            reason_codes = []
        
        # 2.1 使用背离检测器检测背离
        divergence_event = self.update_divergence(
            ts_sec, price, z_ofi, z_cvd, fusion_score, consistency, lag_sec=event_lag_sec
        )
        div_type = divergence_event.get('type') if divergence_event else None
        self._last_divergence_type = div_type  # 确保背离加成可用
        
        # 3. Regime 已在步骤1确定，不再重复调用
        
        # 4. 检查护栏
        guard_active, guard_reason = self.check_guards(
            spread_bps, missing_msgs_rate, resync_detected, reconnect_detected
        )
        
        # 4.0 事件滞后护栏（lag已在步骤2.0计算，这里仅用于记录和检查）
        # 记录lag到监控窗口
        self._lag_window.append(event_lag_sec)
        
        # 每30秒输出一次lag统计
        now = time.time()
        if now - self._last_lag_stats_dump >= 30.0:
            self._dump_lag_stats()
            self._last_lag_stats_dump = now
        
        # 获取配置（统一方法，避免不一致）
        lag_cap, lag_check_mode, outlier_drop_sec = self._get_lag_guard_cfg()
        
        # 检查lag（支持shadow模式与回放模式）
        if not guard_active and event_lag_sec > lag_cap:
            if getattr(self, "replay_mode", False):
                # 回放模式：仅记录，不拦截
                self.gate_reason_stats['lag_shadow'] += 1
            elif lag_check_mode == "shadow" and event_lag_sec < outlier_drop_sec:
                # 影子模式：记录但不过滤
                self.gate_reason_stats['lag_shadow'] += 1
            else:
                # 严格模式或极端lag：拦截
                self.gate_reason_stats['lag_exceeded'] += 1
                guard_active, guard_reason = True, f"lag_exceeded_{event_lag_sec:.2f}s"
        
        # 4.1. 反向防抖检查将在确认逻辑后执行
        
        # 4.5. Warmup护栏检查 - 严格区分"未就绪(None)"与"就绪但弱(数值)"
        warmup_active = False
        ofi_warmup, cvd_warmup = False, False
        if z_ofi is None or z_cvd is None:
            warmup_active = True
            if not guard_active:
                guard_reason = "warmup_guard"
                guard_active = True
                self.gate_reason_stats['warmup_guard'] += 1
            if self.debug:
                self.logger.debug(f"[WARMUP_GUARD] z_ofi={z_ofi}, z_cvd={z_cvd}, guard_reason={guard_reason}")
        else:
            # 检查OFI/CVD的warmup状态
            ofi_warmup = getattr(self.ofi_calc, '_is_warmup', False)
            cvd_warmup = getattr(self.cvd_calc, '_is_warmup', False)
            if ofi_warmup or cvd_warmup:
                warmup_active = True
                if not guard_active:
                    guard_reason = "component_warmup"
                    guard_active = True
                    self.gate_reason_stats['component_warmup'] += 1
                if self.debug:
                    self.logger.debug(f"[COMPONENT_WARMUP] ofi_warmup={ofi_warmup}, cvd_warmup={cvd_warmup}, guard_reason={guard_reason}")
        
        # 5. 确认信号 - 质量优化版（分场景自适应阈值）
        # 从配置获取分场景阈值
        current_regime = getattr(self, '_current_regime', 'normal')
        
        # === 融合→闸门关键字段日志 ===
        if self.debug:
            self.logger.debug(f"[FUSION_GATE] Input: z_ofi={z_ofi}, z_cvd={z_cvd}, fusion_score={fusion_score}, consistency={consistency}")
            self.logger.debug(f"[FUSION_GATE] Guard status: guard_active={guard_active}, guard_reason={guard_reason}")
            self.logger.debug(f"[FUSION_GATE] Warmup status: warmup_active={warmup_active}, ofi_warmup={ofi_warmup}, cvd_warmup={cvd_warmup}")
            self.logger.debug(f"[FUSION_GATE] Current regime: {current_regime}")
        
        # 注意：各分支已经分别计数，这里不再重复累加，避免双计数
        if self.debug and guard_reason:
            self.logger.debug(f"[GATE_STATS] latest_guard={guard_reason}, snapshot={self.gate_reason_stats.get(guard_reason,0)}")
        
        # 获取融合阈值配置（使用统一配置读取方法，兼容新旧格式）
        fusion_cfg = self._get_fusion_cfg()
        thresholds = fusion_cfg.get('thresholds', {})
        # 兼容两种命名：regime_thresholds 或 regime
        regime_thresholds = thresholds.get('regime_thresholds', thresholds.get('regime', {}))
        
        # 获取当前regime的阈值，如果没有则使用基础阈值
        regime_config = regime_thresholds.get(current_regime, {})
        if regime_config:
            # 使用分场景阈值
            fuse_buy = regime_config.get('fuse_buy', thresholds.get('fuse_buy', 1.0))
            fuse_sell = regime_config.get('fuse_sell', thresholds.get('fuse_sell', -1.0))
        else:
            # 使用基础阈值
            fuse_buy = thresholds.get('fuse_buy', 1.0)
            fuse_sell = thresholds.get('fuse_sell', -1.0)
        
        # 根据信号方向选择阈值
        if fusion_score > 0:
            threshold = fuse_buy
        else:
            threshold = abs(fuse_sell)
        
        # 背离信号加成：门槛再降20%（与文档对齐）
        if hasattr(self, '_last_divergence_type') and self._last_divergence_type in ("bull_div", "bear_div", "hidden_bull", "hidden_bear"):
            threshold *= 0.8  # 背离加成：门槛再降20%
        
        # 弱信号节流：只对就绪信号进行节流，未就绪(None)直接跳过
        weak_signal_threshold = float(fusion_cfg.get('weak_signal_threshold', 0.2))
        scenario = getattr(self, '_current_scenario', None) or current_regime
        consistency_params = fusion_cfg.get('consistency', {})
        consistency_threshold = self._scenario_consistency_thresholds.get(
            scenario, consistency_params.get('min_consistency', 0.15)
        )
        
        # 检查弱信号节流 - 只对就绪信号进行节流
        if z_ofi is not None and z_cvd is not None:  # 只对就绪信号进行节流
            if abs(fusion_score) < weak_signal_threshold:
                # 弱信号直接丢弃
                self.gate_reason_stats['weak_signal_throttle'] = self.gate_reason_stats.get('weak_signal_throttle', 0) + 1
                guard_active = True
                guard_reason = "weak_signal_throttle"
                if self.debug:
                    self.logger.debug(f"[WEAK_SIGNAL_THROTTLE] fusion_score={fusion_score:.6f}, threshold={weak_signal_threshold}, z_ofi={z_ofi}, z_cvd={z_cvd}")
            elif consistency < consistency_threshold:
                # 一致性不足
                self.gate_reason_stats['low_consistency'] = self.gate_reason_stats.get('low_consistency', 0) + 1
                guard_active = True
                guard_reason = "low_consistency"
                if self.debug:
                    self.logger.debug(f"[LOW_CONSISTENCY] consistency={consistency:.3f}, threshold={consistency_threshold:.3f}")
        else:
            # 未就绪信号，不进行弱信号节流
            if self.debug:
                self.logger.debug(f"[SKIP_WEAK_SIGNAL_THROTTLE] z_ofi={z_ofi}, z_cvd={z_cvd}, not ready for throttling")
        
        candidate_confirm = (abs(fusion_score) >= threshold and not warmup_active and not guard_active)
        # 候选通过后再做反向防抖（仅判断不落库）
        scenario = getattr(self, '_current_scenario', None) or getattr(self, '_current_regime', 'normal')
        if candidate_confirm:
            reverse_blocked, reverse_reason = self.check_reverse_prevention(symbol, fusion_score, scenario, update_state=False)
            if reverse_blocked:
                guard_active = True
                guard_reason = reverse_reason
        confirm = candidate_confirm and not guard_active
        # 最终确认后才提交防抖状态
        if confirm:
            self.check_reverse_prevention(symbol, fusion_score, scenario, update_state=True)
            self.gate_reason_stats['passed'] += 1
        
        # 更新护栏状态
        self.guard_active = guard_active
        self.guard_reason = guard_reason
        
        # 记录闸门原因统计到JSONL（每10秒快 Photocopy一次，更接近实时）
        if hasattr(self, '_gate_stats_counter'):
            self._gate_stats_counter += 1
        else:
            self._gate_stats_counter = 1
        
        # 每10秒快照一次（类似lag统计的心跳机制）
        now = time.time()
        if not hasattr(self, '_last_gate_dump'):
            self._last_gate_dump = 0.0
        if now - self._last_gate_dump >= 10.0:
            self._log_gate_stats_to_jsonl()
            self._last_gate_dump = now
        
        # 更新统计
        if confirm:
            self.stats['valid_signals'] += 1
        if guard_active:
            self.stats['suppressed_signals'] += 1
        
        # 创建信号数据
        signal_data = SignalData(
            ts_ms=ts_ms,
            symbol=symbol,
            score=fusion_score,
            z_ofi=z_ofi,
            z_cvd=z_cvd,
            regime=regime,
            div_type=div_type,
            confirm=confirm,
            gating=guard_active
        )
        # 5) 记录信号（无论 confirm / gating，完整留痕）
        try:
            self.log_signal(signal_data, output_dir=os.getenv("V13_OUTPUT_DIR", "./runtime"))
        except Exception as e:
            self.logger.warning(f"[SignalLog] write failed: {e}")

        return signal_data
    
    def get_component_stats(self) -> Dict[str, Any]:
        """获取各组件统计信息"""
        return {
            'core_stats': self.stats,
            'ofi_stats': self.ofi_calc.get_state() if hasattr(self, 'ofi_calc') else {},
            'cvd_stats': self.cvd_calc.get_state() if hasattr(self, 'cvd_calc') else {},
            'fusion_stats': self.fusion.get_stats() if hasattr(self, 'fusion') else {},
            'divergence_stats': self.divergence.get_stats() if hasattr(self, 'divergence') else {},
            'strategy_manager_stats': self.strategy_manager.get_mode_stats() if hasattr(self, 'strategy_manager') else {}
        }
    
    def reset_components(self):
        """重置所有组件"""
        if hasattr(self, 'ofi_calc'):
            self.ofi_calc.reset()
        if hasattr(self, 'cvd_calc'):
            self.cvd_calc.reset()
        if hasattr(self, 'fusion'):
            self.fusion.reset()
        if hasattr(self, 'divergence'):
            self.divergence.reset()
        if hasattr(self, 'strategy_manager'):
            # 策略模式管理器没有reset方法，但可以重新初始化
            pass
        
        # 重置统计
        self.stats = {
            'total_updates': 0,
            'valid_signals': 0,
            'suppressed_signals': 0,
            'regime_changes': 0,
            'ofi_updates': 0,
            'cvd_updates': 0,
            'fusion_updates': 0,
            'divergence_events': 0
        }
    
    def log_signal(self, signal_data: SignalData, output_dir: str = None):
        """记录信号日志（健壮 I/O 版）"""
        log_entry = {
            "timestamp": datetime.fromtimestamp(signal_data.ts_ms / 1000).isoformat(),
            "ts_ms": signal_data.ts_ms,
            "symbol": signal_data.symbol,
            "score": signal_data.score,
            "z_ofi": signal_data.z_ofi,
            "z_cvd": signal_data.z_cvd,
            "regime": signal_data.regime,
            "div_type": signal_data.div_type,
            "confirm": signal_data.confirm,
            "gating": signal_data.gating,
            "guard_reason": self.guard_reason if getattr(self, "guard_active", False) else None,
        }

        # 允许函数参数临时覆盖输出目录
        base_dir = Path(output_dir) if output_dir else Path(os.getenv("V13_OUTPUT_DIR", "./runtime"))
        rel_path = Path("ready") / "signal" / signal_data.symbol / f"signals_{datetime.now().strftime('%Y%m%d_%H%M')}.jsonl"

        try:
            # 若显式选择 NullSink，则不做任何写入（用于极限压测/禁用I/O）
            if hasattr(self, "_sink") and isinstance(self._sink, NullSink):
                return
            if hasattr(self, "_sink") and not isinstance(self._sink, NullSink):
                self._sink.emit(log_entry)
            else:
                writer = self._safe_writer if base_dir == self._safe_writer.base_dir else SafeJsonlWriter(base_dir)
                writer.write_line(rel_path, log_entry)
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(
                    f"Signal logged: {signal_data.symbol} score={signal_data.score:.3f} "
                    f"regime={signal_data.regime} confirm={signal_data.confirm} gating={signal_data.gating}"
                )
        except Exception as e:
            # 不让交易/信号路径被 I/O 拖垮
            self.logger.error(f"[FILE-IO] failed to write {rel_path} under {base_dir}: {e}; entry={log_entry}")

def main():
    """测试主函数 - 直接调用成熟组件"""
    parser = argparse.ArgumentParser(description='核心算法组件')
    parser.add_argument('--compat-global-config', action='store_true',
                       help='启用兼容模式：从全局配置目录加载，而非运行时包（临时过渡选项）')
    args = parser.parse_args()
    
    if args.compat_global_config:
        os.environ['V13_COMPAT_GLOBAL_CONFIG'] = 'true'
        os.environ['V13_STRICT_RUNTIME'] = 'false'
    
    print("=== 核心算法v1 - 直接调用成熟组件测试 ===")
    if args.compat_global_config:
        print("[兼容模式] 使用全局配置目录（临时过渡选项）")
    
    # 初始化核心算法
    symbol = "BTCUSDT"
    config = SignalConfig()
    algo = CoreAlgorithm(symbol, config)
    
    # 模拟数据
    ts_ms = int(datetime.now().timestamp() * 1000)
    z_ofi = 1.5
    z_cvd = 1.2
    price = 50000.0
    trade_rate = 50.0
    realized_vol = 0.01
    spread_bps = 5.0
    missing_msgs_rate = 0.0001
    
    print(f"\n--- 测试OFI计算器 ---")
    # 模拟订单簿数据
    bids = [(50000.0, 10.0), (49999.0, 8.0), (49998.0, 6.0), (49997.0, 4.0), (49996.0, 2.0)]
    asks = [(50001.0, 12.0), (50002.0, 9.0), (50003.0, 7.0), (50004.0, 5.0), (50005.0, 3.0)]
    ofi_result = algo.update_ofi(bids, asks, ts_ms)
    print(f"OFI结果: {ofi_result}")
    
    print(f"\n--- 测试CVD计算器 ---")
    cvd_result = algo.update_cvd(price=price, qty=1.0, is_buy=True, event_time_ms=ts_ms)
    print(f"CVD结果: {cvd_result}")
    
    print(f"\n--- 测试融合指标 ---")
    fusion_result = algo.update_fusion(z_ofi, z_cvd, ts_ms/1000.0, price)
    print(f"融合结果: {fusion_result}")
    
    print(f"\n--- 测试背离检测 ---")
    divergence_result = algo.update_divergence(ts_ms/1000.0, price, z_ofi, z_cvd)
    print(f"背离检测结果: {divergence_result}")
    
    print(f"\n--- 测试完整信号处理 ---")
    # 处理信号
    signal_data = algo.process_signal(
        ts_ms, symbol, z_ofi, z_cvd, price,
        trade_rate, realized_vol, spread_bps, missing_msgs_rate
    )
    
    print(f"信号数据: {signal_data}")
    print(f"护栏状态: {algo.guard_active}, 原因: {algo.guard_reason}")
    
    print(f"\n--- 组件统计信息 ---")
    stats = algo.get_component_stats()
    for component, stat in stats.items():
        print(f"{component}: {stat}")
    
    print(f"\n=== 测试完成 ===")

if __name__ == "__main__":
    main()
