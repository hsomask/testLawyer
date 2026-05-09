"""FastAPI 交付层烟测。"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from legal_calc.private_lending import PrivateLendingRequest, calculate_private_lending


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
