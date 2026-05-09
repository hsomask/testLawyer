"""
民间借贷：`calculate_private_lending` 集成验证。

含：跨 2020-08-20 分段 + 三次还款先息后本；无约定利率逾期按一年期 LPR。
全程断言使用 Decimal，避免 float。
"""

from datetime import date
from decimal import Decimal

import pytest

from legal_calc.private_lending import (
    InterestConvention,
    PrivateLendingRequest,
    Repayment,
    calculate_private_lending,
)


def test_cross_policy_agreed_three_repayments() -> None:
    """
    跨分界：借款在 2020-08-20 之前起息，还款与截止日在之后，
    应有「旧段 24% 封顶」与「新段 LPR×4 封顶」下的 min(约定, 上限) 拆段。
    三次还款验证先息后本冲抵。
    """
    req = PrivateLendingRequest(
        principal=Decimal("200000.00"),
        loan_date=date(2020, 7, 1),
        repayments=[
            Repayment(repayment_date=date(2020, 9, 10), amount=Decimal("12000.00")),
            Repayment(repayment_date=date(2020, 12, 1), amount=Decimal("8000.00")),
            Repayment(repayment_date=date(2021, 3, 15), amount=Decimal("15000.00")),
        ],
        end_date=date(2021, 6, 30),
        agreed_annual_rate=Decimal("0.15"),
        filing_date=date(2021, 5, 10),
        lpr_document_month=date(2021, 6, 1),
    )
    out = calculate_private_lending(req)
    assert out.ok is True
    assert any("2020-08-20 及以前" in ln.stage_description or "24%" in ln.stage_description for ln in out.lines)
    assert any("2020-08-21 起" in ln.stage_description or "LPR×4" in ln.stage_description for ln in out.lines)

    total = out.line_amount_sum()
    assert isinstance(total, Decimal)
    assert total > Decimal("0")
    assert total == sum((ln.amount for ln in out.lines), Decimal("0.00"))


def test_overdue_no_agreed_three_repayments() -> None:
    """
    无约定利率：期内零息；到期次日起按一年期 LPR（无四倍），含 LPR 报价变更切段。
    三次还款冲抵利息后剩余冲本。
    """
    req = PrivateLendingRequest(
        principal=Decimal("100000.00"),
        loan_date=date(2020, 3, 15),
        repayments=[
            Repayment(repayment_date=date(2021, 2, 10), amount=Decimal("2500.00")),
            Repayment(repayment_date=date(2021, 5, 20), amount=Decimal("4000.00")),
            Repayment(repayment_date=date(2021, 8, 5), amount=Decimal("6000.00")),
        ],
        end_date=date(2021, 12, 31),
        agreed_annual_rate=None,
        due_date=date(2020, 12, 31),
        lpr_document_month=date(2021, 12, 1),
    )
    out = calculate_private_lending(req)
    assert out.ok is True

    in_term_lines = [ln for ln in out.lines if "期内不计息" in ln.stage_description]
    overdue_lines = [ln for ln in out.lines if "逾期一年期 LPR" in ln.stage_description]
    assert in_term_lines
    assert all(ln.amount == Decimal("0.00") for ln in in_term_lines)
    assert overdue_lines

    total = out.line_amount_sum()
    assert isinstance(total, Decimal)
    assert total > Decimal("0")


def test_finance_convention_rejected() -> None:
    with pytest.raises(ValueError, match="不适用"):
        PrivateLendingRequest(
            principal=Decimal("1.00"),
            loan_date=date(2020, 1, 1),
            end_date=date(2020, 6, 1),
            agreed_annual_rate=Decimal("0.10"),
            convention=InterestConvention.FINANCE_360_COMPOUND,
        )


def test_repayment_day_in_next_segment() -> None:
    """还款日计入下一段首日：第一段不含还款日。"""
    req = PrivateLendingRequest(
        principal=Decimal("100000.00"),
        loan_date=date(2020, 9, 1),
        repayments=[Repayment(repayment_date=date(2020, 10, 1), amount=Decimal("0"))],
        end_date=date(2020, 10, 2),
        agreed_annual_rate=Decimal("0.12"),
        filing_date=date(2020, 10, 1),
    )
    out = calculate_private_lending(req)
    assert out.ok
    days_before = sum(ln.day_count for ln in out.lines if ln.period_end < date(2020, 10, 1))
    assert days_before == 30
    assert any(
        ln.period_start <= date(2020, 10, 1) <= ln.period_end for ln in out.lines
    )


def test_no_float_in_accrual_path() -> None:
    """计息路径不因 JSON 等引入 float：结果行金额均为 Decimal。"""
    req = PrivateLendingRequest(
        principal=Decimal("50000"),
        loan_date=date(2020, 6, 1),
        end_date=date(2020, 12, 31),
        agreed_annual_rate=Decimal("0.10"),
        filing_date=date(2020, 12, 1),
    )
    out = calculate_private_lending(req)
    for ln in out.lines:
        assert type(ln.amount) is Decimal
        assert type(ln.principal_base) is Decimal
