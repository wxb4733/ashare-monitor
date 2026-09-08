"""SEC 财报接入测试：三表对齐映射 + 面值陷阱 + storage currency 迁移 guard。

- mock 模块级 ``sec_financials._obb_fetch``，不触网（沙箱兼容）
- storage 迁移测试用 tmp_path 独立库，验证老库（无 currency 列）自动 ALTER
"""

from __future__ import annotations

import pandas as pd
import pytest

from ashare_monitor import sec_financials as sec
from ashare_monitor.sec_financials import fetch_sec_financials
from ashare_monitor.storage import load_financials, record_financials
from ashare_monitor.fundamentals import FinancialPeriod


def _bal_df(fy: int, assets: float, liab: float, period_end: str) -> pd.DataFrame:
    """构造 balance 假数据（SEC 原始美元值）。"""
    return pd.DataFrame([
        {"fiscal_year": fy, "period_ending": period_end,
         "total_assets": assets, "total_liabilities": liab,
         # 面值陷阱样例：普通股面值远小于权益
         "common_equity": 24_000_000.0},
    ])


def _inc_df(fy: int, rev: float, cost: float, ni: float, eps: float,
            period_end: str) -> pd.DataFrame:
    return pd.DataFrame([
        {"fiscal_year": fy, "period_ending": period_end,
         "operating_revenue": rev, "operating_cost_of_revenue": cost,
         "net_income": ni, "diluted_eps": eps},
    ])


def _cash_df(fy: int, ocf: float) -> pd.DataFrame:
    return pd.DataFrame([
        {"fiscal_year": fy, "period_ending": f"{fy-1}-12-31",
         "net_cash_from_operating_activities": ocf},
    ])


def _patch_tables(monkeypatch, tables: dict):
    """tables: {kind: list[pd.DataFrame]}，按列表顺序拼接返回。"""
    calls = {}

    def fake(kind: str, symbol: str, limit: int):
        calls.setdefault(kind, []).append(limit)
        dfs = tables[kind]
        return pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]

    monkeypatch.setattr(sec, "_obb_fetch", fake)
    return calls


# ---------- 映射核心 ----------

def test_sec_full_mapping_and_par_value_trap(monkeypatch):
    """真实量级对齐：三表映射 + 面值陷阱修正 ROE + 单位换算 + YoY。

    NVDA 风格量级：FY2026 rev $215.9B ni $120.1B assets $206.8B liab $49.5B
    → 落库亿美元: rev=2159, ni=1201, equity=1573 亿美元, ROE≈76.4%
    """
    _patch_tables(monkeypatch, {
        "balance": [
            _bal_df(2026, 206_800_000_000, 49_500_000_000, "2026-01-25"),
            _bal_df(2025, 130_500_000_000, 32_700_000_000, "2025-01-26"),
        ],
        "income": [
            _inc_df(2026, 215_900_000_000, 62_400_000_000, 120_100_000_000,
                    4.84, "2026-01-25"),
            _inc_df(2025, 130_500_000_000, 40_900_000_000, 72_900_000_000,
                    2.98, "2025-01-26"),
        ],
        "cash": [
            _cash_df(2026, 102_700_000_000),
            _cash_df(2025, 66_700_000_000),
        ],
    })
    out = fetch_sec_financials("NVDA", periods=2)
    assert len(out) == 2
    p = out[0]  # FY2026 最新在前
    assert p.report_date == "2026-01-25"
    assert p.revenue == pytest.approx(2159, rel=1e-3)      # 亿美元
    assert p.net_profit == pytest.approx(1201, rel=1e-3)
    assert p.gross_margin == pytest.approx(71.1, abs=0.3)  # (2159-624)/2159
    assert p.net_margin == pytest.approx(1201 / 2159 * 100, rel=1e-3)
    assert p.eps == pytest.approx(4.84, abs=1e-3)
    # 面值陷阱：若误用 common_equity 会得 ~500000%，恒等式应 ~76%
    assert p.roe == pytest.approx(76.4, abs=1.0)
    # YoY：与 FY2025 相邻期
    assert p.revenue_yoy == pytest.approx((2159 - 1305) / 1305 * 100, rel=1e-2)
    assert p.profit_yoy == pytest.approx((1201 - 729) / 729 * 100, rel=1e-2)
    # ocf_per_share 诚实置 None（SEC 无加权股数）
    assert p.ocf_per_share is None


def test_sec_single_period_yoy_none(monkeypatch):
    """只有一期 → YoY/利润率依赖缺项均 None，不崩。"""
    _patch_tables(monkeypatch, {
        "balance": [_bal_df(2026, 100e9, 40e9, "2026-01-25")],
        "income": [_inc_df(2026, 50e9, 20e9, 10e9, 2.0, "2026-01-25")],
        "cash": [_cash_df(2026, 12e9)],
    })
    out = fetch_sec_financials("MSFT", periods=1)
    assert len(out) == 1
    p = out[0]
    assert p.revenue_yoy is None and p.profit_yoy is None
    assert p.gross_margin == pytest.approx(60.0, rel=1e-3)
    assert p.roe is not None


def test_sec_missing_cost_col_graceful(monkeypatch):
    """缺 operating_cost_of_revenue 列 → gross_margin None 而非抛错。"""
    inc = _inc_df(2026, 50e9, 20e9, 10e9, 2.0, "2026-01-25").drop(
        columns=["operating_cost_of_revenue"])
    _patch_tables(monkeypatch, {
        "balance": [_bal_df(2026, 100e9, 40e9, "2026-01-25")],
        "income": [inc],
        "cash": [_cash_df(2026, 12e9)],
    })
    out = fetch_sec_financials("AAPL", periods=1)
    assert out[0].gross_margin is None
    assert out[0].revenue == 500  # 50e9/1e8


def test_sec_upper_colname_tolerant(monkeypatch):
    """SEC XBRL 字段大写（Revenue / NetIncomeLoss）小写不敏感容错。"""
    bal = pd.DataFrame([
        {"FiscalYear": 2026, "PeriodEnding": "2026-01-25",
         "TotalAssets": 100e9, "TotalLiabilities": 40e9},
    ])
    inc = pd.DataFrame([
        {"FiscalYear": 2026, "PeriodEnding": "2026-01-25",
         "Revenue": 50e9, "CostOfRevenue": 20e9,
         "NetIncomeLoss": 10e9, "DilutedEPS": 2.0},
    ])
    cash = pd.DataFrame([
        {"FiscalYear": 2026, "NetCashFromOperatingActivities": 12e9},
    ])
    _patch_tables(monkeypatch, {"balance": [bal], "income": [inc], "cash": [cash]})
    out = fetch_sec_financials("NVDA", periods=1)
    p = out[0]
    assert p.revenue == 500 and p.net_profit == 100
    assert p.gross_margin == pytest.approx(60.0, rel=1e-3)
    assert p.eps == 2.0


def test_sec_openbb_missing_raises(monkeypatch):
    """OpenBB 未安装 → RuntimeError（清晰提示），由降级/调用方捕获。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "openbb" or name.startswith("openbb."):
            raise ImportError("No module named 'openbb'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="OpenBB 未安装"):
        fetch_sec_financials("NVDA")


def test_sec_out_of_order_input_sorted(monkeypatch):
    """income 输入乱序仍按财年降序输出（不依赖数据源行序）。"""
    _patch_tables(monkeypatch, {
        "balance": [_bal_df(2025, 130e9, 33e9, "2025-01-26"),
                    _bal_df(2026, 207e9, 49e9, "2026-01-25")],
        "income": [_inc_df(2025, 130e9, 41e9, 73e9, 2.98, "2025-01-26"),
                   _inc_df(2026, 216e9, 62e9, 120e9, 4.84, "2026-01-25")],
        "cash": [_cash_df(2025, 67e9), _cash_df(2026, 103e9)],
    })
    out = fetch_sec_financials("NVDA", periods=2)
    assert [p.report_date for p in out] == ["2026-01-25", "2025-01-26"]
    # 对齐正确：FY2026 匹配 FY2026 balance（207e9→2070 亿）
    assert out[0].roe is not None and 60 < out[0].roe < 90


# ---------- storage currency 迁移 ----------

def _legacy_financials_db(db_path) -> None:
    """构造无 currency 列的老版 financials 表（模拟升级前库）。"""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE financials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL, name TEXT, report_date TEXT NOT NULL,
            revenue REAL, net_profit REAL, revenue_yoy REAL, profit_yoy REAL,
            roe REAL, gross_margin REAL, net_margin REAL, eps REAL,
            ocf_per_share REAL, UNIQUE(code, report_date)
        );
        INSERT INTO financials (code, report_date, revenue) VALUES ('600519', '2025-12-31', 1500);
    """)
    conn.commit(); conn.close()


def test_migration_legacy_db_gets_currency_col(tmp_path):
    """老库自动 ALTER 加 currency 列（默认 CNY 回填），原数据保留。"""
    db = tmp_path / "legacy.db"
    _legacy_financials_db(db)
    rows = load_financials("600519", db_path=db)
    assert len(rows) == 1
    assert rows[0]["currency"] == "CNY"          # 老数据回填 CNY
    assert rows[0]["revenue"] == 1500


def test_record_currency_usd_roundtrip(tmp_path):
    """美股以 currency='USD' 落库 → load 返回 USD，与 CNY 行并存不混。"""
    db = tmp_path / "mix.db"
    item = FinancialPeriod(report_date="2026-01-25", revenue=2159.0,
                           net_profit=1201.0, revenue_yoy=65.4, profit_yoy=64.7,
                           roe=76.4, gross_margin=71.1, net_margin=55.6,
                           eps=4.84, ocf_per_share=None)
    new, _ = record_financials([item], "NVDA", name="NVIDIA",
                               db_path=db, currency="USD")
    assert new == 1
    rows = load_financials("NVDA", db_path=db)
    assert rows[0]["currency"] == "USD"
    assert rows[0]["eps"] == pytest.approx(4.84)
    assert rows[0]["ocf_per_share"] is None


def test_record_currency_default_cny(tmp_path):
    """默认 currency='CNY' 零影响：A 股路径调用不变。"""
    db = tmp_path / "acn.db"
    item = FinancialPeriod(report_date="2025-12-31", revenue=8039.6,
                           net_profit=326.2, revenue_yoy=3.5, profit_yoy=-19.0,
                           roe=15.3, gross_margin=17.7, net_margin=4.1,
                           eps=3.58, ocf_per_share=6.49)
    record_financials([item], "002594", db_path=db)
    assert load_financials("002594", db_path=db)[0]["currency"] == "CNY"
