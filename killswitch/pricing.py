"""Load the price table. Figures are configuration, never a live quote."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from killswitch.models import TierPrice
from killswitch.money import D, cost_usd
from killswitch.paths import PRICES_PATH


class PriceTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    disclaimer: str
    tiers: list[TierPrice]

    @field_validator("label")
    @classmethod
    def label_is_not_a_claim(cls, value: str) -> str:
        if value not in {"example", "config"}:
            raise ValueError(
                "price table label must be 'example' or 'config' so the figures "
                "cannot be read as a provider invoice"
            )
        return value

    @field_validator("disclaimer")
    @classmethod
    def disclaimer_says_so(cls, value: str) -> str:
        text = " ".join(value.split())
        if len(text) < 40:
            raise ValueError("price disclaimer is too short")
        lowered = text.lower()
        if "example" not in lowered and "config" not in lowered:
            raise ValueError("disclaimer must call the figures example or config values")
        return text

    def tier(self, name: str) -> TierPrice:
        for item in self.tiers:
            if item.tier == name:
                return item
        known = ", ".join(item.tier for item in self.tiers)
        raise KeyError(f"unknown tier {name!r} (known: {known})")


def load_prices(path: Path | None = None) -> PriceTable:
    raw = yaml.safe_load((path or PRICES_PATH).read_text())
    return PriceTable.model_validate(raw)


def assert_ladder(tier_names: list[str], prices: PriceTable) -> None:
    """Tiers are listed expensive to cheap on a fixed 1k/1k token basket."""
    baskets = []
    for name in tier_names:
        item = prices.tier(name)
        baskets.append(
            (
                name,
                cost_usd(1000, 1000, D(item.input_per_million_usd), D(item.output_per_million_usd)),
            )
        )
    for (left, left_cost), (right, right_cost) in zip(baskets, baskets[1:]):
        if left_cost < right_cost:
            raise ValueError(
                f"tier {right} costs more than {left} on a 1000/1000 token basket; "
                "list tiers from expensive to cheap"
            )
