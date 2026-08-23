"""券商 PTrade（恒生）实盘通道占位。

PTrade 为券商程序化交易通道之一（需券商开通）。
接口与 QMT 类似：init / order_buy / order_sell / query_position。

合规：程序化交易需报备。本文件仅为架构占位。
"""


def init():  # pragma: no cover
    raise NotImplementedError("PTrade 通道占位：需券商开通后接入（合规）")


def order_buy(code, price, shares):  # pragma: no cover
    raise NotImplementedError("PTrade 通道占位")
