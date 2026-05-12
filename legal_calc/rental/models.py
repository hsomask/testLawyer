from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class RentalRequest(BaseModel):
    """
    房屋租赁（PRD §2、§0 / §0.1）。

    - **租金滞纳金**：各自然月应交租日 = 当月 **`rent_due_day_of_month` 日**（超过当月天数的钳为月末）；
      自应交租日**次日**起至 **起诉日（含）** 按日计；基数=月租金；一年期 LPR（**无四倍**）。
    - **欠租统计区间**：``arrears_period_start``～``arrears_period_end``（含）**仅用于欠租本金统计展示**，**不参与**滞纳金计息区间（§0.1 第 15–16 条）。
    - **滞纳金所涉月份范围**：自 ``lease_start``（若填）否则 ``arrears_period_start`` 所在月起，至 ``min(lease_end, filing_date)``（若填 ``lease_end``）否则 ``filing_date`` 所在月止（均含）；与欠租区间脱钩。
    - **占用费**：解除日**次日**起至实际搬离日（含），或至起诉日+30（含）；日额 = 月租×2/30。
    """

    monthly_rent: Decimal = Field(gt=0, description="月租金")
    arrears_period_start: date = Field(description="欠租统计区间起点（含），本金统计用")
    arrears_period_end: date = Field(description="欠租统计区间终点（含），本金统计用")
    rent_due_day_of_month: int = Field(
        ge=1,
        le=31,
        description="每月应交租日为该月第几日（1=1 日）；大于当月天数时钳为当月最后一日",
    )

    contract_termination_date: date = Field(description="合同解除日")
    actual_vacate_date: date | None = Field(default=None, description="实际搬离日；无则占用费止日依赖起诉日+30")
    filing_date: date | None = Field(default=None, description="起诉日；滞纳金计至该日（含）；无实际搬离时亦必填以计占用费止日")

    lease_start: date | None = Field(default=None, description="租期起；滞纳金月份范围优先用其作为起点")
    lease_end: date | None = Field(default=None, description="租期止；与起诉日取早作为滞纳金月份范围终点")

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


def due_date_by_day_of_month(year: int, month: int, day_of_month: int) -> date:
    """
    应交租日：该自然月的第 ``day_of_month`` 日；若大于当月天数则钳为当月最后一日。
    """
    _, last_d = calendar.monthrange(year, month)
    d = min(day_of_month, last_d)
    return date(year, month, d)
