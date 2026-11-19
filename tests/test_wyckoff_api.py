# -*- coding: utf-8 -*-
"""Tests for the Wyckoff read-only API."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

try:  # 可选原生指标依赖；缺失时用桩避免整包导入失败，本测试不覆盖 RSI。
    import fin_primitives  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on local environment
    sys.modules["fin_primitives"] = MagicMock()

from api.v1.endpoints import wyckoff as wyckoff_endpoint
from src.config import Config
from src.services.wyckoff.service import reset_wyckoff_service
from src.storage import DatabaseManager

PREFIX = "/api/v1/wyckoff"


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "wyckoff_api.db")
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


def trigger_frame():
    """Flat bars, one SOS day, one shrink pullback.

    The flat bars keep ``low == ma20`` so no Spring is formed: this fixture is
    for the trigger path, and the "feature absent" branch must stay reachable.
    """
    rows = []
    for index in range(20):
        rows.append(
            {
                "date": f"2026-01-{index + 1:02d}",
                "open": 10.0,
                "high": 10.1,
                "low": 10.0,
                "close": 10.0,
                "volume": 1000.0,
                "ma20": 10.0,
                "volume_ratio": 1.0,
            }
        )
    rows.append(
        {
            "date": "2026-01-21",
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
            "date": "2026-01-22",
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


def client(enabled: bool) -> TestClient:
    app = FastAPI()
    app.include_router(wyckoff_endpoint.router, prefix=PREFIX)
    app.dependency_overrides[wyckoff_endpoint.get_config_dep] = (
        lambda: SimpleNamespace(wyckoff_enabled=enabled)
    )
    return TestClient(app)


class TestFeatureFlag:
    def test_disabled_returns_403(self, isolated_db):
        response = client(enabled=False).get(f"{PREFIX}/signals")

        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "wyckoff_disabled"

    def test_disabled_blocks_detail(self, isolated_db):
        response = client(enabled=False).get(f"{PREFIX}/detail/600519")

        assert response.status_code == 403


class TestSignalsEndpoint:
    def test_empty_database_returns_empty_payload(self, isolated_db):
        response = client(enabled=True).get(f"{PREFIX}/signals")

        assert response.status_code == 200
        payload = response.json()
        assert payload["date"] == ""
        assert payload["total"] == 0
        assert payload["signals"] == []

    def test_returns_signal_with_features(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")

        response = client(enabled=True).get(f"{PREFIX}/signals", params={"date": "2026-01-22"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["date"] == "2026-01-22"
        assert payload["latest_data_date"] == "2026-01-22"
        assert payload["total"] == 1
        signal = payload["signals"][0]
        assert signal["code"] == "600519"
        assert signal["sos_date"] == "2026-01-21"
        assert signal["features"]["spring"]["detected"] is False
        assert signal["features"]["spring"]["reason"]

    def test_defaults_to_latest_date(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")

        payload = client(enabled=True).get(f"{PREFIX}/signals").json()

        assert payload["date"] == "2026-01-22"
        assert payload["total"] == 1

    def test_codes_filter(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")
        isolated_db.save_daily_data(trigger_frame(), "000001", "test")

        payload = client(enabled=True).get(
            f"{PREFIX}/signals",
            params={"date": "2026-01-22", "codes": "000001"},
        ).json()

        assert [item["code"] for item in payload["signals"]] == ["000001"]

    def test_invalid_date_is_rejected(self, isolated_db):
        response = client(enabled=True).get(f"{PREFIX}/signals", params={"date": "not-a-date"})

        assert response.status_code == 422


class TestDetailEndpoint:
    def test_returns_bars(self, isolated_db):
        isolated_db.save_daily_data(trigger_frame(), "600519", "test")

        response = client(enabled=True).get(f"{PREFIX}/detail/600519")

        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == "600519"
        assert len(payload["bars"]) == 22
        assert payload["bars"][-1]["date"] == "2026-01-22"
        assert payload["bars"][-1]["high"] == pytest.approx(10.6)

    def test_unknown_code_returns_404(self, isolated_db):
        response = client(enabled=True).get(f"{PREFIX}/detail/000000")

        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "wyckoff_no_data"

    def test_bars_below_minimum_is_rejected(self, isolated_db):
        response = client(enabled=True).get(f"{PREFIX}/detail/600519", params={"bars": 5})

        assert response.status_code == 422
