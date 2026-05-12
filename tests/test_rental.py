"""房屋租赁：滞纳金（至起诉日、DOM 交租日）、占用费、Decimal 与导出。"""

from datetime import date
from decimal import Decimal

import pytest

from legal_calc.export import export_rental_workbook
from legal_calc.rental import RentalRequest, calculate_rental
from legal_calc.rental.models import due_date_by_day_of_month


def test_due_date_clamp_dom_exceeds_month_length() -> None:
    """应交租日：日序大于当月天数时钳为当月最后一日。"""
    assert due_date_by_day_of_month(2025, 2, 31) == date(2025, 2, 28)


def test_late_fee_starts_accrual_day_not_arrears_window() -> None:
    """滞纳金与欠租统计区间脱钩：从应交租次日起，不必晚于欠租统计起点日。"""
    req = RentalRequest(
        monthly_rent=Decimal("6000.00"),
        arrears_period_start=date(2025, 1, 10),
        arrears_period_end=date(2025, 1, 31),
        rent_due_day_of_month=5,
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=date(2025, 3, 15),
        filing_date=date(2025, 4, 1),
    )
    assert due_date_by_day_of_month(2025, 1, 5) == date(2025, 1, 5)
    out = calculate_rental(req)
    assert out.ok
    late = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert late
    assert all(ln.period_start >= date(2025, 1, 6) for ln in late)


def test_lease_caps_month_range_before_filing() -> None:
    """租期止与起诉日取早，滞纳金月份不超出租期。"""
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 6, 30),
        rent_due_day_of_month=26,
        lease_start=date(2025, 3, 1),
        lease_end=date(2025, 4, 30),
        contract_termination_date=date(2025, 7, 1),
        actual_vacate_date=date(2025, 7, 10),
        filing_date=date(2025, 8, 1),
    )
    out = calculate_rental(req)
    assert out.ok
    late = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert not any("2025年01月" in ln.stage_description for ln in late)
    assert not any("2025年02月" in ln.stage_description for ln in late)
    assert any("2025年03月" in ln.stage_description for ln in late)
    assert any("2025年04月" in ln.stage_description for ln in late)
    assert not any("2025年05月" in ln.stage_description for ln in late)


def test_occupancy_no_fee_when_vacate_before_start() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_day_of_month=31,
        contract_termination_date=date(2025, 3, 10),
        actual_vacate_date=date(2025, 3, 5),
        filing_date=date(2025, 5, 1),
    )
    out = calculate_rental(req)
    occ = [ln for ln in out.lines if ln.fee_category == "房屋占用费"]
    assert len(occ) == 0
    assert any("早于起算" in m for m in out.messages)
    assert any("占用费: 0" in m for m in out.messages)


def test_lease_start_after_filing_raises() -> None:
    """租期起晚于 min(租期止, 起诉日) 时无法列滞纳金月份。"""
    req = RentalRequest(
        monthly_rent=Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_day_of_month=15,
        lease_start=date(2025, 6, 1),
        lease_end=date(2025, 12, 31),
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=date(2025, 3, 15),
        filing_date=date(2025, 5, 1),
    )
    with pytest.raises(ValueError, match="滞纳金：租期起"):
        calculate_rental(req)


def test_export_rental_workbook() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_day_of_month=26,
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
        rent_due_day_of_month=28,
        contract_termination_date=date(2024, 12, 1),
        actual_vacate_date=date(2024, 12, 20),
        filing_date=date(2025, 1, 1),
    )
    out = calculate_rental(req)
    for ln in out.lines:
        assert type(ln.amount) is Decimal
        assert type(ln.principal_base) is Decimal
