"""FastAPI 交付层烟测。"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from legal_calc.private_lending import PrivateLendingRequest, calculate_private_lending
from legal_calc.rental import RentalRequest


def test_health_and_calculate():
    from main import app

    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok"}

    body = {
        "principal": "100000.00",
        "loan_date": "2020-09-01",
        "end_date": "2020-12-31",
        "repayments": [],
        "agreed_annual_rate": "0.12",
        "filing_date": "2020-12-01",
        "convention": "civil_365_simple",
    }
    r = c.post("/api/calculate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "rule_version" in data
    assert data["interest_subtotal"] is not None
    assert data["remaining_principal"] is not None
    assert data["total_principal_and_interest"] is not None


def test_export_excel_bytes():
    from main import app

    req = PrivateLendingRequest(
        principal=Decimal("50000"),
        loan_date=date(2020, 6, 1),
        end_date=date(2020, 12, 31),
        agreed_annual_rate=Decimal("0.10"),
        filing_date=date(2020, 12, 1),
    )
    c = TestClient(app)
    r = c.post("/api/export/excel", json=req.model_dump(mode="json"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(r.content) > 1000
    assert r.content[:2] == b"PK"


def test_calculate_matches_engine():
    from main import app

    req = PrivateLendingRequest(
        principal=Decimal("10000"),
        loan_date=date(2020, 9, 1),
        end_date=date(2020, 10, 31),
        agreed_annual_rate=Decimal("0.12"),
        filing_date=date(2020, 10, 15),
    )
    direct = calculate_private_lending(req)
    c = TestClient(app)
    r = c.post("/api/calculate", json=req.model_dump(mode="json"))
    assert r.json() == direct.model_dump(mode="json")


def test_rental_calculate_and_export():
    from main import app

    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_day_of_month=26,
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=None,
        filing_date=date(2025, 4, 1),
    )
    c = TestClient(app)
    r = c.post("/api/rental/calculate", json=req.model_dump(mode="json"))
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("interest_subtotal") is None
    assert data.get("remaining_principal") is None
    assert data.get("total_principal_and_interest") is None

    r2 = c.post("/api/rental/export/excel", json=req.model_dump(mode="json"))
    assert r2.status_code == 200
    assert r2.content[:2] == b"PK"
