"""Small shared helpers: ids, time, money."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite does not keep tz info; everything stored is UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_cents(value: str | float | int | Decimal) -> int:
    """Parse a money amount into integer cents. Accepts '$1,234.56', '(12.00)', '-5'."""
    if isinstance(value, int):
        return value * 100
    s = str(value).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if s.startswith("-"):
        negative, s = (not negative), s[1:]
    if s.startswith("+"):
        s = s[1:]
    if not s:
        raise ValueError("empty amount")
    d = Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cents = int(d * 100)
    return -cents if negative else cents


def cents_to_str(cents: int | None) -> str:
    if cents is None:
        return "n/a"
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}${c // 100:,}.{c % 100:02d}"


MICROS = 1_000_000


def usd_to_micros(usd: float | Decimal) -> int:
    return int((Decimal(str(usd)) * MICROS).to_integral_value(rounding=ROUND_HALF_UP))


def micros_to_usd(micros: int | None) -> float:
    return round((micros or 0) / MICROS, 6)
