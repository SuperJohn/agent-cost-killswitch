"""The kill switch.

Control order for one task:

1. If the loop is already at max depth, halt. The call is not sent.
2. Project the next call from the prompt already in context (known) plus the
   last completion length, or the planning length before any call (unknown).
   If that projection is over the hard budget, halt. The call is not sent.
3. Call the provider. An outage jumps to the local tier and retries. If the
   local tier is the one that failed, halt.
4. Bill the call. If this response repeats a tool call up to the limit, halt
   without executing it. If actual spend is now over the hard budget, halt
   and flag the overshoot (a long completion can beat the estimate).
5. A final answer with no tool call completes the task.
6. If spend has reached the soft budget, step down exactly one tier.
7. Execute the tools, then loop. The new tool text is part of the next projection.
"""

from decimal import Decimal

from killswitch.models import (
    Completion,
    CompletionRequest,
    Dataset,
    LedgerRow,
    Message,
    RunReport,
    Scenario,
    Snapshot,
    TierView,
    ToolCall,
    ToolCatalog,
)
from killswitch.money import D, cost_usd, money
from killswitch.paths import RECORDED_AT
from killswitch.policy import Policy
from killswitch.pricing import PriceTable, assert_ladder
from killswitch.providers import MockReplayProvider, ProviderOutage, RoutingProvider, ollama_from_env
from killswitch.tokens import canonical_tool_key, estimate_messages, estimate_text_tokens, fit_to_tokens
from killswitch.tools import ToolExecutor

SYSTEM_PROMPT = (
    "You are a dispatch assistant for a synthetic facilities team. "
    "Use tools for facts. Ticket ids and SKUs in this demo are fictional. "
    "When the tools have answered, reply in one short paragraph and stop."
)


def public_text(content: str) -> str | None:
    stripped = content.strip()
    if not stripped:
        return None
    if stripped.startswith("synthetic ") and len(stripped) > 280:
        return None
    if len(stripped) > 700:
        return stripped[:700] + "…"
    return stripped


class KillSwitch:
    def __init__(
        self,
        scenario: Scenario,
        policy: Policy,
        prices: PriceTable,
        catalog: ToolCatalog,
        *,
        provider: RoutingProvider | None = None,
        allow_ollama: bool = False,
        generated_at: str = RECORDED_AT,
    ):
        assert_ladder(policy.tiers, prices)
        self.scenario = scenario
        self.policy = policy
        self.prices = prices
        self.generated_at = generated_at
        self.tools = ToolExecutor(catalog, scenario.tool_overrides)
        self._check_tools()
        if provider is None:
            mock = MockReplayProvider(scenario.steps)
            ollama = ollama_from_env(prices) if allow_ollama else None
            provider = RoutingProvider(mock, prices, ollama)
            self.mock = mock
        else:
            self.mock = getattr(provider, "mock", None)
        self.provider = provider
        self.messages: list[Message] = _initial_messages(scenario)
        self.tier_idx = 0
        self.depth = 0
        self.spent = Decimal("0")
        self.completion_est = policy.planning_completion_tokens
        self.repeats: dict[str, int] = {}
        self.failed: set[str] = set()
        self.stood_down: set[str] = set()
        self.rows: list[LedgerRow] = []
        self.snapshots: list[Snapshot] = []
        self.halt_code: str | None = None
        self.halt_message: str | None = None
        self.overshoot = False
        self.final_text: str | None = None
        self.model_calls = 0

    def _check_tools(self) -> None:
        known = set(self.tools.catalog.tools)
        for step in self.scenario.steps:
            for call in step.tool_calls:
                if call.name not in known:
                    raise ValueError(f"scenario {self.scenario.id} calls unknown tool {call.name}")

    @property
    def tier_name(self) -> str:
        return self.policy.tiers[self.tier_idx]

    def prompt_tokens(self) -> int:
        return estimate_messages(self.messages)

    def projected(self) -> Decimal:
        price = self.prices.tier(self.tier_name)
        return self.spent + cost_usd(
            self.prompt_tokens(),
            self.completion_est,
            D(price.input_per_million_usd),
            D(price.output_per_million_usd),
        )

    def tier_views(self) -> list[TierView]:
        views = []
        for name in self.policy.tiers:
            price = self.prices.tier(name)
            if name in self.failed:
                state = "failed"
            elif name == self.tier_name:
                state = "active"
            elif name in self.stood_down:
                state = "stood_down"
            else:
                state = "idle"
            views.append(
                TierView(
                    tier=name,
                    display_name=price.display_name,
                    model_id=price.model_id,
                    input_per_million_usd=money(D(price.input_per_million_usd)),
                    output_per_million_usd=money(D(price.output_per_million_usd)),
                    blurb=price.blurb,
                    state=state,  # type: ignore[arg-type]
                )
            )
        return views

    def top_repeat(self) -> tuple[int, str | None]:
        if not self.repeats:
            return 0, None
        label, count = max(self.repeats.items(), key=lambda item: item[1])
        return count, label

    def snap(
        self,
        kind: str,
        kicker: str,
        title: str,
        detail: str,
        status: str = "running",
    ) -> None:
        repeat_count, repeat_label = self.top_repeat()
        self.snapshots.append(
            Snapshot(
                index=len(self.snapshots),
                kind=kind,  # type: ignore[arg-type]
                kicker=kicker,
                title=title,
                detail=detail,
                status=status,  # type: ignore[arg-type]
                depth=self.depth,
                max_depth=self.policy.max_loop_depth,
                tier=self.tier_name,
                spent_usd=money(self.spent),
                projected_usd=money(self.projected()),
                soft_budget_usd=money(self.policy.soft_budget_usd),
                hard_budget_usd=money(self.policy.hard_budget_usd),
                prompt_tokens_next=self.prompt_tokens(),
                completion_tokens_est=self.completion_est,
                repeat_limit=self.policy.max_identical_tool_repeats,
                repeat_count=repeat_count,
                repeat_label=repeat_label,
                halt_code=self.halt_code,
                halt_message=self.halt_message,
                overshoot=self.overshoot,
                final_text=self.final_text,
                tiers=self.tier_views(),
                rows=list(self.rows),
            )
        )

    def halt(self, code: str, message: str, *, overshoot: bool = False) -> RunReport:
        self.halt_code = code
        self.halt_message = message
        self.overshoot = overshoot
        titles = {
            "hard_budget": "Hard budget",
            "loop_depth": "Loop depth",
            "repeated_tool_call": "Repeated tool call",
            "provider_outage": "Provider outage",
        }
        self.snap("halt", "HALT", titles[code], message, status="halted")
        return self.finish("halted")

    def finish(self, status: str) -> RunReport:
        last = self.snapshots[-1]
        return RunReport(
            id=self.scenario.id,
            title=self.scenario.title,
            summary=self.scenario.summary,
            instruction=self.scenario.instruction.strip(),
            price_label=self.prices.label,
            price_disclaimer=self.prices.disclaimer,
            generated_at=self.generated_at,
            status=status,  # type: ignore[arg-type]
            halt_code=self.halt_code,
            halt_message=self.halt_message,
            overshoot=self.overshoot,
            depth=self.depth,
            final_tier=self.tier_name,
            spent_usd=money(self.spent),
            projected_usd=last.projected_usd,
            soft_budget_usd=money(self.policy.soft_budget_usd),
            hard_budget_usd=money(self.policy.hard_budget_usd),
            max_loop_depth=self.policy.max_loop_depth,
            max_identical_tool_repeats=self.policy.max_identical_tool_repeats,
            prompt_tokens=sum(row.prompt_tokens for row in self.rows),
            completion_tokens=sum(row.completion_tokens for row in self.rows),
            model_calls=self.model_calls,
            tool_executions=self.tools.executions,
            final_text=self.final_text,
            snapshots=list(self.snapshots),
            rows=list(self.rows),
        )

    def run(self) -> RunReport:
        self.snap(
            "start",
            "TASK",
            "Task accepted",
            self.scenario.instruction.strip(),
        )
        for _ in range(self.policy.max_loop_depth + 12):
            if self.depth >= self.policy.max_loop_depth:
                return self.halt(
                    "loop_depth",
                    f"Loop depth is {self.depth}, the maximum of {self.policy.max_loop_depth}. "
                    "No further model call was sent.",
                )
            projected = self.projected()
            if projected > self.policy.hard_budget_usd:
                price = self.prices.tier(self.tier_name)
                return self.halt(
                    "hard_budget",
                    f"Projected spend {money(projected)} USD would exceed the hard budget "
                    f"{money(self.policy.hard_budget_usd)} USD on tier {self.tier_name} "
                    f"({price.model_id}). The next call was not sent.",
                )
            price = self.prices.tier(self.tier_name)
            request = CompletionRequest(
                tier=self.tier_name,
                model_id=price.model_id,
                messages=list(self.messages),
                tools=self.tools.schemas(),
            )
            quote = projected
            try:
                completion = self.provider.complete(request)
            except ProviderOutage as exc:
                halted = self._outage(str(exc))
                if halted is not None:
                    return halted
                continue
            report = self._account(completion, quote)
            if report is not None:
                return report
        raise RuntimeError("kill switch exceeded its own safety iteration cap")

    def _outage(self, message: str) -> RunReport | None:
        failed_tier = self.tier_name
        self.failed.add(failed_tier)
        self.snap(
            "outage",
            "OUTAGE",
            f"{failed_tier} unreachable",
            message,
        )
        if failed_tier == self.policy.local_tier:
            return self.halt(
                "provider_outage",
                f"The local tier is unavailable ({message}). No cheaper fallback remains.",
            )
        self.tier_idx = self.policy.tiers.index(self.policy.local_tier)
        local = self.prices.tier(self.tier_name)
        self.snap(
            "fallback",
            "FALLBACK",
            f"Fell back to {local.display_name}",
            f"Outage on {failed_tier}. The next call uses {self.tier_name} ({local.model_id}), "
            "skipping any hosted tier in between. "
            f"{local.blurb}",
        )
        return None

    def _account(self, completion: Completion, quote: Decimal) -> RunReport | None:
        price = self.prices.tier(self.tier_name)
        turn_cost = cost_usd(
            completion.prompt_tokens,
            completion.completion_tokens,
            D(price.input_per_million_usd),
            D(price.output_per_million_usd),
        )
        self.spent += turn_cost
        self.depth += 1
        self.model_calls += 1
        self.completion_est = completion.completion_tokens or self.policy.planning_completion_tokens
        keys = [canonical_tool_key(call.name, call.arguments) for call in completion.tool_calls]
        tripped: tuple[str, int] | None = None
        for key in keys:
            self.repeats[key] = self.repeats.get(key, 0) + 1
            if self.repeats[key] >= self.policy.max_identical_tool_repeats:
                tripped = (key, self.repeats[key])
                break

        if tripped is not None:
            decision = "halt: repeated_tool_call"
        elif self.spent > self.policy.hard_budget_usd:
            decision = "halt: hard_budget"
        elif not completion.tool_calls:
            decision = "final answer"
        elif (
            self.spent >= self.policy.soft_budget_usd
            and self.tier_idx < len(self.policy.tiers) - 1
        ):
            decision = f"step down to {self.policy.tiers[self.tier_idx + 1]}"
        else:
            decision = "run tools"

        self.rows.append(
            LedgerRow(
                depth=self.depth,
                tier=self.tier_name,
                model_id=price.model_id,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                cost_usd=money(turn_cost),
                cumulative_usd=money(self.spent),
                projected_before_usd=money(quote),
                tool_calls=keys,
                decision=decision,
            )
        )

        if tripped is not None:
            key, count = tripped
            self.snap(
                "turn",
                "TURN",
                f"Model call {self.depth}",
                _turn_detail(price.display_name, price.model_id, self.rows[-1]),
            )
            return self.halt(
                "repeated_tool_call",
                f"{key} was returned {count} times. The limit is "
                f"{self.policy.max_identical_tool_repeats}. That call was not executed.",
            )
        if self.spent > self.policy.hard_budget_usd:
            self.snap(
                "turn",
                "TURN",
                f"Model call {self.depth}",
                _turn_detail(price.display_name, price.model_id, self.rows[-1]),
            )
            return self.halt(
                "hard_budget",
                f"Spend {money(self.spent)} USD crossed the hard budget "
                f"{money(self.policy.hard_budget_usd)} USD after the call returned. "
                "The estimate did not cover this completion. The loop is stopped.",
                overshoot=True,
            )
        if not completion.tool_calls:
            self.final_text = public_text(completion.content)
            self.snap(
                "complete",
                "DONE",
                "Task finished",
                "The model returned an answer and no tool call. The loop stopped.",
                status="completed",
            )
            return self.finish("completed")

        self.snap(
            "turn",
            "TURN",
            f"Model call {self.depth}",
            _turn_detail(price.display_name, price.model_id, self.rows[-1]),
        )
        if decision.startswith("step down to "):
            previous = self.tier_name
            self.stood_down.add(previous)
            self.tier_idx += 1
            nxt = self.prices.tier(self.tier_name)
            self.snap(
                "downgrade",
                "STEP DOWN",
                f"{previous} → {self.tier_name}",
                f"Soft budget {money(self.policy.soft_budget_usd)} USD reached at "
                f"{money(self.spent)} USD. The next model call uses {self.tier_name} "
                f"({nxt.model_id}) instead of {previous}.",
            )
        self._execute(completion)
        return None

    def _execute(self, completion: Completion) -> None:
        self.messages.append(
            Message(
                role="assistant",
                content=completion.content,
                tool_calls=list(completion.tool_calls),
            )
        )
        for call in completion.tool_calls:
            result = self.tools.execute(call)
            self.messages.append(Message(role="tool", name=call.name, content=result))
            tokens = estimate_text_tokens(result)
            if len(result) <= 420:
                detail = f"{call.name} → {result}"
            else:
                detail = (
                    f"{call.name} returned {tokens} tokens of synthetic data. "
                    "Those tokens are now part of the next prompt."
                )
            self.snap("tool", "TOOL", call.name, detail)


def _turn_detail(display: str, model_id: str, row: LedgerRow) -> str:
    calls = ", ".join(row.tool_calls) if row.tool_calls else "no tool call"
    return (
        f"{display} ({model_id}) billed {row.prompt_tokens} prompt tokens and "
        f"{row.completion_tokens} completion tokens. "
        f"Turn cost {row.cost_usd} USD, cumulative {row.cumulative_usd} USD. "
        f"Decision: {row.decision}. Calls: {calls}."
    )


def _initial_messages(scenario: Scenario) -> list[Message]:
    instruction = scenario.instruction.strip()
    if scenario.user_token_target is None:
        user = instruction
    else:
        user = fit_to_tokens(instruction + "\n", scenario.user_token_target, seed=scenario.id)
    return [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=user),
    ]


def run_scenario(
    scenario: Scenario,
    policy: Policy,
    prices: PriceTable,
    catalog: ToolCatalog,
    *,
    allow_ollama: bool = False,
    generated_at: str = RECORDED_AT,
    provider: RoutingProvider | None = None,
) -> RunReport:
    return KillSwitch(
        scenario,
        policy,
        prices,
        catalog,
        allow_ollama=allow_ollama,
        generated_at=generated_at,
        provider=provider,
    ).run()


def run_named(
    scenario_id: str,
    *,
    dataset: Dataset | None = None,
    catalog: ToolCatalog | None = None,
    policy: Policy | None = None,
    prices: PriceTable | None = None,
    allow_ollama: bool = False,
    uri: str | None = None,
) -> RunReport:
    from killswitch.dataset import load_bundle, scenario_by_id
    from killswitch.policy import load_policy
    from killswitch.pricing import load_prices

    if dataset is None or catalog is None:
        dataset, catalog = load_bundle(uri)
    if policy is None:
        policy = load_policy()
    if prices is None:
        prices = load_prices()
    return run_scenario(
        scenario_by_id(dataset, scenario_id),
        policy,
        prices,
        catalog,
        allow_ollama=allow_ollama,
    )
