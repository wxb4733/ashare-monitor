"""高股息选股 → 回填管线：队列生成与已回填比对逻辑。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backfill_screener_pipeline as pipeline  # noqa: E402


def _hit(code, name, dy):
    from ashare_monitor.screen import ScreenHit

    return ScreenHit(code=code, name=name, price=10.0, dividend_yield=dy,
                     pe=8.0, pb=1.0, market_value=2_000_000_000)


def test_pipeline_queue_generation(monkeypatch, tmp_path, capsys):
    """生成待回填队列：已回填标的排除，未回填进入队列并标优先级。"""
    hits = [_hit("601398", "工商银行", 5.2),   # 高股息 → ★ 高
            _hit("600519", "贵州茅台", 3.5),   # 已回填画像+专利
            _hit("000651", "格力电器", 4.1)]   # 中
    monkeypatch.setattr("ashare_monitor.screen.screen_dividend",
                        lambda **kw: hits)
    # 已回填：茅台（画像 + 专利）
    monkeypatch.setattr("ashare_monitor.import_data.get_all_company_profiles",
                        lambda db_path=None: {"贵州茅台酒股份有限公司": {}})
    monkeypatch.setattr("ashare_monitor.import_data.get_all_ip_assets",
                        lambda db_path=None: {"贵州茅台酒股份有限公司": {}})

    rc = pipeline.run_pipeline(top=3, min_yield=3.0)
    assert rc == 0
    out = pipeline.ROOT / "output" / "backfill_queue.json"
    queue = json.loads(out.read_text(encoding="utf-8"))
    names = {q["name"] for q in queue}
    assert names == {"工商银行", "格力电器"}     # 茅台已回填 → 排除
    by_name = {q["name"]: q for q in queue}
    assert by_name["工商银行"]["priority"] == "★ 高"
    assert by_name["工商银行"]["need_profile"] is True
    assert by_name["工商银行"]["need_ip"] is True
    assert by_name["格力电器"]["need_profile"] is True

    err = capsys.readouterr().err
    assert not err


def test_pipeline_fetch_failure(monkeypatch, tmp_path, capsys):
    """数据源不可用时：返回非零并输出本机运行指引。"""
    def _boom(**kw):
        raise RuntimeError("东财 push2 网络受限")

    monkeypatch.setattr("ashare_monitor.screen.screen_dividend", _boom)
    rc = pipeline.run_pipeline(top=15, min_yield=3.0)
    assert rc == 1
    out = capsys.readouterr().out
    assert "本机运行" in out
