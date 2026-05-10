from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class RentalRequest(BaseModel):
    """
    房屋租赁（PRD §2、§0 备忘）。

    - **滞纳金**：欠租自然月内各期租金；应交租日 = 当月最后日历日 − ``rent_due_days_before_month_end``（0=月末当日）；
      自应交租日**次日**起按日累计，基数=月租金，利率=一年期 LPR（**无四倍**）。
    - **占用费**：解除日**次日**起至实际搬离日（含），或至起诉日+30（含）；日额 = 月租×2/30。
    - **欠租统计区间**：``arrears_period_start``～``arrears_period_end``（含），与应交租日次日求交后计息。
    - **租期裁剪**（可选）：若填 ``lease_start`` / ``lease_end``，滞纳金仅在与欠租区间**交集**内生成。
    """

    monthly_rent: Decimal = Field(gt=0, description="月租金")
    arrears_period_start: date = Field(description="欠租统计区间起点（含）")
    arrears_period_end: date = Field(description="欠租统计区间终点（含），滞纳金计至该日")
    rent_due_days_before_month_end: int = Field(
        ge=0,
        le=31,
        description="距该月末的自然日数；5 表示「月末前第 5 日」为应交租日",
    )

    contract_termination_date: date = Field(description="合同解除日")
    actual_vacate_date: date | None = Field(default=None, description="实际搬离日；无则占用费止日依赖起诉日+30")
    filing_date: date | None = Field(default=None, description="无实际搬离时必填")

    lease_start: date | None = Field(default=None, description="租期起，可选；与欠租区间求交后计滞纳金")
    lease_end: date | None = Field(default=None, description="租期止，可选")

    @field_validator("monthly_rent")
    @classmethod
    def q_rent(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def check_occ_and_dates(self) -> RentalRequest:
        if self.actual_vacate_date is None and self.filing_date is None:
            raise ValueError("无「实际搬离日」时必须提供「起诉日」以推算占用费止日（起诉日+30）")
        if self.arrears_period_end < self.arrears_period_start:
            raise ValueError("arrears_period_end 不能早于 arrears_period_start")
        if self.lease_start is not None and self.lease_end is not None and self.lease_end < self.lease_start:
            raise ValueError("lease_end 不能早于 lease_start")
        return self


def due_date_for_calendar_month(year: int, month: int, days_before_month_end: int) -> date:
    """
    应交租日：当月最后一日减去 ``days_before_month_end``（0=当月最后一日）。

    若 N 过大导致落到上月，则钳制为当月 1 日（避免非法或跨月歧义）。
    """
    first = date(year, month, 1)
    _, last_d = calendar.monthrange(year, month)
    anchor = date(year, month, last_d)
    due = anchor - timedelta(days=days_before_month_end)
    if due < first:
        return first
    return due
