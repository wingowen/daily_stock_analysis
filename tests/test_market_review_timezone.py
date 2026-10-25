# -*- coding: utf-8 -*-
"""Regression tests for market review report timezone handling.

GitHub Actions runners execute in UTC, so bare ``datetime.now()`` rendered
UTC timestamps in the market review report footer (and could roll the report
date back a day for runs between 08:00-16:00 Beijing time). The report is a
China-market artifact consumed by domestic users, so display timestamps must
be Beijing time (UTC+8).

Covers:
- ``_now_cn()`` returns an aware datetime fixed at UTC+8
- the Chinese template review footer renders the Beijing time
- the English template review footer renders the Beijing time
- the report date (overview.date source) uses Beijing time
"""
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# Stub heavy dependencies before project imports
for _mod in ("litellm", "google.generativeai", "google.genai", "anthropic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest

from src import market_analyzer as ma
from src.market_analyzer import MarketAnalyzer, MarketOverview

CN_TZ = timezone(timedelta(hours=8))
_FIXED_CN_NOW = datetime(2026, 10, 25, 18, 30, 15, tzinfo=CN_TZ)


@pytest.fixture
def analyzer_stub(monkeypatch):
    """Build a MarketAnalyzer without running __init__, stubbing rendering deps."""
    analyzer = object.__new__(MarketAnalyzer)
    analyzer.region = "cn"
    analyzer.profile = SimpleNamespace(
        has_market_stats=True,
        has_sector_rankings=True,
        mood_index_code="000001",
    )
    monkeypatch.setattr(analyzer, "_get_review_language", lambda: "zh", raising=False)
    monkeypatch.setattr(analyzer, "_get_market_mood_text", lambda code, lang=None: "震荡", raising=False)
    monkeypatch.setattr(analyzer, "_get_turnover_unit_label", lambda: "亿", raising=False)
    monkeypatch.setattr(analyzer, "_get_market_scope_name", lambda lang=None: "A-share", raising=False)
    monkeypatch.setattr(analyzer, "_build_stats_block", lambda overview: "", raising=False)
    monkeypatch.setattr(analyzer, "_build_indices_block", lambda overview: "", raising=False)
    monkeypatch.setattr(analyzer, "_build_sector_block", lambda overview: "", raising=False)
    monkeypatch.setattr(analyzer, "_get_strategy_markdown_block", lambda lang=None: "", raising=False)
    return analyzer


def test_now_cn_is_utc_plus_eight():
    now = ma._now_cn()
    assert now.utcoffset() == timedelta(hours=8)
    # 与真实当前时间的偏差不应超过一分钟（排除时区换算误差）
    assert abs((now - datetime.now(timezone.utc)).total_seconds()) < 60


def test_chinese_template_footer_uses_beijing_time(analyzer_stub, monkeypatch):
    monkeypatch.setattr(ma, "_now_cn", lambda: _FIXED_CN_NOW)
    report = analyzer_stub._generate_template_review(
        MarketOverview(date="2026-10-25"), news=[]
    )
    assert "*复盘时间: 18:30*" in report


def test_english_template_footer_uses_beijing_time(analyzer_stub, monkeypatch):
    monkeypatch.setattr(analyzer_stub, "_get_review_language", lambda: "en", raising=False)
    monkeypatch.setattr(ma, "_now_cn", lambda: _FIXED_CN_NOW)
    report = analyzer_stub._generate_template_review(
        MarketOverview(date="2026-10-25"), news=[]
    )
    assert "*Review Time: 18:30*" in report


def test_report_date_uses_beijing_time(monkeypatch):
    """UTC 00:30 == Beijing 08:30 same day; date must not roll back a day."""
    utc_early_morning = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(ma, "_now_cn", lambda: utc_early_morning.astimezone(CN_TZ))
    assert ma._now_cn().strftime("%Y-%m-%d") == "2026-10-25"
