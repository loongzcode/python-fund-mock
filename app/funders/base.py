"""资金方适配器抽象接口。"""

from abc import ABC, abstractmethod

from app.schemas import SnbGatewayRequest, SnbGatewayResponse


class FunderAdapter(ABC):
    """每接入一家资金方，都实现一次这个统一入口。"""

    @abstractmethod
    async def handle(
        self,
        path_app_code: str,
        path_trans_code: str,
        request: SnbGatewayRequest,
        requested_scenario: str | None,
    ) -> SnbGatewayResponse:
        """校验公共报文、路由交易码并返回资金方格式响应。"""

