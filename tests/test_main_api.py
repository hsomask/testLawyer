"""FastAPI 交付层烟测 + API 结果一致性测试。"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from legal_calc.private_lending import PrivateLendingRequest, calculate_private_lending
from legal_calc.rental import RentalRequest

# ── 共享 test client ──────────────────────────────────────────────


def _client():
    from main import app

    return TestClient(app)


# ── 基础烟测 ──────────────────────────────────────────────────────


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


# ── API 结果一致性测试 ────────────────────────────────────────────


def test_api_interest_subtotal_equals_sum_of_interest_lines():
    """POST /api/calculate 的 interest_subtotal 应等于利息行 amount 加总。"""
    c = _client()
    body = {
        "principal": "10000.00",
        "loan_date": "2020-09-01",
        "end_date": "2020-10-31",
        "agreed_annual_rate": "0.12",
        "filing_date": "2020-10-15",
        "repayments": [],
    }
    r = c.post("/api/calculate", json=body)
    assert r.status_code == 200
    data = r.json()
    interest_lines = [ln for ln in data["lines"] if ln["fee_category"] == "利息"]
    interest_sum = sum(Decimal(ln["amount"]) for ln in interest_lines)
    assert Decimal(data["interest_subtotal"]) == interest_sum, (
        f"interest_subtotal 不等于利息行加总: {data['interest_subtotal']} != {interest_sum}"
    )


def test_api_total_equals_interest_plus_remaining():
    """POST /api/calculate 的 total_principal_and_interest == interest_subtotal + remaining_principal。"""
    c = _client()
    body = {
        "principal": "10000.00",
        "loan_date": "2020-09-01",
        "end_date": "2020-10-31",
        "agreed_annual_rate": "0.12",
        "filing_date": "2020-10-15",
        "repayments": [],
    }
    r = c.post("/api/calculate", json=body)
    assert r.status_code == 200
    data = r.json()
    ist = Decimal(data["interest_subtotal"])
    rp = Decimal(data["remaining_principal"])
    tpi = Decimal(data["total_principal_and_interest"])
    assert tpi == ist + rp, f"total_principal_and_interest 不一致: {tpi} != {ist} + {rp}"


def test_rental_api_returns_lines_and_messages():
    """POST /api/rental/calculate 返回 lines、messages、rule_version，三字段为 null。"""
    c = _client()
    body = {
        "monthly_rent": "3000.00",
        "arrears_period_start": "2025-01-01",
        "arrears_period_end": "2025-01-31",
        "rent_due_day_of_month": 26,
        "contract_termination_date": "2025-03-01",
        "actual_vacate_date": None,
        "filing_date": "2025-04-01",
    }
    r = c.post("/api/rental/calculate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "rule_version" in data
    assert isinstance(data["lines"], list)
    assert len(data["lines"]) > 0
    assert isinstance(data["messages"], list)
    assert data.get("interest_subtotal") is None
    assert data.get("remaining_principal") is None
    assert data.get("total_principal_and_interest") is None


def test_rental_api_lines_distinguishable_by_fee_category():
    """POST /api/rental/calculate 返回的 lines 可按 fee_category 区分。"""
    c = _client()
    body = {
        "monthly_rent": "3000.00",
        "arrears_period_start": "2025-01-01",
        "arrears_period_end": "2025-01-31",
        "rent_due_day_of_month": 26,
        "contract_termination_date": "2025-03-01",
        "actual_vacate_date": "2025-03-15",
        "filing_date": "2025-04-01",
        "monthly_property_management_fee": "200.00",
        "monthly_utility_fee": "100.00",
    }
    r = c.post("/api/rental/calculate", json=body)
    assert r.status_code == 200
    categories = {ln["fee_category"] for ln in r.json()["lines"]}
    for expected in ["租金滞纳金", "物业费滞纳金", "水电费滞纳金", "房屋占用费"]:
        assert expected in categories, f"缺少费用类目: {expected}"


# ── 错误路径测试 ──────────────────────────────────────────────────


def test_finance_360_compound_rejected():
    """convention=finance_360_compound 应返回 400。"""
    c = _client()
    body = {
        "principal": "10000.00",
        "loan_date": "2020-09-01",
        "end_date": "2020-10-31",
        "agreed_annual_rate": "0.12",
        "convention": "finance_360_compound",
    }
    r = c.post("/api/calculate", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("360" in d.get("msg", "") for d in detail)


def test_no_agreed_rate_without_due_date_rejected():
    """无约定利率且未填 due_date 应返回 400。"""
    c = _client()
    body = {
        "principal": "10000.00",
        "loan_date": "2020-09-01",
        "end_date": "2020-10-31",
    }
    r = c.post("/api/calculate", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("due_date" in d.get("msg", "") for d in detail)


def test_rental_no_vacate_date_and_no_filing_date_rejected():
    """房屋租赁无 actual_vacate_date 且无 filing_date 应返回 422。"""
    c = _client()
    body = {
        "monthly_rent": "3000.00",
        "arrears_period_start": "2025-01-01",
        "arrears_period_end": "2025-01-31",
        "rent_due_day_of_month": 26,
        "contract_termination_date": "2025-03-01",
        "actual_vacate_date": None,
        "filing_date": None,
    }
    r = c.post("/api/rental/calculate", json=body)
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.json()}"
    detail = r.json()["detail"]
    assert any("起诉日" in d.get("msg", "") or "搬离" in d.get("msg", "") for d in detail)
