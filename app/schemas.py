"""苏商公共请求和公共响应的数据模型。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SnbGatewayRequest(BaseModel):
    """苏商公共请求报文，交易独有字段统一放入 ``payload``。"""

    signature: str | None = None
    app_code: str | None = Field(default=None, alias="appCode")
    channel_serial_no: str | None = Field(default=None, alias="channelSerialNo")
    timestamp: str | None = None
    algorithm: str | None = None
    device_id: str | None = Field(default=None, alias="deviceId")
    channel_id: str | None = Field(default=None, alias="channelId")
    secret_key: str | None = Field(default=None, alias="secretKey")
    trans_code: str | None = Field(default=None, alias="transCode")
    terminal: str | None = None
    gps: str | None = None
    ip_address: str | None = Field(default=None, alias="ipAddress")
    mac_address: str | None = Field(default=None, alias="macAddress")
    os_version: str | None = Field(default=None, alias="osVersion")
    open_id: str | None = Field(default=None, alias="openId")
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SnbGatewayResponse(BaseModel):
    """苏商公共响应报文。"""

    resp_code: str = Field(alias="respCode")
    resp_msg: str = Field(alias="respMsg")
    secret_key: str = Field(default="MOCK_SECRET_KEY", alias="secretKey")
    channel_serial_no: str | None = Field(default=None, alias="channelSerialNo")
    algorithm: str = "SHA256withRSA"
    charset: str = "UTF-8"
    serial_no: str = Field(default="", alias="serialNo")
    signature: str = "MOCK_SIGNATURE"
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def success(
        cls,
        channel_serial_no: str | None,
        serial_no: str,
        payload: dict[str, Any],
    ) -> "SnbGatewayResponse":
        """创建公共层成功响应。"""

        return cls(
            respCode="00000000",
            respMsg="ok",
            channelSerialNo=channel_serial_no,
            serialNo=serial_no,
            payload=payload,
        )

    @classmethod
    def failure(
        cls,
        channel_serial_no: str | None,
        code: str,
        message: str,
    ) -> "SnbGatewayResponse":
        """创建公共层失败响应。"""

        return cls(
            respCode=code,
            respMsg=message,
            channelSerialNo=channel_serial_no,
            payload={},
        )

