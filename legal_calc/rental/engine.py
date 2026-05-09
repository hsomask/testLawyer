"""房屋租赁：滞纳金（按日、一年期 LPR 无量化四倍）、占用费（月租/30×2×自然日）。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from legal_calc.common.lpr_json_file import JsonFileLprProvider
from legal_calc.money import quantize_money
from legal_calc.rental.models import RentalRequest, due_date_for_calendar_month
from legal_calc.report_models import CalculationResult, ReportLineItem
from legal_calc.version import RULE_VERSION


def _months_in_range_inclusive(lo: date, hi: date) -> list[tuple[int, int]]:
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
    cuts = sorted({lo, hi_excl, *lpr.publication_dates_in_open_interval(lo, hi_excl)})
    return cuts


def calculate_rental(
    req: RentalRequest,
    lpr: JsonFileLprProvider | None = None,
) -> CalculationResult:
    if req.arrears_period_end < req.arrears_period_start:
        raise ValueError("arrears_period_end 不能早于 arrears_period_start")

    lpr = lpr or JsonFileLprProvider()
    lines: list[ReportLineItem] = []
    assumptions = [
        "滞纳金：应交租次日按日累计；利率为公布一年期 LPR（不适用四倍）",
        "欠租计费基数=各月约定的月租金；欠租按月生成子区间",
        "占用费：(月租金/30)×2×占用自然日；合同解除次日起算",
        "无实际搬离时占用费止于起诉日+30（含）；有实际搬离则止于搬离日（含）",
        "金额四舍五入到分，按行舍入",
    ]

    months = _months_in_range_inclusive(req.arrears_period_start, req.arrears_period_end)
    late_fee_hi_excl = req.arrears_period_end + timedelta(days=1)

    for y, m in months:
        due = due_date_for_calendar_month(y, m, req.rent_due_days_before_month_end)
        lo = due + timedelta(days=1)
        if lo >= late_fee_hi_excl:
            continue
        hi_excl = late_fee_hi_excl
        cuts = _lpr_cuts(lo, hi_excl, lpr)
        base = req.monthly_rent
        for i in range(len(cuts) - 1):
            a, b = cuts[i], cuts[i + 1]
            days = (b - a).days
            if days <= 0 or base <= 0:
                continue
            apr = lpr.get_annual_lpr(a)
            raw = base * apr * Decimal(days) / Decimal("365")
            amt = quantize_money(raw)
            if amt == Decimal("0") and raw == Decimal("0"):
                continue
            pend = b - timedelta(days=1)
            lines.append(
                ReportLineItem(
                    fee_category="租金滞纳金",
                    stage_description=f"{y}-{m:02d} 期应付租日 {due.isoformat()} 次日起；年化 LPR({apr}) 无四倍；{a.isoformat()}～{pend.isoformat()}",
                    principal_base=quantize_money(base),
                    rate_standard=f"年化小数 {apr}（滞纳金口径）",
                    period_start=a,
                    period_end=pend,
                    day_count=days,
                    amount=amt,
                )
            )

    occ_start = req.contract_termination_date + timedelta(days=1)
    if req.actual_vacate_date is not None:
        occ_end_inc = req.actual_vacate_date
    else:
        assert req.filing_date is not None
        occ_end_inc = req.filing_date + timedelta(days=30)
    occ_days = (occ_end_inc - occ_start).days + 1
    daily_rate = req.monthly_rent * Decimal("2") / Decimal("30")
    if occ_end_inc < occ_start:
        assumptions.append(
            f"WARN: 占用费止日 {occ_end_inc.isoformat()} 早于起算日 {occ_start.isoformat()}，未产生占用费"
        )
    elif occ_days > 0:
        raw_occ = daily_rate * Decimal(occ_days)
        lines.append(
            ReportLineItem(
                fee_category="房屋占用费",
                stage_description=f"标准为 (月租金/30)×2；{occ_start.isoformat()}～{occ_end_inc.isoformat()}（{occ_days} 自然日）",
                principal_base=quantize_money(req.monthly_rent),
                rate_standard="日标准=月租×2/30",
                period_start=occ_start,
                period_end=occ_end_inc,
                day_count=occ_days,
                amount=quantize_money(raw_occ),
            )
        )

    return CalculationResult(
        ok=True,
        rule_version=RULE_VERSION,
        assumptions_used=assumptions,
        lines=lines,
        messages=[],
    )
