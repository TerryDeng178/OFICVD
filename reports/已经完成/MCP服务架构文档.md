# MCP服务架构文档

**生成时间**: 2025-01-11  
**版本**: v1.0  
**项目**: OFI+CVD 交易系统

---

## 执行摘要

本项目采用**MCP（Model Context Protocol）薄壳架构**，将核心业务逻辑封装在`src/alpha_core/`中，通过MCP服务器提供统一接口。所有MCP服务由`orchestrator/run.py`统一编排管理。

**架构原则**：
- **薄壳设计**：MCP服务器仅做参数解析和调用，不包含业务逻辑
- **统一编排**：所有服务由Orchestrator统一启动、监控和管理
- **可复用库**：核心逻辑在`src/alpha_core/`中，MCP服务可复用

---

## MCP服务概览

| 服务名称 | 状态 | 功能描述 | 核心依赖 |
|---------|------|----------|---------|
| **harvest_server** | ✅ 已实现 | 实时行情/成交/订单簿采集 | `alpha_core.ingestion.harvester` |
| **signal_server** | ✅ 已实现 | 信号生成服务（CoreAlgorithm） | `alpha_core.signals.core_algo` |
| **broker_gateway_server** | ✅ 已实现 | 交易所网关（Mock模式） | 无（Mock实现） |
| **report_server** | ❌ 未实现 | 报表生成服务 | 待定 |
| **data_feed_server** | ❌ 未实现 | 统一数据源接口 | 待定 |
| **ofi_feature_server** | ❌ 未实现 | OFI特征计算服务 | `alpha_core.microstructure.*` |
| **ofi_risk_server** | ❌ 未实现 | 风控服务 | `alpha_core.risk.strategy_mode` |

---

## 1. harvest_server（采集服务器）

### 状态
✅ **已实现** - 生产可用

### 功能描述
实时采集Binance Futures的行情、成交和订单簿数据，输出为JSONL或Parquet格式。

**核心功能**：
- WebSocket实时数据采集
- 自动重连机制
- 分片轮转（按行数/时间）
- 数据质量检查（DQ Gate）
- 支持OFI/CVD/Fusion计算

### 接口参数

```bash
python -m mcp.harvest_server.app [OPTIONS]
```

**参数**：
- `--config <path>`: 配置文件路径（默认: `./config/defaults.yaml`）
- `--output <dir>`: 输出根目录（覆盖配置中的`harvest.output.base_dir`）
- `--format <jsonl|parquet>`: 输出格式（默认: 使用配置）
- `--rotate.max_rows <N>`: 单文件最大行数（默认: 使用配置）
- `--rotate.max_sec <N>`: 轮转时间间隔（秒，默认: 使用配置）

### 使用示例

```powershell
# 基本使用（使用默认配置）
python -m mcp.harvest_server.app --config ./config/defaults.yaml

# 指定输出目录和格式
python -m mcp.harvest_server.app `
  --config ./config/defaults.yaml `
  --output ./deploy/data/ofi_cvd `
  --format parquet

# 自定义轮转参数
python -m mcp.harvest_server.app `
  --config ./config/defaults.yaml `
  --rotate.max_rows 200000 `
  --rotate.max_sec 60
```

### 配置要求

配置文件需包含以下部分：
```yaml
harvest:
  output:
    base_dir: "./deploy/data/ofi_cvd"
    format: "parquet"  # 或 "jsonl"
  rotate:
    max_rows: 200000
    max_sec: 60

symbols:
  - "BTCUSDT"
  - "ETHUSDT"
  # ... 更多交易对
```

### Orchestrator集成

在`orchestrator/run.py`中，harvest_server通过以下方式启动：

```python
ProcessSpec(
    name="harvest",
    cmd=["mcp.harvest_server.app", "--config", str(config_path)],
    # ... 其他配置
)
```

### 输出格式

**Parquet格式**（推荐）：
- 目录结构：`{output_dir}/{symbol}/date={YYYY-MM-DD}/part-{timestamp}.parquet`
- Schema：统一Row Schema（包含`ts_ms`, `symbol`, `price`, `qty`, `side`, `is_maker`等字段）

**JSONL格式**：
- 目录结构：`{output_dir}/{symbol}/date={YYYY-MM-DD}/part-{timestamp}.jsonl`
- 每行一个JSON对象

---

## 2. signal_server（信号服务器）

### 状态
✅ **已实现** - 生产可用

### 功能描述
读取特征数据（JSONL/Parquet），通过`CoreAlgorithm`生成交易信号，支持JSONL/SQLite双Sink输出。

**核心功能**：
- 读取特征数据（支持JSONL和Parquet）
- 调用`CoreAlgorithm`生成信号
- 支持批处理模式和监听模式（`--watch`）
- 双Sink输出（JSONL + SQLite）
- 信号去重和预热期过滤

### 接口参数

```bash
python -m mcp.signal_server.app [OPTIONS]
```

**参数**：
- `--config <path>`: 配置文件路径（默认: 使用`defaults.yaml`）
- `--input <path|dir|->`: 特征数据源（文件/目录/stdin，默认: `-`）
- `--sink <jsonl|sqlite|dual|null>`: Sink类型（默认: 使用配置）
- `--out <dir>`: 输出目录（默认: `./runtime`）
- `--symbols <SYMBOL ...>`: 交易对白名单（可选）
- `--watch`: 监听模式（持续扫描目录中的新文件）
- `--print`: 打印生成的信号（用于调试）

### 使用示例

```powershell
# 批处理模式（一次性处理所有数据）
python -m mcp.signal_server.app `
  --config ./config/defaults.yaml `
  --input ./deploy/data/ofi_cvd/features `
  --sink dual `
  --out ./runtime/ready/signal

# 监听模式（实时处理新文件）
python -m mcp.signal_server.app `
  --config ./config/defaults.yaml `
  --input ./deploy/data/ofi_cvd/features `
  --sink dual `
  --watch

# 指定交易对白名单
python -m mcp.signal_server.app `
  --config ./config/defaults.yaml `
  --input ./deploy/data/ofi_cvd/features `
  --symbols BTCUSDT ETHUSDT `
  --sink dual
```

### 配置要求

配置文件需包含`signal`部分：
```yaml
signal:
  # CoreAlgorithm配置
  # ... 详见 config/defaults.yaml

strategy_mode:
  # StrategyMode配置
  # ... 详见 config/defaults.yaml
```

### 输入格式

**支持格式**：
- JSONL：每行一个JSON对象
- Parquet：使用pandas读取（需安装pandas）

**字段映射**（Parquet → CoreAlgorithm）：
- `ofi_z` → `z_ofi`
- `cvd_z` → `z_cvd`
- `lag_ms_*` → `lag_sec`（转换为秒）

### 输出格式

**JSONL Sink**：
- 文件：`{output_dir}/signals_{run_id}.jsonl`
- 格式：每行一个信号JSON对象

**SQLite Sink**：
- 文件：`{output_dir}/signals_{run_id}.db`
- 表：`signals`（包含所有信号字段）

**Dual Sink**：
- 同时输出JSONL和SQLite

### Orchestrator集成

在`orchestrator/run.py`中，signal_server通过以下方式启动：

```python
signal_cmd = [
    "mcp.signal_server.app",
    "--config", str(config_path),
    "--input", str(features_dir),
    "--sink", actual_sink_kind,  # "dual" 或 "jsonl" 或 "sqlite"
    "--out", str(output_dir)
]
```

### 信号格式

信号JSON对象包含以下字段：
```json
{
  "ts_ms": 1234567890123,
  "symbol": "BTCUSDT",
  "signal_type": "strong_buy",
  "confirm": true,
  "score": 0.85,
  "gating_blocked": false,
  "strategy_mode": "aggressive",
  // ... 更多字段
}
```

---

## 3. broker_gateway_server（交易所网关服务器）

### 状态
✅ **已实现** - Mock模式可用

### 功能描述
监听信号文件，生成模拟订单。当前仅支持Mock模式，未来将支持真实交易所API。

**核心功能**：
- 监听信号目录（JSONL文件）
- Mock订单生成（模拟订单执行）
- 抽样率参数化（普通信号按概率下单）
- 订单状态机（简化版：直接FILLED）

### 接口参数

```bash
python -m mcp.broker_gateway_server.app [OPTIONS]
```

**参数**：
- `--mock <0|1>`: Mock模式（1=启用，0=禁用，默认: 0）
- `--signal-dir <dir>`: 信号目录（默认: `./runtime/ready/signal`）
- `--output <file>`: 订单输出文件（默认: `./runtime/mock_orders.jsonl`）
- `--seed <N>`: 随机数种子（默认: 42，用于可复现的抽样）
- `--sample_rate <0.0-1.0>`: 普通信号抽样率（默认: 0.2，即1/5概率下单）

### 使用示例

```powershell
# 基本使用（Mock模式）
python -m mcp.broker_gateway_server.app --mock 1

# 指定信号目录和输出文件
python -m mcp.broker_gateway_server.app `
  --mock 1 `
  --signal-dir ./runtime/ready/signal `
  --output ./runtime/mock_orders.jsonl

# 自定义抽样率（50%概率下单）
python -m mcp.broker_gateway_server.app `
  --mock 1 `
  --sample_rate 0.5 `
  --seed 42
```

### 订单生成逻辑

**信号过滤**：
- 只处理`confirm=True`的信号
- 解析`signal_type`：`strong_buy`, `buy`, `strong_sell`, `sell`

**抽样规则**：
- `STRONG`信号：100%下单
- `NORMAL`信号：按`sample_rate`概率下单（默认20%）

### 输出格式

订单JSON对象：
```json
{
  "order_id": "MOCK_000001",
  "symbol": "BTCUSDT",
  "side": "BUY",
  "strength": "STRONG",
  "signal_type": "strong_buy",
  "signal_score": 0.85,
  "signal_ts_ms": 1234567890123,
  "order_ts_ms": 1234567890124,
  "status": "FILLED",
  "filled_qty": 0.001,
  "filled_price": 50000.0,
  "fee": 0.0001
}
```

### Orchestrator集成

在`orchestrator/run.py`中，broker_gateway_server通过以下方式启动：

```python
ProcessSpec(
    name="broker",
    cmd=[
        "mcp.broker_gateway_server.app",
        "--mock", "1",
        "--output", str(broker_output_path),
        "--seed", "42",
        "--sample_rate", broker_sample_rate
    ],
    # ... 其他配置
)
```

### 未来扩展

- [ ] 支持Binance Testnet API
- [ ] 支持Binance Live API
- [ ] 实现完整的订单状态机（NEW→PARTIALLY_FILLED→FILLED/CANCELED/REJECTED）
- [ ] 支持部分成交和撤单

---

## 4. report_server（报表服务器）

### 状态
❌ **未实现** - 仅TODO注释

### 功能描述（计划）
读取日志文件（`logs/*.jsonl`），生成日报、分层指标和参数Scoreboard。

### 计划功能

- 读取`logs/*.jsonl`文件
- 生成日报（每日交易统计）
- 分层指标（按交易对/时间段/策略模式等）
- 参数Scoreboard（参数优化结果展示）

### 实现建议

```python
# mcp/report_server/app.py

def generate_daily_report(log_dir: Path, output_dir: Path):
    """生成日报"""
    # 读取所有JSONL日志文件
    # 按日期聚合统计
    # 生成HTML/JSON报告
    pass

def generate_layered_metrics(log_dir: Path, output_dir: Path):
    """生成分层指标"""
    # 按交易对、时间段、策略模式等维度统计
    pass

def generate_scoreboard(log_dir: Path, output_dir: Path):
    """生成参数Scoreboard"""
    # 展示参数优化结果
    pass
```

---

## 5. data_feed_server（数据源服务器）

### 状态
❌ **未实现** - 仅TODO注释

### 功能描述（计划）
提供统一Row Schema的数据源接口，支持实时数据快照和历史数据切片。

### 计划功能

- `/get_live_snapshot`: 实时数据快照
- `/get_historical_slice`: 历史数据切片
- 统一Row Schema输出
- DQ Gate数据质量检查

### 实现建议

```python
# mcp/data_feed_server/app.py

def get_live_snapshot(symbols: List[str]) -> List[Dict]:
    """获取实时数据快照"""
    # 从harvest_server或数据库读取最新数据
    pass

def get_historical_slice(
    symbols: List[str],
    start_ts: int,
    end_ts: int
) -> List[Dict]:
    """获取历史数据切片"""
    # 从Parquet/JSONL文件读取历史数据
    pass
```

---

## 6. ofi_feature_server（OFI特征服务器）

### 状态
❌ **未实现** - 仅导入语句

### 功能描述（计划）
特征计算服务器，调用`alpha_core`组件计算OFI/CVD/FUSION/DIVERGENCE特征。

### 计划功能

- 输入：统一Row Schema批次`rows[]`
- 处理：调用`RealOFI`/`RealCVD`，经`OFI_CVD_Fusion`与`DivergenceDetector`
- 输出：`{z_ofi, z_cvd, fusion:{side,consistency,...}, divergence:{...}, fp}`

### 已导入的组件

```python
from alpha_core.microstructure.ofi import RealOFICalculator, OFIConfig
from alpha_core.microstructure.cvd import RealCVDCalculator, CVDConfig
from alpha_core.microstructure.fusion import OFI_CVD_Fusion, OFICVDFusionConfig
from alpha_core.microstructure.divergence import DivergenceDetector, DivergenceConfig
```

### 实现建议

```python
# mcp/ofi_feature_server/app.py

def process_batch(rows: List[Dict]) -> List[Dict]:
    """处理批次数据"""
    # 1. 计算OFI
    ofi_calc = RealOFICalculator(config=ofi_config)
    z_ofi = ofi_calc.compute(rows)
    
    # 2. 计算CVD
    cvd_calc = RealCVDCalculator(config=cvd_config)
    z_cvd = cvd_calc.compute(rows)
    
    # 3. Fusion
    fusion = OFI_CVD_Fusion(config=fusion_config)
    fusion_result = fusion.compute(z_ofi, z_cvd)
    
    # 4. Divergence
    divergence = DivergenceDetector(config=divergence_config)
    divergence_result = divergence.compute(rows)
    
    # 5. 合并输出
    return {
        "z_ofi": z_ofi,
        "z_cvd": z_cvd,
        "fusion": fusion_result,
        "divergence": divergence_result
    }
```

---

## 7. ofi_risk_server（风控服务器）

### 状态
❌ **未实现** - 仅导入语句

### 功能描述（计划）
风控服务器，使用`StrategyModeManager`做第一层闸门，实现波动率目标仓位与日内损失墙（迟滞）。

### 计划功能

- 使用`StrategyModeManager`做第一层闸门
- 实现波动率目标仓位
- 日内损失墙（迟滞）
- 输出：`{allow, side, qty, lev, mode, reason, risk_state}`

### 已导入的组件

```python
from alpha_core.risk import StrategyModeManager, StrategyMode, MarketActivity
```

### 实现建议

```python
# mcp/ofi_risk_server/app.py

def check_risk(
    signal: Dict,
    current_position: Dict,
    market_data: Dict
) -> Dict:
    """风控检查"""
    # 1. StrategyModeManager检查
    mode_manager = StrategyModeManager(config=risk_config)
    mode_result = mode_manager.check(signal, market_data)
    
    # 2. 波动率目标仓位
    vol_target = compute_volatility_target(market_data)
    
    # 3. 日内损失墙
    daily_loss = compute_daily_loss(current_position)
    loss_wall = check_loss_wall(daily_loss, config.loss_limit)
    
    # 4. 合并结果
    return {
        "allow": mode_result.allow and loss_wall.allow,
        "side": signal.get("side"),
        "qty": compute_quantity(signal, vol_target),
        "lev": compute_leverage(signal, vol_target),
        "mode": mode_result.mode,
        "reason": mode_result.reason or loss_wall.reason,
        "risk_state": {
            "mode": mode_result.mode,
            "daily_loss": daily_loss,
            "vol_target": vol_target
        }
    }
```

---

## Orchestrator集成

### 启动顺序

Orchestrator按照以下顺序启动MCP服务：

1. **harvest_server** - 采集数据
2. **signal_server** - 生成信号（依赖harvest输出）
3. **broker_gateway_server** - 执行交易（依赖signal输出）
4. **report_server** - 生成报表（依赖所有服务输出）

### 健康检查

每个服务都配置了健康检查探针：

- **ready_probe**: 就绪探针（服务是否已启动）
- **health_probe**: 健康探针（服务是否正常运行）

### 配置示例

```python
# orchestrator/run.py

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
    cmd=["mcp.signal_server.app", ...],
    ready_probe="file_exists",
    ready_probe_args={"path": "runtime/ready/signal"},
    health_probe="log_keyword",
    health_probe_args={"keyword": "processed="}
)
```

---

## 数据流

### 实时模式

```
harvest_server (采集)
    ↓ (Parquet/JSONL)
signal_server (信号生成)
    ↓ (JSONL/SQLite)
broker_gateway_server (订单执行)
    ↓ (JSONL)
report_server (报表生成)
```

### 回测模式

```
DataReader (读取历史数据)
    ↓ (特征数据)
signal_server (信号生成)
    ↓ (信号)
TradeSimulator (模拟交易)
    ↓ (交易记录)
MetricsAggregator (指标聚合)
```

---

## 配置管理

### 全局配置

所有MCP服务共享`config/defaults.yaml`配置文件：

```yaml
# 采集配置
harvest:
  output:
    base_dir: "./deploy/data/ofi_cvd"
    format: "parquet"
  rotate:
    max_rows: 200000
    max_sec: 60

# 信号配置
signal:
  # CoreAlgorithm配置
  # ...

# 策略模式配置
strategy_mode:
  # StrategyMode配置
  # ...

# 交易对列表
symbols:
  - "BTCUSDT"
  - "ETHUSDT"
  # ...
```

### 环境变量覆盖

支持通过环境变量覆盖配置：

```powershell
# Windows PowerShell
$env:HARVEST_OUTPUT_DIR = "./custom/data"
$env:SIGNAL_SINK_KIND = "dual"
python -m orchestrator.run
```

---

## 开发指南

### 创建新的MCP服务

1. **创建服务目录**：
   ```bash
   mkdir mcp/my_service
   touch mcp/my_service/app.py
   ```

2. **实现薄壳**：
   ```python
   # mcp/my_service/app.py
   import argparse
   import sys
   from pathlib import Path
   
   # 添加src到路径
   _PROJECT_ROOT = Path(__file__).resolve().parents[2]
   _SRC_DIR = _PROJECT_ROOT / "src"
   if str(_SRC_DIR) not in sys.path:
       sys.path.insert(0, str(_SRC_DIR))
   
   # 导入核心组件
   from alpha_core.my_module import MyComponent
   
   def parse_args():
       parser = argparse.ArgumentParser(description="My MCP Server")
       # ... 添加参数
       return parser.parse_args()
   
   def main():
       args = parse_args()
       # 加载配置
       # 调用核心组件
       # 返回退出码
       return 0
   
   if __name__ == "__main__":
       sys.exit(main())
   ```

3. **集成到Orchestrator**：
   ```python
   # orchestrator/run.py
   ProcessSpec(
       name="my_service",
       cmd=["mcp.my_service.app", "--config", str(config_path)],
       # ... 其他配置
   )
   ```

### 测试MCP服务

```powershell
# 单独测试服务
python -m mcp.harvest_server.app --config ./config/defaults.yaml

# 通过Orchestrator测试
python -m orchestrator.run --mode HOLD
```

---

## 故障排查

### 常见问题

1. **服务启动失败**：
   - 检查配置文件路径
   - 检查Python路径（确保`src/alpha_core`可导入）
   - 检查依赖项是否安装

2. **数据流中断**：
   - 检查上游服务是否正常运行
   - 检查文件权限
   - 检查磁盘空间

3. **性能问题**：
   - 检查日志输出频率
   - 检查文件轮转设置
   - 检查数据库连接池

### 日志位置

- **服务日志**：`logs/{service_name}/`
- **Orchestrator日志**：`logs/orchestrator/`

---

## 未来规划

### 短期（1-2周）

- [ ] 实现`report_server`（报表生成）
- [ ] 完善`broker_gateway_server`（支持Testnet API）
- [ ] 实现`ofi_feature_server`（特征计算服务）

### 中期（1-2月）

- [ ] 实现`ofi_risk_server`（风控服务）
- [ ] 实现`data_feed_server`（统一数据源）
- [ ] 实现`strategy_server`（策略服务，见`策略MCP整合方案.md`）

### 长期（3-6月）

- [ ] 支持多交易所（Binance Spot, OKX等）
- [ ] 支持多策略并行运行
- [ ] 实现分布式部署

---

## 参考文档

- `/README.md` - 主开发文档
- `/docs/architecture_flow.md` - 架构流程图
- `/docs/api_contracts.md` - API契约文档
- `/reports/策略MCP整合方案.md` - 策略服务整合方案
- `/orchestrator/run.py` - Orchestrator实现
- `/config/defaults.yaml` - 默认配置

---

**文档版本**：v1.0  
**最后更新**：2025-01-11  
**维护者**：OFI+CVD开发团队

