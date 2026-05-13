"""
房屋租赁：租金滞纳金（按日、一年期 LPR、无四倍）+ 房屋占用费。

计息与金额全程使用 Decimal；滞纳金按行先 round 再累加（与 PRD §10 一致）。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from legal_calc.common.lpr_json_file import JsonFileLprProvider
from legal_calc.money import quantize_money
from legal_calc.rental.models import RentalRequest, due_date_by_day_of_month
from legal_calc.report_models import CalculationResult, ReportLineItem
from legal_calc.version import RULE_VERSION


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


def _lpr_cuts(lo: date, hi_excl: date, lpr: JsonFileLprProvider) -> list[date]:
    return sorted({lo, hi_excl, *lpr.publication_dates_in_open_interval(lo, hi_excl)})


def _late_fee_month_range(req: RentalRequest) -> tuple[date, date]:
    """
    滞纳金所涉自然月的起、止日历日（含），用于枚举月份。
    起点：租期起（若填）否则欠租统计起点；终点：min(租期止, 起诉日)（若填租期止）否则起诉日。
    """
    assert req.filing_date is not None
    start = req.lease_start or req.arrears_period_start
    if req.lease_end is not None:
        end = min(req.lease_end, req.filing_date)
    else:
        end = req.filing_date
    if start > end:
        raise ValueError(
            "滞纳金：租期起（或欠租统计起点）晚于 min(租期止, 起诉日)，请检查租期与起诉日"
        )
    return start, end


def _late_fee_segment_for_month(
    y: int,
    m: int,
    req: RentalRequest,
    late_hi_excl: date,
    lpr: JsonFileLprProvider,
    lines: list[ReportLineItem],
    *,
    monthly_base: Decimal,
    fee_category: str,
) -> Decimal:
    """
    该月某一「月费」流的滞纳金：起算应交日次日（与 rent_due_day_of_month 同构）；止算 late_hi_excl（半开，即含起诉日）。
    返回本函数产生的**已舍入行金额之和**。
    """
    due = due_date_by_day_of_month(y, m, req.rent_due_day_of_month)
    accrual_start = due + timedelta(days=1)
    seg_lo = accrual_start
    seg_hi_excl = late_hi_excl
    if seg_lo >= seg_hi_excl:
        return Decimal("0")

    if monthly_base <= 0:
        return Decimal("0")

    rounded_sum = Decimal("0")
    cuts = _lpr_cuts(seg_lo, seg_hi_excl, lpr)
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        days = (b - a).days
        if days <= 0:
            continue
        apr = lpr.get_annual_lpr(a)
        raw = monthly_base * apr * Decimal(days) / Decimal("365")
        amt = quantize_money(raw)
        rounded_sum += amt
        pend = b - timedelta(days=1)
        lines.append(
            ReportLineItem(
                fee_category=fee_category,
                stage_description=(
                    f"{y}年{m:02d}月期｜{fee_category}｜应付日 {due.isoformat()}（与交租日同序）；"
                    f"滞纳起算 {accrual_start.isoformat()}；"
                    f"计息区间 {a.isoformat()}～{pend.isoformat()}（{days} 日）；"
                    f"一年期 LPR={apr}（无四倍）"
                ),
                principal_base=quantize_money(monthly_base),
                rate_standard=f"年化小数 {apr}",
                period_start=a,
                period_end=pend,
                day_count=days,
                amount=amt,
            )
        )
    return rounded_sum


def _occupancy_lines(req: RentalRequest, lines: list[ReportLineItem], messages: list[str]) -> Decimal:
    """占用费一行；返回金额（已舍入）。"""
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

    occ_days = (occ_end_inc - occ_start).days + 1
    daily = req.monthly_rent * Decimal("2") / Decimal("30")
    raw_occ = daily * Decimal(occ_days)
    amt = quantize_money(raw_occ)
    lines.append(
        ReportLineItem(
            fee_category="房屋占用费",
            stage_description=(
                f"标准 (月租金/30)×2×自然日；"
                f"起 {occ_start.isoformat()} 止 {occ_end_inc.isoformat()}（{occ_days} 日）"
            ),
            principal_base=quantize_money(req.monthly_rent),
            rate_standard="日标准=月租×2/30",
            period_start=occ_start,
            period_end=occ_end_inc,
            day_count=occ_days,
            amount=amt,
        )
    )
    return amt


def calculate_rental(
    req: RentalRequest,
    lpr: JsonFileLprProvider | None = None,
) -> CalculationResult:
    lpr = lpr or JsonFileLprProvider()
    lines: list[ReportLineItem] = []
    messages: list[str] = []

    assert req.filing_date is not None
    range_lo, range_hi = _late_fee_month_range(req)
    late_hi_excl = req.filing_date + timedelta(days=1)

    assumptions_used = [
        "滞纳金：应交日为每月 rent_due_day_of_month 日（超当月天数则月末）；次日起至起诉日（含）",
        "欠租统计区间仅作本金统计口径，不裁滞纳金；月份范围见 messages",
        "租金滞纳金基数=月租金；利率=公布一年期 LPR÷365×自然日（无四倍）",
        "占用费：(月租金/30)×2×自然日；解除次日起；有搬离至搬离日（含），否则起诉日+30（含）",
        "金额：Decimal；按行四舍五入到分",
    ]
    assumptions_used.append(
        f"欠租本金统计区间 {req.arrears_period_start.isoformat()}～{req.arrears_period_end.isoformat()}（含）"
    )
    assumptions_used.append(
        f"滞纳金月份范围 {range_lo.isoformat()}～{range_hi.isoformat()}（含端月）"
    )
    if (req.monthly_property_management_fee or Decimal("0")) > 0 or (
        req.monthly_utility_fee or Decimal("0")
    ) > 0:
        assumptions_used.append(
            "Demo：物业费/水电费滞纳金与租金滞纳金同日起算、同月份范围、同 LPR 规则；"
            "应交日与 rent_due_day_of_month 对齐（业务评审用，定稿前可调整）"
        )

    months = _months_in_range_inclusive(range_lo, range_hi)
    rent_late_total = Decimal("0")
    prop_late_total = Decimal("0")
    util_late_total = Decimal("0")
    for y, m in months:
        rent_late_total += _late_fee_segment_for_month(
            y,
            m,
            req,
            late_hi_excl,
            lpr,
            lines,
            monthly_base=req.monthly_rent,
            fee_category="租金滞纳金",
        )
        if req.monthly_property_management_fee is not None and req.monthly_property_management_fee > 0:
            prop_late_total += _late_fee_segment_for_month(
                y,
                m,
                req,
                late_hi_excl,
                lpr,
                lines,
                monthly_base=req.monthly_property_management_fee,
                fee_category="物业费滞纳金",
            )
        if req.monthly_utility_fee is not None and req.monthly_utility_fee > 0:
            util_late_total += _late_fee_segment_for_month(
                y,
                m,
                req,
                late_hi_excl,
                lpr,
                lines,
                monthly_base=req.monthly_utility_fee,
                fee_category="水电费滞纳金",
            )

    occ_total = _occupancy_lines(req, lines, messages)

    grand = sum((ln.amount for ln in lines), Decimal("0.00"))
    late_all = rent_late_total + prop_late_total + util_late_total
    messages.append(f"租金滞纳金小计（已舍入行加总）: {rent_late_total}")
    if prop_late_total > 0:
        messages.append(f"物业费滞纳金小计（Demo）: {prop_late_total}")
    if util_late_total > 0:
        messages.append(f"水电费滞纳金小计（Demo）: {util_late_total}")
    messages.append(f"滞纳金合计（租金+可选 Demo 项）: {late_all}")
    messages.append(f"占用费: {occ_total}")
    messages.append(f"本表金额列合计: {grand}")

    return CalculationResult(
        ok=True,
        rule_version=RULE_VERSION,
        assumptions_used=assumptions_used,
        lines=lines,
        messages=messages,
    )
