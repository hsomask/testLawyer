from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from legal_calc.common.lpr_json_file import JsonFileLprProvider, default_lpr_1y_json_path


def test_default_path_exists() -> None:
    assert default_lpr_1y_json_path().is_file()


def test_exact_publish_date() -> None:
    p = JsonFileLprProvider()
    assert p.get_annual_lpr(date(2020, 8, 20)) == Decimal("0.0385")


def test_between_publishes_uses_previous_row() -> None:
    p = JsonFileLprProvider()
    # 2020-08-21 在 2020-08-20 与 2020-09-21 之间，应适用 2020-08-20 公布的值
    assert p.get_annual_lpr(date(2020, 8, 21)) == Decimal("0.0385")


def test_after_last_row_uses_last_value() -> None:
    p = JsonFileLprProvider()
    assert p.get_annual_lpr(date(2030, 1, 1)) == Decimal("0.0300")


def test_before_first_row_raises() -> None:
    p = JsonFileLprProvider()
    with pytest.raises(ValueError, match="早于表中首期"):
        p.get_annual_lpr(date(2019, 1, 1))


def test_non_1y_tenor_raises() -> None:
    p = JsonFileLprProvider()
    with pytest.raises(NotImplementedError):
        p.get_annual_lpr(date(2024, 1, 1), tenor="5Y")


def test_load_custom_path(tmp_path: Path) -> None:
    f = tmp_path / "lpr.json"
    f.write_text(
        '{"unit":"annual_rate","currency":"CNY","description":"x","data":['
        '{"date":"2022-01-01","value":0.01},{"date":"2022-06-01","value":0.02}]}',
        encoding="utf-8",
    )
    p = JsonFileLprProvider(path=f)
    assert p.get_annual_lpr(date(2022, 3, 1)) == Decimal("0.01")
    assert p.get_annual_lpr(date(2022, 6, 1)) == Decimal("0.02")
