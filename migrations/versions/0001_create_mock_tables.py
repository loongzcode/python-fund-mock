"""创建Mock业务表和异步任务表。"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """创建四张表及对应唯一索引、查询索引。"""

    op.create_table(
        "mock_loan_order",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fund_code", sa.String(32), nullable=False),
        sa.Column("merchant_id", sa.String(32), nullable=False),
        sa.Column("product_code", sa.String(20), nullable=False),
        sa.Column("business_no", sa.String(64), nullable=False),
        sa.Column("payout_no", sa.String(64), nullable=False),
        sa.Column("duebill_no", sa.String(64)),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("term", sa.Integer(), nullable=False),
        sa.Column("annual_rate", sa.Numeric(10, 6), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scenario_code", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fund_code", "merchant_id", "business_no", name="uk_mock_loan_business"),
        sa.UniqueConstraint("fund_code", "payout_no", name="uk_mock_loan_payout"),
    )
    op.create_index("idx_mock_loan_status", "mock_loan_order", ["fund_code", "status", "updated_at"])

    op.create_table(
        "mock_repayment_plan",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("loan_order_id", sa.Integer(), sa.ForeignKey("mock_loan_order.id"), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest", sa.Numeric(18, 2), nullable=False),
        sa.Column("fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("paid_principal", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("paid_interest", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("paid_fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("loan_order_id", "period_no", name="uk_mock_plan_period"),
    )
    op.create_index("idx_mock_plan_due", "mock_repayment_plan", ["status", "due_date"])

    op.create_table(
        "mock_repayment_order",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fund_code", sa.String(32), nullable=False),
        sa.Column("merchant_id", sa.String(32), nullable=False),
        sa.Column("business_no", sa.String(64), nullable=False),
        sa.Column("repay_no", sa.String(64), nullable=False),
        sa.Column("payout_no", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("principal_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("interest_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("penalty_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("fee_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("repay_type", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("channel_trans_no", sa.String(64)),
        sa.Column("scenario_code", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fund_code", "merchant_id", "business_no", name="uk_mock_repay_business"),
        sa.UniqueConstraint("fund_code", "repay_no", name="uk_mock_repay_no"),
    )
    op.create_index("idx_mock_repay_payout", "mock_repayment_order", ["fund_code", "payout_no", "created_at"])

    op.create_table(
        "mock_async_task",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("biz_type", sa.String(32), nullable=False),
        sa.Column("biz_id", sa.Integer()),
        sa.Column("execute_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("callback_url", sa.String(512)),
        sa.Column("last_error", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_mock_task_execute", "mock_async_task", ["status", "execute_at"])


def downgrade() -> None:
    """按外键依赖的反向顺序删除表。"""

    op.drop_table("mock_async_task")
    op.drop_table("mock_repayment_order")
    op.drop_table("mock_repayment_plan")
    op.drop_table("mock_loan_order")

