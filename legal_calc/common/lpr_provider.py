"""LPR 数据源接口：业务可接 CSV、手工表或外部 API。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class LprProvider(Protocol):
    """查询某一日的适用年化 LPR（小数形式，如 0.0345 表示 3.45%）。"""

    def get_annual_lpr(self, as_of: date, tenor: str = "1Y") -> Decimal:
        ...


class DummyLprProvider:
    """测试与骨架阶段占位，不用于生产。"""

    def __init__(self, annual_rate: Decimal = Decimal("0.0345")) -> None:
        self._annual_rate = annual_rate

    def get_annual_lpr(self, as_of: date, tenor: str = "1Y") -> Decimal:
        _ = tenor
        _ = as_of
        return self._annual_rate
