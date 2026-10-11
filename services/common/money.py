"""Money on the wire and in words (docs/PLATFORM.md gap 9).

Amounts are `Decimal` everywhere in Python and decimal *strings* on the wire
(`"12.50"`), so no service or browser ever rounds a price through a float.
Every amount has two decimal places; currencies with other minor units are
not supported yet.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal(100)

# ISO 4217 codes a tenant may pick. All are shown with two decimal places.
CURRENCIES: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$",
    "AUD": "A$",
    "NZD": "NZ$",
    "MXN": "MX$",
    "BRL": "R$",
    "ARS": "AR$",
    "CLP": "CLP ",
    "COP": "COL$",
    "PEN": "S/",
    "BOB": "Bs ",
    "CHF": "CHF ",
    "SEK": "SEK ",
    "NOK": "NOK ",
    "DKK": "DKK ",
    "PLN": "zł ",
    "ZAR": "R ",
    "INR": "₹",
    "SGD": "S$",
    "HKD": "HK$",
    "AED": "AED ",
}
DEFAULT_CURRENCY = "USD"
_CODE = re.compile(r"^[A-Z]{3}$")


def dec(value: Any) -> Decimal:
    """Anything amount-like (Decimal, int, a decimal string; never a float on purpose) -> Decimal to the cent."""
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        msg = f"Not an amount: {value!r}"
        raise ValueError(msg) from exc


def wire(value: Any) -> str:
    """The wire shape of an amount: a decimal string with two places."""
    return str(dec(value))


def is_currency(code: str) -> bool:
    return bool(_CODE.match(code)) and code in CURRENCIES


def label(amount: Any, currency: str = DEFAULT_CURRENCY) -> str:
    """`$12.50`, `€12.50`, `CHF 12.50`: for audit lines and alerts, not for the browser (it formats its own)."""
    value = dec(amount)
    symbol = CURRENCIES.get(currency, f"{currency} ")
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"


def tax_split(gross: Decimal, rate: Decimal, *, inclusive: bool) -> tuple[Decimal, Decimal, Decimal]:
    """(subtotal, tax, total) for amounts that already include tax (`inclusive`) or have it added on top."""
    gross, rate = dec(gross), Decimal(str(rate))
    if inclusive:
        net = (gross * HUNDRED / (HUNDRED + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
        return net, gross - net, gross
    tax = (gross * rate / HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)
    return gross, tax, gross + tax
