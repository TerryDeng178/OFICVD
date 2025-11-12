# TASK-A2 执行层抽象优化方案实施计划

**生成时间**：2025-11-12  
**基于**：A1已收尾 + A2执行层抽象优化方案

---

## 一、现状快速结论（OK点）

### ✅ A1 风控合并与服务精简
- 已从8个服务收敛到5条主链（Harvest→Signal→Strategy(含Risk)→Broker→Report）
- E2E/冒烟 12/12 全过
- p95 ≤ 5ms
- Shadow 吞吐降幅 ≤10%

### ✅ Risk 模块落地完整
- guards/position/stops/precheck/shadow/metrics/metrics_endpoint 列表清晰并通过测试
- Prometheus 指标与 /metrics 端点齐备

### ✅ 信号/核心算法侧观测
- 已具备 OFI 心跳与数据质量诊断
- 融合模块对 invalid/warmup 的防御式返回
- 为后续联动执行器提供了可用的上游状态信号

---

## 二、发现的改进空间（关键）

### 1. 契约文档一致性风险
- **问题**：A1最终报告写明"JSON Schema 强校验（硬闸）已落地"，但A1任务卡尾部"后续建议"仍写"实现数据契约的JSON Schema校验器"
- **影响**：避免误导下游引用者
- **优先级**：P0

### 2. 执行层（A2）与上游信号的"状态贯通"不足
- **问题**：上游已产出 warmup/guard_reason/consistency/weak_signal_throttle 等状态，但这些字段如何进入执行决策与速率控制，还需在IExecutor侧定义清晰流转与指标口径
- **影响**：执行层无法充分利用上游状态信息
- **优先级**：P0

### 3. 执行日志与可追溯性需要"统一Outbox模式"
- **问题**：信号层已有JsonlSink的spool→ready原子落盘实现与Windows友好重试；执行侧应直接复用同一套产出规范
- **影响**：减少二义性与平台差异坑
- **优先级**：P1

### 4. 时钟/时间戳与tick规则的跨层一致性
- **问题**：CVD的tick rule已对"价格不变时的方向传播"加入长度/时限上限；此类约束与event_time_ms应在执行仿真/回测时间源中保持一致
- **影响**：避免回测与实盘执行的方向判定偏差
- **优先级**：P1

### 5. 策略模式/时段触发与时区
- **问题**：StrategyMode已支持schedule/market双触发与跨午夜窗口解析；执行层应读取同源模式与场景参数，避免重复解析与时区漂移
- **影响**：确保模式切换一致性
- **优先级**：P1

### 6. 数据接入端的去重/轮转告警
- **问题**：Harvester已有LRU去重、丢弃计数与每小时manifest汇总；执行层的"下单阈值/频率墙"需要能感知这些健康度指标
- **影响**：防止异常输入放大到交易层面
- **优先级**：P2

---

## 三、A2执行层抽象（IExecutor）优化方案

### 1) 契约与数据模型 ⏳

**动作**：
- 统一IExecutor契约：`submit(order: OrderCtx) -> ExecResult`，`cancel(client_order_id) -> CancelResult`，`amend(...) -> AmendResult`，`flush() / close()`
- OrderCtx：包含 `ts_ms`, `event_ts_ms`, `regime`, `scenario`, `tick_size`, `step_size`, `guard_reason`, `warmup`, `consistency`, `costs_bps` 等
- ExecResult：`accepted/rejected`, `reject_reason`, `exchange_order_id`, `latency_ms`, `slippage_bps`, `rounding_applied` 等
- SSoT：Order/Decision的JSON Schema放入 `/docs/api_contracts.md` 下 `executor_contract/v1`，并与A1的`risk_contract`同步索引

**DoD**：
- 所有执行实现（Backtest/Live/Testnet）对齐同一Pydantic/Schema校验通过
- 契约文档渲染与链接检查通过（与A1一致的SSoT要求）

**状态**：⏳ 待实施

---

### 2) 状态贯通与速率控制 ⏳

**动作**：
- 将上游的 `warmup` / `guard_reason` / `consistency` / `weak_signal_throttle` 映射到执行前置决策：
  - `warmup` 或 `guard_active` → 直接拒单并计数 `executor_pre_deny_total{reason=...}`
  - `consistency` 低于阈值 → `executor_throttle_total{reason="low_consistency"}` + 降采样执行
- 引入自适应节流器：按 `gate_reason_stats` 与市场活跃度（StrategyMode）联动限速

**DoD**：
- Prometheus增加：`executor_submit_total{result,reason}`、`executor_latency_ms`直方图、`executor_throttle_total{reason}`；与A1风控指标同屏展示
- E2E新增"信号→执行速率联动"用例，确保p95无退化

**状态**：⏳ 待实施

---

### 3) 执行日志与Outbox（统一落盘） ⏳

**动作**：
- 复用JsonlSink：执行事件采用 `spool/.part` → 原子改名 `ready/.jsonl` 的发布路径；Windows上使用 `_atomic_move_with_retry` 以规避句柄占用
- 事件Schema：`exec_events/{symbol}/exec_YYYYMMDD_HHMM.jsonl`，字段含：`signal_row_id`, `client_order_id`, `side`, `qty`, `px_intent`, `px_sent`, `px_fill`, `rounding_diff`, `slippage_bps`, `exchange_order_id`, `status`, `reason`, `sent_ts_ms`, `ack_ts_ms`

**DoD**：
- 压测（10k events）零丢失；ready目录全可读；错误重试日志可检索

**状态**：⏳ 待实施

---

### 4) 幂等性与重试 ⏳

**动作**：
- 使用 `client_order_id = hash(signal_row_id|ts_ms|side|qty|px)` 作为幂等键
- 指数退避 + 抖动（上限3次）+ 只对网络/5xx重试；本地参数/风控拒单一律不重试
- `cancel/amend` 要求exchange回执与本地状态同步

**DoD**：
- "网络波动模拟"集成测试：重复提交无重复下单；退避重试行为符合策略限速

**状态**：⏳ 待实施

---

### 5) 价格对齐与滑点建模 ⏳

**动作**：
- 统一 `tick_size/step_size` 对齐策略：下单前强制四舍五入到交易所精度；将rounding差额写入日志并纳入 `slippage_bps` 计算
- BacktestExecutor中引入可插拔滑点模型（maker/taker/深度冲击），默认用A1成本口径

**DoD**：
- 对同一批信号：回测与实盘的"期望成交价差"≤ 1 tick的95分位

**状态**：⏳ 待实施

---

### 6) 时间源与可复现性 ⏳

**动作**：
- IExecutor注入 `TimeProvider`（wall-clock vs. sim-time）与 `Rng(seed)`
- BacktestExecutor：强制使用sim-time（来自信号/回放），确保determinism
- Testnet/LiveExecutor：以wall-clock + 交易所ack时间；对比 `ack_ts_ms - sent_ts_ms` 形成延迟分布

**DoD**：
- 回测两次结果bitwise一致；延迟直方图可在Dashboard观察

**状态**：⏳ 待实施

---

### 7) "影子执行(Shadow Execution)"串联 ⏳

**动作**：
- 复用Risk的Shadow验证思路：允许并行向Testnet发送"影子单"，只落账不成交，比较"意图价/回执/拒单率"
- 新增 `executor_shadow_parity_ratio` 指标，与A1的 `risk_shadow_parity_ratio` 同屏，故障时自动告警

**DoD**：
- 影子与主执行"价格/状态"≥ 99%一致；异常触发告警

**状态**：⏳ 待实施

---

### 8) 策略模式与场景参数同源注入 ⏳

**动作**：
- IExecutor初始化时读取 `StrategyModeManager` 的当前模式与场景参数（Z/TP/SL/cost_bps…），避免重复解析
- 严格使用统一时区配置，跨午夜窗口遵循上游 `wrap_midnight` 语义

**DoD**：
- 不同模式切换时的执行阈值/限速自动更新，切换事件有审计日志

**状态**：⏳ 待实施

---

### 9) 可观测性与日志采样 ⏳

**动作**：
- 复用A1的"通过1% / 失败100%"采样策略到执行层；关键字段：`guard_reason`, `warmup`, `scenario`, `rounding_applied`, `reject_reason`

**DoD**：
- 端到端链路的失败路径具备100%可追踪性；采样不影响p95

**状态**：⏳ 待实施

---

### 10) E2E扩展与CI门禁 ⏳

**动作**：
- 在现有5服务主链用例基础上（已验证到Broker），新增"Strategy→Executor→ExecLogSink"的完整链路用例，覆盖：
  - 正常下单、风控拒单、价格对齐、网络抖动重试、影子执行对比、优雅关闭（flush/close join背景线程）
- CI门禁新增：执行层p95、幂等率、影子一致率阈值

**DoD**：
- CI绿灯 + 指标阈值全通过；合入前自动跑回归（±5%容忍，延续A1标准）

**状态**：⏳ 待实施

---

## 四、文档与SSoT同步清单

### 1. 契约文档同步 ⏳
- 合并 `executor_contract/v1` 到 `/docs/api_contracts.md` 索引，与 `risk_contract/v1` 同步
- 修正"是否已实现JSON Schema校验"的口径不一致

### 2. 任务索引更新 ⏳
- 在 `TASK_INDEX.md` 的M3（回放/回测/复盘）下增加"A2执行层抽象"子任务
- 标注与TASK-08/09的依赖关系

---

## 五、实施优先级

### P0（立即实施）
1. 契约与数据模型
2. 状态贯通与速率控制
3. 文档同步（修正口径不一致）

### P1（短期实施）
4. 执行日志与Outbox
5. 幂等性与重试
6. 价格对齐与滑点建模
7. 时间源与可复现性
8. 策略模式与场景参数同源注入

### P2（中期实施）
9. 影子执行串联
10. 可观测性与日志采样
11. E2E扩展与CI门禁

---

## 六、实施计划

### Phase 1: 契约与数据模型（P0）
- 创建 `OrderCtx` 和 `ExecResult` 数据类
- 定义 `executor_contract/v1` JSON Schema
- 更新 `docs/api_contracts.md`
- 修正A1任务卡的口径不一致

### Phase 2: 状态贯通（P0）
- 扩展 `Order` 数据结构，包含上游状态字段
- 实现执行前置决策逻辑
- 添加Prometheus指标
- 实现自适应节流器

### Phase 3: Outbox模式（P1）
- 复用JsonlSink的原子落盘实现
- 实现Windows友好的重试机制
- 统一事件Schema

### Phase 4: 其他优化（P1-P2）
- 按优先级逐步实施剩余优化点

---

## 七、验收标准（DoD）

### 整体DoD
- ✅ 所有P0优化点完成并通过测试
- ✅ 契约文档同步完成，口径一致
- ✅ E2E测试扩展完成，CI门禁通过
- ✅ 指标监控完善，Dashboard可观察

### 分项DoD
见各优化点的DoD部分

---

## 八、风险与缓解

### 风险1：契约变更影响现有实现
- **缓解**：采用向后兼容的方式扩展，逐步迁移

### 风险2：状态贯通增加复杂度
- **缓解**：采用配置开关，支持渐进式启用

### 风险3：Outbox模式在Windows上的性能
- **缓解**：复用已验证的JsonlSink实现，充分测试

---

## 九、相关文件

- **实施计划**：`reports/TASK-A2-优化方案实施计划.md`（本文档）
- **任务卡**：`tasks/整合任务/✅TASK-A2-执行层抽象-IExecutor-Backtest-Live.md`
- **API契约文档**：`docs/api_contracts.md`
- **JsonlSink实现**：`src/alpha_core/signals/core_algo.py`（JsonlSink类）
- **StrategyModeManager**：`src/alpha_core/risk/strategy_mode.py`

