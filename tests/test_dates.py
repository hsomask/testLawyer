from datetime import date

import pytest

from legal_calc.common.dates import days_inclusive, split_segments


def test_days_inclusive_same_day() -> None:
    d = date(2024, 1, 1)
    assert days_inclusive(d, d) == 1


def test_days_inclusive_span() -> None:
    assert days_inclusive(date(2024, 1, 1), date(2024, 1, 3)) == 3


def test_days_inclusive_rejects_inverted() -> None:
    with pytest.raises(ValueError):
        days_inclusive(date(2024, 1, 5), date(2024, 1, 1))


def test_split_segments_no_boundary() -> None:
    s, e = date(2024, 1, 1), date(2024, 1, 31)
    assert split_segments(s, e, []) == [(s, e)]


def test_split_segments_one_boundary_new_segment() -> None:
    s, e = date(2020, 1, 1), date(2020, 12, 31)
    b = date(2020, 8, 20)
    segs = split_segments(s, e, [b], boundary_starts_new_segment=True)
    assert segs == [(s, date(2020, 8, 19)), (b, e)]


def test_split_segments_boundary_old_segment() -> None:
    s, e = date(2020, 1, 1), date(2020, 12, 31)
    b = date(2020, 8, 20)
    segs = split_segments(s, e, [b], boundary_starts_new_segment=False)
    assert segs == [(s, b), (date(2020, 8, 21), e)]


def test_split_segments_boundary_outside_range_ignored() -> None:
    s, e = date(2024, 1, 1), date(2024, 1, 10)
    segs = split_segments(s, e, [date(2020, 8, 20)])
    assert segs == [(s, e)]
