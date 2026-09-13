# 多资金方信贷接口 Mock 服务（Python）

这是一个独立部署的 HTTP Mock 服务。公司业务系统只需要在测试环境中把资金方
`baseUrl` 指向本服务，就可以使用与真实资金方相同的请求路径、交易码、公共报文
和业务响应完成授信、放款、还款及异步回调联调。

当前实现《产品备注版》选定的苏商银行26个接口，不提供Java SDK，也不需要JAR。

## 1. 技术栈

- Python 3.12
- FastAPI + Pydantic v2
- SQLAlchemy 2 + Alembic
- SQLite（本地）/ MySQL（部署）
- httpx（异步结果回调）
- pytest（接口契约和状态流转测试）
- Docker

金额和利率全部使用 `Decimal`，不会使用存在精度问题的 `float`。

## 2. 初学者先理解这一条调用链

```text
HTTP请求
  -> app/api.py：解析JSON或表单
  -> app/funders/snb.py：根据transCode选择苏商接口方法
  -> app/services/state_store.py：修改借款、计划或还款状态
  -> SQLAlchemy Session提交事务
  -> 返回苏商公共响应
```

延迟成功和回调链路：

```text
接口创建AsyncTask
  -> 后台线程只扫描带索引的INIT任务
  -> 原子领取任务
  -> 更新订单状态
  -> 发送HTTP回调
  -> 成功标记SUCCESS，失败按2/4/8秒退避重试
```

## 3. 目录说明

```text
app/
├── api.py                 HTTP入口，不写具体业务规则
├── config.py              环境变量配置
├── constants.py           26个交易码和7种Mock场景
├── database.py            Engine与Session工厂
├── models.py              四张数据库表
├── schemas.py             苏商公共请求、响应模型
├── funders/
│   ├── base.py            多资金方统一适配器接口
│   └── snb.py             苏商26个接口实现
└── services/
    ├── plan_service.py    等额本金计划计算
    ├── state_store.py     借款、计划、还款状态流转
    └── task_service.py    延迟成功、回调及重试
migrations/                Alembic数据库迁移
tests/                     单元测试和接口集成测试
```

## 4. 本地启动

Windows建议安装Python 3.12，然后在本目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
uvicorn app.main:app --reload --port 8000
```

默认使用 `data/fund_mock.db`，首次启动自动建表，不需要安装MySQL。

打开以下地址检查服务：

- Swagger：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`
- 接口清单：`http://127.0.0.1:8000/mock/snb/interfaces`

## 5. 请求示例

```http
POST /mock/snb/MOCK_APP/snb.loan.upgrade.advance.jointloan.apply
Content-Type: application/json
X-Mock-Scenario: SUCCESS
```

```json
{
  "signature": "MOCK_SIGNATURE",
  "appCode": "MOCK_APP",
  "channelSerialNo": "123456782026090100000000000001",
  "timestamp": "2026-09-01 10:00:00",
  "algorithm": "SHA256withRSA",
  "channelId": "MOCK",
  "secretKey": "MOCK_SECRET_KEY",
  "terminal": "5",
  "transCode": "snb.loan.upgrade.advance.jointloan.apply",
  "payload": {
    "merchantId": "12345678",
    "productCode": "100406",
    "businessNo": "LOAN202609010001",
    "busiAmt": "1200.00",
    "term": "3",
    "actualRate": "12.00"
  }
}
```

## 6. Mock场景

通过 `X-Mock-Scenario` 请求头控制：

| 场景 | 含义 |
|---|---|
| `SUCCESS` | 立即成功 |
| `PROCESSING` | 一直处于处理中 |
| `DELAY_SUCCESS` | 先处理中，延迟后成功并回调 |
| `FAILURE` | 失败 |
| `REJECTED` | 业务拒绝 |
| `NOT_FOUND` | 查询无记录 |
| `TIMEOUT` | 30秒后返回，用于测试客户端超时 |

## 7. 数据库保存范围

- `mock_loan_order`：借款订单和实际年利率。
- `mock_repayment_plan`：放款成功后的正式还款计划。
- `mock_repayment_order`：还款申请及本金、利息分配结果。
- `mock_async_task`：延迟状态流转和回调重试技术任务。

授信、绑卡、券、证明和文件接口即时生成确定性响应，不新增业务表。

## 8. MySQL与Alembic

复制 `.env.example` 为 `.env`，修改连接地址：

```text
FUND_MOCK_DATABASE_URL=mysql+pymysql://fund_mock:fund_mock@127.0.0.1:3306/fund_mock?charset=utf8mb4
FUND_MOCK_AUTO_CREATE_TABLES=false
```

执行迁移和启动：

```powershell
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

也可以直接执行：

```powershell
docker compose up --build
```

## 9. 运行测试

```powershell
pytest
```

测试覆盖：26个交易码、JSON和表单请求、借款计划入库、还款金额分配、延迟成功、
实际利率持久化、计划尾差和数据库状态一致性。

## 10. 接入下一家资金方

1. 在 `app/funders/` 新增资金方目录或适配器类。
2. 实现 `FunderAdapter.handle()`。
3. 新增该资金方的交易码、Pydantic报文和响应映射。
4. 在 `app/api.py` 注册新资金方URL。
5. 增加接口清单测试和核心状态流转测试。

不要把不同资金方的字段判断全部堆进苏商适配器中；资金方协议可以不同，借款订单、
还款计划和还款订单等内部领域模型应尽量复用。

