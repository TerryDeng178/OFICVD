# TASK-07A · LIVE 60 分钟端到端实测（Soak Test）

> 里程碑：M3 · 依赖：TASK-07 · 最近更新：2025-11-08 (Asia/Tokyo)  
> **状态**: 🟡 **部分通过**（核心功能100%，监控功能40%，证据产出60%）

---

## 0) 背景与目标

本任务负责在真实/准实时数据上连续运行 60 分钟，验证 Orchestrator 在 LIVE 模式下的稳定性、健康检查、优雅关闭/重启、以及 Reporter→时序库/告警闭环。

**预期产物**：
- 60 分钟 Soak Test 运行日志和报告
- 时序库导出数据（Prometheus/InfluxDB）
- 告警规则验证结果
- 故障注入测试报告
- 优雅关闭验证报告


---

## 1) 范围

### In Scope

* LIVE 模式 60 分钟连续运行（真实/准实时数据源）
* 健康检查验证（LIVE 窗口严格检查）
* 故障注入测试（kill 子进程验证重启）
* 时序库导出验证（Prometheus/InfluxDB）
* 告警规则验证（3 类告警规则触发和恢复）
* 优雅关闭验证（关闭顺序、无残留队列）
* 双 Sink 并行运行验证（JSONL + SQLite，差异 < 0.5%）
* Harvester SLO 指标验证（queue_dropped、reconnect_count、子流超时）
* 资源上限验证（RSS < 600MB、文件数 < 256）
* 证据包生成（run_manifest、source_manifest、parity_diff）

### Out of Scope

* 回测与复盘（见 TASK-09）
* 性能压测（单独任务）

---

## 2) 前置与依赖

* **TASK-07**：Orchestrator 编排与端到端冒烟已完成
* **P0/P1 优化**：双 Sink、健康检查、优雅重启、时序库导出等功能已实现
* 真实/准实时数据源可用（Binance Futures WebSocket 或准实时回放）
* 时序库环境就绪（Prometheus Pushgateway 或 InfluxDB）

---

## 3) 运行契约（CLI & 环境）

### 3.1 Orchestrator CLI

```powershell
# Windows PowerShell - JSONL Sink
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,broker,report `
  --sink jsonl `
  --minutes 60

# Windows PowerShell - SQLite Sink（并行运行）
python -m orchestrator.run `
  --config ./config/defaults.yaml `
  --enable harvest,signal,broker,report `
  --sink sqlite `
  --minutes 60

# Linux/macOS
python -m orchestrator.run \
  --config ./config/defaults.yaml \
  --enable harvest,signal,broker,report \
  --sink jsonl \
  --minutes 60
```

### 3.2 环境变量

**时序库导出**：
* `TIMESERIES_TYPE=prometheus` 或 `influxdb`
* `TIMESERIES_URL=<pushgateway_url>` 或 `<influxdb_url>`
* `REPORT_TZ=Asia/Tokyo`（报表时区）

**LIVE 模式**：
* `V13_REPLAY_MODE=0`（确保 LIVE 模式）
* 不使用 `--config defaults.smoke.yaml`（使用生产配置）

---

## 4) 测试步骤

### 4.1 启动阶段

1. **准备环境**
   - 配置时序库连接（Prometheus Pushgateway 或 InfluxDB）
   - **执行时序库可达性预检**（验证 Pushgateway/InfluxDB 连接）
   - 设置 `REPORT_TZ=Asia/Tokyo`
   - 确保数据源可用（真实 WebSocket 或准实时回放）

2. **启动 Orchestrator（JSONL）**
   ```powershell
   $env:TIMESERIES_TYPE = "prometheus"
   $env:TIMESERIES_URL = "http://localhost:9091"
   $env:REPORT_TZ = "Asia/Tokyo"
   $env:V13_REPLAY_MODE = "0"
   
   python -m orchestrator.run `
     --config ./config/defaults.yaml `
     --enable harvest,signal,broker,report `
     --sink jsonl `
     --minutes 60
   ```

3. **并行启动 Orchestrator（SQLite）**
   - 在另一个终端或后台进程运行 SQLite 版本
   - 使用相同的配置和环境变量
   - **记录启动时间**（用于后续生成 `source_manifest.json`）

### 4.2 运行监控

1. **健康检查监控**
   - 每 10 秒检查一次健康状态
   - 验证 LIVE 模式下的严格时间窗口检查
   - 确保所有进程保持 `health=green`

2. **时序库数据验证**
   - 检查 Prometheus/InfluxDB 中是否有数据
   - 验证指标：`total`、`strong_ratio`、`gating_breakdown`、`per_minute`

3. **告警规则验证**
   - 监控告警触发情况
   - 验证告警恢复机制

### 4.3 故障注入（约 30 分钟时）

1. **查找 signal 进程 PID**
   ```powershell
   # 从日志或进程列表中找到 signal 进程 PID
   Get-Process python | Where-Object {$_.CommandLine -like "*signal_server*"}
   ```

2. **Kill 进程**
   ```powershell
   taskkill /F /PID <signal_pid>
   ```

3. **观察重启**
   - 验证进程在 12 秒内成功重启
   - 检查重启计数和退避延迟
   - 验证新进程 PID 更新

### 4.4 优雅关闭（60 分钟结束时）

1. **发送 SIGINT/SIGTERM**
   - 使用 Ctrl+C 或 `kill` 命令
   - 观察关闭顺序：report → broker → signal → harvest
   - **记录关闭顺序到 `run_manifest.json`**（`shutdown_order_seen=true`）

2. **验证无残留**
   - 检查进程是否完全退出
   - 验证队列是否清空
   - 检查日志中的关闭顺序

3. **生成证据包**
   - 执行双 Sink 等价性测试脚本，生成 `parity_diff.json`
   - 生成 `source_manifest.json`（记录数据源信息、时间窗、配置快照）
   - 验证 `run_manifest.json` 包含资源使用、重启退避模式等字段

---

## 5) 验收（Definition of Done）

### 判定口径（完成标准）

**必须全部满足以下条件才能判定为"完成"**：

1. **LIVE 60 分钟内健康绿灯 ≥ 98%**
   - 所有进程（harvest/signal/broker/report）健康状态为 `healthy`
   - 健康检查失败次数 ≤ 总检查次数的 2%

2. **三类告警能触发并记录**
   - 连续 2 分钟 total == 0（critical）
   - low_consistency 占比单分钟 > 80%（warning）
   - strong_ratio 短时崩塌（warning）
   - 告警触发/恢复时间、规则名、级别、详情记录在 `run_manifest.alerts`

3. **时序导出每分钟 ≥ 1 次且错误计数 = 0**
   - `run_manifest.timeseries_export.export_count ≥ 60`
   - `run_manifest.timeseries_export.error_count == 0`
   - 数据格式正确（Prometheus labels 或 InfluxDB tags）

4. **双 Sink 差异 < 0.5%**
   - `parity_diff.json` 中 `total_diff_pct`、`confirm_diff_pct`、`strong_ratio_diff_pct` 均 < 0.5%
   - 证据包齐全：两份日报（JSONL + SQLite）+ `parity_diff.json` + `source_manifest.json`

5. **Manifest 字段完备**
   - `harvester_metrics`：queue_dropped、substream_timeout_detected、reconnect_count
   - `resource_usage`：max_rss_mb、max_open_files
   - `shutdown_order`：关闭顺序记录（report → broker → signal → harvest）

### 功能验证

* [x] 60 分钟内所有进程保持 `health=green`（LIVE 窗口严格检查）✅ **已通过**
* [ ] 无"连续 2 分钟 total=0"的告警触发（需实现告警记录）
* [ ] 优雅关闭日志顺序正确（report→broker→signal→harvest，需记录到 manifest）
* [ ] 无残留队列或未提交数据

### 双 Sink 等价性验证（必须项）

* [ ] **JSONL vs SQLite 同窗统计差异 < 0.5%**（total/confirm/strong_ratio）
* [ ] **生成 `parity_diff.json` 证据包**（含差异分析和窗口对齐状态）
* [ ] **生成两份日报**（JSONL 和 SQLite 各一份）作为对比证据
* **说明**: 必须使用 `--sink dual` 运行 60 分钟 LIVE 测试

### Harvester SLO 指标（必须项）

* [ ] `queue_dropped == 0`（队列无丢弃）
* [ ] `substream_timeout_detected == false`（子流无超时）
* [ ] `reconnect_count ≤ 3`（重连次数 ≤ 3）
* [ ] **以上指标记录在 `run_manifest.harvester_metrics` 中**（必须实现）

### 时序库导出验证（必须项）

* [ ] 启动前完成 Pushgateway/InfluxDB 可达性预检
* [ ] 时序库中能看到 `total`、`strong_ratio`、`gating_breakdown`、`per_minute` 数据
* [ ] **导出频率：每分钟至少 1 次且无错误日志**（`run_manifest.timeseries_export.export_count ≥ 60`）
* [ ] **错误计数 = 0**（`run_manifest.timeseries_export.error_count == 0`）
* [ ] 数据格式正确（Prometheus labels 或 InfluxDB tags）
* [ ] 若 requests 缺失或 POST 失败，显式记录 Warning（代码已处理）
* [ ] **导出统计记录在 `run_manifest.timeseries_export` 中**（必须实现）

### 资源上限（必须项）

* [ ] RSS < 600MB（内存使用上限）
* [ ] 打开文件数 < 256（文件描述符上限）
* [ ] **资源使用情况记录在 `run_manifest.resource_usage` 中**（必须实现）

### 告警规则（必须项）

* [ ] 3 类告警规则均能触发：
  - 连续 2 分钟 total == 0（critical）
  - low_consistency 占比单分钟 > 80%（warning）
  - strong_ratio 短时崩塌（warning）
* [ ] 告警能够恢复（条件不再满足时告警消失）
* [ ] **告警信息记录在 `run_manifest.alerts` 中**（触发/恢复时间、规则名、级别、详情，必须实现）
* [ ] 告警信息正确输出到日志和报表

### 故障注入（可选，建议执行）

* [ ] signal 进程被 kill 后成功重启（12 秒内）
* [ ] 重启计数正确更新（记录在 `run_manifest.status.processes[process_name].restart_count`）
* [ ] 退避延迟机制生效（记录在 `run_manifest.restart_backoff_pattern`）
* [ ] 重启后进程恢复正常运行

### 产出物（必须项）

* [x] `run_manifest_*.json` 生成（包含运行统计、进程状态）✅ **已生成**
* [ ] **`run_manifest` 字段完备**：
  - [ ] `harvester_metrics`（queue_dropped、substream_timeout_detected、reconnect_count）
  - [ ] `resource_usage`（max_rss_mb、max_open_files）
  - [ ] `shutdown_order`（关闭顺序：report → broker → signal → harvest）
  - [ ] `timeseries_export`（export_count、error_count）
  - [ ] `alerts`（触发/恢复时间、规则名、级别、详情）
* [ ] **`source_manifest.json` 生成**（记录 symbol 列表、会话开始/结束时间、WS 端点与地区、配置快照，必须实现）
* [ ] **`parity_diff.json` 生成**（双 Sink 等价性证据包，必须使用 `--sink dual` 运行）
* [ ] 日报生成（JSON + Markdown，JSONL 和 SQLite 各一份，双 Sink 模式）
* [ ] 日报包含 `runtime_state` 区块
* [ ] 日报包含告警信息
* [ ] 日报包含 Harvester SLO 指标（queue_dropped、substream_timeout_detected、reconnect_count）
* [ ] 时序库导出状态记录在日报中

---

## 6) 测试脚本（可选）

### 6.1 Soak Test 脚本（Windows PowerShell）

```powershell
# scripts/soak_test.ps1
param(
    [string]$Config = "./config/defaults.yaml",
    [int]$Minutes = 60,
    [string]$Sink = "jsonl"
)

$env:TIMESERIES_TYPE = "prometheus"
$env:TIMESERIES_URL = "http://localhost:9091"
$env:REPORT_TZ = "Asia/Tokyo"
$env:V13_REPLAY_MODE = "0"

Write-Host "=== LIVE 60 分钟 Soak Test ===" -ForegroundColor Green
Write-Host "配置: $Config" -ForegroundColor Yellow
Write-Host "Sink: $Sink" -ForegroundColor Yellow
Write-Host "时长: $Minutes 分钟" -ForegroundColor Yellow
Write-Host ""

python -m orchestrator.run `
  --config $Config `
  --enable harvest,signal,broker,report `
  --sink $Sink `
  --minutes $Minutes

Write-Host ""
Write-Host "=== Soak Test 完成 ===" -ForegroundColor Green
```

### 6.2 故障注入脚本

参考 `scripts/test_fault_injection.py`（如存在）或手动执行故障注入步骤。

---

## 7) 风险与回滚

* **数据源中断**：如果 WebSocket 连接中断，Harvest 会触发健康检查失败，应自动标记为 `degraded`
* **时序库不可用**：如果时序库连接失败，应记录警告但不应中断运行
* **告警误报**：如果告警规则过于敏感，应调整阈值或增加过滤条件
* **进程重启失败**：如果重启超过最大次数，应标记为 `unhealthy` 并记录错误

---

## 8) 交付物

### 报告文件
* `reports/v4.0.6-TASK-07A-SoakTest报告.md` - Soak Test 详细报告
* `reports/v4.0.6-TASK-07A-故障注入报告.md` - 故障注入测试报告
* `reports/v4.0.6-TASK-07A-时序库导出验证报告.md` - 时序库导出验证报告
* `reports/v4.0.6-TASK-07A-告警规则验证报告.md` - 告警规则验证报告

### 日志文件
* `logs/orchestrator/orchestrator.log` - Orchestrator 运行日志
* `logs/report/summary_*.json|md` - 生成的日报（JSONL 和 SQLite 各一份）

### 证据包（Manifest & Parity）
* `artifacts/run_logs/run_manifest_*.json` - 运行清单（包含资源使用、优雅关闭顺序、重启退避模式）
* `artifacts/source_manifest.json` - 数据源清单（symbol 列表、会话时间窗、WS 端点、配置快照）
* `artifacts/parity_diff.json` - 双 Sink 等价性证据包（差异分析、窗口对齐状态）

---

## 9) 收尾清单（完成标准）

**当前状态**: 🟡 **部分通过**（核心功能100%，监控功能40%，证据产出60%）

**通过项**:
- ✅ 运行时长 ≥ 60 分钟（60.3 分钟）
- ✅ 进程健康状态全部为 `healthy`
- ✅ 信号产出正常（557,986 条，强信号 11.0%）
- ✅ 信号速率正常（~9,300 信号/分钟）

**待完善项（必须全部完成才能判定为"完成"）**:

### 1. 双 Sink 等价性（LIVE 同窗）🔴 必须项

- [ ] 使用 `--sink dual` 重跑 60 分钟 LIVE 测试
- [ ] 生成 `parity_diff.json` 证据包
- [ ] 核心计数与强信号占比差异 < 0.5%（total/confirm/strong_ratio）
- [ ] 生成两份日报（JSONL + SQLite）作为对比证据

### 2. 时序库导出统计 🔴 必须项

- [ ] 在 `run_manifest` 写入 `timeseries_export` 字段：
  - `export_count`（导出次数，应 ≥ 60）
  - `error_count`（错误次数，应 = 0）
- [ ] 配合已有 `timeseries_data` 字段
- [ ] 按 P1-1 报告的导出实现做联调验证

### 3. 告警记录闭环 🔴 必须项

- [ ] 在 `run_manifest` 补 `alerts` 字段：
  - 触发/恢复时间
  - 规则名（critical/warning）
  - 级别
  - 详情
- [ ] 在日报中落表显示告警信息

### 4. Harvester SLO 指标 🔴 必须项

- [ ] 把以下指标汇总到 `run_manifest.harvester_metrics`：
  - `queue_dropped`（应 = 0）
  - `substream_timeout_detected`（应为 false）
  - `reconnect_count`（应 ≤ 3）

### 5. 资源与关停顺序 🔴 必须项

- [ ] 补 `resource_usage` 字段：
  - `max_rss_mb`（最大 RSS，应 < 600MB）
  - `max_open_files`（最大文件描述符数，应 < 256）
- [ ] 补 `shutdown_order` 字段（记录关闭顺序：report → broker → signal → harvest）

### 6. source_manifest.json 🔴 必须项

- [ ] 写入 symbol 列表
- [ ] 写入会话起止时间
- [ ] 写入 WS 端点/地区
- [ ] 写入配置快照
- [ ] 随证据包产出

### 7. 故障注入（可选，建议执行）🟡 可选项

- [ ] 中途 kill signal 进程验证重启与退避
- [ ] 把 `restart_count` 和 `backoff_pattern` 记入 manifest

---

## 10) 开发提示（Cursor）

### 执行前准备
* 使用真实数据源时，确保网络连接稳定
* **执行时序库可达性预检**（避免运行时才发现连接问题）
* 检查系统资源限制（ulimit -n 等，确保文件描述符充足）

### 执行中监控
* 时序库连接失败不应中断主流程，应记录警告（代码已处理）
* 监控资源使用情况（RSS、文件描述符）
* 建议使用监控工具（如 Grafana）实时查看时序库数据
* 关注 Harvester SLO 指标（queue_dropped、reconnect_count）

### 故障注入与关闭
* 故障注入应在进程稳定运行后进行（建议 30 分钟时）
* 优雅关闭验证应在运行结束时进行
* 确保 `run_manifest.json` 记录关闭顺序和重启退避模式

### 证据包生成
* 运行结束后执行双 Sink 等价性测试脚本
* 生成 `source_manifest.json`（记录数据源、时间窗、配置）
* 验证所有证据包完整性（run_manifest、source_manifest、parity_diff、两份日报）

---

## 10) 质量门禁（PR 勾选）

### 功能验证
* [ ] 60 分钟连续运行无异常退出
* [ ] 所有健康检查保持 `health=green`
* [ ] 故障注入测试通过（重启 12 秒内恢复）
* [ ] 优雅关闭顺序正确（记录到 run_manifest）

### 数据质量
* [ ] 时序库数据正常推送（每分钟至少 1 次，无错误日志）
* [ ] 双 Sink 等价性通过（差异 < 0.5%，parity_diff.json 生成）
* [ ] Harvester SLO 指标达标（queue_dropped==0、无超时、reconnect_count≤3）

### 资源与稳定性
* [ ] 资源使用在限制内（RSS < 600MB、文件数 < 256）
* [ ] 告警规则正确触发和恢复
* [ ] 所有产出物完整（run_manifest、source_manifest、parity_diff、两份日报）
* [ ] 文档同步（README/Docs 链接）

---

**任务状态**: ⏳ **待执行**  
**预计完成时间**: 待定  
**优先级**: P0（高优先级）

