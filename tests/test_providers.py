import pytest

from killswitch.models import CompletionRequest, Message, ScriptStep, ToolCall
from killswitch.pricing import load_prices
from killswitch.providers import (
    MockReplayProvider,
    OllamaProvider,
    ProviderOutage,
    RoutingProvider,
    ScriptExhausted,
)


def _request(tier: str) -> CompletionRequest:
    return CompletionRequest(
        tier=tier,
        model_id=f"{tier}-example",
        messages=[Message(role="user", content="hello")],
    )


def test_mock_outage_and_then_exhaustion():
    mock = MockReplayProvider([ScriptStep(outage=True, outage_message="down"), ScriptStep(content="ok")])
    with pytest.raises(ProviderOutage):
        mock.complete(_request("frontier"))
    done = mock.complete(_request("local"))
    assert done.content == "ok"
    assert done.prompt_tokens > 0
    with pytest.raises(ScriptExhausted):
        mock.complete(_request("local"))


def test_routing_sends_only_the_local_tier_to_ollama():
    seen = {}

    def transport(url, payload, timeout):
        seen["url"] = url
        seen["model"] = payload["model"]
        seen["seed"] = payload["options"]["seed"]
        return {
            "message": {
                "role": "assistant",
                "content": "pong",
                "tool_calls": [
                    {"type": "function", "function": {"name": "list_tickets", "arguments": {"queue": "FAC", "status": "open"}}}
                ],
            },
            "prompt_eval_count": 11,
            "eval_count": 4,
        }

    prices = load_prices()
    ollama = OllamaProvider("http://127.0.0.1:11434", "llama3.2", transport=transport)
    mock = MockReplayProvider([ScriptStep(content="from mock")])
    router = RoutingProvider(mock, prices, ollama)
    local = router.complete(_request("local"))
    assert local.content == "pong"
    assert local.tool_calls == [ToolCall(name="list_tickets", arguments={"queue": "FAC", "status": "open"})]
    assert local.prompt_tokens == 11
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["model"] == "llama3.2"
    assert seen["seed"] == 42
    assert mock.calls == 0
    hosted = router.complete(_request("frontier"))
    assert hosted.content == "from mock"
    assert mock.calls == 1


def test_ollama_transport_errors_are_outages():
    def transport(url, payload, timeout):
        raise TimeoutError("timed out")

    provider = OllamaProvider("http://127.0.0.1:9", "llama3.2", transport=transport)
    with pytest.raises(ProviderOutage):
        provider.complete(_request("local"))


def test_ollama_string_arguments_are_parsed():
    def transport(url, payload, timeout):
        return {"message": {"content": "", "tool_calls": [{"function": {"name": "search_inventory", "arguments": "{\"sku\":\"HX-204\",\"warehouse\":\"south\"}"}}]}}

    provider = OllamaProvider("http://ollama.local", "llama3.2", transport=transport)
    completion = provider.complete(_request("local"))
    assert completion.tool_calls[0].arguments == {"sku": "HX-204", "warehouse": "south"}
