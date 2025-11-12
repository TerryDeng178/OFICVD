# Risk Module Alerting Rules

**生成时间**：2025-11-12  
**适用模块**：`mcp/strategy_server/risk/`  
**指标来源**：Prometheus格式导出（`/metrics`端点）

---

## 告警规则定义

### 1. 延迟告警（risk_check_latency_seconds）

**指标**：`risk_check_latency_seconds`（Histogram，秒）

**告警规则**：

```yaml
# WARN: p95延迟持续5分钟 > 5ms
- alert: RiskLatencyHigh
  expr: |
    histogram_quantile(0.95, rate(risk_check_latency_seconds_bucket[5m])) > 0.005
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Risk check latency p95 exceeds 5ms"
    description: "Risk check p95 latency is {{ $value }}s (threshold: 5ms) for 5 minutes"

# CRITICAL: p95延迟持续5分钟 > 8ms
- alert: RiskLatencyCritical
  expr: |
    histogram_quantile(0.95, rate(risk_check_latency_seconds_bucket[5m])) > 0.008
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Risk check latency p95 exceeds 8ms"
    description: "Risk check p95 latency is {{ $value }}s (threshold: 8ms) for 5 minutes"
```

**依据**：E2E测试性能要求（p95 ≤ 5ms）

---

### 2. Shadow一致性告警（risk_shadow_parity_ratio）

**指标**：`risk_shadow_parity_ratio`（Gauge，0.0-1.0）

**告警规则**：

```yaml
# WARN: 一致率低于99%持续10分钟
- alert: RiskShadowParityLow
  expr: |
    risk_shadow_parity_ratio < 0.99
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Risk shadow parity ratio below 99%"
    description: "Shadow parity ratio is {{ $value }} (threshold: 99%) for 10 minutes"

# CRITICAL: 一致率低于98%持续5分钟
- alert: RiskShadowParityCritical
  expr: |
    risk_shadow_parity_ratio < 0.98
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Risk shadow parity ratio below 98%"
    description: "Shadow parity ratio is {{ $value }} (threshold: 98%) for 5 minutes"
```

**依据**：一致率目标（≥99%）

---

### 3. 拒单率告警（risk_precheck_total）

**指标**：`risk_precheck_total{result="deny",reason=*}`（Counter）

**告警规则**：

```yaml
# WARN: 拒单率超过基线±5%（回归阈值）
- alert: RiskDenyRateAnomaly
  expr: |
    (
      sum(rate(risk_precheck_total{result="deny"}[5m])) /
      sum(rate(risk_precheck_total[5m]))
    ) > (baseline_deny_rate * 1.05) OR
    (
      sum(rate(risk_precheck_total{result="deny"}[5m])) /
      sum(rate(risk_precheck_total[5m]))
    ) < (baseline_deny_rate * 0.95)
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Risk deny rate anomaly detected"
    description: "Deny rate is {{ $value }} (baseline: {{ baseline_deny_rate }}, threshold: ±5%)"
```

**依据**：回归测试阈值（±5%）

---

## 告警集成

### Prometheus配置示例

```yaml
# prometheus.yml
rule_files:
  - "alerting_rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - "alertmanager:9093"
```

### AlertManager路由示例

```yaml
# alertmanager.yml
route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'risk-alerts'
  routes:
    - match:
        severity: critical
      receiver: 'risk-critical'
    - match:
        severity: warning
      receiver: 'risk-warning'

receivers:
  - name: 'risk-critical'
    webhook_configs:
      - url: 'http://risk-alert-handler:8080/alerts'
  - name: 'risk-warning'
    webhook_configs:
      - url: 'http://risk-alert-handler:8080/alerts'
```

---

## 指标口径迁移路线图

### 当前状态（T+0）

- ✅ `risk_check_latency_seconds`（主推）
- ✅ `risk_check_latency_ms`（兼容，标记为DEPRECATED）

### 迁移计划

- **T+7天**：Dashboard全部切换到`risk_check_latency_seconds`
- **T+14天**：停止导出`risk_check_latency_ms`，仅保留`risk_check_latency_seconds`

---

## 使用说明

1. **部署告警规则**：将告警规则文件添加到Prometheus配置
2. **配置AlertManager**：设置告警路由和接收器
3. **监控Dashboard**：创建Grafana面板监控关键指标
4. **定期审查**：每周审查告警规则的有效性和阈值

---

**维护者**：OFI+CVD开发团队  
**版本**：v1.0

