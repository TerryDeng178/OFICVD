# ✅ TASK-03 · Harvest MCP 薄壳与本地运行脚本（增强版）

里程碑：M1（数据打通）｜状态：已完成｜更新：2025-11-06（Asia/Tokyo）
关联：README 的最小可跑（M1）命令需与本任务产物一致可用 ；任务清单在 README/TASK_INDEX 对齐 。

1) 目标（Why）

提供最薄的 MCP Harvest 服务：mcp/harvest_server/app.py 仅做参数解析与调用核心采集实现（alpha_core.ingestion.harvester.*），不落业务逻辑。原任务要求保持不变并明确指向 run_ws_harvest 调用点 。

提供 一键本地运行脚本：scripts/harvest_local.sh，与 README 的“安装与本地采集”示例命令一致可跑 。

确保 分片轮转 与 分区路径 正确：date=YYYY-MM-DD/hour=HH/symbol=<sym>/kind=<kind>/part-*.parquet（实现已写入 harvester，要求薄壳不破坏该路径路由） 。

2) 交付物（What）

代码：

mcp/harvest_server/app.py（MCP 薄壳）

scripts/harvest_local.sh（一键本地启动）

文档：更新 /README.md 的 M1 示例命令（如需），保证命令参数与本薄壳一致可跑 。

目录/导航与 README 对齐（/mcp/*/app.py 为各服务薄壳） 。

3) 目录结构（Where）
repo/
├─ mcp/
│  └─ harvest_server/
│     └─ app.py         # 本任务新增/完善
└─ scripts/
   └─ harvest_local.sh   # 本任务新增/完善

4) 运行时兼容矩阵（平台/版本）

OS：Linux / macOS（首选）；Windows 建议 WSL。

Python：≥3.10；安装方式：pip install -e .（README 要求） 。

输出格式：jsonl | parquet（README 已示例，默认 parquet） 。

Sink 与后续任务：信号层支持 JSONL/SQLite（与 M2 保持一致） 。

5) CLI 规范（Cursor 可直接照抄）

与原任务勾选项保持一致并补完类型/默认值/映射关系 。

参数	类型	必填	默认	说明	映射
--config	path	否	./config/defaults.yaml	全局配置	读取 harvest 段（ws/rotate/output 等）
--output	path	否	覆盖 harvest.output.base_dir	输出根目录	分区落盘逻辑依赖该根目录
--format	str	否	parquet	`jsonl	parquet`
--rotate.max_rows	int	否	harvest.rotate.max_rows	单文件最大行数	支持批次切割/轮转
--rotate.max_sec	int	否	harvest.rotate.max_sec	轮转时间	与极端流量模式切换兼容（内部有 normal↔extreme）

备注：订单簿写盘需剔除复杂列（bids/asks）已在实现里处理，薄壳不应绕过该逻辑 。

5.1 环境变量（严格/兼容）

严格模式（推荐）：仅允许白名单 ENV 被读取：CVD_SIGMA_FLOOR_K, CVD_WINSOR, W_OFI, W_CVD, FUSION_CAL_K, PAPER_ENABLE, V13_DEV_PATHS；其他参数来自 --config（若读取非白名单将报错） 。

兼容模式（已有实现，供过渡）：可读运行参数（如 EXTREME_ROTATE_SEC / MAX_ROWS_PER_FILE / PARQUET_ROTATE_SEC 等）；该模式下仍保持正常/极端轮转切换与健康监控逻辑 。

6) 业务流（How）

读取 --config 合并 CLI 覆盖，构建采集器。

打开 Binance Futures WS 订阅（aggTrade/bookTicker/depth@100ms 等按配置），激活采集（M1 范畴） 。

行级 DQ（缺字段/滞后剔除）与统一 Row Schema；

写盘：按 date/hour/symbol/kind 路由，定时或条数轮转，失败死信落地（已在实现里处理） 。

CTRL+C/SIGINT：优雅取消任务、flush、退出码 0。

下游接口口径：特征→信号层输入、信号层输出（JSONL 一致口径），避免将路径/命名在薄壳层写死（Schema 参照 README 3.2/3.3） 。

7) 代码样例（最小薄壳）
# mcp/harvest_server/app.py
import argparse, os, sys, logging
from pathlib import Path

def parse_args():
    p = argparse.ArgumentParser("Harvest MCP (thin)")
    p.add_argument("--config", default="./config/defaults.yaml")
    p.add_argument("--output", default=None)
    p.add_argument("--format", default=None, choices=["jsonl","parquet"])
    p.add_argument("--rotate.max_rows", dest="rot_rows", type=int)
    p.add_argument("--rotate.max_sec", dest="rot_sec", type=int)
    return p.parse_args()

def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info({"event":"harvest.start", "args": vars(args)})

    # 延迟导入以便日志格式先就位
    # 使用 run_ws_harvest 便捷函数（与任务卡约定一致）
    # 注意：实际实现中 run_ws_harvest(config=dict, **kwargs) 接受配置字典和关键字参数
    from alpha_core.ingestion import run_ws_harvest
    try:
        # 加载并合并配置（实际实现中需要先加载配置字典）
        config = load_config(args.config)  # 需要实现 load_config 和 merge_config_with_args
        config = merge_config_with_args(config, args)
        
        # 调用 run_ws_harvest（内部会创建 SuccessOFICVDHarvester 实例并运行）
        await run_ws_harvest(
            config=config,  # 传入完整配置字典
            compat_env=True,  # 允许环境变量回退
            symbols=None,  # 从配置中读取
            run_hours=87600,
            output_dir=None  # 从配置中读取
        )
        exitcode = 0
    except KeyboardInterrupt:
        logging.info("harvest.stop: received SIGINT, graceful shutdown")
        exitcode = 0
    except Exception as e:
        logging.exception("harvest.failed")
        exitcode = 1

    logging.info({"event":"harvest.exit", "code": exitcode})
    sys.exit(exitcode)

if __name__ == "__main__":
    main()

**说明**：实际实现使用 `run_ws_harvest(config=dict, **kwargs)`，该函数内部会创建 `SuccessOFICVDHarvester` 实例并调用 `run()`。这与直接使用 `SuccessOFICVDHarvester().run()` 语义等价，但更符合任务卡的函数式调用约定。


CLI 名称与 README M1 示例命令匹配（python -m mcp.harvest_server.app --config ... --output ... --format ... --rotate.max_rows ... --rotate.max_sec ...） 。

**注意**: 
- **Linux/macOS**: 使用反斜杠 `\` 作为续行符
- **Windows PowerShell**: 使用反引号 `` ` `` 作为续行符，或使用单行命令，或使用 `scripts/harvest_local.ps1` 脚本

7.1 本地一键脚本
# scripts/harvest_local.sh
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"
# 1) 安装为可编辑包（第一次/环境更新时）
# pip install -e .

# 2) 启动 HARVEST（参数可按需覆盖）
python -m mcp.harvest_server.app \
  --config ./config/defaults.yaml \
  --output ./data/ofi_cvd \
  --format parquet \
  --rotate.max_rows 200000 \
  --rotate.max_sec 60

8) 验收标准（DoD）

 安装即跑：空环境 pip install -e . 后，bash scripts/harvest_local.sh 可成功连接并开始写盘（README M1 对齐） 。

 路径正确：出现 .../date=YYYY-MM-DD/hour=HH/symbol=<sym>/kind=<kind>/part-*.parquet；订单簿复杂列被剔除，单/批写盘逻辑正确 。

 轮转生效：行数/时间阈值达到时发生轮转，日志可见轮转事件；极端流量时切换为更短轮转（extreme） 。

 优雅退出：CTRL+C 触发清理并退出码为 0（日志含 start/exit 事件）。

 README 一致：README 的命令可以原样照抄运行，无额外参数/环境要求（如需改动 README，需本任务一并提交） 。

9) 自测清单（Smoke）

 --help 输出含 5 个核心参数并解释默认/覆盖关系（与表一致）。

 覆盖组合：仅 config；config + output；config + format=jsonl；+rotate 两项组合。

 Windows/WSL：路径带空格、Ctrl+C 正常。

 多 symbol：路径分流正确；不同 kind（prices/trades/orderbook 等）各自分区正确（实现按 kind 分流） 。

 失败回退：写盘异常落入死信（实现已兜底） 。

10) 一致性与契约（Contract）

数据契约：下游 CORE_ALGO 的输入/输出样例口径见 README（3.2 输入；3.3 输出），Harvest 不得擅自改字段名/语义 。

任务索引一致：TASK-03 位置与标题保持 README/TASK_INDEX 对齐（M1） 。

MCP 定位：薄壳仅做 I/O 与调用，算法沉淀在 src/alpha_core/*（README 约定） 。

11) 常见坑与防御

Parquet 写入失败（复杂列）：依赖 harvester 端已删除 bids/asks 等复杂列，薄壳勿绕过流程 。

极端流量：进入 extreme 模式时轮转间隔自动缩短（日志有提示），不用在薄壳强行覆盖 。

ENV 白名单：严格模式下只有指定 ENV 可读，其他参数请走 config 文件（否则抛错） 。

12) 提交要求（Definition of Ready）

 新增文件与可执行权限（harvest_local.sh）

 README M1 命令手试通过（粘贴即跑） 。

 日志包含 {event:"harvest.start"} 与 {event:"harvest.exit"} 便于 Orchestrator 与可观测性对接。

## 完成状态

**✅ 已完成** - 2025-11-06

### 交付物清单

#### 1. 核心代码文件

- ✅ **`mcp/harvest_server/app.py`** - MCP 薄壳实现
  - ✅ 支持所有 5 个核心参数：`--config`, `--output`, `--format`, `--rotate.max_rows`, `--rotate.max_sec`
  - ✅ 参数解析完整，包含类型验证和默认值
  - ✅ 配置加载和合并逻辑（命令行参数覆盖配置文件）
  - ✅ 优雅处理 CTRL+C/SIGINT，退出码为 0
  - ✅ 日志包含 `{event:"harvest.start"}` 和 `{event:"harvest.exit"}`
  - ✅ 支持未安装包模式（自动添加 `src` 到 Python 路径）
  - ✅ 支持 symbols 配置验证和默认值设置（6 个交易对）

#### 2. 启动脚本

- ✅ **`scripts/harvest_local.sh`** - Bash 一键启动脚本
  - ✅ 支持环境变量覆盖参数
  - ✅ 包含错误处理和友好的输出信息
  - ✅ 参数验证和默认值设置
  - ✅ 退出码正确传递

- ✅ **`scripts/harvest_local.ps1`** - PowerShell 一键启动脚本（Windows）
  - ✅ 支持 Windows PowerShell 语法
  - ✅ 支持环境变量覆盖参数
  - ✅ 包含错误处理和友好的输出信息
  - ✅ 与 Bash 脚本功能一致

#### 3. 配置映射逻辑

- ✅ 正确映射任务卡参数到 harvester 期望的配置结构
  - ✅ `harvest.rotate.max_rows` → `files.max_rows_per_file`
  - ✅ `harvest.rotate.max_sec` → `files.parquet_rotate_sec`
- ✅ 路径处理逻辑（自动去除 `./deploy/` 前缀，避免路径重复）
- ✅ 输出目录和格式覆盖逻辑

#### 4. 文档更新

- ✅ **README.md** - M1 示例命令已对齐
  - ✅ 包含 Linux/macOS Bash 命令示例
  - ✅ 包含 Windows PowerShell 命令示例（单行和多行）
  - ✅ 包含脚本启动方式
  - ✅ 命令可以直接复制运行

### 验收标准验证（DoD）

#### ✅ 安装即跑
- 空环境 `pip install -e .` 后，`bash scripts/harvest_local.sh` 可成功连接并开始写盘
- 支持未安装包模式，自动添加 `src` 到 Python 路径
- README 命令可以直接复制运行

#### ✅ 路径正确
- 路径格式：`.../date=YYYY-MM-DD/hour=HH/symbol=<sym>/kind=<kind>/part-*.parquet`
- 订单簿复杂列（bids/asks）已在 harvester 中剔除
- 单/批写盘逻辑正确（使用 PathBuilder 统一路径管理）

#### ✅ 轮转生效
- 行数阈值（`--rotate.max_rows`）达到时发生轮转
- 时间阈值（`--rotate.max_sec`）达到时发生轮转
- 日志可见轮转事件（harvester 内部实现）
- 极端流量时自动切换为更短轮转（extreme 模式，harvester 内部实现）

#### ✅ 优雅退出
- CTRL+C 触发清理并退出码为 0
- 日志包含 `{event:"harvest.start"}` 和 `{event:"harvest.exit"}`
- SIGINT 处理正确

#### ✅ README 一致
- README 的命令可以原样照抄运行
- 无额外参数/环境要求
- 提供 Windows 和 Linux/macOS 两种格式的命令示例

### 自测清单验证（Smoke）

- ✅ `--help` 输出含 5 个核心参数并解释默认/覆盖关系
- ✅ 覆盖组合测试：
  - 仅 config ✓
  - config + output ✓
  - config + format=jsonl ✓
  - +rotate 两项组合 ✓
- ✅ Windows/WSL：路径带空格、Ctrl+C 正常
- ✅ 多 symbol：路径分流正确（6 个交易对同时采集）
- ✅ 不同 kind（prices/trades/orderbook/ofi/cvd/fusion/events/features）各自分区正确
- ✅ 失败回退：写盘异常落入死信（harvester 内部实现）

### 技术实现细节

#### 参数解析
- 使用 `argparse` 标准库
- 参数类型验证（`choices` 限制 format 选项）
- 参数说明和示例完整

#### 配置合并
- 支持命令行参数覆盖配置文件
- 路径处理逻辑（相对路径转绝对路径）
- 自动设置默认 symbols（6 个交易对）

#### 错误处理
- 配置文件不存在：错误提示
- Python 环境检查：脚本中包含检查逻辑
- 异常捕获和日志记录

#### 日志规范
- 启动事件：`{"event": "harvest.start", "args": {...}}`
- 退出事件：`{"event": "harvest.exit", "code": 0}`
- 日志格式统一：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`

### 审查报告修复（2025-11-06）

根据审查报告，已完成以下修复：

1. **✅ 调用点统一**：已修改为使用 `run_ws_harvest()` 函数，与任务卡示例一致
   - 从 `SuccessOFICVDHarvester().run()` 改为 `run_ws_harvest(config=dict, **kwargs)`
   - 更新了任务卡代码示例说明，明确两种调用方式的等价性

2. **✅ 输出目录统一**：脚本和 README 统一使用 `./deploy/data/ofi_cvd`
   - `scripts/harvest_local.sh` 已更新注释说明
   - `scripts/harvest_local.ps1` 已使用统一路径

3. **✅ 路径处理改进**：使用 pathlib.Path 规范化处理
   - 改进了 `merge_config_with_args` 中的路径处理逻辑
   - 使用 POSIX 路径格式统一处理 Windows/Linux 路径
   - 支持 `./deploy/`、`deploy/`、`deploy\` 等多种格式

4. **✅ 任务卡说明更新**：补充了调用点选择说明
   - 在代码样例部分添加了实际实现的说明
   - 明确了 `run_ws_harvest` 与 `SuccessOFICVDHarvester().run()` 的等价关系

### 已知问题和限制

1. **编码问题**：Windows PowerShell 输出中文时可能有编码问题（但不影响功能）
2. **包安装**：推荐使用 `pip install -e .`，但未安装时也能运行（自动添加路径）

### 后续优化建议

1. **可维护性增强**（非必须）：
   - 为 `merge_config_with_args` 增加最小单测（参数覆盖、路径归一、双写映射）
   - CLI 增加 `--symbols` 直传（目前通过配置与默认 6 个交易对兜底，功能已足够）
   - 在 README M1 增加"常见错误排查（PyYAML 未安装、权限、路径）"段落

2. **功能扩展**（未来）：
   - 可以添加更详细的健康检查端点（未来 MCP 协议扩展）
   - 可以添加配置文件验证（YAML schema 检查）
   - 可以添加更详细的启动参数验证

**完成日期**: 2025-11-06  
**最后验证**: 2025-11-06  
**审查修复**: 2025-11-06