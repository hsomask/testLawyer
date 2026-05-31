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
    # 只含 3、4 月义务，不应出现早于 3/27 的区间
    assert all(ln.period_start >= date(2025, 3, 27) for ln in late)
    # 至少应有 3/27 起的一段和 4/27 起的一段
    starts = {ln.period_start for ln in late}
    assert date(2025, 3, 27) in starts
    assert date(2025, 4, 27) in starts


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
    assert any("房屋占用费小计: 0" in m for m in out.messages)


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


def test_demo_property_and_utility_late_same_request() -> None:
    """额外费用：物业费/水电与租金一次试算，固定 LPR 规则。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    req = RentalRequest(
        monthly_rent=Decimal("3000.00"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        rent_due_day_of_month=26,
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=None,
        filing_date=date(2025, 4, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="property", name="物业费 2025-01", amount=Decimal("400"), due_date=date(2025, 1, 26)
            ),
            RentalExtraFeeItem(
                category="utility", name="水电费 2025-01", amount=Decimal("150"), due_date=date(2025, 1, 26)
            ),
        ],
    )
    out = calculate_rental(req)
    cats = [ln.fee_category for ln in out.lines]
    assert cats.count("租金滞纳金") >= 1
    assert cats.count("物业费滞纳金") >= 1
    assert cats.count("水电费滞纳金") >= 1
    assert "租金滞纳金小计" in "".join(out.messages)
    assert "物业费滞纳金小计" in "".join(out.messages)


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


# ════════════════════════════════════════════════════════════════════
# PRD §七 新增测试：欠租本金 / 占用费自然月 / 滞纳金固定 LPR / 额外费用
# ════════════════════════════════════════════════════════════════════


def _rental(
    monthly_rent: Decimal,
    filing_date: date,
    *,
    arrears_period_start: date | None = None,
    arrears_period_end: date | None = None,
    rent_due_day_of_month: int = 26,
    contract_termination_date: date | None = None,
    actual_vacate_date: date | None = None,
    paid_rent_amount: Decimal = Decimal("0"),
    extra_fee_items: list | None = None,
    lease_start: date | None = None,
    lease_end: date | None = None,
):
    """快捷构造 RentalRequest 并调用 calculate_rental。"""
    return calculate_rental(
        RentalRequest(
            monthly_rent=monthly_rent,
            arrears_period_start=arrears_period_start or date(2025, 1, 1),
            arrears_period_end=arrears_period_end or date(2025, 1, 31),
            rent_due_day_of_month=rent_due_day_of_month,
            contract_termination_date=contract_termination_date or date(2025, 3, 1),
            actual_vacate_date=actual_vacate_date,
            filing_date=filing_date,
            paid_rent_amount=paid_rent_amount,
            extra_fee_items=extra_fee_items or [],
            lease_start=lease_start,
            lease_end=lease_end,
        )
    )


# ── 欠租本金 ──────────────────────────────────────────────────────


def test_arrears_principal_full_month() -> None:
    """完整月：应收租金 = 月租金。"""
    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        filing_date=date(2025, 4, 1),
    )
    rs = out.rental_summary
    assert rs is not None
    assert rs.rent_receivable_subtotal == Decimal("3000.00")
    assert rs.arrears_principal_subtotal == Decimal("3000.00")


def test_arrears_principal_partial_month() -> None:
    """不完整月：应收租金按月租/当月天数×实际天数折算。"""
    out = _rental(
        Decimal("3100"),
        arrears_period_start=date(2025, 1, 10),
        arrears_period_end=date(2025, 1, 20),
        filing_date=date(2025, 4, 1),
    )
    rs = out.rental_summary
    assert rs is not None
    # 1月31天，10日到20日共11天
    assert rs.rent_receivable_subtotal == quantize_money(Decimal("3100") * Decimal("11") / Decimal("31"))


def test_arrears_principal_cross_month() -> None:
    """跨月欠租：按自然月分别折算后加总。"""
    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 20),
        arrears_period_end=date(2025, 2, 10),
        filing_date=date(2025, 4, 1),
    )
    rs = out.rental_summary
    assert rs is not None
    # 1月: 3000/31×12, 2月: 3000/28×10
    jan = quantize_money(Decimal("3000") * Decimal("12") / Decimal("31"))
    feb = quantize_money(Decimal("3000") * Decimal("10") / Decimal("28"))
    assert rs.rent_receivable_subtotal == jan + feb
    # 确保生成了两行欠租本金明细
    arrears_lines = [ln for ln in out.lines if ln.fee_category == "欠租本金"]
    assert len(arrears_lines) == 2


def test_arrears_principal_with_paid_rent() -> None:
    """paid_rent_amount 扣减欠租本金小计。"""
    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        paid_rent_amount=Decimal("1000"),
        filing_date=date(2025, 4, 1),
    )
    rs = out.rental_summary
    assert rs is not None
    assert rs.rent_receivable_subtotal == Decimal("3000.00")
    assert rs.paid_rent_amount == Decimal("1000.00")
    assert rs.arrears_principal_subtotal == Decimal("2000.00")


def test_paid_rent_does_not_affect_late_fee() -> None:
    """paid_rent_amount 不影响租金滞纳金基数。"""
    out_no_pay = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        filing_date=date(2025, 4, 1),
    )
    out_with_pay = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        paid_rent_amount=Decimal("2000"),
        filing_date=date(2025, 4, 1),
    )
    assert out_no_pay.rental_summary is not None
    assert out_with_pay.rental_summary is not None
    # 滞纳金不受影响
    assert out_with_pay.rental_summary.rent_late_fee_subtotal == out_no_pay.rental_summary.rent_late_fee_subtotal


# ── 占用费（自然月拆分）───────────────────────────────────────────


def test_occupancy_single_month() -> None:
    """占用费单月：按当月自然日天数折算。"""
    out = _rental(
        Decimal("3000"),
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=date(2025, 3, 15),
        filing_date=date(2025, 4, 1),
    )
    occ = [ln for ln in out.lines if ln.fee_category == "房屋占用费"]
    assert len(occ) == 1
    # 3月31天，3/2~3/15 = 14天
    assert occ[0].day_count == 14
    expected = quantize_money(Decimal("3000") / Decimal("31") * Decimal("14") * Decimal("2"))
    assert occ[0].amount == expected


def test_occupancy_cross_month() -> None:
    """占用费跨月：按自然月分别计算后加总。"""
    out = _rental(
        Decimal("3000"),
        contract_termination_date=date(2025, 2, 20),
        actual_vacate_date=date(2025, 3, 10),
        filing_date=date(2025, 4, 1),
    )
    occ = [ln for ln in out.lines if ln.fee_category == "房屋占用费"]
    assert len(occ) == 2
    # 2月: 2/21~2/28 = 8天 (28天月)
    # 3月: 3/1~3/10 = 10天 (31天月)
    assert occ[0].day_count == 8
    assert occ[1].day_count == 10
    feb_amt = quantize_money(Decimal("3000") / Decimal("28") * Decimal("8") * Decimal("2"))
    mar_amt = quantize_money(Decimal("3000") / Decimal("31") * Decimal("10") * Decimal("2"))
    assert occ[0].amount == feb_amt
    assert occ[1].amount == mar_amt


def test_occupancy_no_longer_uses_30_day_formula() -> None:
    """占用费不再使用 /30 公式，改为自然月天数。"""
    out = _rental(
        Decimal("3000"),
        contract_termination_date=date(2025, 3, 1),
        actual_vacate_date=date(2025, 3, 16),
        filing_date=date(2025, 4, 1),
    )
    occ = [ln for ln in out.lines if ln.fee_category == "房屋占用费"]
    assert len(occ) == 1
    # 旧公式: 3000/30*15*2 = 3000
    # 新公式: 3000/31*15*2 ≈ 2903.23
    assert occ[0].day_count == 15
    assert occ[0].amount != Decimal("3000.00")  # 不等于旧公式结果
    assert "31" in occ[0].stage_description  # 使用31天


# ── 租金滞纳金（固定 LPR，不分段）────────────────────────────────


def test_rent_late_fee_no_lpr_segmentation() -> None:
    """同 LPR 数值不拆分：滞纳期间跨多个 LPR 发布日但数值相同，合并为一行。"""
    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2024, 10, 1),
        arrears_period_end=date(2025, 3, 31),
        lease_start=date(2024, 10, 1),
        lease_end=date(2025, 3, 31),
        filing_date=date(2025, 4, 1),
    )
    rent_lines = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    # 10,11,12,1,2,3 = 6 个月，LPR=0.031 全程不变，每月一行
    assert len(rent_lines) == 6
    for ln in rent_lines:
        assert "年化小数" in ln.rate_standard


def test_rent_late_fee_fixed_lpr_across_months() -> None:
    """LPR 变化时拆分，但同 LPR 区间合并：Aug/Sep 跨 LPR 变动点各拆 2 行。"""
    out = _rental(
        Decimal("5000"),
        arrears_period_start=date(2024, 8, 1),
        arrears_period_end=date(2025, 3, 31),
        lease_start=date(2024, 8, 1),
        lease_end=date(2025, 3, 31),
        filing_date=date(2025, 4, 1),
    )
    rent = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    # 8个月：Aug/Sep 各 2（LPR 变动），Oct-Mar 各 1 = 10
    assert len(rent) >= 8
    for ln in rent:
        assert "年化小数" in ln.rate_standard


# ── 额外费用滞纳金 ────────────────────────────────────────────────


def test_extra_fee_utility() -> None:
    """水电费额外费用：单独指定 due_date，固定 LPR。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = _rental(
        Decimal("3000"),
        filing_date=date(2025, 6, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="utility", name="电费 2025-03", amount=Decimal("500"), due_date=date(2025, 3, 15)
            )
        ],
    )
    util_lines = [ln for ln in out.lines if ln.fee_category == "水电费滞纳金"]
    assert len(util_lines) == 1
    assert util_lines[0].principal_base == Decimal("500.00")
    assert out.rental_summary is not None
    assert out.rental_summary.utility_late_fee_subtotal == util_lines[0].amount


def test_extra_fee_property() -> None:
    """物业费额外费用。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = _rental(
        Decimal("3000"),
        filing_date=date(2025, 6, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="property", name="物业费 2025-Q1", amount=Decimal("1200"), due_date=date(2025, 1, 15)
            )
        ],
    )
    prop_lines = [ln for ln in out.lines if ln.fee_category == "物业费滞纳金"]
    assert len(prop_lines) == 1
    assert out.rental_summary is not None
    assert out.rental_summary.property_late_fee_subtotal == prop_lines[0].amount


def test_extra_fee_other() -> None:
    """其他费用额外费用。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = _rental(
        Decimal("3000"),
        filing_date=date(2025, 6, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="other", name="维修费", amount=Decimal("800"), due_date=date(2025, 2, 1)
            ),
            RentalExtraFeeItem(
                category="other", name="清洁费", amount=Decimal("300"), due_date=date(2025, 3, 1)
            ),
        ],
    )
    other_lines = [ln for ln in out.lines if ln.fee_category == "其他费用滞纳金"]
    assert len(other_lines) == 2
    assert out.rental_summary is not None
    assert out.rental_summary.other_late_fee_subtotal == other_lines[0].amount + other_lines[1].amount


def test_extra_fee_different_due_dates() -> None:
    """不同 due_date 产生不同违约开始日和固定 LPR。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = _rental(
        Decimal("3000"),
        filing_date=date(2025, 6, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="utility", name="电费1月", amount=Decimal("500"), due_date=date(2025, 1, 15)
            ),
            RentalExtraFeeItem(
                category="utility", name="电费3月", amount=Decimal("500"), due_date=date(2025, 3, 15)
            ),
        ],
    )
    util_lines = [ln for ln in out.lines if ln.fee_category == "水电费滞纳金"]
    assert len(util_lines) == 2
    # 两条的滞纳天数不同（违约开始日不同）
    assert util_lines[0].day_count != util_lines[1].day_count


# ── 汇总一致性 ────────────────────────────────────────────────────


def test_rental_summary_structure() -> None:
    """rental_summary 包含所有 9 个字段。"""
    out = _rental(Decimal("3000"), filing_date=date(2025, 4, 1))
    rs = out.rental_summary
    assert rs is not None
    assert rs.rent_receivable_subtotal is not None
    assert rs.paid_rent_amount is not None
    assert rs.arrears_principal_subtotal is not None
    assert rs.rent_late_fee_subtotal is not None
    assert rs.utility_late_fee_subtotal is not None
    assert rs.property_late_fee_subtotal is not None
    assert rs.other_late_fee_subtotal is not None
    assert rs.occupancy_fee_subtotal is not None
    assert rs.grand_total is not None


def test_grand_total_equals_sum_of_subtotals() -> None:
    """grand_total 等于各小计之和。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 3, 31),
        lease_start=date(2025, 1, 1),
        lease_end=date(2025, 3, 31),
        contract_termination_date=date(2025, 4, 1),
        actual_vacate_date=date(2025, 4, 15),
        paid_rent_amount=Decimal("1000"),
        filing_date=date(2025, 5, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="utility", name="电费", amount=Decimal("500"), due_date=date(2025, 2, 15)
            ),
            RentalExtraFeeItem(
                category="other", name="维修", amount=Decimal("300"), due_date=date(2025, 3, 1)
            ),
        ],
    )
    rs = out.rental_summary
    assert rs is not None
    expected = (
        rs.arrears_principal_subtotal
        + rs.rent_late_fee_subtotal
        + rs.utility_late_fee_subtotal
        + rs.property_late_fee_subtotal
        + rs.other_late_fee_subtotal
        + rs.occupancy_fee_subtotal
    )
    assert rs.grand_total == expected, f"grand_total={rs.grand_total} != {expected}"


# ── paid_rent 超过应收租金 ────────────────────────────────────────


def test_paid_rent_exceeds_receivable_arrears_principal_zero() -> None:
    """paid_rent_amount 超过应收租金时，欠租本金小计按 0 处理。"""
    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 15),  # 约半个月
        paid_rent_amount=Decimal("5000"),  # 超过应收
        filing_date=date(2025, 4, 1),
    )
    rs = out.rental_summary
    assert rs is not None
    assert rs.arrears_principal_subtotal == Decimal("0.00")
    assert any("按 0 处理" in m for m in out.messages)


def test_grand_total_uses_deducted_arrears_principal() -> None:
    """有 paid_rent_amount 时，grand_total 使用扣减后的欠租本金。"""
    out = _rental(
        Decimal("3000"),
        arrears_period_start=date(2025, 1, 1),
        arrears_period_end=date(2025, 1, 31),
        paid_rent_amount=Decimal("1000"),
        contract_termination_date=date(2025, 2, 1),
        actual_vacate_date=date(2025, 2, 1),
        filing_date=date(2025, 3, 1),
    )
    rs = out.rental_summary
    assert rs is not None
    # 欠租本金 = 3000 - 1000 = 2000
    assert rs.arrears_principal_subtotal == Decimal("2000.00")
    # line_amount_sum 不含扣减（只含明细行金额）
    line_sum = out.line_amount_sum()
    # grand_total 应 = line_sum - paid_rent_amount（因为欠租本金扣减了 1000）
    assert rs.grand_total == line_sum - Decimal("1000")


# ── 额外费用 due_date 跳过 ────────────────────────────────────────


def test_extra_fee_due_date_after_filing_skipped() -> None:
    """extra_fee_items 的 due_date 晚于或等于 filing_date 时跳过并提示。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = _rental(
        Decimal("3000"),
        filing_date=date(2025, 4, 1),
        extra_fee_items=[
            RentalExtraFeeItem(
                category="utility", name="到期后电费", amount=Decimal("500"),
                due_date=date(2025, 4, 1),  # 等于起诉日
            ),
            RentalExtraFeeItem(
                category="other", name="到期后维修", amount=Decimal("300"),
                due_date=date(2025, 5, 1),  # 晚于起诉日
            ),
        ],
    )
    # 两条都跳过
    assert out.rental_summary.utility_late_fee_subtotal == Decimal("0")
    assert out.rental_summary.other_late_fee_subtotal == Decimal("0")
    assert any("跳过" in m for m in out.messages)


# ── LPR 分段合并测试 ──────────────────────────────────────────────


class _FakeLpr:
    """Fake LPR provider：2/20 前 0.031，之后 0.030。"""

    def get_annual_lpr(self, as_of: date) -> Decimal:
        if as_of < date(2025, 2, 20):
            return Decimal("0.031")
        return Decimal("0.030")

    def publication_dates_in_open_interval(self, lo: date, hi_excl: date) -> list[date]:
        cut = date(2025, 2, 20)
        if lo < cut < hi_excl:
            return [cut]
        return []


def test_rent_late_fee_same_lpr_merged_to_one_line() -> None:
    """同 LPR 且仅一个月租金义务，应合并为一条租金滞纳金。"""
    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 1, 31),
            rent_due_day_of_month=20,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            lease_start=date(2025, 1, 1),
            lease_end=date(2025, 1, 31),
        )
    )
    rent_lines = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert len(rent_lines) == 1, f"expected 1, got {len(rent_lines)}"
    assert rent_lines[0].period_start == date(2025, 1, 21)
    assert rent_lines[0].period_end == date(2025, 4, 1)
    assert rent_lines[0].day_count == 71
    expected = quantize_money(Decimal("3000") * Decimal("0.031") * Decimal("71") / Decimal("365"))
    assert rent_lines[0].amount == expected, f"{rent_lines[0].amount} != {expected}"


def test_rent_late_fee_lpr_change_splits() -> None:
    """仅一个月租金义务 + LPR 变化：拆为 2 段，累计基数均为 3000。"""
    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 1, 31),
            rent_due_day_of_month=20,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            lease_start=date(2025, 1, 1),
            lease_end=date(2025, 1, 31),
        ),
        lpr=_FakeLpr(),
    )
    rent_lines = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert len(rent_lines) == 2, f"expected 2, got {len(rent_lines)}"

    assert rent_lines[0].period_start == date(2025, 1, 21)
    assert rent_lines[0].period_end == date(2025, 2, 19)
    assert rent_lines[0].day_count == 30
    assert "0.031" in rent_lines[0].rate_standard

    assert rent_lines[1].period_start == date(2025, 2, 20)
    assert rent_lines[1].period_end == date(2025, 4, 1)
    assert rent_lines[1].day_count == 41
    assert "0.030" in rent_lines[1].rate_standard


def test_extra_fee_same_lpr_merged_to_one_line() -> None:
    """一条额外费用、同 LPR 数值，应合并为一条明细。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 1, 31),
            rent_due_day_of_month=20,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            extra_fee_items=[
                RentalExtraFeeItem(
                    category="utility", name="电费 2025-01", amount=Decimal("500"),
                    due_date=date(2025, 1, 20),
                ),
            ],
        )
    )
    util_lines = [ln for ln in out.lines if ln.fee_category == "水电费滞纳金"]
    assert len(util_lines) == 1, f"expected 1, got {len(util_lines)}"
    assert util_lines[0].period_start == date(2025, 1, 21)
    assert util_lines[0].period_end == date(2025, 4, 1)
    assert util_lines[0].day_count == 71
    expected = quantize_money(Decimal("500") * Decimal("0.031") * Decimal("71") / Decimal("365"))
    assert util_lines[0].amount == expected, f"{util_lines[0].amount} != {expected}"


def test_extra_fee_lpr_change_splits() -> None:
    """额外费用 LPR 变化时拆分两条。"""
    from legal_calc.rental.models import RentalExtraFeeItem

    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 1, 31),
            rent_due_day_of_month=20,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            extra_fee_items=[
                RentalExtraFeeItem(
                    category="property", name="物业费 Q1", amount=Decimal("1200"),
                    due_date=date(2025, 1, 20),
                ),
            ],
        ),
        lpr=_FakeLpr(),
    )
    prop_lines = [ln for ln in out.lines if ln.fee_category == "物业费滞纳金"]
    assert len(prop_lines) == 2, f"expected 2, got {len(prop_lines)}"

    assert prop_lines[0].period_start == date(2025, 1, 21)
    assert prop_lines[0].period_end == date(2025, 2, 19)
    assert "0.031" in prop_lines[0].rate_standard

    assert prop_lines[1].period_start == date(2025, 2, 20)
    assert prop_lines[1].period_end == date(2025, 4, 1)
    assert "0.030" in prop_lines[1].rate_standard


# ── M2 累计基数时间轴测试 ─────────────────────────────────────────


def test_rent_late_fee_uses_accumulated_base_timeline() -> None:
    """租金滞纳金按累计基数时间轴：3000→6000→9000。"""
    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 3, 31),
            rent_due_day_of_month=26,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            lease_start=date(2025, 1, 1),
            lease_end=date(2025, 3, 31),
        )
    )
    rent_lines = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert len(rent_lines) == 3, f"expected 3, got {len(rent_lines)}"

    # 第一段：1/27~2/26，基数 3000
    assert rent_lines[0].period_start == date(2025, 1, 27)
    assert rent_lines[0].period_end == date(2025, 2, 26)
    assert rent_lines[0].principal_base == Decimal("3000.00")
    assert rent_lines[0].day_count == 31
    e0 = quantize_money(Decimal("3000") * Decimal("0.031") * Decimal("31") / Decimal("365"))
    assert rent_lines[0].amount == e0

    # 第二段：2/27~3/26，基数 6000
    assert rent_lines[1].period_start == date(2025, 2, 27)
    assert rent_lines[1].period_end == date(2025, 3, 26)
    assert rent_lines[1].principal_base == Decimal("6000.00")
    assert rent_lines[1].day_count == 28
    e1 = quantize_money(Decimal("6000") * Decimal("0.031") * Decimal("28") / Decimal("365"))
    assert rent_lines[1].amount == e1

    # 第三段：3/27~4/1，基数 9000
    assert rent_lines[2].period_start == date(2025, 3, 27)
    assert rent_lines[2].period_end == date(2025, 4, 1)
    assert rent_lines[2].principal_base == Decimal("9000.00")
    assert rent_lines[2].day_count == 6
    e2 = quantize_money(Decimal("9000") * Decimal("0.031") * Decimal("6") / Decimal("365"))
    assert rent_lines[2].amount == e2


def test_rent_late_fee_lines_do_not_overlap() -> None:
    """租金滞纳金明细不允许重叠区间。"""
    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 3, 31),
            rent_due_day_of_month=26,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            lease_start=date(2025, 1, 1),
            lease_end=date(2025, 3, 31),
        )
    )
    rent_lines = sorted(
        [ln for ln in out.lines if ln.fee_category == "租金滞纳金"],
        key=lambda ln: ln.period_start,
    )
    assert len(rent_lines) >= 2
    for i in range(len(rent_lines) - 1):
        assert rent_lines[i].period_end < rent_lines[i + 1].period_start, (
            f"重叠: [{rent_lines[i].period_start}, {rent_lines[i].period_end}]"
            f" vs [{rent_lines[i + 1].period_start}, {rent_lines[i + 1].period_end}]"
        )


def test_rent_late_fee_lpr_and_base_both_change() -> None:
    """LPR 和累计基数同时变化：应切 4 段。"""
    out = calculate_rental(
        RentalRequest(
            monthly_rent=Decimal("3000"),
            arrears_period_start=date(2025, 1, 1),
            arrears_period_end=date(2025, 3, 31),
            rent_due_day_of_month=26,
            contract_termination_date=date(2025, 4, 1),
            actual_vacate_date=None,
            filing_date=date(2025, 4, 1),
            lease_start=date(2025, 1, 1),
            lease_end=date(2025, 3, 31),
        ),
        lpr=_FakeLpr(),
    )
    rent_lines = [ln for ln in out.lines if ln.fee_category == "租金滞纳金"]
    assert len(rent_lines) == 4, f"expected 4, got {len(rent_lines)}"

    # 1/27~2/19，基数 3000，LPR 0.031
    assert rent_lines[0].period_start == date(2025, 1, 27)
    assert rent_lines[0].period_end == date(2025, 2, 19)
    assert rent_lines[0].principal_base == Decimal("3000.00")
    assert "0.031" in rent_lines[0].rate_standard

    # 2/20~2/26，基数 3000，LPR 0.030
    assert rent_lines[1].period_start == date(2025, 2, 20)
    assert rent_lines[1].period_end == date(2025, 2, 26)
    assert rent_lines[1].principal_base == Decimal("3000.00")
    assert "0.030" in rent_lines[1].rate_standard

    # 2/27~3/26，基数 6000，LPR 0.030
    assert rent_lines[2].period_start == date(2025, 2, 27)
    assert rent_lines[2].period_end == date(2025, 3, 26)
    assert rent_lines[2].principal_base == Decimal("6000.00")
    assert "0.030" in rent_lines[2].rate_standard

    # 3/27~4/1，基数 9000，LPR 0.030
    assert rent_lines[3].period_start == date(2025, 3, 27)
    assert rent_lines[3].period_end == date(2025, 4, 1)
    assert rent_lines[3].principal_base == Decimal("9000.00")
    assert "0.030" in rent_lines[3].rate_standard


# ── 导入 quantize_money 供测试用 ──────────────────────────────────

from legal_calc.money import quantize_money
