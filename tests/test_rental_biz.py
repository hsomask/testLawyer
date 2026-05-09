from datetime import date
from decimal import Decimal

from legal_calc.rental import RentalRequest, calculate_rental


def test_late_fee_has_lines_and_occupancy() -> None:
    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 2, 28),
        rent_due_days_before_month_end=5,
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=None,
        filing_date=date(2025, 4, 1),
    )
    out = calculate_rental(req)
    assert out.ok
    assert any(ln.fee_category == "租金滞纳金" for ln in out.lines)
    occ = [ln for ln in out.lines if ln.fee_category == "房屋占用费"]
    assert len(occ) == 1
    assert occ[0].day_count > 0


def test_rental_requires_filing_if_no_vacate() -> None:
    try:
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 1, 31),
            rent_due_days_before_month_end=0,
            contract_termination_date=date(2025, 3, 1),
            actual_vacate_date=None,
            filing_date=None,
        )
    except ValueError:
        return
    raise AssertionError("expected ValueError")
