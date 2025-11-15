import math
import pytest
from unittest.mock import Mock, patch

from alpha_core.signals.core_algo import CoreAlgorithm


class TestConsistencyCalculation:
    """测试CoreAlgorithm._calculate_consistency_with_fusion方法"""

    def test_consistency_perfect_alignment(self):
        """测试完全一致的情况 (z_ofi=1, z_cvd=1)"""
        algo = CoreAlgorithm({})
        row = {"z_ofi": 1.0, "z_cvd": 1.0}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == pytest.approx(1.0)

    def test_consistency_half_alignment(self):
        """测试一半一致的情况 (z_ofi=1, z_cvd=0.5)"""
        algo = CoreAlgorithm({})
        row = {"z_ofi": 1.0, "z_cvd": 0.5}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == pytest.approx(0.5)

    def test_consistency_opposite_direction(self):
        """测试方向相反的情况 (z_ofi=1, z_cvd=-1)"""
        algo = CoreAlgorithm({})
        row = {"z_ofi": 1.0, "z_cvd": -1.0}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 0.0

    def test_consistency_zero_values(self):
        """测试零值情况"""
        algo = CoreAlgorithm({})
        row = {"z_ofi": 0.0, "z_cvd": 0.0}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 0.0

    def test_consistency_missing_values(self):
        """测试缺失值情况"""
        algo = CoreAlgorithm({})
        row = {"z_ofi": None, "z_cvd": 1.0}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 0.0

    def test_consistency_with_fusion_engine(self):
        """测试使用Fusion引擎的情况"""
        algo = CoreAlgorithm({})

        # Mock fusion engine
        mock_engine = Mock()
        mock_engine.update.return_value = {'consistency': 0.75}
        algo._fusion_engine = mock_engine

        row = {"z_ofi": 1.0, "z_cvd": 1.0, "ts_ms": 1000000, "mid": 50000.0, "lag_sec": 0.1}

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 0.75

        # Verify fusion engine was called
        mock_engine.update.assert_called_once()

    def test_consistency_fusion_engine_failure(self):
        """测试Fusion引擎失败时的fallback"""
        algo = CoreAlgorithm({})

        # Mock fusion engine to raise exception
        mock_engine = Mock()
        mock_engine.update.side_effect = Exception("Fusion engine error")
        algo._fusion_engine = mock_engine

        row = {"z_ofi": 1.0, "z_cvd": 1.0}

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 1.0  # Fallback calculation

    def test_consistency_fusion_engine_invalid_result(self):
        """测试Fusion引擎返回无效结果时的fallback"""
        algo = CoreAlgorithm({})

        # Mock fusion engine to return invalid result
        mock_engine = Mock()
        mock_engine.update.return_value = {'invalid_key': 'invalid_value'}
        algo._fusion_engine = mock_engine

        row = {"z_ofi": 1.0, "z_cvd": 1.0}

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 1.0  # Fallback calculation

    def test_consistency_clamping(self):
        """测试consistency值的clamp (虽然理论上不应该发生)"""
        algo = CoreAlgorithm({})

        # Mock fusion engine to return out-of-range value
        mock_engine = Mock()
        mock_engine.update.return_value = {'consistency': 1.5}  # > 1.0
        algo._fusion_engine = mock_engine

        row = {"z_ofi": 1.0, "z_cvd": 1.0}

        result = algo._calculate_consistency_with_fusion(row)
        assert result == 1.0  # Should be clamped

    def test_consistency_alternate_field_names(self):
        """测试备用字段名 (ofi_z, cvd_z)"""
        algo = CoreAlgorithm({})
        row = {"ofi_z": 1.0, "cvd_z": 0.5}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == pytest.approx(0.5)

    @pytest.mark.parametrize("z_ofi,z_cvd,expected", [
        (1.0, 1.0, 1.0),
        (1.0, 0.5, 0.5),
        (2.0, 1.0, 0.5),
        (0.1, 0.1, 1.0),
        (1.0, -1.0, 0.0),
        (-1.0, -1.0, 1.0),
        (0.0, 1.0, 0.0),
    ])
    def test_consistency_parametrized_fallback(self, z_ofi, z_cvd, expected):
        """参数化测试fallback一致性计算"""
        algo = CoreAlgorithm({})
        row = {"z_ofi": z_ofi, "z_cvd": z_cvd}

        # Mock fusion engine to return None (use fallback)
        algo._fusion_engine = None

        result = algo._calculate_consistency_with_fusion(row)
        assert result == pytest.approx(expected)
