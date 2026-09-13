"""借款、还款计划和还款订单的持久状态服务。

HTTP 接口只负责接收请求和组装响应，所有需要跨请求保持一致的数据变化都放在
这个类里。这样查询接口、异步任务和回调使用的是同一份业务状态。
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import constants
from app.models import LoanOrder, RepaymentOrder, RepaymentPlan
from app.services.plan_service import generate_equal_principal_plans
from app.utils import (
    DEFAULT_ANNUAL_RATE,
    MONEY_UNIT,
    RATE_UNIT,
    decimal_value,
    integer_value,
    required_text,
    stable_id,
    text,
    value,
)

FUND_CODE = "SNB"


class StateStore:
    """在一个数据库事务中操作三类核心业务状态。"""

    def __init__(self, session: Session):
        self.session = session

    def create_loan(self, payload: dict[str, Any], scenario: str) -> LoanOrder:
        """创建借款订单，相同商户号和业务流水号重复提交时返回原订单。"""

        merchant_id = required_text(payload, "merchantId")
        business_no = required_text(payload, "businessNo")
        existing = self._find_loan_by_business_no(merchant_id, business_no)
        if existing is not None:
            return existing

        amount = decimal_value(payload, "busiAmt", Decimal("0")).quantize(
            MONEY_UNIT, rounding=ROUND_HALF_UP
        )
        term = max(1, integer_value(payload, "term", 12))
        annual_rate = decimal_value(
            payload, "actualRate", DEFAULT_ANNUAL_RATE
        ).quantize(RATE_UNIT, rounding=ROUND_HALF_UP)

        if amount < 0:
            raise ValueError("busiAmt cannot be negative")
        if annual_rate < 0:
            raise ValueError("actualRate cannot be negative")

        if scenario in {constants.FAILURE, constants.REJECTED}:
            status = "F"
        elif scenario in {constants.PROCESSING, constants.DELAY_SUCCESS}:
            status = "P"
        else:
            status = "S"

        now = datetime.now()
        order = LoanOrder(
            fund_code=FUND_CODE,
            merchant_id=merchant_id,
            product_code=value(payload, "productCode", "100406"),
            business_no=business_no,
            payout_no=stable_id("PO", business_no, 32),
            duebill_no=stable_id("DB", business_no, 32),
            amount=amount,
            balance=amount if status == "S" else Decimal("0.00"),
            term=term,
            annual_rate=annual_rate,
            status=status,
            scenario_code=scenario,
            version=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(order)
        # flush 会把 INSERT 发给数据库并取得自增 id，但不会提前提交事务。
        self.session.flush()

        if status == "S":
            self._create_plans_if_missing(order)
        return order

    def find_loan(self, payload: dict[str, Any]) -> LoanOrder | None:
        """按放款单号、借据号或业务流水号查找借款订单。"""

        statement = select(LoanOrder).where(LoanOrder.fund_code == FUND_CODE)
        payout_no = text(payload, "payoutNo")
        duebill_no = text(payload, "duebillNo")
        business_no = text(payload, "businessNo")
        merchant_id = text(payload, "merchantId")

        # 查询优先级与真实业务标识的唯一性一致：放款单号 > 借据号 > 业务流水号。
        if payout_no and payout_no.strip():
            statement = statement.where(LoanOrder.payout_no == payout_no)
        elif duebill_no and duebill_no.strip():
            statement = statement.where(LoanOrder.duebill_no == duebill_no)
        elif business_no and business_no.strip():
            statement = statement.where(LoanOrder.business_no == business_no)
            if merchant_id and merchant_id.strip():
                statement = statement.where(LoanOrder.merchant_id == merchant_id)
        else:
            return None
        return self.session.scalar(statement.limit(1))

    def find_loan_by_id(self, loan_id: int | None) -> LoanOrder | None:
        """按数据库主键查找借款订单。"""

        return None if loan_id is None else self.session.get(LoanOrder, loan_id)

    def complete_loan(self, loan_id: int | None) -> LoanOrder | None:
        """将延迟放款订单改为成功，并根据订单条款生成正式还款计划。"""

        order = self.find_loan_by_id(loan_id)
        if order is None or order.status == "S":
            return order

        order.status = "S"
        order.balance = order.amount
        order.updated_at = datetime.now()
        order.version += 1
        self._create_plans_if_missing(order)
        return order

    def plans_for_loan(self, loan_order_id: int | None) -> list[RepaymentPlan]:
        """按期次升序查询借款订单的还款计划。"""

        if loan_order_id is None:
            return []
        statement = (
            select(RepaymentPlan)
            .where(RepaymentPlan.loan_order_id == loan_order_id)
            .order_by(RepaymentPlan.period_no)
        )
        return list(self.session.scalars(statement))

    def trial_plans(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """根据请求条款生成不落库的借款试算计划。"""

        amount = decimal_value(payload, "busiAmt", Decimal("0"))
        term = max(1, integer_value(payload, "term", 12))
        annual_rate = decimal_value(payload, "actualRate", DEFAULT_ANNUAL_RATE)
        return generate_equal_principal_plans(amount, term, annual_rate, date.today())

    def create_repayment(
        self, payload: dict[str, Any], scenario: str
    ) -> RepaymentOrder:
        """创建还款订单；成功场景立即按“利息优先、本金其次”分配金额。"""

        merchant_id = required_text(payload, "merchantId")
        business_no = required_text(payload, "businessNo")
        existing = self.session.scalar(
            select(RepaymentOrder)
            .where(
                RepaymentOrder.fund_code == FUND_CODE,
                RepaymentOrder.merchant_id == merchant_id,
                RepaymentOrder.business_no == business_no,
            )
            .limit(1)
        )
        if existing is not None:
            return existing

        payout_no = required_text(payload, "payoutNo")
        loan = self.find_loan({"payoutNo": payout_no})
        if loan is None:
            raise ValueError(f"Loan order not found for payoutNo: {payout_no}")

        if scenario in {constants.FAILURE, constants.REJECTED}:
            status = "F"
        elif scenario in {constants.PROCESSING, constants.DELAY_SUCCESS}:
            status = "P"
        else:
            status = "S"

        amount = decimal_value(payload, "repayAmt", Decimal("0")).quantize(
            MONEY_UNIT, rounding=ROUND_HALF_UP
        )
        if amount < 0:
            raise ValueError("repayAmt cannot be negative")

        now = datetime.now()
        order = RepaymentOrder(
            fund_code=FUND_CODE,
            merchant_id=merchant_id,
            business_no=business_no,
            repay_no=stable_id("RP", business_no, 32),
            payout_no=payout_no,
            amount=amount,
            principal_amount=Decimal("0.00"),
            interest_amount=Decimal("0.00"),
            penalty_amount=Decimal("0.00"),
            fee_amount=Decimal("0.00"),
            repay_type=value(payload, "repayType", "1"),
            status=status,
            channel_trans_no=stable_id("CH", business_no, 32),
            scenario_code=scenario,
            version=0,
            completed_at=now if status == "S" else None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(order)
        self.session.flush()

        if status == "S":
            principal, interest = self._allocate_repayment(loan, amount)
            order.principal_amount = principal
            order.interest_amount = interest
        return order

    def find_repayment(self, payload: dict[str, Any]) -> RepaymentOrder | None:
        """按还款单号或业务流水号查询还款订单。"""

        statement = select(RepaymentOrder).where(
            RepaymentOrder.fund_code == FUND_CODE
        )
        repay_no = text(payload, "repayNo")
        business_no = text(payload, "businessNo")
        merchant_id = text(payload, "merchantId")

        if repay_no and repay_no.strip():
            statement = statement.where(RepaymentOrder.repay_no == repay_no)
        elif business_no and business_no.strip():
            statement = statement.where(RepaymentOrder.business_no == business_no)
            if merchant_id and merchant_id.strip():
                statement = statement.where(RepaymentOrder.merchant_id == merchant_id)
        else:
            return None
        return self.session.scalar(statement.limit(1))

    def find_repayment_by_id(self, order_id: int | None) -> RepaymentOrder | None:
        """按数据库主键查询还款订单。"""

        return None if order_id is None else self.session.get(RepaymentOrder, order_id)

    def complete_repayment(self, order_id: int | None) -> RepaymentOrder | None:
        """将延迟还款订单改为成功并完成金额分配。"""

        order = self.find_repayment_by_id(order_id)
        if order is None or order.status == "S":
            return order

        loan = self.find_loan({"payoutNo": order.payout_no})
        now = datetime.now()
        order.status = "S"
        order.completed_at = now
        order.updated_at = now
        order.version += 1

        if loan is not None:
            principal, interest = self._allocate_repayment(loan, order.amount)
            order.principal_amount = principal
            order.interest_amount = interest
        return order

    def total_balance(self, product_code: str | None) -> Decimal:
        """汇总指定产品下全部借据的剩余本金。"""

        statement = select(func.coalesce(func.sum(LoanOrder.balance), 0)).where(
            LoanOrder.fund_code == FUND_CODE
        )
        if product_code and product_code.strip():
            statement = statement.where(LoanOrder.product_code == product_code)
        result = self.session.scalar(statement)
        return Decimal(str(result or 0)).quantize(MONEY_UNIT, rounding=ROUND_HALF_UP)

    def _find_loan_by_business_no(
        self, merchant_id: str, business_no: str
    ) -> LoanOrder | None:
        """使用公司侧幂等键查询借款订单。"""

        return self.session.scalar(
            select(LoanOrder)
            .where(
                LoanOrder.fund_code == FUND_CODE,
                LoanOrder.merchant_id == merchant_id,
                LoanOrder.business_no == business_no,
            )
            .limit(1)
        )

    def _create_plans_if_missing(self, order: LoanOrder) -> None:
        """借款成功后生成正式计划；已有计划时直接返回，保证幂等。"""

        count = self.session.scalar(
            select(func.count(RepaymentPlan.id)).where(
                RepaymentPlan.loan_order_id == order.id
            )
        )
        if count and count > 0:
            return

        plans = generate_equal_principal_plans(
            order.amount, order.term, order.annual_rate, date.today()
        )
        now = datetime.now()
        for item in plans:
            self.session.add(
                RepaymentPlan(
                    loan_order_id=order.id,
                    period_no=int(item["term"]),
                    due_date=datetime.strptime(item["dueDate"], "%Y%m%d").date(),
                    principal=Decimal(item["prinAmt"]),
                    interest=Decimal(item["intAmt"]),
                    fee=Decimal("0.00"),
                    paid_principal=Decimal("0.00"),
                    paid_interest=Decimal("0.00"),
                    paid_fee=Decimal("0.00"),
                    status="UNPAID",
                    version=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        self.session.flush()

    def _allocate_repayment(
        self, loan: LoanOrder, amount: Decimal
    ) -> tuple[Decimal, Decimal]:
        """把还款金额依次分配给每一期的利息和本金。"""

        remaining = max(amount, Decimal("0.00"))
        principal_paid_total = Decimal("0.00")
        interest_paid_total = Decimal("0.00")

        for plan in self.plans_for_loan(loan.id):
            if remaining <= 0:
                break

            outstanding_interest = max(
                Decimal("0.00"), plan.interest - plan.paid_interest
            )
            paid_interest = min(remaining, outstanding_interest)
            plan.paid_interest += paid_interest
            interest_paid_total += paid_interest
            remaining -= paid_interest

            outstanding_principal = max(
                Decimal("0.00"), plan.principal - plan.paid_principal
            )
            paid_principal = min(remaining, outstanding_principal)
            plan.paid_principal += paid_principal
            principal_paid_total += paid_principal
            remaining -= paid_principal

            fully_paid = (
                plan.paid_interest >= plan.interest
                and plan.paid_principal >= plan.principal
            )
            plan.status = "PAID" if fully_paid else "PARTIAL"
            plan.updated_at = datetime.now()
            plan.version += 1

        loan.balance = max(
            Decimal("0.00"), loan.balance - principal_paid_total
        ).quantize(MONEY_UNIT, rounding=ROUND_HALF_UP)
        loan.status = "FP" if loan.balance == 0 else "RP"
        loan.updated_at = datetime.now()
        loan.version += 1

        return (
            principal_paid_total.quantize(MONEY_UNIT, rounding=ROUND_HALF_UP),
            interest_paid_total.quantize(MONEY_UNIT, rounding=ROUND_HALF_UP),
        )

