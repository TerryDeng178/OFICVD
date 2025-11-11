# 策略MCP整合方案 - 深度评估与优化

## 执行摘要

经过全项目深度检阅，对策略MCP整合方案进行全面评估，发现**架构方向正确但需要关键优化**。主要发现：

1. ✅ **架构方向正确**：统一入口、执行层抽象、适配器模式都是正确的设计
2. ⚠️ **集成方式需优化**：需要明确与现有Orchestrator和signal_server的关系
3. ⚠️ **数据流需澄清**：回测模式与实时模式的数据流路径不同，需要分别设计
4. ✅ **代码复用可行**：可以复用现有CoreAlgorithm和TradeSimulator

**结论**：**条件性GO（优化后）** - 在补齐集成方式、数据流设计、与现有服务关系等关键点后，方案可以稳妥推进。

---

## 1. 项目架构深度分析

### 1.1 现有架构特点

#### 1.1.1 Orchestrator编排模式

**关键发现**：
- Orchestrator通过`ProcessSpec`注册和管理MCP服务进程
- 启动顺序：harvest → signal → broker → report
- 关闭顺序：report → broker → signal → harvest（反向）
- 每个MCP服务都是独立进程，通过文件系统通信

**现有MCP服务**：
```python
# orchestrator/run.py 中的注册方式
harvest_spec = ProcessSpec(
    name="harvest",
    cmd=["mcp.harvest_server.app", "--config", str(config_path)],
    ready_probe="log_keyword",
    health_probe="file_count",
)

signal_spec = ProcessSpec(
    name="signal",
    cmd=["mcp.signal_server.app", "--config", str(config_path), "--input", str(features_dir), "--sink", sink_kind],
    ready_probe="file_exists",
    health_probe="file_count",
)

broker_spec = ProcessSpec(
    name="broker",
    cmd=["mcp.broker_gateway_server.app", "--mock", "1"],
    ready_probe="log_keyword",
    health_probe="file_count",
)
```

#### 1.1.2 回测流程（独立路径）

**关键发现**：
- `scripts/replay_harness.py`是独立的回测脚本，不依赖Orchestrator
- 完整流程：DataReader → DataAligner → ReplayFeeder → CoreAlgorithm → TradeSimulator → MetricsAggregator
- ReplayFeeder已经封装了CoreAlgorithm，并处理了_feature_data的传递
- TradeSimulator需要CoreAlgorithm实例（F3功能：退出后冷静期）

**数据流**：
```
历史数据（Parquet/JSONL）
  ↓
DataReader.read_features()
  ↓
ReplayFeeder.feed_features()
  ↓
CoreAlgorithm.process_feature_row() → Signal
  ↓
TradeSimulator.process_signal() → Trade
  ↓
MetricsAggregator.compute_metrics() → Metrics
```

#### 1.1.3 实时流程（Orchestrator编排）

**关键发现**：
- 实时流程通过Orchestrator编排多个MCP服务
- 数据流：harvest_server → FeaturePipe（自动） → signal_server → broker_gateway_server
- signal_server监听features目录，持续处理新文件
- broker_gateway_server监听signals目录，处理信号生成订单

**数据流**：
```
Harvest Server（实时采集）
  ↓ (raw/preview data)
FeaturePipe（自动处理，生成features）
  ↓ (features/*.jsonl)
Signal Server（监听模式，--watch）
  ↓ (signals/*.jsonl 或 signals.db)
Broker Gateway Server（监听信号）
  ↓ (mock_orders.jsonl)
Reporter（生成日报）
```

### 1.2 关键组件分析

#### 1.2.1 CoreAlgorithm（信号生成）

**职责**：
- 处理特征行，生成交易信号
- 门控检查（warmup/spread/lag/consistency/weak_signal）
- 策略模式管理（StrategyModeManager）
- 输出信号包含：`confirm`、`gating_blocked`、`regime`等字段

**关键接口**：
```python
def process_feature_row(self, row: Dict) -> Optional[Dict]:
    """处理特征行，返回信号字典"""
    # 输出包含：ts_ms, symbol, signal_type, confirm, gating_blocked, regime等
```

#### 1.2.2 TradeSimulator（回测执行）

**职责**：
- 处理信号，执行交易（开仓/平仓/反向）
- 持仓管理
- 费用/滑点计算（支持情境化模型）
- PnL计算

**关键接口**：
```python
def process_signal(self, signal: Dict, mid_price: float) -> Optional[Dict]:
    """处理信号，返回交易记录"""
    # 需要CoreAlgorithm实例（F3功能）
```

#### 1.2.3 ReplayFeeder（回测数据流）

**关键发现**：
- 已经封装了CoreAlgorithm
- 处理了_feature_data的传递（包含spread_bps、scenario_2x2等）
- 支持活动度字段注入（trade_rate、quote_rate）

**关键代码**：
```python
# src/alpha_core/backtest/feeder.py
signal = self.algo.process_feature_row(normalized_row)
if signal:
    signal["_feature_data"] = {
        "spread_bps": feature_row.get("spread_bps"),
        "scenario_2x2": feature_row.get("scenario_2x2"),
        # ... 其他字段
    }
```

---

## 2. 方案评估

### 2.1 架构设计评估

#### ✅ 优点

1. **执行层抽象（IExecutor）**
   - ✅ 正确：通过IExecutor接口统一回测和实盘执行逻辑
   - ✅ 避免条件分支：StrategyService只面向接口，不判断模式
   - ✅ 职责清晰：BacktestExecutor封装TradeSimulator，LiveExecutor封装Broker API

2. **适配器模式**
   - ✅ 正确：通过适配器层隔离不同环境
   - ✅ 易于扩展：可以添加新的适配器（如其他交易所）

3. **风控一致性**
   - ✅ 正确：gating/strategy-mode只在CoreAlgorithm判定
   - ✅ 执行层只认结果位：confirm/gating_blocked

#### ⚠️ 需要优化的点

1. **与现有服务的关系不明确**
   - ⚠️ **问题**：策略MCP与signal_server的关系是什么？
     - 是替换signal_server？
     - 还是并行运行（signal_server生成信号，strategy_server执行交易）？
   - ⚠️ **问题**：回测模式是否还需要signal_server？
     - 当前replay_harness.py直接调用CoreAlgorithm，不经过signal_server

2. **数据流设计不完整**
   - ⚠️ **问题**：实时模式的数据流不清晰
     - 方案中`run_live_mode`是占位实现
     - 需要明确：如何从harvest_server获取数据？是否通过signal_server？
   - ⚠️ **问题**：回测模式的数据流
     - 方案中复用replay_harness流程，但StrategyService如何集成？

3. **Orchestrator集成方式不明确**
   - ⚠️ **问题**：策略MCP如何注册到Orchestrator？
     - 是否需要新的ProcessSpec？
     - 启动顺序是什么？
   - ⚠️ **问题**：回测模式是否需要Orchestrator？
     - 当前replay_harness.py是独立脚本，不依赖Orchestrator

### 2.2 实施计划评估

#### ✅ 阶段A（P0清零）- 合理

**任务评估**：
1. ✅ 抽象IExecutor - 正确且必要
2. ✅ 明确BaseAdapter契约 - 正确且必要
3. ✅ gating只在CoreAlgorithm产出 - 正确且必要
4. ✅ 回测行情从features宽表读取 - 正确且必要
5. ✅ 等价性测试套件 - 正确且必要

#### ⚠️ 阶段B/C - 需要补充

**缺失的关键任务**：
1. ⬜ **明确与signal_server的关系**
   - 是否需要替换signal_server？
   - 还是作为新的服务并行运行？
2. ⬜ **设计实时模式数据流**
   - 如何从harvest_server获取数据？
   - 是否通过signal_server的信号？
3. ⬜ **设计Orchestrator集成方式**
   - 如何注册到Orchestrator？
   - 启动顺序和依赖关系

---

## 3. 优化方案

### 3.1 架构优化

#### 3.1.1 明确服务定位

**策略MCP的定位**：
- **回测模式**：独立的回测服务，可以替代`scripts/replay_harness.py`
- **实时模式**：作为新的MCP服务，与signal_server并行运行
  - signal_server：生成信号（CoreAlgorithm）
  - strategy_server：执行交易（IExecutor）

**数据流设计**：

```
回测模式（独立）:
  DataReader → StrategyService
    ├─ CoreAlgorithm (信号生成)
    └─ BacktestExecutor (交易执行)
      └─ TradeSimulator

实时模式（Orchestrator编排）:
  Harvest Server
    ↓ (features)
  Signal Server (生成信号)
    ↓ (signals)
  Strategy Server (执行交易)
    ├─ 读取signals
    ├─ LiveExecutor (交易执行)
    └─ Broker API (Testnet/Live)
```

#### 3.1.2 优化后的目录结构

```
mcp/strategy_server/
├── __init__.py
├── app.py                    # MCP服务器入口
├── strategy_service.py       # 策略服务核心
├── executors/
│   ├── base_executor.py      # IExecutor接口
│   ├── backtest_executor.py  # BacktestExecutor
│   └── live_executor.py      # LiveExecutor
├── adapters/
│   ├── base_adapter.py       # BaseAdapter接口
│   ├── backtest_adapter.py   # BacktestAdapter
│   ├── testnet_adapter.py    # TestnetAdapter
│   └── live_adapter.py       # LiveAdapter
└── modes/                    # 新增：模式处理
    ├── backtest_mode.py      # 回测模式处理（复用replay_harness流程）
    └── live_mode.py          # 实时模式处理（从signals读取）
```

#### 3.1.3 优化后的StrategyService

```python
# mcp/strategy_server/strategy_service.py

class StrategyService:
    """策略服务核心：整合信号生成和交易执行
    
    设计原则：
    1. 回测模式：直接处理feature_row，内部调用CoreAlgorithm和BacktestExecutor
    2. 实时模式：从signals读取信号，只负责执行交易（不生成信号）
    """
    
    def __init__(self, config: Dict, adapter: BaseAdapter, executor: Optional[IExecutor] = None, mode: str = "backtest"):
        """初始化策略服务
        
        Args:
            config: 配置字典
            adapter: 适配器实例
            executor: 执行器实例（可选）
            mode: 运行模式（backtest/live）
        """
        self.config = config
        self.adapter = adapter
        self.mode = mode
        
        # 回测模式：需要CoreAlgorithm（生成信号）
        if mode == "backtest":
            signal_config = config.get("signal", {})
            self.core_algo = CoreAlgorithm(config=signal_config)
            if executor:
                self.executor = executor
            else:
                self.executor = BacktestExecutor(config, self.core_algo)
        else:
            # 实时模式：不需要CoreAlgorithm（信号由signal_server生成）
            self.core_algo = None
            if executor:
                self.executor = executor
            else:
                self.executor = LiveExecutor(adapter, config)
    
    def process_feature_row(self, feature_row: Dict) -> Optional[Dict]:
        """处理特征行（回测模式）
        
        实时模式不应该调用此方法，应该使用process_signal()
        """
        if self.mode != "backtest":
            raise ValueError("process_feature_row() only available in backtest mode")
        
        # 生成信号
        signal = self.core_algo.process_feature_row(feature_row)
        if not signal:
            return None
        
        # 获取市场数据
        symbol = feature_row.get("symbol", "")
        market_data = self.adapter.get_market_data(symbol, feature_row)
        
        # 执行交易
        execution_result = self.executor.execute(signal, market_data)
        
        return {
            "signal": signal,
            "execution": execution_result,
        }
    
    def process_signal(self, signal: Dict, market_data: Optional[Dict] = None) -> Optional[Dict]:
        """处理信号（实时模式）
        
        实时模式下，信号由signal_server生成，这里只负责执行交易
        """
        if not market_data:
            # 从适配器获取市场数据
            symbol = signal.get("symbol", "")
            market_data = self.adapter.get_market_data(symbol)
        
        # 执行交易
        execution_result = self.executor.execute(signal, market_data)
        
        return {
            "signal": signal,
            "execution": execution_result,
        }
```

### 3.2 集成方式优化

#### 3.2.1 Orchestrator集成

**新增ProcessSpec**：

```python
# orchestrator/run.py 中添加

def build_strategy_spec(
    config_path: Path,
    output_dir: Path,
    mode: str = "live",  # live | backtest
    sink_kind: str = "jsonl"
) -> ProcessSpec:
    """构建策略服务器规格
    
    Args:
        config_path: 配置文件路径
        output_dir: 输出目录
        mode: 运行模式（live/backtest）
        sink_kind: 信号Sink类型（用于实时模式读取signals）
    """
    run_id = os.getenv("RUN_ID", "")
    
    if mode == "backtest":
        # 回测模式：独立运行，不依赖其他服务
        strategy_cmd = [
            "mcp.strategy_server.app",
            "--mode", "backtest",
            "--config", str(config_path),
        ]
        strategy_env = {
            "RUN_ID": run_id,
        }
        strategy_ready_probe = "log_keyword"
        strategy_ready_args = {"keyword": "Strategy Server started"}
    else:
        # 实时模式：依赖signal_server，读取signals
        signals_dir = output_dir / "ready" / "signal"
        strategy_cmd = [
            "mcp.strategy_server.app",
            "--mode", "live",
            "--config", str(config_path),
            "--signals-dir", str(signals_dir),
        ]
        strategy_env = {
            "RUN_ID": run_id,
        }
        strategy_ready_probe = "log_keyword"
        strategy_ready_args = {"keyword": "Strategy Server started"}
    
    return ProcessSpec(
        name="strategy",
        cmd=strategy_cmd,
        env=strategy_env,
        ready_probe=strategy_ready_probe,
        ready_probe_args=strategy_ready_args,
        health_probe="file_count",
        health_probe_args={
            "pattern": str(output_dir / "ready" / "strategy" / "**" / "*.jsonl"),
            "min_count": 1,
        },
        restart_policy="on_failure",
        max_restarts=2
    )
```

**启动顺序调整**：
```
回测模式（独立）:
  strategy (不依赖其他服务)

实时模式（Orchestrator编排）:
  harvest → signal → strategy → broker → report
  (strategy依赖signal，broker依赖strategy)
```

#### 3.2.2 回测模式优化

**方案**：回测模式作为独立MCP服务，可以替代`scripts/replay_harness.py`

**实现方式**：
```python
# mcp/strategy_server/modes/backtest_mode.py

def run_backtest_mode(strategy_service: StrategyService, args):
    """运行回测模式（复用replay_harness流程）"""
    from alpha_core.backtest import DataReader, DataAligner, MetricsAggregator
    
    # 1. 数据读取
    reader = DataReader(
        input_dir=Path(args.input),
        kinds=args.kinds.split(","),
        symbols=args.symbols.split(",") if args.symbols else None,
        date=args.date,
    )
    
    # 2. 数据对齐（如果需要）
    if "features" not in args.kinds.split(","):
        aligner = DataAligner(config=args.config)
        prices = reader.read_raw("prices")
        orderbook = reader.read_raw("orderbook")
        features = aligner.align_to_seconds(prices, orderbook)
    else:
        features = reader.read_features()
    
    # 3. 处理特征行（通过策略服务）
    for feature_row in features:
        result = strategy_service.process_feature_row(feature_row)
        if result:
            # 记录结果（由BacktestExecutor的TradeSimulator处理）
            pass
    
    # 4. 指标聚合
    # 注意：TradeSimulator已经保存了trades和pnl_daily
    # MetricsAggregator从这些文件读取
    aggregator = MetricsAggregator(output_dir=Path(args.output))
    # 需要从TradeSimulator获取trades和pnl_daily
    # 这里需要优化：如何从BacktestExecutor获取TradeSimulator的trades？
```

**关键问题**：如何从BacktestExecutor获取TradeSimulator的trades和pnl_daily？

**解决方案**：
```python
# BacktestExecutor需要暴露TradeSimulator的接口
class BacktestExecutor(IExecutor):
    def __init__(self, config: Dict, core_algo: CoreAlgorithm):
        # ... 初始化TradeSimulator ...
        self.trade_sim = TradeSimulator(...)
    
    def get_trades(self) -> List[Dict]:
        """获取交易记录"""
        return self.trade_sim.trades
    
    def get_pnl_daily(self) -> Dict[str, Dict]:
        """获取日度PnL"""
        return self.trade_sim.pnl_daily
    
    def close_all_positions(self, current_prices: Dict[str, float], last_data_ts_ms: Optional[int] = None):
        """关闭所有持仓"""
        self.trade_sim.close_all_positions(current_prices, last_data_ts_ms)
    
    def save_pnl_daily(self):
        """保存日度PnL"""
        self.trade_sim.save_pnl_daily()
```

#### 3.2.3 实时模式优化

**方案**：实时模式从signal_server生成的signals读取，执行交易

**实现方式**：
```python
# mcp/strategy_server/modes/live_mode.py

def run_live_mode(strategy_service: StrategyService, args):
    """运行实时模式（从signals读取，执行交易）"""
    signals_dir = Path(args.signals_dir)
    
    # 监听signals目录（类似broker_gateway_server的方式）
    watched_files = set()
    last_positions = {}
    
    while True:
        try:
            # 查找新的信号文件
            jsonl_files = sorted(signals_dir.rglob("*.jsonl"))
            
            for jsonl_file in jsonl_files:
                file_key = str(jsonl_file)
                
                if file_key not in watched_files:
                    watched_files.add(file_key)
                    last_positions[file_key] = 0
                    logger.info(f"发现新信号文件: {jsonl_file}")
                
                # 读取新内容
                try:
                    with jsonl_file.open("r", encoding="utf-8") as fp:
                        fp.seek(last_positions[file_key])
                        new_lines = fp.readlines()
                        
                        for line in new_lines:
                            line = line.strip()
                            if not line:
                                continue
                            
                            try:
                                signal = json.loads(line)
                                # 只处理已确认的信号
                                if not signal.get("confirm", False):
                                    continue
                                
                                # 获取市场数据
                                symbol = signal.get("symbol", "")
                                market_data = strategy_service.adapter.get_market_data(symbol)
                                
                                # 执行交易
                                result = strategy_service.process_signal(signal, market_data)
                                if result:
                                    # 记录交易结果
                                    _save_execution_result(result, args.output)
                            
                            except json.JSONDecodeError:
                                continue
                        
                        last_positions[file_key] = fp.tell()
                except Exception as e:
                    logger.debug(f"读取信号文件失败 {jsonl_file}: {e}")
            
            time.sleep(1.0)  # 检查间隔
        except KeyboardInterrupt:
            logger.info("收到中断信号，停止监听")
            break
        except Exception as e:
            logger.error(f"监听出错: {e}", exc_info=True)
            time.sleep(5)
```

### 3.3 配置管理优化

#### 3.3.1 配置结构

**建议的配置结构**：

```yaml
# config/defaults.yaml 中添加

strategy_server:
  mode: live  # live | backtest
  adapters:
    backtest:
      data_source: ./runtime/ready/features
    testnet:
      api_key: ${TESTNET_API_KEY}
      api_secret: ${TESTNET_API_SECRET}
      base_url: https://testnet.binancefuture.com
    live:
      api_key: ${LIVE_API_KEY}
      api_secret: ${LIVE_API_SECRET}
      base_url: https://fapi.binance.com
      dry_run: false
  
  executors:
    backtest:
      output_dir: ./runtime/backtest
      ignore_gating: true
    live:
      notional_per_trade: 1000
      max_position_notional: 10000
```

### 3.4 数据流优化

#### 3.4.1 回测模式数据流

```
历史数据（Parquet/JSONL）
  ↓
DataReader.read_features()
  ↓
StrategyService.process_feature_row()
  ├─ CoreAlgorithm.process_feature_row() → Signal
  └─ BacktestExecutor.execute()
      └─ TradeSimulator.process_signal() → Trade
  ↓
MetricsAggregator.compute_metrics() → Metrics
```

#### 3.4.2 实时模式数据流

```
Harvest Server
  ↓ (raw/preview data)
FeaturePipe（自动处理）
  ↓ (features/*.jsonl)
Signal Server（监听模式）
  ↓ (signals/*.jsonl)
Strategy Server（监听signals）
  ├─ 读取signals
  ├─ LiveExecutor.execute()
  └─ Broker API (Testnet/Live)
  ↓ (executions/*.jsonl)
Broker Gateway Server（可选，用于订单管理）
```

---

## 4. 优化后的实施计划

### 阶段A（1周，P0清零）- 保持不变

**任务**：
1. ⬜ 抽象IExecutor，拆分BacktestExecutor/LiveExecutor
2. ⬜ 明确BaseAdapter契约
3. ⬜ 将gating/strategy-mode只在CoreAlgorithm产出
4. ⬜ 回测行情由features宽表提供
5. ⬜ 编写等价性测试套件框架

### 阶段B（1-2周，并行P1）- 补充关键任务

**新增任务**：
1. ⬜ **明确与signal_server的关系**
   - 回测模式：独立运行，不依赖signal_server
   - 实时模式：从signal_server读取signals，并行运行
2. ⬜ **实现回测模式**
   - 复用replay_harness流程
   - 集成DataReader、DataAligner、MetricsAggregator
   - BacktestExecutor暴露TradeSimulator接口
3. ⬜ **实现实时模式**
   - 监听signals目录（类似broker_gateway_server）
   - 处理信号，执行交易
   - 保存执行结果

**原有任务**：
4. ⬜ 订单状态机最小闭环
5. ⬜ 等价性测试套件
6. ⬜ 适配器实现（Binance Testnet/Live）

### 阶段C（1周）- 补充Orchestrator集成

**新增任务**：
1. ⬜ **Orchestrator集成**
   - 添加strategy_server的ProcessSpec
   - 调整启动顺序（实时模式：harvest → signal → strategy → broker）
   - 添加健康检查和就绪探针
2. ⬜ **配置管理**
   - 添加strategy_server配置段
   - 支持环境变量覆盖
3. ⬜ **文档完善**
   - 更新Orchestrator文档
   - 添加策略MCP使用指南

**原有任务**：
4. ⬜ 统一Sink输出
5. ⬜ run_manifest和DQ报告

**总预计时间**：4-5周（阶段A：1周，阶段B：1-2周，阶段C：1周）

---

## 5. 关键风险与应对

### 5.1 与现有服务的关系风险

**风险**：策略MCP与signal_server的关系不明确，可能导致：
- 功能重复
- 数据流混乱
- 维护成本增加

**应对**：
- ✅ **明确分工**：
  - signal_server：生成信号（CoreAlgorithm）
  - strategy_server：执行交易（IExecutor）
- ✅ **数据流清晰**：
  - 实时模式：signal_server生成signals → strategy_server读取并执行
  - 回测模式：strategy_server独立运行，内部调用CoreAlgorithm

### 5.2 回测模式集成风险

**风险**：回测模式需要复用replay_harness流程，但TradeSimulator的状态管理复杂

**应对**：
- ✅ **暴露接口**：BacktestExecutor暴露TradeSimulator的关键接口（get_trades、get_pnl_daily等）
- ✅ **保持兼容**：确保输出格式与现有replay_harness一致

### 5.3 实时模式数据流风险

**风险**：实时模式需要从signals读取，可能存在延迟或数据丢失

**应对**：
- ✅ **文件监听**：使用类似broker_gateway_server的文件监听方式
- ✅ **幂等性**：支持按order_id去重，避免重复执行
- ✅ **错误处理**：完善的错误处理和重试机制

---

## 6. 验收标准更新

### 6.1 回测模式验收标准

**新增标准**：
- ✅ 与现有`scripts/replay_harness.py`输出格式一致
- ✅ 可以完全替代replay_harness.py（可选）
- ✅ MetricsAggregator可以正常读取trades和pnl_daily

### 6.2 实时模式验收标准

**新增标准**：
- ✅ 可以正确读取signal_server生成的signals
- ✅ 执行交易后保存execution结果
- ✅ 与Orchestrator集成正常（启动、健康检查、关闭）

### 6.3 Orchestrator集成验收标准

**新增标准**：
- ✅ 可以正确注册到Orchestrator
- ✅ 启动顺序正确（实时模式：harvest → signal → strategy）
- ✅ 健康检查和就绪探针正常工作

---

## 7. 总结与建议

### 7.1 核心优化点

1. ✅ **明确服务定位**：回测模式独立，实时模式与signal_server并行
2. ✅ **优化数据流**：回测模式复用replay_harness，实时模式从signals读取
3. ✅ **补充Orchestrator集成**：添加ProcessSpec，调整启动顺序
4. ✅ **暴露TradeSimulator接口**：BacktestExecutor需要暴露关键接口

### 7.2 实施建议

**立即行动**：
1. 开始阶段A（P0清零）：架构稳定是基础
2. 并行阶段B（P1改进）：补充关键任务（明确服务关系、实现两种模式）
3. 最后阶段C（集成）：Orchestrator集成和文档完善

**关键决策点**：
- ⚠️ **需要确认**：回测模式是否需要完全替代replay_harness.py，还是作为新选项？
- ⚠️ **需要确认**：实时模式是否需要broker_gateway_server，还是strategy_server直接连接交易所？

### 7.3 最终结论

**条件性GO（优化后）** - 在补齐以下关键点后，方案可以稳妥推进：

1. ✅ 明确与signal_server的关系（已优化）
2. ✅ 设计完整的数据流（已优化）
3. ✅ 补充Orchestrator集成方式（已优化）
4. ⬜ 实现回测模式（阶段B）
5. ⬜ 实现实时模式（阶段B）
6. ⬜ Orchestrator集成（阶段C）

**预计时间**：4-5周（阶段A：1周，阶段B：1-2周，阶段C：1周）

---

**文档版本**：v3.0（深度评估与优化）  
**创建日期**：2025-01-11  
**更新日期**：2025-01-11  
**作者**：AI Assistant  
**审核状态**：待审核

