# Risk Module Dashboard Minimal

**生成时间**：2025-11-12  
**适用模块**：`mcp/strategy_server/risk/`  
**数据源**：Prometheus指标（`/metrics`端点）

---

## Dashboard最小版（4个面板）

### 面板1：Latency（延迟）

**指标**：`risk_check_latency_seconds`（Histogram）

**查询**：
```promql
# p50
histogram_quantile(0.50, rate(risk_check_latency_seconds_bucket[5m]))

# p95
histogram_quantile(0.95, rate(risk_check_latency_seconds_bucket[5m]))

# p99
histogram_quantile(0.99, rate(risk_check_latency_seconds_bucket[5m]))
```

**可视化**：
- 类型：Time Series
- Y轴：秒（seconds）
- 阈值线：p95 ≤ 5ms (0.005s)

---

### 面板2：Deny/Pass Rate（拒单/通过率）

**指标**：`risk_precheck_total{result="pass|deny",reason=*}`（Counter）

**查询**：
```promql
# Pass Rate
sum(rate(risk_precheck_total{result="pass"}[5m])) / sum(rate(risk_precheck_total[5m]))

# Deny Rate
sum(rate(risk_precheck_total{result="deny"}[5m])) / sum(rate(risk_precheck_total[5m]))

# Deny Rate by Reason
sum(rate(risk_precheck_total{result="deny",reason=~".+"}[5m])) by (reason)
```

**可视化**：
- 类型：Time Series + Pie Chart
- Y轴：比率（0.0-1.0）
- 阈值线：Deny Rate基线±5%

---

### 面板3：Shadow Parity & Alert（影子一致性）

**指标**：
- `risk_shadow_parity_ratio`（Gauge）
- `risk_shadow_alert{level=*}`（Gauge）

**查询**：
```promql
# Parity Ratio
risk_shadow_parity_ratio

# Alert Level
risk_shadow_alert{level="warn"}  # 1 = warn, 0 = ok
risk_shadow_alert{level="critical"}  # 1 = critical, 0 = ok
```

**可视化**：
- 类型：Time Series + Stat
- Y轴：比率（0.0-1.0）
- 阈值线：99% (0.99)

---

### 面板4：Throughput（吞吐）

**指标**：`risk_check_latency_seconds_count`（Counter）

**查询**：
```promql
# Checks per second
rate(risk_check_latency_seconds_count[5m])
```

**可视化**：
- 类型：Time Series
- Y轴：Checks/sec

---

## Grafana Dashboard JSON配置

```json
{
  "dashboard": {
    "title": "Risk Module Dashboard",
    "panels": [
      {
        "title": "Latency (p50/p95/p99)",
        "targets": [
          {
            "expr": "histogram_quantile(0.50, rate(risk_check_latency_seconds_bucket[5m]))"
          },
          {
            "expr": "histogram_quantile(0.95, rate(risk_check_latency_seconds_bucket[5m]))"
          },
          {
            "expr": "histogram_quantile(0.99, rate(risk_check_latency_seconds_bucket[5m]))"
          }
        ]
      },
      {
        "title": "Deny/Pass Rate",
        "targets": [
          {
            "expr": "sum(rate(risk_precheck_total{result=\"pass\"}[5m])) / sum(rate(risk_precheck_total[5m]))"
          },
          {
            "expr": "sum(rate(risk_precheck_total{result=\"deny\"}[5m])) / sum(rate(risk_precheck_total[5m]))"
          }
        ]
      },
      {
        "title": "Shadow Parity & Alert",
        "targets": [
          {
            "expr": "risk_shadow_parity_ratio"
          },
          {
            "expr": "risk_shadow_alert{level=\"warn\"}"
          },
          {
            "expr": "risk_shadow_alert{level=\"critical\"}"
          }
        ]
      },
      {
        "title": "Throughput (Checks/sec)",
        "targets": [
          {
            "expr": "rate(risk_check_latency_seconds_count[5m])"
          }
        ]
      }
    ]
  }
}
```

---

## 使用说明

1. **导入Dashboard**：将JSON配置导入到Grafana
2. **配置数据源**：确保Prometheus数据源已配置
3. **设置刷新间隔**：建议30秒
4. **配置告警**：参考 `docs/alerting_rules.md`

---

**维护者**：OFI+CVD开发团队  
**版本**：v1.0

