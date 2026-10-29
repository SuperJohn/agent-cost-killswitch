from decimal import Decimal

import pytest
from pydantic import ValidationError

from killswitch.money import D
from killswitch.policy import Policy, load_policy
from killswitch.pricing import PriceTable, assert_ladder, load_prices


def test_shipped_price_table_is_labeled_example():
    prices = load_prices()
    assert prices.label == "example"
    assert "example" in prices.disclaimer.lower()
    assert "not a quote" in prices.disclaimer.lower()
    assert [t.tier for t in prices.tiers] == ["frontier", "mid", "local"]
    assert prices.tier("local").provider == "ollama"
    assert D(prices.tier("local").input_per_million_usd) == 0
    assert "example" in prices.tier("frontier").model_id


def test_shipped_policy_defaults():
    policy = load_policy()
    assert policy.hard_budget_usd == Decimal("0.50")
    assert policy.soft_budget_usd == Decimal("0.10")
    assert policy.max_loop_depth == 6
    assert policy.max_identical_tool_repeats == 3
    assert policy.tiers == ["frontier", "mid", "local"]
    assert_ladder(policy.tiers, load_prices())


def test_soft_budget_cannot_exceed_hard():
    with pytest.raises(ValidationError):
        Policy(
            hard_budget_usd="0.10",
            soft_budget_usd="0.20",
            max_loop_depth=2,
            max_identical_tool_repeats=2,
            planning_completion_tokens=8,
            local_tier="local",
            tiers=["local"],
        )


def test_unlabeled_prices_are_rejected():
    prices = load_prices()
    raw = prices.model_dump(mode="json")
    raw["label"] = "invoice"
    with pytest.raises(ValidationError):
        PriceTable.model_validate(raw)


def test_ladder_must_get_cheaper():
    prices = load_prices()
    with pytest.raises(ValueError):
        assert_ladder(["local", "frontier"], prices)
