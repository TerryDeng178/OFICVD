# alpha_core：打包成熟组件（OFI/CVD/FUSION/DIVERGENCE/STRATEGYMODE）
**任务编号**: TASK-04  
**批次**: M1  
**优先级**: P0  
**所属模块**: pkg

## 背景
把成熟组件收敛到单一可安装包，MCP 仅适配 I/O。

## 目标
采用 src layout：`src/alpha_core/**`；提供二次导出与别名。

## 前置依赖
- 无

## 输出物
- 可 `pip install -e .` 安装
- 统一导入路径稳定

## 实现步骤（Cursor 分步操作）
- [ ] 新建目录：`src/alpha_core/microstructure/{ofi,cvd,fusion,divergence}`、`src/alpha_core/risk`
- [ ] 移动：real_ofi_calculator.py / real_cvd_calculator.py / ofi_cvd_fusion.py / ofi_cvd_divergence.py / strategy_mode_manager.py→strategy_mode.py
- [ ] 补 `__init__.py` 做二次导出
- [ ] 写 `pyproject.toml`

## 验收标准（Acceptance Criteria）
- MCP 与 orchestrator 可直接 `from alpha_core...` 导入并运行

## 验收命令/脚本
```bash
pip install -e . && python -c "import alpha_core; print('ok')"
```

## 代码改动清单（相对仓库根）
- src/alpha_core/**
- pyproject.toml
- tests/（可选）

## 潜在风险与回滚
- 移动路径破坏相对导入：统一绝对导入
- 命名不一致：在 __init__ 提供别名

## 预计工时
0.5~1 天
