"""房屋租赁：滞纳金窗口、租期裁剪、占用费、Decimal 与导出。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from legal_calc.export import export_rental_workbook
from legal_calc.rental import RentalRequest, calculate_rental
from legal_calc.rental.models import due_date_for_calendar_month


def test_due_date_clamp_large_n() -> None:
    """N 过大时应交租日钳制为当月 1 日。"""
    d = due_date_for_calendar_month(2025, 2, 31)
    assert d == date(2025, 2, 1)


def test_late_fee_respects_arrears_start_mid_window() -> None:
    """欠租从 1/10 起算、应交租次日早于该日时，计息从欠租起点起。"""
    req = RentalRequest(
        monthly_rent=Decimal("6000.00"),
        arrears_period_start=date(2025, 1, 10),
        arrears_period_end=date(2025, 1, 31),
        rent_due_days_before_month_end=26,
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=date(2025, 3, 15),
        filing_date=date(2025, 4, 1),
    )
    due = due_date_for_calendar_month(2025, 1, 26)
    assert due == date(2025, 1, 5)
    assert due + timedelta(days=1) == date(2025, 1, 6)
    out = calculate_rental(req)
    assert out.ok
    late = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert late
    assert all(ln.period_start >= date(2025, 1, 10) for ln in late)


def test_lease_clip_reduces_months() -> None:
    """租期与欠租求交后月份减少。"""
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 6, 30),
        rent_due_days_before_month_end=5,
        lease_start=date(2025, 3, 1),
        lease_end=date(2025, 4, 30),
        contract_termination_date=date(2025, 7, 1),
        actual_vacate_date=date(2025, 7, 10),
        filing_date=date(2025, 8, 1),
    )
    out = calculate_rental(req)
    assert out.ok
    assert "租期裁剪" in "\n".join(out.assumptions_used)
    late = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert not any("2025年01月" in ln.stage_description for ln in late)
    assert not any("2025年02月" in ln.stage_description for ln in late)
    assert any("2025年03月" in ln.stage_description for ln in late)


def test_occupancy_no_fee_when_vacate_before_start() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_days_before_month_end=0,
        contract_termination_date=date(2025, 3, 10),
        actual_vacate_date=date(2025, 3, 5),
        filing_date=date(2025, 5, 1),
    )
    out = calculate_rental(req)
    occ = [ln for ln in out.lines if ln.fee_category == "房屋占用费"]
    assert len(occ) == 0
    assert any("早于起算" in m for m in out.messages)
    assert any("占用费: 0" in m for m in out.messages)


def test_lease_intersection_empty_raises() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_days_before_month_end=0,
        lease_start=date(2025, 6, 1),
        lease_end=date(2025, 12, 31),
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=date(2025, 3, 15),
        filing_date=date(2025, 5, 1),
    )
    with pytest.raises(ValueError, match="无交集"):
        calculate_rental(req)


def test_export_rental_workbook() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_days_before_month_end=5,
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=None,
        filing_date=date(2025, 4, 1),
    )
    out = calculate_rental(req)
    bio = export_rental_workbook(req, out)
    assert bio.getvalue()[:2] == b"PK"


def test_line_amounts_decimal() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("5000"),
        arrears_period_start=date(2024, 10, 1),
        arrears_period_end=date(2024, 11, 30),
        rent_due_days_before_month_end=3,
        contract_termination_date=date(2024, 12, 1),
        actual_vacate_date=date(2024, 12, 20),
        filing_date=date(2025, 1, 1),
    )
    out = calculate_rental(req)
    for ln in out.lines:
        assert type(ln.amount) is Decimal
