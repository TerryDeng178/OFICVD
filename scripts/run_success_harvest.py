#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成功版OFI+CVD数据采集脚本 (基于Task 1.2.5成功实现)
使用正确的Binance Futures WebSocket URL格式
"""

# V13: forbid os.getenv except ALLOWED_ENV (see ALLOWED_ENV below)
# 以下环境变量将在第4步中替换为从cfg读取：
# - EXTREME_TRAFFIC_THRESHOLD (line 135)
# - EXTREME_ROTATE_SEC (line 137)
# - MAX_ROWS_PER_FILE (line 140)
# - SAVE_CONCURRENCY (line 142)
# - HEALTH_CHECK_INTERVAL (line 257) - 注释已标记但代码中可能还有
# - STREAM_IDLE_SEC (line 294)
# - TRADE_TIMEOUT (line 295)
# - ORDERBOOK_TIMEOUT (line 296)
# - BACKOFF_RESET_SECS (line 299)
# - DEDUP_LRU (line 313)
# - QUEUE_DROP_THRESHOLD (line 317)
# - OFI_MAX_LAG_MS (line 1229)
# - OUTPUT_DIR (main函数中，line 2095)
# - PREVIEW_DIR (line 105)
# - SYMBOLS (main函数中，line 2090)
# - RUN_HOURS (main函数中，line 2091)
# - CVD_SIGMA_FLOOR_K, CVD_WINSOR, W_OFI, W_CVD, FUSION_CAL_K (这些不在harvester配置中，可保留env读取)
# - PAPER_ENABLE (line 1425, 2028) - 业务逻辑标志，不在harvester配置中

import asyncio
import websockets
import json
import time
import logging
import os
import hashlib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque, OrderedDict
from typing import Dict, List, Any, Optional
import math
import sys
import uuid  # 新增：用于生成唯一文件名

# 环境变量白名单（仅允许这些env在严格模式下使用）
ALLOWED_ENV = {
    "CVD_SIGMA_FLOOR_K", "CVD_WINSOR", "W_OFI", "W_CVD", "FUSION_CAL_K", "PAPER_ENABLE",
    "V13_DEV_PATHS"  # 开发模式路径注入
}

def _env(name: str, default=None, cast=lambda v: v):
    """安全的环境变量读取（仅允许白名单）"""
    if name not in ALLOWED_ENV:
        raise RuntimeError(f"Env '{name}' not allowed in harvester strict mode (allowed: {ALLOWED_ENV})")
    val = os.getenv(name, default)
    if val is not None:
        return cast(val)
    return default

# 添加项目路径（仅在开发模式）
if _env("V13_DEV_PATHS", "0", str) == "1":
    THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    CANDIDATE_PATHS = [
        os.path.abspath(os.path.join(THIS_DIR, "..", "src")),
        os.path.abspath(os.path.join(THIS_DIR, "..", "..", "src")),
        os.path.abspath(os.path.join(THIS_DIR, "..", "..", "v13_ofi_ai_system", "src")),
        os.path.abspath(os.path.join(THIS_DIR, "..")),
        THIS_DIR,
        os.getcwd(),
    ]
    for p in CANDIDATE_PATHS:
        if p not in sys.path:
            sys.path.insert(0, p)

# 设置日志（必须在导入前设置，以便后续使用logger）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 开发模式下记录路径注入（logger已定义）
if _env("V13_DEV_PATHS", "0", str) == "1":
    for p in CANDIDATE_PATHS:
        if p in sys.path:
            logger.debug(f"dev path added: {p}")

# 导入核心组件
try:
    from real_ofi_calculator import RealOFICalculator, OFIConfig
    from real_cvd_calculator import RealCVDCalculator, CVDConfig
    from ofi_cvd_fusion import OFI_CVD_Fusion, OFICVDFusionConfig
    from ofi_cvd_divergence import DivergenceDetector, DivergenceConfig
    OFI_AVAILABLE = True
    CVD_AVAILABLE = True
    FUSION_AVAILABLE = True
    DIVERGENCE_AVAILABLE = True
    logger.info("成功导入所有核心组件")
except ImportError as e:
    logger.warning(f"无法导入核心组件: {e}")
    OFI_AVAILABLE = False
    CVD_AVAILABLE = False
    FUSION_AVAILABLE = False
    DIVERGENCE_AVAILABLE = False
    # 设置默认值
    RealOFICalculator = None
    OFIConfig = None
    RealCVDCalculator = None
    CVDConfig = None
    OFI_CVD_Fusion = None
    OFICVDFusionConfig = None
    DivergenceDetector = None
    DivergenceConfig = None

# 稳定hash函数
def stable_row_id(s):
    """生成稳定的row_id"""
    return hashlib.md5(s.encode()).hexdigest()

class SuccessOFICVDHarvester:
    """成功版OFI+CVD数据采集器（基于Task 1.2.5成功实现）"""
    
    def __init__(self, cfg: dict = None, *, compat_env: bool = False, symbols=None, run_hours=24, output_dir=None):
        """
        初始化Harvester（统一配置模式）
        
        Args:
            cfg: 配置字典（来自运行时包），如果为None则使用向后兼容模式
            compat_env: 兼容环境变量模式（下一版本将移除，默认False）
            symbols: 向后兼容参数（仅当cfg=None时使用）
            run_hours: 向后兼容参数（实际不再使用，组件支持7x24小时连续运行）
            output_dir: 向后兼容参数（仅当cfg=None时使用）
        """
        # 第2步：修改构造函数签名，接收cfg子树
        self.cfg = cfg or {}
        self._compat_env = compat_env
        
        # 基础目录和时间（所有模式都需要）
        self.base_dir = Path(__file__).parent.absolute()
        self.run_hours = run_hours
        self.start_time = datetime.now().timestamp()
        self.end_time = self.start_time + (run_hours * 3600)
        
        # 第3步：从cfg映射所有字段（在_apply_cfg中实现）
        self._apply_cfg(symbols, output_dir)
        
        # 预览/权威分仓配置
        self.preview_kinds = {'ofi', 'cvd', 'fusion', 'events', 'features'}
        
        # 创建输出目录结构
        self._create_directory_structure()
        
        # 数据缓冲区（按symbol分桶）
        self.data_buffers = {
            'prices': {symbol: [] for symbol in self.symbols},
            'ofi': {symbol: [] for symbol in self.symbols},
            'cvd': {symbol: [] for symbol in self.symbols},
            'fusion': {symbol: [] for symbol in self.symbols},
            'events': {symbol: [] for symbol in self.symbols},
            'orderbook': {symbol: [] for symbol in self.symbols},  # 新增订单簿数据缓冲区
            'features': {symbol: [] for symbol in self.symbols}  # 新增特征对齐宽表缓冲区
        }
        # 极端流量保护：动态轮转间隔
        self.extreme_traffic_mode = False
        
        # 死信（deadletter）目录（已在_apply_cfg中设置artifacts_dir，这里只需创建子目录）
        self.deadletter_dir = self.artifacts_dir / "deadletter"
        self.deadletter_dir.mkdir(parents=True, exist_ok=True)
        
        # 订单簿缓存
        self.orderbooks = {symbol: {} for symbol in self.symbols}
        
        # 订单簿快照队列（用于时间对齐）
        # orderbook_buf_len已在_apply_cfg中设置
        self.orderbook_buf = {symbol: deque(maxlen=self.orderbook_buf_len) for symbol in self.symbols}
        
        # 2×2场景标签计算缓存
        self.scene_cache = {}
        # CVD累积和标准化缓存
        self.cvd_cache = {}
        self.cvd_calc_mode = {}  # 新增：追踪每个symbol的计算模式 (core/fallback)
        for symbol in self.symbols:
            self.scene_cache[symbol] = {
                'price_history': deque(maxlen=300),  # 300秒价格历史
                'trade_history': deque(maxlen=300),  # 300秒交易历史
                'last_update': 0,
                'regime': 'normal',
                'vol_bucket': 'mid',
                'scenario_2x2': 'A_L',  # 默认
                'session': 'Tokyo',  # 默认
                'fee_tier': 'TM'  # 默认
            }
            self.cvd_cache[symbol] = {
                'cvd_cumulative': 0.0,  # 累积CVD
                'delta_history': deque(maxlen=300),  # 300秒delta历史
                'last_update': 0,
                'last_core_cvd': 0.0  # 新增：最后一次核心组件成功计算的CVD值
            }
            self.cvd_calc_mode[symbol] = 'core'  # 默认使用核心组件
        
        # 核心组件初始化
        self.ofi_calculators = {}
        self.cvd_calculators = {}
        self.fusion_calculators = {}
        self.divergence_detectors = {}
        
        # OFI计算器
        if OFI_AVAILABLE:
            for symbol in self.symbols:
                config = OFIConfig(
                    levels=5,
                    z_window=100,
                    ema_alpha=0.1
                )
                self.ofi_calculators[symbol] = RealOFICalculator(symbol, config)
        
        # CVD计算器
        if CVD_AVAILABLE:
            for symbol in self.symbols:
                config = CVDConfig(
                    z_window=150,
                    ema_alpha=0.2,
                    use_tick_rule=True,
                    warmup_min=3
                )
                self.cvd_calculators[symbol] = RealCVDCalculator(symbol, config)
        
        # 融合计算器
        if FUSION_AVAILABLE:
            for symbol in self.symbols:
                config = OFICVDFusionConfig(
                    w_ofi=0.6,
                    w_cvd=0.4,
                    fuse_buy=1.2,
                    fuse_strong_buy=2.0,
                    fuse_sell=-1.2,
                    fuse_strong_sell=-2.0,
                    min_consistency=0.2,
                    strong_min_consistency=0.6
                )
                self.fusion_calculators[symbol] = OFI_CVD_Fusion(config)
        
        # 背离检测器
        if DIVERGENCE_AVAILABLE:
            for symbol in self.symbols:
                config = DivergenceConfig(
                    swing_L=12,
                    ema_k=5,
                    z_hi=1.5,
                    z_mid=0.7,
                    min_separation=6,
                    cooldown_secs=1.0,
                    warmup_min=100,
                    max_lag=0.300,
                    use_fusion=True,
                    cons_min=0.3
                )
                self.divergence_detectors[symbol] = DivergenceDetector(config)
        
        # 统计信息
        self.stats = {
            'total_trades': {symbol: 0 for symbol in self.symbols},
            'total_ofi': {symbol: 0 for symbol in self.symbols},
            'total_cvd': {symbol: 0 for symbol in self.symbols},
            'total_events': {symbol: 0 for symbol in self.symbols},
            'total_orderbook': {symbol: 0 for symbol in self.symbols}  # 新增订单簿统计
        }
        
        # 性能监控字段
        self.reconnect_count = 0  # 重连计数
        self.queue_dropped = 0  # 队列丢弃计数
        
        # 运行状态
        self.running = True
        
        # 单调时钟（避免NTP回拨影响轮转和健康检查）
        self._mono = time.monotonic
        
        # 健康监控（data_timeout和max_connection_errors已在_apply_cfg中设置）
        self.last_health_check = self._mono()
        self.connection_errors = 0
        self.last_data_time = {symbol: self._mono() for symbol in self.symbols}
        
        # 补丁B：分流监控时间戳
        self.last_trade_time = {symbol: self._mono() for symbol in self.symbols}
        self.last_ob_time = {symbol: self._mono() for symbol in self.symbols}
        
        # 健康检查计数器
        self.health_check_counter = 0
        
        # 子流超时检测标志（用于 manifest 观测）
        self.substream_timeout_detected = False
        
        # 每小时写盘行数统计
        self.hourly_write_counts = {kind: 0 for kind in ['prices', 'orderbook', 'ofi', 'cvd', 'fusion', 'events', 'features']}
        
        # CVD/Fusion计算参数（保留环境变量读取，因为这些不在harvester配置中）
        # 这些参数已在上面从配置或环境变量读取
        
        # 轮转定时器 - 使用单调时钟避免NTP回拨影响
        self.last_rotate_time = self._mono()
        
        # slices_manifest定时器
        self.last_manifest_time = self._mono()
        
        # 并发安全锁
        self.rotation_lock = asyncio.Lock()
        self.scene_coverage_stats = {}  # 场景覆盖统计
        
        # 去重缓存
        self.dedup_cache = {}  # {symbol: OrderedDict of trade_ids}
        # dedup_lru_size已在上面从配置读取（cfg模式或环境变量模式）
        
        # 丢弃计数监控
        self.last_queue_dropped = 0
        # queue_drop_threshold已在上面从配置读取（cfg模式或环境变量模式）
        self.consecutive_drop_rounds = 0  # 连续丢弃轮数
        
        # Features去重游标（防止同一秒重复入表）
        self.last_feature_second = {symbol: 0 for symbol in self.symbols}
        
        for symbol in self.symbols:
            self.scene_coverage_stats[symbol] = {
                'A_H': 0, 'A_L': 0, 'Q_H': 0, 'Q_L': 0
            }
        
        logger.info(f"初始化成功版采集器: {self.symbols}, 支持7x24小时连续运行")
        logger.info(f"OFI计算器状态: {'可用' if OFI_AVAILABLE else '不可用'}")
        logger.info(f"场景标签配置: WIN_SECS={self.win_secs}, ACTIVE_TPS={self.active_tps}, VOL_SPLIT={self.vol_split}")
        logger.info(f"补丁A配置: STREAM_IDLE_SEC={self.stream_idle_sec}, TRADE_TIMEOUT={self.trade_timeout}, ORDERBOOK_TIMEOUT={self.orderbook_timeout}")
        logger.info(f"退避复位配置: BACKOFF_RESET_SECS={self.backoff_reset_secs}秒")
        
        # 校验超时阈值关系
        if self.stream_idle_sec >= self.trade_timeout:
            logger.warning(f"[CONFIG] 警告: STREAM_IDLE_SEC({self.stream_idle_sec}) >= TRADE_TIMEOUT({self.trade_timeout}), 可能导致健康告警早于读超时")
        else:
            logger.info(f"[CONFIG] 超时关系校验: STREAM_IDLE_SEC({self.stream_idle_sec}) < TRADE_TIMEOUT({self.trade_timeout}) ✓")
        
        if self.stream_idle_sec >= self.orderbook_timeout:
            logger.warning(f"[CONFIG] 警告: STREAM_IDLE_SEC({self.stream_idle_sec}) >= ORDERBOOK_TIMEOUT({self.orderbook_timeout}), 可能导致健康告警早于读超时")
        else:
            logger.info(f"[CONFIG] 超时关系校验: STREAM_IDLE_SEC({self.stream_idle_sec}) < ORDERBOOK_TIMEOUT({self.orderbook_timeout}) ✓")
        logger.info(f"健康检查间隔: {self.health_check_interval}秒")
        logger.info(f"极端流量保护: 阈值={self.extreme_traffic_threshold}, 正常轮转={self.normal_rotate_sec}s, 极端轮转={self.extreme_rotate_sec}s")
        logger.info(f"保存并发度: {self.save_concurrency}")
        logger.info(f"文件大小控制: 最大行数={self.max_rows_per_file}, 去重LRU={self.dedup_lru_size}")
        logger.info(f"丢弃计数监控: 阈值={self.queue_drop_threshold}")
        
        # 生成run_manifest（增强可复现性）
        self._generate_run_manifest()
    
    def _apply_cfg(self, symbols=None, output_dir=None):
        """
        第3步：从cfg映射所有字段（引入默认值）
        如果cfg为空且compat_env=True，使用向后兼容的环境变量模式
        否则cfg为空直接报错（避免生产无意走回老路）
        """
        c = self.cfg
        
        # 兼容模式：cfg为空时使用环境变量（仅在compat_env=True时允许）
        if not c:
            if not self._compat_env:
                raise ValueError("harvester: cfg is empty but compat_env=False; refuse env fallback (use --compat-global-config or provide runtime package)")
            # 向后兼容：从环境变量读取
            self.symbols = symbols or os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT').split(',')
            
            if output_dir is None:
                output_dir = os.getenv('OUTPUT_DIR', str(self.base_dir / "data" / "ofi_cvd"))
            self.output_dir = Path(output_dir)
            
            preview_dir_env = os.getenv('PREVIEW_DIR')
            if preview_dir_env:
                self.preview_dir = Path(preview_dir_env)
            else:
                self.preview_dir = self.base_dir / "preview" / "ofi_cvd"
            
            self.artifacts_dir = self.base_dir / "artifacts"
            
            # 从环境变量读取所有配置
            self.buffer_high = {
                'prices': 20000, 'orderbook': 12000,
                'ofi': 8000, 'cvd': 8000, 'fusion': 5000, 'events': 5000, 'features': 8000
            }
            self.buffer_emergency = {
                'prices': 40000, 'orderbook': 24000,
                'ofi': 16000, 'cvd': 16000, 'fusion': 10000, 'events': 10000, 'features': 16000
            }
            self.extreme_traffic_threshold = int(os.getenv('EXTREME_TRAFFIC_THRESHOLD', '30000'))
            self.extreme_rotate_sec = int(os.getenv('EXTREME_ROTATE_SEC', '30'))
            self.max_rows_per_file = int(os.getenv('MAX_ROWS_PER_FILE', '50000'))
            self.save_concurrency = int(os.getenv("SAVE_CONCURRENCY", "2"))
            self.save_semaphore = asyncio.Semaphore(self.save_concurrency)
            self.health_check_interval = int(os.getenv('HEALTH_CHECK_INTERVAL', '25'))
            self.win_secs = int(os.getenv('WIN_SECS', '300'))
            self.active_tps = float(os.getenv('ACTIVE_TPS', '0.1'))
            self.vol_split = float(os.getenv('VOL_SPLIT', '0.5'))
            self.fee_tier = os.getenv('FEE_TIER', 'TM')
            self.parquet_rotate_sec = int(os.getenv('PARQUET_ROTATE_SEC', '60'))
            self.normal_rotate_sec = self.parquet_rotate_sec
            self.stream_idle_sec = int(os.getenv('STREAM_IDLE_SEC', '120'))
            self.trade_timeout = int(os.getenv('TRADE_TIMEOUT', '150'))
            self.orderbook_timeout = int(os.getenv('ORDERBOOK_TIMEOUT', '180'))
            self.backoff_reset_secs = int(os.getenv('BACKOFF_RESET_SECS', '300'))
            self.dedup_lru_size = int(os.getenv('DEDUP_LRU', '32768'))
            self.queue_drop_threshold = int(os.getenv('QUEUE_DROP_THRESHOLD', '1000'))
            self.ofi_max_lag_ms = int(os.getenv('OFI_MAX_LAG_MS', '800'))
            
            # 运行期工况常量（兼容模式下使用默认值）
            self.orderbook_buf_len = 1024
            self.features_lookback_secs = 60
            
            # 健康监控配置（兼容模式使用默认值）
            self.data_timeout = 300
            self.max_connection_errors = 10
            
            # 保存并发数（兼容模式）
            self.save_concurrency = int(os.getenv("SAVE_CONCURRENCY", "2"))
            self.save_semaphore = asyncio.Semaphore(self.save_concurrency)
            
            # CVD/Fusion参数（不在harvester配置中，使用白名单env读取）
            self.cvd_sigma_floor_k = float(_env('CVD_SIGMA_FLOOR_K', '0.3'))
            self.cvd_winsor = float(_env('CVD_WINSOR', '2.5'))
            self.w_ofi = float(_env('W_OFI', '0.6'))
            self.w_cvd = float(_env('W_CVD', '0.4'))
            self.fusion_cal_k = float(_env('FUSION_CAL_K', '1.0'))
        else:
            # 新格式：从配置字典读取（严格运行时模式）
            # 1) 符号与路径
            self.symbols = c.get("symbols", ["BTCUSDT", "ETHUSDT"])
            if symbols is not None:
                self.symbols = symbols  # 命令行参数优先
            
            paths = c.get("paths", {})
            base_dir = self.base_dir
            output_dir_cfg = paths.get("output_dir", "./data/ofi_cvd")
            if output_dir is not None:
                self.output_dir = Path(output_dir)
            elif not Path(output_dir_cfg).is_absolute():
                self.output_dir = base_dir / output_dir_cfg
            else:
                self.output_dir = Path(output_dir_cfg)
            
            preview_dir_cfg = paths.get("preview_dir", "./preview/ofi_cvd")
            if not Path(preview_dir_cfg).is_absolute():
                self.preview_dir = base_dir / preview_dir_cfg
            else:
                self.preview_dir = Path(preview_dir_cfg)
            
            artifacts_dir_cfg = paths.get("artifacts_dir", "./artifacts")
            if not Path(artifacts_dir_cfg).is_absolute():
                self.artifacts_dir = base_dir / artifacts_dir_cfg
            else:
                self.artifacts_dir = Path(artifacts_dir_cfg)
            
            # 2) 缓存/并发/文件旋转
            bufs = c.get("buffers", {})
            self.buffer_high = bufs.get("high", {
                "prices": 20000, "orderbook": 12000, "ofi": 8000, "cvd": 8000, 
                "fusion": 5000, "events": 5000, "features": 8000
            })
            self.buffer_emergency = bufs.get("emergency", {
                "prices": 40000, "orderbook": 24000, "ofi": 16000, "cvd": 16000,
                "fusion": 10000, "events": 10000, "features": 16000
            })
            
            files = c.get("files", {})
            self.max_rows_per_file = int(files.get("max_rows_per_file", 50000))
            self.parquet_rotate_sec = int(files.get("parquet_rotate_sec", 60))
            self.normal_rotate_sec = self.parquet_rotate_sec
            
            # 保存并发数（避免访问Semaphore._value）
            self.save_concurrency = int(c.get("concurrency", {}).get("save_concurrency", 2))
            self.save_semaphore = asyncio.Semaphore(self.save_concurrency)
            
            # 3) 超时/门限/健康
            tmo = c.get("timeouts", {})
            self.health_check_interval = int(tmo.get("health_check_interval", 25))
            self.stream_idle_sec = int(tmo.get("stream_idle_sec", 120))
            self.trade_timeout = int(tmo.get("trade_timeout", 150))
            self.orderbook_timeout = int(tmo.get("orderbook_timeout", 180))
            self.backoff_reset_secs = int(tmo.get("backoff_reset_secs", 300))
            
            # 健康监控配置（从health子树读取，或timeouts兼容）
            health = c.get("health", {})
            self.data_timeout = int(health.get("data_timeout", tmo.get("data_timeout", 300)))
            self.max_connection_errors = int(health.get("max_connection_errors", 10))
            
            th = c.get("thresholds", {})
            self.extreme_traffic_threshold = int(th.get("extreme_traffic_threshold", 30000))
            self.extreme_rotate_sec = int(th.get("extreme_rotate_sec", 30))
            self.ofi_max_lag_ms = int(th.get("ofi_max_lag_ms", 800))
            
            # 4) 去重/场景
            ded = c.get("dedup", {})
            self.dedup_lru_size = int(ded.get("lru_size", 32768))
            self.queue_drop_threshold = int(ded.get("queue_drop_threshold", 1000))
            
            sc = c.get("scenario", {})
            self.win_secs = int(sc.get("win_secs", 300))
            self.active_tps = float(sc.get("active_tps", 0.1))
            self.vol_split = float(sc.get("vol_split", 0.5))
            self.fee_tier = sc.get("fee_tier", "TM")
            
            # CVD/Fusion参数（不在harvester配置中，使用白名单env读取）
            self.cvd_sigma_floor_k = float(_env('CVD_SIGMA_FLOOR_K', '0.3'))
            self.cvd_winsor = float(_env('CVD_WINSOR', '2.5'))
            self.w_ofi = float(_env('W_OFI', '0.6'))
            self.w_cvd = float(_env('W_CVD', '0.4'))
            self.fusion_cal_k = float(_env('FUSION_CAL_K', '1.0'))
    
    def _check_health(self):
        """健康检查：监控数据流和连接状态（补丁B：分流监控 + 子流超时检测）"""
        current_time = self._mono()
        
        # 补丁B：分流监控 - 分别检查交易流和订单簿流
        for symbol in self.symbols:
            # 检查交易流超时
            trade_time_since = current_time - self.last_trade_time[symbol]
            if trade_time_since > self.trade_timeout:
                logger.warning(f"[HEALTH][TRADE] {symbol} 交易流超时 {trade_time_since:.1f}s")
                self.substream_timeout_detected = True  # 标记子流超时
            
            # 检查订单簿流超时
            ob_time_since = current_time - self.last_ob_time[symbol]
            if ob_time_since > self.orderbook_timeout:
                logger.warning(f"[HEALTH][OB] {symbol} 订单簿流超时 {ob_time_since:.1f}s")
                self.substream_timeout_detected = True  # 标记子流超时
        
        # 保留原有的全局数据超时检查（不影响现有逻辑）
        for symbol in self.symbols:
            time_since_last_data = current_time - self.last_data_time[symbol]
            if time_since_last_data > self.data_timeout:
                logger.warning(f"[HEALTH] {symbol} 数据超时: {time_since_last_data:.1f}秒")
                self.connection_errors += 1
            else:
                # 任一symbol恢复就让错误计数回落（避免一次抖动累死进程）
                self.connection_errors = max(0, self.connection_errors - 1)
        
        # 检查连接错误次数
        if self.connection_errors > self.max_connection_errors:
            logger.error(f"[HEALTH] 连接错误过多: {self.connection_errors}，请求重连")
            # 不停机，交给上层连接协程去重连
            self.reconnect_count += 1
            self.connection_errors = 0
            return True  # 返回True以保持 loop 继续跑
        
        # 若最近半个超时窗口内所有symbol都有数据，清零错误计数（恢复清零）
        if all((current_time - self.last_data_time[s]) < (self.data_timeout / 2) for s in self.symbols):
            if self.connection_errors:
                logger.info("[HEALTH] 数据恢复，重置连接错误计数")
            self.connection_errors = 0
        
        # 更新健康检查时间
        self.last_health_check = current_time
        return True
    
    def _update_data_time(self, symbol):
        """更新数据接收时间"""
        self.last_data_time[symbol] = self._mono()
    
    def _generate_run_manifest(self):
        try:
            import platform
            import sys
            
            manifest = {
                'run_id': datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
                'start_time': datetime.utcnow().isoformat(),
                'config': {
                    'symbols': self.symbols,
                    'run_hours': self.run_hours,
                    'output_dir': str(self.output_dir),
                    'win_secs': self.win_secs,
                    'active_tps': self.active_tps,
                    'vol_split': self.vol_split,
                    'fee_tier': self.fee_tier,
                    'parquet_rotate_sec': self.parquet_rotate_sec,
                    'dedup_lru_size': self.dedup_lru_size
                },
                'components': {
                    'ofi_available': OFI_AVAILABLE,
                    'cvd_available': CVD_AVAILABLE,
                    'fusion_available': FUSION_AVAILABLE,
                    'divergence_available': DIVERGENCE_AVAILABLE
                },
                'environment': {
                    'python_version': sys.version,
                    'platform': platform.platform(),
                    'architecture': platform.architecture(),
                    'machine': platform.machine(),
                    'processor': platform.processor()
                },
                'parameters': {
                    'cvd_sigma_floor_k': float(_env('CVD_SIGMA_FLOOR_K', '0.3')),
                    'cvd_winsor': float(_env('CVD_WINSOR', '2.5')),
                    'w_ofi': float(_env('W_OFI', '0.6')),
                    'w_cvd': float(_env('W_CVD', '0.4')),
                    'fusion_cal_k': float(_env('FUSION_CAL_K', '1.0')),
                    'paper_enable': _env('PAPER_ENABLE', '0')
                }
            }
            
            # 保存manifest文件（使用固定的artifacts目录）
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            manifest_file = self.artifacts_dir / "run_logs" / f"run_manifest_{timestamp}.json"
            manifest_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            
            logger.info(f"运行清单已保存: {manifest_file}")
            
        except Exception as e:
            logger.error(f"生成运行清单错误: {e}")
    
    def _generate_features_table(self, symbol: str):
        """生成特征对齐宽表（按秒聚合）"""
        try:
            # 仅处理"最近窗口 + 上次未处理后的增量秒"，避免O(N)全表扫描
            current_time = time.time()
            lookback_seconds = self.features_lookback_secs
            start_ms = max(int((current_time - lookback_seconds) * 1000),
                           (self.last_feature_second.get(symbol, 0) + 1) * 1000)
            def _collect_recent(buf):
                out = []
                # 逆向尾扫，遇到过旧数据即停
                for x in reversed(buf):
                    ts = x.get('ts_ms', 0)
                    if ts < start_ms:
                        break
                    out.append(x)
                out.reverse()
                return out
            prices_data = _collect_recent(self.data_buffers['prices'][symbol])
            ofi_data    = _collect_recent(self.data_buffers['ofi'][symbol])
            cvd_data    = _collect_recent(self.data_buffers['cvd'][symbol])
            fusion_data = _collect_recent(self.data_buffers['fusion'][symbol])
            
            if not prices_data:
                return
            
            # 按秒聚合
            features_by_second = {}
            
            # 聚合价格数据（取最后观测）
            for data in prices_data:
                second_ts = int(data['ts_ms'] // 1000)
                if second_ts not in features_by_second:
                    features_by_second[second_ts] = {
                        'second_ts': second_ts,
                        'symbol': symbol,
                        'mid': data.get('price', 0.0),
                        'return_1s': 0.0,
                        'ofi_z': None,
                        'cvd_z': None,
                        'fusion_score': None,
                        'scenario_2x2': data.get('scenario_2x2', 'A_L'),
                        'lag_ms_ofi': None,
                        'lag_ms_cvd': None,
                        'lag_ms_fusion': None,
                        'best_bid': None,
                        'best_ask': None,
                        'spread_bps': None,
                        'best_buy_fill': data.get('best_buy_fill', 0.0),
                        'best_sell_fill': data.get('best_sell_fill', 0.0)
                    }
                else:
                    # 更新为最新观测
                    features_by_second[second_ts]['mid'] = data.get('price', 0.0)
                    features_by_second[second_ts]['scenario_2x2'] = data.get('scenario_2x2', 'A_L')
                    features_by_second[second_ts]['best_buy_fill'] = data.get('best_buy_fill', 0.0)
                    features_by_second[second_ts]['best_sell_fill'] = data.get('best_sell_fill', 0.0)
            
            # 聚合OFI数据（取最后观测）
            for data in ofi_data:
                second_ts = int(data['ts_ms'] // 1000)
                if second_ts in features_by_second:
                    features_by_second[second_ts]['ofi_z'] = data.get('ofi_z', 0.0)
                    features_by_second[second_ts]['lag_ms_ofi'] = data.get('lag_ms_to_trade', 0)
            
            # 聚合CVD数据（取最后观测）
            for data in cvd_data:
                second_ts = int(data['ts_ms'] // 1000)
                if second_ts in features_by_second:
                    features_by_second[second_ts]['cvd_z'] = data.get('z_cvd', 0.0)
                    features_by_second[second_ts]['lag_ms_cvd'] = data.get('latency_ms', 0)
            
            # 聚合融合数据（取最后观测）
            for data in fusion_data:
                second_ts = int(data['ts_ms'] // 1000)
                if second_ts in features_by_second:
                    features_by_second[second_ts]['fusion_score'] = data.get('score', 0.0)
                    features_by_second[second_ts]['lag_ms_fusion'] = data.get('lag_ms_trade', 0)
            
            # 补齐盘口强相关字段（精确时间对齐）
            max_lag_ms = 5000  # Features对齐宽松度：5秒
            logger.debug(f"[FEATURES_ALIGNMENT] {symbol} 使用max_lag_ms={max_lag_ms}进行orderbook时间对齐")
            for second_ts in features_by_second:
                # 使用精确的orderbook快照，确保时间对齐
                ob_snapshot = self._pick_orderbook_snapshot(symbol, second_ts * 1000, max_lag_ms=max_lag_ms)
                if ob_snapshot:
                    features_by_second[second_ts]['best_bid'] = ob_snapshot.get('best_bid')
                    features_by_second[second_ts]['best_ask'] = ob_snapshot.get('best_ask')
                    features_by_second[second_ts]['spread_bps'] = ob_snapshot.get('spread_bps')
            
            # 计算1秒收益率
            sorted_seconds = sorted(features_by_second.keys())
            for i in range(1, len(sorted_seconds)):
                prev_second = sorted_seconds[i-1]
                curr_second = sorted_seconds[i]
                prev_mid = features_by_second[prev_second]['mid']
                curr_mid = features_by_second[curr_second]['mid']
                if prev_mid > 0:
                    features_by_second[curr_second]['return_1s'] = (curr_mid - prev_mid) / prev_mid
            
            # 保存到features缓冲区（去重：筛掉已写过的秒）
            new_rows = 0
            for second_ts, features in features_by_second.items():
                if second_ts <= self.last_feature_second[symbol]:
                    continue  # 跳过已写入的秒
                features['row_id'] = stable_row_id(f"{symbol}|{second_ts}|features")
                features['ts_ms'] = second_ts * 1000
                features['recv_ts_ms'] = int(current_time * 1000)
                self.data_buffers['features'][symbol].append(features)
                new_rows += 1
            
            # 更新游标
            if features_by_second:
                self.last_feature_second[symbol] = max(self.last_feature_second[symbol], max(features_by_second.keys()))
            
            logger.info(f"生成特征宽表: {symbol}, 新增 {new_rows} 秒")
            
        except Exception as e:
            logger.error(f"生成特征宽表错误 {symbol}: {e}")
    
    # --- 内存压力与溢写控制 ---
    async def _maybe_flush_on_pressure(self, symbol: str, kind: str):
        size = len(self.data_buffers[kind][symbol])
        if size >= self.buffer_high.get(kind, 10000):
            async with self.save_semaphore:
                await self._save_data(symbol, kind)
            size = len(self.data_buffers[kind][symbol])
        # 紧急水位：非权威流溢写到deadletter，权威流尝试再次落盘
        if size >= self.buffer_emergency.get(kind, 20000):
            if kind in ('ofi', 'cvd', 'fusion', 'events', 'features'):
                self._spill_to_deadletter(symbol, kind, self.data_buffers[kind][symbol])
                self.data_buffers[kind][symbol].clear()
                logger.error(f"[SPILL] {symbol}-{kind} 超过紧急水位，已spill到deadletter")
            else:
                async with self.save_semaphore:
                    await self._save_data(symbol, kind)
    
    def _spill_to_deadletter(self, symbol: str, kind: str, rows):
        try:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            path = self.deadletter_dir / kind / f"{symbol}_{ts}_{len(rows)}.ndjson"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            
            # 增强可观测性：打印当前symbol的buffers快照
            buffer_snapshot = {k: len(self.data_buffers[k][symbol]) for k in self.data_buffers}
            logger.error(f"[DEADLETTER] {symbol}-{kind} spill完成: {len(rows)}行 → {path}, "
                        f"当前buffers快照: {buffer_snapshot}")
        except Exception as e:
            logger.error(f"[DEADLETTER] 写入失败 {symbol}-{kind}: {e}")
    
    def _create_directory_structure(self):
        """创建目录结构"""
        # 使用UTC时间创建目录，确保与数据分区一致
        today_utc = datetime.utcnow().strftime("%Y-%m-%d")
        
        for symbol in self.symbols:
            # 权威库：只保留 raw（prices/orderbook）
            for kind in ['prices', 'orderbook']:
                dir_path = self.output_dir / f"date={today_utc}" / f"symbol={symbol}" / f"kind={kind}"
                dir_path.mkdir(parents=True, exist_ok=True)
            # 预览库
            for kind in self.preview_kinds:
                dir_path = self.preview_dir / f"date={today_utc}" / f"symbol={symbol}" / f"kind={kind}"
                dir_path.mkdir(parents=True, exist_ok=True)
        
        # 创建artifacts目录（使用固定的绝对路径）
        (self.artifacts_dir / "run_logs").mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "dq_reports").mkdir(parents=True, exist_ok=True)
    
    def _pick_orderbook_snapshot(self, symbol: str, trade_ts_ms: int, max_lag_ms: int = 250) -> Optional[Dict]:
        """选择最接近交易时间的订单簿快照（用于时间对齐）"""
        try:
            buf = self.orderbook_buf[symbol]
            if not buf:
                return None
            
            # 从最新开始查找，找到 <= trade_ts_ms 的最近快照
            candidate = None
            for ob in reversed(buf):
                if ob['ts_ms'] <= trade_ts_ms:
                    candidate = ob
                    break
            
            # 检查滞后时间是否在允许范围内
            if candidate and (trade_ts_ms - candidate['ts_ms']) <= max_lag_ms:
                return candidate
            
            return None
        except Exception as e:
            logger.error(f"选择订单簿快照错误 {symbol}: {e}")
            return None
    
    def _parse_orderbook_message(self, message):
        """解析订单簿消息（兼容Binance b/a键的无包裹场景）"""
        try:
            raw = json.loads(message) if isinstance(message, str) else message
            
            # 统一一个 data 视图，兼容两种形态
            data = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
            
            # 兼容 Binance 'b'/'a' 以及备选 'bids'/'asks'
            bids_raw = data.get("b") or data.get("bids", [])
            asks_raw = data.get("a") or data.get("asks", [])
            event_ts_ms = int(data.get("E", 0) or data.get("T", 0))
            
            # 标准化格式
            def topk_pad(levels, k, reverse=False):
                """填充到K档，不足补0（Binance深度已按价格序给出，无需重排序）"""
                result = []
                for level in (levels[:k] if levels else []):
                    if isinstance(level, (list, tuple)) and len(level) >= 2:
                        price = float(level[0])
                        qty = float(level[1])
                        result.append((price, qty))
                while len(result) < k:
                    result.append((0.0, 0.0))
                # Binance深度数据本身已按价格序给出，省去sort步骤以节省CPU
                return result[:k]
            
            return {
                'bids': topk_pad(bids_raw, 5, reverse=True),
                'asks': topk_pad(asks_raw, 5, reverse=False),
                'event_ts_ms': event_ts_ms,
                'first_id': data.get("U"),
                'last_id': data.get("u") or data.get("lastUpdateId"),
                'prev_last_id': data.get("pu")
            }
            
        except Exception as e:
            logger.error(f"解析订单簿消息错误: {e}")
            return None
    
    def _calculate_scenario_labels(self, symbol: str, price: float, current_time: int) -> Dict[str, str]:
        """计算2×2场景标签"""
        try:
            cache = self.scene_cache[symbol]
            
            # 更新价格和交易历史
            cache['price_history'].append((current_time, price))
            cache['trade_history'].append(current_time)
            
            # 清理过期数据（超过WIN_SECS的数据）
            cutoff_time = current_time - (self.win_secs * 1000)
            cache['price_history'] = deque(
                [(t, p) for t, p in cache['price_history'] if t >= cutoff_time],
                maxlen=300
            )
            cache['trade_history'] = deque(
                [t for t in cache['trade_history'] if t >= cutoff_time],
                maxlen=300
            )
            
            # 计算活跃度（TPS）- 优化计算逻辑
            recent_trades = len([t for t in cache['trade_history'] if t >= cutoff_time])
            tps = recent_trades / self.win_secs if self.win_secs > 0 else 0
            
            # 动态调整Active阈值，增加A_H和A_L场景覆盖
            # 基于历史TPS动态调整阈值，确保有足够的Active场景
            if 'historical_tps' in cache:
                avg_tps = np.mean(list(cache['historical_tps'])[-10:]) if cache['historical_tps'] else 1.0
                dynamic_threshold = max(0.05, avg_tps * 0.3)  # 更低的动态阈值
            else:
                cache['historical_tps'] = deque(maxlen=50)
                dynamic_threshold = self.active_tps
            
            cache['historical_tps'].append(tps)
            regime = 'Active' if tps >= dynamic_threshold else 'Quiet'
            
            # 缓存TPS用于recv_rate_tps
            cache['current_tps'] = tps
            
            # 计算波动（价格变化的分位）- 优化波动计算
            if len(cache['price_history']) >= 10:
                prices = [p for _, p in cache['price_history']]
                price_changes = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                if price_changes:
                    # 使用更低的阈值来增加High波动场景
                    vol_percentile = np.percentile(price_changes, 100 * self.vol_split)
                    # 进一步降低High波动的判断标准
                    vol_bucket = 'High' if np.mean(price_changes) >= vol_percentile * 0.6 else 'Low'
                else:
                    vol_bucket = 'Low'
            else:
                vol_bucket = 'Low'
            
            # 计算会话标签（基于UTC时间）
            utc_hour = datetime.utcfromtimestamp(current_time / 1000).hour
            if 0 <= utc_hour < 8:
                session = 'Tokyo'  # 东京时间
            elif 8 <= utc_hour < 16:
                session = 'London'  # 伦敦时间
            else:
                session = 'NY'  # 纽约时间
            
            # 生成scenario_2x2
            scenario_2x2 = f"{regime[0]}_{vol_bucket[0]}"  # A_H, A_L, Q_H, Q_L
            
            # 更新缓存
            cache['regime'] = regime
            cache['vol_bucket'] = vol_bucket
            cache['scenario_2x2'] = scenario_2x2
            cache['session'] = session
            cache['last_update'] = current_time
            
            # 累计场景统计
            if scenario_2x2 in self.scene_coverage_stats[symbol]:
                self.scene_coverage_stats[symbol][scenario_2x2] += 1
            
            return {
                'regime': regime,
                'vol_bucket': vol_bucket,
                'scenario_2x2': scenario_2x2,
                'session': session,
                'fee_tier': self.fee_tier
            }
            
        except Exception as e:
            logger.error(f"计算场景标签错误 {symbol}: {e}")
            return {
                'regime': 'normal',
                'vol_bucket': 'mid',
                'scenario_2x2': 'A_L',
                'session': 'Tokyo',
                'fee_tier': self.fee_tier
            }
    
    def _calculate_ofi(self, symbol: str, orderbook: Dict) -> Optional[Dict]:
        """计算OFI指标（使用Task 1.2.5的成功实现）"""
        try:
            if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
                return None
            
            # 使用RealOFICalculator核心组件
            if OFI_AVAILABLE and symbol in self.ofi_calculators:
                result = self.ofi_calculators[symbol].update_with_snapshot(
                    orderbook['bids'], 
                    orderbook['asks'],
                    event_time_ms=orderbook.get('event_ts_ms')
                )
                if result:
                    meta = result.get('meta', {})
                    return {
                        'ofi_value': result['ofi'],
                        'ofi_z': result['z_ofi'],
                        'scale': 1.0,  # OFI结果中没有scale字段，使用固定值
                        'regime': 'normal',
                        # 保存RealOFICalculator的meta信息
                        'warmup': meta.get('warmup', False),
                        'std_zero': meta.get('std_zero', False),
                        'session_reset': meta.get('session_reset', False),
                        'bad_points': meta.get('bad_points', 0),
                        'ema_ofi': result.get('ema_ofi', 0.0)
                    }
            
            # 备用简化计算
            bids = orderbook['bids'][:5]
            asks = orderbook['asks'][:5]
            weights = [0.4, 0.3, 0.2, 0.08, 0.02]
            
            ofi_value = 0.0
            for i in range(5):
                bid_qty = max(0, bids[i][1])
                ask_qty = max(0, asks[i][1])
                weight = weights[i]
                ofi_value += weight * (bid_qty - ask_qty)
            
            # OFI fallback做"轻量标准化"（仅当RealOFI不可用时）
            self.ofi_cache = getattr(self, 'ofi_cache', {})
            self.ofi_cache.setdefault(symbol, deque(maxlen=4096))
            self.ofi_cache[symbol].append(ofi_value)
            arr = np.asarray(self.ofi_cache[symbol], dtype=float)
            if arr.size >= 10:
                med = np.median(arr)
                mad = np.median(np.abs(arr - med))
                robust = 1.4826 * mad if mad > 0 else 1.0
                ofi_z = (ofi_value - med) / max(robust, 1e-9)
                scale = robust
            else:
                ofi_z = ofi_value / 1000.0
                scale = 1000.0
            
            return {
                'ofi_value': ofi_value,
                'ofi_z': ofi_z,
                'scale': scale,
                'regime': 'normal'
            }
            
        except Exception as e:
            logger.error(f"OFI计算错误 {symbol}: {e}")
            return None
    
    def _calculate_cvd(self, symbol: str, trade_data: Dict) -> Optional[Dict]:
        """计算CVD指标（使用RealCVDCalculator核心组件）"""
        try:
            price = float(trade_data.get('price', 0))
            qty = float(trade_data.get('qty', 0))
            is_buy = not trade_data.get('is_buyer_maker', False)
            event_ts_ms = int(trade_data.get('event_ts_ms', 0))
            
            # 使用RealCVDCalculator核心组件（增加异常保护）
            if CVD_AVAILABLE and symbol in self.cvd_calculators:
                try:
                    result = self.cvd_calculators[symbol].update_with_trade(
                        price=price,
                        qty=qty,
                        is_buy=is_buy,
                        event_time_ms=event_ts_ms
                    )
                    if result:
                        meta = result.get('meta', {})
                        # 处理z_cvd为None的情况（warmup期间）
                        z_cvd_value = result.get('z_cvd')
                        if z_cvd_value is None:
                            z_cvd_value = 0.0  # warmup期间使用0.0
                        
                        # 保存核心组件的CVD值到缓存（用于备用计算时的状态同步）
                        cvd_cache = self.cvd_cache[symbol]
                        cvd_cache['last_core_cvd'] = result['cvd']
                        self.cvd_calc_mode[symbol] = 'core'  # 确保标记为core模式
                        
                        return {
                            'cvd': result['cvd'],
                            'delta': qty if is_buy else -qty,
                            'z_raw': result.get('z_raw', z_cvd_value),  # 修复：优先使用z_raw
                            'z_cvd': z_cvd_value,  # 使用处理后的值
                            'scale': 1.0,  # CVD结果中没有scale字段，使用固定值
                            'sigma_floor': 0.0,  # 核心组件内部处理
                            'floor_used': False,  # 核心组件内部处理
                            'warmup': meta.get('warmup', False),
                            'std_zero': meta.get('std_zero', False),
                            'bad_points': meta.get('bad_points', 0),
                            'ema_cvd': result.get('ema_cvd', 0.0),
                            'calc_mode': 'core'  # 新增：标记数据来源
                        }
                except Exception as e:
                    logger.error(f"CVD核心组件异常 {symbol}: {e.__class__.__name__}: {e}, 降级到备用计算")
                    # 继续执行备用计算逻辑
            
            # 备用简化计算（保持原有逻辑）
            delta = qty if is_buy else -qty
            
            # 更新CVD缓存（从last_core_cvd继续累积，避免跳跃）
            cache = self.cvd_cache[symbol]
            if self.cvd_calc_mode[symbol] == 'core':
                # 第一次切换到备用模式，从last_core_cvd初始化
                cache['cvd_cumulative'] = cache.get('last_core_cvd', 0.0)
                self.cvd_calc_mode[symbol] = 'fallback'
                logger.warning(f"CVD {symbol} 切换到备用计算，从 {cache['cvd_cumulative']:.2f} 继续累积")
            cache['cvd_cumulative'] += delta
            
            # 1) delta 入队时带时间戳
            cache.setdefault('delta_history_ts', deque(maxlen=4096))   # 新增：带时间戳的队列
            cache['delta_history_ts'].append((event_ts_ms, delta))
            
            # 2) 基于 WIN_SECS 做时间裁剪（按秒窗口，而非固定条数）
            cutoff = event_ts_ms - self.win_secs * 1000
            while cache['delta_history_ts'] and cache['delta_history_ts'][0][0] < cutoff:
                cache['delta_history_ts'].popleft()
            
            # 3) 计算统计量时转成 numpy 数组，避免 list 运算报错
            deltas = np.asarray([d for _, d in cache['delta_history_ts']], dtype=float)
            
            if deltas.size >= 10:
                rolling_mean = deltas.mean()
                rolling_std = deltas.std()
                median_delta = np.median(deltas)
                mad = np.median(np.abs(deltas - median_delta))
                robust_scale = 1.4826 * mad if mad > 0 else 1.0
                
                sigma_floor = self.cvd_sigma_floor_k * robust_scale
                denom = max(rolling_std, sigma_floor)
                z_raw = (delta - rolling_mean) / denom if denom > 0 else 0.0
                
                winsor_limit = self.cvd_winsor
                z_cvd = np.clip(z_raw, -winsor_limit, winsor_limit)
                floor_used = rolling_std < sigma_floor
                scale = robust_scale
            else:
                z_raw = (delta / 100.0) if delta != 0 else 0.0
                z_cvd = z_raw
                scale = 100.0
                sigma_floor = 0.0
                floor_used = False
            
            return {
                'cvd': cache['cvd_cumulative'],  # 累积CVD
                'delta': delta,  # 当前delta
                'z_raw': z_raw,
                'z_cvd': z_cvd,
                'scale': scale,
                'sigma_floor': sigma_floor,
                'floor_used': floor_used,
                'regime': 'normal',
                'calc_mode': 'fallback'  # 新增：标记使用备用计算
            }
        except Exception as e:
            logger.error(f"CVD计算错误 {symbol}: {e}")
            return None
    
    def _calculate_fusion(self, ofi_result: Dict, cvd_result: Dict, symbol: str = None, lag_sec: float = 0.0) -> Optional[Dict]:
        """计算融合指标（使用OFI_CVD_Fusion核心组件）"""
        try:
            if not ofi_result or not cvd_result:
                return None
            
            # 安全获取Z-score值，处理None情况
            ofi_z = ofi_result.get('ofi_z', 0)
            cvd_z = cvd_result.get('z_cvd', 0)
            
            # 如果任一值为None，则跳过融合计算
            if ofi_z is None or cvd_z is None:
                return None
            
            # 使用OFI_CVD_Fusion核心组件
            if FUSION_AVAILABLE and symbol and symbol in self.fusion_calculators:
                result = self.fusion_calculators[symbol].update(
                    z_ofi=ofi_z,
                    z_cvd=cvd_z,
                    ts=time.time(),
                    lag_sec=lag_sec
                )
                if result:
                    return {
                        'score': result['fusion_score'],
                        'score_raw': result['fusion_score'],
                        'proba': result.get('proba', 0.5),
                        'consistency': result.get('consistency', 0.0),
                        'dispersion': abs(ofi_z - cvd_z),  # 计算离散度
                        'sign_agree': int((ofi_z >= 0) == (cvd_z >= 0)),  # 符号一致性
                        'signal': result.get('signal', 'neutral'),
                        'components': result.get('components', {'ofi': 0.0, 'cvd': 0.0}),
                        'regime': 'normal',
                        'calibration_k': result.get('calibration_k', 1.0)
                    }
            
            # 备用简化计算（保持原有逻辑）
            w_ofi = self.w_ofi  # 默认0.6
            w_cvd = self.w_cvd  # 默认0.4
            fusion_raw = w_ofi * ofi_z + w_cvd * cvd_z
            
            # 轻量校准（Platt scaling）
            import math
            k = self.fusion_cal_k
            proba = 1 / (1 + math.exp(-k * fusion_raw))
            
            # 计算信号一致性（方向一致性）
            sign_agree = int((ofi_z >= 0) == (cvd_z >= 0))
            consistency = (min(abs(ofi_z), abs(cvd_z)) / max(abs(ofi_z), abs(cvd_z), 1e-8)) if sign_agree else 0.0
            dispersion = abs(ofi_z - cvd_z)  # 新增：离散度/分歧度
            
            # 基于概率的信号分类（移除gate）
            signal = 'neutral'
            if proba > 0.7:
                signal = 'strong_buy'
            elif proba > 0.6:
                signal = 'buy'
            elif proba < 0.3:
                signal = 'strong_sell'
            elif proba < 0.4:
                signal = 'sell'
            
            return {
                'score': fusion_raw,            # 原始堆分
                'score_raw': fusion_raw,        # 重命名为score_raw，避免误解
                'proba': proba,
                'consistency': consistency,
                'dispersion': dispersion,       # 新增
                'sign_agree': sign_agree,       # 新增
                'signal': signal,
                'components': {
                    'ofi': w_ofi * ofi_z,
                    'cvd': w_cvd * cvd_z
                },
                'regime': 'normal',
                'calibration_k': k
            }
        except Exception as e:
            logger.error(f"融合计算错误: {e}")
            return None
    
    def _detect_events(self, symbol: str, ofi_result: Dict, cvd_result: Dict, price: float, fusion_result: Dict = None) -> List[Dict]:
        """检测事件（使用DivergenceDetector核心组件）"""
        events = []
        
        try:
            if not ofi_result or not cvd_result:
                return events
            
            ofi_z = ofi_result.get('ofi_z', 0)
            cvd_z = cvd_result.get('z_cvd', 0)
            
            # 安全处理None值
            if ofi_z is None or cvd_z is None:
                return events
            
            # 使用DivergenceDetector核心组件
            if DIVERGENCE_AVAILABLE and symbol in self.divergence_detectors:
                fusion_score = fusion_result.get('score', 0.0) if fusion_result else None
                consistency = fusion_result.get('consistency', 0.0) if fusion_result else None
                
                divergence_event = self.divergence_detectors[symbol].update(
                    ts=time.time(),
                    price=price,
                    z_ofi=ofi_z,
                    z_cvd=cvd_z,
                    fusion_score=fusion_score,
                    consistency=consistency,
                    warmup=False,
                    lag_sec=0.0
                )
                
                if divergence_event:
                    events.append({
                        'event_type': divergence_event['type'],
                        'strength_score': divergence_event.get('score', 0.0),
                        'direction': 'bullish' if 'bull' in divergence_event['type'] else 'bearish' if 'bear' in divergence_event['type'] else 'neutral',
                        'trigger_by': 'divergence_detector',
                        'meta_json': json.dumps({
                            'ofi_z': ofi_z,
                            'cvd_z': cvd_z,
                            'price': price,
                            'channels': divergence_event.get('channels', []),
                            'reason_codes': divergence_event.get('reason_codes', []),
                            'pivots': divergence_event.get('pivots', {})
                        })
                    })
            
            # 备用简化检测（保持原有逻辑）
            # 检测OFI-CVD冲突（不一致信号）
            if abs(ofi_z) >= 2.0 and abs(cvd_z) >= 1.0:
                if (ofi_z > 0 and cvd_z < 0) or (ofi_z < 0 and cvd_z > 0):
                    events.append({
                        'event_type': 'ofi_cvd_conflict',
                        'trigger_by': 'ofi_cvd_conflict',
                        'meta_json': json.dumps({
                            'ofi_z': ofi_z,
                            'cvd_z': cvd_z,
                            'price': price,
                            'reason': 'opposite_signals'
                        })
                    })
            
            # 检测强背离信号（重命名为ofi_cvd_divergence）
            if abs(ofi_z) > 2.5 and abs(cvd_z) > 2.5:
                if (ofi_z > 0 and cvd_z < 0) or (ofi_z < 0 and cvd_z > 0):
                    strength_score = (abs(ofi_z) + abs(cvd_z)) / 2
                    direction = 'bullish' if ofi_z > 0 and cvd_z < 0 else 'bearish'
                    events.append({
                        'event_type': 'ofi_cvd_divergence',
                        'strength_score': strength_score,
                        'direction': direction,
                        'trigger_by': 'ofi_cvd_divergence',
                        'meta_json': json.dumps({
                            'ofi_z': ofi_z,
                            'cvd_z': cvd_z,
                            'price': price,
                            'strength': 'strong'
                        })
                    })
            
            # 检测异常波动（对齐CVD截断阈值）
            if abs(ofi_z) > 3.0 or abs(cvd_z) > 2.5:
                trigger_by = 'ofi' if abs(ofi_z) > 3.0 else 'cvd' if abs(cvd_z) > 2.5 else 'both'
                events.append({
                    'event_type': 'anomaly',
                    'trigger_by': trigger_by,
                    'meta_json': json.dumps({
                        'ofi_z': ofi_z,
                        'cvd_z': cvd_z,
                        'price': price,
                        'threshold_exceeded': 'z_score'
                    })
                })
            
            # 检测价格异常（基于价格变化）
            if hasattr(self, '_last_prices'):
                if symbol in self._last_prices:
                    price_change = abs(price - self._last_prices[symbol]) / self._last_prices[symbol]
                    if price_change > 0.05:  # 5%以上价格变化
                        events.append({
                            'event_type': 'price_anomaly',
                            'trigger_by': 'price_change',
                            'meta_json': json.dumps({
                                'price': price,
                                'last_price': self._last_prices[symbol],
                                'change_pct': price_change * 100
                            })
                        })
                self._last_prices[symbol] = price
            else:
                self._last_prices = {symbol: price}
            
        except Exception as e:
            logger.error(f"事件检测错误: {e}")
        
        return events
    
    async def _process_trade_data(self, symbol: str, trade_data: Dict):
        """处理交易数据"""
        try:
            # 更新数据接收时间
            self._update_data_time(symbol)
            # 补丁B：更新交易流时间戳
            self.last_trade_time[symbol] = self._mono()
            
            # 统一时间戳处理：区分事件时间和接收时间
            now = datetime.now()
            recv_ts_ms = int(now.timestamp() * 1000)  # 接收时间
            
            # 事件时间优先使用trade_data中的event_ts_ms字段，否则使用接收时间
            event_ts_ms = int(trade_data.get('event_ts_ms', recv_ts_ms))  # 事件时间
            price = float(trade_data.get('price', 0))
            
            # 去重检查
            trade_id = trade_data.get('trade_id', 0)
            if symbol not in self.dedup_cache:
                self.dedup_cache[symbol] = OrderedDict()
            
            if trade_id in self.dedup_cache[symbol]:
                return  # 跳过重复数据
            
            # 添加到去重缓存（FIFO）
            self.dedup_cache[symbol][trade_id] = None
            
            # LRU清理：如果缓存过大，删除最老的数据
            if len(self.dedup_cache[symbol]) > self.dedup_lru_size:
                self.dedup_cache[symbol].popitem(last=False)  # pop oldest
                self.queue_dropped += 1  # 增加队列丢弃计数
                
                # LRU逐出计数监控：当从0→非零或增长超过阈值时告警
                if self.queue_dropped > self.last_queue_dropped:
                    if self.last_queue_dropped == 0:
                        logger.warning(f"[DEDUP] {symbol} 开始LRU逐出旧key，当前逐出计数: {self.queue_dropped}")
                    elif (self.queue_dropped - self.last_queue_dropped) >= self.queue_drop_threshold:
                        logger.warning(f"[DEDUP] {symbol} LRU逐出计数快速增长: {self.last_queue_dropped} → {self.queue_dropped}")
                    self.last_queue_dropped = self.queue_dropped
            
            # 计算2×2场景标签
            scenario_labels = self._calculate_scenario_labels(symbol, price, event_ts_ms)
            
            # 1. 保存价格数据
            latency_ms = max(0, recv_ts_ms - event_ts_ms)  # 确保延迟非负
            
            # 获取最近的订单簿快照，计算成交可得价
            best_buy_fill = price  # 默认使用成交价
            best_sell_fill = price  # 默认使用成交价
            
            if symbol in self.orderbooks and self.orderbooks[symbol]:
                ob = self.orderbooks[symbol]
                if ob.get('asks') and ob['asks'][0]:
                    best_buy_fill = ob['asks'][0][0]  # 买入用ask价
                if ob.get('bids') and ob['bids'][0]:
                    best_sell_fill = ob['bids'][0][0]  # 卖出用bid价
            
            price_data = {
                'ts_ms': event_ts_ms,  # 使用事件时间戳
                'recv_ts_ms': recv_ts_ms,  # 接收时间戳
                'symbol': symbol,
                'price': price,
                'qty': float(trade_data.get('qty', 0)),
                # 新增：把方向一并落盘，供离线重算CVD使用
                'is_buyer_maker': bool(trade_data.get('is_buyer_maker', False)),
                'agg_trade_id': trade_data.get('trade_id', 0),  # 现在正确使用agg_trade_id
                'latency_ms': latency_ms,
                'recv_rate_tps': self.scene_cache[symbol]['current_tps'],  # 实时TPS
                'row_id': stable_row_id(f"{symbol}|{trade_data.get('trade_id', 0)}|price"),  # 使用agg_trade_id确保唯一性
                # 新增成交可得价字段（用于回测撮合）
                'best_buy_fill': best_buy_fill,  # 买入可得价
                'best_sell_fill': best_sell_fill,  # 卖出可得价
                # 新增性能监控字段
                'reconnect_count': self.reconnect_count,  # 重连计数
                'queue_dropped': self.queue_dropped,  # 队列丢弃计数
                # 新增2×2场景标签字段
                'session': scenario_labels['session'],
                'regime': scenario_labels['regime'],
                'vol_bucket': scenario_labels['vol_bucket'],
                'scenario_2x2': scenario_labels['scenario_2x2'],
                'fee_tier': scenario_labels['fee_tier']
            }
            self.data_buffers['prices'][symbol].append(price_data)
            await self._maybe_flush_on_pressure(symbol, 'prices')
            
            # 2. 计算OFI（使用时间对齐的订单簿快照）
            ofi_result = None
            ofi_ts_ms = event_ts_ms  # 默认使用交易时间
            lag_ms_to_trade = 0
            alignment_source = 'none'  # 'strict', 'fallback', 'none'
            
            # 使用配置的OFI最大滞后（已在构造函数中从配置读取）
            max_lag_ms = getattr(self, "ofi_max_lag_ms", 800)
            
            # 选择最接近交易时间的订单簿快照
            ob_snapshot = self._pick_orderbook_snapshot(symbol, event_ts_ms, max_lag_ms=max_lag_ms)
            
            # 如果找不到合格快照，回退使用最近订单簿（保证of/fusion/events不中断）
            if not ob_snapshot and self.orderbooks.get(symbol):
                last_ob = self.orderbooks[symbol]
                ob_snapshot = {
                    'bids': last_ob.get('bids', []),
                    'asks': last_ob.get('asks', []),
                    'ts_ms': last_ob.get('event_ts_ms', event_ts_ms),
                    'last_id': last_ob.get('last_id'),
                }
                alignment_source = 'fallback'
            elif ob_snapshot:
                alignment_source = 'strict'
            
            if ob_snapshot:
                ofi_result = self._calculate_ofi(symbol, {
                    'bids': ob_snapshot['bids'],
                    'asks': ob_snapshot['asks'],
                    'event_ts_ms': ob_snapshot['ts_ms']
                })
                if ofi_result:
                    ofi_ts_ms = ob_snapshot['ts_ms']  # 使用订单簿时间
                    lag_ms_to_trade = max(0, event_ts_ms - ob_snapshot['ts_ms'])
                    
                    ofi_data = {
                        'ts_ms': ofi_ts_ms,  # 使用订单簿时间戳
                        'recv_ts_ms': recv_ts_ms,  # 接收时间戳
                        'symbol': symbol,
                        'ofi_value': ofi_result['ofi_value'],
                        'ofi_z': ofi_result['ofi_z'],
                        'scale': ofi_result.get('scale', 1.0),  # 统一scale语义，默认1.0
                        'row_id': stable_row_id(f"{symbol}|{ofi_ts_ms}|ofi|{ob_snapshot.get('last_id','na')}"),  # 混入last_id增强去重
                        'regime': scenario_labels['regime'],  # 使用scenario labels的regime
                        # 新增时间对齐信息
                        'lag_ms_to_trade': lag_ms_to_trade,  # 订单簿到交易的滞后
                        'alignment': alignment_source,  # 对齐来源：strict/fallback/none
                        # 新增性能监控字段
                        'latency_ms': latency_ms,  # 处理延迟
                        'reconnect_count': self.reconnect_count,  # 重连计数
                        'queue_dropped': self.queue_dropped,  # 队列丢弃计数
                        # 新增RealOFICalculator meta信息
                        'warmup': ofi_result.get('warmup', False),
                        'std_zero': ofi_result.get('std_zero', False),
                        'session_reset': ofi_result.get('session_reset', False),
                        'bad_points': ofi_result.get('bad_points', 0),
                        'ema_ofi': ofi_result.get('ema_ofi', 0.0),
                        # 新增2×2场景标签字段
                        'session': scenario_labels['session'],
                        'vol_bucket': scenario_labels['vol_bucket'],
                        'scenario_2x2': scenario_labels['scenario_2x2'],
                        'fee_tier': scenario_labels['fee_tier']
                    }
                    self.data_buffers['ofi'][symbol].append(ofi_data)
                    await self._maybe_flush_on_pressure(symbol, 'ofi')
                    self.stats['total_ofi'][symbol] += 1
            
            # 3. 计算CVD
            cvd_result = self._calculate_cvd(symbol, trade_data)
            if cvd_result:
                cvd_data = {
                    'ts_ms': event_ts_ms,  # 使用事件时间戳
                    'recv_ts_ms': recv_ts_ms,  # 接收时间戳
                    'symbol': symbol,
                    'cvd': cvd_result['cvd'],
                    'delta': cvd_result['delta'],
                    'z_raw': cvd_result['z_raw'],
                    'z_cvd': cvd_result['z_cvd'],
                    'scale': cvd_result['scale'],
                    'sigma_floor': cvd_result['sigma_floor'],
                    'floor_used': cvd_result['floor_used'],
                    'row_id': stable_row_id(f"{symbol}|{event_ts_ms}|cvd|{trade_id}"),  # 加入trade_id确保唯一性
                    'regime': scenario_labels['regime'],  # 使用scenario labels的regime
                    # 新增性能监控字段
                    'latency_ms': latency_ms,  # 处理延迟
                    'reconnect_count': self.reconnect_count,  # 重连计数
                    'queue_dropped': self.queue_dropped,  # 队列丢弃计数
                    # 新增2×2场景标签字段
                    'session': scenario_labels['session'],
                    'vol_bucket': scenario_labels['vol_bucket'],
                    'scenario_2x2': scenario_labels['scenario_2x2'],
                    'fee_tier': scenario_labels['fee_tier']
                }
                self.data_buffers['cvd'][symbol].append(cvd_data)
                await self._maybe_flush_on_pressure(symbol, 'cvd')
                self.stats['total_cvd'][symbol] += 1
            
            # 4. 计算融合指标
            # 将OFI对齐到成交的滞后（毫秒）换算为秒传给FUSION
            real_lag_sec = (lag_ms_to_trade / 1000.0) if ofi_result else 0.0
            fusion_result = self._calculate_fusion(ofi_result, cvd_result, symbol, real_lag_sec)
            if fusion_result:
                # 时间对齐：融合使用OFI和交易时间的最大值
                fusion_ts_ms = max(event_ts_ms, ofi_ts_ms) if ofi_result else event_ts_ms
                
                # 扁平化components字段
                components = fusion_result.get('components', {})
                fusion_data = {
                    'ts_ms': fusion_ts_ms,  # 使用对齐后的时间戳
                    'recv_ts_ms': recv_ts_ms,  # 接收时间戳
                    'symbol': symbol,
                    'score': fusion_result['score'],
                    'score_raw': fusion_result['score_raw'],
                    'row_id': stable_row_id(f"{symbol}|{fusion_ts_ms}|fusion|{trade_id}"),  # 混入trade_id增强去重
                    'regime': scenario_labels['regime'],  # 使用scenario labels的regime
                    # 新增时间对齐信息
                    'lag_ms_ob': max(0, fusion_ts_ms - ofi_ts_ms) if ofi_result else 0,  # OFI滞后
                    'lag_ms_trade': max(0, fusion_ts_ms - event_ts_ms),  # 交易滞后
                    # 新增性能监控字段
                    'latency_ms': latency_ms,  # 处理延迟
                    'reconnect_count': self.reconnect_count,  # 重连计数
                    'queue_dropped': self.queue_dropped,  # 队列丢弃计数
                    # 新增2×2场景标签字段
                    'session': scenario_labels['session'],
                    'vol_bucket': scenario_labels['vol_bucket'],
                    'scenario_2x2': scenario_labels['scenario_2x2'],
                    'fee_tier': scenario_labels['fee_tier'],
                    # 新增融合关键信息
                    'proba': fusion_result.get('proba', 0.5),
                    'consistency': fusion_result.get('consistency', 0.0),
                    'dispersion': fusion_result.get('dispersion', 0.0),  # 新增离散度
                    'sign_agree': fusion_result.get('sign_agree', 1),  # 新增符号一致性
                    'signal': fusion_result.get('signal', 'neutral'),
                    'comp_ofi': components.get('ofi', 0.0),  # 扁平化components
                    'comp_cvd': components.get('cvd', 0.0),  # 扁平化components
                    'components_json': json.dumps(components),  # 保留JSON格式
                    'calibration_k': fusion_result.get('calibration_k', 1.0)
                }
                self.data_buffers['fusion'][symbol].append(fusion_data)
                await self._maybe_flush_on_pressure(symbol, 'fusion')
            
            # 5. 检测事件
            events = self._detect_events(symbol, ofi_result, cvd_result, float(trade_data.get('price', 0)), fusion_result)
            for event in events:
                # 事件使用融合时间（与融合保持一致）
                event_ts_ms_final = fusion_ts_ms if fusion_result else event_ts_ms
                
                event_data = {
                    'ts_ms': event_ts_ms_final,  # 使用对齐后的时间戳
                    'recv_ts_ms': recv_ts_ms,  # 接收时间戳
                    'symbol': symbol,
                    'event_type': event['event_type'],
                    'meta_json': event['meta_json'],
                    'row_id': stable_row_id(f"{symbol}|{event_ts_ms_final}|{event['event_type']}|{trade_id}"),  # 混入trade_id增强去重
                    # 事件命名更明确 & 列扁平
                    'ofi_z': ofi_result.get('ofi_z') if ofi_result else None,
                    'cvd_z': cvd_result.get('z_cvd') if cvd_result else None,
                    'strength_score': event.get('strength_score', 0.0),
                    'direction': event.get('direction', 'neutral'),
                    # 新增时间对齐信息
                    'lag_ms_ob': max(0, event_ts_ms_final - ofi_ts_ms) if ofi_result else 0,  # OFI滞后
                    'lag_ms_trade': max(0, event_ts_ms_final - event_ts_ms),  # 交易滞后
                    # 新增触发因子信息
                    'trigger_by': event.get('trigger_by', 'unknown'),  # 触发因子
                    # 新增性能监控字段
                    'latency_ms': latency_ms,  # 处理延迟
                    'reconnect_count': self.reconnect_count,  # 重连计数
                    'queue_dropped': self.queue_dropped,  # 队列丢弃计数
                    # 新增2×2场景标签字段
                    'session': scenario_labels['session'],
                    'regime': scenario_labels['regime'],
                    'vol_bucket': scenario_labels['vol_bucket'],
                    'scenario_2x2': scenario_labels['scenario_2x2'],
                    'fee_tier': scenario_labels['fee_tier']
                }
                self.data_buffers['events'][symbol].append(event_data)
                self.stats['total_events'][symbol] += 1
            
            self.stats['total_trades'][symbol] += 1
            
            # 发布实时特征到core_algo_paper（空值兜底）
            if _env("PAPER_ENABLE", "0") == "1" and hasattr(self, "paper") and self.paper:
                await self.paper.on_feature({
                    "symbol": symbol,
                    "ts_ms": event_ts_ms,
                    "price": price,
                    "ofi_z": ofi_result and ofi_result.get("ofi_z") or 0.0,  # 空值兜底
                    "cvd_z": cvd_result and cvd_result.get("z_cvd") or 0.0,  # 空值兜底
                    "fusion_z": fusion_result and fusion_result.get("score") or 0.0,  # 修复：使用score而不是score_z
                    "scenario": scenario_labels["scenario_2x2"]
                })
            
        except Exception as e:
            logger.error(f"处理交易数据错误 {symbol}: {e}")
    
    async def _process_orderbook_data(self, symbol: str, orderbook_data: Dict):
        """处理订单簿数据"""
        try:
            # 更新数据接收时间
            self._update_data_time(symbol)
            # 补丁B：更新订单簿流时间戳
            self.last_ob_time[symbol] = self._mono()
            
            if 'bids' in orderbook_data and 'asks' in orderbook_data:
                # 在更新内存前先取前一份快照，计算OFI原语
                prev = self.orderbooks.get(symbol)
                curr = orderbook_data
                
                # 计算一级~五级的数量变化（原语）
                def delta_levels(prev_side, curr_side):
                    deltas = []
                    for i in range(5):
                        pv = prev_side[i][1] if prev_side and len(prev_side) > i else 0.0
                        cv = curr_side[i][1] if curr_side and len(curr_side) > i else 0.0
                        deltas.append(cv - pv)
                    return deltas
                
                d_b = delta_levels(prev.get('bids') if prev else None, curr['bids'])
                d_a = delta_levels(prev.get('asks') if prev else None, curr['asks'])
                
                # 更新内存缓存
                self.orderbooks[symbol] = orderbook_data
                
                # 保存订单簿快照到队列（用于时间对齐）
                event_ts_ms = int(orderbook_data.get('event_ts_ms', 0))
                self.orderbook_buf[symbol].append({
                    'ts_ms': event_ts_ms,
                    'bids': orderbook_data['bids'],
                    'asks': orderbook_data['asks'],
                    'last_id': orderbook_data.get('last_id'),
                    'first_id': orderbook_data.get('first_id'),
                    'prev_last_id': orderbook_data.get('prev_last_id'),
                })
                
                # 计算扁平化字段
                bb = orderbook_data['bids'][0][0] if orderbook_data['bids'] and orderbook_data['bids'][0] else 0.0
                ba = orderbook_data['asks'][0][0] if orderbook_data['asks'] and orderbook_data['asks'][0] else 0.0
                mid = (bb + ba) / 2 if (bb > 0 and ba > 0) else 0.0
                spread_bps = (ba - bb) / mid * 1e4 if mid > 0 else 0.0
                
                # 提取Top5档位扁平化字段（避免保存时json.loads）
                bid_levels = [0.0, 0.0] * 5  # [bid1_p, bid1_q, bid2_p, bid2_q, ...]
                ask_levels = [0.0, 0.0] * 5  # [ask1_p, ask1_q, ask2_p, ask2_q, ...]
                
                for i in range(5):
                    if i < len(orderbook_data['bids']):
                        bid_levels[i*2] = float(orderbook_data['bids'][i][0])  # price
                        bid_levels[i*2+1] = float(orderbook_data['bids'][i][1])  # qty
                    if i < len(orderbook_data['asks']):
                        ask_levels[i*2] = float(orderbook_data['asks'][i][0])  # price
                        ask_levels[i*2+1] = float(orderbook_data['asks'][i][1])  # qty
                
                # 保存订单簿数据到缓冲区
                now = datetime.now()
                recv_ts_ms = int(now.timestamp() * 1000)
                latency_ms = max(0, recv_ts_ms - event_ts_ms)
                
                orderbook_record = {
                    'ts_ms': event_ts_ms,  # 事件时间戳
                    'recv_ts_ms': recv_ts_ms,  # 接收时间戳
                    'latency_ms': latency_ms,  # 延迟
                    'symbol': symbol,
                    'row_id': stable_row_id(f"{symbol}|{event_ts_ms}|orderbook|{orderbook_data.get('last_id','na')}"),  # 混入last_id增强唯一性
                    'bids': orderbook_data['bids'],  # 保存原始bids数据
                    'asks': orderbook_data['asks'],  # 保存原始asks数据
                    'bids_json': json.dumps(orderbook_data['bids']),  # JSON格式便于查询
                    'asks_json': json.dumps(orderbook_data['asks']),  # JSON格式便于查询
                    'levels': min(len(orderbook_data['bids']), len(orderbook_data['asks'])),  # 有效价差范围内的匹配深度
                    # date字段由_save_data统一生成（UTC），避免时区混淆
                    # 新增扁平化字段（用于回测撮合）
                    'best_bid': bb,
                    'best_ask': ba,
                    'mid': mid,
                    'spread_bps': spread_bps,
                    # 新增性能监控字段
                    'reconnect_count': self.reconnect_count,  # 重连计数
                    'queue_dropped': self.queue_dropped,  # 队列丢弃计数
                    # 回放序列字段
                    'first_id': orderbook_data.get('first_id'),
                    'last_id': orderbook_data.get('last_id'),
                    'prev_last_id': orderbook_data.get('prev_last_id'),
                    # OFI 原语（聚合 + 扁平）
                    'd_bid_qty_agg': float(sum(x for x in d_b if x is not None)),
                    'd_ask_qty_agg': float(sum(x for x in d_a if x is not None)),
                    # 可选：逐档（便于审计/回放）
                    'd_b0': d_b[0], 'd_b1': d_b[1], 'd_b2': d_b[2], 'd_b3': d_b[3], 'd_b4': d_b[4],
                    'd_a0': d_a[0], 'd_a1': d_a[1], 'd_a2': d_a[2], 'd_a3': d_a[3], 'd_a4': d_a[4],
                    # Top5档位扁平化字段（避免保存时json.loads）
                    'bid1_p': bid_levels[0], 'bid1_q': bid_levels[1],
                    'bid2_p': bid_levels[2], 'bid2_q': bid_levels[3],
                    'bid3_p': bid_levels[4], 'bid3_q': bid_levels[5],
                    'bid4_p': bid_levels[6], 'bid4_q': bid_levels[7],
                    'bid5_p': bid_levels[8], 'bid5_q': bid_levels[9],
                    'ask1_p': ask_levels[0], 'ask1_q': ask_levels[1],
                    'ask2_p': ask_levels[2], 'ask2_q': ask_levels[3],
                    'ask3_p': ask_levels[4], 'ask3_q': ask_levels[5],
                    'ask4_p': ask_levels[6], 'ask4_q': ask_levels[7],
                    'ask5_p': ask_levels[8], 'ask5_q': ask_levels[9],
                }
                
                self.data_buffers['orderbook'][symbol].append(orderbook_record)
                await self._maybe_flush_on_pressure(symbol, 'orderbook')
                self.stats['total_orderbook'][symbol] += 1  # 增加订单簿统计计数
                
        except Exception as e:
            logger.error(f"处理订单簿数据错误 {symbol}: {e}")
    
    async def _save_data(self, symbol: str, kind: str):
        """保存数据到Parquet文件"""
        # 原子快照：交换式取走缓冲，避免并发修改
        buf, self.data_buffers[kind][symbol] = self.data_buffers[kind][symbol], []
        if not buf:
            return
        
        try:
            # 创建DataFrame
            df = pd.DataFrame(buf)
            
            # 数据清洗：统一NaN/inf处理与类型锚定
            df = df.replace([np.inf, -np.inf], np.nan)
            
            # 数值列类型锚定（补充更多可能出现的数值列）
            numeric_columns = ['ofi_z', 'z_raw', 'z_cvd', 'score', 'proba', 'consistency', 
                              'dispersion', 'price', 'qty', 'latency_ms', 'best_buy_fill', 
                              'best_sell_fill', 'best_bid', 'best_ask', 'mid', 'spread_bps',
                              'd_bid_qty_agg', 'd_ask_qty_agg', 'd_b0', 'd_b1', 'd_b2', 'd_b3', 'd_b4',
                              'd_a0', 'd_a1', 'd_a2', 'd_a3', 'd_a4', 'ofi_value', 'ema_ofi', 
                              'ema_cvd', 'cvd', 'delta', 'return_1s', 'lag_ms_ofi', 'lag_ms_cvd', 
                              'lag_ms_fusion', 'score_raw', 'lag_ms_ob', 'lag_ms_trade',
                              # 新增orderbook扁平化字段
                              'bid1_p', 'bid1_q', 'bid2_p', 'bid2_q', 'bid3_p', 'bid3_q', 'bid4_p', 'bid4_q', 'bid5_p', 'bid5_q',
                              'ask1_p', 'ask1_q', 'ask2_p', 'ask2_q', 'ask3_p', 'ask3_q', 'ask4_p', 'ask4_q', 'ask5_p', 'ask5_q']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 序列字段类型加固（避免类型漂移）- 使用可空Int64
            for col in ['first_id','last_id','prev_last_id','agg_trade_id','trade_id']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-1).astype('Int64')  # 可空整数类型
            
            # 布尔字段类型锚定
            for col in ['is_buyer_maker']:
                if col in df.columns:
                    df[col] = df[col].astype('boolean')
            
            # 按事件时间分区，避免跨日错桶（使用UTC时间确保一致性）
            df['date'] = pd.to_datetime(df['ts_ms'], unit='ms', utc=True).dt.strftime('%Y-%m-%d')
            df['hour'] = pd.to_datetime(df['ts_ms'], unit='ms', utc=True).dt.strftime('%H')  # 新增小时分区
            
            # 路由输出路径，并打上 source_tier
            df['source_tier'] = 'preview' if kind in self.preview_kinds else 'raw'
            base_dir = self.preview_dir if kind in self.preview_kinds else self.output_dir
            
            # 按日期+小时分组保存
            for (date_str, hour_str), time_group in df.groupby(['date', 'hour']):
                # raw 仓剔除策略/监控列（避免把参数相关字段写死进权威库）
                if kind == 'prices':
                    time_group = time_group.drop(
                        columns=['session','regime','vol_bucket','scenario_2x2','fee_tier','recv_rate_tps'],
                        errors='ignore'
                    )
                
                # 修复orderbook复杂列导致的Parquet写入失败，扁平化字段已在process阶段生成
                if kind == 'orderbook':
                    # 删除复杂列，保留扁平化字段
                    time_group = time_group.drop(columns=['bids','asks','bids_json','asks_json'], errors='ignore')
                
                # 文件大小控制：如果超过最大行数，分批保存
                if len(time_group) > self.max_rows_per_file:
                    # 分批保存
                    for i in range(0, len(time_group), self.max_rows_per_file):
                        batch = time_group.iloc[i:i+self.max_rows_per_file]
                        filename = f"part-{time.time_ns()}-{uuid.uuid4().hex[:6]}-batch{i//self.max_rows_per_file}.parquet"
                        filepath = base_dir / f"date={date_str}" / f"hour={hour_str}" / f"symbol={symbol}" / f"kind={kind}" / filename
                        filepath.parent.mkdir(parents=True, exist_ok=True)
                        batch.to_parquet(filepath, compression='snappy', index=False)
                        logger.info(f"保存数据: {symbol}-{kind} date={date_str} hour={hour_str} rows={len(batch)} → {filepath}")
                        
                        # 更新每小时写盘行数统计
                        self.hourly_write_counts[kind] += len(batch)
                else:
                    # 单文件保存
                    filename = f"part-{time.time_ns()}-{uuid.uuid4().hex[:6]}.parquet"
                    filepath = base_dir / f"date={date_str}" / f"hour={hour_str}" / f"symbol={symbol}" / f"kind={kind}" / filename
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    time_group.to_parquet(filepath, compression='snappy', index=False)
                    logger.info(f"保存数据: {symbol}-{kind} date={date_str} hour={hour_str} rows={len(time_group)} → {filepath}")
                    
                    # 更新每小时写盘行数统计
                    self.hourly_write_counts[kind] += len(time_group)
            
        except Exception as e:
            logger.error(f"保存数据错误 {symbol}-{kind}: {e.__class__.__name__}: {e}")
            # 不再回灌到内存，改为死信落地，避免失败→回灌→再失败死循环
            self._spill_to_deadletter(symbol, kind, buf)
    
    def _check_extreme_traffic(self):
        """检查是否进入极端流量模式"""
        try:
            # 检查所有symbol的prices缓冲区大小
            max_prices_buffer = max(len(self.data_buffers['prices'][symbol]) for symbol in self.symbols)
            
            if max_prices_buffer >= self.extreme_traffic_threshold and not self.extreme_traffic_mode:
                self.extreme_traffic_mode = True
                self.parquet_rotate_sec = self.extreme_rotate_sec
                logger.warning(f"[EXTREME_TRAFFIC] 进入极端流量模式: max_prices_buffer={max_prices_buffer}, "
                             f"轮转间隔调整为{self.extreme_rotate_sec}秒")
            elif max_prices_buffer < self.extreme_traffic_threshold * 0.7 and self.extreme_traffic_mode:
                self.extreme_traffic_mode = False
                self.parquet_rotate_sec = self.normal_rotate_sec
                logger.info(f"[EXTREME_TRAFFIC] 退出极端流量模式: max_prices_buffer={max_prices_buffer}, "
                           f"轮转间隔恢复为{self.normal_rotate_sec}秒")
        except Exception as e:
            logger.error(f"检查极端流量模式错误: {e}")

    async def _check_and_rotate_data(self):
        """检查是否需要轮转数据（按时间切分，并发安全）"""
        # 检查极端流量模式
        self._check_extreme_traffic()
        
        current_time = self._mono()
        if current_time - self.last_rotate_time >= self.parquet_rotate_sec:
            tasks = []
            async with self.rotation_lock:
                # 双重检查，避免重复轮转；只在锁内更新时间并收集任务，写盘放到锁外
                if current_time - self.last_rotate_time >= self.parquet_rotate_sec:
                    mode_str = "EXTREME" if self.extreme_traffic_mode else "NORMAL"
                    logger.info(f"执行定时轮转: {current_time - self.last_rotate_time:.1f}秒 (模式: {mode_str})")
                    
                    # 补丁增强：轮转时输出关键统计指标
                    # 全局LRU逐出增量（循环外计算一次，避免重复计算）
                    queue_dropped_delta = self.queue_dropped - getattr(self, 'last_rotate_queue_dropped', 0)
                    
                    for symbol in self.symbols:
                        trade_delta_s = current_time - self.last_trade_time[symbol]
                        ob_delta_s = current_time - self.last_ob_time[symbol]
                        buffer_sizes = {kind: len(self.data_buffers[kind][symbol]) for kind in self.data_buffers}
                        
                        # 智能日志级别：正常情况DEBUG，异常情况INFO/WARN
                        has_anomaly = (queue_dropped_delta > 0 or 
                                     trade_delta_s > self.trade_timeout * 0.8 or 
                                     ob_delta_s > self.orderbook_timeout * 0.8 or
                                     self.reconnect_count > 0 or
                                     getattr(self, 'substream_timeout_detected', False))
                        
                        log_level = logger.warning if has_anomaly else logger.debug
                        log_level(f"[ROTATE] {symbol}: trade_delta={trade_delta_s:.1f}s, ob_delta={ob_delta_s:.1f}s, "
                                f"buffers={buffer_sizes}, reconnect_count={self.reconnect_count}, mode={mode_str}, "
                                f"lru_evict_delta={queue_dropped_delta}")
                    
                    # 记录本轮轮转的queue_dropped计数
                    self.last_rotate_queue_dropped = self.queue_dropped
                    
                    # 增量丢弃连续告警
                    if queue_dropped_delta > 0:
                        self.consecutive_drop_rounds += 1
                        if self.consecutive_drop_rounds >= 2:
                            # 收集当前缓冲区快照便于排障
                            buffer_snapshot = {}
                            for symbol in self.symbols:
                                buffer_snapshot[symbol] = {kind: len(self.data_buffers[kind][symbol]) for kind in self.data_buffers}
                            logger.warning(f"[DEDUP_WARNING] 连续{self.consecutive_drop_rounds}轮发生LRU逐出（delta={queue_dropped_delta}），可能存在重复流/重放源，缓冲区快照: {buffer_snapshot}")
                    else:
                        self.consecutive_drop_rounds = 0  # 重置连续计数
                    
                    # 先生成特征（不持锁，避免阻塞；此处仅用当前缓冲的尾部数据）
                    for symbol in self.symbols:
                        # 特征生成日志降噪：只在异常时输出INFO
                        has_anomaly = (queue_dropped_delta > 0 or 
                                     getattr(self, 'substream_timeout_detected', False) or
                                     self.reconnect_count > 0)
                        if has_anomaly:
                            logger.info(f"[FEATURES_GEN] {symbol} 生成特征表（异常状态）")
                        else:
                            logger.debug(f"[FEATURES_GEN] {symbol} 生成特征表")
                        self._generate_features_table(symbol)
                        # 权威库
                        for kind in ['prices', 'orderbook']:
                            if self.data_buffers[kind][symbol]:
                                tasks.append(self._save_data(symbol, kind))
                        # 预览库
                        for kind in self.preview_kinds:
                            if self.data_buffers[kind][symbol]:
                                tasks.append(self._save_data(symbol, kind))
                    self.last_rotate_time = current_time
            # 锁外并发落盘（优化：每个任务内部各自获取信号量，提高并行度）
            if tasks:
                # 为每个任务包装信号量，实现真正的并发保存
                async def save_with_semaphore(task):
                    async with self.save_semaphore:
                        return await task
                
                wrapped_tasks = [save_with_semaphore(task) for task in tasks]
                await asyncio.gather(*wrapped_tasks, return_exceptions=True)
    
    async def _generate_slices_manifest(self):
        """生成slices_manifest报告（并发安全）"""
        current_time = self._mono()
        if current_time - self.last_manifest_time >= 3600:  # 每小时生成一次
            async with self.rotation_lock:
                # 双重检查，避免重复生成
                if current_time - self.last_manifest_time >= 3600:
                    logger.info("生成slices_manifest报告")
                    
                    # 统计场景覆盖情况
                    manifest_data = {
                        'timestamp': datetime.utcnow().isoformat(),
                        'symbols': {},
                        'scene_coverage_miss': 0,
                        'hour_stats': {
                            'prices_rows': sum(len(self.data_buffers['prices'][s]) for s in self.symbols),
                            'orderbook_rows': sum(len(self.data_buffers['orderbook'][s]) for s in self.symbols),
                            'reconnect_count': self.reconnect_count,
                            'queue_dropped': self.queue_dropped,
                            'substream_timeout_detected': self.substream_timeout_detected,
                            'hourly_write_counts': self.hourly_write_counts.copy()  # 本小时写盘行数
                        }
                    }
                    
                    # 检查每个symbol的场景覆盖（使用累计统计）
                    for symbol in self.symbols:
                        coverage_counts = self.scene_coverage_stats[symbol]
                        symbol_stats = {
                            'scenario_2x2': coverage_counts.copy(),  # 使用累计统计
                            'total_samples': sum(coverage_counts.values()),
                            'coverage_ratio': {}
                        }
                        
                        # 计算覆盖比例
                        total = sum(coverage_counts.values())
                        if total > 0:
                            for scenario, count in coverage_counts.items():
                                symbol_stats['coverage_ratio'][scenario] = count / total
                        
                        manifest_data['symbols'][symbol] = symbol_stats
                        
                        # 检查场景覆盖阈值
                        for scenario in ['A_H', 'A_L', 'Q_H', 'Q_L']:
                            if coverage_counts[scenario] == 0:
                                manifest_data['scene_coverage_miss'] = 1
                                logger.warning(f"场景覆盖不足: {symbol} 缺少 {scenario} (total_samples={total})")
                        
                        logger.info(f"{symbol} 场景覆盖统计: {coverage_counts} (total_samples={total})")
                    
                    # 保存manifest文件（使用固定的artifacts目录）
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H")
                    manifest_file = self.artifacts_dir / "dq_reports" / f"slices_manifest_{timestamp}.json"
                    manifest_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(manifest_file, 'w', encoding='utf-8') as f:
                        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"slices_manifest已保存: {manifest_file}")
                    
                    # 重置场景统计（准备下一轮）
                    for symbol in self.symbols:
                        self.scene_coverage_stats[symbol] = {
                            'A_H': 0, 'A_L': 0, 'Q_H': 0, 'Q_L': 0
                        }
                    
                    # 重置子流超时标志
                    self.substream_timeout_detected = False
                    
                    # 重置每小时写盘行数统计
                    self.hourly_write_counts = {kind: 0 for kind in ['prices', 'orderbook', 'ofi', 'cvd', 'fusion', 'events', 'features']}
                    
                    # 更新manifest时间
                    self.last_manifest_time = current_time
    
    async def connect_unified_streams(self):
        """连接统一的多流WebSocket（优化连接数）+ 自愈重连"""
        # 构建交易流URL（所有symbol的aggTrade流）
        trade_streams = [f"{symbol.lower()}@aggTrade" for symbol in self.symbols]
        trade_url = f"wss://fstream.binance.com/stream?streams={'/'.join(trade_streams)}"
        
        # 构建订单簿流URL（所有symbol的depth5@100ms流）
        orderbook_streams = [f"{symbol.lower()}@depth5@100ms" for symbol in self.symbols]
        orderbook_url = f"wss://fstream.binance.com/stream?streams={'/'.join(orderbook_streams)}"
        
        logger.info(f"连接统一交易流: {len(self.symbols)}个symbol")
        logger.info(f"连接统一订单簿流: {len(self.symbols)}个symbol")
        
        backoff = 1.0
        stable_connection_start = None  # 稳定连接开始时间
        while self.running:
            try:
                # 创建两个并发任务
                tasks = {
                    asyncio.create_task(self._handle_unified_trade_stream(trade_url)),
                    asyncio.create_task(self._handle_unified_orderbook_stream(orderbook_url)),
                }
                
                # 记录连接开始时间（用于稳定连接检测）
                if stable_connection_start is None:
                    stable_connection_start = time.time()
                
                # 关键改进：使用FIRST_COMPLETED模式，任一子流异常立即取消另一个并整体重连
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                
                # 取消所有未完成的任务
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                
                # 检查是否有任务异常完成
                has_exception = False
                for task in done:
                    try:
                        await task
                    except Exception as e:
                        logger.warning(f"子流异常完成: {e}")
                        has_exception = True
                
                # 稳定连接检测：如果连接稳定超过配置阈值且无异常，重置退避
                if not has_exception and stable_connection_start:
                    stable_duration = time.time() - stable_connection_start
                    if stable_duration > self.backoff_reset_secs:
                        if backoff > 1.0:
                            logger.info(f"连接稳定{stable_duration:.0f}秒，重置退避从{backoff:.1f}到1.0")
                            backoff = 1.0
                
                # 正常退出，退出循环
                if not self.running:
                    break
                
                # 小退避后继续下一轮，统一重连
                logger.info(f"统一流重连(#{self.reconnect_count + 1})")
                await asyncio.sleep(min(5.0, backoff))
                backoff = min(60.0, backoff * 1.5)  # 温和退避
                
                # 重置稳定连接计时
                stable_connection_start = None
                
            except Exception as e:
                self.reconnect_count += 1
                logger.error(f"统一流连接错误(#{self.reconnect_count}): {e}")
                await asyncio.sleep(min(60.0, backoff))
                backoff = min(60.0, backoff * 2)  # 指数退避，上限60s
    
    async def _handle_unified_trade_stream(self, url: str):
        """处理统一交易流（补丁A：带超时的读watchdog + ping_timeout）"""
        try:
            # 关键改进：设置ping_interval和ping_timeout，确保连接健康检测
            async with websockets.connect(url, ping_interval=20, ping_timeout=10, max_size=2**23, close_timeout=5) as websocket:
                logger.info("统一交易流连接成功")
                
                while self.running:
                    try:
                        # 修复：使用 trade_timeout 专用阈值（而非 stream_idle_sec），防止假死不重连
                        # 一旦超过 trade_timeout 未收到成交，就抛 TimeoutError，统一连接协程会自愈重连
                        message = await asyncio.wait_for(websocket.recv(), timeout=self.trade_timeout)
                        
                        data = json.loads(message)
                        
                        # 处理交易数据（Futures aggTrade格式）
                        trade_data_raw = data.get('data', data)
                        symbol = trade_data_raw.get('s', '').upper()  # 获取symbol
                        
                        if symbol not in self.symbols:
                            continue
                        
                        trade_data = {
                            'event_ts_ms': trade_data_raw.get('T', trade_data_raw.get('E', 0)),
                            'symbol': symbol,
                            'price': trade_data_raw.get('p', '0'),
                            'qty': trade_data_raw.get('q', '0'),
                            'trade_id': trade_data_raw.get('a', 0),
                            'is_buyer_maker': trade_data_raw.get('m', False)
                        }
                        
                        await self._process_trade_data(symbol, trade_data)
                        
                        # 检查是否需要定时轮转
                        await self._check_and_rotate_data()
                        
                        # 检查是否需要生成slices_manifest
                        await self._generate_slices_manifest()
                        
                    except asyncio.TimeoutError:
                        logger.warning(f"[TRADE] {self.trade_timeout}s 未收到消息，触发重连")
                        raise  # 跑到外层 except，令外层循环重建连接
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("[TRADE] WebSocket连接关闭，触发重连")
                        raise
                    except json.JSONDecodeError as e:
                        logger.error(f"交易流JSON解析错误: {e}")
                    except Exception as e:
                        logger.error(f"处理交易消息错误: {e}")
                        
        except asyncio.CancelledError:
            logger.info("统一交易流任务被取消（重连编排预期行为）")
            raise  # 向上抛出，让调度层感知已取消，但不计错误、不增重连计数
        except Exception as e:
            logger.error(f"统一交易流连接错误: {e}")
            self.reconnect_count += 1
    
    async def _handle_unified_orderbook_stream(self, url: str):
        """处理统一订单簿流（补丁A：带超时的读watchdog + ping_timeout）"""
        try:
            # 关键改进：设置ping_interval和ping_timeout，确保连接健康检测
            async with websockets.connect(url, ping_interval=20, ping_timeout=10, max_size=2**23, close_timeout=5) as websocket:
                logger.info("统一订单簿流连接成功")
                
                while self.running:
                    try:
                        # 修复：使用 orderbook_timeout 专用阈值（而非 stream_idle_sec），防止假死不重连
                        # 一旦超过 orderbook_timeout 未收到订单簿更新，就抛 TimeoutError，统一连接协程会自愈重连
                        message = await asyncio.wait_for(websocket.recv(), timeout=self.orderbook_timeout)
                        
                        # 正确解析symbol + 传入解析器
                        data = json.loads(message)
                        raw = data.get('data', data)
                        stream = data.get('stream', '')
                        symbol = (raw.get('s') or (stream.split('@')[0] if '@' in stream else '')).upper()
                        if not symbol or symbol not in self.symbols:
                            continue
                        
                        # 解析并处理
                        orderbook_data = self._parse_orderbook_message(raw)  # 允许 dict
                        if orderbook_data:
                            await self._process_orderbook_data(symbol, orderbook_data)
                            
                        # 检查是否需要定时轮转
                        await self._check_and_rotate_data()
                        
                    except asyncio.TimeoutError:
                        logger.warning(f"[ORDERBOOK] {self.orderbook_timeout}s 未收到消息，触发重连")
                        raise  # 跑到外层 except，令外层循环重建连接
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("[ORDERBOOK] WebSocket连接关闭，触发重连")
                        raise
                    except json.JSONDecodeError as e:
                        logger.error(f"订单簿流JSON解析错误: {e}")
                    except Exception as e:
                        logger.error(f"处理订单簿消息错误: {e}")
                        
        except asyncio.CancelledError:
            logger.info("统一订单簿流任务被取消（重连编排预期行为）")
            raise  # 向上抛出，让调度层感知已取消，但不计错误、不增重连计数
        except Exception as e:
            logger.error(f"统一订单簿流连接错误: {e}")
            self.reconnect_count += 1
    
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while self.running:
            try:
                # 执行健康检查
                ok = self._check_health()
                
                # 每10轮进行一次超时阈值关系自检
                self.health_check_counter += 1
                if self.health_check_counter % 10 == 0:
                    if self.stream_idle_sec >= self.trade_timeout:
                        logger.warning(f"[HEALTH_SELF_CHECK] 警告: STREAM_IDLE_SEC({self.stream_idle_sec}) >= TRADE_TIMEOUT({self.trade_timeout})")
                    else:
                        logger.info(f"[HEALTH_SELF_CHECK] 超时关系正常: STREAM_IDLE_SEC({self.stream_idle_sec}) < TRADE_TIMEOUT({self.trade_timeout})")
                
                # 每小时进行一次完整的阈值关系检查（便于长期运行排障）
                if self.health_check_counter % (3600 // self.health_check_interval) == 0:
                    logger.info(f"[HEALTH_HOURLY_CHECK] 阈值关系检查: STREAM_IDLE_SEC({self.stream_idle_sec}) < TRADE_TIMEOUT({self.trade_timeout}) < ORDERBOOK_TIMEOUT({self.orderbook_timeout})")
                    if not (self.stream_idle_sec < self.trade_timeout < self.orderbook_timeout):
                        logger.warning(f"[HEALTH_HOURLY_CHECK] 阈值关系异常: 建议 STREAM_IDLE_SEC < TRADE_TIMEOUT < ORDERBOOK_TIMEOUT")
                
                # 定时也触发一次轮转，避免"没有新消息就不落盘"
                await self._check_and_rotate_data()
                
                # 等待下次检查
                await asyncio.sleep(self.health_check_interval)
                
            except Exception as e:
                logger.error(f"[HEALTH] 健康检查错误: {e}")
                await asyncio.sleep(10)  # 错误时短暂等待
    
    async def run(self):
        """运行成功版采集器"""
        logger.info("开始成功版数据采集（基于Task 1.2.5成功实现）...")
        
        # 初始化paper trader（如果启用）
        if _env("PAPER_ENABLE", "0") == "1":
            try:
                from core_algo_paper import start_paper_trader
                self.paper = await start_paper_trader()
                logger.info("Paper trader已启用")
            except ImportError:
                logger.warning("core_algo_paper模块未找到，跳过paper trader初始化")
                self.paper = None
        else:
            self.paper = None
        
        # 创建任务
        tasks = []
        
        # 使用统一流连接（优化连接数）
        unified_stream_task = asyncio.create_task(self.connect_unified_streams())
        tasks.append(unified_stream_task)
        
        # 添加健康检查任务
        health_check_task = asyncio.create_task(self._health_check_loop())
        tasks.append(health_check_task)
        
        try:
            # 等待所有任务完成（移除超时限制，支持7x24小时运行）
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"运行错误: {e}")
        finally:
            # 停止运行
            logger.info("准备停止采集，开始保存剩余数据...")
            self.running = False
            # 短暂停顿，让流任务自然break
            await asyncio.sleep(0.1)
            
            # 保存剩余数据（加锁保证原子性）
            async with self.rotation_lock:
                for symbol in self.symbols:
                    # 最后生成一次特征宽表
                    self._generate_features_table(symbol)
                    
                    # 保存权威库数据（prices, orderbook）
                    for kind in ['prices', 'orderbook']:
                        if self.data_buffers[kind][symbol]:
                            await self._save_data(symbol, kind)
                    
                    # 保存预览库数据（ofi, cvd, fusion, events, features）
                    for kind in self.preview_kinds:
                        if self.data_buffers[kind][symbol]:
                            await self._save_data(symbol, kind)
            
            # 打印统计信息
            logger.info("数据采集完成，统计信息:")
            for symbol in self.symbols:
                logger.info(f"{symbol}: 交易{self.stats['total_trades'][symbol]}, "
                          f"OFI{self.stats['total_ofi'][symbol]}, "
                          f"CVD{self.stats['total_cvd'][symbol]}, "
                          f"事件{self.stats['total_events'][symbol]}, "
                          f"订单簿{self.stats['total_orderbook'][symbol]}")  # 添加订单簿统计

async def main():
    """主函数 - 支持7x24小时连续运行 + 严格运行时配置"""
    import argparse
    
    parser = argparse.ArgumentParser(description='OFI+CVD数据采集器')
    parser.add_argument("--config", type=str, default=None,
                       help="显式指定运行时包路径（默认使用dist/config/harvester.runtime.current.yaml或V13_HARVESTER_RUNTIME_PACK）")
    parser.add_argument("--dry-run-config", action="store_true",
                       help="仅验证配置，不运行采集器")
    parser.add_argument("--compat-global-config", action="store_true",
                       help="启用兼容模式：使用全局配置目录（临时过渡选项）")
    args = parser.parse_args()
    
    # 加载严格运行时配置（优先）
    try:
        from v13conf.runtime_loader import load_component_runtime_config, print_component_effective_config
        
        # 读取严格运行包
        cfg = load_component_runtime_config(
            component="harvester",
            pack_path=args.config,
            compat_global=args.compat_global_config,
            verify_scenarios_snapshot=False  # harvester不需要场景快照验证
        )
        
        # 打印有效配置
        print_component_effective_config(cfg, component="harvester")
        
        if args.dry_run_config:
            print("\n[DRY-RUN] 配置验证通过，退出")
            return
        
        # 提取harvester配置子树
        harvester_cfg = cfg.get('components', {}).get('harvester', {})
        
        if not harvester_cfg:
            raise ValueError("运行时包中未找到components.harvester配置")
        
        # 创建采集器（使用配置注入）
        harvester = SuccessOFICVDHarvester(cfg=harvester_cfg)
        
    except ImportError as e:
        # 降级：使用向后兼容模式
        import warnings
        warnings.warn(f"无法加载统一配置系统: {e}，降级到环境变量模式", UserWarning)
        
        symbols = os.getenv('SYMBOLS', 'BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT').split(',')
        run_hours = float(os.getenv('RUN_HOURS', '87600'))
        script_dir = Path(__file__).parent.absolute()
        default_output_dir = script_dir / "data" / "ofi_cvd"
        output_dir = os.getenv('OUTPUT_DIR', str(default_output_dir))
        
        harvester = SuccessOFICVDHarvester(
            cfg=None,
            compat_env=True,  # 关键：显式允许 env 回退
            symbols=symbols,
            run_hours=run_hours,
            output_dir=output_dir
        )
    
    # 运行采集
    await harvester.run()

if __name__ == "__main__":
    asyncio.run(main())
