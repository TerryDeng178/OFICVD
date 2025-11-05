# Broker MCP：后端切换（paper｜ccxt｜testnet）
**任务编号**: TASK-15  
**批次**: M2  
**优先级**: P1  
**所属模块**: broker

## 背景
保持统一接口，按配置切换后端，优先接 testnet。

## 目标
抽象 `IBroker`；提供 PaperBackend 与 CCXTBackend（testnet）。

## 前置依赖
- TASK-14

## 输出物
- 切换后端无需改上游
- 速率限制/429 退避

## 实现步骤（Cursor 分步操作）
- [ ] 定义接口与工厂
- [ ] 实作 CCXT backend（testnet）
- [ ] 步进/精度/最小委托校验
- [ ] 速率限制与指数退避

## 验收标准（Acceptance Criteria）
- testnet 下单/撤单/查持仓通过；429 自动退避

## 验收命令/脚本
```bash
export BROKER_BACKEND=ccxt
python orchestrator/run.py
```

## 代码改动清单（相对仓库根）
- mcp/broker_gateway_server/app.py
- config/defaults.yaml: broker.*

## 潜在风险与回滚
- 精度差异：下单前 round_down

## 预计工时
1.5 天
