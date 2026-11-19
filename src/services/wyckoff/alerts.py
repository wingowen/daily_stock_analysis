"""Wyckoff 信号到告警中心的桥接。

职责边界：

- 本模块只把信号映射成 ``price_cross`` 规则并写入告警中心；
- 投递完全交给 ``AlertWorker`` -> ``NotificationService`` (``route_type="alert"``)，
  这里不碰任何通知渠道；
- 引擎与只读 API 保持无副作用，写操作只会从显式的同步入口进来。

每个信号生成两条**互相独立**的规则：

1. 下破 LPS 低点（结构失效，``critical``）；
2. 上破 SOS 高点（放量确认，``info``）。

两条规则的方向、价位都不同，因此语义 key 不同，可以独立触发与冷却。
若信号日收盘已经高于 SOS 高点，则跳过确认规则，避免当天立即误触发。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Set, Tuple

from src.config import Config, get_config
from src.services.alert_service import AlertService
from src.services.wyckoff.service import SignalRecord, get_wyckoff_service

logger = logging.getLogger(__name__)

ALERT_SOURCE = "wyckoff"
PRICE_CROSS_TYPE = "price_cross"
DEFAULT_EXPIRE_DAYS = 30
INVALIDATION_SEVERITY = "critical"
CONFIRMATION_SEVERITY = "info"


@dataclass(frozen=True)
class AlertRulePlan:
    """一条待写入的 ``price_cross`` 规则（纯数据，可独立比较）。"""

    code: str
    direction: str
    price: float
    name: str
    severity: str
    expires_at: Optional[datetime]

    @property
    def key(self) -> Tuple[str, str, float]:
        return (self.code, self.direction, round(self.price, 4))


@dataclass
class AlertSyncResult:
    created: int = 0
    existing: int = 0
    expired: int = 0
    failed: int = 0
    disabled: bool = False

    def __bool__(self) -> bool:
        return self.created > 0


def _valid_price(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN / 非正数
        return None
    if number in (float("inf"), float("-inf")):
        return None
    return number


def _resolve_expiry(trigger_date: str, expire_days: int) -> Optional[datetime]:
    if expire_days <= 0:
        return None
    try:
        signal_day = datetime.strptime(trigger_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return datetime.combine(signal_day + timedelta(days=expire_days), time.min)


def build_rule_plans(
    signal: SignalRecord,
    *,
    expire_days: int = DEFAULT_EXPIRE_DAYS,
    today: Optional[date] = None,
) -> Tuple[AlertRulePlan, ...]:
    """把单个信号映射成最多两条规则；价位缺失或已过期时该条直接跳过。"""
    expires_at = _resolve_expiry(signal.trigger_date, expire_days)
    if today is not None and expires_at is not None and expires_at.date() < today:
        return ()

    plans: List[AlertRulePlan] = []

    trigger_low = _valid_price(signal.trigger_low)
    if trigger_low is not None:
        plans.append(
            AlertRulePlan(
                code=signal.code,
                direction="below",
                price=round(trigger_low, 2),
                name=f"Wyckoff 结构失效 {signal.code} 下破 {trigger_low:.2f}",
                severity=INVALIDATION_SEVERITY,
                expires_at=expires_at,
            )
        )

    sos_high = _valid_price(signal.sos_high)
    already_confirmed = signal.price is not None and sos_high is not None and signal.price >= sos_high
    if sos_high is not None and not already_confirmed:
        plans.append(
            AlertRulePlan(
                code=signal.code,
                direction="above",
                price=round(sos_high, 2),
                name=f"Wyckoff 放量确认 {signal.code} 上破 {sos_high:.2f}",
                severity=CONFIRMATION_SEVERITY,
                expires_at=expires_at,
            )
        )

    return tuple(plans)


class WyckoffAlertBridge:
    """把信号同步到告警中心；单条失败只记日志，不影响其他规则与主流程。"""

    def __init__(
        self,
        alert_service: Optional[AlertService] = None,
        *,
        expire_days: int = DEFAULT_EXPIRE_DAYS,
    ):
        self._alerts = alert_service or AlertService()
        self._expire_days = expire_days

    def sync(self, signals: Iterable[SignalRecord], *, today: Optional[date] = None) -> AlertSyncResult:
        result = AlertSyncResult()
        existing_by_code: dict = {}
        for signal in signals:
            plans = build_rule_plans(signal, expire_days=self._expire_days, today=today)
            if not plans:
                result.expired += 1
                continue
            keys = existing_by_code.get(signal.code)
            if keys is None:
                keys = self._existing_keys(signal.code)
                existing_by_code[signal.code] = keys
            for plan in plans:
                if plan.key in keys:
                    result.existing += 1
                    continue
                try:
                    self._alerts.create_rule(self._payload(plan), source=ALERT_SOURCE)
                except Exception as exc:  # 非致命：单条规则失败不阻断主流程
                    logger.warning("Wyckoff 告警规则写入失败 %s %s: %s", plan.code, plan.direction, exc)
                    result.failed += 1
                    continue
                keys.add(plan.key)
                result.created += 1
        return result

    def _existing_keys(self, code: str) -> Set[Tuple[str, str, float]]:
        try:
            listing = self._alerts.list_rules(
                alert_type=PRICE_CROSS_TYPE,
                target_scope="single_symbol",
                target=code,
                source=ALERT_SOURCE,
                page_size=200,
            )
        except Exception as exc:  # 去重兜底：读失败时继续，最坏情况是多建一条同价规则
            logger.warning("Wyckoff 告警去重读取失败 %s: %s", code, exc)
            return set()
        keys: Set[Tuple[str, str, float]] = set()
        for item in listing.get("items", []):
            parameters = item.get("parameters") or {}
            direction = parameters.get("direction")
            price = parameters.get("price")
            if isinstance(direction, str) and isinstance(price, (int, float)):
                keys.add((code, direction, round(float(price), 4)))
        return keys

    @staticmethod
    def _payload(plan: AlertRulePlan) -> dict:
        return {
            "name": plan.name,
            "target_scope": "single_symbol",
            "target": plan.code,
            "alert_type": PRICE_CROSS_TYPE,
            "parameters": {"direction": plan.direction, "price": plan.price},
            "severity": plan.severity,
            "enabled": True,
            "expires_at": plan.expires_at,
        }


def sync_wyckoff_alerts(
    config: Optional[Config] = None,
    *,
    target_date: Optional[str] = None,
    today: Optional[date] = None,
    service=None,
    bridge: Optional[WyckoffAlertBridge] = None,
) -> AlertSyncResult:
    """编排入口：开关关闭时零副作用；供调度与手工任务调用。"""
    cfg = config or get_config()
    if not getattr(cfg, "wyckoff_enabled", False) or not getattr(cfg, "wyckoff_alerts_enabled", False):
        return AlertSyncResult(disabled=True)

    wyckoff_service = service or get_wyckoff_service()
    scan = wyckoff_service.scan(target_date)
    alert_bridge = bridge or WyckoffAlertBridge(
        expire_days=getattr(cfg, "wyckoff_alert_expire_days", DEFAULT_EXPIRE_DAYS),
    )
    return alert_bridge.sync(scan.signals, today=today or date.today())
