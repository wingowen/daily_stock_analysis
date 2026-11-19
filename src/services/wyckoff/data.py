# -*- coding: utf-8 -*-
"""Data access for the Wyckoff engine.

The engine never opens its own SQLite file and never talks to a market data
source. Daily bars are read through the upstream repository layer
(``StockRepository`` -> ``DatabaseManager`` -> ``StockDaily``) so indicator
values (``ma20`` / ``volume_ratio``) have exactly one definition: the one
``data_provider`` writes at ingestion time.

Full history is loaded by default. Truncating history changes which bars
satisfy the breakout window and therefore changes triggers, so windowing is
the caller's explicit choice, never a hidden default.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func

from src.repositories.stock_repo import StockRepository
from src.services.wyckoff.models import DailyBar
from src.storage import DatabaseManager, StockDaily

logger = logging.getLogger(__name__)


def _finite(value: Optional[float]) -> Optional[float]:
    """Return a finite float, or ``None`` for missing/invalid values."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso_date(value: object) -> str:
    if isinstance(value, str):
        return value
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@dataclass(frozen=True)
class DailySeries:
    """Chronologically ordered daily bars for one code."""

    code: str
    bars: Tuple[DailyBar, ...]

    def __post_init__(self) -> None:
        previous: Optional[str] = None
        for bar in self.bars:
            if previous is not None and bar.date <= previous:
                raise ValueError(f"daily bars for {self.code} must be strictly ordered by date")
            previous = bar.date

    @property
    def bar_count(self) -> int:
        return len(self.bars)

    @property
    def is_empty(self) -> bool:
        return not self.bars

    @property
    def start_date(self) -> Optional[str]:
        return self.bars[0].date if self.bars else None

    @property
    def end_date(self) -> Optional[str]:
        return self.bars[-1].date if self.bars else None


def to_daily_bar(row: StockDaily) -> DailyBar:
    """Convert one persisted row into an immutable ``DailyBar``."""
    return DailyBar(
        date=_iso_date(row.date),
        open=_finite(row.open),
        high=_finite(row.high),
        low=_finite(row.low),
        close=_finite(row.close),
        volume=_finite(row.volume),
        ma20=_finite(row.ma20),
        volume_ratio=_finite(row.volume_ratio),
    )


def to_daily_series(code: str, rows: Iterable[StockDaily]) -> DailySeries:
    return DailySeries(code=code, bars=tuple(to_daily_bar(row) for row in rows))


class WyckoffDataProvider:
    """Read-only access to persisted daily bars."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self._repo = StockRepository(db_manager)
        self._db = db_manager or DatabaseManager.get_instance()

    def load_series(
        self,
        code: str,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> DailySeries:
        """Load a code's bars, full history unless bounds are given explicitly."""
        rows: Sequence[StockDaily] = self._repo.get_range(
            code,
            start_date or date.min,
            end_date or date.max,
        )
        if not rows:
            logger.debug("wyckoff: no daily bars stored for %s", code)
        return to_daily_series(code, rows)

    def load_series_many(
        self,
        codes: Iterable[str],
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[DailySeries]:
        """Load several codes; empty series are kept so callers can report them."""
        return [
            self.load_series(code, start_date=start_date, end_date=end_date)
            for code in codes
        ]

    def list_codes(self) -> List[str]:
        """All codes that have at least one stored daily bar, ascending."""
        with self._db.get_session() as session:
            rows = (
                session.query(StockDaily.code)
                .distinct()
                .order_by(StockDaily.code)
                .all()
            )
        return [row[0] for row in rows]

    def latest_data_date(self) -> Optional[str]:
        """Newest stored trading date across all codes, or ``None`` when empty."""
        with self._db.get_session() as session:
            latest = session.query(func.max(StockDaily.date)).scalar()
        return _iso_date(latest) if latest is not None else None
