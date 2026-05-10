"""
房屋租赁：租金滞纳金（按日、一年期 LPR、无四倍）+ 房屋占用费。

计息与金额全程使用 Decimal；滞纳金按行先 round 再累加（与 PRD §10 一致）。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from legal_calc.common.lpr_json_file import JsonFileLprProvider
from legal_calc.money import quantize_money
from legal_calc.rental.models import RentalRequest, due_date_for_calendar_month
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


def _effective_arrears_window(req: RentalRequest) -> tuple[date, date]:
    """欠租区间与租期（若填）求交。"""
    start = req.arrears_period_start
    end = req.arrears_period_end
    if req.lease_start is not None:
        start = max(start, req.lease_start)
    if req.lease_end is not None:
        end = min(end, req.lease_end)
    if start > end:
        raise ValueError("欠租区间与租期（lease_start/lease_end）无交集，无法计算滞纳金")
    return start, end


def _late_fee_segment_for_month(
    y: int,
    m: int,
    req: RentalRequest,
    arrears_start: date,
    arrears_hi_excl: date,
    lpr: JsonFileLprProvider,
    lines: list[ReportLineItem],
) -> Decimal:
    """
    该月应付租的滞纳金：起算 max(应交租次日, arrears_start)，止算 arrears_hi_excl（半开）。
    返回本函数产生的**已舍入行金额之和**。
    """
    due = due_date_for_calendar_month(y, m, req.rent_due_days_before_month_end)
    accrual_start = due + timedelta(days=1)
    seg_lo = max(accrual_start, arrears_start)
    seg_hi_excl = arrears_hi_excl
    if seg_lo >= seg_hi_excl:
        return Decimal("0")

    base = req.monthly_rent
    if base <= 0:
        return Decimal("0")

    rounded_sum = Decimal("0")
    cuts = _lpr_cuts(seg_lo, seg_hi_excl, lpr)
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        days = (b - a).days
        if days <= 0:
            continue
        apr = lpr.get_annual_lpr(a)
        raw = base * apr * Decimal(days) / Decimal("365")
        amt = quantize_money(raw)
        rounded_sum += amt
        pend = b - timedelta(days=1)
        lines.append(
            ReportLineItem(
                fee_category="租金滞纳金",
                stage_description=(
                    f"{y}年{m:02d}月期｜应付租日 {due.isoformat()}；"
                    f"滞纳起算 {accrual_start.isoformat()}；"
                    f"计息区间 {a.isoformat()}～{pend.isoformat()}（{days} 日）；"
                    f"一年期 LPR={apr}（无四倍）"
                ),
                principal_base=quantize_money(base),
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

    arrears_start, arrears_end = _effective_arrears_window(req)
    arrears_hi_excl = arrears_end + timedelta(days=1)

    assumptions_used = [
        "滞纳金：应交租日次日；计息与欠租区间求交 max(起算日, 欠租起点)；止日=欠租区间末日（含）",
        "基数=月租金；利率=公布一年期 LPR÷365×自然日（无四倍）",
        "占用费：(月租金/30)×2×自然日；解除次日起；有搬离至搬离日（含），否则起诉日+30（含）",
        "金额：Decimal；按行四舍五入到分",
    ]
    if req.lease_start is not None or req.lease_end is not None:
        assumptions_used.append(
            f"租期裁剪：effective 欠租窗口 {arrears_start.isoformat()}～{arrears_end.isoformat()}"
        )

    months = _months_in_range_inclusive(arrears_start, arrears_end)
    late_total = Decimal("0")
    for y, m in months:
        late_total += _late_fee_segment_for_month(y, m, req, arrears_start, arrears_hi_excl, lpr, lines)

    occ_total = _occupancy_lines(req, lines, messages)

    grand = sum((ln.amount for ln in lines), Decimal("0.00"))
    messages.append(f"滞纳金小计（已舍入行加总）: {late_total}")
    messages.append(f"占用费: {occ_total}")
    messages.append(f"本表金额列合计: {grand}")

    return CalculationResult(
        ok=True,
        rule_version=RULE_VERSION,
        assumptions_used=assumptions_used,
        lines=lines,
        messages=messages,
    )
