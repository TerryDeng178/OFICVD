#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试：STAGE-2搜索空间过滤BUG修复"""
import unittest
import sys
import yaml
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.alpha_core.report.optimizer import ParameterOptimizer


class TestSearchSpaceFilter(unittest.TestCase):
    """测试搜索空间过滤逻辑"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_search_space_filter")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建测试基线配置
        self.base_config = {
            "signal": {
                "weak_signal_threshold": 0.76,
                "consistency_min": 0.53,
                "dedupe_ms": 8000,
                "min_consecutive_same_dir": 3
            },
            "execution": {
                "cooldown_ms": 500
            }
        }
        
        self.config_path = self.test_dir / "test_baseline.yaml"
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_config, f)
    
    def test_filter_note_field(self):
        """测试过滤note字段"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4, 5],
            "execution.cooldown_ms": [500, 800, 1200],
            "signal.dedupe_ms": [8000, 10000],
            "note": "F3: 阶梯试连击/冷却/去重，抑制亏损翻手",  # 应该被过滤
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        # 验证note字段被过滤
        self.assertNotIn("note", optimizer.search_space)
        self.assertIn("signal.min_consecutive_same_dir", optimizer.search_space)
        self.assertIn("execution.cooldown_ms", optimizer.search_space)
        self.assertIn("signal.dedupe_ms", optimizer.search_space)
    
    def test_filter_description_field(self):
        """测试过滤description字段"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4, 5],
            "execution.cooldown_ms": [500, 800],
            "description": "测试描述",  # 应该被过滤
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        # 验证description字段被过滤
        self.assertNotIn("description", optimizer.search_space)
        self.assertEqual(len(optimizer.search_space), 2)
    
    def test_filter_target_field(self):
        """测试过滤target字段"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4],
            "target": "胜率≥45%",  # 应该被过滤
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        # 验证target字段被过滤
        self.assertNotIn("target", optimizer.search_space)
        self.assertEqual(len(optimizer.search_space), 1)
    
    def test_filter_multiple_metadata_fields(self):
        """测试过滤多个元数据字段"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4, 5],
            "execution.cooldown_ms": [500, 800, 1200],
            "signal.dedupe_ms": [8000, 10000],
            "note": "F3: 阶梯试连击/冷却/去重",
            "description": "F3组：反向防抖 & 连击/冷却联合",
            "target": "胜率≥45% 且 avg_pnl_per_trade由负转正（>0）",
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        # 验证所有元数据字段被过滤
        self.assertNotIn("note", optimizer.search_space)
        self.assertNotIn("description", optimizer.search_space)
        self.assertNotIn("target", optimizer.search_space)
        
        # 验证参数字段保留
        self.assertEqual(len(optimizer.search_space), 3)
        self.assertIn("signal.min_consecutive_same_dir", optimizer.search_space)
        self.assertIn("execution.cooldown_ms", optimizer.search_space)
        self.assertIn("signal.dedupe_ms", optimizer.search_space)
    
    def test_generate_trials_with_filtered_space(self):
        """测试使用过滤后的搜索空间生成trial"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4, 5],
            "execution.cooldown_ms": [500, 800, 1200],
            "signal.dedupe_ms": [8000, 10000],
            "note": "F3: 阶梯试连击/冷却/去重，抑制亏损翻手",
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证生成了正确的组合数：3×3×2 = 18
        self.assertEqual(len(trials), 18)
        
        # 验证参数值的变化
        min_consecutive_values = set()
        cooldown_values = set()
        dedupe_values = set()
        
        for trial in trials:
            config = trial["config"]
            min_consecutive_values.add(config.get("signal", {}).get("min_consecutive_same_dir"))
            cooldown_values.add(config.get("execution", {}).get("cooldown_ms"))
            dedupe_values.add(config.get("signal", {}).get("dedupe_ms"))
        
        # 验证所有值都被使用
        self.assertEqual(min_consecutive_values, {3, 4, 5})
        self.assertEqual(cooldown_values, {500, 800, 1200})
        self.assertEqual(dedupe_values, {8000, 10000})
    
    def test_generate_trials_unique_combinations(self):
        """测试生成的trial组合是唯一的"""
        search_space = {
            "signal.min_consecutive_same_dir": [3, 4],
            "execution.cooldown_ms": [500, 800],
            "note": "测试note",
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证生成了4个组合
        self.assertEqual(len(trials), 4)
        
        # 验证每个组合的参数组合是唯一的
        param_combinations = set()
        for trial in trials:
            config = trial["config"]
            combo = (
                config.get("signal", {}).get("min_consecutive_same_dir"),
                config.get("execution", {}).get("cooldown_ms"),
            )
            param_combinations.add(combo)
        
        # 验证所有组合都是唯一的
        self.assertEqual(len(param_combinations), 4)
        self.assertEqual(param_combinations, {(3, 500), (3, 800), (4, 500), (4, 800)})
    
    def test_load_yaml_search_space_with_note(self):
        """测试从YAML文件加载包含note字段的搜索空间"""
        # 创建测试搜索空间YAML文件
        search_space_yaml = {
            "stage": 2,
            "description": "F3组：反向防抖 & 连击/冷却联合",
            "target": "胜率≥45%",
            "search_space": {
                "signal.min_consecutive_same_dir": [3, 4, 5],
                "execution.cooldown_ms": [500, 800, 1200],
                "signal.dedupe_ms": [8000, 10000],
                "note": "F3: 阶梯试连击/冷却/去重，抑制亏损翻手",
            }
        }
        
        search_space_path = self.test_dir / "test_search_space.yaml"
        with open(search_space_path, "w", encoding="utf-8") as f:
            yaml.dump(search_space_yaml, f)
        
        # 加载搜索空间（模拟run_stage2_optimization.py的逻辑）
        with open(search_space_path, "r", encoding="utf-8") as f:
            search_space_data = yaml.safe_load(f)
        
        search_space = search_space_data.get("search_space", {})
        # 过滤掉非参数字段
        search_space = {k: v for k, v in search_space.items() if k not in ("note", "description", "target")}
        
        # 验证过滤后的搜索空间
        self.assertNotIn("note", search_space)
        self.assertNotIn("description", search_space)
        self.assertNotIn("target", search_space)
        self.assertEqual(len(search_space), 3)
        
        # 使用过滤后的搜索空间创建optimizer
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        trials = optimizer.generate_trials(method="grid")
        
        # 验证生成了18个组合
        self.assertEqual(len(trials), 18)


class TestSearchSpaceFilterRegression(unittest.TestCase):
    """回归测试：确保修复不会破坏现有功能"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_dir = Path("runtime/test_search_space_filter_regression")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_config = {
            "signal": {"weak_signal_threshold": 0.76},
            "components": {"fusion": {"w_ofi": 0.6, "w_cvd": 0.4}},
        }
        
        self.config_path = self.test_dir / "test_baseline.yaml"
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.base_config, f)
    
    def test_no_metadata_fields(self):
        """测试没有元数据字段的搜索空间（向后兼容）"""
        search_space = {
            "signal.weak_signal_threshold": [0.76, 0.77, 0.78],
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        # 验证搜索空间正常
        self.assertEqual(len(optimizer.search_space), 1)
        self.assertIn("signal.weak_signal_threshold", optimizer.search_space)
        
        trials = optimizer.generate_trials(method="grid")
        self.assertEqual(len(trials), 3)
    
    def test_only_metadata_fields(self):
        """测试只有元数据字段的搜索空间（边界情况）"""
        search_space = {
            "note": "只有note字段",
            "description": "只有description字段",
        }
        
        optimizer = ParameterOptimizer(
            base_config_path=str(self.config_path),
            search_space=search_space,
            output_dir=self.test_dir,
        )
        
        # 验证所有字段被过滤，搜索空间为空
        self.assertEqual(len(optimizer.search_space), 0)
        
        # 生成trial应该只有基线配置
        trials = optimizer.generate_trials(method="grid")
        self.assertEqual(len(trials), 1)  # 只有一个基线配置


if __name__ == "__main__":
    unittest.main()


