# -*- coding: utf-8 -*-
"""CORE_ALGO MCP thin shell.

This CLI wires FeaturePipe output into `alpha_core.signals.CoreAlgorithm` and
supports JSONL / SQLite sinks for TASK-05.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

import yaml

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from alpha_core.signals import CoreAlgorithm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def load_signal_config(config_path: Optional[str]) -> Dict:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    # Return signal config merged with strategy_mode (if present)
    signal_cfg = raw.get("signal", {})
    if "strategy_mode" in raw:
        signal_cfg["strategy_mode"] = raw["strategy_mode"]
    return signal_cfg


def iter_feature_rows(source: Optional[str], symbols: Optional[Iterable[str]]) -> Iterator[Dict]:
    """迭代特征行，支持 JSONL 和 Parquet 格式"""
    allowed = set(s.upper() for s in symbols) if symbols else None

    if not source or source == "-":
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if allowed and payload.get("symbol") not in allowed:
                continue
            yield payload
        return

    path = Path(source)
    candidates: Iterable[Path]
    if path.is_dir():
        # 递归查找 JSONL 和 Parquet 文件
        jsonl_files = sorted(path.rglob("*.jsonl"))
        parquet_files = sorted(path.rglob("*.parquet")) if PANDAS_AVAILABLE else []
        candidates = jsonl_files + parquet_files
    elif path.is_file():
        candidates = [path]
    else:
        # 通配符模式
        jsonl_matches = sorted(path.parent.glob(path.name.replace(".parquet", ".jsonl")))
        parquet_matches = sorted(path.parent.glob(path.name.replace(".jsonl", ".parquet"))) if PANDAS_AVAILABLE else []
        candidates = list(jsonl_matches) + list(parquet_matches)

    for file_path in candidates:
        if file_path.suffix == ".parquet":
            # 读取 Parquet 文件
            if not PANDAS_AVAILABLE:
                logger.warning(f"跳过 Parquet 文件 {file_path}：pandas 未安装")
                continue
            
            try:
                df = pd.read_parquet(file_path)
                # 将 DataFrame 转换为字典列表
                for _, row in df.iterrows():
                    record = row.to_dict()
                    # 处理 NaN 值
                    record = {k: (None if pd.isna(v) else v) for k, v in record.items()}
                    
                    # 字段名映射：Parquet 字段名 -> CoreAlgorithm 期望的字段名
                    if "ofi_z" in record and "z_ofi" not in record:
                        record["z_ofi"] = record.get("ofi_z")
                    if "cvd_z" in record and "z_cvd" not in record:
                        record["z_cvd"] = record.get("cvd_z")
                    
                    # lag 字段转换：lag_ms_* -> lag_sec
                    if "lag_ms_ofi" in record or "lag_ms_cvd" in record or "lag_ms_fusion" in record:
                        # 使用最大的 lag_ms 值转换为秒
                        lag_ms_values = [
                            record.get("lag_ms_ofi"),
                            record.get("lag_ms_cvd"),
                            record.get("lag_ms_fusion")
                        ]
                        lag_ms = max([v for v in lag_ms_values if v is not None and not pd.isna(v)], default=0)
                        record["lag_sec"] = lag_ms / 1000.0 if lag_ms > 0 else 0.0
                    
                    # consistency 和 warmup 字段：如果不存在，设置默认值
                    if "consistency" not in record:
                        # 可以根据其他字段计算或设置默认值
                        record["consistency"] = 1.0  # 默认一致性
                    if "warmup" not in record:
                        record["warmup"] = False  # 默认非预热
                    
                    if allowed and record.get("symbol") not in allowed:
                        continue
                    yield record
            except Exception as e:
                logger.error(f"读取 Parquet 文件失败 {file_path}: {e}")
                continue
        elif file_path.suffix == ".jsonl":
            # 读取 JSONL 文件（原有逻辑）
            try:
                with file_path.open("r", encoding="utf-8") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if allowed and record.get("symbol") not in allowed:
                                continue
                            yield record
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.error(f"读取 JSONL 文件失败 {file_path}: {e}")
                continue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CORE_ALGO MCP thin shell")
    parser.add_argument("--config", help="Path to YAML configuration (defaults.yaml)")
    parser.add_argument("--input", default="-", help="Feature JSONL (file/dir/- for stdin)")
    parser.add_argument("--sink", choices=["jsonl", "sqlite", "null"], help="Override sink kind")
    parser.add_argument("--out", help="Override output directory (default ./runtime)")
    parser.add_argument("--symbols", nargs="*", help="Optional symbol whitelist (e.g. BTCUSDT ETHUSDT)")
    parser.add_argument("--watch", action="store_true", help="Watch input directory for new files (continuous mode)")
    parser.add_argument("--print", action="store_true", help="Print emitted decisions for inspection")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_signal_config(args.config)

    algo = CoreAlgorithm(
        config=config,
        sink_kind=args.sink,
        output_dir=args.out,
    )

    try:
        if args.watch and args.input and args.input != "-":
            # 监听模式：持续扫描目录中的新文件
            input_path = Path(args.input)
            if input_path.is_dir():
                processed_files = set()
                logger.info(f"监听模式：持续扫描 {input_path}")
                
                while True:
                    try:
                        # 查找新的 JSONL 和 Parquet 文件
                        jsonl_files = sorted(input_path.rglob("*.jsonl"))
                        parquet_files = sorted(input_path.rglob("*.parquet")) if PANDAS_AVAILABLE else []
                        all_files = jsonl_files + parquet_files
                        
                        for file_path in all_files:
                            file_key = str(file_path)
                            if file_key in processed_files:
                                continue
                            
                            # 处理新文件
                            logger.info(f"处理新文件: {file_path}")
                            try:
                                if file_path.suffix == ".parquet":
                                    # 处理 Parquet 文件
                                    if not PANDAS_AVAILABLE:
                                        logger.warning(f"跳过 Parquet 文件 {file_path}：pandas 未安装")
                                        continue
                                    
                                    df = pd.read_parquet(file_path)
                                    for _, row in df.iterrows():
                                        record = row.to_dict()
                                        # 处理 NaN 值
                                        record = {k: (None if pd.isna(v) else v) for k, v in record.items()}
                                        
                                        # 字段名映射：Parquet 字段名 -> CoreAlgorithm 期望的字段名
                                        if "ofi_z" in record and "z_ofi" not in record:
                                            record["z_ofi"] = record.get("ofi_z")
                                        if "cvd_z" in record and "z_cvd" not in record:
                                            record["z_cvd"] = record.get("cvd_z")
                                        
                                        # lag 字段转换：lag_ms_* -> lag_sec
                                        if "lag_ms_ofi" in record or "lag_ms_cvd" in record or "lag_ms_fusion" in record:
                                            lag_ms_values = [
                                                record.get("lag_ms_ofi"),
                                                record.get("lag_ms_cvd"),
                                                record.get("lag_ms_fusion")
                                            ]
                                            lag_ms = max([v for v in lag_ms_values if v is not None and not pd.isna(v)], default=0)
                                            record["lag_sec"] = lag_ms / 1000.0 if lag_ms > 0 else 0.0
                                        
                                        # consistency 和 warmup 字段：如果不存在，设置默认值
                                        if "consistency" not in record:
                                            record["consistency"] = 1.0  # 默认一致性
                                        if "warmup" not in record:
                                            record["warmup"] = False  # 默认非预热
                                        
                                        if args.symbols and record.get("symbol") not in [s.upper() for s in args.symbols]:
                                            continue
                                        decision = algo.process_feature_row(record)
                                        if args.print and decision:
                                            sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
                                elif file_path.suffix == ".jsonl":
                                    # 处理 JSONL 文件
                                    with file_path.open("r", encoding="utf-8") as fp:
                                        for line in fp:
                                            line = line.strip()
                                            if not line:
                                                continue
                                            try:
                                                row = json.loads(line)
                                                if args.symbols and row.get("symbol") not in [s.upper() for s in args.symbols]:
                                                    continue
                                                decision = algo.process_feature_row(row)
                                                if args.print and decision:
                                                    sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
                                            except json.JSONDecodeError:
                                                continue
                                
                                processed_files.add(file_key)
                            except Exception as e:
                                logger.error(f"处理文件失败 {file_path}: {e}")
                        
                        time.sleep(5)  # 每 5 秒扫描一次
                    except KeyboardInterrupt:
                        logger.info("收到中断信号，停止监听")
                        break
                    except Exception as e:
                        logger.error(f"监听出错: {e}", exc_info=True)
                        time.sleep(5)
            else:
                # 非目录，回退到普通模式
                for row in iter_feature_rows(args.input, args.symbols):
                    decision = algo.process_feature_row(row)
                    if args.print and decision:
                        sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
        else:
            # 普通模式：一次性处理
            for row in iter_feature_rows(args.input, args.symbols):
                decision = algo.process_feature_row(row)
                if args.print and decision:
                    sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
    finally:
        algo.close()

    stats = algo.stats
    sys.stderr.write(
        f"[core_algo] processed={stats.processed} emitted={stats.emitted} "
        f"suppressed={stats.suppressed} deduped={stats.deduplicated} warmup_blocked={stats.warmup_blocked}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

