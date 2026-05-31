"""
房屋租赁（PRD §2）：租金滞纳金 + 额外费用滞纳金 + 占用费 + 欠租本金。

- 租金滞纳金：按时间轴累计欠租基数计算，以本金基数变化日（各月违约开始日）
  和 LPR 数值变化日切段；相邻同 LPR 且同基数合并。
- 额外费用滞纳金：按单项费用计算，以 LPR 数值变化日切段，相邻同 LPR 合并；
  不同费用项目之间不合并。
- 占用费：按自然月拆分：月租金 / 当月自然日天数 × 当月占用天数 × 2。
- 欠租本金：按自然月拆分。
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from legal_calc.common.lpr_json_file import JsonFileLprProvider
from legal_calc.money import quantize_money
from legal_calc.rental.models import RentalExtraFeeItem, RentalRequest, due_date_by_day_of_month
from legal_calc.report_models import CalculationResult, RentalSummary, ReportLineItem
from legal_calc.version import RULE_VERSION

# 费用类目
_FEE_CAT_UTILITY = "水电费滞纳金"
_FEE_CAT_PROPERTY = "物业费滞纳金"
_FEE_CAT_OTHER = "其他费用滞纳金"
_FEE_CAT_RENT = "租金滞纳金"
_FEE_CAT_OCCUPANCY = "房屋占用费"
_FEE_CAT_ARREARS = "欠租本金"


@dataclass
class _LateFeeSegment:
    """一个滞纳金候选分段（额外费用用）。"""
    period_start: date
    period_end: date   # inclusive
    day_count: int
    lpr: Decimal


@dataclass
class _RentLateFeeSegment:
    """租金滞纳金分段（含累计基数）。"""
    period_start: date
    period_end: date   # inclusive
    day_count: int
    lpr: Decimal
    active_base: Decimal


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




def _merge_adjacent_same_lpr(segments: list[_LateFeeSegment]) -> list[_LateFeeSegment]:
    """合并相邻且 LPR 数值相同的分段。"""
    if not segments:
        return []
    merged: list[_LateFeeSegment] = []
    for seg in segments:
        if (
            merged
            and merged[-1].lpr == seg.lpr
            and merged[-1].period_end + timedelta(days=1) == seg.period_start
        ):
            prev = merged[-1]
            merged[-1] = _LateFeeSegment(
                period_start=prev.period_start,
                period_end=seg.period_end,
                day_count=prev.day_count + seg.day_count,
                lpr=prev.lpr,
            )
        else:
            merged.append(seg)
    return merged


def _lpr_segments_merged_by_value(
    start: date,
    end_inclusive: date,
    lpr_provider: JsonFileLprProvider,
) -> list[_LateFeeSegment]:
    """
    在 [start, end_inclusive] 区间内按 LPR 发布日生成候选分段，
    每段取起始日对应的 LPR，最后合并相邻同值分段。
    """
    hi_excl = end_inclusive + timedelta(days=1)
    cuts = sorted(lpr_provider.publication_dates_in_open_interval(start, hi_excl))

    # 生成候选分段
    segments: list[_LateFeeSegment] = []
    seg_start = start
    for cut in cuts:
        seg_end = cut - timedelta(days=1)
        if seg_start <= seg_end:
            days = (seg_end - seg_start).days + 1
            apr = lpr_provider.get_annual_lpr(seg_start)
            segments.append(_LateFeeSegment(seg_start, seg_end, days, apr))
        seg_start = cut
    # 末段
    if seg_start <= end_inclusive:
        days = (end_inclusive - seg_start).days + 1
        apr = lpr_provider.get_annual_lpr(seg_start)
        segments.append(_LateFeeSegment(seg_start, end_inclusive, days, apr))

    return _merge_adjacent_same_lpr(segments)


def _merge_adjacent_same_lpr_and_base(
    segments: list[_RentLateFeeSegment],
) -> list[_RentLateFeeSegment]:
    """合并相邻且 LPR 相同且累计基数相同的分段。"""
    if not segments:
        return []
    merged: list[_RentLateFeeSegment] = []
    for seg in segments:
        if (
            merged
            and merged[-1].lpr == seg.lpr
            and merged[-1].active_base == seg.active_base
            and merged[-1].period_end + timedelta(days=1) == seg.period_start
        ):
            prev = merged[-1]
            merged[-1] = _RentLateFeeSegment(
                period_start=prev.period_start,
                period_end=seg.period_end,
                day_count=prev.day_count + seg.day_count,
                lpr=prev.lpr,
                active_base=prev.active_base,
            )
        else:
            merged.append(seg)
    return merged


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
    租金滞纳金：按时间轴累计欠租基数计算。

    1. 生成各应付月的租金义务（accrual_start = due_date + 1）；
    2. 切点 = 各义务 accrual_start + LPR 实际变化日 + filing_date+1；
    3. 每段累计基数 = 该段开始时已逾期的月租金之和；
    4. 合并相邻同 LPR 且同累积基数的分段。
    """
    filing_date = late_hi_excl - timedelta(days=1)
    range_lo, range_hi = _late_fee_month_range(req)
    months = _months_in_range_inclusive(range_lo, range_hi)

    # Step 1: 生成租金应付义务
    obligations: list[tuple[str, date, date]] = []  # (label, due_date, accrual_start)
    for y, m in months:
        due = due_date_by_day_of_month(y, m, req.rent_due_day_of_month)
        acc_start = due + timedelta(days=1)
        if acc_start < late_hi_excl:
            obligations.append((f"{y}年{m:02d}月租金", due, acc_start))

    if not obligations:
        return Decimal("0")

    # Step 2: 生成切点
    cuts: set[date] = set()
    cuts.add(late_hi_excl)
    for _, _, acc_start in obligations:
        cuts.add(acc_start)

    # 仅在 LPR 数值实际变化时才加入切点
    first_acc = obligations[0][2]
    pub_dates = lpr.publication_dates_in_open_interval(first_acc, late_hi_excl)
    for d in sorted(pub_dates):
        prev_lpr = lpr.get_annual_lpr(d - timedelta(days=1))
        curr_lpr = lpr.get_annual_lpr(d)
        if prev_lpr != curr_lpr:
            cuts.add(d)

    cut_list = sorted(cuts)

    # Step 3: 按切点生成分段（累计基数）
    segments: list[_RentLateFeeSegment] = []
    for i in range(len(cut_list) - 1):
        seg_start = cut_list[i]
        seg_end = cut_list[i + 1] - timedelta(days=1)
        days = (cut_list[i + 1] - cut_list[i]).days
        if days <= 0:
            continue
        active_base = sum(
            req.monthly_rent
            for _, _, acc_start in obligations
            if acc_start <= seg_start
        )
        if active_base <= 0:
            continue
        lpr_val = lpr.get_annual_lpr(seg_start)
        segments.append(
            _RentLateFeeSegment(seg_start, seg_end, days, lpr_val, active_base)
        )

    # Step 4: 合并相邻同 LPR 且同累积基数的分段
    merged = _merge_adjacent_same_lpr_and_base(segments)

    # Step 5: 生成明细行
    total = Decimal("0")
    for seg in merged:
        raw = seg.active_base * seg.lpr * Decimal(seg.day_count) / Decimal("365")
        amt = quantize_money(raw)
        total += amt
        months_count = int(seg.active_base / req.monthly_rent)
        lines.append(
            ReportLineItem(
                fee_category=_FEE_CAT_RENT,
                stage_description=(
                    f"累计逾期租金 {seg.active_base}｜"
                    f"截至本段起始日已逾期 {months_count} 期月租｜"
                    f"LPR={seg.lpr}"
                ),
                principal_base=quantize_money(seg.active_base),
                rate_standard=f"年化小数 {seg.lpr}",
                period_start=seg.period_start,
                period_end=seg.period_end,
                day_count=seg.day_count,
                amount=amt,
            )
        )
    return total


def _extra_fee_late_lines(
    items: list[RentalExtraFeeItem],
    late_hi_excl: date,
    lpr: JsonFileLprProvider,
    lines: list[ReportLineItem],
    messages: list[str],
) -> tuple[Decimal, Decimal, Decimal]:
    """
    额外费用滞纳金：每项单独计算，按 LPR 变化分段，合并相邻同值区间。
    due_date 晚于或等于起诉日时跳过并提示。
    返回 (utility_subtotal, property_subtotal, other_subtotal)。
    """
    category_map = {
        "utility": _FEE_CAT_UTILITY,
        "property": _FEE_CAT_PROPERTY,
        "other": _FEE_CAT_OTHER,
    }
    subtotals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    filing_date = late_hi_excl - timedelta(days=1)

    for item in items:
        fee_cat = category_map[item.category]
        accrual_start = item.due_date + timedelta(days=1)
        if accrual_start >= late_hi_excl:
            messages.append(
                f"额外费用「{item.name}」：应付日 {item.due_date.isoformat()} 不早于起诉日 {filing_date.isoformat()}，"
                "无滞纳期间，跳过"
            )
            continue

        segments = _lpr_segments_merged_by_value(accrual_start, filing_date, lpr)
        for seg in segments:
            raw = item.amount * seg.lpr * Decimal(seg.day_count) / Decimal("365")
            amt = quantize_money(raw)
            subtotals[item.category] += amt
            lines.append(
                ReportLineItem(
                    fee_category=fee_cat,
                    stage_description=(
                        f"{item.name}｜应付日 {item.due_date.isoformat()}；"
                        f"违约开始 {accrual_start.isoformat()}；"
                        f"LPR={seg.lpr}（本案全程不变）"
                    ),
                    principal_base=quantize_money(item.amount),
                    rate_standard=f"年化小数 {seg.lpr}",
                    period_start=seg.period_start,
                    period_end=seg.period_end,
                    day_count=seg.day_count,
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

    late_hi_excl = req.filing_date + timedelta(days=1)

    range_lo, range_hi = _late_fee_month_range(req)

    # --- 欠租本金 ---
    rent_receivable = _arrears_principal_lines(req, lines)
    arrears_principal = rent_receivable - req.paid_rent_amount
    if arrears_principal < 0:
        messages.append(
            f"已支付租金 {req.paid_rent_amount} 超过应收租金 {rent_receivable}，欠租本金小计按 0 处理"
        )
        arrears_principal = Decimal("0")

    # --- 租金滞纳金 ---
    rent_late = _rent_late_fee_lines(req, late_hi_excl, lpr, lines)

    # --- 额外费用滞纳金 ---
    extra_items = req.extra_fee_items
    util_late, prop_late, other_late = _extra_fee_late_lines(extra_items, late_hi_excl, lpr, lines, messages)

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
        "滞纳金：按 LPR 发布日生成候选区间，合并相邻同 LPR 数值区间；仅 LPR 数值变化时拆分",
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
        (
            "line_amount_sum 为明细行金额（不含已支付租金扣减），"
            "最终总计以 rental_summary.grand_total 为准"
        ),
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
            f"额外费用（{', '.join(cat_names)}）：共 {len(extra_items)} 项，逐条按 LPR 变化分段并合并同值区间"
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
