# TASK-07B · 双 Sink 等价性收敛（目标 < 0.2%）

> 里程碑：M3 · 依赖：TASK-07/07A · 最近更新：2025-11-08 (Asia/Tokyo)  
> **状态**: ⏳ **待执行**

---

## 0) 背景与目标

本任务负责将 JSONL↔SQLite 在同窗口内的总量/确认量/强信号占比差异收敛到 <0.2%，确保双 Sink 模式的等价性和数据一致性。

**当前状态**：
- ✅ 双 Sink 功能已实现（MultiSink 类）
- ✅ 基础等价性测试已通过（差异 < 1.5%）
- ⏳ 需要进一步优化以达到 < 0.2% 的目标

**预期产物**：
- 双 Sink 等价性测试脚本（支持分钟交集窗口聚合）
- `parity_diff.json` 证据包（含 Top-N 差异分钟）
- 双 Sink 等价性验证报告
- 优化后的关闭流程（确保无未提交批次）

---

## 1) 范围

### In Scope

* 双 Sink 等价性测试脚本（分钟交集窗口聚合）
* 关闭流程优化（MultiSink.shutdown() → jsonl.drain()、sqlite.flush_and_commit()）
* 差异分析（总量、确认量、强信号占比）
* 窗口对齐检查（无"窗口未对齐"提示）
* 证据包生成（parity_diff.json + 两份日报）

### Out of Scope

* 单 Sink 模式优化（不在本任务范围）
* 性能优化（单独任务）

---

## 2) 前置与依赖

* **TASK-07**：Orchestrator 编排与端到端冒烟已完成
* **P0-1**：双 Sink 覆盖功能已实现
* 双 Sink 基础等价性测试已通过（差异 < 1.5%）

---

## 3) 运行契约（CLI & 环境）

### 3.1 双 Sink 模式运行

```powershell
# Windows PowerShell - 双 Sink 模式
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,broker,report `
  --sink dual `
  --minutes 30

# Linux/macOS
python -m orchestrator.run \
  --config ./config/defaults.yaml \
  --enable harvest,signal,broker,report \
  --sink dual \
  --minutes 30
```

### 3.2 等价性测试脚本

```powershell
# Windows PowerShell
python scripts/test_dual_sink_parity.py `
  --jsonl-dir ./runtime/ready/signal `
  --sqlite-db ./runtime/signals.db `
  --output ./artifacts/parity_diff.json

# Linux/macOS
python scripts/test_dual_sink_parity.py \
  --jsonl-dir ./runtime/ready/signal \
  --sqlite-db ./runtime/signals.db \
  --output ./artifacts/parity_diff.json
```

---

## 4) 实现步骤

### 4.1 关闭流程优化

**目标**：确保双 Sink 关闭时无未提交批次

**实现位置**：
- `src/alpha_core/signals/core_algo.py::MultiSink.close()`
- `src/alpha_core/signals/sinks.py::JsonlSink.close()` / `SqliteSink.close()`

**要求**：
- `MultiSink.close()` 调用所有子 Sink 的 `close()`
- `JsonlSink.close()` 执行 `drain()`（确保缓冲区清空）
- `SqliteSink.close()` 执行 `flush_and_commit()`（确保所有批次提交）

### 4.2 等价性测试脚本

**功能**：
1. 读取 JSONL 文件（`./runtime/ready/signal/**/*.jsonl`）
2. 读取 SQLite 数据库（`./runtime/signals.db`）
3. 按分钟交集窗口聚合数据
4. 对比关键指标：
   - `overlap_total`：交集窗口内的总信号数
   - `overlap_confirm`：交集窗口内的确认信号数
   - `strong_ratio`：强信号占比
5. 计算差异百分比
6. 生成 `parity_diff.json` 证据包

**输出格式**（parity_diff.json）：
```json
{
  "test_timestamp": "2025-11-08T12:00:00Z",
  "jsonl_stats": {
    "total": 100000,
    "confirmed": 50000,
    "strong": 10000,
    "strong_ratio": 0.20
  },
  "sqlite_stats": {
    "total": 100050,
    "confirmed": 50025,
    "strong": 10010,
    "strong_ratio": 0.2001
  },
  "differences": {
    "total_diff_pct": 0.05,
    "confirm_diff_pct": 0.05,
    "strong_ratio_diff_pct": 0.05
  },
  "window_alignment": {
    "status": "aligned",
    "first_minute": 1730790000,
    "last_minute": 1730791800,
    "overlap_minutes": 30
  },
  "top_minute_diffs": [
    {
      "minute": 1730790000,
      "jsonl_count": 1000,
      "sqlite_count": 1002,
      "diff_pct": 0.20
    }
  ],
  "threshold_exceeded_minutes": []
}
```

### 4.3 窗口对齐检查

**要求**：
- 计算 JSONL 和 SQLite 的时间窗口交集
- 仅对比交集窗口内的数据
- 如果窗口未对齐，记录警告但不影响测试
- 在 `parity_diff.json` 中记录窗口对齐状态

---

## 5) 验收（Definition of Done）

### 等价性指标

* [ ] `overlap_total` 差异 < 0.2%
* [ ] `overlap_confirm` 差异 < 0.2%
* [ ] `strong_ratio` 差异 < 0.2%

### 窗口对齐

* [ ] 无"窗口未对齐"提示
* [ ] `window_alignment.status` 为 `"aligned"`
* [ ] `overlap_minutes` > 0

### 关闭流程

* [ ] 关闭时两 Sink 均无未提交批次
* [ ] JSONL Sink 队列 = 0（`drain()` 成功）
* [ ] SQLite Sink 无脏页/半行（`flush_and_commit()` 成功）

### 证据包

* [ ] `parity_diff.json` 生成
* [ ] 包含 `top_minute_diffs`（Top-N 差异分钟）
* [ ] 包含 `threshold_exceeded_minutes`（超过阈值的分钟）
* [ ] 两份日报生成（JSONL 和 SQLite 各一份）
* [ ] 证据包随 CI artifact 上传

---

## 6) 实现清单（Cursor 可执行）

### 6.1 关闭流程优化

* [ ] 修改 `MultiSink.close()` 确保顺序关闭
* [ ] 修改 `JsonlSink.close()` 添加 `drain()` 逻辑
* [ ] 修改 `SqliteSink.close()` 添加 `flush_and_commit()` 逻辑
* [ ] 添加关闭状态检查（队列长度、未提交批次）

### 6.2 等价性测试脚本

* [ ] 创建 `scripts/test_dual_sink_parity.py`
* [ ] 实现分钟交集窗口聚合逻辑
* [ ] 实现差异计算逻辑
* [ ] 实现 `parity_diff.json` 生成逻辑
* [ ] 添加窗口对齐检查

### 6.3 集成测试

* [ ] 运行双 Sink 模式 30 分钟
* [ ] 执行等价性测试脚本
* [ ] 验证差异 < 0.2%
* [ ] 验证关闭流程无残留

---

## 7) 测试脚本

### 7.1 双 Sink 等价性测试脚本

**文件**: `scripts/test_dual_sink_parity.py`

**功能**:
- 读取 JSONL 和 SQLite 数据
- 按分钟交集窗口聚合
- 计算差异百分比
- 生成 `parity_diff.json`

**使用方法**:
```powershell
python scripts/test_dual_sink_parity.py `
  --jsonl-dir ./runtime/ready/signal `
  --sqlite-db ./runtime/signals.db `
  --output ./artifacts/parity_diff.json `
  --threshold 0.2
```

### 7.2 完整测试流程

```powershell
# 1. 运行双 Sink 模式
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,broker,report `
  --sink dual `
  --minutes 30

# 2. 执行等价性测试
python scripts/test_dual_sink_parity.py `
  --jsonl-dir ./runtime/ready/signal `
  --sqlite-db ./runtime/signals.db `
  --output ./artifacts/parity_diff.json

# 3. 检查结果
# 查看 parity_diff.json 中的 differences 字段
```

---

## 8) 风险与回滚

* **差异过大**：如果差异 > 0.2%，需要分析原因（时间窗口、数据丢失、写入顺序等）
* **窗口未对齐**：如果窗口未对齐，需要检查数据源时间戳一致性
* **关闭残留**：如果关闭时仍有未提交批次，需要优化关闭流程
* **性能影响**：关闭流程优化可能影响性能，需要平衡

---

## 9) 交付物

* `scripts/test_dual_sink_parity.py` - 等价性测试脚本
* `artifacts/parity_diff.json` - 差异分析证据包
* `reports/v4.0.6-TASK-07B-双Sink等价性收敛报告.md` - 详细验证报告
* 两份日报（JSONL 和 SQLite 各一份）

---

## 10) 开发提示（Cursor）

* 优先优化关闭流程，确保无残留
* 使用分钟交集窗口避免时间窗口不一致导致的差异
* 差异分析应聚焦于数据一致性，而非性能差异
* 建议使用固定数据源（如回放数据）进行测试，避免实时数据的时间窗口问题

---

## 11) 质量门禁（PR 勾选）

* [ ] 所有差异指标 < 0.2%
* [ ] 窗口对齐检查通过
* [ ] 关闭流程无残留
* [ ] `parity_diff.json` 生成正确
* [ ] 证据包完整（含两份日报）
* [ ] 测试脚本可重复执行
* [ ] 文档同步（README/Docs 链接）

---

**任务状态**: ⏳ **待执行**  
**预计完成时间**: 待定  
**优先级**: P0（高优先级）  
**当前差异**: < 1.5%（目标：< 0.2%）

