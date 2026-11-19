# -*- coding: utf-8 -*-
"""SOS -> LPS trigger detection (fact layer).

Definitions used here, deliberately narrow and objective:

- **SOS (sign of strength)**: close makes a new ``breakout_window``-day high
  while ``volume_ratio`` exceeds ``volume_ratio_high``.
- **LPS (last point of support)**: close sits within ``pullback_band`` of MA20
  on lower volume (``volume_ratio`` below ``volume_ratio_low``).
- **trigger**: the first LPS within ``sos_lps_window`` trading days after an
  SOS. The LPS day is the entry day.

The caller must pass the *full* history it has. Truncating history changes
which bars satisfy the breakout window and therefore changes triggers; that is
why this module never applies its own lookback limit.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from src.services.wyckoff.models import DailyBar, SignalConfig, WyckoffTrigger


def _finite(value: Optional[float]) -> Optional[float]:
    """Return ``value`` when it is a finite float, else ``None``."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _close_at(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    if index < 0 or index >= len(bars):
        return None
    return _finite(bars[index].close)


def _volume_ratio_at(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    if index < 0 or index >= len(bars):
        return None
    return _finite(bars[index].volume_ratio)


def _ma20_at(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    if index < 0 or index >= len(bars):
        return None
    return _finite(bars[index].ma20)


def _high_at(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    if index < 0 or index >= len(bars):
        return None
    return _finite(bars[index].high)


def _low_at(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    if index < 0 or index >= len(bars):
        return None
    return _finite(bars[index].low)


def detect_sos(
    bars: Sequence[DailyBar],
    index: int,
    config: SignalConfig = SignalConfig(),
) -> bool:
    """True when ``bars[index]`` is a sign-of-strength day."""
    if index < config.breakout_window or index >= len(bars):
        return False

    current_close = _close_at(bars, index)
    if current_close is None or current_close <= 0:
        return False

    window = [_close_at(bars, i) for i in range(index - config.breakout_window, index)]
    if any(value is None for value in window):
        return False
    if current_close <= max(value for value in window if value is not None):
        return False

    volume_ratio = _volume_ratio_at(bars, index)
    if volume_ratio is None or volume_ratio <= config.volume_ratio_high:
        return False

    return True


def detect_lps(
    bars: Sequence[DailyBar],
    index: int,
    config: SignalConfig = SignalConfig(),
) -> bool:
    """True when ``bars[index]`` is a last-point-of-support day."""
    if index < 0 or index >= len(bars):
        return False

    current_close = _close_at(bars, index)
    ma20 = _ma20_at(bars, index)
    if current_close is None or ma20 is None or ma20 <= 0:
        return False

    if abs(current_close - ma20) / ma20 > config.pullback_band:
        return False

    volume_ratio = _volume_ratio_at(bars, index)
    if volume_ratio is None or volume_ratio >= config.volume_ratio_low:
        return False

    return True


def is_trend_up(
    bars: Sequence[DailyBar],
    index: int,
    config: SignalConfig = SignalConfig(),
) -> bool:
    """True when MA20 at ``index`` is higher than ``trend_lookback`` days ago."""
    if index < config.trend_lookback or index >= len(bars):
        return False

    current = _ma20_at(bars, index)
    past = _ma20_at(bars, index - config.trend_lookback)
    if current is None or past is None or past <= 0:
        return False

    return current > past


def find_triggers(
    bars: Sequence[DailyBar],
    config: SignalConfig = SignalConfig(),
) -> List[WyckoffTrigger]:
    """Scan ``bars`` for SOS -> LPS pairs, in chronological order.

    After a pair is matched, scanning resumes on the day after the LPS so the
    same SOS cannot be paired twice and overlapping pairs are not emitted.
    """
    triggers: List[WyckoffTrigger] = []
    total = len(bars)
    index = 0

    while index < total:
        if not detect_sos(bars, index, config):
            index += 1
            continue

        sos_index = index
        window_end = min(sos_index + 1 + config.sos_lps_window, total)
        matched = False

        for candidate in range(sos_index + 1, window_end):
            if not detect_lps(bars, candidate, config):
                continue
            triggers.append(
                WyckoffTrigger(
                    sos_index=sos_index,
                    trigger_index=candidate,
                    sos_date=bars[sos_index].date,
                    trigger_date=bars[candidate].date,
                    price=_close_at(bars, candidate),
                    ma20=_ma20_at(bars, candidate),
                    volume_ratio=_volume_ratio_at(bars, candidate),
                    sos_high=_high_at(bars, sos_index),
                    trigger_low=_low_at(bars, candidate),
                )
            )
            matched = True
            index = candidate + 1
            break

        if not matched:
            index = sos_index + 1

    return triggers
