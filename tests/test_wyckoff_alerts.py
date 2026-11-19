# -*- coding: utf-8 -*-
"""Tests for the Wyckoff -> alert-center bridge."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

try:  # optional dependency, absent from some local virtualenvs
    import fin_primitives  # noqa: F401
except ModuleNotFoundError:
    sys.modules["fin_primitives"] = MagicMock()

from src.config import Config
from src.services.alert_service import AlertService
from src.services.wyckoff.alerts import (
    ALERT_SOURCE,
    WyckoffAlertBridge,
    build_rule_plans,
    sync_wyckoff_alerts,
)
from src.services.wyckoff.models import (
    SpringFeature,
    TestFeature,
    TrendFeature,
    WyckoffFeatures,
)
from src.services.wyckoff.service import ScanResult, SignalRecord
from src.storage import DatabaseManager

FEATURES = WyckoffFeatures(
    spring=SpringFeature(detected=False, reason="no_breakdown"),
    test=TestFeature(detected=False, reason="no_shrink_day"),
    trend=TrendFeature(ratio=1.0, up_days=1, down_days=1),
)


def make_signal(
    *,
    code: str = "600519",
    trigger_date: str = "2026-01-22",
    price: float = 10.4,
    sos_high: float = 11.0,
    trigger_low: float = 10.3,
) -> SignalRecord:
    return SignalRecord(
        code=code,
        trigger_date=trigger_date,
        sos_date="2026-01-21",
        price=price,
        ma20=10.2,
        volume_ratio=0.7,
        sos_high=sos_high,
        trigger_low=trigger_low,
        features=FEATURES,
    )


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "wyckoff_alerts.db")
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


class TestBuildRulePlans:
    def test_builds_two_independent_rules(self):
        plans = build_rule_plans(make_signal(), today=date(2026, 1, 22))

        assert len(plans) == 2
        invalidation, confirmation = plans
        assert invalidation.direction == "below"
        assert invalidation.price == 10.3
        assert invalidation.severity == "critical"
        assert confirmation.direction == "above"
        assert confirmation.price == 11.0
        assert confirmation.severity == "info"
        assert invalidation.key != confirmation.key
        assert invalidation.expires_at == datetime(2026, 2, 21, 0, 0)

    def test_skips_confirmation_when_already_above_sos_high(self):
        plans = build_rule_plans(make_signal(price=11.2), today=date(2026, 1, 22))

        assert [plan.direction for plan in plans] == ["below"]

    def test_skips_invalid_prices(self):
        plans = build_rule_plans(
            make_signal(sos_high=float("nan"), trigger_low=-1.0),
            today=date(2026, 1, 22),
        )

        assert plans == ()

    def test_expired_signal_is_skipped(self):
        plans = build_rule_plans(make_signal(), expire_days=5, today=date(2026, 3, 1))

        assert plans == ()

    def test_zero_expire_days_never_expires(self):
        plans = build_rule_plans(make_signal(), expire_days=0, today=date(2030, 1, 1))

        assert len(plans) == 2
        assert all(plan.expires_at is None for plan in plans)


class TestBridgeWrites:
    def test_creates_two_rules_with_wyckoff_source(self, isolated_db):
        service = AlertService(isolated_db)

        result = WyckoffAlertBridge(service).sync([make_signal()], today=date(2026, 1, 22))

        assert (result.created, result.existing, result.failed) == (2, 0, 0)
        listing = service.list_rules(source=ALERT_SOURCE, page_size=50)
        assert listing["total"] == 2
        rules = {item["parameters"]["direction"]: item for item in listing["items"]}
        assert rules["below"]["parameters"]["price"] == 10.3
        assert rules["above"]["parameters"]["price"] == 11.0
        assert all(item["source"] == ALERT_SOURCE for item in listing["items"])
        assert all(item["expires_at"] for item in listing["items"])
        assert rules["below"]["id"] != rules["above"]["id"]

    def test_rerun_is_idempotent(self, isolated_db):
        service = AlertService(isolated_db)
        bridge = WyckoffAlertBridge(service)

        first = bridge.sync([make_signal()], today=date(2026, 1, 22))
        second = bridge.sync([make_signal()], today=date(2026, 1, 22))

        assert first.created == 2
        assert (second.created, second.existing) == (0, 2)
        assert service.list_rules(source=ALERT_SOURCE, page_size=50)["total"] == 2

    def test_single_failure_is_not_fatal(self, isolated_db):
        class FlakyAlertService(AlertService):
            def __init__(self, db):
                super().__init__(db)
                self.calls = 0

            def create_rule(self, payload, *, source="api"):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("boom")
                return super().create_rule(payload, source=source)

        service = FlakyAlertService(isolated_db)

        result = WyckoffAlertBridge(service).sync([make_signal()], today=date(2026, 1, 22))

        assert (result.created, result.failed) == (1, 1)
        assert service.list_rules(source=ALERT_SOURCE, page_size=50)["total"] == 1

    def test_expired_signal_writes_nothing(self, isolated_db):
        service = AlertService(isolated_db)

        result = WyckoffAlertBridge(service, expire_days=1).sync(
            [make_signal()], today=date(2026, 6, 1)
        )

        assert result.created == 0
        assert result.expired == 1
        assert service.list_rules(source=ALERT_SOURCE, page_size=50)["total"] == 0


class FakeConfig:
    def __init__(self, *, wyckoff=True, alerts=True, expire_days=30):
        self.wyckoff_enabled = wyckoff
        self.wyckoff_alerts_enabled = alerts
        self.wyckoff_alert_expire_days = expire_days


class FakeScanService:
    def __init__(self, signals):
        self._signals = tuple(signals)
        self.calls = 0

    def scan(self, target_date=None):
        self.calls += 1
        return ScanResult(
            date="2026-01-22",
            latest_data_date="2026-01-22",
            is_stale=False,
            signals=self._signals,
            codes_scanned=len(self._signals),
            codes_without_data=0,
        )


class TestSyncEntrypoint:
    def test_disabled_config_is_a_no_op(self, isolated_db):
        service = AlertService(isolated_db)
        scan_service = FakeScanService([make_signal()])

        result = sync_wyckoff_alerts(
            FakeConfig(alerts=False),
            service=scan_service,
            bridge=WyckoffAlertBridge(service),
        )

        assert result.disabled is True
        assert scan_service.calls == 0
        assert service.list_rules(source=ALERT_SOURCE, page_size=50)["total"] == 0

    def test_enabled_config_scans_and_writes(self, isolated_db):
        service = AlertService(isolated_db)
        scan_service = FakeScanService([make_signal()])

        result = sync_wyckoff_alerts(
            FakeConfig(),
            service=scan_service,
            bridge=WyckoffAlertBridge(service),
            today=date(2026, 1, 22),
        )

        assert scan_service.calls == 1
        assert result.created == 2
        assert service.list_rules(source=ALERT_SOURCE, page_size=50)["total"] == 2


class TestAlertRuleExpiry:
    def test_legacy_table_gets_expires_at_column(self, tmp_path):
        import sqlite3

        legacy_path = tmp_path / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("CREATE TABLE alert_rules (id INTEGER PRIMARY KEY, name VARCHAR(64))")

        old_database_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(legacy_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        try:
            DatabaseManager.get_instance()
            with sqlite3.connect(legacy_path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(alert_rules)")}
            assert "expires_at" in columns
        finally:
            DatabaseManager.reset_instance()
            Config.reset_instance()
            if old_database_path is None:
                os.environ.pop("DATABASE_PATH", None)
            else:
                os.environ["DATABASE_PATH"] = old_database_path

    def test_expired_rules_are_not_loaded(self, isolated_db):
        from src.repositories.alert_repo import AlertRepository

        repo = AlertRepository(isolated_db)
        repo.create_rule(
            {
                "name": "expired",
                "target_scope": "single_symbol",
                "target": "600519",
                "alert_type": "price_cross",
                "parameters": '{"direction": "below", "price": 10.0}',
                "severity": "info",
                "enabled": True,
                "source": "wyckoff",
                "cooldown_policy": None,
                "notification_policy": None,
                "expires_at": datetime(2020, 1, 1),
            }
        )
        repo.create_rule(
            {
                "name": "active",
                "target_scope": "single_symbol",
                "target": "600519",
                "alert_type": "price_cross",
                "parameters": '{"direction": "above", "price": 11.0}',
                "severity": "info",
                "enabled": True,
                "source": "wyckoff",
                "cooldown_policy": None,
                "notification_policy": None,
                "expires_at": None,
            }
        )

        enabled = repo.list_enabled_rules(limit=10)

        assert [row.name for row in enabled] == ["active"]

    def test_expires_at_round_trips_through_service(self, isolated_db):
        service = AlertService(isolated_db)

        created = service.create_rule(
            {
                "target_scope": "single_symbol",
                "target": "600519",
                "alert_type": "price_cross",
                "parameters": {"direction": "below", "price": 10.0},
                "expires_at": "2026-02-21T00:00:00",
            },
            source=ALERT_SOURCE,
        )

        assert created["expires_at"] == "2026-02-21T00:00:00"
        fetched = service.get_rule(created["id"])
        assert fetched["expires_at"] == "2026-02-21T00:00:00"

        updated = service.update_rule(created["id"], {"expires_at": None})
        assert updated["expires_at"] is None

    def test_invalid_expires_at_is_rejected(self, isolated_db):
        from src.services.alert_service import AlertServiceError

        service = AlertService(isolated_db)

        with pytest.raises(AlertServiceError):
            service.create_rule(
                {
                    "target_scope": "single_symbol",
                    "target": "600519",
                    "alert_type": "price_cross",
                    "parameters": {"direction": "below", "price": 10.0},
                    "expires_at": "not-a-date",
                }
            )
