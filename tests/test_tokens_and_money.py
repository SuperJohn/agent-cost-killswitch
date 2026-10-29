from decimal import Decimal

import pytest

from killswitch.money import cost_usd, money
from killswitch.tokens import (
    canonical_tool_key,
    estimate_text_tokens,
    fit_to_tokens,
    text_with_token_count,
)


@pytest.mark.parametrize("n", [0, 1, 2, 5, 64, 1000])
def test_text_token_count_is_exact(n):
    text = text_with_token_count(n, seed="widget")
    assert estimate_text_tokens(text) == n
    if n >= 5:
        assert text.startswith("synthetic ")


def test_fit_to_tokens_keeps_the_prefix():
    fitted = fit_to_tokens("Count the widgets.\n", 40, seed="job")
    assert fitted.startswith("Count the widgets.\n")
    assert estimate_text_tokens(fitted) == 40


def test_fit_rejects_a_prefix_that_is_already_too_long():
    with pytest.raises(ValueError):
        fit_to_tokens("abcdef", 1, seed="x")


def test_canonical_key_ignores_argument_order():
    left = canonical_tool_key("search_inventory", {"b": 1, "a": 2})
    right = canonical_tool_key("search_inventory", {"a": 2, "b": 1})
    assert left == right == 'search_inventory:{"a":2,"b":1}'


def test_money_half_up_and_rates():
    assert money(Decimal("0.5")) == "0.500000"
    assert money(Decimal("0.0000005")) == "0.000001"
    assert cost_usd(1, 0, Decimal("1"), Decimal("0")) == Decimal("0.000001")
    # 1 token at $0.50 / 1M is half a micro-dollar, which rounds half up.
    assert cost_usd(1, 0, Decimal("0.5"), Decimal("0")) == Decimal("0.000001")
    assert cost_usd(8000, 0, Decimal("15"), Decimal("60")) == Decimal("0.120000")
