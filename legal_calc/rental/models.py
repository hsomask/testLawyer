from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class RentalRequest(BaseModel):
    """
    房屋租赁（业务确认 §6–§9）。
    滞纳金：欠租期间内各月租金子任务；应交租日为「每月「距该月末 N 日」」，`rent_due_days_before_month_end` 即 N（0=月末当日）。
    """

    monthly_rent: Decimal = Field(gt=0, description="月租金（用于滞纳金基数与占用费日标准）")
    arrears_period_start: date = Field(description="欠租统计 / 滞纳金计至区间起点（含该日所在月应付租逻辑）")
    arrears_period_end: date = Field(description="滞纳金计至该日（含）")
    rent_due_days_before_month_end: int = Field(
        ge=0,
        le=31,
        description='与「月末前 N 日」一致：N=5 表示应交租日=该月最后一日往回数 5 天（见实现）',
    )

    contract_termination_date: date = Field(description="合同解除日")
    actual_vacate_date: date | None = Field(default=None, description="实际搬离日")
    filing_date: date | None = Field(default=None, description="无实际搬离时必填，占用费止日为起诉日+30")

    lease_start: date | None = Field(default=None, description="预留与合同对齐，滞纳金不按此截取")
    lease_end: date | None = Field(default=None, description="预留")

    @field_validator("monthly_rent")
    @classmethod
    def q_rent(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def check_occ(self) -> RentalRequest:
        if self.actual_vacate_date is None and self.filing_date is None:
            raise ValueError("无「实际搬离日」时必须提供「起诉日」以推算占用费止日（起诉日+30）")
        return self


def due_date_for_calendar_month(year: int, month: int, days_before_month_end: int) -> date:
    """应交租日：该月末日减去 days_before_month_end（0=当月最后一日）。"""
    _, last_day = calendar.monthrange(year, month)
    anchor = date(year, month, last_day)
    return anchor - timedelta(days=days_before_month_end)
