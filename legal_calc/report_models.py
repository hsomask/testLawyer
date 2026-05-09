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


class CalculationResult(BaseModel):
    """单次计算统一出口，便于 API 与导出。"""

    ok: bool = Field(description="业务规则实现完整且通过自检时为 True")
    rule_version: str
    assumptions_used: list[str] = Field(default_factory=list)
    lines: list[ReportLineItem] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)

    def line_amount_sum(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal("0.00"))
