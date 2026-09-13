"""还款计划计算单元测试。"""

from datetime import date
from decimal import Decimal

from app.services.plan_service import add_months, generate_equal_principal_plans


def test_equal_principal_plan_absorbs_rounding_difference_in_last_period():
    """无法整除的本金尾差必须放到最后一期，所有本金之和仍等于借款金额。"""

    plans = generate_equal_principal_plans(
        Decimal("1000.00"), 3, Decimal("12.00"), date(2026, 1, 1)
    )
    principals = [Decimal(plan["prinAmt"]) for plan in plans]
    assert principals == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert sum(principals) == Decimal("1000.00")


def test_add_months_handles_month_end():
    """1月31日增加一个月时应落到2月最后一天。"""

    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

