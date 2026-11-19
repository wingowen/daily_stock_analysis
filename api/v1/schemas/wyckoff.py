# -*- coding: utf-8 -*-
"""Wyckoff API schemas (read-only projections)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class WyckoffSpringOut(BaseModel):
    detected: bool = Field(..., description="是否识别到 Spring 形态")
    break_date: Optional[str] = Field(None, description="跌破 MA20 的交易日")
    recover_date: Optional[str] = Field(None, description="收回 MA20 的交易日")
    break_depth: Optional[float] = Field(None, description="跌破幅度（相对 MA20）")
    reason: Optional[str] = Field(None, description="未识别时的原因")


class WyckoffTestOut(BaseModel):
    detected: bool = Field(..., description="是否识别到 Test 形态")
    test_date: Optional[str] = Field(None, description="缩量测试日")
    volume_ratio: Optional[float] = Field(None, description="测试日量比")
    reason: Optional[str] = Field(None, description="未识别时的原因")


class WyckoffTrendOut(BaseModel):
    ratio: Optional[float] = Field(None, description="上涨日成交量 / 下跌日成交量")
    up_days: int = Field(0, description="窗口内上涨天数")
    down_days: int = Field(0, description="窗口内下跌天数")
    reason: Optional[str] = Field(None, description="无法计算时的原因")


class WyckoffFeaturesOut(BaseModel):
    spring: WyckoffSpringOut
    test: WyckoffTestOut
    trend: WyckoffTrendOut


class WyckoffSignalItem(BaseModel):
    code: str = Field(..., description="股票代码")
    trigger_date: str = Field(..., description="触发日（LPS，即入场日）")
    sos_date: str = Field(..., description="SOS 日")
    price: Optional[float] = Field(None, description="触发日收盘价")
    ma20: Optional[float] = Field(None, description="触发日 MA20")
    volume_ratio: Optional[float] = Field(None, description="触发日量比")
    sos_high: Optional[float] = Field(None, description="SOS 日最高价（突破确认参考位）")
    trigger_low: Optional[float] = Field(None, description="触发日最低价（结构失效参考位）")
    features: WyckoffFeaturesOut


class WyckoffSignalsResponse(BaseModel):
    date: str = Field(..., description="查询的信号日期")
    latest_data_date: Optional[str] = Field(None, description="本地日线最新交易日")
    is_stale: bool = Field(False, description="本地数据是否落后于最近一个工作日")
    total: int = Field(0, description="信号数量")
    codes_scanned: int = Field(0, description="本次扫描的股票数")
    codes_without_data: int = Field(0, description="无日线数据而跳过的股票数")
    signals: List[WyckoffSignalItem] = Field(default_factory=list)


class WyckoffBarOut(BaseModel):
    date: str = Field(..., description="交易日")
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    ma20: Optional[float] = None
    volume_ratio: Optional[float] = None


class WyckoffDetailResponse(BaseModel):
    code: str = Field(..., description="股票代码")
    latest_data_date: Optional[str] = Field(None, description="该股票最新交易日")
    bars: List[WyckoffBarOut] = Field(default_factory=list, description="近期日线（升序）")
    signals: List[WyckoffSignalItem] = Field(default_factory=list, description="窗口内触发点")
