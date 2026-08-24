"""因子表达式 DSL 单元测试。"""

import pytest


def _mk_rows(closes, volumes=None):
    """构造 K 线 rows（日期连续，模拟 2024-01-01 起）。"""
    rows = []
    for i, c in enumerate(closes):
        d = f"2024-01-{i % 28 + 1:02d}"
        rows.append({"date": d, "open": c, "close": c,
                     "high": c, "low": c,
                     "volume": (volumes[i] if volumes else 1000.0)})
    return rows


def test_eval_basic_arithmetic():
    from ashare_monitor.factor_dsl import eval_factor_expr

    rows = _mk_rows([10.0, 11.0, 12.0])
    out = eval_factor_expr("close*2+1", rows)
    assert out[rows[0]["date"]] == pytest.approx(21.0)
    assert out[rows[2]["date"]] == pytest.approx(25.0)


def test_eval_ref_momentum():
    from ashare_monitor.factor_dsl import eval_factor_expr

    rows = _mk_rows([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    out = eval_factor_expr("(close/Ref(close,2)-1)*100", rows)
    # i=2: 12/10-1=20%; i=5: 15/13-1
    dates = [r["date"] for r in rows]
    assert len(out) == 4            # 前 2 天无 Ref 值
    assert out[dates[2]] == pytest.approx(20.0)
    assert out[dates[5]] == pytest.approx((15 / 13 - 1) * 100)


def test_eval_sma_and_std():
    from ashare_monitor.factor_dsl import eval_factor_expr

    rows = _mk_rows([10.0, 11.0, 12.0, 13.0])
    out = eval_factor_expr("SMA(close,3)", rows)
    dates = [r["date"] for r in rows]
    assert out[dates[2]] == pytest.approx((10 + 11 + 12) / 3)
    assert out[dates[3]] == pytest.approx((11 + 12 + 13) / 3)

    std = eval_factor_expr("STD(close,3)", rows)
    # 总体标准差：sqrt(mean((x-mean)^2))，std([10,11,12]) ≈ 0.8165
    mean = (10 + 11 + 12) / 3
    exp = (((10 - mean) ** 2 + (11 - mean) ** 2 + (12 - mean) ** 2) / 3) ** 0.5
    assert std[dates[2]] == pytest.approx(exp)


def test_eval_rsi_matches_timing():
    from ashare_monitor.factor_dsl import eval_factor_expr
    from ashare_monitor.timing import _rsi_series

    closes = [10.0, 10.5, 10.2, 10.8, 11.0, 10.9, 11.2, 11.5, 11.3, 12.0]
    rows = _mk_rows(closes)
    out = eval_factor_expr("RSI(close,3)", rows)
    ref = {rows[i]["date"]: v for i, v in enumerate(_rsi_series(closes, 3))
           if v is not None}
    assert set(out) == set(ref)
    assert all(abs(out[d] - ref[d]) < 1e-9 for d in out)


def test_eval_compare_returns_bool():
    from ashare_monitor.factor_dsl import eval_factor_expr

    rows = _mk_rows([10.0, 12.0, 9.0])
    out = eval_factor_expr("close > SMA(close,2)", rows)
    dates = [r["date"] for r in rows]
    assert out[dates[1]] == pytest.approx(1.0)   # 12 > 11
    assert out[dates[2]] == pytest.approx(0.0)   # 9 < 10.5


def test_unknown_field_and_fn():
    from ashare_monitor.factor_dsl import eval_factor_expr

    rows = _mk_rows([10.0, 11.0])
    with pytest.raises(ValueError, match="未知字段"):
        eval_factor_expr("pe/close", rows)
    with pytest.raises(ValueError, match="未知函数"):
        eval_factor_expr("FOO(close,5)", rows)


def test_load_factor_exprs(tmp_path):
    from ashare_monitor.factor_dsl import BUILTIN_EXPRS, load_factor_exprs

    cfg = tmp_path / "factors.yaml"
    cfg.write_text("factors:\n  momentum20: '(close/Ref(close,20)-1)*100'\n"
                   "  my_factor: 'close/Ref(close,5)-1'\n",
                   encoding="utf-8")
    exprs = load_factor_exprs([str(cfg)])
    assert "momentum" in exprs           # 内置保留
    assert exprs["my_factor"] == "close/Ref(close,5)-1"
    # 覆盖内置
    cfg2 = tmp_path / "factors2.yaml"
    cfg2.write_text("factors:\n  momentum: '(close/Ref(close,60)-1)*100'\n",
                    encoding="utf-8")
    exprs2 = load_factor_exprs([str(cfg2)])
    assert exprs2["momentum"] == "(close/Ref(close,60)-1)*100"


def test_get_factor_fn(tmp_path, monkeypatch):
    from ashare_monitor.factor_dsl import get_factor_fn

    # 内置名
    e1, fn1 = get_factor_fn("momentum")
    assert "Ref(close,20)" in e1
    assert callable(fn1)
    # 直接表达式
    e2, _ = get_factor_fn("close/Ref(close,5)-1")
    assert e2 == "close/Ref(close,5)-1"
    # 未知名字报错
    with pytest.raises(RuntimeError, match="未知因子"):
        get_factor_fn("not_a_factor")


def test_factor_ic_with_custom_expr(tmp_path, monkeypatch):
    """IC 检验直接用 DSL 表达式（不经 FACTOR_FNS）。"""
    from ashare_monitor import strategy

    drift_map = {"600519": 0.5, "000001": 0.0, "300750": -0.05}

    def fake_load(code, market):
        rows = []
        for i in range(120):
            m = 1 + i // 30
            d = i % 30 + 1
            c = 10.0 + i * drift_map[code]
            rows.append({"date": f"2024-{m:02d}-{d:02d}", "open": c,
                         "close": c, "high": c, "low": c, "volume": 1000.0})
        return rows

    monkeypatch.setattr("ashare_monitor.storage.load_klines", fake_load)
    ic = strategy.factor_ic_test(
        ["600519", "000001", "300750"],
        "(close/Ref(close,10)-1)*100", forward_days=10)
    assert ic["n_days"] > 0
    assert -1.0 <= ic["mean_ic"] <= 1.0
