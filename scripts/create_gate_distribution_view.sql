-- TASK09X: 创建Gate分布查询视图
-- 从signals表中提取lag_sec、spread_bps、consistency等字段用于分布分析

-- 注意：signals表可能没有这些列，需要从其他来源获取
-- 如果这些字段在_feature_data JSON中，需要使用json_extract

-- 创建视图：v_signals_gate_distribution
-- 用于查询lag/consistency/spread的分布和超阈占比

CREATE VIEW IF NOT EXISTS v_signals_gate_distribution AS
SELECT 
    ts_ms,
    symbol,
    confirm,
    gating,
    guard_reason,
    -- 尝试从guard_reason中提取信息（如果格式为"lag_sec>0.01"）
    CASE 
        WHEN guard_reason LIKE 'lag_sec>%' THEN 1 
        ELSE 0 
    END AS has_lag_exceeded,
    CASE 
        WHEN guard_reason LIKE '%spread_bps>%' THEN 1 
        ELSE 0 
    END AS has_spread_exceeded,
    CASE 
        WHEN guard_reason LIKE '%low_consistency%' THEN 1 
        ELSE 0 
    END AS has_low_consistency,
    CASE 
        WHEN guard_reason LIKE '%weak_signal%' THEN 1 
        ELSE 0 
    END AS has_weak_signal,
    CASE 
        WHEN guard_reason LIKE '%warmup%' THEN 1 
        ELSE 0 
    END AS has_warmup
FROM signals;

-- 创建统计视图：v_gate_distribution_stats
-- 用于快速查询分布统计

CREATE VIEW IF NOT EXISTS v_gate_distribution_stats AS
SELECT 
    COUNT(*) AS total_signals,
    SUM(CASE WHEN gating = 1 THEN 1 ELSE 0 END) AS blocked_signals,
    SUM(has_lag_exceeded) AS lag_exceeded_count,
    SUM(has_spread_exceeded) AS spread_exceeded_count,
    SUM(has_low_consistency) AS low_consistency_count,
    SUM(has_weak_signal) AS weak_signal_count,
    SUM(has_warmup) AS warmup_count,
    -- 占比
    CAST(SUM(has_lag_exceeded) AS FLOAT) / NULLIF(SUM(CASE WHEN gating = 1 THEN 1 ELSE 0 END), 0) * 100 AS lag_exceeded_pct,
    CAST(SUM(has_spread_exceeded) AS FLOAT) / NULLIF(SUM(CASE WHEN gating = 1 THEN 1 ELSE 0 END), 0) * 100 AS spread_exceeded_pct,
    CAST(SUM(has_low_consistency) AS FLOAT) / NULLIF(SUM(CASE WHEN gating = 1 THEN 1 ELSE 0 END), 0) * 100 AS low_consistency_pct,
    CAST(SUM(has_weak_signal) AS FLOAT) / NULLIF(SUM(CASE WHEN gating = 1 THEN 1 ELSE 0 END), 0) * 100 AS weak_signal_pct,
    CAST(SUM(has_warmup) AS FLOAT) / NULLIF(SUM(CASE WHEN gating = 1 THEN 1 ELSE 0 END), 0) * 100 AS warmup_pct
FROM v_signals_gate_distribution;

