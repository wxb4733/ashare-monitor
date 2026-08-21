"""arXiv 论文监测单元测试（mock API）。"""

import pytest

from ashare_monitor.arxiv import (
    ArxivPaper,
    build_arxiv_report,
    company_aliases,
    fetch_company_papers,
)

XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2606.27924v1</id>
    <published>2026-06-26T00:00:00Z</published>
    <updated>2026-06-26T00:00:00Z</updated>
    <title>Heterogeneous Diffusion of Electric Vehicles in China</title>
    <summary>This paper studies EV diffusion with BYD data.</summary>
    <author><name>Zhang San</name>
      <arxiv:affiliation>BYD Company Limited</arxiv:affiliation></author>
    <author><name>Li Si</name>
      <arxiv:affiliation>Tsinghua University</arxiv:affiliation></author>
    <category term="econ.GN"/>
    <category term="stat.AP"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2508.12300v3</id>
    <published>2025-08-17T00:00:00Z</published>
    <updated>2025-08-17T00:00:00Z</updated>
    <title>Mutually Assured Deregulation</title>
    <summary>Regulation theory paper with no company reference.</summary>
    <author><name>Wang Wu</name>
      <arxiv:affiliation>Stanford University</arxiv:affiliation></author>
    <category term="econ.GN"/>
  </entry>
</feed>"""


def test_fetch_company_papers(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return XML

    monkeypatch.setattr("ashare_monitor.arxiv.requests.get",
                        lambda *a, **k: _Resp())
    papers = fetch_company_papers("BYD", ["BYD", "BYD Company"],
                                  max_results=10, days=730)
    # 仅保留摘要含 BYD 的第一篇；无关的 Stanford 那篇被过滤
    assert len(papers) == 1
    p = papers[0]
    assert p.title.startswith("Heterogeneous Diffusion")
    assert "BYD Company" in p.affiliation
    assert p.matched_alias == "BYD"
    assert p.published == "2026-06-26"
    assert p.link == "https://arxiv.org/abs/2606.27924"


def test_company_aliases_builtin():
    cfg = type("C", (), {"arxiv": {}})()
    company, aliases = company_aliases(cfg, "002594")
    assert company == "BYD" and "BYD" in aliases
    assert company_aliases(cfg, "300750")[0] == "CATL"


def test_company_aliases_config_override():
    cfg = type("C", (), {"arxiv": {"002594": ["BYD Auto", "FinDreams"]}})()
    company, aliases = company_aliases(cfg, "002594")
    assert company == "BYD Auto"
    assert "FinDreams" in aliases


def test_company_aliases_unknown():
    cfg = type("C", (), {"arxiv": {}})()
    assert company_aliases(cfg, "999999") == ("", [])


def test_build_arxiv_report():
    p = ArxivPaper(
        arxiv_id="2606.27924v1", title="EV Diffusion in China",
        authors="Zhang San", affiliation="BYD Company Limited",
        published="2026-06-26", updated="2026-06-26",
        summary="Studies EV diffusion.", link="https://arxiv.org/abs/2606.27924",
        categories="econ.GN,stat.AP", matched_alias="BYD",
    )
    html, md = build_arxiv_report([p], "002594", "比亚迪", "BYD", 730,
                                  as_of="2026-08-21")
    assert "arXiv 论文监测" in html
    assert "EV Diffusion in China" in html and "BYD Company" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 公司论文监测 比亚迪")
