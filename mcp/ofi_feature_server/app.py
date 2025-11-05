# -*- coding: utf-8 -*-
"""
OFI Feature MCP Server

特征计算服务器：调用 alpha_core 组件计算 OFI/CVD/FUSION/DIVERGENCE
"""

# TODO: 实现 Feature MCP 服务器
# - 输入：统一 Row Schema 批次 rows[]
# - 处理：调用 RealOFI/RealCVD，经 OFI_CVD_Fusion 与 DivergenceDetector
# - 输出：{z_ofi, z_cvd, fusion:{side,consistency,...}, divergence:{...}, fp}

from alpha_core.microstructure.ofi import RealOFICalculator, OFIConfig
from alpha_core.microstructure.cvd import RealCVDCalculator, CVDConfig
from alpha_core.microstructure.fusion import OFI_CVD_Fusion, OFICVDFusionConfig
from alpha_core.microstructure.divergence import DivergenceDetector, DivergenceConfig

