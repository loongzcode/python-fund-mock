"""交易码和 Mock 场景常量。"""

# 场景通过 X-Mock-Scenario 请求头传入。
SUCCESS = "SUCCESS"
PROCESSING = "PROCESSING"
DELAY_SUCCESS = "DELAY_SUCCESS"
FAILURE = "FAILURE"
REJECTED = "REJECTED"
NOT_FOUND = "NOT_FOUND"
TIMEOUT = "TIMEOUT"

SCENARIOS = {SUCCESS, PROCESSING, DELAY_SUCCESS, FAILURE, REJECTED, NOT_FOUND, TIMEOUT}

# 字典同时承担“允许的交易码清单”和“接口中文名称”两个职责。
SNB_TRANSACTION_NAMES: dict[str, str] = {
    "snb.loan.upgrade.credit.jointloan.apply": "产品授信申请",
    "snb.loan.upgrade.credit.progress.jointloan.query": "授信申请进度查询",
    "snb.loan.upgrade.limit.jointloan.query": "额度利率查询",
    "snb.loan.upgrade.agreement.jointloan.query": "协议信息查询",
    "snb.loan.upgrade.advance.trial": "借款试算",
    "snb.loan.upgrade.advance.jointloan.apply": "放款申请",
    "snb.loan.upgrade.advance.progress.jointloan.query": "放款申请状态查询",
    "snb.loan.upgrade.advance.contract.jointloan.query": "已签约协议查询",
    "snb.loan.upgrade.repay.jointloan.trial": "还款试算",
    "snb.loan.upgrade.repay.jointloan.apply": "还款申请",
    "snb.loan.upgrade.repay.result.jointloan.query": "还款结果查询",
    "snb.loan.upgrade.repay.plan.jointloan.query": "还款计划查询",
    "snb.loan.upgrade.bind.card.sign": "绑卡签约",
    "snb.loan.upgrade.bind.card.sign.code.check": "绑卡签约校验",
    "snb.loan.upgrade.bind.card.info.query": "绑卡信息查询",
    "snb.loan.bind.card.deal.sync": "绑卡协议同步",
    "snb.mps.coupon.info.query": "券信息查询",
    "snb.loan.certify.apply": "结清证明申请",
    "snb.loan.certify.query": "结清证明结果查询",
    "snb.common.openid.query": "openid查询",
    "snb.loan.clbims.limit.close": "额度关闭",
    "snb.loan.payout.balance.query": "在贷余额查询",
    "snb.fsofts.filePath.upload": "文件路径上传",
    "snb.fsofts.fileStream.upload": "文件流上传",
    "snb.fsofts.file.upload.result.query": "文件上传结果查询",
    "snb.fsofts.remoteFile.download": "单笔文件下载",
}

# 给业务代码使用的交易码，避免到处复制长字符串。
CREDIT_APPLY = "snb.loan.upgrade.credit.jointloan.apply"
CREDIT_PROGRESS_QUERY = "snb.loan.upgrade.credit.progress.jointloan.query"
LIMIT_QUERY = "snb.loan.upgrade.limit.jointloan.query"
AGREEMENT_QUERY = "snb.loan.upgrade.agreement.jointloan.query"
ADVANCE_TRIAL = "snb.loan.upgrade.advance.trial"
ADVANCE_APPLY = "snb.loan.upgrade.advance.jointloan.apply"
ADVANCE_PROGRESS_QUERY = "snb.loan.upgrade.advance.progress.jointloan.query"
ADVANCE_CONTRACT_QUERY = "snb.loan.upgrade.advance.contract.jointloan.query"
REPAY_TRIAL = "snb.loan.upgrade.repay.jointloan.trial"
REPAY_APPLY = "snb.loan.upgrade.repay.jointloan.apply"
REPAY_RESULT_QUERY = "snb.loan.upgrade.repay.result.jointloan.query"
REPAY_PLAN_QUERY = "snb.loan.upgrade.repay.plan.jointloan.query"
BIND_CARD_SIGN = "snb.loan.upgrade.bind.card.sign"
BIND_CARD_CHECK = "snb.loan.upgrade.bind.card.sign.code.check"
BIND_CARD_INFO_QUERY = "snb.loan.upgrade.bind.card.info.query"
BIND_CARD_SYNC = "snb.loan.bind.card.deal.sync"
COUPON_QUERY = "snb.mps.coupon.info.query"
CERTIFY_APPLY = "snb.loan.certify.apply"
CERTIFY_QUERY = "snb.loan.certify.query"
OPEN_ID_QUERY = "snb.common.openid.query"
LIMIT_CLOSE = "snb.loan.clbims.limit.close"
PAYOUT_BALANCE_QUERY = "snb.loan.payout.balance.query"
FILE_PATH_UPLOAD = "snb.fsofts.filePath.upload"
FILE_STREAM_UPLOAD = "snb.fsofts.fileStream.upload"
FILE_UPLOAD_RESULT_QUERY = "snb.fsofts.file.upload.result.query"
FILE_DOWNLOAD = "snb.fsofts.remoteFile.download"

