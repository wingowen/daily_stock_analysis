# -*- coding: utf-8 -*-
"""Tests for the Wyckoff service layer."""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest

from src.config import Config
from src.services.wyckoff.service import (
    WyckoffService,
    expected_last_trading_day,
    reset_wyckoff_service,
)
from src.storage import DatabaseManager


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "wyckoff_service.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    reset_wyckoff_service()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        reset_wyckoff_service()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def trigger_frame(day_offset: int = 0):
    """20 flat bars, one SOS day, one shrink pullback (LPS)."""
    rows = []
    for index in range(20):
        rows.append(
            {
                "date": f"2026-01-{index + 1 + day_offset:02d}",
                "open": 10.0,
                "high": 10.1,
                "low": 9.95,
                "close": 10.0,
                "volume": 1000.0,
                "ma20": 10.0,
                "volume_ratio": 1.0,
            }
        )
    rows.append(
        {
            "date": f"2026-01-{21 + day_offset:02d}",
            "open": 10.5,
            "high": 11.0,
            "low": 10.4,
            "close": 11.0,
            "volume": 2000.0,
            "ma20": 10.2,
            "volume_ratio": 2.0,
        }
    )
    rows.append(
        {
            "date": f"2026-01-{22 + day_offset:02d}",
            "open": 10.6,
            "high": 10.6,
            "low": 10.3,
            "close": 10.4,
            "volume": 700.0,
            "ma20": 10.2,
            "volume_ratio": 0.7,
        }
    )
    return pd.DataFrame(rows)


def trailing_frame(count: int = 6):
    """Flat bars after the trigger so a short detail window lands past it."""
    rows = []
    for index in range(count):
        rows.append(
            {
                "date": f"2026-01-{23 + index:02d}",
                "open": 10.4,
                "high": 10.5,
                "low": 10.3,
                "close": 10.4,
                "volume": 800.0,
                "ma20": 10.2,
                "volume_ratio": 0.9,
            }
        )
    return pd.DataFrame(rows)


class TestScan:
    def test_scan_returns_signal_on_trigger_date(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")
        service = WyckoffService(isolated_db)

        result = service.scan("2026-01-22")

        assert result.date == "2026-01-22"
        assert result.codes_scanned == 1
        assert len(result.signals) == 1
        signal = result.signals[0]
        assert signal.code == "600519"
        assert signal.sos_date == "2026-01-21"
        assert signal.price == pytest.approx(10.4)
        assert signal.features is not None

    def test_scan_defaults_to_latest_data_date(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")
        service = WyckoffService(isolated_db)

        result = service.scan()

        assert result.date == "2026-01-22"
        assert result.latest_data_date == "2026-01-22"
        assert len(result.signals) == 1

    def test_scan_on_date_without_trigger_is_empty(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")
        service = WyckoffService(isolated_db)

        result = service.scan("2026-01-10")

        assert result.date == "2026-01-10"
        assert result.signals == ()

    def test_scan_on_empty_database(self, isolated_db):
        result = WyckoffService(isolated_db).scan()

        assert result.date == ""
        assert result.latest_data_date is None
        assert result.signals == ()

    def test_scan_code_filter_and_limit(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")
        isolated_db.save_daily_data(trigger_frame(), "000001", "test")
        service = WyckoffService(isolated_db)

        filtered = service.scan("2026-01-22", codes=["000001"])
        limited = service.scan("2026-01-22", limit=1)

        assert [signal.code for signal in filtered.signals] == ["000001"]
        assert limited.codes_scanned == 1

    def test_repeated_scan_uses_cache_without_changing_result(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")
        service = WyckoffService(isolated_db)

        first = service.scan("2026-01-22")
        second = service.scan("2026-01-22")

        assert first == second
        assert len(service._trigger_cache) == 1  # noqa: SLF001 - cache reuse is the contract under test


class TestDetail:
    def test_detail_returns_bars_and_signals(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")

        result = WyckoffService(isolated_db).detail("600519")

        assert result.code == "600519"
        assert result.latest_data_date == "2026-01-22"
        assert len(result.bars) == 22
        assert [signal.trigger_date for signal in result.signals] == ["2026-01-22"]

    def test_detail_window_excludes_old_signals(self, isolated_db):
        frame = pd.concat([trigger_frame(), trailing_frame()], ignore_index=True)
        isolated_db.save_daily_data(frame, "600519", "test")

        result = WyckoffService(isolated_db).detail("600519", bars=5)

        assert len(result.bars) == 5
        assert result.bars[0].date == "2026-01-24"
        assert result.signals == ()

    def test_detail_unknown_code(self, isolated_db):
        result = WyckoffService(isolated_db).detail("000000")

        assert result.bars == ()
        assert result.latest_data_date is None


class TestStaleness:
    def test_expected_last_trading_day_skips_weekend(self):
        assert expected_last_trading_day(date(2026, 11, 22)) == date(2026, 11, 20)
        assert expected_last_trading_day(date(2026, 11, 19)) == date(2026, 11, 19)

    def test_is_stale_compares_against_latest_weekday(self, isolated_db):
        service = WyckoffService(isolated_db)

        assert service.is_stale("2026-11-19", today=date(2026, 11, 19)) is False
        assert service.is_stale("2026-11-18", today=date(2026, 11, 19)) is True
        assert service.is_stale(None, today=date(2026, 11, 19)) is False
