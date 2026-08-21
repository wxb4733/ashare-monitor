"""HuggingFace 监测单元测试（mock API）。"""

import pytest

from ashare_monitor.hf import (
    HFModel,
    HFPaper,
    build_hf_report,
    fetch_models,
    fetch_papers,
    orgs_for,
)


def test_fetch_models(monkeypatch):
    monkeypatch.setattr("ashare_monitor.hf._get",
                        lambda path, params: [
                            {"id": "Qwen/Qwen3-8B",
                             "lastModified": "2026-06-01T00:00:00Z",
                             "downloads": 1234567, "likes": 890,
                             "pipeline_tag": "text-generation",
                             "tags": ["qwen", "llm"]},
                        ])
    ms = fetch_models("Qwen", limit=5)
    assert len(ms) == 1
    assert ms[0].id == "Qwen/Qwen3-8B"
    assert ms[0].downloads == 1234567
    assert ms[0].pipeline_tag == "text-generation"
    assert ms[0].last_modified == "2026-06-01"


def test_fetch_models_empty_org():
    assert fetch_models("", limit=5) == []


def test_fetch_papers(monkeypatch):
    monkeypatch.setattr("ashare_monitor.hf._get",
                        lambda path, params: [
                            {"id": "2608.19758", "title": "FlashPrefill V2",
                             "publishedAt": "2026-08-01T00:00:00Z",
                             "authors": [{"name": "Qihang Fan"}],
                             "upvotes": 12, "summary": "Block-sparse attention",
                             "organization": "Huawei"},
                        ])
    ps = fetch_papers("Huawei", limit=5)
    assert len(ps) == 1
    assert ps[0].title == "FlashPrefill V2"
    assert ps[0].published == "2026-08-01"
    assert ps[0].authors == "Qihang Fan"
    assert ps[0].link.startswith("https://huggingface.co/papers/")


def test_orgs_for_builtin():
    cfg = type("C", (), {"hf": {}})()
    org, company = orgs_for(cfg, "00700")
    assert org == "tencent" and company == "Tencent"
    assert orgs_for(cfg, "002594") == ("", "BYD")  # 无 HF 组织


def test_orgs_for_config_override():
    cfg = type("C", (), {"hf": {"002594": ["BYD-Auto", "BYD"]}})()
    org, company = orgs_for(cfg, "002594")
    assert org == "BYD-Auto" and company == "BYD"


def test_build_hf_report():
    models = [HFModel("Qwen/Qwen3-8B", "2026-06-01", 1234567, 890,
                      "text-generation", ["qwen"])]
    papers = [HFPaper("2608.19758", "FlashPrefill V2", "2026-08-01",
                      "Qihang Fan", 12, "Block-sparse", "Huawei",
                      "https://huggingface.co/papers/2608.19758")]
    html, md = build_hf_report("00700", "腾讯", "tencent", "Tencent",
                               models, papers, as_of="2026-08-21")
    assert "Hugging Face 监测" in html
    assert "Qwen/Qwen3-8B" in html and "1,234,567" in html
    assert "FlashPrefill V2" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: HuggingFace 监测 腾讯")
