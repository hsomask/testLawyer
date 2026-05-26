"""
房屋租赁（PRD §2）：租金滞纳金 + 额外费用滞纳金 + 占用费 + 欠租本金。

- 滞纳金不再按 LPR 发布日分段，每月/每项取违约开始日固定 LPR。
- 占用费按自然月拆分：月租金 / 当月自然日天数 × 当月占用天数 × 2。
- 欠租本金按自然月拆分。
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from legal_calc.common.lpr_json_file import JsonFileLprProvider
from legal_calc.money import quantize_money
from legal_calc.rental.models import RentalExtraFeeItem, RentalRequest, due_date_by_day_of_month
from legal_calc.report_models import CalculationResult, RentalSummary, ReportLineItem
from legal_calc.version import RULE_VERSION

# 费用类目 → RentalSummary 字段映射
_FEE_CAT_UTILITY = "水电费滞纳金"
_FEE_CAT_PROPERTY = "物业费滞纳金"
_FEE_CAT_OTHER = "其他费用滞纳金"
_FEE_CAT_RENT = "租金滞纳金"
_FEE_CAT_OCCUPANCY = "房屋占用费"
_FEE_CAT_ARREARS = "欠租本金"


def _days_in_month(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _months_in_range_inclusive(lo: date, hi: date) -> list[tuple[int, int]]:
    """从 lo 所在自然月到 hi 所在自然月（含），各 (year, month)。"""
    out: list[tuple[int, int]] = []
    y, m = lo.year, lo.month
    ey, em = hi.year, hi.month
    while True:
        out.append((y, m))
        if y == ey and m == em:
            break
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return out


def _intersect_days_in_month(
    y: int, m: int, period_start: date, period_end_incl: date
) -> int:
    """返回 [period_start, period_end_incl] 与 (y,m) 自然月的交集天数。"""
    month_first = date(y, m, 1)
    month_last = date(y, m, _days_in_month(y, m))
    lo = max(period_start, month_first)
    hi = min(period_end_incl, month_last)
    if lo > hi:
        return 0
    return (hi - lo).days + 1


def _late_fee_month_range(req: RentalRequest) -> tuple[date, date]:
    """
    滞纳金所涉自然月的起、止日历日（含）。
    起点：lease_start（若填）否则 arrears_period_start；
    终点：min(lease_end, filing_date)（若填 lease_end）否则 filing_date。
    """
    assert req.filing_date is not None
    start = req.lease_start or req.arrears_period_start
    if req.lease_end is not None:
        end = min(req.lease_end, req.filing_date)
    else:
        end = req.filing_date
    if start > end:
        raise ValueError("滞纳金：租期起（或欠租统计起点）晚于 min(租期止, 起诉日)，请检查租期与起诉日")
    return start, end




def _fixed_lpr(as_of: date, lpr: JsonFileLprProvider) -> Decimal:
    """取 as_of 当日或之前最近一次已公布的一年期 LPR。"""
    return lpr.get_annual_lpr(as_of)


def _arrears_principal_lines(req: RentalRequest, lines: list[ReportLineItem]) -> Decimal:
    """
    欠租本金：按自然月拆分。
    应收租金 = Σ(月租金 / 当月天数 × 该月欠租天数)。
    返回 rent_receivable_subtotal。
    """
    start = req.arrears_period_start
    end = req.arrears_period_end
    months = _months_in_range_inclusive(start, end)
    total = Decimal("0")
    for y, m in months:
        days = _intersect_days_in_month(y, m, start, end)
        if days <= 0:
            continue
        dim = _days_in_month(y, m)
        raw = req.monthly_rent * Decimal(days) / Decimal(dim)
        amt = quantize_money(raw)
        total += amt
        lines.append(
            ReportLineItem(
                fee_category=_FEE_CAT_ARREARS,
                stage_description=(
                    f"{y}年{m:02d}月｜月租金 {req.monthly_rent} / {dim}天 × {days}天"
                ),
                principal_base=quantize_money(req.monthly_rent),
                rate_standard=f"当月天数 {dim}",
                period_start=max(start, date(y, m, 1)),
                period_end=min(end, date(y, m, dim)),
                day_count=days,
                amount=amt,
            )
        )
    return total


def _rent_late_fee_lines(
    req: RentalRequest,
    late_hi_excl: date,
    lpr: JsonFileLprProvider,
    lines: list[ReportLineItem],
) -> Decimal:
    """
    租金滞纳金：每个应付月一行。
    取违约开始日（应交日次日）的固定 LPR，不按发布日分段。
    返回 rent_late_fee_subtotal（已舍入行金额之和）。
    """
    range_lo, range_hi = _late_fee_month_range(req)
    months = _months_in_range_inclusive(range_lo, range_hi)
    total = Decimal("0")
    for y, m in months:
        due = due_date_by_day_of_month(y, m, req.rent_due_day_of_month)
        accrual_start = due + timedelta(days=1)
        if accrual_start >= late_hi_excl:
            continue
        days = (late_hi_excl - accrual_start).days
        if days <= 0:
            continue
        fixed_apr = _fixed_lpr(accrual_start, lpr)
        raw = req.monthly_rent * fixed_apr * Decimal(days) / Decimal("365")
        amt = quantize_money(raw)
        total += amt
        pend = late_hi_excl - timedelta(days=1)
        lines.append(
            ReportLineItem(
                fee_category=_FEE_CAT_RENT,
                stage_description=(
                    f"{y}年{m:02d}月期｜应付日 {due.isoformat()}；"
                    f"违约开始 {accrual_start.isoformat()}；"
                    f"固定 LPR 取值日 {accrual_start.isoformat()} 对应 {fixed_apr}；"
                    f"计息 {accrual_start.isoformat()}～{pend.isoformat()}（{days} 日）"
                ),
                principal_base=quantize_money(req.monthly_rent),
                rate_standard=f"年化小数 {fixed_apr}（固定，不分段）",
                period_start=accrual_start,
                period_end=pend,
                day_count=days,
                amount=amt,
            )
        )
    return total


def _extra_fee_late_lines(
    items: list[RentalExtraFeeItem],
    late_hi_excl: date,
    lpr: JsonFileLprProvider,
    lines: list[ReportLineItem],
) -> tuple[Decimal, Decimal, Decimal]:
    """
    额外费用滞纳金：每项一条。
    取违约开始日（应付日次日）的固定 LPR，不按发布日分段。
    返回 (utility_subtotal, property_subtotal, other_subtotal)。
    """
    category_map = {
        "utility": _FEE_CAT_UTILITY,
        "property": _FEE_CAT_PROPERTY,
        "other": _FEE_CAT_OTHER,
    }
    subtotals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for item in items:
        fee_cat = category_map[item.category]
        accrual_start = item.due_date + timedelta(days=1)
        if accrual_start >= late_hi_excl:
            continue
        days = (late_hi_excl - accrual_start).days
        if days <= 0:
            continue
        fixed_apr = _fixed_lpr(accrual_start, lpr)
        raw = item.amount * fixed_apr * Decimal(days) / Decimal("365")
        amt = quantize_money(raw)
        subtotals[item.category] += amt
        pend = late_hi_excl - timedelta(days=1)
        lines.append(
            ReportLineItem(
                fee_category=fee_cat,
                stage_description=(
                    f"{item.name}｜应付日 {item.due_date.isoformat()}；"
                    f"违约开始 {accrual_start.isoformat()}；"
                    f"固定 LPR 取值日 {accrual_start.isoformat()} 对应 {fixed_apr}；"
                    f"计息 {accrual_start.isoformat()}～{pend.isoformat()}（{days} 日）"
                ),
                principal_base=quantize_money(item.amount),
                rate_standard=f"年化小数 {fixed_apr}（固定，不分段）",
                period_start=accrual_start,
                period_end=pend,
                day_count=days,
                amount=amt,
            )
        )
    return (
        subtotals["utility"],
        subtotals["property"],
        subtotals["other"],
    )


def _occupancy_lines(req: RentalRequest, lines: list[ReportLineItem], messages: list[str]) -> Decimal:
    """
    占用费按自然月拆分：月租金 / 当月自然日天数 × 当月占用天数 × 2。
    返回 occupancy_fee_subtotal（已舍入行金额之和）。
    """
    occ_start = req.contract_termination_date + timedelta(days=1)
    if req.actual_vacate_date is not None:
        occ_end_inc = req.actual_vacate_date
    else:
        assert req.filing_date is not None
        occ_end_inc = req.filing_date + timedelta(days=30)

    if occ_end_inc < occ_start:
        messages.append(
            f"占用费：止日 {occ_end_inc.isoformat()} 早于起算日 {occ_start.isoformat()}，未产生占用费。"
        )
        return Decimal("0")

    months = _months_in_range_inclusive(occ_start, occ_end_inc)
    total = Decimal("0")
    for y, m in months:
        days = _intersect_days_in_month(y, m, occ_start, occ_end_inc)
        if days <= 0:
            continue
        dim = _days_in_month(y, m)
        raw = req.monthly_rent * Decimal(days) / Decimal(dim) * Decimal("2")
        amt = quantize_money(raw)
        total += amt
        first_of_month = date(y, m, 1)
        last_of_month = date(y, m, dim)
        actual_start = max(occ_start, first_of_month)
        actual_end = min(occ_end_inc, last_of_month)
        lines.append(
            ReportLineItem(
                fee_category=_FEE_CAT_OCCUPANCY,
                stage_description=(
                    f"{y}年{m:02d}月｜月租金 {req.monthly_rent} / {dim}天 × {days}天 × 2"
                ),
                principal_base=quantize_money(req.monthly_rent),
                rate_standard=f"月租 / {dim} × 2",
                period_start=actual_start,
                period_end=actual_end,
                day_count=days,
                amount=amt,
            )
        )
    return total


def calculate_rental(
    req: RentalRequest,
    lpr: JsonFileLprProvider | None = None,
) -> CalculationResult:
    lpr = lpr or JsonFileLprProvider()
    lines: list[ReportLineItem] = []
    messages: list[str] = []

    assert req.filing_date is not None
    late_hi_excl = req.filing_date + timedelta(days=1)

    range_lo, range_hi = _late_fee_month_range(req)

    # --- 欠租本金 ---
    rent_receivable = _arrears_principal_lines(req, lines)
    arrears_principal = rent_receivable - req.paid_rent_amount

    # --- 租金滞纳金 ---
    rent_late = _rent_late_fee_lines(req, late_hi_excl, lpr, lines)

    # --- 额外费用滞纳金 ---
    extra_items = req.extra_fee_items
    util_late, prop_late, other_late = _extra_fee_late_lines(extra_items, late_hi_excl, lpr, lines)

    # --- 占用费 ---
    occ_total = _occupancy_lines(req, lines, messages)

    # --- 组装汇总 ---
    grand = (
        arrears_principal
        + rent_late
        + util_late
        + prop_late
        + other_late
        + occ_total
    )
    rental_summary = RentalSummary(
        rent_receivable_subtotal=rent_receivable,
        paid_rent_amount=req.paid_rent_amount,
        arrears_principal_subtotal=arrears_principal,
        rent_late_fee_subtotal=rent_late,
        utility_late_fee_subtotal=util_late,
        property_late_fee_subtotal=prop_late,
        other_late_fee_subtotal=other_late,
        occupancy_fee_subtotal=occ_total,
        grand_total=quantize_money(grand),
    )

    # --- 口径说明 ---
    assumptions_used = [
        "滞纳金：不再按 LPR 发布日分段，每月/每项取违约开始日（应付日次日）的固定一年期 LPR",
        (
            f"滞纳金月份范围：{range_lo.isoformat()}～{range_hi.isoformat()}（含端月）；"
            "起点=租期起（若填）否则欠租统计起点；终点=min(租期止,起诉日)（若填租期止）否则起诉日"
        ),
        (
            f"欠租本金统计区间：{req.arrears_period_start.isoformat()}～{req.arrears_period_end.isoformat()}（含）；"
            "按自然月拆分：月租金 / 当月自然日天数 × 当月欠租天数"
        ),
        "占用费：按自然月拆分：月租金 / 当月自然日天数 × 当月占用天数 × 2",
        "金额：Decimal；按行四舍五入到分",
    ]
    if req.paid_rent_amount > 0:
        assumptions_used.append(
            f"已支付租金 {req.paid_rent_amount} 仅扣减欠租本金小计，不影响租金滞纳金基数"
        )
    if extra_items:
        item_cats = set(it.category for it in extra_items)
        cat_names = []
        if "utility" in item_cats:
            cat_names.append("水电费")
        if "property" in item_cats:
            cat_names.append("物业费")
        if "other" in item_cats:
            cat_names.append("其他")
        assumptions_used.append(
            f"额外费用（{', '.join(cat_names)}）：共 {len(extra_items)} 项，逐条取固定 LPR 不计分段"
        )

    messages.append(f"应收租金小计: {rent_receivable}")
    if req.paid_rent_amount > 0:
        messages.append(f"已支付租金合计: {req.paid_rent_amount}")
    messages.append(f"欠租本金小计: {arrears_principal}")
    messages.append(f"租金滞纳金小计: {rent_late}")
    if util_late > 0:
        messages.append(f"水电费滞纳金小计: {util_late}")
    if prop_late > 0:
        messages.append(f"物业费滞纳金小计: {prop_late}")
    if other_late > 0:
        messages.append(f"其他费用滞纳金小计: {other_late}")
    messages.append(f"房屋占用费小计: {occ_total}")
    messages.append(f"最终总计: {grand}")

    return CalculationResult(
        ok=True,
        rule_version=RULE_VERSION,
        assumptions_used=assumptions_used,
        lines=lines,
        messages=messages,
        rental_summary=rental_summary,
    )
