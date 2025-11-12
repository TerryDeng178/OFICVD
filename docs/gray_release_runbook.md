# Risk Module Gray Release Runbook

**生成时间**：2025-11-12  
**适用场景**：`RISK_INLINE_ENABLED` 从 `false` 切换到 `true` 的灰度发布

---

## 灰度策略

### 50/50灰度

- **50%流量**：使用内联风控（`RISK_INLINE_ENABLED=true`）
- **50%流量**：使用Legacy风控（`RISK_INLINE_ENABLED=false`）
- **Shadow比对**：并行运行，实时比对决策一致性

### 自动回归检查

使用 `scripts/regression_test_risk.py` 脚本，检查以下指标（±5%阈值）：

- **Pass Rate**（通过率）
- **Deny Rate**（拒单率）
- **Notional**（名义额）
- **Latency**（延迟）

---

## 灰度发布步骤

### D-1（发布前一天）

1. **准备回归测试数据**
   ```bash
   # 准备测试数据（JSONL格式）
   python scripts/prepare_test_data.py --output ./runtime/test_signals.jsonl --count 1000
   ```

2. **运行基线测试（Legacy模式）**
   ```bash
   # 设置Legacy模式
   $env:RISK_INLINE_ENABLED = "false"
   python scripts/regression_test_risk.py --test-data ./runtime/test_signals.jsonl --output ./runtime/baseline_results.json
   ```

3. **验证监控和告警**
   - 确认Prometheus指标正常采集
   - 确认告警规则已部署（`docs/alerting_rules.md`）
   - 确认Dashboard可用

### D-0（发布当天）

1. **启动10%灰度**
   ```bash
   # 设置10%流量使用内联风控
   $env:RISK_INLINE_ENABLED = "true"
   $env:RISK_GRAY_RATIO = "0.1"  # 10%灰度
   
   # 启动strategy_server
   python -m mcp.strategy_server.app --config ./config/defaults.yaml
   ```

2. **监控关键指标**
   - `risk_shadow_parity_ratio` ≥ 99%
   - `risk_check_latency_seconds` p95 ≤ 5ms
   - `risk_precheck_total{result="deny"}` 拒单率在基线±5%内

3. **观察30分钟**
   - 检查告警是否触发
   - 检查日志是否有异常
   - 检查Shadow比对结果

4. **如果正常，提升到50%灰度**
   ```bash
   $env:RISK_GRAY_RATIO = "0.5"  # 50%灰度
   # 重启strategy_server
   ```

5. **观察1小时**
   - 持续监控关键指标
   - 运行回归测试脚本
   ```bash
   python scripts/regression_test_risk.py --test-data ./runtime/test_signals.jsonl --threshold 0.05
   ```

### D+1（发布后一天）

1. **如果50%灰度正常，提升到100%**
   ```bash
   $env:RISK_INLINE_ENABLED = "true"
   $env:RISK_GRAY_RATIO = "1.0"  # 100%灰度
   # 重启strategy_server
   ```

2. **持续监控24小时**
   - Shadow比对连续观测
   - 分时段检查（亚盘/欧盘/美盘）
   - 运行回归测试脚本

---

## 自动回滚触发条件

### 立即回滚（CRITICAL）

以下情况立即回滚到Legacy模式：

1. **Shadow一致率 < 98% 持续5分钟**
   ```bash
   # 自动回滚脚本
   $env:RISK_INLINE_ENABLED = "false"
   # 重启strategy_server
   ```

2. **p95延迟 > 8ms 持续5分钟**

3. **拒单率超出基线±10%**

### 警告回滚（WARN）

以下情况考虑回滚：

1. **Shadow一致率 < 99% 持续10分钟**
2. **p95延迟 > 5ms 持续5分钟**
3. **拒单率超出基线±5%**

---

## Shadow 24h连续观测

### 分时段检查

- **亚盘时段**（09:00-17:00 UTC+8）：检查parity比率
- **欧盘时段**（14:00-22:00 UTC+8）：检查parity比率
- **美盘时段**（21:00-05:00 UTC+8）：检查parity比率

### 观测脚本

```bash
# 24小时连续观测
python scripts/shadow_24h_monitor.py \
  --start-time "2025-11-13T00:00:00" \
  --duration 24h \
  --output ./runtime/shadow_24h_report.json
```

---

## 回滚步骤

### 快速回滚

```bash
# 1. 设置环境变量
$env:RISK_INLINE_ENABLED = "false"

# 2. 重启strategy_server
python -m mcp.strategy_server.app --config ./config/defaults.yaml

# 3. 验证回滚成功
# 检查日志：应该看到 "RiskManager disabled (fallback to legacy)"
```

### 回滚验证

1. **检查服务状态**
   ```bash
   curl http://localhost:9090/readyz
   # 应该返回：ready: RiskManager disabled (fallback to legacy)
   ```

2. **检查指标**
   ```bash
   curl http://localhost:9090/metrics | Select-String "risk_precheck_total"
   ```

3. **运行回归测试**
   ```bash
   python scripts/regression_test_risk.py --test-data ./runtime/test_signals.jsonl
   ```

---

## 检查清单

### 发布前检查

- [ ] 回归测试脚本已准备
- [ ] 告警规则已部署
- [ ] Dashboard已创建
- [ ] Shadow比对已启用
- [ ] 回滚脚本已测试

### 发布中检查

- [ ] 关键指标正常（parity ≥ 99%, latency p95 ≤ 5ms）
- [ ] 告警未触发
- [ ] 日志无异常
- [ ] Shadow比对结果正常

### 发布后检查

- [ ] 24小时连续观测完成
- [ ] 分时段parity检查通过
- [ ] 回归测试通过（±5%阈值）
- [ ] 无异常告警

---

## 联系信息

- **On-Call**：Strategy Owner
- **Escalation**：QA Lead, Orchestrator Owner

---

**维护者**：OFI+CVD开发团队  
**版本**：v1.0

