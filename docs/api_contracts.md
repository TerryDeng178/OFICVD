# API 契约文档

**单一事实来源（SSoT）**：本文档为所有API契约的权威定义。

**版本**：v1.0  
**最后更新**：2025-11-12

---

## 目录

1. [数据契约](#数据契约)
   - [输入（HARVEST → 特征层）](#31-输入harvest--特征层)
   - [输出（特征层 → CORE_ALGO）](#32-输出特征层--core_algo)
   - [信号输出（CORE_ALGO → 风控/执行）](#33-core_algo--风控执行信号输出)
2. [MCP 接口契约](#mcp-接口契约)
3. [风控契约 (risk_contract/v1)](#风控契约-risk_contractv1)
4. [执行层契约 (executor_contract/v1)](#执行层契约-executor_contractv1)
5. [适配器层契约 (adapter_contract/v1)](#适配器层契约-adapter_contractv1)
6. [契约版本索引](#契约版本索引)

---

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

## 风控契约 (risk_contract/v1)

### 4.1 订单上下文 (OrderCtx v1)

**单一事实来源**：字段定义以本文档为准，版本标识为 `risk_contract/v1`

```yaml
symbol: string            # 交易对，如 BTCUSDT（大写，统一）
side: "buy"|"sell"       # 方向：buy/sell
order_type: "market"|"limit"
qty: float               # 张/币数量（与交易所精度、步长对齐）
price: float|null        # 限价单必填
account_mode: "isolated"|"cross"
max_slippage_bps: float  # 允许滑点上限 bps
ts_ms: int               # 本地决定时间戳（ms）
regime: string           # 来自策略层的场景标签（normal/quiet/turbulent/...）
guards:
  spread_bps: float      # 价差（基点），与策略层一致性对齐
  event_lag_sec: float   # 事件延迟（秒），与策略层一致性对齐
  activity_tpm: float    # 每分钟交易数，与策略层一致性对齐
context:
  fees_bps: float        # 手续费（基点）
  maker_ratio_target: float  # 目标maker比例
  recent_pnl: float      # 最近PnL
```

**字段说明**：
- `guards` 字段与策略层一致性对齐；Fusion/Consistency 等信号由策略层聚合，不在风控层重复计算
- `regime` 由 StrategyModeManager 注入，反映当前市场状态
- 所有价格/数量字段需与交易所精度对齐（通过 `normalize_quantity` 等适配器方法）

### 4.2 风控决策 (RiskDecision v1)

```yaml
passed: bool              # 是否通过风控检查
reason_codes: string[]    # 拒绝原因码，如 ["spread_too_wide","lag_exceeds_cap","market_inactive","notional_exceeds_limit","symbol_qty_exceeds_limit"]
adjustments:
  max_qty: float|null    # 建议的最大数量（如果超过限制）
  price_cap: float|null  # 限价上限（根据滑点护栏计算）
metrics:
  check_latency_ms: float  # 风控检查耗时（毫秒）
shadow_compare:
  legacy_passed: bool    # legacy风控判定结果（shadow模式）
  parity: bool          # 与legacy判定是否一致（shadow模式）
```

**拒绝原因码说明**：
- `spread_too_wide`: 价差超过 `spread_bps_max` 阈值
- `lag_exceeds_cap`: 事件延迟超过 `lag_sec_cap` 阈值
- `market_inactive`: 市场活跃度低于 `activity_min_tpm` 阈值
- `notional_exceeds_limit`: 名义额超过 `max_notional_usd` 限制
- `symbol_qty_exceeds_limit`: 单币种数量超过 `symbol_limits` 限制

### 4.3 接口定义

**函数签名**：
```python
def pre_order_check(order_ctx: OrderCtx) -> RiskDecision:
    """下单前置检查
    
    Args:
        order_ctx: 订单上下文（v1）
        
    Returns:
        风控决策（v1）
    """
    pass
```

**使用示例**：
```python
from mcp.strategy_server.risk import pre_order_check, OrderCtx

# 构建订单上下文
order_ctx = OrderCtx(
    symbol="BTCUSDT",
    side="buy",
    order_type="market",
    qty=0.001,
    price=70325.0,
    ts_ms=1730790000456,
    regime="active",
    guards={
        "spread_bps": 1.2,
        "event_lag_sec": 0.04,
        "activity_tpm": 15.0,
    },
    context={
        "fees_bps": 4.0,
        "maker_ratio_target": 0.6,
        "recent_pnl": 100.0,
    }
)

# 执行风控检查
decision = pre_order_check(order_ctx)

if decision.passed:
    print(f"Order allowed. Adjustments: {decision.adjustments}")
else:
    print(f"Order denied. Reasons: {decision.reason_codes}")
```

### 4.4 配置对齐

**统一配置树**（`config/defaults.yaml`）：
```yaml
components:
  strategy:
    risk:
      enabled: ${RISK_INLINE_ENABLED:false}  # 环境变量控制，默认关闭
      guards:
        spread_bps_max: 8.0      # 价差上限（bps）
        lag_sec_cap: 1.5         # 延迟上限（秒）
        activity_min_tpm: 10.0   # 最小活跃度（每分钟交易数）
      position:
        max_notional_usd: 20000  # 最大名义额（USD）
        max_leverage: 5          # 最大杠杆
        symbol_limits:
          BTCUSDT: { max_qty: 0.5 }
      stop_rules:
        take_profit_bps: 40      # 止盈（bps）
        stop_loss_bps: 25        # 止损（bps）
      shadow_mode:
        compare_with_legacy: true  # 是否启用shadow对比
        diff_alert: ">=1%"         # 不一致占比阈值
```

**参数映射表**（旧 → 新）：
| 旧模块/键 | 新模块/键 | 口径说明 |
|-----------|-----------|----------|
| `ofi_risk_server.max_slippage_bps` | `strategy.risk.guards.spread_bps_max` | 均以 **bps** 表示 |
| `ofi_risk_server.lag_cap_seconds` | `strategy.risk.guards.lag_sec_cap` | 秒 |
| `strategy_manager.params.*` | `strategy.risk.position.*` | 场景参数通过 StrategyMode 注入 |

> **重要**：融合/一致性阈值（如 `fuse_buy/sell`, `min_consistency`）继续在信号侧维护，不在风控层重定义。

### 4.5 兼容性与回滚

**开关控制**：
- `RISK_INLINE_ENABLED=false`：默认关闭，回退到 legacy `ofi_risk_server`（只读）
- `RISK_INLINE_ENABLED=true`：启用内联风控，`strategy_server` 内置风控模块

**Shadow 对比**：
- 内联风控与 legacy 输出做逐单对比，生成 `risk_shadow.jsonl`
- 一致率阈值：≥99%（不一致占比 ≤1%）
- 超过阈值时告警，但不阻断执行

**快速回滚**：
- 仅需置 `RISK_INLINE_ENABLED=false` 并重启 `strategy_server`
- legacy 只读服务保留在 `legacy/` 目录

---

## 执行层契约 (executor_contract/v1) {#执行层契约-executor_contractv1}

**SSoT锚点**：本文档为执行层契约的单一事实来源，版本标识为 `executor_contract/v1`。

### 5.1 订单上下文 (OrderCtx v1)

**单一事实来源**：字段定义以本文档为准，版本标识为 `executor_contract/v1`

**注意**：与 `risk_contract/v1` 的 `OrderCtx` 对齐，但增加了执行层特有的字段。

```yaml
# 基础订单字段
client_order_id: string      # 客户端订单ID（幂等键：hash(signal_row_id|ts_ms|side|qty|px)）
symbol: string               # 交易对，如 BTCUSDT（大写，统一）
side: "buy"|"sell"          # 方向：buy/sell
qty: float                   # 数量（与交易所精度、步长对齐）
order_type: "market"|"limit" # 订单类型
price: float|null            # 限价单价格
tif: "GTC"|"IOC"|"FOK"      # 订单有效期

# 时间戳字段
ts_ms: int                   # 本地决定时间戳（ms）
event_ts_ms: int|null        # 事件时间戳（ms，来自上游信号）

# 上游状态字段（来自信号层）
signal_row_id: string|null    # 信号行ID（用于追溯）
regime: string|null          # 市场状态：active/quiet
scenario: string|null        # 场景标识（2x2场景：HH/HL/LH/LL）
warmup: bool                 # 是否在暖启动阶段
guard_reason: string|null    # 护栏原因（逗号分隔，如"warmup,low_consistency"）
consistency: float|null      # 一致性分数（0.0-1.0）
weak_signal_throttle: bool   # 是否因弱信号被节流

# 交易所约束字段
tick_size: float|null        # 价格精度（最小变动单位）
step_size: float|null        # 数量精度（最小变动单位）
min_notional: float|null      # 最小名义价值

# 成本字段
costs_bps: float|null        # 预期成本（基点）

# 元数据
metadata: object             # 其他上下文信息
```

**字段说明**：
- `client_order_id`：幂等键，建议格式：`hash(signal_row_id|ts_ms|side|qty|px)`
- `warmup`：来自信号层的暖启动标志，执行层应据此拒单
- `guard_reason`：来自信号层的护栏原因，执行层应据此决策
- `consistency`：一致性分数，低于阈值时执行层应降采样或拒单
- `tick_size/step_size`：交易所精度约束，执行层应据此对齐价格/数量

### 5.2 执行结果 (ExecResult v1)

```yaml
status: "accepted"|"rejected"  # 执行状态
client_order_id: string        # 客户端订单ID
exchange_order_id: string|null # 交易所订单ID
reject_reason: string|null     # 拒绝原因（如果被拒绝）
latency_ms: int|null           # 延迟（ms，从提交到ACK）
slippage_bps: float|null       # 滑点（基点）
rounding_applied: object|null  # 价格/数量对齐调整（price_diff, qty_diff）
sent_ts_ms: int|null           # 发送时间戳（ms）
ack_ts_ms: int|null            # ACK时间戳（ms）
meta: object                   # 其他元数据
```

**拒绝原因说明**：
- `warmup`: 暖启动阶段，拒单
- `guard_active`: 护栏激活，拒单
- `low_consistency`: 一致性低于阈值，拒单或降采样
- `weak_signal_throttle`: 弱信号节流，拒单
- `exchange_rejected`: 交易所拒绝
- `network_error`: 网络错误
- `rate_limit`: 速率限制

### 5.3 撤销结果 (CancelResult v1)

```yaml
success: bool                  # 是否成功
client_order_id: string        # 客户端订单ID
exchange_order_id: string|null # 交易所订单ID
reason: string|null            # 失败原因（如果失败）
latency_ms: int|null           # 延迟（ms）
cancel_ts_ms: int|null         # 撤销时间戳（ms）
meta: object                   # 其他元数据
```

### 5.4 修改结果 (AmendResult v1)

```yaml
success: bool                  # 是否成功
client_order_id: string        # 客户端订单ID
exchange_order_id: string|null # 交易所订单ID
reason: string|null            # 失败原因（如果失败）
latency_ms: int|null           # 延迟（ms）
amend_ts_ms: int|null          # 修改时间戳（ms）
meta: object                   # 其他元数据
```

**注意**：修改功能当前未实现，此契约为预留。

### 5.5 接口定义

**IExecutor接口**：
```python
class IExecutor(ABC):
    """执行器抽象接口"""
    
    @abstractmethod
    def prepare(self, cfg: Dict[str, Any]) -> None:
        """初始化执行器"""
        pass
    
    @abstractmethod
    def submit(self, order: Order) -> str:
        """提交订单（基础接口，向后兼容）
        
        Returns:
            broker_order_id: 交易所订单ID
        """
        pass
    
    def submit_with_ctx(self, order_ctx: OrderCtx) -> ExecResult:
        """提交订单（扩展接口，包含上游状态）
        
        Returns:
            ExecResult: 执行结果
        """
        pass
    
    @abstractmethod
    def cancel(self, order_id: str) -> bool:
        """撤销订单（基础接口，向后兼容）"""
        pass
    
    def cancel_with_result(self, order_id: str) -> CancelResult:
        """撤销订单（扩展接口，返回详细结果）"""
        pass
    
    @abstractmethod
    def fetch_fills(self, since_ts_ms: Optional[int] = None) -> List[Fill]:
        """获取成交记录"""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> float:
        """获取持仓"""
        pass
    
    def flush(self) -> None:
        """刷新缓存"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭执行器"""
        pass
```

### 5.6 执行事件Schema (ExecLogEvent v1)

**JSONL格式**：`ready/execlog/{symbol}/exec_YYYYMMDD_HHMM.jsonl`

**Outbox模式**：采用 `spool/execlog/{symbol}/exec_YYYYMMDD_HHMM.part` → `ready/execlog/{symbol}/exec_YYYYMMDD_HHMM.jsonl` 原子发布

```json
{
  "ts_ms": 1731379200123,
  "symbol": "BTCUSDT",
  "event": "submit|ack|partial|filled|canceled|rejected",
  "signal_row_id": "signal_1234567890",
  "client_order_id": "C123",
  "exchange_order_id": "E456",
  "side": "buy",
  "qty": 0.01,
  "px_intent": 70321.5,
  "px_sent": 70321.5,
  "px_fill": 70322.0,
  "rounding_diff": {"price_diff": 0.0, "qty_diff": 0.0},
  "slippage_bps": 0.71,
  "status": "filled",
  "reason": null,
  "sent_ts_ms": 1731379200123,
  "ack_ts_ms": 1731379200135,
  "fill_ts_ms": 1731379200145,
  "meta": {
    "mode": "backtest|testnet|live",
    "latency_ms": 12,
    "warmup": false,
    "guard_reason": null,
    "consistency": 0.85,
    "scenario": "HH"
  }
}
```

**字段说明**：
- `signal_row_id`: 信号行ID，用于追溯上游信号
- `px_intent`: 意图价格（来自策略层）
- `px_sent`: 发送价格（对齐后）
- `px_fill`: 成交价格
- `rounding_diff`: 对齐调整差额
- `slippage_bps`: 滑点（基点）

### 5.7 JSON Schema验证

**已实现**：所有执行实现（Backtest/Live/Testnet）对齐同一Pydantic/Schema校验。

**验证点**：
- OrderCtx字段完整性
- ExecResult状态一致性
- 价格/数量精度对齐
- 时间戳有效性

**参考实现**：
- `src/alpha_core/executors/base_executor.py`：数据类定义（OrderCtx, ExecResult, CancelResult, AmendResult）
- `src/alpha_core/executors/exec_log_sink_outbox.py`：事件Schema（ExecLogEvent v1）

### 5.8 配置对齐

**统一配置树**（`config/defaults.yaml`）：
```yaml
executor:
  mode: backtest   # backtest|testnet|live
  sink: jsonl      # jsonl|sqlite|dual（与全局V13_SINK一致）
  output_dir: ./runtime
  symbols: [BTCUSDT]
  slippage_bps: 1.0      # backtest用
  fee_bps: 1.93          # 成本估计，回测/测试网默认
  max_parallel_orders: 4
  order_size_usd: 100
  tif: GTC
  order_type: market
```

---

## 适配器层契约 (adapter_contract/v1) {#适配器层契约-adapter_contractv1}

**SSoT锚点**：本文档为适配器层契约的单一事实来源，版本标识为 `adapter_contract/v1`。

**最后更新**：2025-11-12

**单一事实来源**：字段定义以本文档为准，版本标识为 `adapter_contract/v1`

### 6.1 BaseAdapter 接口契约

BaseAdapter 统一固化执行落地的底层契约，消除 `backtest/testnet/live` 的分支差异。

**职责边界**：
- **IExecutor**：订单生命周期/状态机、事件汇聚、将适配器回执转成统一事件并落地（execlog）
- **BaseAdapter**：交易规则/精度规范化、限频/重试/幂等、错误码统一映射、与交易所交互

**组合/依赖注入**：BaseAdapter 作为 IExecutor 的依赖，通过 `make_adapter()` 工厂创建。

```python
# adapters/base_adapter.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class AdapterOrder:
    client_order_id: str
    symbol: str
    side: str  # buy|sell
    qty: float
    price: Optional[float] = None
    order_type: str = "market"  # market|limit
    tif: str = "GTC"  # GTC|IOC|FOK
    ts_ms: int = 0

@dataclass
class AdapterResp:
    ok: bool
    code: str          # 统一错误码（见下）
    msg: str
    broker_order_id: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

class BaseAdapter(ABC):
    @abstractmethod
    def kind(self) -> str: ...  # backtest|testnet|live
    
    @abstractmethod
    def load_rules(self, symbol: str) -> Dict[str, Any]: ...
    
    @abstractmethod
    def normalize(self, symbol: str, qty: float, price: Optional[float]) -> Dict[str, float]: ...
    
    @abstractmethod
    def submit(self, order: AdapterOrder) -> AdapterResp: ...
    
    @abstractmethod
    def cancel(self, symbol: str, broker_order_id: str) -> AdapterResp: ...
    
    @abstractmethod
    def fetch_fills(self, symbol: str, since_ts_ms: Optional[int]) -> List[Dict[str, Any]]: ...
```

### 6.2 统一错误码（Code Space）

| 代码                 | 含义                             | 可重试    | 典型来源        |
| ------------------ | ------------------------------ | ------ | ----------- |
| `OK`               | 成功                             | -      | -           |
| `E.PARAMS`         | 参数不合法（precision/step/notional） | 否      | 本地校验/交易所400 |
| `E.RULES.MISS`     | 交易规则缺失/过期                      | 是（刷新后） | 本地缓存过期      |
| `E.RATE.LIMIT`     | 触发限频                           | 是（退避）  | 交易所429/418  |
| `E.NETWORK`        | 网络/超时                          | 是（退避）  | TCP/HTTP 超时 |
| `E.BROKER.REJECT`  | 交易所拒绝（余额/风险）                   | 否      | 交易所业务拒绝     |
| `E.STATE.CONFLICT` | 状态竞争/重复撤单                      | 否      | 重复请求        |
| `E.UNKNOWN`        | 未分类错误                          | 视情况    | 其他          |

**统一映射**：Testnet/Live 返回码 → 上表；Backtest 仅会返回 `OK` 或 `E.PARAMS`。

### 6.3 错误码 → 状态机映射

**映射规则**（在 IExecutor 中实现）：
- `OK` → `ACK`（后续可能变为 `PARTIAL`/`FILLED`）
- `E.PARAMS` / `E.BROKER.REJECT` / `E.STATE.CONFLICT` → `REJECTED`
- `E.RATE.LIMIT` / `E.NETWORK` / `E.RULES.MISS` → `REJECTED`（适配器已重试，超出上限）

**重试策略**：
- **策略**：指数退避（`base=200ms`，`factor=2.0`，`jitter±25%`），最大 `retries=5`
- **触发**：`E.NETWORK`、`E.RATE.LIMIT`、`E.RULES.MISS`（先刷新规则再重放）
- **幂等**：`client_order_id` 作为幂等键，本地 `idempotency_cache(ttl=10m)` 屏蔽重放副作用
- **注意**：重试策略仅在适配器层，IExecutor 不做二次重试

### 6.4 节流与并发

**令牌桶节流**：
- `capacity=burst`，`fill_rate=rps`
- **默认键**：`adapter.rate_limit.{place/cancel/query}.rps|burst`
- **全局并发**：`max_inflight_orders`，拒绝时返回 `E.RATE.LIMIT` 并记录

### 6.5 数量/精度规范化

**规范化顺序**：
1. `qty = floor(qty/qty_step)*qty_step`
2. `price = round_to_tick(price, price_tick)`（限价单）
3. `notional = qty * (price or mark_price)`，校验 `>= min_notional`
4. 边界处理：若 `qty < qty_min` → `E.PARAMS`

**支持 USD名义下单**：`order_size_usd / mark_price → qty`。

### 6.6 适配器事件Schema (AdapterEvent v1)

**JSONL格式**：`ready/adapter/{symbol}/adapter_event-YYYYMMDD-HH.jsonl`

**SQLite格式**：`adapter_events` 表（WAL模式）

```json
{
  "ts_ms": 1731379200456,
  "mode": "testnet",
  "symbol": "BTCUSDT",
  "event": "submit|cancel|rules.refresh|retry|rate.limit",
  "order": {
    "id": "C123",
    "side": "buy",
    "qty": 0.01,
    "type": "market"
  },
  "resp": {
    "ok": true,
    "code": "OK",
    "broker_order_id": "123456"
  },
  "meta": {
    "latency_ms": 87,
    "retries": 1
  }
}
```

**字段说明**：
- `mode`: 适配器模式（backtest|testnet|live）
- `event`: 事件类型（submit|cancel|rules.refresh|retry|rate.limit）
- `order`: 订单信息（可选）
- `resp`: 适配器响应（可选）
- `meta`: 元数据（延迟、重试次数等）

### 6.7 配置对齐

**统一配置树**（`config/defaults.yaml`）：
```yaml
adapter:
  impl: backtest  # backtest|testnet|live（如果未设置，从executor.mode推断）
  rate_limit:
    place: { rps: 8, burst: 16 }
    cancel: { rps: 5, burst: 10 }
    query: { rps: 10, burst: 20 }
  max_inflight_orders: 32
  rules_ttl_sec: 300
  idempotency_ttl_sec: 600
  order_size_usd: 100
  tif: GTC
  order_type: market
  retry:
    max_retries: 5
    base_delay_ms: 200
    factor: 2.0
    jitter_pct: 0.25
```

**配置一致性**：
- `executor.mode` 为单一权威
- `adapter.impl` 默认跟随 `executor.mode`
- 如果强行覆盖，会进行一致性校验并告警

**环境变量**：
- `V13_SINK`：Sink类型（jsonl|sqlite），与全局一致
- `V13_OUTPUT_DIR`：输出目录，与全局一致
- `ADAPTER_IMPL`：适配器实现（可选，覆盖配置）

### 6.8 参考实现

- `src/alpha_core/adapters/base_adapter.py`：BaseAdapter 抽象接口
- `src/alpha_core/adapters/backtest_adapter.py`：回测适配器
- `src/alpha_core/adapters/testnet_adapter.py`：测试网适配器
- `src/alpha_core/adapters/live_adapter.py`：实盘适配器
- `src/alpha_core/executors/adapter_integration.py`：适配器集成工具（错误码映射、状态机转换）

---

## 契约版本索引

### 当前版本
- `risk_contract/v1`: 风控契约（A1完成）
- `executor_contract/v1`: 执行层契约（A2完成）
- `adapter_contract/v1`: 适配器层契约（A3完成）

### 版本兼容性
- 所有契约采用向后兼容的扩展方式
- 新增字段均为可选字段
- 旧接口保留，新接口通过扩展方法提供

### JSON Schema校验状态

**已实现**：
- ✅ `risk_contract/v1`: JSON Schema强校验（硬闸）已落地（A1完成）
- ✅ `executor_contract/v1`: JSON Schema强校验（硬闸）已落地（A2完成）
- ✅ `adapter_contract/v1`: 适配器层契约已落地（A3完成）

**统一口径**：所有契约均采用Pydantic/Schema校验，确保数据一致性。

