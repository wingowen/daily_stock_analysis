# -*- coding: utf-8 -*-
"""Wyckoff service: scan orchestration, caching and read-only projections.

Design decisions (see ``docs/wyckoff.md``):

- every scan recomputes from the code's **full** stored history; there is no
  incremental window that could shift a trigger depending on the query range;
- ``find_triggers`` results are cached per ``(code, last bar date, bar count,
  signal config fingerprint)`` so repeated scans of different dates reuse the
  same work while staying deterministic;
- the service never fetches market data and never writes to the database.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from src.services.wyckoff.data import DailySeries, WyckoffDataProvider
from src.services.wyckoff.features import extract_features
from src.services.wyckoff.models import (
    DailyBar,
    FeatureConfig,
    SignalConfig,
    WyckoffFeatures,
    WyckoffTrigger,
)
from src.services.wyckoff.signals import find_triggers
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

TRIGGER_CACHE_SIZE = 4096
DEFAULT_DETAIL_BARS = 250


@dataclass(frozen=True)
class SignalRecord:
    """One trigger with its objective features, ready for API projection."""

    code: str
    trigger_date: str
    sos_date: str
    price: Optional[float]
    ma20: Optional[float]
    volume_ratio: Optional[float]
    sos_high: Optional[float]
    trigger_low: Optional[float]
    features: WyckoffFeatures


@dataclass(frozen=True)
class ScanResult:
    date: str
    latest_data_date: Optional[str]
    is_stale: bool
    signals: Tuple[SignalRecord, ...]
    codes_scanned: int
    codes_without_data: int


@dataclass(frozen=True)
class DetailResult:
    code: str
    latest_data_date: Optional[str]
    bars: Tuple[DailyBar, ...]
    signals: Tuple[SignalRecord, ...]


def _normalize_date(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text).isoformat()


def expected_last_trading_day(today: date) -> date:
    """Last weekday on or before ``today``.

    Weekends only; public holidays are intentionally not modelled here.
    """
    candidate = today
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


class WyckoffService:
    """Read-only Wyckoff queries over persisted daily bars."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        *,
        signal_config: SignalConfig = SignalConfig(),
        feature_config: FeatureConfig = FeatureConfig(),
        data_provider: Optional[WyckoffDataProvider] = None,
        cache_size: int = TRIGGER_CACHE_SIZE,
    ):
        self._provider = data_provider or WyckoffDataProvider(db_manager)
        self._signal_config = signal_config
        self._feature_config = feature_config
        self._cache_size = max(cache_size, 0)
        self._trigger_cache: "OrderedDict[Tuple[str, str, int, str], Tuple[WyckoffTrigger, ...]]" = OrderedDict()

    # ------------------------------------------------------------------ helpers

    def _fingerprint(self) -> str:
        config = self._signal_config
        return (
            f"{config.breakout_window}:{config.volume_ratio_high}:{config.pullback_band}:"
            f"{config.volume_ratio_low}:{config.trend_lookback}:{config.sos_lps_window}"
        )

    def _triggers_for(self, series: DailySeries) -> Tuple[WyckoffTrigger, ...]:
        if series.is_empty:
            return ()
        if self._cache_size == 0:
            return tuple(find_triggers(series.bars, self._signal_config))

        key = (series.code, series.end_date or "", series.bar_count, self._fingerprint())
        cached = self._trigger_cache.get(key)
        if cached is not None:
            self._trigger_cache.move_to_end(key)
            return cached

        computed = tuple(find_triggers(series.bars, self._signal_config))
        self._trigger_cache[key] = computed
        if len(self._trigger_cache) > self._cache_size:
            self._trigger_cache.popitem(last=False)
        return computed

    def _record(self, code: str, bars: Sequence[DailyBar], trigger: WyckoffTrigger) -> SignalRecord:
        features = extract_features(bars, trigger.trigger_index, self._feature_config)
        return SignalRecord(
            code=code,
            trigger_date=trigger.trigger_date,
            sos_date=trigger.sos_date,
            price=trigger.price,
            ma20=trigger.ma20,
            volume_ratio=trigger.volume_ratio,
            sos_high=trigger.sos_high,
            trigger_low=trigger.trigger_low,
            features=features,
        )

    # ------------------------------------------------------------------ queries

    def latest_data_date(self) -> Optional[str]:
        return self._provider.latest_data_date()

    def is_stale(self, latest_data_date: Optional[str], today: Optional[date] = None) -> bool:
        if not latest_data_date:
            return False
        return latest_data_date < expected_last_trading_day(today or date.today()).isoformat()

    def scan(
        self,
        target_date: Optional[object] = None,
        *,
        codes: Optional[Iterable[str]] = None,
        limit: Optional[int] = None,
    ) -> ScanResult:
        """Return every trigger whose entry day equals ``target_date``.

        ``target_date`` defaults to the newest stored trading date so the call
        stays deterministic for a given database snapshot.
        """
        latest = self.latest_data_date()
        resolved = _normalize_date(target_date) or latest
        if resolved is None:
            return ScanResult(
                date="",
                latest_data_date=None,
                is_stale=False,
                signals=(),
                codes_scanned=0,
                codes_without_data=0,
            )

        selected = list(codes) if codes is not None else self._provider.list_codes()
        if limit is not None:
            selected = selected[: max(limit, 0)]

        signals: List[SignalRecord] = []
        missing = 0
        for code in selected:
            series = self._provider.load_series(code)
            if series.is_empty:
                missing += 1
                continue
            for trigger in self._triggers_for(series):
                if trigger.trigger_date == resolved:
                    signals.append(self._record(code, series.bars, trigger))

        signals.sort(key=lambda item: item.code)
        return ScanResult(
            date=resolved,
            latest_data_date=latest,
            is_stale=self.is_stale(latest),
            signals=tuple(signals),
            codes_scanned=len(selected),
            codes_without_data=missing,
        )

    def detail(
        self,
        code: str,
        *,
        bars: int = DEFAULT_DETAIL_BARS,
    ) -> DetailResult:
        """Return the recent bars plus every trigger inside that window."""
        series = self._provider.load_series(code)
        window = series.bars[-max(bars, 1):] if series.bars else ()
        window_start = window[0].date if window else ""

        signals = tuple(
            self._record(code, series.bars, trigger)
            for trigger in self._triggers_for(series)
            if trigger.trigger_date >= window_start
        )
        return DetailResult(
            code=code,
            latest_data_date=series.end_date,
            bars=tuple(window),
            signals=signals,
        )


_service_instance: Optional[WyckoffService] = None


def get_wyckoff_service() -> WyckoffService:
    """Process-wide service instance so the trigger cache survives requests."""
    global _service_instance
    if _service_instance is None:
        _service_instance = WyckoffService()
    return _service_instance


def reset_wyckoff_service() -> None:
    """Drop the cached service instance (tests and config reloads)."""
    global _service_instance
    _service_instance = None
