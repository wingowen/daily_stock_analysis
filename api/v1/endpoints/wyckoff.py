# -*- coding: utf-8 -*-
"""Wyckoff 只读查询接口。

职责：
1. GET /api/v1/wyckoff/signals — 查询指定交易日（默认最新交易日）的 SOS/LPS 信号
2. GET /api/v1/wyckoff/detail/{code} — 查询单只股票的近期日线与触发点

接口默认关闭，需 ``WYCKOFF_ENABLED=true``；关闭时返回 403。
本接口只读本地日线缓存，不触发抓取，也不写库。
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_config_dep
from api.v1.schemas.wyckoff import (
    WyckoffBarOut,
    WyckoffDetailResponse,
    WyckoffFeaturesOut,
    WyckoffSignalItem,
    WyckoffSignalsResponse,
    WyckoffSpringOut,
    WyckoffTestOut,
    WyckoffTrendOut,
)
from src.config import Config
from src.services.wyckoff.service import (
    DEFAULT_DETAIL_BARS,
    DetailResult,
    ScanResult,
    SignalRecord,
    get_wyckoff_service,
)

router = APIRouter()


def _ensure_wyckoff_enabled(config: Config) -> None:
    if not config.wyckoff_enabled:
        raise HTTPException(
            status_code=403,
            detail={"error": "wyckoff_disabled", "message": "WYCKOFF_ENABLED is false."},
        )


def _to_signal_item(record: SignalRecord) -> WyckoffSignalItem:
    features = record.features
    return WyckoffSignalItem(
        code=record.code,
        trigger_date=record.trigger_date,
        sos_date=record.sos_date,
        price=record.price,
        ma20=record.ma20,
        volume_ratio=record.volume_ratio,
        sos_high=record.sos_high,
        trigger_low=record.trigger_low,
        features=WyckoffFeaturesOut(
            spring=WyckoffSpringOut(
                detected=features.spring.detected,
                break_date=features.spring.break_date or None,
                recover_date=features.spring.recover_date or None,
                break_depth=features.spring.break_depth,
                reason=features.spring.reason or None,
            ),
            test=WyckoffTestOut(
                detected=features.test.detected,
                test_date=features.test.test_date or None,
                volume_ratio=features.test.volume_ratio,
                reason=features.test.reason or None,
            ),
            trend=WyckoffTrendOut(
                ratio=features.trend.ratio,
                up_days=features.trend.up_days,
                down_days=features.trend.down_days,
                reason=features.trend.reason or None,
            ),
        ),
    )


def _to_detail_response(result: DetailResult) -> WyckoffDetailResponse:
    return WyckoffDetailResponse(
        code=result.code,
        latest_data_date=result.latest_data_date,
        bars=[
            WyckoffBarOut(
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                ma20=bar.ma20,
                volume_ratio=bar.volume_ratio,
            )
            for bar in result.bars
        ],
        signals=[_to_signal_item(record) for record in result.signals],
    )


def _parse_codes(raw: Optional[str]) -> Optional[Sequence[str]]:
    if not raw:
        return None
    codes = [item.strip() for item in raw.split(",") if item.strip()]
    return codes or None


@router.get(
    "/signals",
    response_model=WyckoffSignalsResponse,
    summary="查询威科夫触发信号",
    description="按交易日查询 SOS→LPS 触发点；不传 date 时使用本地最新交易日。",
)
def get_signals(
    date: Optional[date] = Query(None, description="信号日期；缺省为本地最新交易日"),
    codes: Optional[str] = Query(None, description="只扫描指定股票，逗号分隔"),
    limit: Optional[int] = Query(None, ge=1, le=5000, description="最多扫描的股票数"),
    config: Config = Depends(get_config_dep),
) -> WyckoffSignalsResponse:
    _ensure_wyckoff_enabled(config)

    result: ScanResult = get_wyckoff_service().scan(
        date,
        codes=_parse_codes(codes),
        limit=limit,
    )
    return WyckoffSignalsResponse(
        date=result.date,
        latest_data_date=result.latest_data_date,
        is_stale=result.is_stale,
        total=len(result.signals),
        codes_scanned=result.codes_scanned,
        codes_without_data=result.codes_without_data,
        signals=[_to_signal_item(record) for record in result.signals],
    )


@router.get(
    "/detail/{code}",
    response_model=WyckoffDetailResponse,
    summary="查询单只股票的威科夫详情",
    description="返回近期日线与窗口内的触发点；只读本地缓存。",
)
def get_detail(
    code: str,
    bars: int = Query(DEFAULT_DETAIL_BARS, ge=20, le=1000, description="返回的日线数量"),
    config: Config = Depends(get_config_dep),
) -> WyckoffDetailResponse:
    _ensure_wyckoff_enabled(config)

    normalized = code.strip()
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail={"error": "wyckoff_invalid_code", "message": "code must not be empty."},
        )

    result = get_wyckoff_service().detail(normalized, bars=bars)
    if not result.bars:
        raise HTTPException(
            status_code=404,
            detail={"error": "wyckoff_no_data", "message": f"No daily bars stored for {normalized}."},
        )
    return _to_detail_response(result)
