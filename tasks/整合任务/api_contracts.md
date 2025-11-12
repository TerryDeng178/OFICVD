
# API 契约（摘录）

## Signals（示例）
```json
{
  "signal_id": "ts_1731400000123_0001",
  "symbol": "BTCUSDT",
  "ts_ms": 1731400000123,
  "confirm": true,
  "gating": "PASS",
  "regime": "maker_first",
  "score": 0.73,
  "expiry_ms": 800
}
```

## Executions（示例）
```json
{
  "order_id": "ord_1731400000456_0001",
  "signal_id": "ts_1731400000123_0001",
  "state": "FILLED",
  "filled_qty": 0.0123,
  "avg_price": 98765.4,
  "fee_bps": 1.9
}
```
