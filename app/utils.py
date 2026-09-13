"""业务代码共用的小工具。"""

import hashlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

MONEY_UNIT = Decimal("0.01")
RATE_UNIT = Decimal("0.000001")
DEFAULT_ANNUAL_RATE = Decimal("18.00")


def text(payload: dict[str, Any], key: str) -> str | None:
    """把 payload 字段安全转换成字符串，缺失时返回 None。"""

    raw_value = payload.get(key)
    return None if raw_value is None else str(raw_value)


def required_text(payload: dict[str, Any], key: str) -> str:
    """读取必填字符串，缺失或空字符串时抛出易读错误。"""

    value = text(payload, key)
    if value is None or not value.strip():
        raise ValueError(f"Missing required payload field: {key}")
    return value


def value(payload: dict[str, Any], key: str, fallback: str) -> str:
    """读取字符串；字段不存在或为空时返回默认值。"""

    result = text(payload, key)
    return fallback if result is None or not result.strip() else result


def decimal_value(payload: dict[str, Any], key: str, fallback: Decimal) -> Decimal:
    """读取金额或利率，并拒绝无法转换的内容。"""

    raw_value = payload.get(key)
    if raw_value is None or str(raw_value).strip() == "":
        return fallback
    try:
        # 先转字符串再构造 Decimal，避免 float 已经产生二进制精度误差。
        return Decimal(str(raw_value))
    except InvalidOperation as exception:
        raise ValueError(f"Payload field {key} must be a decimal number") from exception


def integer_value(payload: dict[str, Any], key: str, fallback: int) -> int:
    """读取整数，空值时返回默认值。"""

    raw_value = payload.get(key)
    if raw_value is None or str(raw_value).strip() == "":
        return fallback
    try:
        return int(str(raw_value))
    except ValueError as exception:
        raise ValueError(f"Payload field {key} must be an integer") from exception


def money(amount: Decimal | None) -> str:
    """将金额格式化成资金方报文常用的两位小数字符串。"""

    return (amount or Decimal("0")).quantize(MONEY_UNIT, rounding=ROUND_HALF_UP).to_eng_string()


def stable_id(prefix: str, source: object, max_length: int) -> str:
    """根据同一输入稳定生成同一编号，便于重复请求验证幂等。"""

    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest().upper()
    return (prefix + digest)[:max_length]

