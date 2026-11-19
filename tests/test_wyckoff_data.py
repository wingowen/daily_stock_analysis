# -*- coding: utf-8 -*-
"""Tests for the Wyckoff data access layer."""

from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from src.config import Config
from src.services.wyckoff.data import DailySeries, WyckoffDataProvider, to_daily_bar
from src.services.wyckoff.models import DailyBar
from src.storage import DatabaseManager


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "wyckoff_data.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def daily_frame(rows):
    return pd.DataFrame(rows)


def row(day: str, close: float, **overrides):
    base = {
        "date": day,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1000.0,
        "ma20": close,
        "volume_ratio": 1.0,
    }
    base.update(overrides)
    return base


class TestLoadSeries:
    def test_returns_full_history_in_ascending_order(self, isolated_db):
        isolated_db.save_daily_data(
            daily_frame(
                [
                    row("2026-01-07", 102.0),
                    row("2026-01-05", 100.0),
                    row("2026-01-06", 101.0),
                ]
            ),
            "600519",
            "test",
        )

        series = WyckoffDataProvider(isolated_db).load_series("600519")

        assert series.bar_count == 3
        assert [bar.date for bar in series.bars] == ["2026-01-05", "2026-01-06", "2026-01-07"]
        assert series.start_date == "2026-01-05"
        assert series.end_date == "2026-01-07"
        latest = series.bars[-1]
        assert latest.close == pytest.approx(102.0)
        assert latest.high == pytest.approx(102.0 * 1.01)
        assert latest.low == pytest.approx(102.0 * 0.99)
        assert latest.ma20 == pytest.approx(102.0)
        assert latest.volume_ratio == pytest.approx(1.0)

    def test_explicit_range_is_honoured(self, isolated_db):
        isolated_db.save_daily_data(
            daily_frame([row("2026-01-05", 100.0), row("2026-01-06", 101.0), row("2026-01-07", 102.0)]),
            "600519",
            "test",
        )

        series = WyckoffDataProvider(isolated_db).load_series(
            "600519",
            start_date=date(2026, 1, 6),
            end_date=date(2026, 1, 7),
        )

        assert [bar.date for bar in series.bars] == ["2026-01-06", "2026-01-07"]

    def test_unknown_code_returns_empty_series(self, isolated_db):
        series = WyckoffDataProvider(isolated_db).load_series("000000")

        assert series.is_empty
        assert series.bar_count == 0
        assert series.start_date is None
        assert series.end_date is None

    def test_missing_indicator_stays_none(self, isolated_db):
        isolated_db.save_daily_data(
            daily_frame([row("2026-01-05", 100.0, ma20=None, volume_ratio=None)]),
            "600519",
            "test",
        )

        bar = WyckoffDataProvider(isolated_db).load_series("600519").bars[0]

        assert bar.ma20 is None
        assert bar.volume_ratio is None

    def test_load_many_keeps_empty_series(self, isolated_db):
        isolated_db.save_daily_data(daily_frame([row("2026-01-05", 100.0)]), "600519", "test")

        series_list = WyckoffDataProvider(isolated_db).load_series_many(["600519", "000000"])

        assert [series.code for series in series_list] == ["600519", "000000"]
        assert [series.bar_count for series in series_list] == [1, 0]


class TestConversion:
    def test_non_finite_values_become_none(self):
        stock_row = SimpleNamespace(
            date=date(2026, 1, 5),
            open=float("nan"),
            high=float("inf"),
            low=None,
            close=100.0,
            volume=float("-inf"),
            ma20=99.0,
            volume_ratio=None,
        )

        bar = to_daily_bar(stock_row)

        assert bar.date == "2026-01-05"
        assert bar.open is None
        assert bar.high is None
        assert bar.low is None
        assert bar.volume is None
        assert bar.close == pytest.approx(100.0)
        assert bar.ma20 == pytest.approx(99.0)

    def test_series_rejects_unsorted_bars(self):
        bars = (DailyBar(date="2026-01-06", close=1.0), DailyBar(date="2026-01-05", close=1.0))

        with pytest.raises(ValueError):
            DailySeries(code="600519", bars=bars)

    def test_series_rejects_duplicate_dates(self):
        bars = (DailyBar(date="2026-01-05", close=1.0), DailyBar(date="2026-01-05", close=2.0))

        with pytest.raises(ValueError):
            DailySeries(code="600519", bars=bars)
