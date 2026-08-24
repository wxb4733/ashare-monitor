"""因子表达式 DSL（qlib 风格，轻量实现）。

表达式语法（用 Python ast 解析，无需手写 tokenizer）：
    字段：close / open / high / low / volume
    常量：数字（252 / 100 / 0.5 等）
    函数：Ref(x, n)  SMA(x, n)  EMA(x, n)  RSI(x, n)  STD(x, n)
          SUM(x, n)  MEAN(x, n)  MAX(x, n)  MIN(x, n)
          ABS(x)  SQRT(x)  SIGN(x)
    运算：+ - * / % ** 以及比较 > < >= <= ==（返回 1.0/0.0）

示例：
    (close/Ref(close,20)-1)*100                      # 20 日动量（%）
    STD(close/Ref(close,1)-1,20)*SQRT(252)*100       # 20 日年化波动率（%）
    RSI(close,14)                                    # 14 日 RSI（Wilder 口径）
    SMA(close,5)-SMA(close,20)                       # 均线差（多头排列为正）

求值方式：序列化（对整个时间序列一次扫描）；滚动窗口增量维护（deque），
复杂度 O(n)（窗口函数单次扫描），不会像历史 bug 那样逐点重算 O(n²)。

返回 {date: value}——与 strategy.FACTOR_FNS 口径一致，缺失值跳过。
因子可在 factors.local.yaml 中配置（覆盖内置），见 factors.example.yaml。
"""

from __future__ import annotations

import ast
import math
from collections import deque
from pathlib import Path

# 内置因子表达式（可被 factors.local.yaml 覆盖）
BUILTIN_EXPRS: dict[str, str] = {
    "momentum": "(close/Ref(close,20)-1)*100",
    "rsi": "RSI(close,14)",
    "volatility": "STD(close/Ref(close,1)-1,20)*SQRT(252)*100",
}

_FIELDS = ("close", "open", "high", "low", "volume")


def _looks_like_expr(s: str) -> bool:
    """判断字符串是否直接是表达式（含运算符或函数调用）。"""
    upper = s.upper()
    return (any(c in s for c in "+-*/%()<>=:")
            or any(f in upper for f in (
                "REF(", "SMA(", "EMA(", "RSI(", "STD(", "SUM(",
                "MEAN(", "MAX(", "MIN(", "SQRT(", "ABS(", "SIGN(", "LOG(")))


def load_factor_exprs(paths: list[str] | None = None) -> dict[str, str]:
    """合并因子表达式：内置 < factors.example.yaml < factors.local.yaml。"""
    merged = dict(BUILTIN_EXPRS)
    for p in paths or ["factors.example.yaml", "factors.local.yaml"]:
        path = Path(p)
        if not path.exists():
            continue
        try:
            import yaml

            d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            items = d.get("factors") if isinstance(d, dict) else None
            if not isinstance(items, dict):
                items = d if isinstance(d, dict) else {}
            for k, v in items.items():
                if isinstance(v, str) and v.strip():
                    merged[str(k)] = v.strip()
        except Exception:  # noqa: BLE001
            continue
    return merged


def get_factor_fn(name: str) -> tuple[str, callable]:
    """按名字（内置/yaml 自定义）或直接表达式解析因子。

    返回 (expr_str, fn)；fn(rows: list[dict]) -> {date: value}。
    """
    exprs = load_factor_exprs()
    if name in exprs:
        e = exprs[name]
    elif _looks_like_expr(name):
        e = name
    else:
        raise RuntimeError(
            f"未知因子 '{name}'（可选：{'/'.join(exprs)}，或 --expr 直接写表达式）")
    return e, (lambda rows, expr=e: eval_factor_expr(expr, rows))


def eval_factor_expr(expr: str, rows: list[dict]) -> dict[str, float]:
    """对 K 线 rows 求值表达式，返回 {date: value}（缺失值跳过）。"""
    tree = ast.parse(expr, mode="eval")
    series = {
        f: [float(r[f]) for r in rows]
        for f in _FIELDS
    }
    n = len(rows)
    vals = _eval_node(tree.body, series, n)
    out: dict[str, float] = {}
    for i, v in enumerate(vals):
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            out[rows[i]["date"]] = float(v)
    return out


# ── AST 解释执行 ──────────────────────────────────────────────

_BINOPS = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*",
    ast.Div: "/", ast.Mod: "%", ast.Pow: "**",
}
_UNOPS = {ast.USub: "-", ast.UAdd: "+"}
_CMPOPS = {
    ast.Gt: ">", ast.Lt: "<", ast.GtE: ">=",
    ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!=",
}


def _eval_node(node, series: dict, n: int) -> list:
    """返回长度 n 的序列（元素 float | None）。"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return [float(node.value)] * n
        raise ValueError(f"不支持的常量: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in series:
            raise ValueError(f"未知字段 '{node.id}'（可选：{'/'.join(_FIELDS)}）")
        return series[node.id]
    if isinstance(node, ast.Call):
        fn = node.func.id.upper()
        args = [_eval_node(a, series, n) for a in node.args]
        return _call_fn(fn, args, n)
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        return _binop(op, _eval_node(node.left, series, n),
                      _eval_node(node.right, series, n))
    if isinstance(node, ast.UnaryOp):
        op = _UNOPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        x = _eval_node(node.operand, series, n)
        return [(-v if v is not None else None) for v in x] if op == "-" else x
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, series, n)
        for op_node, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, series, n)
            op = _CMPOPS[type(op_node)]
            out = []
            for a, b in zip(left, right):
                if a is None or b is None:
                    out.append(None)
                else:
                    try:
                        out.append(1.0 if _cmp(op, a, b) else 0.0)
                    except Exception:  # noqa: BLE001
                        out.append(None)
            left = out
        return left
    raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


def _cmp(op: str, a: float, b: float) -> bool:
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == "==":
        return abs(a - b) < 1e-12
    return abs(a - b) >= 1e-12


def _binop(op: str, a: list, b: list) -> list:
    out = []
    for x, y in zip(a, b):
        if x is None or y is None:
            out.append(None)
            continue
        try:
            if op == "+":
                out.append(x + y)
            elif op == "-":
                out.append(x - y)
            elif op == "*":
                out.append(x * y)
            elif op == "/":
                out.append(x / y if y else None)
            elif op == "%":
                out.append(x % y if y else None)
            else:  # **
                out.append(x ** y)
        except (ZeroDivisionError, ValueError, OverflowError):
            out.append(None)
    return out


def _const(args: list, idx: int = 0) -> int:
    v = args[idx][0]
    return int(round(v)) if v is not None else 0


def _call_fn(fn: str, args: list, n: int) -> list:
    x = args[0]
    if fn == "REF":
        k = _const(args, 1)
        if k <= 0:
            return x[:]
        if k >= n:
            return [None] * n
        return [None] * k + x[:-k]
    if fn in ("SUM", "MEAN", "MAX", "MIN", "SMA", "STD"):
        w = _const(args, 1)
        if w <= 0:
            return [None] * n
        if fn == "STD":
            return _roll_std(x, n, w)
        if fn == "SUM":
            return _roll_agg(x, n, w, lambda d: sum(d))
        if fn == "MEAN" or fn == "SMA":
            return _roll_agg(x, n, w, lambda d: sum(d) / len(d))
        if fn == "MAX":
            return _roll_agg(x, n, w, max)
        return _roll_agg(x, n, w, min)
    if fn == "EMA":
        return _ema(x, _const(args, 1))
    if fn == "RSI":
        return _rsi(x, _const(args, 1))
    if fn == "ABS":
        return [abs(v) if v is not None else None for v in x]
    if fn == "SQRT":
        return [math.sqrt(v) if v is not None and v >= 0 else None for v in x]
    if fn == "SIGN":
        return [(1.0 if v > 0 else (-1.0 if v < 0 else 0.0))
                if v is not None else None for v in x]
    if fn == "LOG":
        return [math.log(v) if v is not None and v > 0 else None for v in x]
    raise ValueError(f"未知函数 {fn}（可选：Ref/SMA/EMA/RSI/STD/SUM/MEAN/"
                     f"MAX/MIN/ABS/SQRT/SIGN/LOG）")


def _roll_agg(x: list, n: int, w: int, agg) -> list:
    """滚动窗口聚合（deque 增量，O(n)）。窗口含 None → 该点 None。"""
    out: list = [None] * n
    dq: deque = deque()
    for i, v in enumerate(x):
        dq.append(v)
        if len(dq) > w:
            dq.popleft()
        if len(dq) == w and all(a is not None for a in dq):
            try:
                out[i] = agg(dq)
            except (ValueError, ZeroDivisionError):
                out[i] = None
    return out


def _roll_std(x: list, n: int, w: int) -> list:
    """滚动总体标准差（与历史 _vol_factor 同口径：除以 w）。"""
    out: list = [None] * n
    dq: deque = deque()
    for i, v in enumerate(x):
        dq.append(v)
        if len(dq) > w:
            dq.popleft()
        if len(dq) == w and all(a is not None for a in dq):
            vals = list(dq)
            mean = sum(vals) / w
            var = sum((a - mean) ** 2 for a in vals) / w
            out[i] = var ** 0.5
    return out


def _ema(x: list, n: int) -> list:
    if n <= 0:
        return [None] * len(x)
    alpha = 2 / (n + 1)
    out: list = [None] * len(x)
    prev = None
    for i, v in enumerate(x):
        if v is None:
            continue
        prev = v if prev is None else alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def _rsi(x: list, n: int) -> list:
    """Wilder RSI（与 timing._rsi_series 同口径）。"""
    if len(x) <= n or n <= 0:
        return [None] * len(x)
    out: list = [None] * n
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = x[i] - x[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    for i in range(n, len(x)):
        if i > n:
            d = x[i] - x[i - 1]
            gains = (gains * (n - 1) + max(d, 0.0)) / n
            losses = (losses * (n - 1) + max(-d, 0.0)) / n
        out.append(100.0 if losses == 0 else 100 - 100 / (1 + gains / losses))
    return out
