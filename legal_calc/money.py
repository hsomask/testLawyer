"""金额舍入：四舍五入到分，先舍入再求和（业务确认 §10）。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANT = Decimal("0.01")


def quantize_money(v: Decimal) -> Decimal:
    return v.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
