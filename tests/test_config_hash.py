# -*- coding: utf-8 -*-
"""Config Hash Tests

测试 config_hash 计算功能
"""

import pytest

from src.alpha_core.signals.config_hash import calculate_config_hash, extract_core_config


class TestConfigHash:
    """Config Hash 测试"""
    
    def test_calculate_config_hash(self):
        """测试 config_hash 计算"""
        core_config = {
            "expiry_ms": 60000,
            "cooldown_ms": 30000,
            "allow_quiet": False,
            "gating": {
                "ofi_z": 1.5,
                "cvd_z": 1.2,
            },
            "threshold": {
                "entry": {
                    "trend": 1.8,
                    "revert": 2.2,
                },
            },
        }
        
        hash1 = calculate_config_hash(core_config)
        hash2 = calculate_config_hash(core_config)
        
        # 相同配置应该产生相同哈希
        assert hash1 == hash2
        # TASK-A4 修复4: config_hash 长度从 8 提升到 12（降低碰撞概率）
        assert len(hash1) == 12  # 前 12 位
    
    def test_calculate_config_hash_different_configs(self):
        """测试不同配置产生不同哈希"""
        config1 = {"expiry_ms": 60000}
        config2 = {"expiry_ms": 30000}
        
        hash1 = calculate_config_hash(config1)
        hash2 = calculate_config_hash(config2)
        
        assert hash1 != hash2
    
    def test_calculate_config_hash_stable_serialization(self):
        """测试稳定序列化（键顺序不影响哈希）"""
        config1 = {
            "a": 1,
            "b": 2,
            "c": 3,
        }
        config2 = {
            "c": 3,
            "a": 1,
            "b": 2,
        }
        
        hash1 = calculate_config_hash(config1)
        hash2 = calculate_config_hash(config2)
        
        # 键顺序不同，但内容相同，应该产生相同哈希
        assert hash1 == hash2

    def test_config_hash_changes_with_rules_and_features_versions(self):
        """rules_ver 与 features_ver 改变时 config_hash 应变化"""
        base = {
            "expiry_ms": 60000,
            "rules_ver": "core v1",
            "features_ver": "ofi/cvd v3",
        }
        hash_base = calculate_config_hash(base)
        updated = dict(base)
        updated["rules_ver"] = "core v2"
        hash_updated = calculate_config_hash(updated)
        assert hash_base != hash_updated

        updated_features = dict(base)
        updated_features["features_ver"] = "ofi/cvd v4"
        hash_features = calculate_config_hash(updated_features)
        assert hash_base != hash_features

    def test_config_hash_changes_when_env_like_override_applied(self):
        """模拟环境变量覆盖（如 CORE_COOLDOWN_MS），哈希需变化"""
        config_a = {"cooldown_ms": 30000, "expiry_ms": 60000}
        config_b = {"cooldown_ms": 45000, "expiry_ms": 60000}
        hash_a = calculate_config_hash(config_a)
        hash_b = calculate_config_hash(config_b)
        assert hash_a != hash_b

    def test_config_hash_has_stable_length_and_format(self):
        """hash 长度固定 12 且为十六进制字符串"""
        config = {"expiry_ms": 12345}
        hash_value = calculate_config_hash(config)
        assert len(hash_value) == 12
        int(hash_value, 16)  # 应可转换为十六进制整数
    
    def test_extract_core_config(self):
        """测试提取 core.* 配置"""
        full_config = {
            "core": {
                "expiry_ms": 60000,
                "cooldown_ms": 30000,
                "gating": {
                    "ofi_z": 1.5,
                },
            },
            "other": {
                "key": "value",
            },
        }
        
        core_config = extract_core_config(full_config)
        
        assert "expiry_ms" in core_config
        assert core_config["expiry_ms"] == 60000
        assert "other" not in core_config
    
    def test_extract_core_config_no_core_key(self):
        """测试提取 core.* 配置（没有 core 键）"""
        full_config = {
            "expiry_ms": 60000,
            "cooldown_ms": 30000,
            "allow_quiet": False,
        }
        
        core_config = extract_core_config(full_config)
        
        assert "expiry_ms" in core_config
        assert core_config["expiry_ms"] == 60000

