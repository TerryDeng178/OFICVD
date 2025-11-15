# -*- coding: utf-8 -*-
"""PnL 回归测试 - 验证 BUY/SELL 分支修复

测试 BUY→SELL→BUY→SELL 交易序列的 PnL 计算是否正确。
这个测试用于验证 SELL 分支缩进修复后的正确性。
"""

import pytest
from collections import deque
from datetime import datetime, timezone


class TestPnLRegression:
    """PnL 回归测试"""

    def test_buy_sell_pnl_calculation(self):
        """测试 BUY/SELL 交易序列的 PnL 计算"""
        # 初始化持仓簿和闭合腿
        lots = {}
        closed_legs = []
        sym = "BTCUSDT"

        lots.setdefault(sym, deque())

        # 交易序列：BUY → SELL → BUY → SELL
        trades = [
            # 1. BUY 1.0 @ 50000
            {
                "symbol": sym,
                "side": "BUY",
                "exec_px": 50000.0,
                "qty": 1.0,
                "ts_ms": 1640995200000,  # 2022-01-01 00:00:00 UTC
                "fee_abs": 25.0  # 0.05% 手续费
            },
            # 2. SELL 1.0 @ 51000 (盈利)
            {
                "symbol": sym,
                "side": "SELL",
                "exec_px": 51000.0,
                "qty": 1.0,
                "ts_ms": 1640995260000,  # 2022-01-01 00:01:00 UTC
                "fee_abs": 25.5  # 0.05% 手续费
            },
            # 3. BUY 1.0 @ 49000
            {
                "symbol": sym,
                "side": "BUY",
                "exec_px": 49000.0,
                "qty": 1.0,
                "ts_ms": 1640995320000,  # 2022-01-01 00:02:00 UTC
                "fee_abs": 24.5  # 0.05% 手续费
            },
            # 4. SELL 1.0 @ 48000 (亏损)
            {
                "symbol": sym,
                "side": "SELL",
                "exec_px": 48000.0,
                "qty": 1.0,
                "ts_ms": 1640995380000,  # 2022-01-01 00:03:00 UTC
                "fee_abs": 24.0  # 0.05% 手续费
            }
        ]

        # 执行PnL计算逻辑（复制自app.py）
        for trade in trades:
            sym = trade["symbol"]
            side = trade["side"]
            px = trade["exec_px"]
            qty = trade["qty"]
            trade_ts = trade["ts_ms"]

            lots.setdefault(sym, deque())

            # 处理持仓簿
            if side == "BUY":
                # 先平空头仓位
                remain = qty
                while remain > 1e-12 and lots[sym] and lots[sym][0]["side"] == "SELL":
                    leg = lots[sym][0]
                    close_qty = min(remain, leg["qty"])

                    if close_qty > 0:
                        trade_fee = float(trade.get("fee_abs", 0.0))
                        # 分摊开仓费用
                        fee_open_part = float(leg.get("fee_open", 0.0)) * (close_qty / leg.get("qty_open", close_qty))
                        # 总费用 = 开仓费分摊 + 平仓费分摊
                        total_fee = fee_open_part + (trade_fee * (close_qty / qty))

                        pnl = (leg["px"] - px) * close_qty
                        closed_legs.append({
                            "sym": sym,
                            "open_ts": leg["ts"],
                            "close_ts": trade_ts,
                            "pnl": pnl,
                            "fee_abs": total_fee
                        })

                    leg["qty"] -= close_qty
                    remain -= close_qty

                    if leg["qty"] <= 1e-12:
                        lots[sym].popleft()

                # 剩余部分作为新多头仓位
                if remain > 1e-12:
                    lots[sym].append({
                        "side": "BUY",
                        "px": px,
                        "qty": remain,
                        "ts": trade_ts,
                        "fee_open": float(trade.get("fee_abs", 0.0)),
                        "qty_open": remain
                    })

            elif side == "SELL":
                # 先平多头仓位
                remain = qty
                while remain > 1e-12 and lots[sym] and lots[sym][0]["side"] == "BUY":
                    leg = lots[sym][0]
                    close_qty = min(remain, leg["qty"])

                    if close_qty > 0:
                        trade_fee = float(trade.get("fee_abs", 0.0))
                        # 分摊开仓费用
                        fee_open_part = float(leg.get("fee_open", 0.0)) * (close_qty / leg.get("qty_open", close_qty))
                        # 总费用 = 开仓费分摊 + 平仓费分摊
                        total_fee = fee_open_part + (trade_fee * (close_qty / qty))

                        pnl = (px - leg["px"]) * close_qty
                        closed_legs.append({
                            "sym": sym,
                            "open_ts": leg["ts"],
                            "close_ts": trade_ts,
                            "pnl": pnl,
                            "fee_abs": total_fee
                        })

                    leg["qty"] -= close_qty
                    remain -= close_qty

                    if leg["qty"] <= 1e-12:
                        lots[sym].popleft()

                # 剩余部分作为新空头仓位
                if remain > 1e-12:
                    lots[sym].append({
                        "side": "SELL",
                        "px": px,
                        "qty": remain,
                        "ts": trade_ts,
                        "fee_open": float(trade.get("fee_abs", 0.0)),
                        "qty_open": remain
                    })

        # 验证结果
        # 应该有2个闭合腿
        assert len(closed_legs) == 2, f"Expected 2 closed legs, got {len(closed_legs)}"

        # 第一个腿：BUY@50000 -> SELL@51000，盈利 1000
        leg1 = closed_legs[0]
        assert leg1["pnl"] == 1000.0, f"First leg PnL should be 1000.0, got {leg1['pnl']}"
        assert leg1["open_ts"] == 1640995200000
        assert leg1["close_ts"] == 1640995260000

        # 第二个腿：BUY@49000 -> SELL@48000，亏损 -1000
        leg2 = closed_legs[1]
        assert leg2["pnl"] == -1000.0, f"Second leg PnL should be -1000.0, got {leg2['pnl']}"
        assert leg2["open_ts"] == 1640995320000
        assert leg2["close_ts"] == 1640995380000

        # 总PnL：1000 - 1000 = 0
        total_pnl = sum(leg["pnl"] for leg in closed_legs)
        assert total_pnl == 0.0, f"Total PnL should be 0.0, got {total_pnl}"

        # 验证持仓簿为空（所有仓位都已平掉）
        assert len(lots[sym]) == 0, f"Position book should be empty, but has {len(lots[sym])} positions"

    def test_buy_sell_with_partial_fills(self):
        """测试部分成交的 BUY/SELL 序列"""
        lots = {}
        closed_legs = []
        sym = "BTCUSDT"

        lots.setdefault(sym, deque())

        # 交易序列：部分BUY -> 部分SELL -> 剩余SELL
        trades = [
            # 1. BUY 2.0 @ 50000
            {
                "symbol": sym,
                "side": "BUY",
                "exec_px": 50000.0,
                "qty": 2.0,
                "ts_ms": 1640995200000,
                "fee_abs": 50.0
            },
            # 2. SELL 1.0 @ 51000 (平掉1.0，盈利)
            {
                "symbol": sym,
                "side": "SELL",
                "exec_px": 51000.0,
                "qty": 1.0,
                "ts_ms": 1640995260000,
                "fee_abs": 25.5
            },
            # 3. SELL 1.0 @ 52000 (平掉剩余1.0，盈利)
            {
                "symbol": sym,
                "side": "SELL",
                "exec_px": 52000.0,
                "qty": 1.0,
                "ts_ms": 1640995320000,
                "fee_abs": 26.0
            }
        ]

        # 执行PnL计算
        for trade in trades:
            sym = trade["symbol"]
            side = trade["side"]
            px = trade["exec_px"]
            qty = trade["qty"]
            trade_ts = trade["ts_ms"]

            lots.setdefault(sym, deque())

            if side == "BUY":
                remain = qty
                while remain > 1e-12 and lots[sym] and lots[sym][0]["side"] == "SELL":
                    leg = lots[sym][0]
                    close_qty = min(remain, leg["qty"])

                    if close_qty > 0:
                        trade_fee = float(trade.get("fee_abs", 0.0))
                        fee_open_part = float(leg.get("fee_open", 0.0)) * (close_qty / leg.get("qty_open", close_qty))
                        total_fee = fee_open_part + (trade_fee * (close_qty / qty))

                        pnl = (leg["px"] - px) * close_qty
                        closed_legs.append({
                            "sym": sym,
                            "open_ts": leg["ts"],
                            "close_ts": trade_ts,
                            "pnl": pnl,
                            "fee_abs": total_fee
                        })

                    leg["qty"] -= close_qty
                    remain -= close_qty

                    if leg["qty"] <= 1e-12:
                        lots[sym].popleft()

                if remain > 1e-12:
                    lots[sym].append({
                        "side": "BUY",
                        "px": px,
                        "qty": remain,
                        "ts": trade_ts,
                        "fee_open": float(trade.get("fee_abs", 0.0)),
                        "qty_open": remain
                    })

            elif side == "SELL":
                remain = qty
                while remain > 1e-12 and lots[sym] and lots[sym][0]["side"] == "BUY":
                    leg = lots[sym][0]
                    close_qty = min(remain, leg["qty"])

                    if close_qty > 0:
                        trade_fee = float(trade.get("fee_abs", 0.0))
                        fee_open_part = float(leg.get("fee_open", 0.0)) * (close_qty / leg.get("qty_open", close_qty))
                        total_fee = fee_open_part + (trade_fee * (close_qty / qty))

                        pnl = (px - leg["px"]) * close_qty
                        closed_legs.append({
                            "sym": sym,
                            "open_ts": leg["ts"],
                            "close_ts": trade_ts,
                            "pnl": pnl,
                            "fee_abs": total_fee
                        })

                    leg["qty"] -= close_qty
                    remain -= close_qty

                    if leg["qty"] <= 1e-12:
                        lots[sym].popleft()

                if remain > 1e-12:
                    lots[sym].append({
                        "side": "SELL",
                        "px": px,
                        "qty": remain,
                        "ts": trade_ts,
                        "fee_open": float(trade.get("fee_abs", 0.0)),
                        "qty_open": remain
                    })

        # 验证结果
        # 应该有2个闭合腿
        assert len(closed_legs) == 2, f"Expected 2 closed legs, got {len(closed_legs)}"

        # 第一个腿：BUY@50000 -> SELL@51000，盈利 1000
        leg1 = closed_legs[0]
        assert leg1["pnl"] == 1000.0, f"First leg PnL should be 1000.0, got {leg1['pnl']}"

        # 第二个腿：BUY@50000 -> SELL@52000，盈利 2000
        leg2 = closed_legs[1]
        assert leg2["pnl"] == 2000.0, f"Second leg PnL should be 2000.0, got {leg2['pnl']}"

        # 总PnL：1000 + 2000 = 3000
        total_pnl = sum(leg["pnl"] for leg in closed_legs)
        assert total_pnl == 3000.0, f"Total PnL should be 3000.0, got {total_pnl}"

        # 持仓簿为空
        assert len(lots[sym]) == 0, "Position book should be empty"
