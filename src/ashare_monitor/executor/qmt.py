"""券商 QMT（迅投）实盘通道占位。

QMT 是券商程序化交易的主流通道（需券商开通 + 协议签署）。
接入时需实现：
    - init(): 券商 QMT 客户端初始化（账号/路径）
    - order_buy(code, price, shares): 买入委托
    - order_sell(code, price, shares): 卖出委托
    - query_position(): 持仓查询

合规：程序化交易需按 2024《程序化交易管理规定》向交易所/券商报备。
本文件仅为架构占位，未包含真实券商 API。
"""


def init():  # pragma: no cover
    raise NotImplementedError("QMT 通道占位：需券商开通后接入（合规）")


def order_buy(code, price, shares):  # pragma: no cover
    raise NotImplementedError("QMT 通道占位")
