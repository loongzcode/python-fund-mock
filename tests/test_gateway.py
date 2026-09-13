"""苏商HTTP网关和业务状态流转测试。"""

from typing import Any

from fastapi.testclient import TestClient

from app import constants


def gateway_request(
    app_code: str, trans_code: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """构造带公共字段的标准苏商请求。"""

    return {
        "signature": "MOCK_SIGNATURE",
        "appCode": app_code,
        "channelSerialNo": "123456782026090100000000000001",
        "timestamp": "2026-09-01 10:00:00",
        "algorithm": "SHA256withRSA",
        "channelId": "MOCK",
        "secretKey": "MOCK_SECRET_KEY",
        "terminal": "5",
        "transCode": trans_code,
        "payload": payload,
    }


def invoke(
    client: TestClient,
    app_code: str,
    trans_code: str,
    payload: dict[str, Any],
    scenario: str | None = None,
):
    """调用指定交易码并校验公共层响应成功。"""

    headers = {"X-Mock-Scenario": scenario} if scenario else {}
    response = client.post(
        f"/mock/snb/{app_code}/{trans_code}",
        json=gateway_request(app_code, trans_code, payload),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["respCode"] == "00000000"
    return response


def test_exposes_only_twenty_six_product_selected_interfaces(client: TestClient):
    """接口清单必须严格等于产品选定的26个接口。"""

    response = client.get("/mock/snb/interfaces")
    assert response.status_code == 200
    assert len(response.json()) == 26
    assert len(constants.SNB_TRANSACTION_NAMES) == 26


def test_persists_loan_plans_and_repayment(client: TestClient):
    """验证放款、计划、还款和借据余额使用同一份数据库状态。"""

    app_code = "MOCK_APP"
    loan_payload = {
        "merchantId": "12345678",
        "productCode": "100406",
        "businessNo": "LOAN-PY-0001",
        "busiAmt": "1200.00",
        "term": "3",
        "actualRate": "18.00",
    }
    apply = invoke(
        client, app_code, constants.ADVANCE_APPLY, loan_payload
    ).json()["payload"]
    assert apply["status"] == "S"
    payout_no = apply["payoutNo"]

    query_payload = {
        "merchantId": "12345678",
        "businessNo": "LOAN-PY-0001",
        "payoutNo": payout_no,
    }
    plans = invoke(
        client, app_code, constants.REPAY_PLAN_QUERY, query_payload
    ).json()["payload"]["repayPlanList"]
    assert len(plans) == 3

    repayment_payload = {
        "merchantId": "12345678",
        "businessNo": "REPAY-PY-0001",
        "payoutNo": payout_no,
        "repayType": "1",
        "repayAmt": "400.00",
    }
    repayment = invoke(
        client, app_code, constants.REPAY_APPLY, repayment_payload
    ).json()["payload"]
    assert repayment["status"] == "S"
    assert repayment["repayAmt"] == "400.00"

    loan = invoke(
        client, app_code, constants.ADVANCE_PROGRESS_QUERY, query_payload
    ).json()["payload"]
    # 首期利息为18元，因此400元先还18元利息，再还382元本金。
    assert loan["duebillInfo"]["balance"] == "818.00"


def test_delayed_success_uses_saved_rate_and_matches_trial(client: TestClient):
    """延迟成功也必须使用申请时保存的12%利率，不能退回默认18%。"""

    app_code = "MOCK_APP"
    payload = {
        "merchantId": "12345678",
        "productCode": "100406",
        "businessNo": "LOAN-PY-DELAY-0001",
        "busiAmt": "1200.00",
        "term": "3",
        "actualRate": "12.00",
    }
    trial = invoke(client, app_code, constants.ADVANCE_TRIAL, payload).json()["payload"]
    apply = invoke(
        client,
        app_code,
        constants.ADVANCE_APPLY,
        payload,
        constants.DELAY_SUCCESS,
    ).json()["payload"]
    assert apply["status"] == "P"

    # 测试配置把延迟设为0，手动执行一次任务扫描即可完成放款。
    client.app.state.task_worker.run_due_tasks_once()
    query_payload = {
        "merchantId": "12345678",
        "businessNo": "LOAN-PY-DELAY-0001",
        "payoutNo": apply["payoutNo"],
    }
    persisted = invoke(
        client, app_code, constants.REPAY_PLAN_QUERY, query_payload
    ).json()["payload"]["repayPlanList"]

    assert len(persisted) == len(trial["planList"])
    assert [item["intAmt"] for item in persisted] == ["12.00", "8.00", "4.00"]
    assert [item["intAmt"] for item in persisted] == [
        item["intAmt"] for item in trial["planList"]
    ]


def test_all_twenty_six_transaction_codes_have_routes(client: TestClient):
    """逐个调用26个交易码，防止新增清单后忘记实现处理方法。"""

    app_code = "SMOKE_APP"
    payload: dict[str, Any] = {
        "merchantId": "87654321",
        "productCode": "100406",
        "businessNo": "LOAN-PY-SMOKE-0001",
        "busiAmt": "600.00",
        "repayAmt": "100.00",
        "term": "3",
        "actualRate": "18.00",
        "certNo": "320100199001010000",
    }
    loan = invoke(client, app_code, constants.ADVANCE_APPLY, payload).json()["payload"]
    payload["payoutNo"] = loan["payoutNo"]

    for index, trans_code in enumerate(constants.SNB_TRANSACTION_NAMES, start=1):
        if trans_code == constants.ADVANCE_APPLY:
            continue
        request_payload = dict(payload)
        request_payload["businessNo"] = (
            "REPAY-PY-SMOKE-0001"
            if trans_code == constants.REPAY_APPLY
            else f"SMOKE-PY-{index}"
        )
        invoke(client, app_code, trans_code, request_payload)


def test_form_request_is_supported(client: TestClient):
    """资金方文档中的表单提交方式也必须能够解析payload JSON。"""

    trans_code = constants.OPEN_ID_QUERY
    body = gateway_request(
        "FORM_APP", trans_code, {"businessNo": "FORM-001", "certNo": "123"}
    )
    import json

    body["payload"] = json.dumps(body["payload"], ensure_ascii=False)
    response = client.post(
        f"/mock/snb/FORM_APP/{trans_code}",
        data=body,
    )
    assert response.status_code == 200
    assert response.json()["payload"]["businessNo"] == "FORM-001"

