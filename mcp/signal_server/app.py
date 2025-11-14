# -*- coding: utf-8 -*-
"""CORE_ALGO MCP thin shell.

This CLI wires FeaturePipe output into `alpha_core.signals.CoreAlgorithm` and
supports JSONL / SQLite sinks for TASK-05.
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import signal
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

    logger.info(f"[iter_feature_rows] 找到 {len(candidates)} 个候选文件")
    processed_count = 0
    total_row_count = 0
    
    for file_path in candidates:
        if file_path.suffix == ".parquet":
            # 读取 Parquet 文件
            if not PANDAS_AVAILABLE:
                logger.warning(f"跳过 Parquet 文件 {file_path}：pandas 未安装")
                continue
            
            try:
                logger.debug(f"[iter_feature_rows] 读取 Parquet 文件: {file_path}")
                df = pd.read_parquet(file_path)
                file_row_count = 0
                logger.debug(f"[iter_feature_rows] Parquet 文件 {file_path} 包含 {len(df)} 行")
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
                        # TASK-07A: 使用保守的一致性估算，避免"低一致性抑制"失效
                        # 基于 |z_ofi| 和 |z_cvd| 的简单函数估算
                        z1 = abs(float(record.get("z_ofi") or record.get("ofi_z") or 0.0))
                        z2 = abs(float(record.get("z_cvd") or record.get("cvd_z") or 0.0))
                        record["consistency"] = min(0.6, max(0.0, (z1 + z2) * 0.15))
                    if "warmup" not in record:
                        record["warmup"] = False  # 默认非预热
                    
                    if allowed and record.get("symbol") not in allowed:
                        continue
                    file_row_count += 1
                    total_row_count += 1
                    yield record
                processed_count += 1
                logger.info(f"[iter_feature_rows] Parquet 文件 {file_path.name} 处理完成，yield {file_row_count} 行（累计 {total_row_count} 行）")
            except Exception as e:
                logger.error(f"读取 Parquet 文件失败 {file_path}: {e}", exc_info=True)
                continue
        elif file_path.suffix == ".jsonl":
            # 读取 JSONL 文件（原有逻辑）
            try:
                logger.debug(f"[iter_feature_rows] 读取 JSONL 文件: {file_path}")
                jsonl_row_count = 0
                with file_path.open("r", encoding="utf-8") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if allowed and record.get("symbol") not in allowed:
                                continue
                            jsonl_row_count += 1
                            total_row_count += 1
                            yield record
                        except json.JSONDecodeError:
                            continue
                processed_count += 1
                logger.info(f"[iter_feature_rows] JSONL 文件 {file_path.name} 处理完成，yield {jsonl_row_count} 行（累计 {total_row_count} 行）")
            except Exception as e:
                logger.error(f"读取 JSONL 文件失败 {file_path}: {e}", exc_info=True)
                continue
    
    logger.info(f"[iter_feature_rows] 处理完成：共处理 {processed_count} 个文件，yield {total_row_count} 行数据")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CORE_ALGO MCP thin shell")
    parser.add_argument("--config", help="Path to YAML configuration (defaults.yaml)")
    parser.add_argument("--input", default="-", help="Feature JSONL (file/dir/- for stdin)")
    parser.add_argument("--sink", choices=["jsonl", "sqlite", "null", "dual"], help="Override sink kind (dual = jsonl + sqlite)")
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
    
    # TASK-B1 P1: Signal启动固定输出JSON日志套，便于orchestrator提取sink_used
    try:
        sink_health = algo._sink.get_health() if hasattr(algo, '_sink') and algo._sink else {}
        sink_used = sink_health.get('kind', 'unknown')
        schema_version = 'v2' if hasattr(algo, '_sink') and 'v2' in str(type(algo._sink)) else 'v1'

        boot_log = {
            "kind": "signal_boot",
            "sink_used": sink_used,
            "schema": schema_version,
            "timestamp": int(time.time() * 1000)
        }
        print(json.dumps(boot_log, ensure_ascii=False), flush=True)
    except Exception as e:
        logger.warning(f"[signal_server] 生成启动日志失败: {e}")

    # TASK-07A: 启动时打印Sink运行态（不可关闭），确认实际使用的sink类型
    try:
        sink_health = algo._sink.get_health() if hasattr(algo, '_sink') and algo._sink else {}
        sink_kind = sink_health.get('kind', 'unknown')
        logger.info(f"[signal_server] Sink运行态: kind={sink_kind}")
        if sink_kind == "multi":
            # MultiSink: 打印子sink信息
            sinks_info = sink_health.get('sinks', [])
            for i, sub_sink in enumerate(sinks_info):
                sub_kind = sub_sink.get('kind', 'unknown')
                sub_path = sub_sink.get('path', 'unknown')
                logger.info(f"[signal_server]  子Sink[{i}]: kind={sub_kind}, path={sub_path}")
        else:
            # 单一Sink: 打印kind和path
            sink_path = sink_health.get('path', 'unknown')
            logger.info(f"[signal_server]  路径: {sink_path}")
    except Exception as e:
        logger.warning(f"[signal_server] 获取Sink运行态失败: {e}", exc_info=True)
    
    # TASK-07A: 注册清理函数，确保进程退出时调用algo.close()
    cleanup_called = False
    
    def cleanup():
        """清理函数：确保Sink正确关闭"""
        nonlocal cleanup_called
        if cleanup_called:
            return  # 避免重复调用
        cleanup_called = True
        try:
            logger.info("[signal_server] 执行清理：关闭Sink...")
            sys.stderr.flush()  # 确保日志立即输出
            algo.close()
            logger.info("[signal_server] Sink已关闭")
            sys.stderr.flush()
        except Exception as e:
            logger.error(f"[signal_server] 清理时出错: {e}", exc_info=True)
            sys.stderr.flush()
    
    # 注册atexit清理函数（进程正常退出时调用）
    atexit.register(cleanup)
    logger.debug("[signal_server] atexit清理函数已注册")
    
    # 注册信号处理（Windows上SIGTERM可能不可用，但SIGINT可用）
    def signal_handler(signum, frame):
        """信号处理函数"""
        logger.info(f"[signal_server] 收到信号 {signum}，开始清理...")
        cleanup()
        sys.exit(0)
    
    try:
        # Windows上SIGTERM可能不可用，使用SIGINT作为备选
        # 注意：Windows上process.terminate()发送的是SIGTERM，但Python可能无法捕获
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        logger.debug("[signal_server] 信号处理已注册")
    except (AttributeError, ValueError) as e:
        # Windows上可能不支持某些信号，忽略
        logger.debug(f"[signal_server] 信号注册失败（可忽略）: {e}")
        pass

    try:
        if args.watch and args.input and args.input != "-":
            # 监听模式：持续扫描目录中的新文件
            input_path = Path(args.input)
            if input_path.is_dir():
                processed_files = set()
                logger.info(f"监听模式：持续扫描 {input_path}")
                
                # TASK-07A: 使用标志控制循环，确保能及时响应终止信号
                running = True
                
                def stop_handler(signum=None, frame=None):
                    """停止处理函数"""
                    nonlocal running
                    logger.info("[signal_server] 收到停止信号，准备退出...")
                    running = False
                
                # 更新信号处理，设置停止标志
                try:
                    if hasattr(signal, 'SIGTERM'):
                        signal.signal(signal.SIGTERM, stop_handler)
                    signal.signal(signal.SIGINT, stop_handler)
                except (AttributeError, ValueError):
                    pass
                
                while running:
                    try:
                        # 查找新的 JSONL 和 Parquet 文件
                        jsonl_files = sorted(input_path.rglob("*.jsonl"))
                        parquet_files = sorted(input_path.rglob("*.parquet")) if PANDAS_AVAILABLE else []
                        all_files = jsonl_files + parquet_files
                        
                        for file_path in all_files:
                            if not running:  # 检查停止标志
                                break
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
                                            # TASK-07A: 使用保守的一致性估算，避免"低一致性抑制"失效
                                            # 基于 |z_ofi| 和 |z_cvd| 的简单函数估算
                                            z1 = abs(float(record.get("z_ofi") or record.get("ofi_z") or 0.0))
                                            z2 = abs(float(record.get("z_cvd") or record.get("cvd_z") or 0.0))
                                            record["consistency"] = min(0.6, max(0.0, (z1 + z2) * 0.15))
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
                        
                        # TASK-07A: 使用可中断的sleep，确保能及时响应停止信号
                        if running:
                            # 分段sleep，每1秒检查一次running标志
                            for _ in range(5):
                                if not running:
                                    break
                                time.sleep(1)
                    except KeyboardInterrupt:
                        logger.info("收到中断信号，停止监听")
                        running = False
                        break
                    except Exception as e:
                        logger.error(f"监听出错: {e}", exc_info=True)
                        if running:
                            time.sleep(5)
                
                # 退出循环后，确保清理
                logger.info("[signal_server] 监听循环已退出，准备清理...")
            else:
                # 非目录，回退到普通模式
                for row in iter_feature_rows(args.input, args.symbols):
                    decision = algo.process_feature_row(row)
                    if args.print and decision:
                        sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
        else:
            # 普通模式：一次性处理（批处理模式）
            logger.info("[signal_server] 批处理模式：处理所有输入数据...")
            processed_row_count = 0
            emitted_signal_count = 0
            try:
                for row in iter_feature_rows(args.input, args.symbols):
                    processed_row_count += 1
                    decision = algo.process_feature_row(row)
                    if decision:
                        emitted_signal_count += 1
                    if args.print and decision:
                        sys.stdout.write(json.dumps(decision, ensure_ascii=False) + "\n")
                    # 每处理1000行输出一次进度
                    if processed_row_count % 1000 == 0:
                        logger.info(f"[signal_server] 批处理进度: 已处理 {processed_row_count} 行特征数据，已生成 {emitted_signal_count} 个信号")
            except Exception as e:
                logger.error(f"[signal_server] 批处理过程中出错: {e}", exc_info=True)
                raise
            
            logger.info(f"[signal_server] 批处理完成，共处理 {processed_row_count} 行特征数据，生成 {emitted_signal_count} 个信号，准备清理...")
            # TASK-07A: 批处理模式下，处理完所有数据后显式调用cleanup()
            # 只调用公开接口algo.close()，不访问私有属性，保持契约边界清晰
            logger.info("[signal_server] 批处理模式：显式调用cleanup()确保数据落盘...")
            cleanup()
            logger.info("[signal_server] 批处理模式：cleanup()调用完成")
    finally:
        # TASK-07A: 确保Sink正确关闭（finally块 + atexit双重保障）
        logger.info("[signal_server] 执行finally块：关闭Sink...")
        sys.stderr.flush()
        algo.close()
        logger.info("[signal_server] finally块：Sink已关闭")
        sys.stderr.flush()

    stats = algo.stats
    sys.stderr.write(
        f"[core_algo] processed={stats.processed} emitted={stats.emitted} "
        f"suppressed={stats.suppressed} deduped={stats.deduplicated} warmup_blocked={stats.warmup_blocked}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

