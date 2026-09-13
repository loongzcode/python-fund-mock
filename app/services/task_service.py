"""数据库异步任务、延迟状态流转和HTTP回调。

这里没有使用 FastAPI ``BackgroundTasks``，因为进程重启后内存任务会丢失。
任务先写入数据库，再由后台线程领取；即使服务重启，未完成任务仍能继续执行。
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import AsyncTask, LoanOrder, RepaymentOrder
from app.services.state_store import StateStore
from app.utils import money

CALLBACK = "CALLBACK"
LOAN_COMPLETE = "LOAN_COMPLETE"
REPAYMENT_COMPLETE = "REPAYMENT_COMPLETE"

logger = logging.getLogger(__name__)


class TaskScheduler:
    """在当前HTTP事务中创建异步任务。"""

    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    def schedule_credit_callback(
        self, payload: dict[str, Any], delay_millis: int
    ) -> None:
        self._schedule(
            CALLBACK,
            "CREDIT",
            None,
            delay_millis,
            payload,
            self.settings.credit_callback_url,
        )

    def schedule_loan_completion(self, loan: LoanOrder, delay_millis: int) -> None:
        self._schedule(
            LOAN_COMPLETE,
            "LOAN",
            loan.id,
            delay_millis,
            {},
            self.settings.loan_callback_url,
        )

    def schedule_loan_callback(self, loan: LoanOrder, delay_millis: int = 0) -> None:
        self._schedule(
            CALLBACK,
            "LOAN",
            loan.id,
            delay_millis,
            loan_callback_payload(loan),
            self.settings.loan_callback_url,
        )

    def schedule_repayment_completion(
        self, repayment: RepaymentOrder, delay_millis: int
    ) -> None:
        self._schedule(
            REPAYMENT_COMPLETE,
            "REPAYMENT",
            repayment.id,
            delay_millis,
            {},
            self.settings.repayment_callback_url,
        )

    def schedule_repayment_callback(
        self, repayment: RepaymentOrder, delay_millis: int = 0
    ) -> None:
        state_store = StateStore(self.session)
        self._schedule(
            CALLBACK,
            "REPAYMENT",
            repayment.id,
            delay_millis,
            repayment_callback_payload(repayment, state_store),
            self.settings.repayment_callback_url,
        )

    def _schedule(
        self,
        task_type: str,
        biz_type: str,
        biz_id: int | None,
        delay_millis: int,
        payload: dict[str, Any],
        callback_url: str | None,
    ) -> None:
        """把任务保存成 INIT，等待后台线程领取。"""

        now = datetime.now()
        task = AsyncTask(
            task_type=task_type,
            biz_type=biz_type,
            biz_id=biz_id,
            execute_at=now + timedelta(milliseconds=max(0, delay_millis)),
            status="INIT",
            retry_count=0,
            payload_json=json.dumps(payload, ensure_ascii=False),
            callback_url=callback_url,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(task)


class AsyncTaskWorker:
    """循环扫描到期任务的后台线程。"""

    def __init__(self, session_factory: sessionmaker, settings: Settings):
        self.session_factory = session_factory
        self.settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动守护线程；重复调用不会创建多个线程。"""

        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="fund-mock-task-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """通知线程停止，并最多等待3秒。"""

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def run_due_tasks_once(self) -> None:
        """执行一批到期任务；测试可以直接调用这个方法。"""

        with self.session_factory() as session:
            task_ids = list(
                session.scalars(
                    select(AsyncTask.id)
                    .where(
                        AsyncTask.status == "INIT",
                        AsyncTask.execute_at <= datetime.now(),
                    )
                    .order_by(AsyncTask.execute_at)
                    .limit(100)
                )
            )

        for task_id in task_ids:
            if self._claim(task_id):
                self._execute_claimed(task_id)

    def _run_loop(self) -> None:
        interval = max(50, self.settings.task_scan_interval_millis) / 1_000
        while not self._stop_event.is_set():
            try:
                self.run_due_tasks_once()
            except Exception:  # 后台线程不能因为单批异常永久退出。
                logger.exception("Unexpected error while scanning async tasks")
            self._stop_event.wait(interval)

    def _claim(self, task_id: int) -> bool:
        """使用“id + INIT状态”条件原子领取任务，避免多实例重复执行。"""

        with self.session_factory() as session:
            result = session.execute(
                update(AsyncTask)
                .where(AsyncTask.id == task_id, AsyncTask.status == "INIT")
                .values(status="PROCESSING", updated_at=datetime.now())
            )
            session.commit()
            return result.rowcount == 1

    def _execute_claimed(self, task_id: int) -> None:
        """执行已领取任务，成功标记SUCCESS，失败则安排指数退避重试。"""

        try:
            with self.session_factory() as session:
                task = session.get(AsyncTask, task_id)
                if task is None:
                    return
                self._execute(task, session)
                task.status = "SUCCESS"
                task.last_error = None
                task.updated_at = datetime.now()
                session.commit()
        except Exception as exception:
            logger.exception("Async task %s failed", task_id)
            self._retry_or_fail(task_id, exception)

    def _execute(self, task: AsyncTask, session: Session) -> None:
        state_store = StateStore(session)
        if task.task_type == LOAN_COMPLETE:
            loan = state_store.complete_loan(task.biz_id)
            if loan is not None:
                self._post_callback(task.callback_url, loan_callback_payload(loan))
        elif task.task_type == REPAYMENT_COMPLETE:
            repayment = state_store.complete_repayment(task.biz_id)
            if repayment is not None:
                payload = repayment_callback_payload(repayment, state_store)
                self._post_callback(task.callback_url, payload)
        elif task.task_type == CALLBACK:
            self._post_callback(task.callback_url, json.loads(task.payload_json))
        else:
            raise ValueError(f"Unknown async task type: {task.task_type}")

    @staticmethod
    def _post_callback(callback_url: str | None, payload: dict[str, Any]) -> None:
        """向公司系统发送苏商风格的结果通知；未配置地址时安全跳过。"""

        if not callback_url:
            logger.debug("Skip callback because callback URL is not configured")
            return
        request_body = {
            "signature": "MOCK_SIGNATURE",
            "algorithm": "SHA256withRSA",
            "charset": "UTF-8",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "payload": payload,
        }
        with httpx.Client(timeout=10) as client:
            response = client.post(callback_url, json=request_body)
            response.raise_for_status()

    def _retry_or_fail(self, task_id: int, exception: Exception) -> None:
        with self.session_factory() as session:
            task = session.get(AsyncTask, task_id)
            if task is None:
                return
            retries = task.retry_count + 1
            task.retry_count = retries
            task.last_error = str(exception)[:1_000]
            task.updated_at = datetime.now()
            if retries >= self.settings.callback_max_retries:
                task.status = "FAILED"
            else:
                # 第1次失败等2秒，第2次等4秒，最多等待60秒。
                retry_seconds = min(60, 2 ** min(retries, 6))
                task.status = "INIT"
                task.execute_at = datetime.now() + timedelta(seconds=retry_seconds)
            session.commit()


def loan_info(loan: LoanOrder) -> dict[str, Any]:
    """构造放款响应和异步通知共用的借据信息。"""

    return {
        "businessNo": loan.business_no,
        "payoutNo": loan.payout_no,
        "duebillNo": loan.duebill_no,
        "productCode": loan.product_code,
        "repayDt": "1MA28",
        "balance": money(loan.balance),
        "overDueDays": "0",
        "status": loan.status,
        "updateTime": loan.updated_at.strftime("%Y%m%d%H%M%S"),
        "payoffDate": loan.updated_at.strftime("%Y%m%d%H%M%S") if loan.status == "FP" else "",
        "reductionInterest": "0.00",
    }


def loan_callback_payload(loan: LoanOrder) -> dict[str, Any]:
    """构造放款结果异步通知的业务部分。"""

    return {
        "noticeType": "LOAN_RESULT",
        "merchantId": loan.merchant_id,
        "businessNo": loan.business_no,
        "payoutNo": loan.payout_no,
        "status": loan.status,
        "statusTime": loan.updated_at.strftime("%Y%m%d%H%M%S"),
        "busiAmt": money(loan.amount),
        "duebillInfo": loan_info(loan),
    }


def repayment_callback_payload(
    repayment: RepaymentOrder, state_store: StateStore
) -> dict[str, Any]:
    """构造还款结果异步通知的业务部分。"""

    payload: dict[str, Any] = {
        "noticeType": "REPAYMENT_RESULT",
        "merchantId": repayment.merchant_id,
        "businessNo": repayment.business_no,
        "repayNo": repayment.repay_no,
        "payoutNo": repayment.payout_no,
        "status": repayment.status,
        "repayAmt": money(repayment.amount),
        "hxCapi": money(repayment.principal_amount),
        "hxInte": money(repayment.interest_amount),
        "hxFinte": money(repayment.penalty_amount),
        "repayFee": money(repayment.fee_amount),
        "repayCompleteTime": (
            repayment.completed_at.strftime("%Y%m%d%H%M%S")
            if repayment.completed_at
            else ""
        ),
        "channelTransNo": repayment.channel_trans_no,
    }
    loan = state_store.find_loan({"payoutNo": repayment.payout_no})
    if loan is not None:
        payload["duebillInfo"] = loan_info(loan)
    return payload

