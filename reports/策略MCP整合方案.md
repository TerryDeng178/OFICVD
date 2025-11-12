# 策略MCP整合方案（精简合并版 V4.2）

**版本**：V4.2（精简合并）  
**更新日期**：2025-11-11  
**目标**：在不改变核心算法库（`src/alpha_core/*`）的前提下，删减不必要的MCP服务，合并策略执行逻辑，形成最小可跑、易维护、可扩展的MCP服务架构。

---

## 0. 执行摘要

### 0.1 核心原则

- **薄壳设计**：MCP服务器只做I/O、参数解析与调用编排，业务逻辑全部在库层（`src/alpha_core/*`）
- **最小可跑闭环**：优先保证"采集→信号→策略执行→报表"的端到端闭环最短路径
- **单一事实来源**：统一Schema + 宽表聚合，避免多入口/二义性
- **可替换/可验证**：回测与实时共享一套策略核心，以等价性测试作为合并闸门
- **配置集中**：全局配置集中在`config/defaults.yaml`，支持环境变量最小覆盖

### 0.2 服务清单（精简后）

| 服务 | 角色 | 状态 | 说明 |
|------|------|------|------|
| **harvest_server** | 采集/对齐/落盘（Raw+Preview/宽表） | ✅ 保留 | 产出`prices/orderbook`（权威）与`features`（预览/分析）；含DQ、轮转、死信 |
| **signal_server** | 信号生成（CoreAlgo薄壳） | ✅ 保留 | 从**features**读，产出**signals.jsonl/signals.db**；仅最小门控（暖启动、lag/spread基础护栏） |
| **strategy_server** | 策略执行（合成方案） | 🆕 新增/合并 | **读取signals**，基于Adapter执行（`backtest`/`testnet`/`live`）；**风控/模式护栏内聚到此** |
| **broker_gateway_server** | 交易所网关 | ✅ 保留 | Testnet/Live网关；`strategy_server`通过Adapter调用 |
| **report_server** | 报表生成 | ✅ 保留 | 聚合signals/executions生成PnL、胜率、滑点、费用等 |
| ~~data_feed_server~~ | 统一数据源 | ❌ **移除** | 由`harvest_server`输出与宽表对齐功能**已覆盖** |
| ~~ofi_feature_server~~ | OFI/CVD/Fusion/DIV特征服务 | ❌ **移除** | 特征计算复用库层（`alpha_core.microstructure.*`），由`signal_server`内部调用 |
| ~~ofi_risk_server~~ | 风控服务 | ⏸️ **冻结** | 逻辑并入`strategy_server`（下单前置校验）与`core_algo`（模式/护栏） |

> 备注：移除项的代码可保留为示例/备档，但不进入部署链路。

### 0.3 两条运行链路

**1. 实时链路（生产）**：
```
Harvest → Signal → Strategy → Broker → Report
(features) (signals) (执行交易) (Testnet/Live) (报表)
```

**2. 回测链路（研发/CI）**：
```
Strategy (独立运行)
  ├─ CoreAlgorithm (信号生成)
  └─ BacktestExecutor (交易执行，封装TradeSimulator)
```

### 0.4 单一事实来源

- **在线/离线统一**：以**Features宽表**（由Harvester + 计算产物对齐）为事实来源
- **信号层**：以**signals目录/SQLite**为唯一上游
- **策略层**：仅读取**signals**，不直接读取features

---

## 1. 需求理解

### 1.1 核心需求
- **以回测为界限**：将回测开发后的所有策略逻辑整合到统一的MCP策略服务
- **统一入口**：通过策略MCP可以对接三种环境：
  - 回测（Backtest）- 独立运行，可替代replay_harness.py
  - 测试网（Testnet）- 通过Orchestrator编排
  - 真实交易（Live）- 通过Orchestrator编排
- **精简合并**：移除冗余服务，合并风控逻辑，形成最小可跑闭环

### 1.2 目标架构

```
实时链路（Orchestrator编排）:
  harvest_server (features)
    ↓
  signal_server (signals)
    ↓
  strategy_server (执行交易)
    ↓
  broker_gateway_server (Testnet/Live)
    ↓
  report_server (报表)

回测链路（独立运行）:
  strategy_server --mode backtest
    → StrategyService
      ├─ CoreAlgorithm (信号生成)
      └─ BacktestExecutor (交易执行，封装TradeSimulator)
```

## 2. 整合范围与精简策略

### 2.1 回测路径上的策略组件

**需要整合的组件**：
1. **CoreAlgorithm** (`src/alpha_core/signals/core_algo.py`)
   - 信号生成逻辑
   - 最小门控检查（暖启动、lag/spread基础护栏）
   - **注意**：策略模式管理（StrategyMode）逻辑保留在CoreAlgorithm，但风控护栏下沉到strategy_server

2. **TradeSimulator** (`src/alpha_core/backtest/trade_sim.py`)
   - 交易执行逻辑
   - 持仓管理
   - 费用/滑点计算
   - PnL计算

3. **回测流程** (`scripts/replay_harness.py`)
   - 数据读取（DataReader）
   - 数据对齐（DataAligner）
   - 回放喂送（ReplayFeeder）
   - 指标聚合（MetricsAggregator）

### 2.2 精简与合并策略

**移除的服务**：
- ❌ **data_feed_server**：功能由`harvest_server`覆盖，无需单独服务
- ❌ **ofi_feature_server**：特征计算在库层，由`signal_server`内部调用
- ⏸️ **ofi_risk_server**：逻辑合并到`strategy_server`和`core_algo`

**合并的逻辑**：
- **风控/模式护栏**：合并到`strategy_server`（下单前置校验）
- **StrategyMode**：保留在`core_algo`（信号生成层），但执行层风控下沉到`strategy_server`

**原则**：
- 保持现有回测路径的接口不变（向后兼容）
- 将策略逻辑封装到MCP服务中
- 通过适配器模式支持不同环境
- **单一事实来源**：features → signals → strategy（不跨层读取）

## 3. 架构设计

### 3.1 目录结构

```
mcp/
├── harvest_server/           # ✅ 保留：采集服务
│   └── app.py
├── signal_server/            # ✅ 保留：信号生成服务
│   └── app.py
├── strategy_server/          # 🆕 新增：策略执行服务（合并风控）
│   ├── __init__.py
│   ├── app.py                # MCP服务器入口（统一入口）
│   ├── strategy_service.py   # 策略服务核心（整合CoreAlgorithm + IExecutor + 风控）
│   ├── executors/            # 执行层抽象（P0）
│   │   ├── __init__.py
│   │   ├── base_executor.py  # IExecutor接口
│   │   ├── backtest_executor.py  # BacktestExecutor（封装TradeSimulator）
│   │   └── live_executor.py  # LiveExecutor（封装Broker API）
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base_adapter.py   # 基础适配器接口（P0：明确契约）
│   │   ├── backtest_adapter.py  # 回测适配器
│   │   ├── testnet_adapter.py   # 测试网适配器（Binance Testnet）
│   │   └── live_adapter.py   # 实盘适配器（Binance Live）
│   ├── risk/                 # 🆕 新增：风控模块（合并ofi_risk_server逻辑）
│   │   ├── __init__.py
│   │   ├── risk_manager.py   # 风险管理器（下单前置校验）
│   │   └── position_manager.py  # 仓位管理器
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_equivalence.py  # 等价性测试套件（P0）
│   │   └── test_contracts.py    # 契约测试
│   └── utils/
│       ├── __init__.py
│       ├── config_loader.py  # 配置加载器
│       └── logger.py         # 日志工具
├── broker_gateway_server/    # ✅ 保留：交易所网关
│   └── app.py
└── report_server/            # ✅ 保留：报表服务
    └── app.py

# ❌ 移除（代码保留为示例/备档，不进入部署链路）：
# mcp/data_feed_server/        # 功能由harvest_server覆盖
# mcp/ofi_feature_server/      # 特征计算在库层，由signal_server调用
# mcp/ofi_risk_server/          # 逻辑合并到strategy_server
```

### 3.2 核心类设计

#### 3.2.1 IExecutor接口（执行层抽象，P0）

```python
# mcp/strategy_server/executors/base_executor.py

from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

class OrderStatus(Enum):
    """订单状态枚举（修复：统一状态类型）"""
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

@dataclass
class ExecutionResult:
    """执行结果"""
    ts_ms: int
    symbol: str
    side: str  # buy/sell
    action: str  # entry/exit
    price: float
    quantity: float
    fee: float
    slippage: float
    pnl: Optional[float] = None
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.FILLED  # 修复：使用OrderStatus枚举，统一类型

class IExecutor(ABC):
    """执行层接口：统一回测和实盘执行逻辑"""
    
    @abstractmethod
    def execute(self, signal: Dict, market_data: Dict) -> Optional[ExecutionResult]:
        """执行交易
        
        Args:
            signal: 信号字典（来自CoreAlgorithm，已包含confirm/gating_blocked）
            market_data: 市场数据字典
            
        Returns:
            ExecutionResult对象，如果未执行则返回None
            
        注意：
            - 只处理confirm=True且gating_blocked=False的信号
            - 不在此处重复判定gating/strategy-mode（已在CoreAlgorithm完成）
        """
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取当前持仓"""
        pass
    
    @abstractmethod
    def calculate_pnl(self, entry_price: float, exit_price: float, 
                      quantity: float, side: str, fee: float) -> float:
        """计算PnL（统一计算逻辑）"""
        pass
```

#### 3.2.2 BacktestExecutor（回测执行器）

```python
# mcp/strategy_server/executors/backtest_executor.py

from typing import Dict, Optional
from pathlib import Path
from alpha_core.backtest.trade_sim import TradeSimulator
from alpha_core.signals import CoreAlgorithm
from .base_executor import IExecutor, ExecutionResult

class BacktestExecutor(IExecutor):
    """回测执行器：封装TradeSimulator"""
    
    def __init__(self, config: Dict, core_algo: CoreAlgorithm):
        """初始化回测执行器
        
        Args:
            config: 回测配置字典
            core_algo: CoreAlgorithm实例（用于F3功能）
        """
        backtest_config = config.get("backtest", {})
        output_dir = Path(backtest_config.get("output_dir", "./runtime/backtest"))
        ignore_gating = backtest_config.get("ignore_gating_in_backtest", True)
        
        self.trade_sim = TradeSimulator(
            config=backtest_config,
            output_dir=output_dir,
            ignore_gating_in_backtest=ignore_gating,
            core_algo=core_algo,  # F3功能
        )
    
    def execute(self, signal: Dict, market_data: Dict) -> Optional[ExecutionResult]:
        """执行回测交易"""
        # 只处理已确认且未被门控阻止的信号
        if not signal.get("confirm", False) or signal.get("gating_blocked", False):
            return None
        
        mid_price = market_data.get("mid_price", signal.get("price", 0))
        trade_dict = self.trade_sim.process_signal(signal, mid_price)
        
        if not trade_dict:
            return None
        
        return ExecutionResult(
            ts_ms=trade_dict["ts_ms"],
            symbol=trade_dict["symbol"],
            side=trade_dict["side"],
            action=trade_dict["action"],
            price=trade_dict["price"],
            quantity=trade_dict["quantity"],
            fee=trade_dict["fee"],
            slippage=trade_dict["slippage"],
            pnl=trade_dict.get("pnl"),
        )
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓（由TradeSimulator管理）"""
        return self.trade_sim.positions.get(symbol)
    
    def calculate_pnl(self, entry_price: float, exit_price: float, 
                     quantity: float, side: str, fee: float) -> float:
        """计算PnL"""
        if side == "buy":
            return (exit_price - entry_price) * quantity - fee
        else:
            return (entry_price - exit_price) * quantity - fee
```

#### 3.2.3 LiveExecutor（实盘执行器）

```python
# mcp/strategy_server/executors/live_executor.py

import time
from typing import Dict, Optional
from .base_executor import IExecutor, ExecutionResult
from ..adapters.base_adapter import BaseAdapter, OrderStatus

class LiveExecutor(IExecutor):
    """实盘执行器：封装Broker API（测试网/实盘）"""
    
    def __init__(self, adapter: BaseAdapter, config: Dict):
        """初始化实盘执行器
        
        Args:
            adapter: 适配器实例（TestnetAdapter/LiveAdapter）
            config: 配置字典
        """
        self.adapter = adapter
        self.config = config
        self.positions: Dict[str, Dict] = {}  # symbol -> position
    
    def execute(self, signal: Dict, market_data: Dict) -> Optional[ExecutionResult]:
        """执行实盘交易"""
        # 只处理已确认且未被门控阻止的信号
        if not signal.get("confirm", False) or signal.get("gating_blocked", False):
            return None
        
        symbol = signal.get("symbol", "")
        signal_type = signal.get("signal_type", "")
        
        # 确定交易方向
        side = None
        if signal_type in ("buy", "strong_buy"):
            side = "buy"
        elif signal_type in ("sell", "strong_sell"):
            side = "sell"
        
        if not side:
            return None
        
        # 获取当前持仓
        current_position = self.get_position(symbol)
        
        # 决定交易动作
        if not current_position:
            # 无持仓，开仓
            return self._enter_position(symbol, side, signal, market_data)
        elif current_position.get("side") != side:
            # 反向持仓，先平仓再开仓
            exit_result = self._exit_position(current_position, market_data, "reverse")
            if exit_result:
                return self._enter_position(symbol, side, signal, market_data)
        else:
            # 同向持仓，不操作
            return None
        
        return None
    
    def _enter_position(self, symbol: str, side: str, signal: Dict, 
                       market_data: Dict) -> Optional[ExecutionResult]:
        """开仓"""
        # 修复：从execute配置读取，而非backtest配置
        execute_config = self.config.get("execute", {})
        notional = execute_config.get("notional_per_trade", 
                                     self.config.get("backtest", {}).get("notional_per_trade", 1000))
        mid_price = market_data.get("mid_price", 0.0)
        # 通过适配器校验和取整数量（lot/精度校验）
        quantity = self.adapter.normalize_quantity(symbol, notional / mid_price if mid_price > 0 else 0)
        
        # 通过适配器执行订单
        order_result = self.adapter.execute_order({
            "symbol": symbol,
            "side": "BUY" if side == "buy" else "SELL",
            "type": "MARKET",
            "quantity": quantity,
        })
        
        if not order_result or not order_result.get("filled"):
            return None
        
        # 记录持仓
        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_ts_ms": signal.get("ts_ms", 0),
            "entry_price": order_result["filled_price"],
            "quantity": order_result["filled_quantity"],
        }
        
        return ExecutionResult(
            ts_ms=signal.get("ts_ms", 0),
            symbol=symbol,
            side=side,
            action="entry",
            price=order_result["filled_price"],
            quantity=order_result["filled_quantity"],
            fee=order_result.get("fee", 0.0),
            slippage=order_result.get("slippage", 0.0),
            order_id=order_result.get("order_id"),
            status=order_result.get("status", OrderStatus.FILLED),
        )
    
    def _exit_position(self, position: Dict, market_data: Dict, 
                      reason: str) -> Optional[ExecutionResult]:
        """平仓"""
        symbol = position.get("symbol", "")
        side = position.get("side", "")
        quantity = position.get("quantity", 0)
        
        # 通过适配器执行平仓订单
        order_result = self.adapter.execute_order({
            "symbol": symbol,
            "side": "SELL" if side == "buy" else "BUY",
            "type": "MARKET",
            "quantity": quantity,
        })
        
        if not order_result or not order_result.get("filled"):
            return None
        
        # 计算PnL
        entry_price = position.get("entry_price", 0)
        exit_price = order_result["filled_price"]
        fee = order_result.get("fee", 0.0)
        pnl = self.calculate_pnl(entry_price, exit_price, quantity, side, fee)
        
        # 移除持仓
        self.positions.pop(symbol, None)
        
        return ExecutionResult(
            ts_ms=int(time.time() * 1000),
            symbol=symbol,
            side=side,
            action="exit",
            price=exit_price,
            quantity=quantity,
            fee=fee,
            slippage=order_result.get("slippage", 0.0),
            pnl=pnl,
            order_id=order_result.get("order_id"),
            status=order_result.get("status", OrderStatus.FILLED),
        )
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        return self.positions.get(symbol) or self.adapter.get_position(symbol)
    
    def calculate_pnl(self, entry_price: float, exit_price: float, 
                     quantity: float, side: str, fee: float) -> float:
        """计算PnL"""
        if side == "buy":
            return (exit_price - entry_price) * quantity - fee
        else:
            return (entry_price - exit_price) * quantity - fee
```

#### 3.2.4 StrategyService（策略服务核心，重构后）

```python
# mcp/strategy_server/strategy_service.py

from typing import Dict, Optional
from alpha_core.signals import CoreAlgorithm
from .executors.base_executor import IExecutor
from .executors.backtest_executor import BacktestExecutor
from .executors.live_executor import LiveExecutor
from .adapters.base_adapter import BaseAdapter
from .adapters.backtest_adapter import BacktestAdapter  # 修复：补充导入

class StrategyService:
    """策略服务核心：整合信号生成和交易执行（合并风控逻辑）
    
    关键设计原则（P0）：
    1. **信号层门控**：CoreAlgorithm完成最小门控（暖启动、lag/spread基础护栏）
    2. **执行层风控**：strategy_server在执行前应用StrategyMode/风险墙/目标仓位等（合并ofi_risk_server逻辑）
    3. 通过IExecutor接口统一回测和实盘执行逻辑，避免条件分支
    4. **单一事实来源**：回测模式从features读取，实时模式从signals读取（不跨层）
    """
    
    def __init__(self, config: Dict, adapter: BaseAdapter, executor: Optional[IExecutor] = None):
        """初始化策略服务
        
        Args:
            config: 配置字典（包含signal、risk和backtest配置）
            adapter: 适配器实例（BacktestAdapter/TestnetAdapter/LiveAdapter）
            executor: 执行器实例（可选，如果不提供则根据adapter自动创建）
        """
        self.config = config
        self.adapter = adapter
        
        # 初始化CoreAlgorithm（信号生成，仅最小门控）
        signal_config = config.get("signal", {})
        self.core_algo = CoreAlgorithm(config=signal_config)
        
        # 🆕 初始化风控管理器（合并ofi_risk_server逻辑）
        from .risk.risk_manager import RiskManager
        risk_config = config.get("risk", {})
        self.risk_manager = RiskManager(risk_config)
        
        # 初始化执行器（根据adapter类型自动选择）
        if executor:
            self.executor = executor
        elif isinstance(adapter, BacktestAdapter):
            self.executor = BacktestExecutor(config, self.core_algo)
        else:
            self.executor = LiveExecutor(adapter, config)
    
    def process_signal(self, signal: Dict, market_data: Optional[Dict] = None) -> Optional[Dict]:
        """处理信号：执行风控检查并执行交易
        
        这是统一的策略处理入口，支持三种模式：
        - 回测模式：使用BacktestExecutor（封装TradeSimulator）
        - 测试网/实盘模式：使用LiveExecutor（封装Broker API）
        
        **重要**：实时模式从signals读取，不直接读取features
        
        Args:
            signal: 信号字典（来自signal_server）
            market_data: 市场数据字典（可选，实时模式从adapter获取）
            
        Returns:
            处理结果字典（包含信号和执行结果）
        """
        # 1. 风控检查（执行层前置校验，合并ofi_risk_server逻辑）
        risk_check = self.risk_manager.check_signal(signal, market_data)
        if not risk_check.get("allow", False):
            return {
                "signal": signal,
                "execution": None,
                "risk_blocked": True,
                "risk_reason": risk_check.get("reason", "unknown"),
            }
        
        # 2. 获取市场数据（实时模式从adapter获取）
        if not market_data:
            symbol = signal.get("symbol", "")
            market_data = self.adapter.get_market_data(symbol)
        
        # 3. 执行交易（通过IExecutor接口，统一处理）
        # 注意：执行层只处理confirm=True且gating_blocked=False的信号
        execution_result = self.executor.execute(signal, market_data)
        
        # 修复：通过adapter.kind明确区分testnet和live
        mode = "backtest"
        if hasattr(self.adapter, "kind"):
            mode = self.adapter.kind  # "backtest" | "testnet" | "live"
        elif isinstance(self.executor, BacktestExecutor):
            mode = "backtest"
        else:
            mode = "live"  # 默认fallback
        
        return {
            "signal": signal,
            "execution": execution_result,
            "mode": mode,
            "risk_state": risk_check.get("risk_state", {}),
        }
    
    def process_feature_row(self, feature_row: Dict) -> Optional[Dict]:
        """处理特征行：生成信号并执行交易（回测模式专用）
        
        **注意**：此方法仅用于回测模式，实时模式应使用process_signal()从signals读取
        
        Args:
            feature_row: 特征行字典
            
        Returns:
            处理结果字典（包含信号和执行结果）
        """
        # 1. 生成信号（CoreAlgorithm，仅最小门控）
        signal = self.core_algo.process_feature_row(feature_row)
        
        if not signal:
            return None
        
        # 2. 获取市场数据（通过适配器，从features宽表读取）
        symbol = feature_row.get("symbol", "")
        market_data = self.adapter.get_market_data(symbol, feature_row)
        
        # 3. 执行风控检查
        risk_check = self.risk_manager.check_signal(signal, market_data)
        if not risk_check.get("allow", False):
            return {
                "signal": signal,
                "execution": None,
                "risk_blocked": True,
                "risk_reason": risk_check.get("reason", "unknown"),
            }
        
        # 4. 执行交易（通过IExecutor接口，统一处理）
        execution_result = self.executor.execute(signal, market_data)
        
        return {
            "signal": signal,
            "execution": execution_result,
            "mode": "backtest",
            "risk_state": risk_check.get("risk_state", {}),
        }
```

#### 3.2.5 BaseAdapter契约（P0：明确契约）

```python
# mcp/strategy_server/adapters/base_adapter.py

from abc import ABC, abstractmethod
from typing import Dict, Optional, List
from enum import Enum

class OrderStatus(Enum):
    """订单状态"""
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

class AdapterError(Exception):
    """适配器错误基类"""
    pass

class RetryableError(AdapterError):
    """可重试错误"""
    pass

class RateLimitError(RetryableError):
    """速率限制错误"""
    pass

class BaseAdapter(ABC):
    """基础适配器接口（P0：明确契约）
    
    契约要求：
    1. 所有方法必须线程安全
    2. 错误码统一：使用AdapterError及其子类
    3. 重试策略：RateLimitError自动重试（指数退避）
    4. 幂等性：execute_order支持幂等键（order_id）
    5. 时钟校准：get_clock()返回服务器时间
    6. 速率限制：遵守交易所API限制（通过limiters配置）
    7. 适配器类型标识：kind属性（"backtest" | "testnet" | "live"）
    """
    
    @property
    @abstractmethod
    def kind(self) -> str:
        """适配器类型标识
        
        Returns:
            "backtest" | "testnet" | "live"
        """
        pass
    
    @abstractmethod
    def get_market_data(self, symbol: str, feature_row: Optional[Dict] = None) -> Dict:
        """获取市场数据
        
        Args:
            symbol: 交易对符号
            feature_row: 特征行（回测模式可选，用于从features宽表读取）
            
        Returns:
            市场数据字典：
            {
                "mid_price": float,      # 中间价
                "bid": float,            # 最优买价
                "ask": float,            # 最优卖价
                "spread_bps": float,     # 价差（基点）
                "ts_ms": int,            # 时间戳（毫秒）
            }
            
        Raises:
            AdapterError: 获取失败
            RateLimitError: 速率限制（可重试）
        """
        pass
    
    @abstractmethod
    def execute_order(self, order: Dict) -> Optional[Dict]:
        """执行订单
        
        Args:
            order: 订单字典
            {
                "symbol": str,           # 交易对
                "side": "BUY" | "SELL",  # 方向
                "type": "MARKET" | "LIMIT",
                "quantity": float,       # 数量
                "price": float,          # 价格（LIMIT订单）
                "order_id": str,         # 幂等键（可选）
            }
            
        Returns:
            订单结果字典：
            {
                "order_id": str,         # 订单ID
                "status": OrderStatus,   # 订单状态
                "filled": bool,          # 是否已成交
                "filled_price": float,   # 成交均价
                "filled_quantity": float,# 成交数量
                "fee": float,           # 手续费
                "slippage": float,       # 滑点（基点）
            }
            
        Raises:
            AdapterError: 执行失败
            RateLimitError: 速率限制（可重试）
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销订单
        
        Args:
            order_id: 订单ID
            symbol: 交易对符号
            
        Returns:
            True if成功，False otherwise
        """
        pass
    
    @abstractmethod
    def query_fills(self, symbol: str, start_ts_ms: Optional[int] = None, 
                   end_ts_ms: Optional[int] = None) -> List[Dict]:
        """查询成交记录
        
        Args:
            symbol: 交易对符号
            start_ts_ms: 开始时间戳（可选）
            end_ts_ms: 结束时间戳（可选）
            
        Returns:
            成交记录列表
        """
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓
        
        Args:
            symbol: 交易对符号
            
        Returns:
            持仓字典：
            {
                "symbol": str,
                "side": "buy" | "sell",
                "quantity": float,
                "entry_price": float,
            }
            如果无持仓则返回None
        """
        pass
    
    @abstractmethod
    def get_balance(self) -> Dict:
        """获取账户余额
        
        Returns:
            余额字典：
            {
                "available": float,  # 可用余额
                "locked": float,     # 锁定余额
            }
        """
        pass
    
    @abstractmethod
    def get_clock(self) -> Dict:
        """获取服务器时钟（用于时钟校准）
        
        Returns:
            时钟字典：
            {
                "server_time_ms": int,  # 服务器时间（毫秒）
                "local_time_ms": int,   # 本地时间（毫秒）
                "offset_ms": int,       # 时钟偏移（毫秒）
            }
        """
        pass
    
    def normalize_quantity(self, symbol: str, quantity: float) -> float:
        """数量取整与校验（修复：lot/精度校验下沉到adapter）
        
        Args:
            symbol: 交易对符号
            quantity: 原始数量
            
        Returns:
            取整后的数量（符合交易所lot/stepSize要求）
            
        Raises:
            AdapterError: 数量不符合最小交易单位要求
        """
        # 默认实现：直接返回（子类应重写）
        return quantity
```

#### 3.2.6 BacktestAdapter（回测适配器，P1：从features宽表读取）

```python
# mcp/strategy_server/adapters/backtest_adapter.py

from typing import Dict, Optional
from pathlib import Path
from .base_adapter import BaseAdapter

class BacktestAdapter(BaseAdapter):
    """回测适配器：从features宽表读取行情（P1修复）"""
    
    @property
    def kind(self) -> str:
        """适配器类型标识"""
        return "backtest"
    
    def __init__(self, config: Dict):
        """初始化回测适配器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.data_source = Path(config.get("data_source", "./runtime/ready/features"))
    
    def get_market_data(self, symbol: str, feature_row: Optional[Dict] = None) -> Dict:
        """从features宽表获取市场数据（P1修复）
        
        Args:
            symbol: 交易对符号
            feature_row: 特征行（包含mid/best_bid/best_ask/spread_bps字段）
            
        Returns:
            市场数据字典
        """
        if feature_row:
            # 优先从features宽表读取（Harvester已产出这些字段）
            mid_price = feature_row.get("mid") or feature_row.get("price", 0.0)
            best_bid = feature_row.get("best_bid") or feature_row.get("bid", 0.0)
            best_ask = feature_row.get("best_ask") or feature_row.get("ask", 0.0)
            spread_bps = feature_row.get("spread_bps", 0.0)
            
            # 如果缺失，从订单簿计算
            if not best_bid or not best_ask:
                # 从orderbook字段读取（如果有）
                bids = feature_row.get("bids", [])
                asks = feature_row.get("asks", [])
                if bids and asks:
                    best_bid = bids[0][0] if isinstance(bids[0], list) else bids[0]
                    best_ask = asks[0][0] if isinstance(asks[0], list) else asks[0]
                    if mid_price == 0:
                        mid_price = (best_bid + best_ask) / 2
                    if spread_bps == 0:
                        spread_bps = ((best_ask - best_bid) / mid_price) * 10000
            
            return {
                "mid_price": mid_price,
                "bid": best_bid,
                "ask": best_ask,
                "spread_bps": spread_bps,
                "ts_ms": feature_row.get("ts_ms", 0),
            }
        
        # 兜底：返回默认值（不应到达）
        return {
            "mid_price": 50000.0,
            "bid": 49999.0,
            "ask": 50001.0,
            "spread_bps": 2.0,
            "ts_ms": 0,
        }
    
    def execute_order(self, order: Dict) -> Optional[Dict]:
        """回测模式下，订单执行由TradeSimulator处理
        
        Args:
            order: 订单字典
            
        Returns:
            None（由TradeSimulator处理）
        """
        # 回测模式下，订单执行由BacktestExecutor的TradeSimulator处理
        return None
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓（回测模式由TradeSimulator管理）
        
        Args:
            symbol: 交易对符号
            
        Returns:
            None（由TradeSimulator管理）
        """
        return None
    
    def get_balance(self) -> Dict:
        """获取账户余额（回测模式）
        
        Returns:
            余额字典
        """
        return {
            "available": 100000.0,  # 模拟余额
            "locked": 0.0,
        }
```

#### 3.2.3 TestnetAdapter / LiveAdapter

```python
# mcp/strategy_server/adapters/testnet_adapter.py
# mcp/strategy_server/adapters/live_adapter.py

# 实现与之前设计相同，连接测试网/实盘API
```

### 3.3 MCP服务器入口

```python
# mcp/strategy_server/app.py

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from .strategy_service import StrategyService
from .adapters.backtest_adapter import BacktestAdapter
from .adapters.testnet_adapter import TestnetAdapter
from .adapters.live_adapter import LiveAdapter

# 导入回测相关组件（用于回测模式）
from alpha_core.backtest import DataReader, DataAligner, ReplayFeeder, MetricsAggregator

def load_config(config_path: str) -> Dict:
    """加载配置文件"""
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def run_backtest_mode(strategy_service: StrategyService, args):
    """运行回测模式（复用现有回测流程，独立运行）"""
    logger = logging.getLogger(__name__)
    logger.info("Strategy Server (Backtest Mode) started")
    
    # 1. 数据读取（从features宽表读取）
    reader = DataReader(
        input_dir=Path(args.input),
        kinds=args.kinds.split(",") if args.kinds else ["features"],
        symbols=args.symbols.split(",") if args.symbols else None,
        date=args.date,
    )
    
    # 2. 数据对齐
    aligner = DataAligner(config=args.config)
    
    # 3. 回放喂送
    output_dir = Path(args.output) if args.output else Path("./runtime/backtest")
    feeder = ReplayFeeder(
        reader=reader,
        aligner=aligner,
        output_dir=output_dir,
    )
    
    # 4. 处理特征行（通过策略服务）
    execution_count = 0
    for feature_row in feeder.iter_features():
        result = strategy_service.process_feature_row(feature_row)
        if result and result.get("execution"):
            execution_count += 1
    
    logger.info(f"Backtest completed: {execution_count} executions")
    
    # 5. 指标聚合
    aggregator = MetricsAggregator(output_dir=output_dir)
    aggregator.aggregate()

def run_live_mode(strategy_service: StrategyService, args):
    """运行实盘模式（测试网/实盘）：从signals读取，执行交易"""
    logger = logging.getLogger(__name__)
    logger.info(f"Strategy Server ({args.mode.upper()} Mode) started")
    
    # 确定signals目录（单一事实来源）
    signals_dir = Path(args.signals_dir or "./runtime/ready/signal")
    if not signals_dir.exists():
        logger.error(f"Signals directory not found: {signals_dir}")
        return 1
    
    # 监听signals文件（JSONL或SQLite）
    if args.sink == "sqlite":
        # SQLite模式：查询signals.db
        import sqlite3
        db_path = signals_dir / "signals.db"
        if not db_path.exists():
            logger.error(f"Signals database not found: {db_path}")
            return 1
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 查询未处理的信号（通过order_id幂等去重）
        processed_order_ids = set()
        while True:
            try:
                cursor.execute("""
                    SELECT ts_ms, symbol, score, confirm, gating, signal_type, 
                           z_ofi, z_cvd, regime, div_type
                    FROM signals
                    WHERE confirm = 1 AND gating = 0
                    ORDER BY ts_ms ASC
                """)
                
                for row in cursor.fetchall():
                    signal = {
                        "ts_ms": row[0],
                        "symbol": row[1],
                        "score": row[2],
                        "confirm": bool(row[3]),
                        "gating_blocked": bool(row[4]),
                        "signal_type": row[5],
                        "z_ofi": row[6],
                        "z_cvd": row[7],
                        "regime": row[8],
                        "div_type": row[9],
                    }
                    
                    # 幂等处理（通过order_id）
                    order_id = f"{signal['ts_ms']}_{signal['symbol']}_{signal['signal_type']}"
                    if order_id in processed_order_ids:
                        continue
                    processed_order_ids.add(order_id)
                    
                    # 处理信号
                    result = strategy_service.process_signal(signal)
                    if result and result.get("execution"):
                        # 保存执行结果
                        execution_dir = Path(args.output or "./runtime/executions")
                        execution_dir.mkdir(parents=True, exist_ok=True)
                        execution_file = execution_dir / f"executions_{int(time.time())}.jsonl"
                        with execution_file.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(result, ensure_ascii=False) + "\n")
                
                time.sleep(1.0)  # 轮询间隔
            except KeyboardInterrupt:
                logger.info("Received interrupt signal, stopping...")
                break
            except Exception as e:
                logger.error(f"Error processing signals: {e}", exc_info=True)
                time.sleep(5.0)
        
        conn.close()
    else:
        # JSONL模式：监听signals/*.jsonl文件
        watched_files = set()
        last_positions = {}
        
        while True:
            try:
                jsonl_files = sorted(signals_dir.rglob("*.jsonl"))
                
                for jsonl_file in jsonl_files:
                    file_key = str(jsonl_file)
                    
                    if file_key not in watched_files:
                        watched_files.add(file_key)
                        last_positions[file_key] = 0
                        logger.info(f"Watching signals file: {jsonl_file}")
                    
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
                                    # 只处理已确认且未被门控阻止的信号
                                    if not signal.get("confirm", False) or signal.get("gating", False):
                                        continue
                                    
                                    # 幂等处理
                                    order_id = f"{signal.get('ts_ms', 0)}_{signal.get('symbol', '')}_{signal.get('signal_type', '')}"
                                    if order_id in processed_order_ids:
                                        continue
                                    processed_order_ids.add(order_id)
                                    
                                    # 处理信号
                                    result = strategy_service.process_signal(signal)
                                    if result and result.get("execution"):
                                        # 保存执行结果
                                        execution_dir = Path(args.output or "./runtime/executions")
                                        execution_dir.mkdir(parents=True, exist_ok=True)
                                        execution_file = execution_dir / f"executions_{int(time.time())}.jsonl"
                                        with execution_file.open("a", encoding="utf-8") as f:
                                            f.write(json.dumps(result, ensure_ascii=False) + "\n")
                                except json.JSONDecodeError:
                                    continue
                            
                            last_positions[file_key] = fp.tell()
                    except Exception as e:
                        logger.debug(f"Error reading file {jsonl_file}: {e}")
                
                time.sleep(1.0)
            except KeyboardInterrupt:
                logger.info("Received interrupt signal, stopping...")
                break
            except Exception as e:
                logger.error(f"Error watching signals: {e}", exc_info=True)
                time.sleep(5.0)
    
    return 0

def main():
    parser = argparse.ArgumentParser(description="MCP Strategy Server - 统一策略服务（精简合并版）")
    parser.add_argument("--mode", choices=["backtest", "testnet", "live"], required=True,
                       help="运行模式：backtest（回测）/ testnet（测试网）/ live（实盘）")
    parser.add_argument("--config", default="./config/defaults.yaml",
                       help="配置文件路径")
    parser.add_argument("--input", help="输入数据目录（回测模式：features目录）")
    parser.add_argument("--signals-dir", help="信号目录（实时模式：signals目录，默认./runtime/ready/signal）")
    parser.add_argument("--output", help="输出目录")
    parser.add_argument("--symbols", help="交易对列表（逗号分隔）")
    parser.add_argument("--kinds", help="数据类型（回测模式，逗号分隔，默认features）")
    parser.add_argument("--date", help="日期过滤（回测模式，YYYY-MM-DD）")
    parser.add_argument("--sink", choices=["jsonl", "sqlite"], default="jsonl",
                       help="信号Sink类型（实时模式，默认jsonl）")
    parser.add_argument("--dry-run", action="store_true",
                       help="Dry run模式（仅实盘模式）")
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 选择适配器
    if args.mode == "backtest":
        adapter = BacktestAdapter(config.get("adapters", {}).get("backtest", {}))
    elif args.mode == "testnet":
        adapter = TestnetAdapter(config.get("adapters", {}).get("testnet", {}))
    elif args.mode == "live":
        adapter_config = config.get("adapters", {}).get("live", {})
        adapter_config["dry_run"] = args.dry_run
        adapter = LiveAdapter(adapter_config)
    
    # 创建策略服务
    strategy_service = StrategyService(config, adapter)
    
    # 运行策略循环
    if args.mode == "backtest":
        run_backtest_mode(strategy_service, args)
    else:
        return run_live_mode(strategy_service, args)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## 4. 数据与控制流

### 4.1 实时链路（生产）

```
harvest_server (features.jsonl / features.db)
    ↓
signal_server (signals.jsonl / signals.db)
    ↓
strategy_server (读取signals，执行交易)
    ↓
broker_gateway_server (Testnet/Live)
    ↓
report_server (报表)
```

**要点**：
- **单一事实来源**：`signal_server`只读features；`strategy_server`只读signals（文件/SQLite二选一）
- **幂等/去重**：`strategy_server`以`order_id`做幂等处理，防止重复执行
- **探针**：`signal_server`以`processed=`关键词/`signals`数量为健康信号；`strategy_server`以`executions/*.jsonl`计数作为健康信号

### 4.2 回测链路（研发/CI）

```
strategy_server --mode backtest
    ├─ DataReader (读取features)
    ├─ DataAligner (数据对齐)
    ├─ StrategyService (信号生成 + 执行)
    │   ├─ CoreAlgorithm (信号生成)
    │   ├─ RiskManager (风控检查)
    │   └─ BacktestExecutor (交易执行)
    └─ MetricsAggregator (指标聚合)
```

**要点**：
- `strategy_server --mode backtest`独立运行，不依赖Orchestrator
- 复用`CoreAlgorithm`产信号；封装回测执行器（TradeSimulator）；产出一致的报表

## 5. 使用示例

### 5.1 回测模式（兼容现有接口）

```powershell
# 使用策略MCP进行回测（兼容现有replay_harness.py接口）
python -m mcp.strategy_server.app `
  --mode backtest `
  --config ./config/defaults.yaml `
  --input ./deploy/data/ofi_cvd `
  --output ./runtime/backtest_results `
  --kinds features `
  --symbols BTCUSDT,ETHUSDT `
  --date 2025-11-10
```

### 5.2 测试网模式（从signals读取）

```powershell
# 测试网模式：从signals目录读取信号，执行交易
python -m mcp.strategy_server.app `
  --mode testnet `
  --config ./config/defaults.yaml `
  --signals-dir ./runtime/ready/signal `
  --sink sqlite `
  --output ./runtime/executions
```

### 5.3 实盘模式（Dry Run）

```powershell
# 实盘模式（Dry Run）：从signals读取，模拟执行
python -m mcp.strategy_server.app `
  --mode live `
  --config ./config/defaults.yaml `
  --signals-dir ./runtime/ready/signal `
  --sink sqlite `
  --dry-run `
  --output ./runtime/executions
```

### 5.4 统一编排（Orchestrator）

```powershell
# 统一编排：启动所有服务
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,strategy,broker,report
```

## 6. 目录与产物

```
./deploy/data/ofi_cvd/                # 权威 raw（prices/orderbook）
./preview/ofi_cvd/                    # 预览/分析（ofi/cvd/fusion/events/features）
./runtime/
  ├─ ready/
  │  ├─ signal/                       # signal_server 就绪标记
  │  └─ strategy/                     # strategy_server 就绪标记
  ├─ signals.db                       # 可选：SQLite Sink
  ├─ signals/*.jsonl                 # 可选：JSONL Sink（signals）
  ├─ executions/*.jsonl              # strategy 执行日志（orders/fills）
  └─ reports/*.jsonl|*.md|*.html     # 报表产物
```

## 7. API契约（摘要）

### 7.1 Features（features.jsonl / features.db）

```json
{
  "ts_ms": 1730790000456,
  "symbol": "BTCUSDT",
  "mid": 70325.1,
  "best_bid": 70325.0,
  "best_ask": 70325.2,
  "spread_bps": 1.2,
  "z_ofi": 1.8,
  "z_cvd": 0.9,
  "fusion_score": 1.4,
  "scenario_2x2": "A_L"
}
```

### 7.2 Signals（signals.jsonl / signals.db）

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
  "gating": false
}
```

### 7.3 Executions（executions/*.jsonl）

```json
{
  "ts_ms": 1730790000789,
  "order_id": "...",
  "symbol": "BTCUSDT",
  "side": "BUY",
  "qty": 0.001,
  "price": 70330.5,
  "status": "FILLED",
  "slippage": 0.5,
  "fee": 0.0003,
  "risk_state": {
    "mode": "active",
    "daily_loss": 0.0,
    "vol_target": 0.1
  }
}
```

## 8. 兼容性保证

### 8.1 与现有回测路径兼容

**策略**：
- 保持 `scripts/replay_harness.py` 的接口不变
- 策略MCP的回测模式可以完全替代现有回测流程
- 输出格式保持一致（trades.jsonl, pnl_daily.jsonl等）

**验证**：
- 使用相同输入数据，对比输出结果
- 确保PnL计算结果一致（等价性测试：|Δ| < 1e-8）

### 8.2 向后兼容

**策略**：
- 现有回测脚本（`scripts/replay_harness.py`）可以继续使用
- 策略MCP作为新选项，逐步迁移
- 两种方式可以并存

### 8.3 服务精简兼容

**移除服务**：
- `data_feed_server`：功能由`harvest_server`覆盖，代码保留为示例
- `ofi_feature_server`：特征计算在库层，由`signal_server`内部调用，代码保留为示例
- `ofi_risk_server`：逻辑合并到`strategy_server`，代码保留为示例

**迁移路径**：
1. 下线移除服务的Orchestrator spec
2. 将`ofi_risk_server`的逻辑并入`strategy_server`
3. 统一使用`signals`作为Strategy的唯一入口

## 9. 风控与模式（合并策略）

### 9.1 信号层门控（CoreAlgorithm）

**保留在CoreAlgorithm**：
- 组件暖启动检查
- 融合一致性校验
- 背离加成计算
- 分场景阈值判定
- lag/spread基础护栏

**职责**：产信号，仅最小门控

### 9.2 执行层风控（StrategyServer）

**合并到strategy_server**（原ofi_risk_server逻辑）：
- StrategyMode判定（下单前置校验）
- 风险墙检查（日内损失限制）
- 目标仓位计算（波动率目标）
- 持仓管理（多空平衡）

**职责**：执行前风控，确保下单决策合规

**实现**：
```python
# mcp/strategy_server/risk/risk_manager.py

class RiskManager:
    """风险管理器（合并ofi_risk_server逻辑）"""
    
    def check_signal(self, signal: Dict, market_data: Dict) -> Dict:
        """检查信号是否允许执行
        
        Returns:
            {
                "allow": bool,
                "reason": str,
                "risk_state": {
                    "mode": str,
                    "daily_loss": float,
                    "vol_target": float,
                }
            }
        """
        # 1. StrategyMode检查
        # 2. 风险墙检查
        # 3. 目标仓位计算
        # 4. 返回检查结果
        pass
```

## 10. P0/P1缺口与修复

### 10.1 P0缺口（必须先补齐）

#### 10.1.1 执行层抽象不足（已修复）
- ✅ **问题**：StrategyService同时握有TradeSimulator和实盘下单逻辑，模式分支在同一处判断
- ✅ **修复**：抽象IExecutor接口，BacktestExecutor封装TradeSimulator，LiveExecutor封装Broker API

#### 10.1.2 回测/实盘等价性测试套件（待实现）

```python
# mcp/strategy_server/tests/test_equivalence.py

def test_equivalence_backtest_vs_live():
    """等价性测试：同一输入，BacktestExecutor vs LiveExecutor(dry-run)的成交轨迹/费用/PnL对齐"""
    # 1. 准备测试数据（features + quotes）
    test_features = load_test_features("test_data/features.jsonl")
    
    # 2. 运行BacktestExecutor
    backtest_executor = BacktestExecutor(config, core_algo)
    backtest_results = []
    for feature_row in test_features:
        signal = core_algo.process_feature_row(feature_row)
        market_data = backtest_adapter.get_market_data(symbol, feature_row)
        result = backtest_executor.execute(signal, market_data)
        if result:
            backtest_results.append(result)
    
    # 3. 运行LiveExecutor(dry-run)
    live_executor = LiveExecutor(testnet_adapter, config)
    live_results = []
    for feature_row in test_features:
        signal = core_algo.process_feature_row(feature_row)
        market_data = testnet_adapter.get_market_data(symbol, feature_row)
        result = live_executor.execute(signal, market_data)
        if result:
            live_results.append(result)
    
    # 4. 逐条对比（误差阈值<1e-8）
    assert len(backtest_results) == len(live_results)
    for bt, lv in zip(backtest_results, live_results):
        assert abs(bt.price - lv.price) < 1e-8
        assert abs(bt.fee - lv.fee) < 1e-8
        assert abs(bt.pnl - lv.pnl) < 1e-8
```

#### 10.1.3 适配器契约具体化（已修复）
- ✅ **问题**：Testnet/Live是占位说明，未定义节流/重试/幂等/签名/时钟/时区/风控护栏透传等API细则
- ✅ **修复**：在BaseAdapter中明确所有方法的语义、错误码、可重试矩阵与速率限制

#### 10.1.4 风控护栏一致性（已修复）
- ✅ **问题**：实盘执行前在_execute_live_trade才检查confirm/gating，与CoreAlgorithm内部门控可能不一致
- ✅ **修复**：gating/strategy-mode判定固定在CoreAlgorithm的输出契约，执行层只认结果位（confirm/gating_blocked）

### 10.2 P1改进（并行推进）

#### 10.2.1 回测行情获取（已修复）
- ✅ **问题**：BacktestAdapter的get_market_data直接给默认mid/quote，占位实现
- ✅ **修复**：从features宽表读取mid/best_bid/best_ask/spread_bps字段（Harvester已产出）

#### 10.2.2 订单状态机与部分成交（待实现）

```python
# mcp/strategy_server/executors/order_state_machine.py

class OrderStateMachine:
    """订单状态机：NEW → PARTIALLY_FILLED → FILLED/CANCELED/REJECTED"""
    
    def __init__(self):
        self.orders: Dict[str, Order] = {}  # order_id -> Order
    
    def update_order(self, order_id: str, status: OrderStatus, 
                    filled_qty: float = 0, filled_price: float = 0):
        """更新订单状态"""
        order = self.orders.get(order_id)
        if not order:
            return
        
        # 状态迁移
        if order.status == OrderStatus.NEW:
            if status == OrderStatus.PARTIALLY_FILLED:
                order.status = OrderStatus.PARTIALLY_FILLED
                order.filled_quantity += filled_qty
            elif status == OrderStatus.FILLED:
                order.status = OrderStatus.FILLED
                order.filled_quantity = order.quantity
            elif status == OrderStatus.CANCELED:
                order.status = OrderStatus.CANCELED
            elif status == OrderStatus.REJECTED:
                order.status = OrderStatus.REJECTED
        elif order.status == OrderStatus.PARTIALLY_FILLED:
            if status == OrderStatus.FILLED:
                order.status = OrderStatus.FILLED
                order.filled_quantity = order.quantity
            elif status == OrderStatus.CANCELED:
                order.status = OrderStatus.CANCELED
```

#### 10.2.3 运行契约与编排（待实现）
- ⬜ 输出与signal_server同步采用JSONL/SQLite Sink
- ⬜ 统一Schema与分区命名
- ⬜ 写run_manifest、DQ报告以便复现

## 11. Orchestrator编排（最小化）

**启动顺序**：`harvest → signal → strategy → broker → report`

**ProcessSpec（示例）**：

```python
ProcessSpec(
    name="harvest",
    cmd=["mcp.harvest_server.app", "--config", str(config_path)],
    ready_probe="file_exists",
    ready_probe_args={"path": "deploy/data/ofi_cvd"},
    health_probe="file_count",
    health_probe_args={"path": "deploy/data/ofi_cvd", "min_count": 1}
)

ProcessSpec(
    name="signal",
    cmd=["mcp.signal_server.app", "--config", str(config_path)],
    ready_probe="file_exists",
    ready_probe_args={"path": "runtime/ready/signal"},
    health_probe="log_keyword",
    health_probe_args={"keyword": "processed="}
)

ProcessSpec(
    name="strategy",
    cmd=["mcp.strategy_server.app", "--mode", "testnet", "--config", str(config_path)],
    ready_probe="log_keyword",
    ready_probe_args={"keyword": "Strategy Server started"},
    health_probe="file_count",
    health_probe_args={"path": "runtime/executions", "min_count": 1}
)

ProcessSpec(
    name="broker",
    cmd=["mcp.broker_gateway_server.app", "--config", str(config_path)]
)

ProcessSpec(
    name="report",
    cmd=["mcp.report_server.app", "--config", str(config_path)]
)
```

## 12. 实施计划（三阶段落地路径）

### 阶段A（P0清零，1周）

**目标**：补齐P0缺口，确保架构稳定，完成服务精简

**任务**：
1. ⬜ **修复必修小改**（当日完成）：
   - ✅ 补充BacktestAdapter导入
   - ✅ 添加adapter.kind属性区分testnet/live
   - ✅ 修复实盘下单尺寸来源（config.execute.notional_per_trade）
   - ✅ 补充time导入
   - ✅ 统一状态类型（OrderStatus枚举）
   - ✅ 删除旧版本描述
2. ⬜ **服务精简**：
   - ⬜ 下线`data_feed_server`、`ofi_feature_server`的Orchestrator spec
   - ⬜ 将`ofi_risk_server`逻辑合并到`strategy_server`（RiskManager）
   - ⬜ 更新文档和配置，移除冗余服务引用
3. ⬜ 抽象IExecutor，拆分BacktestExecutor/LiveExecutor；StrategyService仅面向接口
4. ⬜ 明确BaseAdapter契约：方法、错误码、重试、节流、时钟校准、normalize_quantity、kind属性
5. ⬜ 将gating/strategy-mode只在CoreAlgorithm产出；执行层不再重复判定（更新接口契约说明）
6. ⬜ 回测行情由features宽表提供，落地字段映射：mid/best_bid/best_ask/spread_bps
7. ⬜ 编写等价性测试套件框架（test_equivalence.py）

**交付物**：
- IExecutor接口和两个实现
- BaseAdapter完整契约文档
- CoreAlgorithm输出契约文档（更新docs/api_contracts.md）
- BacktestAdapter从features宽表读取行情
- 等价性测试套件框架

### 阶段B（并行推进，1-2周）

**目标**：明确服务关系，实现回测和实时模式，完成单一事实来源

**任务**：
1. ⬜ **明确与signal_server的并行关系**
   - signal_server：产出信号（CoreAlgorithm），输出到signals目录/SQLite
   - strategy_server：**只读signals**，执行交易（IExecutor）
   - 并行运行，不互相依赖，**signals为唯一边界**
2. ⬜ **实现回测模式**
   - 复用replay_harness流程：DataReader → DataAligner → StrategyService → MetricsAggregator
   - StrategyService集成CoreAlgorithm、RiskManager和BacktestExecutor
   - BacktestExecutor暴露TradeSimulator接口（get_trades、get_pnl_daily等）
   - **独立运行**，不依赖Orchestrator
3. ⬜ **实现实时模式**
   - **从signals目录读取**（JSONL或SQLite），不直接读features
   - 监听signal_server生成的signals文件
   - 调用RiskManager进行风控检查
   - 调用LiveExecutor执行交易
   - 保存execution结果到executions目录
   - **幂等处理**：通过order_id去重，防止重复执行
4. ⬜ **订单状态机最小闭环**（建议优化）：
   - NEW→PARTIALLY_FILLED→FILLED/CANCELED/REJECTED
   - 支持部分成交与撤单
   - 纳入等价性测试集（部分成交合并、撮合延迟）
5. ⬜ **等价性测试套件**（DoD自动化）：
   - 同一输入对比BacktestExecutor vs LiveExecutor(dry-run)的成交与PnL
   - pytest -k equivalence绑定到CI（作为合并闸门）
   - replay_harness vs strategy_server backtest产物一致测试
6. ⬜ **适配器实现**（建议优化：lot/精度校验）：
   - Binance Testnet（签名/时钟/节流/幂等键）
   - Dry-Run通路跑通
   - normalize_quantity实现（tickSize/stepSize/minNotional校验）
7. ⬜ LiveAdapter实现：Binance Live（dry_run模式）
8. ⬜ **费用与滑点参数化**（建议优化）：
   - 统一ExecutionParams（maker/taker、阶梯费率、冲击成本）
   - Backtest/Live共享参数化逻辑，提升等价性可控度

**交付物**：
- 回测模式完整实现（可替代replay_harness.py）
- 实时模式完整实现（监听signals目录）
- 订单状态机实现
- 等价性测试套件（通过测试）
- TestnetAdapter实现（连接测试网API）
- LiveAdapter实现（dry_run模式）

### 阶段C（1周）

**目标**：Orchestrator集成与文档完善，完成端到端冒烟

**任务**：
1. ⬜ **Orchestrator集成**
   - 新增`build_strategy_spec()`函数（返回ProcessSpec）
   - 启动顺序：harvest → signal → strategy → broker → report
   - 就绪探针：log_keyword（"Strategy Server started"）
   - 健康探针：file_count（检查executions/*.jsonl）
   - 最小重启策略：on_failure，max_restarts=2
   - **移除冗余服务的ProcessSpec**（data_feed、ofi_feature、ofi_risk）
2. ⬜ **配置管理**
   - 在config/defaults.yaml中添加strategy_server配置段
   - 添加risk配置段（合并ofi_risk_server配置）
   - 支持环境变量覆盖（API密钥等）
   - 与现有配置结构保持一致
3. ⬜ **文档完善**
   - 更新README.md（添加strategy_server说明，移除冗余服务）
   - 更新TASK_INDEX.md（添加新任务卡）
   - 更新docs/api_contracts.md（固化数据流与边界，单一事实来源）
   - 提供使用指南与环境覆盖说明
   - **更新MCP服务架构文档**（精简合并版V4.2）
4. ⬜ 输出与signal_server一致的Sink；加运行清单与指标聚合脚本
5. ⬜ **端到端冒烟测试**
   - 实时链路：1小时无错误重启、无死信溢出、探针稳定
   - 回测链路：与旧回放产物一致（指标Δ<1e-8）

**交付物**：
- Orchestrator集成（ProcessSpec、启动顺序、健康检查）
- 配置管理（defaults.yaml、环境变量覆盖）
- 完整文档（README、TASK_INDEX、api_contracts、使用指南）
- 统一Sink输出（JSONL/SQLite）
- run_manifest和DQ报告

**总预计时间**：4-5周（阶段A：1周，阶段B：1-2周，阶段C：1周）

## 13. 优势

### 13.1 统一入口
- 回测、测试网、实盘都通过同一个策略MCP执行
- 策略逻辑集中管理，易于维护

### 13.2 代码复用
- 复用现有的 `CoreAlgorithm` 和 `TradeSimulator`
- 不需要重写策略逻辑

### 13.3 易于扩展
- 适配器模式易于添加新环境
- 策略逻辑与执行环境解耦

### 13.4 向后兼容
- 现有回测脚本（`scripts/replay_harness.py`）可以继续使用
- 策略MCP作为新选项，逐步迁移
- 两种方式可以并存

### 13.5 精简合并优势

- ✅ **最小可跑闭环**：只保留5个核心服务，减少维护成本
- ✅ **单一事实来源**：features → signals → strategy，避免多入口/二义性
- ✅ **逻辑内聚**：风控逻辑合并到strategy_server，减少服务间通信
- ✅ **易于验证**：等价性测试确保回测与实时一致

## 14. 验收标准（DoD - 上线闸门）

### 14.1 等价性（P0，必须通过）

**标准**：同一features+quotes输入，BacktestExecutor与LiveExecutor(dry-run)的成交轨迹/费用/PnL按笔对齐

**测试方法**：
```python
# 使用等价性测试套件
python -m pytest mcp/strategy_server/tests/test_equivalence.py -v
```

**通过标准**：
- 成交轨迹：每笔交易的price/quantity/fee/slippage绝对误差<1e-8
- PnL：累计PnL绝对误差<1e-8
- 成交顺序：交易顺序完全一致

### 14.2 回测兼容性（P0，必须通过）

**标准**：新旧路径（replay_harness vs strategy_server backtest）PnL/成交结果一致

**测试方法**：
1. 使用相同输入数据，分别运行：
   - `scripts/replay_harness.py`（原有路径）
   - `python -m mcp.strategy_server.app --mode backtest`（新路径）
2. 对比输出结果（trades.jsonl, pnl_daily.jsonl）

**通过标准**：
- PnL计算结果一致（误差<1e-8）
- 交易记录一致（顺序、价格、数量）
- 输出格式一致

### 14.3 契约稳定（P0，必须通过）

**标准**：BaseAdapter/IExecutor/CoreAlgorithm输出字段与含义在`/docs/api_contracts.md`固化

**检查方法**：
1. 检查`docs/api_contracts.md`是否包含：
   - BaseAdapter所有方法的输入输出契约
   - IExecutor接口契约
   - CoreAlgorithm输出契约（signal字段：confirm/gating_blocked/regime等）
   - **数据流与边界**（回测独立、实时编排）
2. CLI与配置与方案示例保持一致

**通过标准**：
- 所有接口契约已文档化
- 数据流与边界已明确（回测：DataReader→StrategyService→Metrics；实时：Harvest→Signal→Strategy→Broker）
- CLI参数与示例一致
- 配置格式与示例一致

### 14.4 Sink一致性（P0，必须通过）

**标准**：保持与signal_server相同的JSONL/SQLite Sink选项与启动方式

**检查方法**：
1. 检查strategy_server是否支持：
   - `--sink jsonl`（JSONL输出）
   - `--sink sqlite`（SQLite输出）
   - `--sink dual`（双Sink：JSONL + SQLite）
2. 检查输出目录结构是否与signal_server一致：
   - `runtime/ready/strategy/`（JSONL）
   - `runtime/signals.db`（SQLite，如果启用）

**通过标准**：
- Sink选项与signal_server一致
- 输出目录结构与signal_server一致
- 文件格式与signal_server一致

### 14.5 服务精简（P0，必须通过）

**标准**：移除的服务不再被Orchestrator引用，文档/配置/脚本同步更新

**检查方法**：
1. 检查Orchestrator中是否还有`data_feed_server`、`ofi_feature_server`、`ofi_risk_server`的ProcessSpec
2. 检查README和文档是否已更新，移除冗余服务说明
3. 检查配置文件中是否还有冗余服务的配置段

**通过标准**：
- 所有移除服务的引用已清理
- 文档和配置已同步更新
- 代码保留为示例/备档，但不进入部署链路

### 14.6 单一事实来源（P0，必须通过）

**标准**：实时模式strategy_server只读signals，不直接读features

**检查方法**：
1. 检查strategy_server实时模式的代码，确认只从signals目录读取
2. 检查是否有跨层读取features的逻辑
3. 验证数据流：features → signals → strategy

**通过标准**：
- strategy_server实时模式只读signals
- 无跨层读取features的逻辑
- 数据流清晰，单一事实来源

### 14.7 可观测性（P1，必须通过）

**标准**：统一Sink（JSONL/SQLite）、运行清单与指标聚合产物可复现回测报告

**检查方法**：
1. 运行回测，检查输出：
   - `runtime/backtest/{run_id}/signals/`（JSONL）
   - `runtime/backtest/{run_id}/signals.db`（SQLite）
   - `runtime/backtest/{run_id}/run_manifest.json`
   - `runtime/backtest/{run_id}/trades.jsonl`
   - `runtime/backtest/{run_id}/pnl_daily.jsonl`
2. 使用现有报表工具生成报告，验证可复现

**通过标准**：
- 所有输出文件格式正确
- 报表工具可以正常读取并生成报告
- 结果可复现（相同输入产生相同输出）

## 15. 总结

本方案将回测路径上的策略逻辑（CoreAlgorithm + TradeSimulator）整合到统一的MCP策略服务中，通过适配器模式支持回测、测试网、实盘三种环境。

### 15.1 核心特点

- ✅ **统一入口**：一个策略MCP服务支持三种环境
- ✅ **代码复用**：复用现有策略逻辑（CoreAlgorithm + TradeSimulator），不需要重写
- ✅ **执行层抽象**：IExecutor接口统一回测和实盘执行逻辑，避免条件分支
- ✅ **向后兼容**：现有回测脚本（`scripts/replay_harness.py`）可以继续使用
- ✅ **易于扩展**：适配器模式易于添加新环境
- ✅ **精简合并**：移除冗余服务，合并风控逻辑，形成最小可跑闭环
- ✅ **单一事实来源**：features → signals → strategy，避免多入口/二义性

### 15.2 关键改进（按快评建议和精简合并要求）

**P0缺口（已补齐）**：
- ✅ 执行层抽象：IExecutor接口，BacktestExecutor/LiveExecutor分离
- ✅ 适配器契约：BaseAdapter明确所有方法的语义、错误码、重试策略
- ✅ 风控一致性：gating/strategy-mode只在CoreAlgorithm判定，执行层只认结果位
- ⬜ 等价性测试：待实现（阶段A）

**P1改进（已部分补齐）**：
- ✅ 回测行情获取：从features宽表读取mid/best_bid/best_ask/spread_bps
- ✅ 服务精简：移除data_feed_server、ofi_feature_server，冻结ofi_risk_server
- ✅ 风控合并：将ofi_risk_server逻辑合并到strategy_server
- ⬜ 订单状态机：待实现（阶段B）
- ⬜ 运行契约与编排：待实现（阶段C）

### 15.3 关键优化点（已明确）

**经过全项目深度检阅和反馈，已明确以下关键点**：

1. **与signal_server的关系（已明确）**
   - **并行运行**：signal_server产出信号，strategy_server执行交易
   - signal_server：CoreAlgorithm生成信号，输出到signals目录/SQLite
   - strategy_server：**只读signals目录**，通过IExecutor执行交易
   - 两者不互相依赖，**signals为唯一边界**，不跨层读取features

2. **数据流与边界（已固化）**
   - **回测（独立）**：DataReader → StrategyService（CoreAlgorithm产信号 + BacktestExecutor/TradeSimulator执行）→ MetricsAggregator
   - **实时（编排）**：Harvest（features）→ Signal（signals）→ Strategy（执行）→ Broker（Testnet/Live）
   - **统一事实来源**：features宽表作为统一数据源

3. **Orchestrator集成（已明确）**
   - 新增`build_strategy_spec()`函数（返回ProcessSpec）
   - 启动顺序：harvest → signal → strategy → broker → report
   - 就绪探针：log_keyword（"Strategy Server started"）
   - 健康探针：file_count（检查executions/*.jsonl）
   - 回测模式独立运行，不依赖Orchestrator

4. **目录与服务命名（已统一）**
   - 与现有目录保持一致：`mcp/harvest_server`、`mcp/signal_server`、`mcp/strategy_server`、`mcp/broker_gateway_server`
   - 输出目录：`runtime/ready/strategy/`（JSONL）、`runtime/signals.db`（SQLite）

**详细评估报告**：请参考 `策略MCP整合方案-评估与优化.md`

### 15.4 主要风险与对策

#### 15.4.1 双服务边界不清导致重复/漏读（实时）

**风险**：signal_server和strategy_server可能重复读取或漏读signals文件

**对策**：
- ✅ 在Orchestrator中固定"signals目录"为唯一入口
- ✅ strategy_server只读signals目录，**不直接读取features**（单一事实来源）
- ✅ 使用file_count健康探针与最小重启策略兜底
- ✅ 支持按order_id幂等性去重，避免重复执行

#### 15.4.2 回测结果与实时干路定义不一致

**风险**：回测和实时使用不同的数据源或计算逻辑，导致结果不一致

**对策**：
- ✅ 把features宽表作为统一"事实来源"
- ✅ 在README和docs中明示数据流与边界
- ✅ 等价性测试套件确保回测和实时（dry-run）结果一致
- ✅ 回测兼容性测试确保新旧路径结果一致

#### 15.4.3 编排耦合

**风险**：过度依赖Orchestrator，导致研发和CI环境不可用

**对策**：
- ✅ 独立运行的backtest模式（不依赖Orchestrator）
- ✅ 确保研发与CI可用（可以直接运行strategy_server）
- ✅ 生产走编排链路（通过Orchestrator统一管理）

### 15.5 实施建议

**结论**：**条件性GO** - P0关键结构基本补齐，服务精简方案明确，剩余几个小坑修掉即可进入阶段A落实与对齐测试。方向正确，需先把"与现有服务关系、数据流、Orchestrator集成、服务精简"4个关键点补齐后再全量推进（建议按A/B/C三阶段执行）。

**立即行动**（按反馈落地顺序和精简合并要求）：

1. **先修6个"必修小改"**（当日完成，提交MR）：
   - ✅ 补充BacktestAdapter导入
   - ✅ 添加adapter.kind属性（区分testnet/live）
   - ✅ 修复实盘下单尺寸来源（config.execute.notional_per_trade）
   - ✅ 补充time导入
   - ✅ 统一状态类型（OrderStatus枚举）
   - ✅ 删除旧版本描述

2. **服务精简**（阶段A，1周内）：
   - ⬜ 下线`data_feed_server`、`ofi_feature_server`的Orchestrator spec
   - ⬜ 将`ofi_risk_server`逻辑合并到`strategy_server`（RiskManager）
   - ⬜ 更新文档和配置，移除冗余服务引用

3. **补全等价性测试骨架并接入CI**（作为合并闸门）：
   - pytest -k equivalence：同一features+quotes → 两执行器成交＋PnL对齐（|Δ|<1e-8）
   - replay_harness vs strategy_server backtest产物一致测试

4. **阶段A（P0清零，1周）**：
   - 抽象IExecutor，明确BaseAdapter契约
   - 编写等价性测试框架
   - 完成服务精简和风控合并

5. **阶段B（并行推进，1-2周）**：
   - 明确与signal_server的并行关系（signals为唯一边界）
   - 实现回测模式（复用replay_harness流程，独立运行）
   - 实现实时模式（从signals读取，不跨层读features）
   - 拉起订单状态机最小闭环与adapter的lot/精度校验

6. **阶段C（1周）**：
   - Orchestrator集成（新增build_strategy_spec，移除冗余服务）
   - 输出Orchestrator的build_strategy_spec()与健康/就绪探针
   - 实现端到端冒烟（实时链路1小时稳定，回测链路等价性验证）
   - 配置管理与文档完善（更新MCP服务架构文档V4.2）
   - 统一Sink输出，run_manifest和DQ报告

**预计时间**：4-5周（阶段A：1周，阶段B：1-2周，阶段C：1周）

---

**文档版本**：v4.2（精简合并版）  
**创建日期**：2025-01-11  
**更新日期**：2025-11-11  
**作者**：AI Assistant  
**审核状态**：待审核

---

## 16. 附录

### 16.1 深度评估报告

详细的项目检阅和优化建议请参考：`策略MCP整合方案-评估与优化.md`

该报告包含：
- 项目架构深度分析
- 方案评估（优点和需要优化的点）
- 详细的优化方案（架构、集成方式、数据流）
- 优化后的实施计划
- 关键风险与应对

### 16.2 MCP服务架构文档

精简合并后的MCP服务架构请参考：`MCP服务架构文档.md`（精简合并版V4.2）

该文档包含：
- 服务清单（精简后5个核心服务）
- 数据流与控制流（实时/回测两条链路）
- API契约（Features/Signals/Executions）
- Orchestrator编排（最小化）
- 运行与配置（最小）

