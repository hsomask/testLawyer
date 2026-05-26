"""报告行与计算结果（与 PRD Excel 列对齐）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ReportLineItem(BaseModel):
    """对应 PRD：费用类目、阶段说明、基数、利率标准、起止日与天数、应付金额。"""

    fee_category: str = Field(description="费用类目")
    stage_description: str = Field(description="阶段说明")
    principal_base: Decimal = Field(description="计算基数（本金或计费基数）")
    rate_standard: str = Field(description="利率标准（展示用文案）")
    period_start: date
    period_end: date
    day_count: int = Field(ge=0)
    amount: Decimal = Field(description="应付金额（利息/滞纳金等）")


class RentalSummary(BaseModel):
    """房屋租赁结构化汇总（PRD §二）。"""

    rent_receivable_subtotal: Decimal = Field(description="应收租金小计")
    paid_rent_amount: Decimal = Field(description="已支付租金合计")
    arrears_principal_subtotal: Decimal = Field(description="欠租本金小计 = 应收租金 - 已支付租金")
    rent_late_fee_subtotal: Decimal = Field(description="租金滞纳金小计")
    utility_late_fee_subtotal: Decimal = Field(description="水电费滞纳金小计")
    property_late_fee_subtotal: Decimal = Field(description="物业费滞纳金小计")
    other_late_fee_subtotal: Decimal = Field(description="其他费用滞纳金小计")
    occupancy_fee_subtotal: Decimal = Field(description="房屋占用费小计")
    grand_total: Decimal = Field(description="最终总计")


class CalculationResult(BaseModel):
    """单次计算统一出口，便于 API 与导出。"""

    ok: bool = Field(description="业务规则实现完整且通过自检时为 True")
    rule_version: str
    assumptions_used: list[str] = Field(default_factory=list)
    lines: list[ReportLineItem] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    # 民间借贷 PRD §3.1；租赁等场景保持为 None
    interest_subtotal: Decimal | None = Field(
        default=None,
        description="利息类 ReportLineItem 金额之和（按行舍入后再加总）",
    )
    remaining_principal: Decimal | None = Field(
        default=None,
        description="冲抵后剩余本金（与计息末日时点一致）",
    )
    total_principal_and_interest: Decimal | None = Field(
        default=None,
        description="本息合计：冲抵后剩余本金 + 利息小计",
    )
    # 房屋租赁 PRD §二
    rental_summary: RentalSummary | None = Field(
        default=None,
        description="房屋租赁结构化汇总；民间借贷为 None",
    )

    def line_amount_sum(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal("0.00"))
