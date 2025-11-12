# TASK-A5: 等价性测试框架指南

## 概述

等价性测试框架用于验证回测（BacktestExecutor）与执行器（replay/testnet）在相同输入下的强一致性。这是合并门闸（CI Gate），任何涉及执行层/撮合/费用/滑点的 PR 必须通过该测试才能合并。

## 目标

在相同输入（features + quotes + config_hash）的前提下，确保：
- 回放（replay）与回测（backtest）在相同数据窗口下的逐笔等价性
- 撮合/手续费/滑点模型的一致性验证
- schema_v2 信号产出路径、confirm 语义与双 Sink（JSONL/SQLite）的结果一致性

## 等价性定义与容差

### 指标级容差

| 指标 | 容差 | 说明 |
|------|------|------|
| 成交路径 | 逐笔一致 | 方向/数量/价格完全一致 |
| 费用模型 | 完全一致 | maker/taker 费率与 bps 计算完全一致 |
| 滑点模型 | 完全一致 | 同一撮合规则，落地到"统一函数" |
| 仓位路径 | 逐笔一致 | 持仓均价、未实现盈亏轨迹一致 |
| PNL | \|Δ\| < 1e-8 | double 精度门限 |
| 信号计数 | ≤ 0.1% | JSONL vs SQLite 行数差异 |

### 说明

- 若 testnet 真实撮合导致轻微偏差，则以 replay vs backtest 为强一致门闸
- testnet 只做统计一致（比例/分布）参考

## 一致性与兼容性约束

### 路径对齐

- JSONL: `{V13_OUTPUT_DIR}/ready/signal/<symbol>/signals-YYYYMMDD-HH.jsonl`
- SQLite: 默认 `signals_v2.db`（WAL），避免与 v1 混淆

### 命名与时间

- symbol 统一大写
- ts_ms 统一 UTC 毫秒

### confirm 语义

**强约束**：`confirm=true ⇒ gating=1 && decision_code=OK`

测试与执行两侧都强校验。

### v1→v2 兼容

- 优先消费 v2
- 读取 v1 时自动补字段并升级到 signal/v2 视图

### 幂等 Top-1

同 `(symbol, ts_ms)` 仅保留 1 条候选（|score| 最大）。

## 数据准备

### 测试夹具

测试夹具位于 `tests/fixtures/`，包含：
- `equiv_case_*.parquet`: 小样本行情数据
- `equiv_case_*.jsonl`: 对应 v2 信号数据

### 生成测试数据

可以使用回放脚本在线生成：

```bash
python scripts/replay_harness.py \
  --input ./data/features \
  --output ./runtime/equiv_test \
  --config ./config/defaults.yaml \
  --symbols BTCUSDT
```

## 运行测试

### 单元测试

运行等价性测试套件：

```bash
# 运行所有等价性测试
pytest tests/test_equivalence.py -v

# 运行特定测试用例
pytest tests/test_equivalence.py::TestEquivalence::test_case_a_replay_vs_backtest -v
pytest tests/test_equivalence.py::TestEquivalence::test_case_b_dual_sink_consistency -v
pytest tests/test_equivalence.py::TestEquivalence::test_case_c_idempotency -v
```

### 统一入口脚本

使用 `scripts/equiv_run.py` 运行完整等价性测试：

```bash
# 基本用法
python scripts/equiv_run.py \
  --t-min 1731379200000 \
  --t-max 1731382800000 \
  --sink dual \
  --seed 42 \
  --fees-bps 1.93 \
  --slip-mode static \
  --config ./config/defaults.yaml \
  --output-dir ./runtime/equiv_test \
  --symbols BTCUSDT

# 参数说明
# --t-min: 开始时间戳（ms）
# --t-max: 结束时间戳（ms）
# --sink: Sink 类型（jsonl/sqlite/dual）
# --seed: 随机种子（确保可重复）
# --fees-bps: 手续费（基点）
# --slip-mode: 滑点模式（static/piecewise）
# --config: 配置文件路径
# --output-dir: 输出目录
# --symbols: 交易对列表
```

### CI 集成

等价性测试已纳入 CI 门闸：

```bash
# CI 中运行
pytest -k equivalence --junitxml=test-results/equivalence.xml

# 检查结果
python scripts/check_equiv_results.py test-results/equivalence.xml
```

## 测试用例说明

### Case-A: replay == backtest 等价性

**目标**：验证回放执行器与回测执行器在相同输入下的结果一致性。

**验证点**：
- 成交路径：逐笔方向/数量/价格一致
- 费用模型：maker/taker 费率与 bps 计算完全一致
- 滑点模型：同一撮合规则
- 仓位路径：持仓均价、未实现盈亏轨迹一致
- PNL：最终与逐时段 PnL 误差 \|Δ\| < 1e-8

### Case-B: 双 Sink 一致性

**目标**：验证同一 run_id 下 JSONL 与 SQLite 的一致性。

**验证点**：
- 行数差异 ≤ 0.1%
- 字段/Schema 完整
- confirm=true 强约束断言（confirm ⇒ gating=1 && decision_code=OK）

### Case-C: 幂等性

**目标**：验证同 (symbol, ts_ms) 仅保留 1 条候选。

**验证点**：
- 构造 (symbol, ts_ms) 冲突样本
- 验证仅保留 |score| 最大的一条

## 常见偏差解释

### 1. 双 Sink 行数差异 > 0.1%

**可能原因**：
- SQLite 事务未提交
- JSONL 文件未刷新
- 进程异常退出

**解决方法**：
- 确保 `SignalWriterV2.close()` 被调用
- 检查 SQLite WAL 模式配置
- 验证进程优雅退出

### 2. PNL 差异 > 1e-8

**可能原因**：
- 浮点数精度累积误差
- 费用计算顺序不同
- 滑点模型实现不一致

**解决方法**：
- 统一费用计算函数
- 统一滑点模型实现
- 使用 Decimal 类型进行精确计算（如需要）

### 3. 成交路径不一致

**可能原因**：
- 撮合逻辑不同
- 价格对齐规则不同
- 数量精度处理不同

**解决方法**：
- 统一撮合函数
- 统一价格/数量对齐规则
- 验证交易所精度约束

### 4. 契约违反（confirm=true 但 gating!=1）

**可能原因**：
- CoreAlgorithm 输出错误
- 信号转换逻辑错误

**解决方法**：
- 检查 CoreAlgorithm 的决策逻辑
- 验证信号转换代码
- 添加契约断言

## 调试技巧

### 1. 启用详细日志

```bash
export LOG_LEVEL=DEBUG
pytest tests/test_equivalence.py -v -s
```

### 2. 保存中间结果

```bash
python scripts/equiv_run.py \
  --output-dir ./runtime/equiv_test_debug \
  --config ./config/defaults.yaml
```

### 3. 对比结果文件

```bash
# 生成结果
python scripts/equiv_run.py --output-dir ./runtime/equiv_test_1
python scripts/equiv_run.py --output-dir ./runtime/equiv_test_2

# 对比
diff -u runtime/equiv_test_1/equiv_result_*.json runtime/equiv_test_2/equiv_result_*.json
```

## 回滚与风控

### 门闸失败处理

若门闸新增导致历史 PR 大量失败：
1. 临时降低为"警告模式"
2. 48 小时内修正执行侧差异
3. 开 Issue 记录差异解释 + 恢复计划

### 放宽容差

任何放宽均需：
1. 开 Issue 记录
2. 给出"差异解释 + 恢复计划"
3. 明确时间表

## 防回归硬化（Regression Hardening）

### 跨平台矩阵测试
等价性测试在以下环境矩阵中执行，确保平台/版本兼容性：
- **OS**: Ubuntu-latest, Windows-latest
- **Python**: 3.11, 3.12

### 依赖锁定
- 使用 `constraints.txt` 冻结传递依赖版本
- 安装命令: `pip install -e ".[dev]" -c constraints.txt`
- 防止上游依赖版本波动导致的回归

### 跳过机制加锁
- 需要 `skip-equivalence` 标签 **且** CODEOWNERS 审批
- 允许用户列表: `terrydeng178, repo-owner`
- 确保紧急修复时的可控性

### CI 调试工件
- 自动上传测试报告: `reports/junit.xml`
- 自动上传对比明细: `runtime/equiv_test/equiv_diff_*.json`
- 失败时可一键下载复盘差异

### CI 配置优化
- CI 中使用 `-v` 详细输出，便于调试
- 矩阵测试失败时仍保留其他平台的 artifact
- 并发控制: 同一分支同时只能运行一个等价性测试

## Definition of Done (DoD)

- [x] 回放 vs 回测：成交、费用、仓位、PNL 在样本集 \|Δ\| < 1e-8
- [x] 契约强校验：confirm=true ⇒ gating=1 && decision_code=OK 断言通过
- [x] 双 Sink 一致性：同一 run_id 下 JSONL vs SQLite 行数差 ≤ 0.1%，字段/Schema 完整
- [x] 幂等：同 (symbol, ts_ms) 仅保留 1 条候选（含单测）
- [x] CI 门闸：pytest -k equivalence 纳入必过检查，合并前自动执行
- [x] 文档：本文档完整说明数据准备、命令示例、阈值、常见偏差解释
- [x] 防回归硬化：跨平台矩阵、依赖锁定、跳过加锁、调试工件

## 参考

- TASK-A4: CoreAlgorithm 输出契约与单点判定
- TASK-A2: 执行层抽象 IExecutor
- `tests/test_equivalence.py`: 核心测试用例
- `scripts/equiv_run.py`: 统一入口脚本


