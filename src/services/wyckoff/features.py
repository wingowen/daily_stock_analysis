# -*- coding: utf-8 -*-
"""Objective feature extraction for a single trigger (feature layer).

Three facts are reported, never a score:

- ``spring``: a break below MA20 that is recovered within a few days.
- ``test``: the most recent low-volume day that does not undercut the prior low.
- ``trend``: up-day volume divided by down-day volume near the trigger.

Every non-detection carries a ``reason`` so "shape is absent" stays
distinguishable from "input data was missing". Missing indicator values are
never coerced to ``0`` because that silently fabricates a low-volume day.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from src.services.wyckoff.models import (
    DailyBar,
    FeatureConfig,
    SpringFeature,
    TestFeature,
    TrendFeature,
    WyckoffFeatures,
)

INSUFFICIENT_HISTORY = "insufficient_history"
INVALID_TRIGGER = "invalid_trigger_index"
MISSING_DATA = "missing_data"
NO_DOWNSIDE = "no_down_day"


def _finite(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _low(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    return _finite(bars[index].low)


def _close(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    return _finite(bars[index].close)


def _ma20(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    return _finite(bars[index].ma20)


def _volume(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    return _finite(bars[index].volume)


def _volume_ratio(bars: Sequence[DailyBar], index: int) -> Optional[float]:
    return _finite(bars[index].volume_ratio)


def _undetected_features(reason: str) -> WyckoffFeatures:
    return WyckoffFeatures(
        spring=SpringFeature(detected=False, reason=reason),
        test=TestFeature(detected=False, reason=reason),
        trend=TrendFeature(reason=reason),
    )


def _extract_spring(
    bars: Sequence[DailyBar],
    trigger_index: int,
    config: FeatureConfig,
) -> SpringFeature:
    if trigger_index < config.spring_lookback:
        return SpringFeature(detected=False, reason=INSUFFICIENT_HISTORY)

    start = trigger_index - config.spring_lookback
    break_index = start
    break_low: Optional[float] = None
    for index in range(start, trigger_index + 1):
        low = _low(bars, index)
        if low is None:
            return SpringFeature(detected=False, reason=MISSING_DATA)
        if break_low is None or low < break_low:
            break_low = low
            break_index = index

    if break_low is None:
        return SpringFeature(detected=False, reason=MISSING_DATA)

    ma20_at_break = _ma20(bars, break_index)
    if ma20_at_break is None or ma20_at_break <= 0:
        return SpringFeature(detected=False, reason=MISSING_DATA)

    break_depth = (ma20_at_break - break_low) / ma20_at_break
    if break_depth <= 0:
        return SpringFeature(detected=False, reason="no_breakdown")

    recover_end = min(break_index + 1 + config.spring_recover_days, trigger_index + 1)
    for candidate in range(break_index + 1, recover_end):
        close = _close(bars, candidate)
        ma20 = _ma20(bars, candidate)
        if close is None or ma20 is None:
            return SpringFeature(detected=False, reason=MISSING_DATA)
        if close >= ma20:
            return SpringFeature(
                detected=True,
                break_date=bars[break_index].date,
                recover_date=bars[candidate].date,
                break_depth=round(break_depth, 4),
            )

    return SpringFeature(detected=False, reason="not_recovered")


def _extract_test(
    bars: Sequence[DailyBar],
    trigger_index: int,
    config: FeatureConfig,
) -> TestFeature:
    if trigger_index < config.test_lookback:
        return TestFeature(detected=False, reason=INSUFFICIENT_HISTORY)

    start = trigger_index - config.test_lookback
    lows: List[float] = []
    ratios: List[float] = []
    for index in range(start, trigger_index + 1):
        low = _low(bars, index)
        volume_ratio = _volume_ratio(bars, index)
        if low is None or volume_ratio is None:
            return TestFeature(detected=False, reason=MISSING_DATA)
        lows.append(low)
        ratios.append(volume_ratio)

    # Walk back from the trigger: the first low-volume day decides the verdict.
    for offset in range(len(lows) - 1, -1, -1):
        if ratios[offset] >= config.test_shrink_ratio:
            continue
        prior_min = min(lows[:offset]) if offset > 0 else lows[0]
        if lows[offset] >= prior_min:
            return TestFeature(
                detected=True,
                test_date=bars[start + offset].date,
                volume_ratio=round(ratios[offset], 4),
            )
        return TestFeature(detected=False, reason="new_low")

    return TestFeature(detected=False, reason="no_shrink_day")


def _extract_trend(
    bars: Sequence[DailyBar],
    trigger_index: int,
    config: FeatureConfig,
) -> TrendFeature:
    if trigger_index < config.trend_window:
        return TrendFeature(reason=INSUFFICIENT_HISTORY)

    start = trigger_index - config.trend_window
    up_volume = 0.0
    down_volume = 0.0
    up_days = 0
    down_days = 0

    for index in range(start + 1, trigger_index + 1):
        current = _close(bars, index)
        previous = _close(bars, index - 1)
        volume = _volume(bars, index)
        if current is None or previous is None or volume is None:
            return TrendFeature(reason=MISSING_DATA)
        if current > previous:
            up_volume += volume
            up_days += 1
        elif current < previous:
            down_volume += volume
            down_days += 1

    if down_volume <= 0 or down_days == 0:
        return TrendFeature(up_days=up_days, down_days=down_days, reason=NO_DOWNSIDE)

    return TrendFeature(
        ratio=round(up_volume / down_volume, 4),
        up_days=up_days,
        down_days=down_days,
    )


def extract_features(
    bars: Sequence[DailyBar],
    trigger_index: int,
    config: FeatureConfig = FeatureConfig(),
) -> WyckoffFeatures:
    """Return the objective Spring / Test / trend facts for one trigger."""
    if trigger_index < 0 or trigger_index >= len(bars):
        return _undetected_features(INVALID_TRIGGER)

    return WyckoffFeatures(
        spring=_extract_spring(bars, trigger_index, config),
        test=_extract_test(bars, trigger_index, config),
        trend=_extract_trend(bars, trigger_index, config),
    )
