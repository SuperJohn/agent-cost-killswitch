from decimal import Decimal

import pytest

from killswitch.dataset import load_bundle, scenario_by_id
from killswitch.engine import run_named, run_scenario
from killswitch.models import Scenario, ScriptStep, ToolCall
from killswitch.policy import load_policy
from killswitch.pricing import load_prices
from killswitch.providers import MockReplayProvider, RoutingProvider


@pytest.fixture(scope="module")
def bundle():
    return load_bundle()


@pytest.fixture(scope="module")
def prices():
    return load_prices()


@pytest.fixture(scope="module")
def policy():
    return load_policy()


def _run(bundle, policy, prices, scenario_id):
    dataset, catalog = bundle
    return run_scenario(scenario_by_id(dataset, scenario_id), policy, prices, catalog)


def test_normal_task_stays_on_frontier_under_soft(bundle, policy, prices):
    report = _run(bundle, policy, prices, "normal")
    assert report.status == "completed"
    assert report.halt_code is None
    assert report.final_tier == "frontier"
    assert report.depth == 2
    assert Decimal(report.spent_usd) < policy.soft_budget_usd
    assert "FAC-1842" in report.final_text
    assert [row.tier for row in report.rows] == ["frontier", "frontier"]
    assert report.price_label == "example"
    kinds = [s.kind for s in report.snapshots]
    assert "downgrade" not in kinds
    assert kinds[-1] == "complete"
    # Ledger lines sum to the reported spend.
    assert sum(Decimal(row.cost_usd) for row in report.rows) == Decimal(report.spent_usd)


def test_runaway_halts_on_the_third_identical_call_without_running_it(bundle, policy, prices):
    dataset, catalog = bundle
    scenario = scenario_by_id(dataset, "runaway-loop")
    mock = MockReplayProvider(scenario.steps)
    report = run_scenario(
        scenario,
        policy,
        prices,
        catalog,
        provider=RoutingProvider(mock, prices, None),
    )
    assert report.status == "halted"
    assert report.halt_code == "repeated_tool_call"
    assert report.depth == 3
    assert report.final_tier == "frontier"
    assert Decimal(report.spent_usd) < policy.soft_budget_usd
    assert report.tool_executions == 2
    assert mock.calls == 3
    assert mock.tiers == ["frontier", "frontier", "frontier"]
    assert "search_inventory" in report.halt_message
    assert report.rows[-1].decision == "halt: repeated_tool_call"


def test_argument_order_does_not_reset_the_repeat_counter(bundle, policy, prices):
    # The third scripted call swaps key order. It still counts as the same call.
    report = _run(bundle, policy, prices, "runaway-loop")
    assert report.halt_code == "repeated_tool_call"
    assert report.snapshots[-1].repeat_count == 3


def test_budget_steps_down_then_refuses_the_call(bundle, policy, prices):
    dataset, catalog = bundle
    scenario = scenario_by_id(dataset, "budget-overrun")
    mock = MockReplayProvider(scenario.steps)
    report = run_scenario(
        scenario,
        policy,
        prices,
        catalog,
        provider=RoutingProvider(mock, prices, None),
    )
    assert report.status == "halted"
    assert report.halt_code == "hard_budget"
    assert report.overshoot is False
    assert report.final_tier == "mid"
    assert Decimal(report.spent_usd) <= policy.hard_budget_usd
    assert Decimal(report.projected_usd) > policy.hard_budget_usd
    assert mock.calls == 1
    assert mock.tiers == ["frontier"]
    assert report.tool_executions == 1
    kinds = [s.kind for s in report.snapshots]
    assert kinds.count("downgrade") == 1
    downgrade = next(s for s in report.snapshots if s.kind == "downgrade")
    assert downgrade.tiers[0].state == "stood_down"
    assert downgrade.tiers[1].state == "active"
    assert "not sent" in report.halt_message
    assert report.rows[0].decision == "step down to mid"


def test_outage_falls_back_to_local_and_finishes(bundle, policy, prices):
    dataset, catalog = bundle
    scenario = scenario_by_id(dataset, "provider-outage")
    mock = MockReplayProvider(scenario.steps)
    report = run_scenario(
        scenario,
        policy,
        prices,
        catalog,
        provider=RoutingProvider(mock, prices, None),
    )
    assert report.status == "completed"
    assert report.final_tier == "local"
    assert report.spent_usd == "0.000000"
    assert report.depth == 2
    assert mock.tiers == ["frontier", "local", "local"]
    assert "FAC-1842" in report.final_text
    kinds = [s.kind for s in report.snapshots]
    assert kinds[1] == "outage"
    assert kinds[2] == "fallback"
    outage = report.snapshots[1]
    assert outage.tiers[0].state == "failed"
    fallback = report.snapshots[2]
    assert fallback.tier == "local"
    assert fallback.tiers[2].state == "active"
    # Mid was not used. Outage skips to local.
    assert "mid" not in mock.tiers


def test_two_runs_are_identical(bundle, policy, prices):
    first = _run(bundle, policy, prices, "normal").model_dump(mode="json")
    second = _run(bundle, policy, prices, "normal").model_dump(mode="json")
    assert first == second


def test_preflight_halt_sends_no_call(bundle, prices):
    dataset, catalog = bundle
    policy = load_policy().model_copy(
        update={"hard_budget_usd": Decimal("0.01"), "soft_budget_usd": Decimal("0.005")}
    )
    scenario = Scenario(
        id="preflight",
        title="Preflight",
        summary="Projection is already over the cap.",
        instruction="Count the synthetic widgets.",
        steps=[ScriptStep(content="should not run")],
    )
    mock = MockReplayProvider(scenario.steps)
    report = run_scenario(
        scenario, policy, prices, catalog, provider=RoutingProvider(mock, prices, None)
    )
    assert report.halt_code == "hard_budget"
    assert report.depth == 0
    assert report.spent_usd == "0.000000"
    assert mock.calls == 0
    assert report.rows == []


def test_long_completion_can_overshoot_then_stops(bundle, prices):
    dataset, catalog = bundle
    policy = load_policy().model_copy(
        update={
            "hard_budget_usd": Decimal("0.20"),
            "soft_budget_usd": Decimal("0.19"),
            "planning_completion_tokens": 32,
        }
    )
    scenario = Scenario(
        id="overshoot",
        title="Overshoot",
        summary="The completion is longer than the estimate.",
        instruction="Dump the synthetic log.",
        steps=[ScriptStep(content_tokens=5000, content_seed="verbose")],
    )
    report = run_scenario(scenario, policy, prices, catalog)
    assert report.halt_code == "hard_budget"
    assert report.overshoot is True
    assert Decimal(report.spent_usd) > policy.hard_budget_usd
    assert report.depth == 1
    assert not any(s.kind == "downgrade" for s in report.snapshots)


def test_loop_depth_halts_before_another_call(bundle, prices):
    dataset, catalog = bundle
    policy = load_policy().model_copy(update={"max_loop_depth": 2, "soft_budget_usd": Decimal("0.49")})
    steps = [
        ScriptStep(tool_calls=[ToolCall(name="search_inventory", arguments={"sku": f"HX-{i}", "warehouse": "south"})])
        for i in range(4)
    ]
    scenario = Scenario(
        id="depth",
        title="Depth",
        summary="Unique calls so the repeat limit stays quiet.",
        instruction="Look up four synthetic SKUs.",
        steps=steps,
    )
    mock = MockReplayProvider(scenario.steps)
    report = run_scenario(
        scenario, policy, prices, catalog, provider=RoutingProvider(mock, prices, None)
    )
    assert report.halt_code == "loop_depth"
    assert report.depth == 2
    assert mock.calls == 2
    assert report.tool_executions == 2


def test_soft_budget_does_not_halt_on_the_cheapest_tier(bundle, prices):
    dataset, catalog = bundle
    policy = load_policy().model_copy(
        update={
            "tiers": ["local"],
            "local_tier": "local",
            "soft_budget_usd": Decimal("0"),
            "hard_budget_usd": Decimal("0.50"),
        }
    )
    scenario = scenario_by_id(dataset, "normal")
    report = run_scenario(scenario, policy, prices, catalog)
    assert report.status == "completed"
    assert report.final_tier == "local"
    assert not any(s.kind == "downgrade" for s in report.snapshots)


def test_local_outage_halts(bundle, policy, prices):
    dataset, catalog = bundle
    scenario = Scenario(
        id="local-down",
        title="Local down",
        summary="Both attempts fail.",
        instruction="Write the note.",
        steps=[
            ScriptStep(outage=True, outage_message="example frontier provider returned HTTP 503"),
            ScriptStep(outage=True, outage_message="ollama connection refused"),
        ],
    )
    report = run_scenario(scenario, policy, prices, catalog)
    assert report.halt_code == "provider_outage"
    assert report.spent_usd == "0.000000"
    assert report.depth == 0


def test_named_runner_matches(bundle):
    report = run_named("normal")
    assert report.id == "normal"
    assert report.status == "completed"
