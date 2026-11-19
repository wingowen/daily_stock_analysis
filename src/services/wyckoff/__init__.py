# -*- coding: utf-8 -*-
"""Wyckoff signal engine (pure domain layer).

Layering:
  1. fact layer   -- ``signals``: SOS -> LPS trigger detection
  2. feature layer -- ``features``: objective Spring / Test / volume-trend labels
  3. combination layer (not implemented yet) -- scoring / pattern composition

This package must stay free of I/O: no database, no network, no config lookup.
Callers pass a sequence of ``DailyBar``; indicator values (``ma20``,
``volume_ratio``) come from ``data_provider`` so every entry point uses one
definition of each indicator.
"""

from src.services.wyckoff.features import extract_features
from src.services.wyckoff.models import (
    DailyBar,
    FeatureConfig,
    SignalConfig,
    SpringFeature,
    TestFeature,
    TrendFeature,
    WyckoffFeatures,
    WyckoffTrigger,
)
from src.services.wyckoff.signals import detect_lps, detect_sos, find_triggers, is_trend_up

__all__ = [
    "DailyBar",
    "FeatureConfig",
    "SignalConfig",
    "SpringFeature",
    "TestFeature",
    "TrendFeature",
    "WyckoffFeatures",
    "WyckoffTrigger",
    "detect_lps",
    "detect_sos",
    "extract_features",
    "find_triggers",
    "is_trend_up",
]
