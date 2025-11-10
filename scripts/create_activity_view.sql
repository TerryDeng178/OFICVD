-- P0修复: 创建活动度视图，支持从JSON字段提取活动度数据
-- 使用方法: sqlite3 signals.db < create_activity_view.sql

-- 创建视图（如果不存在）
CREATE VIEW IF NOT EXISTS v_signals_activity AS
SELECT 
    *,
    json_extract(_feature_data, '$.activity.trade_rate') AS trade_rate,
    json_extract(_feature_data, '$.activity.quote_rate') AS quote_rate,
    json_extract(_feature_data, '$.trades_per_min') AS trades_per_min,
    json_extract(_feature_data, '$.quote_updates_per_sec') AS quote_updates_per_sec
FROM signals;

-- 检查覆盖率
-- SELECT
--     COUNT(*) AS total_signals,
--     SUM(CASE WHEN trade_rate IS NOT NULL AND CAST(trade_rate AS REAL) > 0 THEN 1 ELSE 0 END) AS trade_rate_valid,
--     SUM(CASE WHEN quote_rate IS NOT NULL AND CAST(quote_rate AS REAL) > 0 THEN 1 ELSE 0 END) AS quote_rate_valid,
--     CAST(SUM(CASE WHEN trade_rate IS NOT NULL AND CAST(trade_rate AS REAL) > 0 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100 AS trade_rate_coverage_pct,
--     CAST(SUM(CASE WHEN quote_rate IS NOT NULL AND CAST(quote_rate AS REAL) > 0 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100 AS quote_rate_coverage_pct
-- FROM v_signals_activity;

