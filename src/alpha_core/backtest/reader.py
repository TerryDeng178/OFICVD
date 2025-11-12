# -*- coding: utf-8 -*-
"""T08.1: Reader - Partition scanning, filtering, and deduplication"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

try:
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

logger = logging.getLogger(__name__)

class DataReader:
    """Read historical data from JSONL or Parquet files with filtering and deduplication"""
    
    def __init__(
        self,
        input_dir: Path,
        date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        kinds: Optional[List[str]] = None,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        minutes: Optional[int] = None,
        session: Optional[str] = None,
        include_preview: bool = False,
        source_priority: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            input_dir: Base data directory (e.g., ./deploy/data/ofi_cvd)
            date: Date filter (YYYY-MM-DD format)
            symbols: Symbol filter (e.g., ["BTCUSDT", "ETHUSDT"])
            kinds: Data kind filter (e.g., ["features", "signals", "prices", "orderbook"])
            start_ms: Start timestamp (Unix ms, UTC)
            end_ms: End timestamp (Unix ms, UTC)
            minutes: Number of minutes to read (alternative to start_ms/end_ms)
            session: Session filter (e.g., "NY", "AS", "EU")
        """
        self.input_dir = Path(input_dir)
        self.date = date
        self.symbols = symbols or []
        self.kinds = kinds or []
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.minutes = minutes
        self.session = session
        # P0: 默认不扫preview，避免时间窗对不齐
        self.include_preview = include_preview
        # P0-5: 默认来源优先级与"ready覆盖preview"的语义一致（ready优先）
        self.source_priority = source_priority or (["ready", "preview"] if include_preview else ["ready"])
        # P1-1: 保存config，便于_cleanup_old_buckets读取reader.dedup_keep_hours
        self.config = config or {}
        
        # Statistics
        self.stats = {
            "total_rows": 0,
            "deduplicated_rows": 0,
            "filtered_rows": 0,
            "missing_fields": defaultdict(int),
            # P1: 可观测性补完
            "scanned_dirs": set(),
            "partition_count": 0,
            "file_count": 0,
        }
        
        # 代码.3: Reader去重集内存优化（按分钟桶维护/定期清窗）
        # 使用字典按分钟桶存储，避免长窗口内存占用增长
        # 结构: {minute_bucket: Set[(symbol, second_ts)]}
        # minute_bucket = ts_ms // (60 * 1000)  # 分钟级桶
        self._seen_keys_buckets: Dict[int, Set[Tuple[str, int]]] = {}
        self._current_file_path: Optional[Path] = None  # 跟踪当前处理的文件
        # P1-5: 记录实际命中样例文件路径（用于CI目录结构回归）
        self._sample_files = set()
        # P1-4: 记录结构类型（flat/partition/preview_partition）
        self._structure_type: Optional[str] = None
    
    def read_features(self) -> Iterator[Dict[str, Any]]:
        """Read features data (fast path)"""
        return self._read_data("features")
    
    def read_raw(self, kind: str) -> Iterator[Dict[str, Any]]:
        """Read raw data (prices, orderbook, etc.)"""
        return self._read_data(kind)
    
    def _read_data(self, kind: str) -> Iterator[Dict[str, Any]]:
        """Internal method to read data of a specific kind
        
        P0修复: 按source_priority优先级分批读取，保证ready覆盖preview
        """
        # P0修复: 按source_priority优先级分批读取文件
        file_paths = self._find_files(kind)
        
        # 按source_priority分组文件
        files_by_source = {"ready": [], "preview": []}
        for file_path in file_paths:
            if "preview" in str(file_path):
                files_by_source["preview"].append(file_path)
            else:
                files_by_source["ready"].append(file_path)
        
        # P0修复: 按source_priority顺序读取（ready优先，覆盖preview）
        source_order = self.source_priority or ["ready", "preview"]
        for source in source_order:
            if source in files_by_source:
                for file_path in files_by_source[source]:
                    logger.debug(f"Reading {kind} from {file_path} (source: {source})")
                    
                    # 代码.3: 处理完每个文件后清理过期桶
                    self._current_file_path = file_path
                    
                    # P1-5: 记录实际命中样例文件路径（用于CI目录结构回归）
                    if len(self._sample_files) < 3:
                        self._sample_files.add(str(file_path))
                    
                    if file_path.suffix == ".parquet":
                        yield from self._read_parquet(file_path, kind)
                    elif file_path.suffix == ".jsonl":
                        yield from self._read_jsonl(file_path, kind)
                    else:
                        logger.warning(f"Unsupported file format: {file_path.suffix}")
                    
                    # 代码.3: 处理完文件后清理过期桶（保留最近2小时的桶）
                    self._cleanup_old_buckets()
    
    def _find_files(self, kind: str) -> List[Path]:
        """Find files matching the criteria
        
        P1: 返回文件列表，并在统计中记录扫描到的目录和分片数量
        """
        files = []
        scanned_dirs = []
        partition_count = 0
        
        # P1: 记录扫描的目录
        if self.include_preview or "preview" in (self.source_priority or []):
            if (self.input_dir / "preview").exists():
                scanned_dirs.append("preview")
        if (self.input_dir / "ready").exists():
            scanned_dirs.append("ready")
        
        # Support multiple directory structures:
        # 1. Partition structure: data/ofi_cvd/date=2025-10-30/hour=10/symbol=btcusdt/kind=features/...
        # 2. Flat structure: data/ofi_cvd/ready/{kind}/{symbol}/...
        # 3. Raw structure: data/ofi_cvd/raw/date=2025-10-30/hour=10/symbol=btcusdt/kind=prices/...
        
        if self.date:
            # Partition structure: date=/hour=/symbol=/kind=
            # Check both root and raw subdirectory
            for base_dir in [self.input_dir, self.input_dir / "raw"]:
                date_partition = base_dir / f"date={self.date}"
                if date_partition.exists():
                    # P1-4: 记录结构类型为partition
                    if self._structure_type is None:
                        self._structure_type = "partition"
                    # Check all hour directories
                    for hour_dir in date_partition.iterdir():
                        if hour_dir.is_dir() and hour_dir.name.startswith("hour="):
                            for symbol_dir in hour_dir.iterdir():
                                if symbol_dir.is_dir() and symbol_dir.name.startswith("symbol="):
                                    symbol = symbol_dir.name.split("=")[1].upper()
                                    if self.symbols and symbol not in self.symbols:
                                        continue
                                    kind_dir = symbol_dir / f"kind={kind}"
                                    if kind_dir.exists():
                                        found_files = list(kind_dir.rglob("*.parquet")) + list(kind_dir.rglob("*.jsonl"))
                                        files.extend(found_files)
                                        partition_count += len(found_files)  # P1: 统计分片数量
        else:
            # Flat structure: data/ofi_cvd/ready/{kind}/{symbol}/...
            ready_dir = self.input_dir / "ready" / kind
            if ready_dir.exists():
                # P1-4: 记录结构类型为flat
                if self._structure_type is None:
                    self._structure_type = "flat"
                for symbol_dir in ready_dir.iterdir():
                    if symbol_dir.is_dir():
                        symbol = symbol_dir.name.upper()
                        if self.symbols and symbol not in self.symbols:
                            continue
                        found_files = list(symbol_dir.rglob("*.jsonl"))
                        files.extend(found_files)
                        # P0-2: flat结构扫描时也累计partition_count，保持监控指标口径一致
                        partition_count += len(found_files)
        
        # P0: 默认不扫preview，避免时间窗对不齐
        # 仅在include_preview=True或source_priority包含preview时扫描
        if self.include_preview or "preview" in self.source_priority:
            # Check preview/ready/{kind}/{symbol}/...
            preview_ready_dir = self.input_dir / "preview" / "ready" / kind
            if preview_ready_dir.exists():
                # P1-4: 记录结构类型为preview_partition（preview下的flat结构）
                if self._structure_type is None:
                    self._structure_type = "preview_partition"
                for symbol_dir in preview_ready_dir.iterdir():
                    if symbol_dir.is_dir():
                        symbol = symbol_dir.name.upper()
                        if self.symbols and symbol not in self.symbols:
                            continue
                        found_files = list(symbol_dir.rglob("*.jsonl"))
                        files.extend(found_files)
                        partition_count += len(found_files)  # P1: 统计分片数量
            
            # Check preview/date=/hour=/symbol=/kind= (partition structure)
            if self.date:
                preview_date_partition = self.input_dir / "preview" / f"date={self.date}"
                if preview_date_partition.exists():
                    # P1-4: 记录结构类型为preview_partition
                    if self._structure_type is None:
                        self._structure_type = "preview_partition"
                    for hour_dir in preview_date_partition.iterdir():
                        if hour_dir.is_dir() and hour_dir.name.startswith("hour="):
                            for symbol_dir in hour_dir.iterdir():
                                if symbol_dir.is_dir() and symbol_dir.name.startswith("symbol="):
                                    symbol = symbol_dir.name.split("=")[1].upper()
                                    if self.symbols and symbol not in self.symbols:
                                        continue
                                    kind_dir = symbol_dir / f"kind={kind}"
                                    if kind_dir.exists():
                                        found_files = list(kind_dir.rglob("*.parquet")) + list(kind_dir.rglob("*.jsonl"))
                                        files.extend(found_files)
                                        partition_count += len(found_files)  # P1: 统计分片数量
        
        # P1: 更新统计（扫描目录、分片数量）
        self.stats["scanned_dirs"] = set(scanned_dirs)  # 使用set避免重复
        self.stats["partition_count"] = partition_count
        self.stats["file_count"] = len(files)
        return sorted(files)
    
    def _read_parquet(self, file_path: Path, kind: str) -> Iterator[Dict[str, Any]]:
        """Read Parquet file with schema evolution handling"""
        if not PARQUET_AVAILABLE:
            logger.error("Parquet support not available. Install pyarrow: pip install pyarrow")
            return
        
        try:
            # Try reading the entire table first
            try:
                table = pq.read_table(file_path)
                for batch in table.to_batches():
                    for row in batch.to_pylist():
                        processed = self._process_row(row, kind)
                        if processed:
                            yield processed
            except Exception as schema_error:
                # If schema merge fails, read row groups individually
                logger.debug(f"Schema merge failed for {file_path}, reading row groups individually: {schema_error}")
                parquet_file = pq.ParquetFile(file_path)
                
                for i in range(parquet_file.num_row_groups):
                    try:
                        rg_table = parquet_file.read_row_group(i)
                        for batch in rg_table.to_batches():
                            for row in batch.to_pylist():
                                processed = self._process_row(row, kind)
                                if processed:
                                    yield processed
                    except Exception as rg_error:
                        logger.warning(f"Error reading row group {i} from {file_path}: {rg_error}")
                        continue
        except Exception as e:
            logger.error(f"Error reading Parquet file {file_path}: {e}")
    
    def _read_jsonl(self, file_path: Path, kind: str) -> Iterator[Dict[str, Any]]:
        """Read JSONL file"""
        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        processed = self._process_row(row, kind)
                        if processed:
                            yield processed
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON at {file_path}:{line_num}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error reading JSONL file {file_path}: {e}")
    
    def _process_row(self, row: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
        """Process a single row: filter, deduplicate, and validate"""
        self.stats["total_rows"] += 1
        
        # Extract key fields
        symbol = row.get("symbol", "")
        ts_ms = row.get("ts_ms", 0) or row.get("second_ts", 0) * 1000
        
        # Symbol filter
        if self.symbols and symbol not in self.symbols:
            self.stats["filtered_rows"] += 1
            return None
        
        # Time filter
        if self.start_ms and ts_ms < self.start_ms:
            self.stats["filtered_rows"] += 1
            return None
        if self.end_ms and ts_ms > self.end_ms:
            self.stats["filtered_rows"] += 1
            return None
        if self.minutes and self.start_ms:
            if ts_ms > self.start_ms + self.minutes * 60 * 1000:
                self.stats["filtered_rows"] += 1
                return None
        
        # 代码.3: 按分钟桶维护去重集
        # Deduplication: use (symbol, second_ts) for features, (symbol, ts_ms) for others
        if kind == "features":
            second_ts = ts_ms // 1000
            dedup_key = (symbol, second_ts)
            # 使用分钟级桶（second_ts // 60）
            minute_bucket = second_ts // 60
        else:
            dedup_key = (symbol, ts_ms)
            # 使用分钟级桶（ts_ms // (60 * 1000)）
            minute_bucket = ts_ms // (60 * 1000)
        
        # 获取或创建该分钟桶
        if minute_bucket not in self._seen_keys_buckets:
            self._seen_keys_buckets[minute_bucket] = set()
        
        bucket = self._seen_keys_buckets[minute_bucket]
        
        if dedup_key in bucket:
            self.stats["deduplicated_rows"] += 1
            return None
        
        bucket.add(dedup_key)
        
        # Check for missing required fields
        required_fields = ["symbol", "ts_ms"] if kind != "features" else ["symbol", "second_ts"]
        for field in required_fields:
            if field not in row or row[field] is None:
                self.stats["missing_fields"][field] += 1
        
        # Normalize ts_ms for features
        if kind == "features" and "second_ts" in row and "ts_ms" not in row:
            row["ts_ms"] = row["second_ts"] * 1000
        
        return row
    
    def _cleanup_old_buckets(self, keep_hours: Optional[int] = None):
        """代码.3: 清理过期桶，保留最近N小时的桶
        
        P1-2: 保留时长参数化（支持config和env覆盖）
        
        Args:
            keep_hours: 保留的小时数（默认从config或env读取，fallback为2小时）
        """
        # P1-2: 从config或env读取keep_hours
        if keep_hours is None:
            import os
            keep_hours = int(os.getenv("READER_DEDUP_KEEP_HOURS", "2"))
            # 如果Reader有config属性，也可以从config读取
            if hasattr(self, "config") and self.config:
                keep_hours = self.config.get("reader", {}).get("dedup_keep_hours", keep_hours)
        if not self._seen_keys_buckets:
            return
        
        # 计算当前时间戳（如果有start_ms则使用，否则使用最新的桶）
        if self.start_ms:
            current_minute = self.start_ms // (60 * 1000)
        else:
            current_minute = max(self._seen_keys_buckets.keys()) if self._seen_keys_buckets else 0
        
        # 计算保留的最小分钟桶（保留最近keep_hours小时）
        keep_minutes = keep_hours * 60
        min_bucket = current_minute - keep_minutes
        
        # 删除过期桶
        buckets_to_remove = [b for b in self._seen_keys_buckets.keys() if b < min_bucket]
        for bucket in buckets_to_remove:
            del self._seen_keys_buckets[bucket]
        
        if buckets_to_remove:
            logger.debug(f"[DataReader] Cleaned up {len(buckets_to_remove)} old buckets, kept {len(self._seen_keys_buckets)} buckets")
    
    def get_stats(self) -> Dict[str, any]:
        """Get reading statistics"""
        dedup_rate = (
            self.stats["deduplicated_rows"] / self.stats["total_rows"] * 100
            if self.stats["total_rows"] > 0
            else 0.0
        )
        
        # P1-5: 记录实际命中样例文件路径（用于CI目录结构回归）
        sample_files = []
        if hasattr(self, "_sample_files") and self._sample_files:
            # 记录前3个样例文件路径（相对路径）
            for f in list(self._sample_files)[:3]:
                try:
                    rel_path = str(Path(f).relative_to(self.input_dir)) if Path(f).is_relative_to(self.input_dir) else str(f)
                    sample_files.append(rel_path)
                except Exception:
                    sample_files.append(str(f))
        
        return {
            "total_rows": self.stats["total_rows"],
            "deduplicated_rows": self.stats["deduplicated_rows"],
            "filtered_rows": self.stats["filtered_rows"],
            "missing_fields": dict(self.stats.get("missing_fields", {})),
            "deduplication_rate_pct": dedup_rate,
            "scanned_dirs": list(self.stats.get("scanned_dirs", set())),
            "partition_count": self.stats.get("partition_count", 0),
            "file_count": self.stats.get("file_count", 0),
            "sample_files": sample_files,  # P1-5: 实际命中样例文件路径
            "structure_type": self._structure_type,  # P1-4: 记录结构类型（flat/partition/preview_partition）
        }

