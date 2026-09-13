"""数据库实体定义。

业务数据库只保存借款订单、还款计划、还款订单三类状态；``AsyncTask`` 是保证
延迟成功和回调重试可靠执行的技术表，不属于新的业务对象。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LoanOrder(Base):
    """借款订单，是还款计划和还款订单的业务根。"""

    __tablename__ = "mock_loan_order"
    __table_args__ = (
        UniqueConstraint("fund_code", "merchant_id", "business_no", name="uk_mock_loan_business"),
        UniqueConstraint("fund_code", "payout_no", name="uk_mock_loan_payout"),
        Index("idx_mock_loan_status", "fund_code", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(32), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(32), nullable=False)
    product_code: Mapped[str] = mapped_column(String(20), nullable=False)
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    payout_no: Mapped[str] = mapped_column(String(64), nullable=False)
    duebill_no: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    term: Mapped[int] = mapped_column(Integer, nullable=False)
    # 18.000000 表示年利率 18%，而不是小数 0.18。
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    scenario_code: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    plans: Mapped[list["RepaymentPlan"]] = relationship(back_populates="loan")


class RepaymentPlan(Base):
    """一笔借款中的单期还款计划。"""

    __tablename__ = "mock_repayment_plan"
    __table_args__ = (
        UniqueConstraint("loan_order_id", "period_no", name="uk_mock_plan_period"),
        Index("idx_mock_plan_due", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    loan_order_id: Mapped[int] = mapped_column(ForeignKey("mock_loan_order.id"), nullable=False)
    period_no: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    interest: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    paid_principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    paid_interest: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    paid_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    loan: Mapped[LoanOrder] = relationship(back_populates="plans")


class RepaymentOrder(Base):
    """公司发起的一笔还款申请。"""

    __tablename__ = "mock_repayment_order"
    __table_args__ = (
        UniqueConstraint("fund_code", "merchant_id", "business_no", name="uk_mock_repay_business"),
        UniqueConstraint("fund_code", "repay_no", name="uk_mock_repay_no"),
        Index("idx_mock_repay_payout", "fund_code", "payout_no", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(32), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(32), nullable=False)
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    repay_no: Mapped[str] = mapped_column(String(64), nullable=False)
    payout_no: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    interest_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    penalty_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    repay_type: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_trans_no: Mapped[str | None] = mapped_column(String(64))
    scenario_code: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AsyncTask(Base):
    """可重试的数据库异步任务。"""

    __tablename__ = "mock_async_task"
    __table_args__ = (Index("idx_mock_task_execute", "status", "execute_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_id: Mapped[int | None] = mapped_column(Integer)
    execute_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    callback_url: Mapped[str | None] = mapped_column(String(512))
    last_error: Mapped[str | None] = mapped_column(String(1_000))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

