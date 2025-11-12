# -*- coding: utf-8 -*-
"""Error Code Mapping

错误码映射：HTTP状态码、交易所业务码 → AdapterErrorCode
"""

import logging
from typing import Dict, Optional, List, Tuple

from .base_adapter import AdapterErrorCode

logger = logging.getLogger(__name__)


# HTTP 状态码 → AdapterErrorCode 映射
HTTP_STATUS_MAP: Dict[int, str] = {
    400: AdapterErrorCode.E_PARAMS,  # Bad Request
    401: AdapterErrorCode.E_BROKER_REJECT,  # Unauthorized
    403: AdapterErrorCode.E_BROKER_REJECT,  # Forbidden
    404: AdapterErrorCode.E_PARAMS,  # Not Found
    429: AdapterErrorCode.E_RATE_LIMIT,  # Too Many Requests
    418: AdapterErrorCode.E_RATE_LIMIT,  # I'm a teapot (Binance rate limit)
    500: AdapterErrorCode.E_NETWORK,  # Internal Server Error
    502: AdapterErrorCode.E_NETWORK,  # Bad Gateway
    503: AdapterErrorCode.E_NETWORK,  # Service Unavailable
    504: AdapterErrorCode.E_NETWORK,  # Gateway Timeout
}

# Binance 错误码 → AdapterErrorCode 映射
# 参考：https://binance-docs.github.io/apidocs/futures/cn/#error-code
BINANCE_ERROR_MAP: Dict[int, str] = {
    # 参数错误
    -1100: AdapterErrorCode.E_PARAMS,  # Illegal characters
    -1101: AdapterErrorCode.E_PARAMS,  # Too many parameters
    -1102: AdapterErrorCode.E_PARAMS,  # Mandatory parameter missing
    -1103: AdapterErrorCode.E_PARAMS,  # Unknown parameter
    -1104: AdapterErrorCode.E_PARAMS,  # Unsupported parameter
    -1105: AdapterErrorCode.E_PARAMS,  # Parameter is empty
    -1106: AdapterErrorCode.E_PARAMS,  # Parameter not sent
    -1111: AdapterErrorCode.E_PARAMS,  # Invalid precision
    -1112: AdapterErrorCode.E_PARAMS,  # No valid symbol
    -1114: AdapterErrorCode.E_PARAMS,  # Invalid symbol
    -1121: AdapterErrorCode.E_PARAMS,  # Invalid side
    -1125: AdapterErrorCode.E_PARAMS,  # Invalid order type
    -1130: AdapterErrorCode.E_PARAMS,  # Invalid quantity
    
    # 业务拒绝
    -2010: AdapterErrorCode.E_BROKER_REJECT,  # New order rejected
    -2011: AdapterErrorCode.E_BROKER_REJECT,  # Cancel rejected
    -2013: AdapterErrorCode.E_BROKER_REJECT,  # No such order
    -2014: AdapterErrorCode.E_BROKER_REJECT,  # API-key format invalid
    -2015: AdapterErrorCode.E_BROKER_REJECT,  # Invalid API-key, IP, or permissions
    -2019: AdapterErrorCode.E_BROKER_REJECT,  # Margin is insufficient
    -2021: AdapterErrorCode.E_BROKER_REJECT,  # Order would immediately match and take
    
    # 限频
    -1003: AdapterErrorCode.E_RATE_LIMIT,  # Way too many requests
    -1006: AdapterErrorCode.E_RATE_LIMIT,  # Unexpected response
    -1007: AdapterErrorCode.E_RATE_LIMIT,  # Timeout
    
    # 状态冲突
    -2012: AdapterErrorCode.E_STATE_CONFLICT,  # Order does not exist
    -2022: AdapterErrorCode.E_STATE_CONFLICT,  # Reduce only order rejected
    
    # 网络错误
    -1021: AdapterErrorCode.E_NETWORK,  # Timestamp for this request is outside of the recvWindow
    -1022: AdapterErrorCode.E_NETWORK,  # Signature for this request is not valid
}

# 错误消息关键词 → AdapterErrorCode 映射（作为后备）
ERROR_MSG_KEYWORDS: List[Tuple[List[str], str]] = [
    (["timeout", "timed out", "connection"], AdapterErrorCode.E_NETWORK),
    (["rate limit", "too many requests", "429", "418"], AdapterErrorCode.E_RATE_LIMIT),
    (["insufficient", "balance", "margin"], AdapterErrorCode.E_BROKER_REJECT),
    (["invalid", "bad request", "400"], AdapterErrorCode.E_PARAMS),
    (["not found", "404"], AdapterErrorCode.E_PARAMS),
    (["conflict", "already exists", "duplicate"], AdapterErrorCode.E_STATE_CONFLICT),
]


def map_http_status_to_error_code(status_code: int) -> str:
    """映射 HTTP 状态码到 AdapterErrorCode
    
    Args:
        status_code: HTTP 状态码
        
    Returns:
        AdapterErrorCode
    """
    return HTTP_STATUS_MAP.get(status_code, AdapterErrorCode.E_UNKNOWN)


def map_binance_error_to_error_code(error_code: int) -> str:
    """映射 Binance 错误码到 AdapterErrorCode
    
    Args:
        error_code: Binance 错误码
        
    Returns:
        AdapterErrorCode
    """
    return BINANCE_ERROR_MAP.get(error_code, AdapterErrorCode.E_UNKNOWN)


def map_error_message_to_error_code(error_msg: str) -> str:
    """映射错误消息到 AdapterErrorCode（后备方案）
    
    Args:
        error_msg: 错误消息
        
    Returns:
        AdapterErrorCode
    """
    error_msg_lower = error_msg.lower()
    for keywords, error_code in ERROR_MSG_KEYWORDS:
        if any(keyword in error_msg_lower for keyword in keywords):
            return error_code
    return AdapterErrorCode.E_UNKNOWN


def map_exception_to_error_code(exception: Exception, http_status: Optional[int] = None) -> str:
    """映射异常到 AdapterErrorCode
    
    Args:
        exception: 异常对象
        http_status: HTTP 状态码（如果可用）
        
    Returns:
        AdapterErrorCode
    """
    # 优先使用 HTTP 状态码
    if http_status:
        error_code = map_http_status_to_error_code(http_status)
        if error_code != AdapterErrorCode.E_UNKNOWN:
            return error_code
    
    # 检查异常类型
    exception_type = type(exception).__name__
    exception_msg = str(exception)
    
    # 网络相关异常
    if "timeout" in exception_type.lower() or "timeout" in exception_msg.lower():
        return AdapterErrorCode.E_NETWORK
    
    if "connection" in exception_type.lower() or "connection" in exception_msg.lower():
        return AdapterErrorCode.E_NETWORK
    
    # 使用错误消息关键词映射
    return map_error_message_to_error_code(exception_msg)

