"""日期区间与分段工具（与具体利率规则解耦）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def days_inclusive(period_start: date, period_end: date) -> int:
    """闭区间天数：起、止两日都计入。"""
    if period_end < period_start:
        raise ValueError("period_end 不能早于 period_start")
    return (period_end - period_start).days + 1


def split_segments(
    period_start: date,
    period_end: date,
    boundaries: Iterable[date],
    *,
    boundary_starts_new_segment: bool = True,
) -> list[tuple[date, date]]:
    """
    将闭区间 [period_start, period_end] 按分界日切成若干闭子区间。

    - boundary_starts_new_segment=True（默认）：分界日当天起适用「新段」，
      上一段在分界日前一日结束（与文档「2020-08-20 起为 LPR 段」的常见实现一致，**仍以业务定稿为准**）。
    - boundary_starts_new_segment=False：分界日仍属旧段，新段从次日开始。
    """
    if period_end < period_start:
        raise ValueError("period_end 不能早于 period_start")

    raw = sorted({b for b in boundaries if period_start < b <= period_end})
    if not raw:
        return [(period_start, period_end)]

    segments: list[tuple[date, date]] = []
    cursor = period_start

    for b in raw:
        if boundary_starts_new_segment:
            seg_end = b - timedelta(days=1)
            if seg_end >= cursor:
                segments.append((cursor, seg_end))
            cursor = b
        else:
            seg_end = b
            if seg_end >= cursor:
                segments.append((cursor, seg_end))
            cursor = b + timedelta(days=1)

    if cursor <= period_end:
        segments.append((cursor, period_end))

    return segments
