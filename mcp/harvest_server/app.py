# -*- coding: utf-8 -*-
"""
HARVEST MCP Server (薄壳)
采集层服务器：使用 alpha_core.ingestion.harvester 实现

本薄壳仅做参数解析与调用核心采集实现，不包含业务逻辑。
"""

import argparse
import asyncio
import os
import sys
import logging
from pathlib import Path
from typing import Optional

# 添加 src 目录到 Python 路径（如果未安装包）
# 这样可以支持两种运行方式：
# 1. 已安装包：pip install -e . （推荐）
# 2. 未安装包：直接运行，自动添加 src 到路径
_APP_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _APP_DIR.parents[1]  # mcp/harvest_server -> mcp -> project_root
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Harvest MCP (薄壳)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m mcp.harvest_server.app --config ./config/defaults.yaml
  python -m mcp.harvest_server.app --config ./config/defaults.yaml --output ./data/ofi_cvd --format parquet
  python -m mcp.harvest_server.app --config ./config/defaults.yaml --rotate.max_rows 200000 --rotate.max_sec 60
        """
    )
    
    # 核心参数
    parser.add_argument(
        "--config",
        type=str,
        default="./config/defaults.yaml",
        help="全局配置文件路径（默认: ./config/defaults.yaml）"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出根目录（覆盖 harvest.output.base_dir，默认: 使用配置中的路径）"
    )
    
    parser.add_argument(
        "--format",
        type=str,
        default=None,
        choices=["jsonl", "parquet"],
        help="输出格式（jsonl/parquet，默认: 使用配置中的格式）"
    )
    
    parser.add_argument(
        "--rotate.max_rows",
        dest="rotate_max_rows",
        type=int,
        default=None,
        help="单文件最大行数（默认: 使用配置中的 harvest.rotate.max_rows）"
    )
    
    parser.add_argument(
        "--rotate.max_sec",
        dest="rotate_max_sec",
        type=int,
        default=None,
        help="轮转时间间隔（秒，默认: 使用配置中的 harvest.rotate.max_sec）"
    )
    
    return parser.parse_args()


def load_config(config_path: str) -> dict:
    """加载 YAML 配置文件"""
    try:
        import yaml
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        logger.info(f"已加载配置文件: {config_path}")
        return config
    except ImportError:
        logger.warning("PyYAML 未安装，使用空配置字典")
        return {}
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {config_path}")
        raise
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        raise


def merge_config_with_args(config: dict, args) -> dict:
    """合并命令行参数到配置中"""
    # 确保 harvest 配置存在
    if 'harvest' not in config:
        config['harvest'] = {}
    
    # 覆盖输出目录（harvester 期望 paths.data_root 或 paths.output_dir）
    if args.output:
        if 'paths' not in config:
            config['paths'] = {}
        
        # 使用 pathlib 规范化处理路径，避免字符串替换的边缘情况
        # 注意：不调用 resolve()，因为相对路径需要保持相对性
        output_path_str = args.output
        
        # 检查是否包含 deploy 前缀（支持多种格式：./deploy/, deploy/, deploy\）
        # 转换为 POSIX 路径格式便于比较（统一处理 Windows/Linux 路径分隔符）
        posix_path = output_path_str.replace('\\', '/')
        
        # 去除 ./deploy/ 或 deploy/ 前缀（harvester 会将其相对于 deploy_root 解析）
        if posix_path.startswith('./deploy/'):
            output_path_str = posix_path.replace('./deploy/', '', 1)
        elif posix_path.startswith('deploy/'):
            output_path_str = posix_path.replace('deploy/', '', 1)
        # 对于绝对路径或没有 deploy 前缀的相对路径，保持原样
        
        config['paths']['output_dir'] = output_path_str
        
        config['paths']['data_root'] = config['paths']['output_dir']  # 同时设置 data_root 作为兼容
        logger.info(f"覆盖输出目录: {config['paths']['output_dir']}")
    
    # 覆盖格式（如果支持，harvester 可能不支持这个参数，但保留在配置中）
    if args.format:
        if 'output' not in config['harvest']:
            config['harvest']['output'] = {}
        config['harvest']['output']['format'] = args.format
        logger.info(f"覆盖输出格式: {args.format}")
    
    # 覆盖轮转参数
    # harvester 期望 files.max_rows_per_file 和 files.parquet_rotate_sec
    # 但任务卡要求 harvest.rotate.max_rows 和 harvest.rotate.max_sec
    # 我们同时设置两者以保持兼容性
    
    # 设置 harvest.rotate（任务卡规范）
    if 'rotate' not in config['harvest']:
        config['harvest']['rotate'] = {}
    
    if args.rotate_max_rows is not None:
        config['harvest']['rotate']['max_rows'] = args.rotate_max_rows
        logger.info(f"覆盖轮转最大行数: {args.rotate_max_rows}")
    
    if args.rotate_max_sec is not None:
        config['harvest']['rotate']['max_sec'] = args.rotate_max_sec
        logger.info(f"覆盖轮转时间间隔: {args.rotate_max_sec}秒")
    
    # 同时设置 harvester 期望的配置结构（files 子树）
    if 'files' not in config:
        config['files'] = {}
    
    if args.rotate_max_rows is not None:
        config['files']['max_rows_per_file'] = args.rotate_max_rows
    
    if args.rotate_max_sec is not None:
        config['files']['parquet_rotate_sec'] = args.rotate_max_sec
    
    return config


async def run_harvest(config: dict):
    """运行采集器"""
    try:
        # 延迟导入以便日志格式先就位
        # 使用 run_ws_harvest 便捷函数，与任务卡示例一致
        from alpha_core.ingestion import run_ws_harvest
        
        # 运行采集（run_ws_harvest 内部会创建 SuccessOFICVDHarvester 实例）
        # 兼容参数：compat_env=True 允许环境变量回退
        await run_ws_harvest(
            config=config,  # 传入完整配置
            compat_env=True,  # 允许环境变量回退（如果配置不完整）
            symbols=None,  # 从配置中读取，如果配置中没有则使用环境变量
            run_hours=87600,  # 默认运行一年（7x24小时）
            output_dir=None  # 从配置中读取，如果配置中有 paths.data_root
        )
        
        return 0
        
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("收到 SIGINT，优雅退出")
        return 0
    except Exception as e:
        logger.exception("采集器运行失败")
        return 1


async def main_async(args):
    """异步主函数"""
    # 记录启动事件
    logger.info({"event": "harvest.start", "args": vars(args)})
    
    # 加载配置
    config_path = Path(args.config)
    if not config_path.is_absolute():
        # 相对于项目根目录
        project_root = Path(__file__).resolve().parents[2]
        config_path = project_root / args.config
    else:
        config_path = Path(args.config)
    
    try:
        config = load_config(str(config_path))
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        return 1
    
    # 验证 symbols 配置
    symbols = config.get('symbols', [])
    if symbols:
        logger.info(f"配置中的交易对数量: {len(symbols)}")
        logger.info(f"交易对列表: {symbols}")
    else:
        logger.warning("配置中未找到 symbols，将使用默认值或环境变量")
        # 如果配置中没有 symbols，设置默认的 6 个交易对
        config['symbols'] = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
        logger.info(f"已设置默认交易对: {config['symbols']}")
    
    # 合并命令行参数
    config = merge_config_with_args(config, args)
    
    # 再次确认 symbols（合并后）
    final_symbols = config.get('symbols', [])
    logger.info(f"最终使用的交易对数量: {len(final_symbols)}")
    logger.info(f"最终交易对列表: {final_symbols}")
    
    # 运行采集器
    exitcode = await run_harvest(config)
    
    # 记录退出事件
    logger.info({"event": "harvest.exit", "code": exitcode})
    
    return exitcode


def main():
    """主函数"""
    args = parse_args()
    
    try:
        # 使用 asyncio.run() 运行异步主函数
        # asyncio.run() 会自动处理事件循环的创建和清理
        exitcode = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        # KeyboardInterrupt 在 asyncio.run() 中会被正确处理
        # 事件循环会优雅关闭，所有任务会被取消
        logger.info("收到 SIGINT，优雅退出")
        exitcode = 0
    except Exception as e:
        logger.exception("程序异常退出")
        exitcode = 1
    
    sys.exit(exitcode)


if __name__ == "__main__":
    main()
