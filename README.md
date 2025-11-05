
# OFI+CVD 交易系统 · 主开发文档（Cursor 友好版 · V4）

> **这版更新点（相对 V3）**
> - 采用 **src layout**：将成熟组件打包为 `alpha_core` 可安装包，MCP/Orchestrator 仅做 I/O 适配，不再重写策略逻辑。
> - 明确目录与导入路径，统一在 Cursor 中“就地引用”，避免 `sys.path` 污染。
> - 快速起步脚本与验收检查点对齐任务卡（M1→M2→M3）。

---

## 0. 快速导航（Cursor 固钉建议）
- `/README.md`（本文）
- `/docs/architecture_flow.md`（架构图 · Mermaid）
- `/docs/order_state_machine.md`（订单状态机 · Mermaid）
- `/docs/api_contracts.md`（MCP 工具契约）
- `/mcp/*/app.py`（服务薄壳）
- `/orchestrator/run.py`（主控循环）
- `/config/defaults.yaml`（全局参数，含 OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE）
- `/TASK_INDEX.md` & `tasks/*.md`（任务卡）

---

## 1) 目录结构（V4 · 可安装包 + MCP 薄壳）
```
repo/
├─ pyproject.toml                                # 包构建配置（setuptools）
├─ README.md                                     # 主开发文档（本文）
├─ TASK_INDEX.md                                 # 任务卡索引
├─ .gitignore                                    # Git 忽略文件
│
├─ src/                                          # 源代码目录（src layout）
│  └─ alpha_core/                                # 核心组件包
│     ├─ __init__.py
│     ├─ microstructure/                         # 微结构分析模块
│     │  ├─ __init__.py
│     │  ├─ ofi/                                 # OFI 计算器
│     │  │  ├─ __init__.py
│     │  │  └─ real_ofi_calculator.py
│     │  ├─ cvd/                                 # CVD 计算器
│     │  │  ├─ __init__.py
│     │  │  └─ real_cvd_calculator.py
│     │  ├─ fusion/                              # OFI+CVD 融合
│     │  │  ├─ __init__.py
│     │  │  └─ ofi_cvd_fusion.py
│     │  └─ divergence/                          # 背离检测
│     │     ├─ __init__.py
│     │     └─ ofi_cvd_divergence.py
│     └─ risk/                                   # 风险管理模块
│        ├─ __init__.py
│        └─ strategy_mode.py                     # StrategyModeManager
│
├─ mcp/                                          # MCP 服务器（薄壳层）
│  ├─ data_feed_server/
│  │  └─ app.py                                  # 数据源服务器
│  ├─ ofi_feature_server/
│  │  └─ app.py                                  # 特征计算服务器（import alpha_core.*）
│  ├─ ofi_risk_server/
│  │  └─ app.py                                  # 风控服务器（import alpha_core.*）
│  ├─ broker_gateway_server/
│  │  └─ app.py                                  # 交易所网关服务器
│  └─ report_server/
│     └─ app.py                                  # 报表服务器
│
├─ orchestrator/
│  └─ run.py                                     # 主控循环
│
├─ config/                                       # 配置文件
│  ├─ defaults.yaml                              # 默认配置（OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE）
│  └─ overrides.d/                               # 配置覆盖目录
│
├─ docs/                                         # 文档目录
│  ├─ architecture_flow.md                       # 架构流程图（Mermaid）
│  ├─ order_state_machine.md                     # 订单状态机（Mermaid）
│  └─ api_contracts.md                           # MCP 工具契约
│
├─ tasks/                                        # 任务卡目录
│  ├─ TASK-01 - Data MCP：统一 Row Schema + 出站 DQ Gate（V4）.md
│  ├─ TASK-02 - Data MCP：接入真实 WS／Harvester（实时）.md
│  ├─ ...                                        # 共 18 个任务卡
│  └─ TASK-18 - CI：Mermaid—JSON 契约校验 + Smoke 起停.md
│
├─ logs/                                         # 日志目录（运行时生成）
│  └─ *.jsonl                                    # 事件流日志
│
└─ scripts/                                      # 脚本目录
   └─ dev_run.sh                                 # 开发环境启动脚本
```

### 安装方式（本地开发）
```bash
pip install -e .              # 在仓库根执行，安装 alpha_core 包（src layout）
export PYTHONPATH="$PWD/src:$PYTHONPATH"   # 备选：不安装时的临时方式
```

---

## 2) 成熟组件导入路径（**统一对外 API**）
为减少未来路径变更的影响，推荐从包命名空间导入：
```python
# 特征与微结构（Alpha）
from alpha_core.microstructure.ofi import RealOFICalculator, OFIConfig
from alpha_core.microstructure.cvd import RealCVDCalculator, CVDConfig
from alpha_core.microstructure.fusion import OFI_CVD_Fusion, OFICVDFusionConfig
from alpha_core.microstructure.divergence import DivergenceDetector, DivergenceConfig

# 风控/治理
from alpha_core.risk import StrategyModeManager, StrategyMode, MarketActivity
```
> 提示：在各子包的 `__init__.py` 中二次导出上述类，保持 import 简洁与稳定。

---

## 3) MCP 薄壳（只做 I/O 适配，禁止重写策略逻辑）

### 3.1 `mcp/ofi_feature_server/app.py`
- 输入：统一 Row Schema 批次 `rows[]`（来自 `data_feed_server`）
- 处理：调用 `RealOFI`/`RealCVD`，经 `OFI_CVD_Fusion` 与 `DivergenceDetector` 生成方向、一致性与背离评分
- 输出：`{z_ofi, z_cvd, fusion:{side,consistency,...}, divergence:{...}, fp}`

**要点**  
1) 数据端缺成交流时，CVD 可退化（仅 OFI）；接口不变。  
2) 指纹 `fp = sha256(config_sha + last_ts + symbol)` 用于回放与审计。  
3) 冷却、最小持仓、翻转迟滞、Regime 收敛等稳定化逻辑可放在 `generate_signal` 工具方法。

### 3.2 `mcp/ofi_risk_server/app.py`
- 使用 `StrategyModeManager` 做**第一层闸门**（时段白名单、市场活跃度、数据质量联动）。
- 实现**波动率目标仓位**与**日内损失墙（迟滞）**，输出 `{allow, side, qty, lev, mode, reason, risk_state}`。

### 3.3 其他 MCP
- `data_feed_server`：`/get_live_snapshot` 与 `/get_historical_slice` **同一 Row Schema**。附带 `dq:{ok,reason}`。  
- `broker_gateway_server`：**幂等键 + 订单状态机**（TIMEOUT→REQUERY→ACK/FILLED/CANCELLED）；后端可切换 `paper|ccxt|testnet|live`。  
- `report_server`：读取 `logs/*.jsonl` 产出日报 & 分层指标 & 参数 Scoreboard。

---

## 4) Orchestrator（唯一的大脑）
- **模式**：`HOLD / PAPER / SHADOW / LIVE`（Shadow = 生成订单与记账，但不推交易所）  
- **一致性**：实时与回放 **同接口**；事件落地 `ticks/decisions/orders/fills/pnl` 可重放可审计  

运行示例：
```bash
bash scripts/dev_run.sh     # 启动 5 个 MCP（uvicorn --reload）
python orchestrator/run.py  # 主控循环
```

环境变量：
```bash
export MODE=PAPER
export DATA_URL=http://localhost:9001
export FEAT_URL=http://localhost:9002
export RISK_URL=http://localhost:9003
export BROKER_URL=http://localhost:9004
export REPORT_URL=http://localhost:9005
```

---

## 5) 配置（`config/defaults.yaml` 与 overrides.d）
- **组件参数对齐**：已列出 OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE 所需字段（详见 V3 文档与源码注释）。  
- **覆盖策略**：环境/账户/合约差异放 `overrides.d/*.yaml`；Orchestrator 可提供 `set_config(new, activate_at)` 做定时生效。  
- **时区**：统一使用 `Asia/Tokyo`；事件时钟以**交易所服务器时间 ts_ms** 为准。

---

## 6) 统一 Row Schema（Data MCP 与回放一致性）
```json
[{
  "ts_ms": 1730784000123,
  "bid": 65000.5, "ask": 65000.7,
  "bid_sz": 1.2,  "ask_sz": 0.9,
  "mid": 65000.6, "spread_bps": 3.1,
  "lag_ms": 42,   "exch_seq": 99887766,
  "schema_version": "v1"
}]
```
- **DQ Gate**：时间不回退、spread_bps ≤ 上界、lag ≤ 阈值、静默超时 → `dq.ok=false`，由 Risk 触发短暂 HOLD_DATA。

---

## 7) 任务卡对齐（如何用本文档驱动开发）

### 7.1 任务卡索引（TASK_INDEX.md）

任务卡按依赖关系分为三个里程碑（M1→M2→M3），每个任务卡包含：
- **任务编号**：TASK-XX
- **批次**：M1/M2/M3
- **优先级**：P0/P1/P2
- **所属模块**：data/feature/risk/broker/orchestrator/pkg/report/ops/test/ci
- **背景、目标、前置依赖、输出物**
- **实现步骤**（Cursor 分步操作）
- **验收标准**（Acceptance Criteria）
- **验收命令/脚本**
- **代码改动清单**
- **潜在风险与回滚**
- **预计工时**

### 7.2 任务列表

#### M1 里程碑（最小闭环）
目标：回放=纸面一致；稳健下单；Kill Switch 可用。

- [ ] **TASK-01** — Data MCP：统一 Row Schema + 出站 DQ Gate（V4） · M1 · data
- [ ] **TASK-02** — Data MCP：接入真实 WS／Harvester（实时） · M1 · data
- [ ] **TASK-03** — Data MCP：历史回放（Parquet/CSV） · M1 · data
- [ ] **TASK-04** — alpha_core：打包成熟组件（OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE） · M1 · pkg
- [ ] **TASK-05** — Feature MCP：defaults.yaml → 组件构造器映射（V4） · M1 · feature
- [ ] **TASK-06** — Feature MCP：compute_features 接线（OFI/CVD/FUSION/DIVERGENCE） · M1 · feature
- [ ] **TASK-07** — Feature MCP：generate_signal 稳定化（冷却/持仓最小/翻转滞后/Regime） · M1 · feature
- [ ] **TASK-08** — Risk MCP：StrategyMode 闸门 + 健康检查（V4） · M1 · risk
- [ ] **TASK-09** — Risk MCP：波动率目标仓位 + 日内损失墙（迟滞） · M1 · risk
- [ ] **TASK-10** — Broker MCP：幂等键 + 订单状态机（TIMEOUT→REQUERY） · M1 · broker
- [ ] **TASK-12** — Orchestrator：事件流 JSONL + 模式（HOLD/PAPER/SHADOW/LIVE） · M1 · orchestrator
- [ ] **TASK-16** — 治理：Kill Switch 梯度（DATA/BROKER/RISK/MANUAL）+ 脚本 · M1 · ops

#### M2 里程碑（Testnet 可验证）
目标：账务/PnL 可重放；日报与分层指标；CI 基本校验。

- [ ] **TASK-11** — Broker MCP：后端切换（paper｜ccxt｜testnet） · M2 · broker
- [ ] **TASK-13** — PnL Engine：手续费/资金费率/已未实现盈亏（独立模块） · M2 · pnl
- [ ] **TASK-14** — Report MCP：日报 + 分层指标 + 参数 Scoreboard · M2 · report
- [ ] **TASK-15** — 控制面：set_config(new, activate_at) + 变更事件 · M2 · orchestrator
- [ ] **TASK-17** — 回放一致性：Replay Harness（离线→在线对齐） · M2 · test
- [ ] **TASK-18** — CI：Mermaid/JSON 契约校验 + Smoke 起停 · M2 · ci

### 7.3 使用指南

在 Cursor 中执行任务：
1. **固钉文档**：固钉本文档与 `/docs/api_contracts.md` 到 Cursor 侧边栏
2. **按序执行**：严格按照 `TASK_INDEX.md` 中的顺序执行任务卡
3. **查看任务卡**：打开 `tasks/TASK-XX - 任务名称.md` 查看详细内容
4. **分步实现**：按照任务卡中的"实现步骤"逐项完成
5. **验收测试**：每张卡的"验收命令/脚本"本地跑通后再提交 PR
6. **记录进度**：在 `TASK_INDEX.md` 中标记完成的任务（将 `- [ ]` 改为 `- [x]`）

### 7.4 任务卡文件位置

- **任务索引**：`/TASK_INDEX.md` - 所有任务的索引和里程碑划分
- **任务详情**：`/tasks/TASK-XX - 任务名称.md` - 每个任务的详细说明

> 提示：任务卡采用 Markdown 格式，便于在 Cursor 中直接查看和编辑。每个任务卡都是独立的文档，包含完整的上下文信息。

---

## 8) 常见坑位与规避
- **禁止重写策略逻辑**：MCP 薄壳只做输入/输出映射，所有 OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE 计算留在 `alpha_core`。  
- **幂等缺失**：实盘必须有 `idempotency_key` 与状态机；避免重复下单与半成交“僵尸单”。  
- **时钟混乱**：统一以交易所 **ts_ms** 为准；主机时钟仅用于日志。  
- **数据质量**：点差暴涨、lag 爆表、静默超时 → Risk HOLD；不要“硬做”。

---

## 9) 里程碑与上线闸门（摘自 /docs/milestones.md）
- **达线样例**：胜率 ≥ 60~65%、盈亏比 ≥ 1.8、费用（手续费+滑点）≤ 35%、日交易 ≥ 20、MDD < 6~8%/月。  
- **流程**：回放/纸面 → Testnet（7~14 天） → 小额 LIVE（2~4 周） → 放大 2×。

---

## 10) 变更记录
- **V4**：采用 `alpha_core` 包（src layout），明确导入路径与组件归属；补充环境变量与 Row Schema；任务卡联动。  
- **V3**：首次提供 MCP 薄壳示例与 Orchestrator 主循环、稳定化策略与 KPI 门槛。

> 任何新增文件/接口，请优先对齐这里约定的命名与路径，以保持后续替换/扩展成本最低。
