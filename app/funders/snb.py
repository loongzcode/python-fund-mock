"""苏商银行26个产品接口的交易路由和响应组装。"""

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app import constants
from app.config import Settings
from app.funders.base import FunderAdapter
from app.models import LoanOrder, RepaymentOrder, RepaymentPlan
from app.schemas import SnbGatewayRequest, SnbGatewayResponse
from app.services.plan_service import add_months
from app.services.state_store import StateStore
from app.services.task_service import TaskScheduler, loan_info
from app.utils import decimal_value, money, required_text, stable_id, text, value


class SnbAdapter(FunderAdapter):
    """苏商接口处理器。

    这个类只做三件事：校验公共报文、根据交易码选择方法、组装苏商响应。
    需要保存的数据变化全部交给 ``StateStore``，异步任务交给 ``TaskScheduler``。
    """

    def __init__(self, session: Session, settings: Settings):
        self.settings = settings
        self.state_store = StateStore(session)
        self.tasks = TaskScheduler(session, settings)

        # 交易码到处理方法的映射，等价于 Java 中的 switch-case。
        self.handlers: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
            constants.CREDIT_APPLY: self.credit_apply,
            constants.CREDIT_PROGRESS_QUERY: self.credit_progress,
            constants.LIMIT_QUERY: self.limit_query,
            constants.AGREEMENT_QUERY: self.agreement_query,
            constants.ADVANCE_TRIAL: self.advance_trial,
            constants.ADVANCE_APPLY: self.advance_apply,
            constants.ADVANCE_PROGRESS_QUERY: self.advance_progress,
            constants.ADVANCE_CONTRACT_QUERY: self.contract_query,
            constants.REPAY_TRIAL: self.repay_trial,
            constants.REPAY_APPLY: self.repay_apply,
            constants.REPAY_RESULT_QUERY: self.repay_result,
            constants.REPAY_PLAN_QUERY: self.repay_plan,
            constants.BIND_CARD_SIGN: self.bind_card_sign,
            constants.BIND_CARD_CHECK: self.simple_status,
            constants.BIND_CARD_INFO_QUERY: self.bind_card_info,
            constants.BIND_CARD_SYNC: self.simple_status,
            constants.COUPON_QUERY: self.coupon_query,
            constants.CERTIFY_APPLY: self.certify_apply,
            constants.CERTIFY_QUERY: self.certify_query,
            constants.OPEN_ID_QUERY: self.open_id_query,
            constants.LIMIT_CLOSE: self.limit_close,
            constants.PAYOUT_BALANCE_QUERY: self.payout_balance,
            constants.FILE_PATH_UPLOAD: self.file_path_upload,
            constants.FILE_STREAM_UPLOAD: self.file_stream_upload,
            constants.FILE_UPLOAD_RESULT_QUERY: self.file_upload_result,
            constants.FILE_DOWNLOAD: self.file_download,
        }

    async def handle(
        self,
        path_app_code: str,
        path_trans_code: str,
        request: SnbGatewayRequest,
        requested_scenario: str | None,
    ) -> SnbGatewayResponse:
        """校验路径和报文中的公共字段，再把请求分发给具体接口。"""

        if path_trans_code not in constants.SNB_TRANSACTION_NAMES:
            return SnbGatewayResponse.failure(
                request.channel_serial_no,
                "FSOS0001",
                f"Unsupported transaction code: {path_trans_code}",
            )
        if request.trans_code and request.trans_code != path_trans_code:
            return SnbGatewayResponse.failure(
                request.channel_serial_no,
                "FSOS0002",
                "transCode does not match request path",
            )
        if request.app_code and request.app_code != path_app_code:
            return SnbGatewayResponse.failure(
                request.channel_serial_no,
                "FSOS0003",
                "appCode does not match request path",
            )

        scenario = self._normalize_scenario(requested_scenario)
        if scenario == constants.TIMEOUT:
            # asyncio.sleep 不会阻塞 FastAPI 处理其他请求的事件循环。
            await asyncio.sleep(30)

        stateful_codes = {constants.ADVANCE_APPLY, constants.REPAY_APPLY}
        if scenario == constants.FAILURE and path_trans_code not in stateful_codes:
            return SnbGatewayResponse.failure(
                request.channel_serial_no, "00999999", "Mock system failure"
            )

        payload = request.payload or {}
        result = self.handlers[path_trans_code](payload, scenario)
        serial_no = stable_id(
            "SN", f"{request.channel_serial_no}{path_trans_code}", 32
        )
        return SnbGatewayResponse.success(
            request.channel_serial_no, serial_no, result
        )

    def credit_apply(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """受理授信申请，并按场景创建授信结果通知任务。"""

        business_no = required_text(payload, "businessNo")
        apply_no = stable_id("CA", business_no, 32)
        open_id = stable_id(
            "OI", f"{text(payload, 'certNo')}{business_no}", 64
        )
        status = "03" if scenario == constants.REJECTED else "01"
        result = {
            "businessNo": business_no,
            "applyNo": apply_no,
            "status": status,
            "statusTime": self._now(),
            "openId": open_id,
        }

        if scenario not in {constants.REJECTED, constants.PROCESSING}:
            callback = self.credit_progress(payload, constants.SUCCESS)
            callback["noticeType"] = "CREDIT_RESULT"
            delay = self._delay_millis() if scenario == constants.DELAY_SUCCESS else 0
            self.tasks.schedule_credit_callback(callback, delay)
        return result

    def credit_progress(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询授信申请状态。"""

        business_no = value(payload, "businessNo", "MOCK_CREDIT_BUSINESS")
        if scenario == constants.NOT_FOUND:
            status = "00"
        elif scenario in {constants.PROCESSING, constants.DELAY_SUCCESS}:
            status = "01"
        elif scenario in {constants.REJECTED, constants.FAILURE}:
            status = "03"
        else:
            status = "02"

        result: dict[str, Any] = {
            "businessNo": business_no,
            "applyNo": business_no if business_no.startswith("CA") else stable_id("CA", business_no, 32),
            "status": status,
            "statusTime": self._now(),
            "rejectPeriod": "30" if status == "03" else "",
            "remark": "Mock credit rejected" if status == "03" else "",
        }
        if status == "02":
            result["creditInfo"] = self._credit_info(payload)
            result["authFileList"] = [
                {
                    "fileType": "LHD016",
                    "fileName": "mock-credit-authorization.pdf",
                    "filePath": "mock://snb/contracts/credit-authorization.pdf",
                }
            ]
        return result

    def limit_query(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询审批额度和实际利率。"""

        if scenario == constants.NOT_FOUND:
            return {"businessNo": value(payload, "businessNo", ""), "status": "00"}
        business_no = value(payload, "businessNo", "MOCK_LIMIT_QUERY")
        return {
            "businessNo": business_no,
            "applyNo": value(payload, "applyNo", stable_id("CA", business_no, 32)),
            "updateTime": self._now(),
            "creditInfo": self._credit_info(payload),
        }

    def agreement_query(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        """返回资金方分账比例和协议编号。"""

        business_no = value(payload, "businessNo", "MOCK_AGREEMENT_QUERY")
        return {
            "businessNo": business_no,
            "status": "01",
            "actualRate": value(payload, "actualRate", "18.00"),
            "snbRatio": "0.50",
            "partnerRatio": "0.50",
            "snbBankName": "江苏苏商银行股份有限公司",
            "snbBankCode": "SNB",
            "agreementList": [
                {
                    "agreementType": "LHD007",
                    "agreementName": "个人借款合同",
                    "agreementNo": stable_id("AG", business_no, 32),
                }
            ],
        }

    def advance_trial(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        """借款试算只返回计划，不写数据库。"""

        plans = self.state_store.trial_plans(payload)
        principal = sum((Decimal(item["prinAmt"]) for item in plans), Decimal("0"))
        interest = sum((Decimal(item["intAmt"]) for item in plans), Decimal("0"))
        business_no = value(payload, "businessNo", "MOCK_TRIAL")
        response_plans = []
        for plan in plans:
            item = dict(plan)
            item["planNo"] = stable_id(
                "PL", f"{business_no}{plan['term']}", 32
            )
            response_plans.append(item)
        return {
            "businessNo": business_no,
            "lnAmt": money(principal),
            "totInt": money(interest),
            "totReduIntAmt": "0.00",
            "planList": response_plans,
        }

    def advance_apply(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """创建放款订单；放款成功时正式还款计划已经同步生成。"""

        loan = self.state_store.create_loan(payload, scenario)
        if scenario == constants.DELAY_SUCCESS:
            self.tasks.schedule_loan_completion(loan, self._delay_millis())
        elif loan.status == "S":
            self.tasks.schedule_loan_callback(loan)
        return self._loan_result(loan)

    def advance_progress(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询已经持久化的放款状态。"""

        if scenario == constants.NOT_FOUND:
            return {"businessNo": value(payload, "businessNo", ""), "status": "U"}
        loan = self.state_store.find_loan(payload)
        if loan is None:
            return {"businessNo": value(payload, "businessNo", ""), "status": "U"}
        return self._loan_result(loan)

    def contract_query(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        """返回用于联调的模拟借款合同地址。"""

        business_no = value(payload, "businessNo", "MOCK_CONTRACT_QUERY")
        return {
            "businessNo": business_no,
            "authFileList": [
                {
                    "fileType": "LHD007",
                    "fileName": "mock-loan-contract.pdf",
                    "filePath": f"mock://snb/contracts/{business_no}.pdf",
                }
            ],
        }

    def repay_trial(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """根据数据库计划计算当前全部未还本金和利息。"""

        if scenario == constants.NOT_FOUND:
            return {"status": "U", "businessNo": value(payload, "businessNo", "")}
        loan = self.state_store.find_loan(payload)
        if loan is None:
            return {"status": "U", "businessNo": value(payload, "businessNo", "")}

        plans = self.state_store.plans_for_loan(loan.id)
        principal = max(
            Decimal("0"),
            sum((plan.principal - plan.paid_principal for plan in plans), Decimal("0")),
        )
        interest = max(
            Decimal("0"),
            sum((plan.interest - plan.paid_interest for plan in plans), Decimal("0")),
        )
        return {
            "status": "S",
            "businessNo": value(payload, "businessNo", "MOCK_REPAY_TRIAL"),
            "repayAmt": money(principal + interest),
            "hxCapi": money(principal),
            "hxInte": money(interest),
            "hxFinte": "0.00",
            "repayFee": "0.00",
            "reductionInterest": "0.00",
        }

    def repay_apply(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """创建还款订单并按场景安排延迟成功或结果通知。"""

        repayment = self.state_store.create_repayment(payload, scenario)
        if scenario == constants.DELAY_SUCCESS:
            self.tasks.schedule_repayment_completion(repayment, self._delay_millis())
        elif repayment.status == "S":
            self.tasks.schedule_repayment_callback(repayment)
        return self._repayment_result(repayment)

    def repay_result(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询已经持久化的还款结果。"""

        if scenario == constants.NOT_FOUND:
            return {"businessNo": value(payload, "businessNo", ""), "status": "U"}
        repayment = self.state_store.find_repayment(payload)
        if repayment is None:
            return {"businessNo": value(payload, "businessNo", ""), "status": "U"}
        return self._repayment_result(repayment)

    def repay_plan(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询放款成功时已写入数据库的正式还款计划。"""

        if scenario == constants.NOT_FOUND:
            return {"repayPlanList": []}
        loan = self.state_store.find_loan(payload)
        if loan is None:
            return {"repayPlanList": []}
        return {
            "repayPlanList": [
                self._plan_map(plan)
                for plan in self.state_store.plans_for_loan(loan.id)
            ]
        }

    def bind_card_sign(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """绑卡签约，稳定生成短信鉴权编号。"""

        business_no = required_text(payload, "businessNo")
        failed = self._failed(scenario)
        return {
            "businessNo": business_no,
            "status": "02" if failed else "01",
            "reasonCode": "ICE3717" if failed else "",
            "remark": "Mock bind card failure" if failed else "",
            "smsKey": stable_id("SM", business_no, 32),
            "authTransNbr": stable_id("AT", business_no, 64),
            "openId": stable_id("OI", value(payload, "certNo", business_no), 64),
        }

    def simple_status(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """绑卡校验、协议同步等无需持久状态接口的公共响应。"""

        failed = self._failed(scenario)
        return {
            "businessNo": value(payload, "businessNo", "MOCK_BUSINESS"),
            "status": "02" if failed else "01",
            "reasonCode": "ICE3726" if failed else "",
            "remark": "Mock operation failed" if failed else "",
        }

    def bind_card_info(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """返回确定性银行卡信息，不保存新的银行卡业务表。"""

        if scenario == constants.NOT_FOUND:
            return {"acctInfoList": []}
        return {
            "acctInfoList": [
                {
                    "acctNo": value(payload, "acctNo", "6222000000000000"),
                    "acctName": value(payload, "acctName", "MOCK USER"),
                    "acctBankName": value(payload, "acctBankName", "MOCK BANK"),
                    "phoneNo": value(payload, "phoneNo", "13800000000"),
                    "priority": value(payload, "priority", "1"),
                    "authTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            ]
        }

    def coupon_query(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        """默认返回无可用券。"""

        return {
            "businessNo": value(payload, "businessNo", "MOCK_COUPON_QUERY"),
            "ticketInfoList": [],
        }

    def certify_apply(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """受理结清证明申请。"""

        business_no = required_text(payload, "businessNo")
        failed = self._failed(scenario)
        return {
            "businessNo": business_no,
            "applyNo": stable_id("CF", business_no, 32),
            "status": "F" if failed else "P",
            "remark": "Mock certificate application failed" if failed else "",
        }

    def certify_query(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询模拟结清证明结果。"""

        business_no = value(payload, "businessNo", "MOCK_CERT_QUERY")
        if scenario == constants.NOT_FOUND:
            return {"businessNo": business_no, "status": "U"}
        failed = self._failed(scenario)
        return {
            "businessNo": business_no,
            "applyNo": value(payload, "applyNo", stable_id("CF", business_no, 32)),
            "status": "F" if failed else "S",
            "filePath": "" if failed else f"mock://snb/certificates/{business_no}.pdf",
            "remark": "Mock certificate generation failed" if failed else "",
        }

    def open_id_query(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        """根据证件号或手机号稳定生成 openId。"""

        source = value(payload, "certNo", value(payload, "phoneNo", "MOCK"))
        return {
            "businessNo": value(payload, "businessNo", "MOCK_OPENID_QUERY"),
            "openId": stable_id("OI", source, 64),
        }

    def limit_close(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """处理额度关闭请求。"""

        failed = self._failed(scenario)
        return {
            "businessNo": value(payload, "businessNo", "MOCK_LIMIT_CLOSE"),
            "status": "F" if failed else "S",
            "remark": "Mock limit close failed" if failed else "",
        }

    def payout_balance(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        """汇总指定产品下所有借据的剩余本金。"""

        product_code = value(payload, "productCode", "100406")
        return {
            "businessNo": value(payload, "businessNo", "MOCK_BALANCE_QUERY"),
            "productCode": product_code,
            "endDate": date.today().strftime("%Y%m%d"),
            "productBalance": money(self.state_store.total_balance(product_code)),
            "detailList": [],
        }

    def file_path_upload(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        return self._file_accepted(payload, "PATH")

    def file_stream_upload(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        return self._file_accepted(payload, "STREAM")

    def file_upload_result(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """查询文件上传结果。"""

        failed = self._failed(scenario)
        return {
            "businessNo": value(payload, "businessNo", "MOCK_FILE_QUERY"),
            "fileId": value(payload, "fileId", stable_id("FI", "MOCK_FILE_QUERY", 32)),
            "status": "U" if scenario == constants.NOT_FOUND else "F" if failed else "S",
            "remark": "Mock file upload failed" if failed else "",
        }

    def file_download(self, payload: dict[str, Any], scenario: str) -> dict[str, Any]:
        """返回一段Base64模拟文件内容。"""

        not_found = scenario == constants.NOT_FOUND
        return {
            "filePath": value(payload, "filePath", "mock://snb/files/mock.txt"),
            "status": "U" if not_found else "S",
            "fileContent": "" if not_found else "TU9DS19GSUxFX0NPTlRFTlQ=",
        }

    def _credit_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "creditTime": self._now(),
            "creditLimit": money(decimal_value(payload, "creditLimit", Decimal("100000"))),
            "limitType": "01",
            "status": "002",
            "creditBeginDate": date.today().isoformat(),
            "creditEndDate": add_months(date.today(), 12).isoformat(),
            "actualRate": value(payload, "actualRate", "18.00"),
        }

    @staticmethod
    def _loan_result(loan: LoanOrder) -> dict[str, Any]:
        result: dict[str, Any] = {
            "businessNo": loan.business_no,
            "payoutNo": loan.payout_no,
            "status": loan.status,
            "statusTime": loan.updated_at.strftime("%Y%m%d%H%M%S"),
            "busiAmt": money(loan.amount),
            "remark": "Mock payout failed" if loan.status == "F" else "",
        }
        if loan.status != "F":
            result["duebillInfo"] = loan_info(loan)
        return result

    def _repayment_result(self, repayment: RepaymentOrder) -> dict[str, Any]:
        result: dict[str, Any] = {
            "businessNo": repayment.business_no,
            "repayNo": repayment.repay_no,
            "status": repayment.status,
            "repayCompleteTime": (
                repayment.completed_at.strftime("%Y%m%d%H%M%S")
                if repayment.completed_at
                else ""
            ),
            "repayAmt": money(repayment.amount),
            "hxCapi": money(repayment.principal_amount),
            "hxInte": money(repayment.interest_amount),
            "hxFinte": money(repayment.penalty_amount),
            "repayFee": money(repayment.fee_amount),
            "remark": "Mock repayment failed" if repayment.status == "F" else "",
            "channelTransNo": repayment.channel_trans_no,
            "reductionInterest": "0.00",
        }
        loan = self.state_store.find_loan({"payoutNo": repayment.payout_no})
        if loan is not None:
            result["duebillInfo"] = loan_info(loan)
        return result

    @staticmethod
    def _plan_map(plan: RepaymentPlan) -> dict[str, Any]:
        return {
            "term": str(plan.period_no),
            "startDate": plan.created_at.date().strftime("%Y%m%d"),
            "dueDate": plan.due_date.strftime("%Y%m%d"),
            "planStatus": "2" if plan.status == "PAID" else "0",
            "prinAmt": money(plan.principal),
            "intAmt": money(plan.interest),
            "ointAmt": "0.00",
            "feeAmt": money(plan.fee),
            "actPrinAmt": money(plan.paid_principal),
            "actIntAmt": money(plan.paid_interest),
            "actOintAmt": "0.00",
            "actFeeAmt": money(plan.paid_fee),
            "graceDate": plan.due_date.strftime("%Y%m%d"),
            "settleTime": plan.updated_at.strftime("%Y%m%d%H%M%S") if plan.status == "PAID" else "",
            "reduIntAmt": "0.00",
        }

    @staticmethod
    def _file_accepted(payload: dict[str, Any], mode: str) -> dict[str, Any]:
        business_no = value(payload, "businessNo", value(payload, "fileId", "MOCK_FILE"))
        return {
            "businessNo": business_no,
            "fileId": stable_id("FI", f"{business_no}{mode}", 32),
            "status": "P",
        }

    def _normalize_scenario(self, requested: str | None) -> str:
        candidate = requested or self.settings.default_scenario
        normalized = candidate.upper()
        if normalized not in constants.SCENARIOS:
            raise ValueError(f"Unsupported mock scenario: {requested}")
        return normalized

    def _delay_millis(self) -> int:
        return max(0, self.settings.delayed_success_millis)

    @staticmethod
    def _failed(scenario: str) -> bool:
        return scenario in {constants.FAILURE, constants.REJECTED}

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S")
