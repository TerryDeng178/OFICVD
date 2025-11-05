# -*- coding: utf-8 -*-
"""
数据质量检查（DQ Gate）模块

在 Harvester 落盘前执行数据质量检查，坏数据分流并产出 JSON 报告。
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# Preview 列白名单（用于RAW→Preview列裁剪）
PREVIEW_COLUMNS = {
    'prices': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'price', 'qty', 'latency_ms', 'best_buy_fill', 'best_sell_fill'],
    'orderbook': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'best_bid', 'best_ask', 'mid', 'spread_bps', 'latency_ms',
                  'bid1_p', 'bid1_q', 'bid2_p', 'bid2_q', 'bid3_p', 'bid3_q', 'bid4_p', 'bid4_q', 'bid5_p', 'bid5_q',
                  'ask1_p', 'ask1_q', 'ask2_p', 'ask2_q', 'ask3_p', 'ask3_q', 'ask4_p', 'ask4_q', 'ask5_p', 'ask5_q'],
    'ofi': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'ofi_z', 'ofi_value', 'scale', 'regime', 'lag_ms_to_trade'],
    'cvd': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'z_cvd', 'cvd', 'delta', 'latency_ms'],
    'fusion': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'score', 'proba', 'score_raw', 'lag_ms_trade'],
    'events': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'event_type', 'event_data'],
    'features': ['second_ts', 'symbol', 'mid', 'ts_ms', 'recv_ts_ms', 'row_id', 'return_1s', 'ofi_z', 'cvd_z',
                 'fusion_score', 'scenario_2x2', 'lag_ms_ofi', 'lag_ms_cvd', 'lag_ms_fusion', 'best_bid', 'best_ask',
                 'spread_bps', 'best_buy_fill', 'best_sell_fill']
}

# 必需字段定义（按kind）
REQUIRED_FIELDS = {
    'prices': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'price'],
    'orderbook': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'best_bid', 'best_ask', 'mid'],
    'ofi': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'ofi_z'],
    'cvd': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'z_cvd'],
    'fusion': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'score', 'proba'],
    'events': ['ts_ms', 'recv_ts_ms', 'symbol', 'row_id', 'event_type'],
    'features': ['second_ts', 'symbol', 'mid']
}


def dq_gate_df(kind: str, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """
    数据质量检查（DQ Gate）
    
    Args:
        kind: 数据类型（prices/orderbook/ofi/cvd/fusion/events/features）
        df: 待检查的DataFrame
    
    Returns:
        (ok_df, bad_df, report): 合格数据、坏数据、检查报告
    """
    if df.empty:
        return df, pd.DataFrame(), {
            'kind': kind,
            'total_rows': 0,
            'ok_rows': 0,
            'bad_rows': 0,
            'reasons': {}
        }
    
    # 初始化坏数据标记
    bad_mask = pd.Series([False] * len(df), index=df.index)
    reasons = {}
    
    # 1. 必需字段检查
    required = REQUIRED_FIELDS.get(kind, [])
    missing_fields = [f for f in required if f not in df.columns]
    if missing_fields:
        bad_mask = bad_mask | True  # 全部标记为坏
        reasons['missing_required_fields'] = {
            'count': len(df),
            'fields': missing_fields
        }
    else:
        # 检查必需字段是否为空
        for field in required:
            null_mask = df[field].isna()
            if null_mask.any():
                bad_mask = bad_mask | null_mask
                if 'missing_values' not in reasons:
                    reasons['missing_values'] = {}
                reasons['missing_values'][field] = int(null_mask.sum())
    
    # 2. latency_ms >= 0（若存在）
    if 'latency_ms' in df.columns:
        invalid_latency = df['latency_ms'] < 0
        if invalid_latency.any():
            bad_mask = bad_mask | invalid_latency
            reasons['invalid_latency'] = int(invalid_latency.sum())
    
    # 3. row_id 唯一性检查
    if 'row_id' in df.columns:
        duplicates = df['row_id'].duplicated()
        if duplicates.any():
            bad_mask = bad_mask | duplicates
            reasons['duplicate_row_id'] = int(duplicates.sum())
    
    # 4. kind 特定规则
    if kind == 'prices':
        # prices.price > 0
        if 'price' in df.columns:
            invalid_price = (df['price'] <= 0) | df['price'].isna()
            if invalid_price.any():
                bad_mask = bad_mask | invalid_price
                reasons['invalid_price'] = int(invalid_price.sum())
    
    elif kind == 'orderbook':
        # best_bid <= mid <= best_ask
        if all(col in df.columns for col in ['best_bid', 'mid', 'best_ask']):
            invalid_bid = df['best_bid'] > df['mid']
            invalid_ask = df['best_ask'] < df['mid']
            invalid_range = invalid_bid | invalid_ask
            
            # 检查是否有0值或NaN
            zero_or_nan = df['best_bid'].isna() | (df['best_bid'] <= 0) | \
                         df['best_ask'].isna() | (df['best_ask'] <= 0) | \
                         df['mid'].isna() | (df['mid'] <= 0)
            invalid_range = invalid_range | zero_or_nan
            
            if invalid_range.any():
                bad_mask = bad_mask | invalid_range
                reasons['invalid_orderbook'] = int(invalid_range.sum())
    
    # 分离好坏数据
    ok_df = df[~bad_mask].copy()
    bad_df = df[bad_mask].copy()
    
    # 生成报告
    report = {
        'kind': kind,
        'total_rows': len(df),
        'ok_rows': len(ok_df),
        'bad_rows': len(bad_df),
        'reasons': reasons,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    return ok_df, bad_df, report


def save_dq_report(report: Dict, output_dir: Path, symbol: str, kind: str):
    """
    保存DQ报告到JSON文件
    
    Args:
        report: DQ检查报告
        output_dir: 输出目录
        symbol: 交易对符号
        kind: 数据类型
    """
    dq_reports_dir = output_dir / 'dq_reports'
    dq_reports_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    report_file = dq_reports_dir / f'dq_{symbol}_{kind}_{timestamp}.json'
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return report_file


def save_bad_data_to_deadletter(bad_df: pd.DataFrame, deadletter_dir: Path, symbol: str, kind: str):
    """
    保存坏数据到deadletter目录（NDJSON格式）
    
    Args:
        bad_df: 坏数据DataFrame
        deadletter_dir: deadletter目录
        symbol: 交易对符号
        kind: 数据类型
    """
    if bad_df.empty:
        return None
    
    deadletter_subdir = deadletter_dir / f'{kind}_dq_bad'
    deadletter_subdir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    deadletter_file = deadletter_subdir / f'{symbol}_{kind}_dq_bad_{timestamp}.ndjson'
    
    # 转换为NDJSON格式（每行一个JSON对象）
    with open(deadletter_file, 'w', encoding='utf-8') as f:
        for _, row in bad_df.iterrows():
            record = row.to_dict()
            # 处理NaN和Inf
            for k, v in record.items():
                if pd.isna(v):
                    record[k] = None
                elif isinstance(v, (float, np.floating)) and (np.isinf(v) or np.isnan(v)):
                    record[k] = None
            json.dump(record, f, ensure_ascii=False)
            f.write('\n')
    
    return deadletter_file

