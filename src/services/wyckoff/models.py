# -*- coding: utf-8 -*-
"""Value objects for the Wyckoff signal engine.

Everything here is immutable and I/O-free. ``DailyBar`` carries the full OHLCV
row plus the two indicators the engine reads (``ma20``, ``volume_ratio``) so
consumers never have to re-query raw rows to recover fields the trigger logic
needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DailyBar:
    """One trading day.

    ``ma20`` and ``volume_ratio`` are produced by ``data_provider``:

    - ``ma20``: 20-day simple moving average of close (``min_periods=1``).
    - ``volume_ratio``: today's volume divided by the mean volume of the
      previous 5 trading days.

    Both may be ``None`` when the source row or the warm-up window is missing;
    the engine treats ``None`` as "not evaluable" instead of substituting 0.
    """

    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    ma20: Optional[float] = None
    volume_ratio: Optional[float] = None


@dataclass(frozen=True)
class SignalConfig:
    """Thresholds for SOS -> LPS trigger detection.

    Defaults mirror the classic Wyckoff breakout/pullback reading; override per
    call instead of editing constants in place.
    """

    breakout_window: int = 20
    volume_ratio_high: float = 1.5
    pullback_band: float = 0.02
    volume_ratio_low: float = 0.8
    trend_lookback: int = 10
    sos_lps_window: int = 15

    def __post_init__(self) -> None:
        if self.breakout_window < 1:
            raise ValueError("breakout_window must be >= 1")
        if self.trend_lookback < 1:
            raise ValueError("trend_lookback must be >= 1")
        if self.sos_lps_window < 1:
            raise ValueError("sos_lps_window must be >= 1")
        if not 0 < self.pullback_band < 1:
            raise ValueError("pullback_band must be within (0, 1)")
        if self.volume_ratio_high <= 0 or self.volume_ratio_low <= 0:
            raise ValueError("volume ratio thresholds must be positive")
        if self.volume_ratio_low >= self.volume_ratio_high:
            raise ValueError("volume_ratio_low must be below volume_ratio_high")


@dataclass(frozen=True)
class FeatureConfig:
    """Lookback windows for the feature layer."""

    spring_lookback: int = 20
    spring_recover_days: int = 3
    test_lookback: int = 20
    test_shrink_ratio: float = 0.8
    trend_window: int = 20

    def __post_init__(self) -> None:
        for name in ("spring_lookback", "spring_recover_days", "test_lookback", "trend_window"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.test_shrink_ratio <= 0:
            raise ValueError("test_shrink_ratio must be positive")


@dataclass(frozen=True)
class WyckoffTrigger:
    """A matched SOS -> LPS pair; ``trigger_index`` is the LPS (entry) day.

    ``sos_high`` / ``trigger_low`` are the price levels the alert bridge uses:
    the SOS day high (breakout confirmation) and the LPS day low (structure
    invalidation). Both stay ``None`` when the source bar lacks the field.
    """

    sos_index: int
    trigger_index: int
    sos_date: str
    trigger_date: str
    price: Optional[float] = None
    ma20: Optional[float] = None
    volume_ratio: Optional[float] = None
    sos_high: Optional[float] = None
    trigger_low: Optional[float] = None


@dataclass(frozen=True)
class SpringFeature:
    """Spring: price breaks below MA20 then closes back above it quickly."""

    detected: bool
    break_date: str = ""
    recover_date: str = ""
    break_depth: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class TestFeature:
    """Test: a low-volume day that does not undercut the prior low."""

    detected: bool
    test_date: str = ""
    volume_ratio: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class TrendFeature:
    """Volume trend: up-day volume divided by down-day volume."""

    ratio: Optional[float] = None
    up_days: int = 0
    down_days: int = 0
    reason: str = ""


@dataclass(frozen=True)
class WyckoffFeatures:
    """Objective facts about one trigger. No score, no verdict."""

    spring: SpringFeature
    test: TestFeature
    trend: TrendFeature
