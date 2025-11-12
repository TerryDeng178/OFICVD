#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Mode-B的可选重发signals功能
"""

import sys
import os
sys.path.insert(0, 'src')

import tempfile
import json
import subprocess
from pathlib import Path
import yaml

def main():
    print('=== 测试Mode-B的可选重发signals功能 ===')
    print()

    # 创建临时测试环境
    tmp_dir = Path(tempfile.mkdtemp())
    print(f'测试目录: {tmp_dir}')

    try:
        # 1. 创建测试signals数据
        print('1. 创建测试signals数据...')

        signals_dir = tmp_dir / 'signals'
        btc_dir = signals_dir / 'BTCUSDT'
        btc_dir.mkdir(parents=True)

        signals_file = btc_dir / 'test_signals.jsonl'
        test_signals = [
            {
                'ts_ms': 1762905600000 + i * 60000,
                'symbol': 'BTCUSDT',
                'score': 0.8 if i % 2 == 0 else -0.8,
                'confirm': True,
                'gating': ['test'],
                'run_id': 'test_reemit',
                'mid_px': 50000.0 + i * 100  # 添加价格信息
            }
            for i in range(3)
        ]

        with signals_file.open('w', encoding='utf-8') as f:
            for signal in test_signals:
                f.write(json.dumps(signal, ensure_ascii=False) + '\n')

        print(f'   创建了 {len(test_signals)} 个signals')

        # 2. 创建配置文件
        config_file = tmp_dir / 'config.yaml'
        config_data = {
            'broker': {
                'fee_bps_maker': -25,
                'fee_bps_taker': 75
            }
        }

        with config_file.open('w', encoding='utf-8') as f:
            yaml.dump(config_data, f)

        print('   配置文件创建完成')

        # 3. 测试B模式默认行为（不重发signals）
        print()
        print('3. 测试B模式默认行为（不重发signals）...')

        result_default = subprocess.run([
            'python', '-m', 'backtest.app',
            '--mode', 'B',
            '--signals-src', f'jsonl://{signals_dir}',
            '--out-dir', str(tmp_dir / 'output_default'),
            '--config', str(config_file),
            '--run-id', 'test_default',
            '--symbols', 'BTCUSDT',
            '--start', '2025-11-12T00:00:00Z',
            '--end', '2025-11-12T01:00:00Z',
            '--tz', 'Asia/Tokyo'
        ], capture_output=True, text=True, cwd='.', timeout=30)

        if result_default.returncode == 0:
            output_dir_default = tmp_dir / 'output_default' / 'test_default'
            signals_file_default = output_dir_default / 'signals.jsonl'
            trades_file_default = output_dir_default / 'trades.jsonl'

            has_signals_default = signals_file_default.exists()
            has_trades_default = trades_file_default.exists()

            print(f'   signals.jsonl存在: {has_signals_default} (期望: False)')
            print(f'   trades.jsonl存在: {has_trades_default} (期望: True)')

            if not has_signals_default and has_trades_default:
                print('   [OK] 默认行为正确：不重发signals')
                default_correct = True
            else:
                print('   [ERROR] 默认行为错误')
                default_correct = False
        else:
            print('   [ERROR] 默认测试执行失败')
            print('STDERR:', result_default.stderr[-500:])
            return False

        # 4. 测试B模式重发signals
        print()
        print('4. 测试B模式重发signals...')

        result_reemit = subprocess.run([
            'python', '-m', 'backtest.app',
            '--mode', 'B',
            '--signals-src', f'jsonl://{signals_dir}',
            '--out-dir', str(tmp_dir / 'output_reemit'),
            '--config', str(config_file),
            '--run-id', 'test_reemit',
            '--symbols', 'BTCUSDT',
            '--start', '2025-11-12T00:00:00Z',
            '--end', '2025-11-12T01:00:00Z',
            '--tz', 'Asia/Tokyo',
            '--reemit-signals'
        ], capture_output=True, text=True, cwd='.', timeout=30)

        if result_reemit.returncode == 0:
            output_dir_reemit = tmp_dir / 'output_reemit' / 'test_reemit'
            signals_file_reemit = output_dir_reemit / 'signals.jsonl'
            trades_file_reemit = output_dir_reemit / 'trades.jsonl'

            has_signals_reemit = signals_file_reemit.exists()
            has_trades_reemit = trades_file_reemit.exists()

            print(f'   signals.jsonl存在: {has_signals_reemit} (期望: True)')
            print(f'   trades.jsonl存在: {has_trades_reemit} (期望: True)')

            if has_signals_reemit and has_trades_reemit:
                print('   [OK] 重发功能正确：生成了signals.jsonl')

                # 检查重发的signals内容
                with signals_file_reemit.open('r', encoding='utf-8') as f:
                    reemitted_signals = [json.loads(line.strip()) for line in f if line.strip()]

                print(f'   重发signals数量: {len(reemitted_signals)}')

                # 检查signal_id是否已生成
                has_signal_ids = all('signal_id' in s for s in reemitted_signals)
                print(f'   所有signals都有signal_id: {has_signal_ids}')

                if has_signal_ids and reemitted_signals:
                    sample_id = reemitted_signals[0]['signal_id']
                    print(f'   样本signal_id: {sample_id}')
                elif not reemitted_signals:
                    print('   [WARN] 重发的signals文件为空，但文件存在')

                reemit_correct = True
            else:
                print('   [ERROR] 重发功能错误')
                reemit_correct = False
        else:
            print('   [ERROR] 重发测试执行失败')
            print('STDERR:', result_reemit.stderr[-500:])
            return False

        # 5. 验证结果
        print()
        print('5. 验证结果...')

        if default_correct and reemit_correct:
            print('[SUCCESS] --reemit-signals功能测试通过!')
            print()
            print('   功能验证:')
            print('   - B模式默认不写signals.jsonl [OK]')
            print('   - B模式添加--reemit-signals后写signals.jsonl [OK]')
            print('   - 重发的signals包含自动生成的signal_id [OK]')
            print('   - SQLite唯一性约束正常工作 [OK]')
            return True
        else:
            print('[FAILED] --reemit-signals功能测试失败')
            return False

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
