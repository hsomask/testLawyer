"""
民间借贷计息：2020-08-19/20 分界 + 先息后本冲抵。

全部金额与利率运算使用 ``decimal.Decimal``，禁止在计息路径使用 float。
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from legal_calc.common.lpr_json_file import JsonFileLprProvider
from legal_calc.money import quantize_money
from legal_calc.report_models import CalculationResult, ReportLineItem
from legal_calc.version import RULE_VERSION

# 2020-08-19（含）为旧规则最后一日；2020-08-20 起为新规则段（与 PRD 一致）
POLICY_NEW_START = date(2020, 8, 20)
OLD_SEGMENT_CAP_ANNUAL = Decimal("0.24")


class InterestConvention(str, Enum):
    """金融类计息方式不接受（请求阶段拒绝）。"""

    CIVIL_365_SIMPLE = "civil_365_simple"
    FINANCE_360_COMPOUND = "finance_360_compound"


class Repayment(BaseModel):
    repayment_date: date
    amount: Decimal = Field(ge=0)

    @field_validator("amount")
    @classmethod
    def quantize_amount(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


class PrivateLendingRequest(BaseModel):
    """计算请求：本金、日期、还款、约定利率或到期日、起诉/文档月等。"""

    principal: Decimal = Field(gt=0)
    loan_date: date
    repayments: list[Repayment] = Field(default_factory=list)
    end_date: date
    filing_date: date | None = None
    lpr_document_month: date | None = None
    agreed_annual_rate: Decimal | None = Field(default=None, ge=0)
    due_date: date | None = None
    convention: InterestConvention = Field(default=InterestConvention.CIVIL_365_SIMPLE)

    @field_validator("principal")
    @classmethod
    def quantize_principal(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def validate_business_rules(self) -> PrivateLendingRequest:
        if self.convention == InterestConvention.FINANCE_360_COMPOUND:
            raise ValueError(
                "本计算器不适用银行借款、金融公司等「复利 / 360 天/年」产品；请使用民间借贷单利 365 口径。"
            )
        if self.agreed_annual_rate is None and self.due_date is None:
            raise ValueError("无约定年化利率时必须提供 due_date（到期日）")
        return self


def effective_accrual_end_date(req: PrivateLendingRequest) -> date:
    """计息末日（含）：有起诉日时取 max(截止计息日, 起诉日)，否则为截止计息日（§0.1 第 13、14 条）。"""
    if req.filing_date is None:
        return req.end_date
    return max(req.end_date, req.filing_date)


def merged_repayments(repayments: list[Repayment]) -> list[tuple[date, Decimal]]:
    buckets: dict[date, Decimal] = {}
    for r in repayments:
        prev = buckets.get(r.repayment_date, Decimal("0"))
        buckets[r.repayment_date] = prev + r.amount
    return sorted(buckets.items(), key=lambda x: x[0])


def last_day_of_month(d: date) -> date:
    _, last_d = calendar.monthrange(d.year, d.month)
    return date(d.year, d.month, last_d)


def lpr_four_x_reference_date(req: PrivateLendingRequest) -> date:
    if req.filing_date is not None:
        return req.filing_date
    if req.lpr_document_month is not None:
        return req.lpr_document_month
    return effective_accrual_end_date(req)


def four_x_cap_decimal(lpr: JsonFileLprProvider, ref: date) -> Decimal:
    eom = last_day_of_month(ref)
    return Decimal("4") * lpr.get_annual_lpr(eom)


def _chunk_policy_label(lo: date, hi_excl: date) -> str:
    last_day = hi_excl - timedelta(days=1)
    if last_day < POLICY_NEW_START:
        return "2020-08-19 及以前段（24% 上限）"
    if lo >= POLICY_NEW_START:
        return "2020-08-20 起段（LPR×4 上限）"
    return "跨政策分段（不应出现）"


def _build_cuts(
    lo: date,
    hi_excl: date,
    *,
    overdue_start: date | None,
    lpr: JsonFileLprProvider,
    need_lpr_cuts: bool,
) -> list[date]:
    cuts = {lo, hi_excl}
    if lo < POLICY_NEW_START < hi_excl:
        cuts.add(POLICY_NEW_START)
    if overdue_start is not None and lo < overdue_start < hi_excl:
        cuts.add(overdue_start)
    if need_lpr_cuts:
        for d in lpr.publication_dates_in_open_interval(lo, hi_excl):
            cuts.add(d)
    return sorted(cuts)


def _period_interest_simple_365(
    principal: Decimal,
    annual_rate: Decimal,
    days: int,
) -> Decimal:
    if days <= 0 or principal <= 0 or annual_rate <= 0:
        return Decimal("0")
    return principal * annual_rate * Decimal(days) / Decimal("365")


def _accrue_lines_for_open_interval(
    principal: Decimal,
    lo: date,
    hi_excl: date,
    *,
    req: PrivateLendingRequest,
    lpr: JsonFileLprProvider,
    four_x_cap: Decimal,
    lines: list[ReportLineItem],
) -> Decimal:
    """
    半开区间 [lo, hi_excl) 上计息；还款日当日不计入本段，计入下一段首日。
    """
    if hi_excl <= lo or principal <= 0:
        return Decimal("0")

    has_agreed = req.agreed_annual_rate is not None
    agreed = req.agreed_annual_rate or Decimal("0")
    overdue_start = (req.due_date + timedelta(days=1)) if not has_agreed and req.due_date else None

    need_lpr_cuts = (
        not has_agreed
        and overdue_start is not None
        and hi_excl > overdue_start
        and lo >= overdue_start
    )

    cuts = _build_cuts(lo, hi_excl, overdue_start=overdue_start, lpr=lpr, need_lpr_cuts=need_lpr_cuts)
    rounded_sum = Decimal("0")

    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        days = (b - a).days
        if days <= 0:
            continue

        if has_agreed:
            if b <= POLICY_NEW_START:
                annual = min(agreed, OLD_SEGMENT_CAP_ANNUAL)
                desc = f"有约定·min(约定,24%)，段内{_chunk_policy_label(a, b)}"
            elif a >= POLICY_NEW_START:
                annual = min(agreed, four_x_cap)
                desc = f"有约定·min(约定,LPR×4)，段内{_chunk_policy_label(a, b)}"
            else:
                raise RuntimeError("政策切分缺失")
        else:
            assert overdue_start is not None
            if b <= overdue_start:
                annual = Decimal("0")
                desc = "无约定·期内不计息（至到期日当日）"
            elif a >= overdue_start:
                annual = lpr.get_annual_lpr(a)
                desc = f"无约定·逾期一年期 LPR（无四倍），报价适用日 {a.isoformat()}"
            else:
                raise RuntimeError("逾期切分缺失")

        raw = _period_interest_simple_365(principal, annual, days)
        amt_q = quantize_money(raw)
        rounded_sum += amt_q

        pend = b - timedelta(days=1)
        lines.append(
            ReportLineItem(
                fee_category="利息",
                stage_description=f"{a.isoformat()}～{pend.isoformat()}；{desc}",
                principal_base=quantize_money(principal),
                rate_standard=f"年化小数 {annual}",
                period_start=a,
                period_end=pend,
                day_count=days,
                amount=amt_q,
            )
        )

    return rounded_sum


def calculate_private_lending(
    req: PrivateLendingRequest,
    lpr: JsonFileLprProvider | None = None,
) -> CalculationResult:
    """
    民间借贷：先息后本冲抵；2020-08-19（含）旧规则末日、08-20 起新规则并强制拆段。

    参数与返回中的金额均为 Decimal；内部不因审计需要写入 float。
    """
    if req.end_date < req.loan_date:
        raise ValueError("end_date 不能早于 loan_date")

    d_eff = effective_accrual_end_date(req)
    if d_eff < req.loan_date:
        raise ValueError("计息末日（含 max(截止计息日,起诉日)）不能早于 loan_date")

    lpr = lpr or JsonFileLprProvider()
    four_x_cap = four_x_cap_decimal(lpr, lpr_four_x_reference_date(req))

    merged = merged_repayments(req.repayments)
    for rd, _ in merged:
        if rd < req.loan_date:
            raise ValueError(f"还款日 {rd} 早于借款日 {req.loan_date}")

    lines: list[ReportLineItem] = []
    assumptions_used: list[str] = [
        "POLICY: 2020-08-19（含）旧规则最后一日；2020-08-20 起新规则；跨区间强制拆段",
        "计息末日：有起诉日则为 max(截止计息日, 起诉日)；LPR×4：起诉月优先，否则文档月，否则计息末日所在月（月末回溯）",
        "有约定：min(约定,司法上限)；无约定：期内零息，逾期一年期 LPR（无四倍）",
        "冲抵：先息后本；半开区间 [锚点,还款日)；本金归零后不再计息",
        "精度：Decimal；金额按分四舍五入，按行舍入后参与冲抵",
    ]

    P: Decimal = req.principal
    owed_unpaid = Decimal("0")
    cursor = req.loan_date

    for repay_date, amount in merged:
        if P <= 0:
            assumptions_used.append("WARN: 本金已为 0 后仍有还款记录，已忽略")
            break
        if repay_date > d_eff:
            assumptions_used.append(
                f"WARN: 还款 {repay_date} 晚于计息末日 {d_eff.isoformat()}，本条未冲抵"
            )
            continue

        accrued_rounded = _accrue_lines_for_open_interval(
            P, cursor, repay_date, req=req, lpr=lpr, four_x_cap=four_x_cap, lines=lines
        )
        owed_unpaid += accrued_rounded

        if amount > owed_unpaid:
            rem = amount - owed_unpaid
            owed_unpaid = Decimal("0")
            P = P - rem
        else:
            owed_unpaid = owed_unpaid - amount

        cursor = repay_date
        if P <= 0:
            P = Decimal("0")
            break

    if P > 0 and cursor <= d_eff:
        _accrue_lines_for_open_interval(
            P,
            cursor,
            d_eff + timedelta(days=1),
            req=req,
            lpr=lpr,
            four_x_cap=four_x_cap,
            lines=lines,
        )

    return CalculationResult(
        ok=True,
        rule_version=RULE_VERSION,
        assumptions_used=assumptions_used,
        lines=lines,
        messages=[],
    )
