"""Task policy: soft downgrade, hard halt, depth ceiling, repeat ceiling."""

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from killswitch.money import D
from killswitch.paths import POLICY_PATH


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    hard_budget_usd: Decimal
    soft_budget_usd: Decimal
    max_loop_depth: int
    max_identical_tool_repeats: int
    planning_completion_tokens: int
    local_tier: str
    tiers: list[str]

    @field_validator("hard_budget_usd", "soft_budget_usd", mode="before")
    @classmethod
    def as_decimal(cls, value: object) -> Decimal:
        return D(value)

    @model_validator(mode="after")
    def check(self) -> "Policy":
        if self.hard_budget_usd <= 0:
            raise ValueError("hard budget must be positive")
        if self.soft_budget_usd < 0 or self.soft_budget_usd > self.hard_budget_usd:
            raise ValueError("soft budget must sit between 0 and the hard budget")
        if self.max_loop_depth < 1:
            raise ValueError("max_loop_depth must be >= 1")
        if self.max_identical_tool_repeats < 2:
            raise ValueError("repeat limit must be at least 2")
        if self.planning_completion_tokens < 1:
            raise ValueError("planning_completion_tokens must be >= 1")
        if self.local_tier not in self.tiers:
            raise ValueError("local_tier is not listed in tiers")
        if len(set(self.tiers)) != len(self.tiers):
            raise ValueError("tier names must be unique")
        return self


def load_policy(path: Path | None = None) -> Policy:
    raw = yaml.safe_load((path or POLICY_PATH).read_text())
    return Policy.model_validate(raw)
