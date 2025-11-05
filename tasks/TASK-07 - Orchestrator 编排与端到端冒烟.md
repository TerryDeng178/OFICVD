# TASK-07 · Orchestrator 编排与端到端冒烟
> 里程碑：M2 | 更新：2025-11-05 (Asia/Tokyo)

## 目标
- `orchestrator/run.py` 串起 harvest→features→signal→broker→report；
- 命令：
```bash
python -m orchestrator.run --config ./config/defaults.yaml --enable harvest,signal,broker,report
```
- 输出：订单模拟（或对接模拟网关），以及简单日报。

## 验收标准
- [ ] 端到端跑通 30 分钟；  
- [ ] 产出 signals 与 mock orders；  
- [ ] 没有无界内存增长。
