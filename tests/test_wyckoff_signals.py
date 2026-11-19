# -*- coding: utf-8 -*-
"""Tests for the pure Wyckoff signal engine."""

from __future__ import annotations

import pytest

from src.services.wyckoff import (
    DailyBar,
    FeatureConfig,
    SignalConfig,
    detect_lps,
    detect_sos,
    extract_features,
    find_triggers,
    is_trend_up,
)

CONFIG = SignalConfig()
FEATURES = FeatureConfig()


def bar(
    index: int,
    close: float = 10.0,
    *,
    low: float | None = None,
    high: float | None = None,
    open_: float | None = None,
    volume: float = 1000.0,
    ma20: float | None = 10.0,
    volume_ratio: float | None = 1.0,
) -> DailyBar:
    return DailyBar(
        date=f"2026-01-{index:02d}",
        open=open_ if open_ is not None else close,
        high=high if high is not None else close * 1.01,
        low=low if low is not None else close * 0.99,
        close=close,
        volume=volume,
        ma20=ma20,
        volume_ratio=volume_ratio,
    )


def flat_history(length: int, **overrides) -> list[DailyBar]:
    return [bar(i, **overrides) for i in range(length)]


def breakout_series() -> list[DailyBar]:
    """20 flat bars, then one SOS day, then a shrink pullback (LPS)."""
    bars = flat_history(20)
    bars.append(bar(20, 11.0, volume_ratio=2.0, ma20=10.2))
    bars.append(bar(21, 10.4, volume_ratio=0.7, ma20=10.2))
    bars.append(bar(22, 10.05, volume_ratio=0.6, ma20=10.2))
    return bars


class TestSignals:
    def test_sos_requires_breakout_and_volume(self) -> None:
        bars = breakout_series()
        assert detect_sos(bars, 20, CONFIG) is True
        # Same breakout without relative volume is not an SOS.
        bars[20] = bar(20, 11.0, volume_ratio=1.1, ma20=10.2)
        assert detect_sos(bars, 20, CONFIG) is False

    def test_sos_needs_full_breakout_window(self) -> None:
        bars = flat_history(5) + [bar(5, 11.0, volume_ratio=2.0)]
        assert detect_sos(bars, 5, CONFIG) is False

    def test_sos_missing_volume_ratio_is_not_an_sos(self) -> None:
        bars = flat_history(20) + [bar(20, 11.0, volume_ratio=None)]
        assert detect_sos(bars, 20, CONFIG) is False

    def test_lps_requires_band_and_shrink(self) -> None:
        inside = [bar(0, 10.0, ma20=10.0, volume_ratio=0.5)]
        assert detect_lps(inside, 0, CONFIG) is True
        too_far = [bar(0, 10.5, ma20=10.0, volume_ratio=0.5)]
        assert detect_lps(too_far, 0, CONFIG) is False
        no_shrink = [bar(0, 10.0, ma20=10.0, volume_ratio=1.2)]
        assert detect_lps(no_shrink, 0, CONFIG) is False

    def test_lps_missing_ma20_is_not_evaluable(self) -> None:
        bars = [bar(0, 10.0, ma20=None, volume_ratio=0.5)]
        assert detect_lps(bars, 0, CONFIG) is False

    def test_find_triggers_pairs_first_lps(self) -> None:
        triggers = find_triggers(breakout_series(), CONFIG)
        assert len(triggers) == 1
        assert triggers[0].sos_index == 20
        assert triggers[0].trigger_index == 21
        assert triggers[0].sos_date == "2026-01-20"
        assert triggers[0].trigger_date == "2026-01-21"
        assert triggers[0].price == pytest.approx(10.4)

    def test_find_triggers_skips_sos_without_lps(self) -> None:
        bars = flat_history(20) + [bar(20, 11.0, volume_ratio=2.0)]
        bars += [bar(i, 10.0, volume_ratio=1.0) for i in range(21, 40)]
        assert find_triggers(bars, CONFIG) == []

    def test_find_triggers_does_not_reuse_matched_sos(self) -> None:
        bars = breakout_series()
        # A second LPS inside the same window must not create a second trigger.
        bars.append(bar(23, 10.02, volume_ratio=0.5, ma20=10.2))
        triggers = find_triggers(bars, CONFIG)
        assert [trigger.trigger_index for trigger in triggers] == [21]

    def test_is_trend_up(self) -> None:
        bars = [bar(i, 10.0, ma20=10.0 + i * 0.01) for i in range(20)]
        assert is_trend_up(bars, 19, CONFIG) is True
        bars = [bar(i, 10.0, ma20=10.0 - i * 0.01) for i in range(20)]
        assert is_trend_up(bars, 19, CONFIG) is False


class TestFeatures:
    def test_spring_detected_after_recovery(self) -> None:
        bars = flat_history(40, ma20=10.0, low=9.95)
        bars[30] = bar(30, 9.4, low=9.0, ma20=10.0)
        bars[31] = bar(31, 10.2, low=9.8, ma20=10.0)
        features = extract_features(bars, 35, FEATURES)
        assert features.spring.detected is True
        assert features.spring.break_date == "2026-01-30"
        assert features.spring.recover_date == "2026-01-31"
        assert features.spring.break_depth == pytest.approx(0.1)

    def test_spring_reports_missing_data_instead_of_guessing(self) -> None:
        bars = flat_history(40, ma20=10.0, low=9.95)
        bars[30] = bar(30, 9.4, low=9.0, ma20=None)
        features = extract_features(bars, 35, FEATURES)
        assert features.spring.detected is False
        assert features.spring.reason == "missing_data"

    def test_test_detected_when_shrink_day_holds_prior_low(self) -> None:
        bars = flat_history(40, ma20=10.0, low=10.0, volume_ratio=1.2)
        bars[30] = bar(30, 10.0, low=10.0, ma20=10.0, volume_ratio=0.5)
        features = extract_features(bars, 35, FEATURES)
        assert features.test.detected is True
        assert features.test.test_date == "2026-01-30"

    def test_test_rejects_shrink_day_that_makes_new_low(self) -> None:
        bars = flat_history(40, ma20=10.0, low=10.0, volume_ratio=1.2)
        bars[30] = bar(30, 9.5, low=9.5, ma20=10.0, volume_ratio=0.5)
        features = extract_features(bars, 35, FEATURES)
        assert features.test.detected is False
        assert features.test.reason == "new_low"

    def test_test_missing_volume_ratio_is_not_zero(self) -> None:
        bars = flat_history(40, ma20=10.0, low=10.0, volume_ratio=1.2)
        bars[30] = bar(30, 10.0, low=10.0, ma20=10.0, volume_ratio=None)
        features = extract_features(bars, 35, FEATURES)
        assert features.test.detected is False
        assert features.test.reason == "missing_data"

    def test_trend_ratio_uses_volume_split(self) -> None:
        bars = flat_history(40, ma20=10.0, low=10.0, volume_ratio=1.0)
        for index, close in zip(range(16, 36), [10.0, 10.2, 10.1, 10.3, 10.2] * 4):
            bars[index] = bar(index, close, ma20=10.0, volume=1000.0 if close > bars[index - 1].close else 500.0)
        features = extract_features(bars, 35, FEATURES)
        assert features.trend.ratio is not None
        assert features.trend.up_days > 0
        assert features.trend.down_days > 0

    def test_trend_reports_absent_downside(self) -> None:
        bars = [bar(i, 10.0 + i * 0.1, ma20=10.0) for i in range(40)]
        features = extract_features(bars, 35, FEATURES)
        assert features.trend.ratio is None
        assert features.trend.reason == "no_down_day"

    def test_invalid_trigger_index(self) -> None:
        bars = flat_history(10)
        assert extract_features(bars, -1, FEATURES).spring.reason == "invalid_trigger_index"
        assert extract_features(bars, 99, FEATURES).test.reason == "invalid_trigger_index"


class TestConfig:
    def test_rejects_inverted_volume_thresholds(self) -> None:
        with pytest.raises(ValueError):
            SignalConfig(volume_ratio_low=2.0, volume_ratio_high=1.5)

    def test_rejects_non_positive_windows(self) -> None:
        with pytest.raises(ValueError):
            SignalConfig(breakout_window=0)
        with pytest.raises(ValueError):
            FeatureConfig(trend_window=0)
