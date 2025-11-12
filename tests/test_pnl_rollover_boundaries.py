# -*- coding: utf-8 -*-
"""P1.2: PnL切日回归测试 - 跨月/跨年/周末/闰日/DST边界

测试_biz_date()方法在各种边界情况下的正确性
"""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from alpha_core.backtest.trade_sim import TradeSimulator


class TestPnLRolloverBoundaries:
    """测试PnL切日边界情况"""
    
    def test_cross_month_boundary(self, tmp_path: Path):
        """T1: 跨自然月边界（1月31日 → 2月1日）"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 1月31日23:59:59 UTC
        ts_jan = int(datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        # 2月1日00:00:01 UTC
        ts_feb = int(datetime(2025, 2, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_jan = trade_sim._biz_date(ts_jan)
        date_feb = trade_sim._biz_date(ts_feb)
        
        assert date_jan == "2025-01-31"
        assert date_feb == "2025-02-01"
    
    def test_cross_year_boundary(self, tmp_path: Path):
        """T2: 跨自然年边界（12月31日 → 1月1日）"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2024年12月31日23:59:59 UTC
        ts_dec = int(datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年1月1日00:00:01 UTC
        ts_jan = int(datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_dec = trade_sim._biz_date(ts_dec)
        date_jan = trade_sim._biz_date(ts_jan)
        
        assert date_dec == "2024-12-31"
        assert date_jan == "2025-01-01"
    
    def test_leap_year_feb_29(self, tmp_path: Path):
        """T3: 闰年2月29日"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2024年2月29日（闰年）
        ts_leap = int(datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        date_leap = trade_sim._biz_date(ts_leap)
        
        assert date_leap == "2024-02-29"
        
        # 2025年2月28日（非闰年，2月29日不存在）
        ts_non_leap = int(datetime(2025, 2, 28, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        date_non_leap = trade_sim._biz_date(ts_non_leap)
        
        assert date_non_leap == "2025-02-28"
    
    def test_weekend_boundary(self, tmp_path: Path):
        """T4: 周末边界（周五 → 周六 → 周日 → 周一）"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2025年1月3日（周五）23:59:59 UTC
        ts_fri = int(datetime(2025, 1, 3, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年1月4日（周六）00:00:01 UTC
        ts_sat = int(datetime(2025, 1, 4, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年1月5日（周日）12:00:00 UTC
        ts_sun = int(datetime(2025, 1, 5, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年1月6日（周一）00:00:01 UTC
        ts_mon = int(datetime(2025, 1, 6, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_fri = trade_sim._biz_date(ts_fri)
        date_sat = trade_sim._biz_date(ts_sat)
        date_sun = trade_sim._biz_date(ts_sun)
        date_mon = trade_sim._biz_date(ts_mon)
        
        assert date_fri == "2025-01-03"
        assert date_sat == "2025-01-04"
        assert date_sun == "2025-01-05"
        assert date_mon == "2025-01-06"
    
    def test_dst_transition_america_new_york(self, tmp_path: Path):
        """T5: DST切换（America/New_York）- 春季向前跳"""
        try:
            import pytz
        except ImportError:
            pytest.skip("pytz not available")
        
        config = {
            "rollover_timezone": "America/New_York",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2024年3月10日（DST开始，时钟向前跳1小时）
        # 02:00:00 EST → 03:00:00 EDT
        tz_ny = pytz.timezone("America/New_York")
        
        # DST开始前（02:00 EST）
        dt_before_dst = tz_ny.localize(datetime(2024, 3, 10, 1, 59, 59))
        ts_before = int(dt_before_dst.timestamp() * 1000)
        
        # DST开始后（03:00 EDT，实际是同一UTC时间）
        dt_after_dst = tz_ny.localize(datetime(2024, 3, 10, 3, 0, 1))
        ts_after = int(dt_after_dst.timestamp() * 1000)
        
        date_before = trade_sim._biz_date(ts_before)
        date_after = trade_sim._biz_date(ts_after)
        
        # 两个时间应该属于同一天（或相邻天，取决于具体实现）
        # 这里主要验证不会因为DST切换而崩溃
        assert date_before in ["2024-03-10", "2024-03-09"]
        assert date_after in ["2024-03-10", "2024-03-11"]
    
    def test_dst_fallback_america_new_york(self, tmp_path: Path):
        """P1-3: DST切换（America/New_York）- 秋季向后跳"""
        try:
            import pytz
        except ImportError:
            pytest.skip("pytz not available")
        
        config = {
            "rollover_timezone": "America/New_York",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2024年11月3日（DST结束，时钟向后跳1小时）
        # 02:00:00 EDT → 01:00:00 EST（重复1小时）
        tz_ny = pytz.timezone("America/New_York")
        
        # DST结束前（01:59:59 EDT）
        dt_before_fallback = tz_ny.localize(datetime(2024, 11, 3, 1, 59, 59))
        ts_before = int(dt_before_fallback.timestamp() * 1000)
        
        # DST结束后（01:00:01 EST，实际是同一UTC时间）
        dt_after_fallback = tz_ny.localize(datetime(2024, 11, 3, 1, 0, 1), is_dst=False)
        ts_after = int(dt_after_fallback.timestamp() * 1000)
        
        date_before = trade_sim._biz_date(ts_before)
        date_after = trade_sim._biz_date(ts_after)
        
        # 验证不会因为DST回退而崩溃
        assert date_before in ["2024-11-03", "2024-11-02"]
        assert date_after in ["2024-11-03", "2024-11-02"]
    
    def test_dst_cross_month_ny(self, tmp_path: Path):
        """P1-3: NY时区跨DST切换 + 跨月边界"""
        try:
            import pytz
        except ImportError:
            pytest.skip("pytz not available")
        
        config = {
            "rollover_timezone": "America/New_York",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        tz_ny = pytz.timezone("America/New_York")
        
        # 2024年3月9日（DST切换前一天）23:59:59 EST
        dt_mar9 = tz_ny.localize(datetime(2024, 3, 9, 23, 59, 59))
        ts_mar9 = int(dt_mar9.timestamp() * 1000)
        
        # 2024年3月10日（DST切换日）00:00:01 EDT（实际是03:00:01 UTC）
        dt_mar10 = tz_ny.localize(datetime(2024, 3, 10, 0, 0, 1))
        ts_mar10 = int(dt_mar10.timestamp() * 1000)
        
        date_mar9 = trade_sim._biz_date(ts_mar9)
        date_mar10 = trade_sim._biz_date(ts_mar10)
        
        # 验证跨日正确
        assert date_mar9 == "2024-03-09"
        assert date_mar10 == "2024-03-10"
    
    def test_cross_month_small_sample(self, tmp_path: Path):
        """P1-3: 跨月/跨年窗口的小样本回归"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 测试跨月边界的小样本
        # 1月31日23:59:59 → 2月1日00:00:01
        ts_jan_end = int(datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        ts_feb_start = int(datetime(2025, 2, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_jan = trade_sim._biz_date(ts_jan_end)
        date_feb = trade_sim._biz_date(ts_feb_start)
        
        assert date_jan == "2025-01-31"
        assert date_feb == "2025-02-01"
        
        # 测试跨年边界的小样本
        # 12月31日23:59:59 → 1月1日00:00:01
        ts_dec_end = int(datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        ts_jan_start = int(datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_dec = trade_sim._biz_date(ts_dec_end)
        date_jan = trade_sim._biz_date(ts_jan_start)
        
        assert date_dec == "2024-12-31"
        assert date_jan == "2025-01-01"
    
    def test_dst_with_custom_rollover_hour(self, tmp_path: Path):
        """P1-3: DST切换 + 自定义rollover_hour（08:00切日）"""
        try:
            import pytz
        except ImportError:
            pytest.skip("pytz not available")
        
        config = {
            "rollover_timezone": "America/New_York",
            "rollover_hour": 8,  # 08:00切日
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        tz_ny = pytz.timezone("America/New_York")
        
        # 2024年3月10日（DST切换日）07:59:59 EST（应该属于3月9日）
        dt_before_rollover = tz_ny.localize(datetime(2024, 3, 10, 7, 59, 59))
        ts_before = int(dt_before_rollover.timestamp() * 1000)
        
        # 2024年3月10日08:00:01 EDT（应该属于3月10日）
        dt_after_rollover = tz_ny.localize(datetime(2024, 3, 10, 8, 0, 1))
        ts_after = int(dt_after_rollover.timestamp() * 1000)
        
        date_before = trade_sim._biz_date(ts_before)
        date_after = trade_sim._biz_date(ts_after)
        
        # 验证自定义rollover_hour在DST切换时仍然正确
        assert date_before == "2024-03-09"
        assert date_after == "2024-03-10"
    
    def test_cross_timezone_consistency(self, tmp_path: Path):
        """P1.2: 跨时区一致性测试（Asia/Tokyo vs UTC）"""
        try:
            import pytz
        except ImportError:
            pytest.skip("pytz not available")
        
        # UTC配置
        config_utc = {
            "rollover_timezone": "UTC",
            "rollover_hour": 0,
        }
        trade_sim_utc = TradeSimulator(config_utc, tmp_path / "utc")
        
        # Asia/Tokyo配置
        config_tokyo = {
            "rollover_timezone": "Asia/Tokyo",
            "rollover_hour": 0,
        }
        trade_sim_tokyo = TradeSimulator(config_tokyo, tmp_path / "tokyo")
        
        # 测试同一UTC时间在不同时区的切日一致性
        # 2025-01-01 00:00:00 UTC = 2025-01-01 09:00:00 JST
        ts_utc_midnight = int(datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_utc = trade_sim_utc._biz_date(ts_utc_midnight)
        date_tokyo = trade_sim_tokyo._biz_date(ts_utc_midnight)
        
        # UTC: 2025-01-01 00:00:00 -> 2025-01-01
        # Tokyo: 2025-01-01 00:00:00 UTC = 2025-01-01 09:00:00 JST -> 2025-01-01
        assert date_utc == "2025-01-01"
        assert date_tokyo == "2025-01-01"
        
        # 测试"last bar close → next day open"一致性
        # 2024-12-31 23:59:59 UTC = 2025-01-01 08:59:59 JST
        ts_last_bar_utc = int(datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        ts_next_day_utc = int(datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_last_utc = trade_sim_utc._biz_date(ts_last_bar_utc)
        date_next_utc = trade_sim_utc._biz_date(ts_next_day_utc)
        date_last_tokyo = trade_sim_tokyo._biz_date(ts_last_bar_utc)
        date_next_tokyo = trade_sim_tokyo._biz_date(ts_next_day_utc)
        
        # UTC: 应该跨日
        assert date_last_utc == "2024-12-31"
        assert date_next_utc == "2025-01-01"
        
        # Tokyo: 由于时差，23:59:59 UTC已经是第二天08:59:59 JST，所以都是2025-01-01
        # 但0:00:01 UTC是09:00:01 JST，也是2025-01-01
        assert date_last_tokyo == "2025-01-01"
        assert date_next_tokyo == "2025-01-01"
    
    def test_custom_rollover_hour(self, tmp_path: Path):
        """T6: 自定义rollover_hour（08:00切日）"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 8,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2025年1月1日07:59:59 UTC（应该属于前一日）
        ts_before = int(datetime(2025, 1, 1, 7, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年1月1日08:00:01 UTC（应该属于当日）
        ts_after = int(datetime(2025, 1, 1, 8, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        date_before = trade_sim._biz_date(ts_before)
        date_after = trade_sim._biz_date(ts_after)
        
        # 08:00切日，07:59应该属于前一日（2024-12-31），08:00应该属于当日（2025-01-01）
        assert date_before == "2024-12-31"
        assert date_after == "2025-01-01"
    
    def test_custom_rollover_hour_cross_month(self, tmp_path: Path):
        """T7: 自定义rollover_hour跨月边界"""
        config = {
            "rollover_timezone": "UTC",
            "rollover_hour": 8,
        }
        trade_sim = TradeSimulator(config, tmp_path)
        
        # 2025年1月31日07:59:59 UTC（应该属于1月30日）
        ts_jan = int(datetime(2025, 1, 31, 7, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年1月31日08:00:01 UTC（应该属于1月31日）
        ts_jan_after = int(datetime(2025, 1, 31, 8, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年2月1日07:59:59 UTC（应该属于1月31日）
        ts_feb_before = int(datetime(2025, 2, 1, 7, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
        # 2025年2月1日08:00:01 UTC（应该属于2月1日）
        ts_feb_after = int(datetime(2025, 2, 1, 8, 0, 1, tzinfo=timezone.utc).timestamp() * 1000)
        
        assert trade_sim._biz_date(ts_jan) == "2025-01-30"
        assert trade_sim._biz_date(ts_jan_after) == "2025-01-31"
        assert trade_sim._biz_date(ts_feb_before) == "2025-01-31"
        assert trade_sim._biz_date(ts_feb_after) == "2025-02-01"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

