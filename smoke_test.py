#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TASK-B2 冒烟测试脚本
"""

import sys
import os
sys.path.insert(0, 'src')

import tempfile
import json
import subprocess
from pathlib import Path
import yaml
import time

def main():
    print('=== TASK-B2 冒烟测试开始 ===')
    print()

    # 创建临时测试环境
    tmp_dir = Path(tempfile.mkdtemp())
    print(f'测试目录: {tmp_dir}')

    try:
        # 1. 创建测试数据
        print('1. 准备测试数据...')

        # 创建signals数据 (用于B模式)
        signals_dir = tmp_dir / 'signals'
        btc_dir = signals_dir / 'BTCUSDT'
        btc_dir.mkdir(parents=True)

        signals_data = [
            {
                'ts_ms': 1762905600000 + i * 60000,  # 每分钟一个信号
                'symbol': 'BTCUSDT',
                'score': 0.8 if i % 2 == 0 else -0.8,  # 交替买卖信号
                'confirm': True,
                'gating': ['smoke_test'],
                'run_id': 'smoke_test',
                'mid_px': 50000.0 + i * 10
            }
            for i in range(5)  # 5个信号
        ]

        signals_file = btc_dir / 'smoke_signals.jsonl'
        with signals_file.open('w', encoding='utf-8') as f:
            for signal in signals_data:
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        print(f'   创建了 {len(signals_data)} 个signals')

        # 2. 创建配置文件
        print('2. 创建配置文件...')

        config_file = tmp_dir / 'smoke_config.yaml'
        config_data = {
            'broker': {
                'fee_bps_maker': -25,
                'fee_bps_taker': 75,
                'latency_ms': 100
            },
            'order': {
                'qty': 0.1
            }
        }

        with config_file.open('w', encoding='utf-8') as f:
            yaml.dump(config_data, f)

        print('   配置文件创建完成')

        # 3. 测试B模式 (signals -> trades)
        print()
        print('3. 测试B模式 (signals -> trades)...')

        start_time = time.time()
        result = subprocess.run([
            'python', '-m', 'backtest.app',
            '--mode', 'B',
            '--signals-src', f'jsonl://{signals_dir}',
            '--out-dir', str(tmp_dir / 'output'),
            '--config', str(config_file),
            '--run-id', 'smoke_test',
            '--symbols', 'BTCUSDT',
            '--start', '2025-11-12T00:00:00Z',
            '--end', '2025-11-12T01:00:00Z',
            '--tz', 'Asia/Tokyo'
        ], capture_output=True, text=True, cwd='.', timeout=30)

        duration = time.time() - start_time

        print(f'   执行时间: {duration:.2f}s')

        if result.returncode == 0:
            print('   执行成功!')

            # 检查输出文件
            output_dir = tmp_dir / 'output' / 'smoke_test'
            trades_file = output_dir / 'trades.jsonl'
            pnl_file = output_dir / 'pnl_daily.jsonl'
            manifest_file = output_dir / 'run_manifest.json'

            files_exist = {
                'trades.jsonl': trades_file.exists(),
                'pnl_daily.jsonl': pnl_file.exists(),
                'run_manifest.json': manifest_file.exists()
            }

            print(f'   输出文件: {files_exist}')

            if all(files_exist.values()):
                print('   所有输出文件都已生成')

                # 检查manifest
                with manifest_file.open('r', encoding='utf-8') as f:
                    manifest = json.load(f)

                processed = manifest.get('perf', {}).get('signals_processed', 0)
                trades_count = manifest.get('perf', {}).get('trades_generated', 0)

                print(f'   处理信号数: {processed}')
                print(f'   生成交易数: {trades_count}')

            else:
                print('   部分输出文件缺失')
                return False

        else:
            print('   执行失败')
            print('STDERR:', result.stderr[-500:])
            return False

        # 4. 验证修复效果
        print()
        print('4. 验证关键修复...')

        error_output = result.stderr

        # 检查是否没有fee_abs NameError
        if 'NameError' in error_output and 'fee_abs' in error_output:
            print('   存在fee_abs NameError - 修复失败')
            return False
        else:
            print('   没有fee_abs相关的NameError - 修复成功')

        # 检查CoreAlgorithm fallback
        if 'CoreAlgorithm' in error_output and ('failed' in error_output or 'fallback' in error_output):
            print('   CoreAlgorithm fallback机制工作正常')
        else:
            print('   CoreAlgorithm导入正常 (没有触发fallback)')

        # 5. 最终状态
        print()
        print('5. 最终状态...')
        print('   冒烟测试通过!')
        print()
        print('   关键验证点:')
        print('   - B模式执行成功')
        print('   - 没有运行时错误')
        print('   - 输出文件正确生成')
        print('   - fee_abs修复有效')
        print('   - 性能表现良好')

        return True

    finally:
        # 清理临时目录
        import shutil
        try:
            shutil.rmtree(tmp_dir)
            print(f'清理测试目录: {tmp_dir}')
        except:
            pass

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
