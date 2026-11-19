# -*- coding: utf-8 -*-
"""回填 stock_daily 中缺失或非法的 ma20 / volume_ratio。

背景：指标在 data_provider 抓取入库时计算，但历史上存在未写入指标的行。
本脚本按 data_provider 同款公式补齐这些行，不引入第二套口径。

行为：
1. 只处理 ma20 或 volume_ratio 为 NULL / 非有限值的行，已有合法值的行不动；
2. 计算时使用该股票在库内的完整历史，避免窗口被截断；
3. 默认 dry-run，只输出受影响规模；加 --apply 才写库；
4. 幂等：可重复执行，第二次执行待回填行数应为 0。

用法：
    python scripts/backfill_daily_indicators.py
    python scripts/backfill_daily_indicators.py --apply
    python scripts/backfill_daily_indicators.py --codes 600519,000001 --apply
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import date as DateType
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import bindparam, select

# 允许直接以脚本方式执行；不依赖当前工作目录。
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_provider.base import BaseFetcher  # noqa: E402
from src.storage import DatabaseManager, StockDaily  # noqa: E402

logger = logging.getLogger(__name__)

UPDATE_CHUNK_SIZE = 500
NON_FINITE_CEILING = 1e308


class _IndicatorCalculator(BaseFetcher):
    """仅用于复用 upstream 指标公式，不实现任何抓取能力。"""

    name = "indicator-backfill"

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("backfill script does not fetch market data")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("backfill script does not normalize market data")


@dataclass
class CodePlan:
    code: str
    rows: List[Tuple[DateType, float, float]] = field(default_factory=list)
    uncomputable: int = 0


@dataclass
class BackfillTotals:
    codes_inspected: int = 0
    codes_affected: int = 0
    rows_planned: int = 0
    rows_uncomputable: int = 0


def _is_valid(value: Optional[float]) -> bool:
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _invalid_indicator(column):
    """NULL 或非有限值（SQLite 把 NaN 存成 NULL，这里额外覆盖 ±inf）。"""
    return column.is_(None) | (column > NON_FINITE_CEILING) | (column < -NON_FINITE_CEILING)


def _iter_candidate_codes(db: DatabaseManager) -> List[str]:
    with db.get_session() as session:
        rows = session.execute(
            select(StockDaily.code)
            .where(_invalid_indicator(StockDaily.ma20) | _invalid_indicator(StockDaily.volume_ratio))
            .distinct()
            .order_by(StockDaily.code)
        ).scalars().all()
    return list(rows)


def _build_plan_for_code(db: DatabaseManager, code: str, calculator: _IndicatorCalculator) -> CodePlan:
    with db.get_session() as session:
        rows = session.execute(
            select(
                StockDaily.date,
                StockDaily.close,
                StockDaily.volume,
                StockDaily.ma20,
                StockDaily.volume_ratio,
            )
            .where(StockDaily.code == code)
            .order_by(StockDaily.date)
        ).all()

    plan = CodePlan(code=code)
    if not rows:
        return plan

    dates = [row.date for row in rows]
    frame = pd.DataFrame(
        {
            "date": dates,
            "close": [row.close for row in rows],
            "volume": [row.volume for row in rows],
        }
    )
    computed = calculator._calculate_indicators(frame)

    for offset, row in enumerate(rows):
        needs_ma20 = not _is_valid(row.ma20)
        needs_ratio = not _is_valid(row.volume_ratio)
        if not needs_ma20 and not needs_ratio:
            continue

        ma20 = computed.at[offset, "ma20"]
        ratio = computed.at[offset, "volume_ratio"]
        ma20 = float(ma20) if _is_valid(ma20) else None
        ratio = float(ratio) if _is_valid(ratio) else None

        if (needs_ma20 and ma20 is None) or (needs_ratio and ratio is None):
            plan.uncomputable += 1
            continue

        # 已有合法值的列保持原样，只替换缺失/非法的列。
        plan.rows.append(
            (
                row.date,
                ma20 if needs_ma20 else float(row.ma20),
                ratio if needs_ratio else float(row.volume_ratio),
            )
        )

    return plan


def build_plans(
    db: DatabaseManager,
    codes: Optional[Iterable[str]] = None,
) -> Tuple[List[CodePlan], BackfillTotals]:
    calculator = _IndicatorCalculator()
    selected = list(codes) if codes else _iter_candidate_codes(db)

    plans: List[CodePlan] = []
    totals = BackfillTotals()
    for code in selected:
        plan = _build_plan_for_code(db, code, calculator)
        totals.codes_inspected += 1
        totals.rows_uncomputable += plan.uncomputable
        if plan.rows:
            plans.append(plan)
            totals.codes_affected += 1
            totals.rows_planned += len(plan.rows)
    return plans, totals


def apply_plans(db: DatabaseManager, plans: Sequence[CodePlan]) -> int:
    # 用 Core 语句 + bindparam 做批量更新，按 (code, date) 定位行。
    table = StockDaily.__table__
    statement = (
        table.update()
        .where(table.c.code == bindparam("b_code"))
        .where(table.c.date == bindparam("b_date"))
        .values(ma20=bindparam("b_ma20"), volume_ratio=bindparam("b_ratio"))
    )

    updated = 0
    pending: List[Dict[str, object]] = []
    for plan in plans:
        for row_date, ma20, ratio in plan.rows:
            pending.append({"b_code": plan.code, "b_date": row_date, "b_ma20": ma20, "b_ratio": ratio})

    with db.session_scope() as session:
        for start in range(0, len(pending), UPDATE_CHUNK_SIZE):
            chunk = pending[start : start + UPDATE_CHUNK_SIZE]
            session.execute(statement, chunk)
            updated += len(chunk)
    return updated


def _parse_codes(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    codes = [item.strip() for item in raw.split(",") if item.strip()]
    return codes or None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填 stock_daily 缺失的 ma20 / volume_ratio")
    parser.add_argument("--apply", action="store_true", help="实际写库；不加则只做 dry-run 统计")
    parser.add_argument("--codes", default=None, help="只处理指定股票代码，逗号分隔")
    parser.add_argument("--max-codes", type=int, default=None, help="最多处理的股票数量（安全上限）")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    db = DatabaseManager.get_instance()
    codes = _parse_codes(args.codes)
    if args.max_codes is not None:
        if args.max_codes <= 0:
            print("--max-codes 必须为正整数", file=sys.stderr)
            return 2
        codes = codes if codes is not None else _iter_candidate_codes(db)
        codes = codes[: args.max_codes]

    plans, totals = build_plans(db, codes)

    print("=" * 56)
    print("指标回填计划")
    print(f"  检查股票数        : {totals.codes_inspected}")
    print(f"  待回填股票数      : {totals.codes_affected}")
    print(f"  待回填行数        : {totals.rows_planned}")
    print(f"  无法计算行数      : {totals.rows_uncomputable}")
    print("=" * 56)

    if not args.apply:
        print("dry-run：未写库。确认规模后加 --apply 执行。")
        return 0

    if not plans:
        print("没有需要回填的数据。")
        return 0

    updated = apply_plans(db, plans)
    print(f"已回填 {updated} 行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
