"""Decimal money helpers.

Every figure this package emits is computed from the configured price table.
The table is labeled example or config. Nothing here is an invoice.
"""

from decimal import Decimal, ROUND_HALF_UP

MONEY = Decimal("0.000001")
MILLION = Decimal(1_000_000)


def D(value: object) -> Decimal:
    """Coerce YAML numbers and strings to Decimal without binary float residue."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"cannot read {value!r} as a decimal")
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value.strip())


def money(value: Decimal) -> str:
    """Format a dollar amount at micro-dollar resolution (half up)."""
    quantized = D(value).quantize(MONEY, rounding=ROUND_HALF_UP)
    return f"{quantized:.6f}"


def cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    input_per_million: Decimal,
    output_per_million: Decimal,
) -> Decimal:
    raw = (
        Decimal(prompt_tokens) * D(input_per_million)
        + Decimal(completion_tokens) * D(output_per_million)
    ) / MILLION
    return raw.quantize(MONEY, rounding=ROUND_HALF_UP)
