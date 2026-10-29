"""Pydantic models for scenarios, ledgers, and replay snapshots."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from killswitch.money import D


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    name: str | None = None


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str
    model_id: str
    messages: list[Message]
    tools: list[dict[str, Any]] = Field(default_factory=list)


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int
    completion_tokens: int
    provider_model: str


class ScriptStep(BaseModel):
    """One scripted model response for the mock provider."""

    model_config = ConfigDict(extra="forbid")

    content: str = ""
    content_tokens: int | None = None
    content_seed: str = "completion"
    tool_calls: list[ToolCall] = Field(default_factory=list)
    outage: bool = False
    outage_message: str = "example frontier provider returned HTTP 503"


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str
    instruction: str
    user_token_target: int | None = None
    steps: list[ScriptStep]
    tool_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    synthetic: Literal[True]
    note: str
    scenarios: list[Scenario]

    @field_validator("scenarios")
    @classmethod
    def unique_ids(cls, scenarios: list[Scenario]) -> list[Scenario]:
        ids = [s.id for s in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario ids must be unique")
        return scenarios


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    parameters: dict[str, Any]
    result: dict[str, Any] | None = None
    result_mode: Literal["json", "token_target"] = "json"
    default_token_target: int = 64


class ToolCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic: Literal[True]
    note: str
    tools: dict[str, ToolSpec]


class TierPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str
    model_id: str
    display_name: str
    provider: Literal["mock", "ollama"]
    ollama_model: str | None = None
    input_per_million_usd: Any
    output_per_million_usd: Any
    blurb: str

    @field_validator("input_per_million_usd", "output_per_million_usd", mode="before")
    @classmethod
    def as_decimal(cls, value: object):
        return D(value)


class LedgerRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth: int
    tier: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: str
    cumulative_usd: str
    projected_before_usd: str
    tool_calls: list[str]
    decision: str


class TierView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str
    display_name: str
    model_id: str
    input_per_million_usd: str
    output_per_million_usd: str
    blurb: str
    state: Literal["active", "stood_down", "idle", "failed"]


class Snapshot(BaseModel):
    """One frame of a recorded run. The static site replays these in order."""

    model_config = ConfigDict(extra="forbid")

    index: int
    kind: Literal["start", "turn", "downgrade", "tool", "outage", "fallback", "halt", "complete"]
    kicker: str
    title: str
    detail: str
    status: Literal["running", "completed", "halted"]
    depth: int
    max_depth: int
    tier: str
    spent_usd: str
    projected_usd: str
    soft_budget_usd: str
    hard_budget_usd: str
    prompt_tokens_next: int
    completion_tokens_est: int
    repeat_limit: int
    repeat_count: int
    repeat_label: str | None
    halt_code: str | None = None
    halt_message: str | None = None
    overshoot: bool = False
    final_text: str | None = None
    tiers: list[TierView]
    rows: list[LedgerRow]


class RunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str
    instruction: str
    synthetic: Literal[True] = True
    price_label: str
    price_disclaimer: str
    generated_at: str
    status: Literal["completed", "halted"]
    halt_code: str | None
    halt_message: str | None
    overshoot: bool
    depth: int
    final_tier: str
    spent_usd: str
    projected_usd: str
    soft_budget_usd: str
    hard_budget_usd: str
    max_loop_depth: int
    max_identical_tool_repeats: int
    prompt_tokens: int
    completion_tokens: int
    model_calls: int
    tool_executions: int
    final_text: str | None
    snapshots: list[Snapshot]
    rows: list[LedgerRow]
