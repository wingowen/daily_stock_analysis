# -*- coding: utf-8 -*-
"""Tests for the daily indicator backfill script."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from scripts.backfill_daily_indicators import apply_plans, build_plans, main
from src.config import Config
from src.storage import DatabaseManager, StockDaily


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "backfill.db")
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


def rows_without_indicators(closes):
    return pd.DataFrame(
        [
            {
                "date": f"2026-01-{index + 1:02d}",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
            }
            for index, close in enumerate(closes)
        ]
    )


def stored(isolated_db, code):
    with isolated_db.get_session() as session:
        records = (
            session.query(StockDaily)
            .filter(StockDaily.code == code)
            .order_by(StockDaily.date)
            .all()
        )
        return [(record.date, record.ma20, record.volume_ratio) for record in records]


class TestBackfill:
    def test_fills_missing_indicators_with_upstream_formula(self, isolated_db):
        isolated_db.save_daily_data(rows_without_indicators([10.0, 11.0, 12.0, 13.0, 14.0]), "600519", "test")

        plans, totals = build_plans(isolated_db)
        assert totals.codes_affected == 1
        assert totals.rows_planned == 5

        assert apply_plans(isolated_db, plans) == 5

        values = stored(isolated_db, "600519")
        assert [round(ma20, 2) for _, ma20, _ in values] == [10.0, 10.5, 11.0, 11.5, 12.0]
        assert [round(ratio, 2) for _, _, ratio in values] == [1.0, 1.0, 1.0, 1.0, 1.0]

    def test_is_idempotent(self, isolated_db):
        isolated_db.save_daily_data(rows_without_indicators([10.0, 11.0]), "600519", "test")
        plans, _ = build_plans(isolated_db)
        apply_plans(isolated_db, plans)

        plans_again, totals_again = build_plans(isolated_db)

        assert plans_again == []
        assert totals_again.rows_planned == 0

    def test_keeps_existing_valid_values(self, isolated_db):
        frame = rows_without_indicators([10.0])
        frame["ma20"] = [123.45]
        isolated_db.save_daily_data(frame, "600519", "test")

        plans, _ = build_plans(isolated_db)
        apply_plans(isolated_db, plans)

        values = stored(isolated_db, "600519")
        assert values[0][1] == pytest.approx(123.45)
        assert values[0][2] == pytest.approx(1.0)

    def test_rows_without_close_are_reported_not_guessed(self, isolated_db):
        frame = rows_without_indicators([10.0])
        frame.loc[0, "close"] = None
        isolated_db.save_daily_data(frame, "600519", "test")

        plans, totals = build_plans(isolated_db)

        assert totals.rows_uncomputable == 1
        assert plans == []

    def test_non_finite_values_are_candidates_without_null(self, isolated_db):
        frame = rows_without_indicators([10.0])
        frame["ma20"] = [10.0]
        frame["volume_ratio"] = [float("inf")]
        isolated_db.save_daily_data(frame, "600519", "test")

        plans, totals = build_plans(isolated_db)

        assert totals.codes_affected == 1
        assert totals.rows_planned == 1
        assert apply_plans(isolated_db, plans) == 1
        assert stored(isolated_db, "600519")[0][2] == pytest.approx(1.0)

    def test_cli_dry_run_does_not_write(self, isolated_db):
        isolated_db.save_daily_data(rows_without_indicators([10.0]), "600519", "test")

        assert main([]) == 0

        values = stored(isolated_db, "600519")
        assert values[0][1] is None

    def test_cli_apply_writes(self, isolated_db):
        isolated_db.save_daily_data(rows_without_indicators([10.0]), "600519", "test")

        assert main(["--apply"]) == 0

        values = stored(isolated_db, "600519")
        assert values[0][1] == pytest.approx(10.0)

    def test_codes_filter_limits_scope(self, isolated_db):
        isolated_db.save_daily_data(rows_without_indicators([10.0]), "600519", "test")
        isolated_db.save_daily_data(rows_without_indicators([20.0]), "000001", "test")

        plans, totals = build_plans(isolated_db, codes=["000001"])

        assert totals.codes_inspected == 1
        assert plans[0].code == "000001"
