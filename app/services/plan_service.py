"""还款计划试算规则。"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.utils import MONEY_UNIT, money


def add_months(start: date, months: int) -> date:
    """在不依赖第三方日期库的情况下给日期增加月份。

    例如 1 月 31 日增加 1 个月时，2 月不存在 31 日，因此自动取 2 月最后一天。
    """

    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def generate_equal_principal_plans(
    amount: Decimal,
    term: int,
    annual_rate: Decimal,
    start: date,
) -> list[dict[str, Any]]:
    """按等额本金生成还款计划。

    计算口径：

    * 每期本金 = 借款金额 / 期数；
    * 月利率 = 年利率百分数 / 1200；
    * 每期利息 = 当期期初剩余本金 × 月利率；
    * 最后一期本金负责吸收前面四舍五入产生的尾差。
    """

    if amount < 0:
        raise ValueError("busiAmt cannot be negative")
    if term < 1:
        raise ValueError("term must be greater than zero")
    if annual_rate < 0:
        raise ValueError("actualRate cannot be negative")

    principal = (amount / Decimal(term)).quantize(MONEY_UNIT, rounding=ROUND_HALF_UP)
    monthly_rate = (annual_rate / Decimal("1200")).quantize(
        Decimal("0.0000000001"), rounding=ROUND_HALF_UP
    )
    allocated = Decimal("0.00")
    plans: list[dict[str, Any]] = []

    for period in range(1, term + 1):
        period_principal = amount - allocated if period == term else principal
        period_principal = period_principal.quantize(MONEY_UNIT, rounding=ROUND_HALF_UP)
        allocated += period_principal

        remaining_before = max(
            Decimal("0.00"), amount - principal * Decimal(period - 1)
        )
        interest = (remaining_before * monthly_rate).quantize(
            MONEY_UNIT, rounding=ROUND_HALF_UP
        )
        due_date = add_months(start, period)

        plans.append(
            {
                "term": str(period),
                "startDate": start.strftime("%Y%m%d"),
                "dueDate": due_date.strftime("%Y%m%d"),
                "planStatus": "0",
                "prinAmt": money(period_principal),
                "intAmt": money(interest),
                "ointAmt": "0.00",
                "feeAmt": "0.00",
                "actPrinAmt": "0.00",
                "actIntAmt": "0.00",
                "actOintAmt": "0.00",
                "actFeeAmt": "0.00",
                "graceDate": due_date.strftime("%Y%m%d"),
                "reduIntAmt": "0.00",
            }
        )

    return plans

