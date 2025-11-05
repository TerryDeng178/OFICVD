# TASK-04 · 特征计算接线（OFI＋CVD＋FUSION＋DIVERGENCE）
> 里程碑：M1→M2 | 更新：2025-11-05 (Asia/Tokyo)

## 背景
已有成熟组件：
- `src/alpha_core/microstructure/ofi/real_ofi_calculator.py`
- `src/alpha_core/microstructure/cvd/real_cvd_calculator.py`
- `src/alpha_core/microstructure/fusion/ofi_cvd_fusion.py`
- `src/alpha_core/microstructure/divergence/ofi_cvd_divergence.py`

## 目标
- 用统一输入（来自 HARVEST）驱动上述组件；
- 固定输出字段（z_ofi / z_cvd / fusion_score / div_type 等）；
- 提供最小可跑 demo：读取 `data/...` → 产出 `feature_stream`（内存管道或本地 cache）。

## 成果物
- 代码：`alpha_core.microstructure.*` 对外 `compute(batch)->dict` API；  
- 文档：在 `/docs/api_contracts.md` 新增“3.2 特征层 → CORE_ALGO”。

## 验收标准
- [ ] 单元测试：给定样本输入，输出字段完备且稳定；  
- [ ] 性能：每秒 1k 条输入下 CPU<1 核（本地）。
