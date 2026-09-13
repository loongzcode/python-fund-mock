"""FastAPI HTTP 路由。

HTTP 层只处理协议相关工作：解析 JSON/表单、创建数据库事务、选择资金方适配器、
把异常转换成统一响应。具体授信、放款和还款规则不写在 Controller 中。
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text as sql_text

from app.constants import SNB_TRANSACTION_NAMES
from app.funders.snb import SnbAdapter
from app.schemas import SnbGatewayRequest, SnbGatewayResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    """健康检查同时执行一条最小SQL，确认数据库连接可用。"""

    session_factory = request.app.state.session_factory
    with session_factory() as session:
        session.execute(sql_text("SELECT 1"))
    return {"status": "UP"}


@router.get("/mock/snb/interfaces")
def snb_interfaces() -> list[dict[str, str]]:
    """返回产品选定的26个苏商交易码。"""

    return [
        {"transCode": code, "name": name}
        for code, name in SNB_TRANSACTION_NAMES.items()
    ]


@router.post("/mock/snb/{app_code}/{trans_code}")
async def snb_gateway(
    app_code: str,
    trans_code: str,
    request: Request,
) -> JSONResponse:
    """统一苏商网关，同时兼容JSON和表单请求。"""

    channel_serial_no: str | None = None
    session_factory = request.app.state.session_factory
    settings = request.app.state.settings

    try:
        raw_request = await _read_request(request)
        gateway_request = SnbGatewayRequest.model_validate(raw_request)
        channel_serial_no = gateway_request.channel_serial_no

        # 每个HTTP请求使用一个独立Session；成功统一commit，异常统一rollback。
        with session_factory() as session:
            try:
                adapter = SnbAdapter(session, settings)
                response = await adapter.handle(
                    app_code,
                    trans_code,
                    gateway_request,
                    request.headers.get("X-Mock-Scenario"),
                )
                session.commit()
            except Exception:
                session.rollback()
                raise

        return JSONResponse(
            status_code=200,
            content=response.model_dump(by_alias=True),
        )
    except (ValueError, ValidationError, json.JSONDecodeError) as exception:
        response = SnbGatewayResponse.failure(
            channel_serial_no, "FSOS0004", str(exception)
        )
        return JSONResponse(
            status_code=400,
            content=response.model_dump(by_alias=True),
        )
    except Exception:
        logger.exception("Unhandled mock gateway error")
        response = SnbGatewayResponse.failure(
            channel_serial_no, "00999999", "Mock server error"
        )
        return JSONResponse(
            status_code=500,
            content=response.model_dump(by_alias=True),
        )


async def _read_request(request: Request) -> dict[str, Any]:
    """根据 Content-Type 把HTTP请求转换成普通字典。"""

    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        return body

    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        result: dict[str, Any] = {key: form.get(key) for key in form.keys()}
        raw_payload = result.get("payload")
        if raw_payload is None or str(raw_payload).strip() == "":
            result["payload"] = {}
        else:
            payload = json.loads(str(raw_payload))
            if not isinstance(payload, dict):
                raise ValueError("Form field payload must be a JSON object")
            result["payload"] = payload
        return result

    raise ValueError(
        "Content-Type must be application/json or application/x-www-form-urlencoded"
    )

