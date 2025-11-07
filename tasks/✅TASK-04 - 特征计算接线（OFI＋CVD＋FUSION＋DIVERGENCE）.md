# ✅ TASK-04 · 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）

> 里程碑：M1→M2｜负责人：@you｜状态：已完成并签收（2025-11-06）  
> 性能验收：14,524 rows/s（14.5倍），CPU 38.54% ✅  
> 签收清单：详见 `TASK-04-评估报告-签收清单.md`

---

## 0) 概述

已有成熟组件（OFI/CVD/FUSION/DIVERGENCE）。本任务以“统一输入 → 标准输出 → 最小可跑”为目标，实现**特征层**与**信号层**之间的稳定数据契约，并提供可回放/可落地的最小样例。

---

## 1) 前置依赖与目录

* 组件位置：

  * `src/alpha_core/microstructure/ofi/real_ofi_calculator.py`
  * `src/alpha_core/microstructure/cvd/real_cvd_calculator.py`
  * `src/alpha_core/microstructure/fusion/ofi_cvd_fusion.py`
  * `src/alpha_core/microstructure/divergence/ofi_cvd_divergence.py`
* 关联模块：

  * `src/alpha_core/ingestion/harvester.py`（输入统一 Row）
  * `src/alpha_core/signals/core_algo.py`（下游消费）
* 配置：`/config/defaults.yaml`（features.ofi/cvd/fusion/divergence 等）
* 文档：`/docs/api_contracts.md`（3.1/3.2）

---

## 2) 目标与验收

### 2.1 目标

* 用**统一 Row** 驱动 OFI/CVD，产出 `z_ofi`/`z_cvd`；
* 调用 FUSION 得到 `fusion_score`、`signal`、`consistency` 等；
* 调用 DIVERGENCE 得到 `div_type` 等事件字段；
* 输出 **FeatureStream**（供 CORE_ALGO 消费）并可落地 JSONL/SQLite。

### 2.2 验收

* 功能：样本输入 → 输出字段**完备稳定**（字段/命名不抖动）；
* 性能：本地 1k rows/s 下 CPU < 1 core（**实际测试：14,524 rows/s，CPU 38.54%** ✅）；
* 可靠：暖启动、缺失数据、异常流量时**降级不炸**；
* 可回放：支持 JSONL 文件回放，结果可复现（稳定 JSON 序列化）；
* 观测：DEBUG 打点含关键链路（ofi/cvd/fusion/div 与去重窗口）；
* 契约：输入订单簿排序约定、SQLite schema 与 JSONL 对齐。

---

## 3) 数据契约

### 3.1 输入（HARVEST → 特征层）

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
  "bids": [[70321.4, 10.5], [70321.3, 8.2], [70321.2, 6.0], [70321.1, 5.0], [70321.0, 4.0]],
  "asks": [[70321.6, 11.2], [70321.7, 9.5], [70321.8, 7.0], [70321.9, 6.0], [70322.0, 5.0]],
  "meta": { "latency_ms": 12, "recv_ts_ms": 1730790000125 }
}
```

**排序约定**（重要）:
- **bids**: 必须按价格从高到低排序（`bids[0][0]` 为最高买价）
- **asks**: 必须按价格从低到高排序（`asks[0][0]` 为最低卖价）
- 如输入未保证顺序，实现侧会先排序再取前 5 档（安全排序）

> 说明：OFI 需要订单簿快照（K 档），CVD 需要成交（price/qty/is_buy）。若输入为聚合表，需在管道内维护**符号态**（缓存 L1/LK）以生成调用参数。

### 3.2 输出（特征层 → CORE_ALGO）

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

> 统一字段命名，禁止随意更名；扩展字段以**小写蛇形**命名。JSONL 和 SQLite 两种 sink 字段完全一致。

---

## 4) 接口与函数签名（Cursor 直接实现）

### 4.1 FeaturePipe（新增）

* 文件：`src/alpha_core/microstructure/feature_pipe.py`
* 职责：

  1. 维护 per-symbol 态（orderbook L1/LK、最近 trades）；
  2. 调用 OFI/CVD/FUSION/DIVERGENCE；
  3. 产出 FeatureRow 并写入 sink（JSONL/SQLite）。
* 类图：

```text
FeaturePipe
  ├─ __init__(config, symbols, sink)
  ├─ on_row(row: Dict) -> Optional[Dict]      # 单条更新 → FeatureRow 或 None
  ├─ flush() -> None                          # 停机/轮转钩子
  └─ _mk_feature(symbol, ts_ms, price, spread_bps, lag_sec, ...)
```

### 4.2 组件调用（统一签名适配层）

* OFI：

```python
update_ofi(bids: List[Tuple[float,float]],
           asks: List[Tuple[float,float]],
           event_time_ms: Optional[int]) -> Dict  # 取 .get("z_ofi")
```

* CVD：

```python
update_cvd(price: Optional[float], qty: float,
           is_buy: Optional[bool], event_time_ms: Optional[int]) -> Dict  # 取 .get("z_cvd")
```

* FUSION：

```python
update_fusion(z_ofi: float, z_cvd: float, ts_sec: float,
              price: Optional[float], lag_sec: float) -> Dict  # fusion_score/signal/consistency
```

* DIVERGENCE：

```python
update_divergence(ts_sec: float, price: float,
                  z_ofi: float, z_cvd: float,
                  fusion_score: float, consistency: float,
                  lag_sec: float) -> Dict  # {"type": "bull|bear|null", ...}
```

> 适配层：对 None/NaN/inf 做兜底；warmup 期将 `z_*` 视为 0，不触发强信号；保留 `reason_codes` 便于诊断。

---

## 5) 业务流（最小可跑）

1. 从 `./data/...` 读取（或直连 harvester 内存流）；
2. 解析为统一 Row；
3. 维护 per-symbol state：

   * L1/LK orderbook（for OFI）
   * 最近一笔成交（for CVD）
   * lag 估算（事件到达与撮合时间差、或 bid/ask/aggTrade 对齐差）
4. 顺序调用：OFI → CVD → FUSION → DIVERGENCE；
5. 生成 FeatureRow → 写入 sink（JSONL 默认，SQLite 可选）；
6. 暖启动阶段打 `warmup=true` 标识，信号阈值自动收敛。

---

## 6) 代码清单（新增/改动）

* `src/alpha_core/microstructure/feature_pipe.py`（新增，672 行）
* `tests/test_feature_pipe.py`（新增，310 行，7 个测试用例）
* `tests/conftest.py`（新增，pytest 配置）
* `scripts/feature_demo.sh`（新增，Bash 版本）
* `scripts/feature_demo.ps1`（新增，PowerShell 版本）
* `scripts/performance_test.sh`（新增，性能测试 Bash 版本）
* `scripts/performance_test.ps1`（新增，性能测试 PowerShell 版本）
* `scripts/m2_smoke_test.sh`（新增，M2 冒烟测试 Bash 版本）
* `scripts/m2_smoke_test.ps1`（新增，M2 冒烟测试 PowerShell 版本）
* `docs/api_contracts.md`（补充 3.1/3.2 字段与样例，排序约定）
* `config/defaults.yaml`（添加 features 和 sink 配置段）
* `TASK-04-评估报告-签收清单.md`（新增，完整签收证据链）

---

## 7) 配置（defaults.yaml 片段）

```yaml
features:
  ofi:
    window_ms: 5000
    zscore_window: 30000
    levels: 5
    weights: [0.4,0.25,0.2,0.1,0.05]
  cvd:
    window_ms: 60000
    z_mode: "delta"   # delta|level
  fusion:
    method: "zsum"    # zsum|weighted
  divergence:
    lookback_bars: 60
sink:
  kind: jsonl         # jsonl|sqlite
  output_dir: ./runtime
```

---

## 8) 命令行与运行

```bash
# 方式A：直接跑 FeaturePipe（文件输入 → JSONL 输出）
python -m alpha_core.microstructure.feature_pipe \
  --input ./data/**/*.parquet \
  --sink jsonl --out ./runtime/features.jsonl \
  --symbols BTCUSDT

# 方式B：与 CORE_ALGO 一起跑（MCP 信号服务）
V13_SINK=jsonl V13_OUTPUT_DIR=./runtime \
python -m mcp.signal_server.app --config ./config/defaults.yaml
```

---

## 9) 测试用例（最小集）

* **Case-01**：正常流（bookTicker + aggTrade + depth@100ms）→ `z_*` 非空，`fusion_score` 合理。
* **Case-02**：warmup（窗口样本不足）→ `z_*` 置 0，`signal=neutral`，含 `warmup=true`。
* **Case-3**：缺失成交/缺失盘口 → 自动降级，`reason_codes` 带 `invalid_input`；
* **Case-4**：lag 异常（>max_lag）→ `consistency` 低、`signal` 节流；
* **Case-5**：重复流/重放 → 去重窗口生效，不抖动。

> 断言：输出字段齐全；数值范围/单调关系正确；空值策略一致；性能达标。

---

## 10) 注意事项（一致性/兼容性）

* **字段命名**：全部小写蛇形；以后仅追加，不移除/重命名；
* **时间统一**：输入毫秒 `ts_ms`，向 FUSION/DIV 传秒 `ts_sec`；
* **降级策略**：任一 `z_*` 为 None → 置 0，`signal=neutral`；
* **性能**：避免 O(K*N) 排序；只在必要时排序；
* **跨平台**：路径与 JSON 序列化保持稳定；
* **日志**：异常分支提升到 INFO/WARN；正常分支 DEBUG；
* **幂等/去重**：配置化 `dedupe_ms`；
* **可观测性**：`reason_codes`、`stats` 进入输出或 DEBUG 日志。

---

## 11) Definition of Done（DoD）

* [x] 新增文件与改动按上表落地；
* [x] `feature_demo.sh` 本地可跑，生成 `runtime/features.jsonl`；
* [x] 单测覆盖：OFI/CVD/FUSION/DIV 适配层 + 5 条业务流用例（7 个测试用例全部通过）；
* [x] README 与 `/docs/api_contracts.md` 更新；
* [x] Cursor 打开 `TASK_INDEX.md` 与本任务卡一致（已同步更新）；
* [x] 通过 M2 冒烟（与 CORE_ALGO 联调）。

## 完成状态

**✅ 核心功能已完成** - 2025-11-06

### 已完成的工作

1. **FeaturePipe 类实现** (`src/alpha_core/microstructure/feature_pipe.py`)
   - ✅ 维护 per-symbol 状态（orderbook L1/LK、最近 trades）
   - ✅ 调用 OFI/CVD/FUSION/DIVERGENCE 组件
   - ✅ 产出 FeatureRow 并写入 sink（JSONL/SQLite）
   - ✅ 支持去重窗口（dedupe_ms）
   - ✅ 支持 lag 检查和降级处理
   - ✅ 支持 warmup 标识

2. **配置文件更新** (`config/defaults.yaml`)
   - ✅ 添加 `features` 配置段（ofi/cvd/fusion/divergence）
   - ✅ 添加 `sink` 配置段

3. **演示脚本** 
   - ✅ `scripts/feature_demo.sh` (Bash)
   - ✅ `scripts/feature_demo.ps1` (PowerShell)

4. **文档更新**
   - ✅ `docs/api_contracts.md` - 添加 3.1/3.2 数据契约说明
   - ✅ 添加 FeaturePipe 接口说明和使用示例

5. **模块导出**
   - ✅ `src/alpha_core/microstructure/__init__.py` - 导出 FeaturePipe

### 已完成的工作（2025-11-06 更新）

1. **文件读取功能**（P1）✅
   - ✅ 实现 Parquet 文件读取（支持目录递归和 glob 模式）
   - ✅ 实现 JSONL 文件读取
   - ✅ 支持单文件、目录和 glob 模式输入
   - ✅ 自动处理 numpy 类型转换
   - ✅ 错误处理和日志记录

2. **单测覆盖**（P1）✅
   - ✅ 创建 `tests/test_feature_pipe.py`
   - ✅ 测试用例：
     - Case-01: 正常流（bookTicker + aggTrade + depth）
     - Case-02: warmup 测试（窗口样本不足）
     - Case-03: 缺失成交/缺失盘口（自动降级）
     - Case-04: lag 异常（>max_lag）
     - Case-05: 重复流/重放（去重窗口生效）
   - ✅ JSONL sink 输出验证

3. **M2 冒烟测试**（P0）✅
   - ✅ 创建 `scripts/m2_smoke_test.sh` (Bash)
   - ✅ 创建 `scripts/m2_smoke_test.ps1` (PowerShell)
   - ✅ 测试流程：
     1. 运行 FeaturePipe 生成特征
     2. 验证特征文件格式
     3. 运行 CORE_ALGO 信号生成（如果可用）
   - ✅ 错误处理和状态检查

### 已完成的工作（文档同步）

1. **文档同步**（P2）✅
   - ✅ 更新 TASK-04 任务卡状态为"已完成"
   - ✅ 更新 TASK_INDEX.md，标记 TASK-04 为已完成
   - ✅ 更新 README.md，添加 FeaturePipe 说明和使用示例
   - ✅ 更新 README.md 目录结构，添加 `feature_pipe.py`
   - ✅ 更新 README.md M2 章节，添加特征计算步骤说明

2. **测试配置**（P1）✅
   - ✅ 创建 `tests/conftest.py` - pytest 配置和路径设置
   - ✅ 修复测试导入问题（添加路径处理）
   - ✅ 添加 pytest 配置到 `pyproject.toml`（消除 asyncio 警告）
   - ✅ 所有 7 个测试用例全部通过

### 技术实现细节

- **状态管理**: 使用 `SymbolState` 类维护每个交易对的状态
- **去重机制**: 基于时间窗口（dedupe_ms）和 row_id 的去重
- **降级策略**: warmup 期 z_* 置为 0，lag 超限跳过
- **数据流**: 统一 Row → OFI → CVD → FUSION → DIVERGENCE → FeatureRow
- **Sink 支持**: JSONL（默认）和 SQLite（可选）

**完成日期**: 2025-11-06  
**最后更新**: 2025-11-06（文件读取、单测、M2 冒烟测试、文档同步、审查修复）

### 审查修复（2025-11-06）

根据审查报告，已完成以下修复：

#### P0 修复（阻断型）

1. **✅ 依赖补齐** (`pyproject.toml`)
   - 添加 `pandas>=2.1.0`（Parquet 文件读取）
   - 添加 `pyarrow>=14.0.0`（Parquet 引擎）
   - 添加 `PyYAML>=6.0.0`（配置文件读取）
   - 添加开发依赖：`ruff>=0.5.0`, `isort>=5.12.0`

2. **✅ Python 版本统一** (`pyproject.toml`)
   - 统一为 `>=3.10`（与脚本提示一致）
   - 更新 classifiers 和工具配置（black, mypy）

3. **✅ 打包配置修复** (`pyproject.toml`)
   - 使用 `[tool.setuptools.packages.find]` 自动发现子包
   - 确保 `alpha_core.microstructure.*` 子包被正确打包

#### P1 修复（重要）

1. **✅ FeaturePipe 逻辑修复** (`feature_pipe.py`)
   - 修复 `activity_window` 初始化判断：从 `symbol not in state.activity_window` 改为 `isinstance(state.activity_window, deque)`

2. **✅ 稳定 JSON 序列化** (`feature_pipe.py`)
   - 启用 `sort_keys=True` 确保字段排序稳定
   - 使用 `separators=(",", ":")` 紧凑格式
   - 确保回放可复现（逐行对比）

3. **✅ 输入订单簿排序约定** (`feature_pipe.py` + `api_contracts.md`)
   - 实现侧 `_extract_bids()` 和 `_extract_asks()` 添加安全排序
   - bids 按价格从高到低排序，asks 按价格从低到高排序
   - 契约文档明确排序要求

4. **✅ SQLite Schema 对齐** (`feature_pipe.py`)
   - 添加 `signal TEXT` 字段到 CREATE TABLE
   - 使用 PRAGMA 检查列存在性，智能 ALTER TABLE（向后兼容）
   - INSERT 语句使用显式列名，包含 signal 字段

#### P2 优化（建议）

1. **✅ 文档补齐** (`api_contracts.md`)
   - 移除"详细契约待补充"占位符
   - 添加 FeaturePipe 输入输出契约说明
   - 添加字段验证示例代码
   - 明确 bids/asks 排序约定

2. **✅ 配置对齐验证** (`defaults.yaml`)
   - 确认 `fusion.w_ofi: 0.6` 和 `fusion.w_cvd: 0.4` 已正确配置
   - 所有 features 配置段已完整
   - `fusion.method` 标注为预留字段（当前实现未使用）

3. **✅ 性能测试与验收** (`scripts/performance_test.ps1` + `.sh`)
   - 实现双指标：rows_per_sec 和 features_per_sec
   - CPU 指标采用核等效平均值（验收口径）
   - 性能测试结果：14,524 rows/s（14.5 倍于要求），CPU 38.54%

### 验证清单

- ✅ `pip install -e .[dev]` 安装依赖（按修复后的 pyproject.toml）
- ✅ `python -m pytest tests/test_feature_pipe.py -v` - 7 个测试用例全部通过
- ✅ FeaturePipe 导入测试通过
- ✅ JSON 序列化使用稳定排序（sort_keys=True）
- ✅ SQLite schema 与 JSONL/契约完全对齐（包含 signal 字段）
- ✅ 输入订单簿排序约定已实现并文档化
- ✅ 性能测试通过（14,524 rows/s，CPU 38.54%）

### 签收状态（2025-11-06）

**✅ 已签收（Pass）**

- 所有核心功能已完成并通过测试
- 所有审查修复项已补齐
- SQLite schema 与契约对齐
- 性能验收通过（超额完成）
- 可复现实证材料完整（测试日志、性能结果）

**签收清单**: 详见 `TASK-04-评估报告-签收清单.md`

---

## 12) 参考输出样例（features.jsonl）

```json
{"ts_ms":1730790000456,"symbol":"BTCUSDT","z_ofi":1.2,"z_cvd":0.8,"price":70325.1,"lag_sec":0.04,"spread_bps":1.2,"fusion_score":0.66,"consistency":0.41,"dispersion":0.4,"sign_agree":1,"div_type":null,"activity":{"tps":2.3},"warmup":false,"signal":"neutral"}
{"ts_ms":1730790000556,"symbol":"BTCUSDT","z_ofi":1.4,"z_cvd":0.9,"price":70326.0,"lag_sec":0.03,"spread_bps":1.1,"fusion_score":0.72,"consistency":0.47,"dispersion":0.5,"sign_agree":1,"div_type":null,"activity":{"tps":2.5},"warmup":false,"signal":"neutral"}
```

**格式说明**:
- JSONL 格式（每行一个 JSON 对象）
- UTF-8 编码，稳定序列化（`sort_keys=True`，紧凑格式）
- 字段顺序稳定，支持回放可复现
- SQLite sink 字段与 JSONL 完全一致（包含 `signal` 字段）

---

> 备注：本任务卡为 Cursor 友好版，完成后请将关键参数固化到 `defaults.yaml` 并在 `api_contracts.md` 追加样例。
