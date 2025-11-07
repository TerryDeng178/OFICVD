# API 契约文档

## 数据契约

### 3.1 输入（HARVEST → 特征层）

统一 Row Schema，支持以下数据源：
- `aggTrade`: 聚合成交
- `bookTicker`: 最优买卖价
- `depth`: 订单簿深度（@100ms）

```json
{
  "ts_ms": 1730790000123,
  "symbol": "BTCUSDT",
  "src": "aggTrade|bookTicker|depth",
  "price": 70321.5,
  "qty": 0.01,
  "side": "buy|sell|null",
  "bid": 70321.4,
  "ask": 70321.6,
  "best_spread_bps": 1.4,
  "bids": [[70321.4, 10.5], [70321.3, 8.2], ...],
  "asks": [[70321.6, 11.2], [70321.7, 9.5], ...],
  "meta": { "latency_ms": 12, "recv_ts_ms": 1730790000125 }
}
```

**字段说明**：
- `ts_ms`: 事件时间戳（毫秒，UTC）
- `symbol`: 交易对符号（大写，如 "BTCUSDT"）
- `src`: 数据源类型
- `price`: 成交价格（aggTrade/trade 时有效）
- `qty`: 成交数量（aggTrade/trade 时有效）
- `side`: 买卖方向（"buy"/"sell"/null）
- `bid`: 最优买价（bookTicker/depth 时有效）
- `ask`: 最优卖价（bookTicker/depth 时有效）
- `best_spread_bps`: 最优价差（基点）
- `bids`: 买档列表 [[价格, 数量], ...]（最多5档）
  - **排序要求**: 必须按价格从高到低排序（`bids[0][0]` 为最高买价）
  - 如输入未保证顺序，实现侧会先排序再取前 5 档
- `asks`: 卖档列表 [[价格, 数量], ...]（最多5档）
  - **排序要求**: 必须按价格从低到高排序（`asks[0][0]` 为最低卖价）
  - 如输入未保证顺序，实现侧会先排序再取前 5 档

### 3.2 输出（特征层 → CORE_ALGO）

FeatureRow Schema，包含 OFI/CVD/FUSION/DIVERGENCE 计算结果：

```json
{
  "ts_ms": 1730790000456,
  "symbol": "BTCUSDT",
  "z_ofi": 1.8,
  "z_cvd": 0.9,
  "price": 70325.1,
  "lag_sec": 0.04,
  "spread_bps": 1.2,
  "fusion_score": 0.73,
  "consistency": 0.42,
  "dispersion": 0.9,
  "sign_agree": 1,
  "div_type": null,
  "activity": { "tps": 2.3 },
  "warmup": false,
  "signal": "neutral"
}
```

**字段说明**：
- `ts_ms`: 时间戳（毫秒，UTC）
- `symbol`: 交易对符号
- `z_ofi`: OFI Z-score（标准化后的订单流不平衡）
- `z_cvd`: CVD Z-score（标准化后的累积成交量差）
- `price`: 当前价格
- `lag_sec`: 滞后时间（秒，事件时间与处理时间的差）
- `spread_bps`: 价差（基点）
- `fusion_score`: 融合分数（OFI 和 CVD 的加权融合）
- `consistency`: 一致性分数（OFI 和 CVD 方向一致性）
- `dispersion`: 离散度（OFI 和 CVD 的离散程度）
- `sign_agree`: 符号一致性（1: 同向, -1: 反向）
- `div_type`: 背离类型（null/"bull_div"/"bear_div"/"hidden_bull"/"hidden_bear"/"ofi_cvd_conflict"）
- `activity`: 活动度指标（如 `tps`: 每秒交易数）
- `warmup`: 是否在暖启动阶段（true/false）
- `signal`: 信号类型（"neutral"/"buy"/"sell"/"strong_buy"/"strong_sell"）

**字段命名规范**：
- 全部使用小写蛇形命名（snake_case）
- 禁止随意更名，扩展字段遵循相同规范
- 以后仅追加字段，不移除/重命名现有字段

### 3.3 输出样例（features.jsonl）

```json
{"ts_ms":1730790000456,"symbol":"BTCUSDT","z_ofi":1.2,"z_cvd":0.8,"price":70325.1,"lag_sec":0.04,"spread_bps":1.2,"fusion_score":0.66,"consistency":0.41,"dispersion":0.4,"sign_agree":1,"div_type":null,"activity":{"tps":2.3},"warmup":false,"signal":"neutral"}
{"ts_ms":1730790000556,"symbol":"BTCUSDT","z_ofi":1.4,"z_cvd":0.9,"price":70326.0,"lag_sec":0.03,"spread_bps":1.1,"fusion_score":0.72,"consistency":0.47,"dispersion":0.5,"sign_agree":1,"div_type":null,"activity":{"tps":2.5},"warmup":false,"signal":"neutral"}
```

### 3.3 CORE_ALGO → 风控/执行（信号输出）
```json
{
  "ts_ms": 1730790000456,
  "symbol": "BTCUSDT",
  "score": 1.72,
  "z_ofi": 1.9,
  "z_cvd": 1.3,
  "regime": "active",
  "div_type": null,
  "confirm": true,
  "gating": false,
  "signal_type": "strong_buy",
  "guard_reason": null
}
```

**字段说明**：
- `signal_type`: 输出信号类别（`strong_buy|buy|sell|strong_sell|neutral|pending`）
- `guard_reason`: 若被护栏拦截，记录首个原因；放行时为 `null`
- 其余字段延续 FeatureRow 契约

**落地路径**：
- JSONL：`<output_dir>/ready/signal/{symbol}/signals_YYYYMMDD_HHMM.jsonl`
- SQLite：`<output_dir>/signals.db`（表 `signals`，列与 JSONL 对齐）

## MCP 接口契约

### FeaturePipe 接口

**类**: `alpha_core.microstructure.feature_pipe.FeaturePipe`

**方法**：
- `__init__(config, symbols, sink, output_dir, dedupe_ms, max_lag_sec)`: 初始化
- `on_row(row: Dict) -> Optional[Dict]`: 处理单条输入行，返回 FeatureRow
- `flush()`: 刷新缓冲区
- `close()`: 关闭资源

**使用示例**：
```python
from alpha_core.microstructure import FeaturePipe
import yaml

# 加载配置
with open("config/defaults.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 创建 FeaturePipe
pipe = FeaturePipe(
    config=config,
    symbols=["BTCUSDT", "ETHUSDT"],
    sink="jsonl",
    output_dir="./runtime"
)

# 处理数据行
feature_row = pipe.on_row(input_row)

# 关闭
pipe.flush()
pipe.close()
```

## 详细契约

### FeaturePipe 输入输出契约

**输入数据源**：
- HARVEST 采集的 Parquet/JSONL 文件
- 统一 Row Schema（见 3.1）

**输出数据格式**：
- JSONL：每行一个 JSON 对象，使用稳定序列化（sort_keys=True）
- SQLite：features 表，字段与 JSONL 对应

**字段完整性**：
- 必需字段：`ts_ms`, `symbol`, `z_ofi`, `z_cvd`, `price`, `lag_sec`, `spread_bps`, `fusion_score`, `consistency`, `dispersion`, `sign_agree`, `div_type`, `activity`, `warmup`, `signal`
- 可选字段：`reason_codes`（降级原因）

### 验证脚本

M2 冒烟测试脚本包含字段验证逻辑，可参考 `scripts/m2_smoke_test.sh` 中的 Python 验证代码。

**字段验证示例**：
```python
required_fields = [
    'ts_ms', 'symbol', 'z_ofi', 'z_cvd', 'price',
    'lag_sec', 'spread_bps', 'fusion_score', 'consistency',
    'dispersion', 'sign_agree', 'div_type', 'activity',
    'warmup', 'signal'
]

# 验证 JSONL 文件
with open('features.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        missing = [f for f in required_fields if f not in data]
        if missing:
            print(f'缺少字段: {missing}')
```

