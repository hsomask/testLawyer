"""从 JSON 配置文件读取 1 年期 LPR（年化小数）。"""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field


class LprQuoteRow(BaseModel):
    date: date
    value: Decimal = Field(description="年化利率小数，如 0.0345 表示 3.45%")


class LprJsonTable(BaseModel):
    unit: str
    currency: str
    description: str
    data: list[LprQuoteRow]


def default_lpr_1y_json_path() -> Path:
    """包内默认 1年期 LPR 表路径。"""
    return Path(__file__).resolve().parent.parent / "data" / "lpr_1y_cny.json"


class JsonFileLprProvider:
    """
    适用规则：取「报价发布日 <= as_of」中最新一条的 value（常用「按最近一次公布」口径）。
    仅支持 tenor=1Y 且与当前 JSON 语义一致时可用；其他期限需另建配置文件。
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else default_lpr_1y_json_path()
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self._table = LprJsonTable.model_validate(raw)
        if self._table.unit != "annual_rate":
            raise ValueError(f"不支持的 unit: {self._table.unit!r}，期望 annual_rate")
        self._dates: list[date] = [row.date for row in self._table.data]
        self._values: list[Decimal] = [row.value for row in self._table.data]
        if self._dates != sorted(self._dates):
            raise ValueError("LPR data 必须按 date 升序")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def table(self) -> LprJsonTable:
        return self._table

    def get_annual_lpr(self, as_of: date, tenor: str = "1Y") -> Decimal:
        if tenor != "1Y":
            raise NotImplementedError(f"当前 JSON 仅覆盖 1Y，收到 tenor={tenor!r}")
        if not self._dates:
            raise ValueError("LPR 表为空")
        i = bisect_right(self._dates, as_of) - 1
        if i < 0:
            raise ValueError(
                f"as_of={as_of.isoformat()} 早于表中首期 {self._dates[0].isoformat()}，请扩展 JSON 或调整查询日"
            )
        return self._values[i]

    @property
    def publication_dates(self) -> list[date]:
        """报价发布日列表（升序），用于按 LPR 变更切分计息区间。"""
        return list(self._dates)

    def publication_dates_in_open_interval(self, lo: date, hi_excl: date) -> list[date]:
        """满足 lo < d < hi_excl 的发布日。"""
        return [d for d in self._dates if lo < d < hi_excl]
