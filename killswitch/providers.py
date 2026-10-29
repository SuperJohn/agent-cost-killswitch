"""Model providers.

The mock replays a scenario script and is the default, so tests and CI need no
keys. Ollama is optional: set HL_OLLAMA_HOST and the local tier is sent there.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Callable

from killswitch.models import Completion, CompletionRequest, Message, ScriptStep, ToolCall
from killswitch.pricing import PriceTable
from killswitch.tokens import canonical_args, estimate_messages, estimate_text_tokens

Transport = Callable[[str, dict, float], dict]


class ProviderOutage(Exception):
    """The provider could not be reached or returned a server error."""


class ScriptExhausted(RuntimeError):
    """The mock was asked for a step the scenario did not script."""


class ProviderError(RuntimeError):
    """The provider answered, but not in a shape we can bill."""


class MockReplayProvider:
    """Return the next scripted step. Token counts use the shared estimator."""

    def __init__(self, steps: list[ScriptStep]):
        self.steps = list(steps)
        self.cursor = 0
        self.calls = 0
        self.tiers: list[str] = []

    def complete(self, request: CompletionRequest) -> Completion:
        if self.cursor >= len(self.steps):
            raise ScriptExhausted(
                f"scenario has no step left after {self.cursor} provider calls"
            )
        step = self.steps[self.cursor]
        self.cursor += 1
        self.calls += 1
        self.tiers.append(request.tier)
        if step.outage:
            raise ProviderOutage(step.outage_message)
        if step.content_tokens is not None:
            from killswitch.tokens import text_with_token_count

            content = text_with_token_count(step.content_tokens, step.content_seed)
        else:
            content = step.content
        completion_tokens = estimate_text_tokens(content)
        for call in step.tool_calls:
            completion_tokens += estimate_text_tokens(call.name)
            completion_tokens += estimate_text_tokens(canonical_args(call.arguments))
        return Completion(
            content=content,
            tool_calls=list(step.tool_calls),
            prompt_tokens=estimate_messages(request.messages),
            completion_tokens=completion_tokens,
            provider_model=request.model_id,
        )


def urllib_transport(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise ProviderOutage(f"ollama request failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderError("ollama returned non-JSON") from exc


class OllamaProvider:
    """Local models via the Ollama HTTP API. No SDK dependency."""

    def __init__(
        self,
        host: str,
        model: str,
        transport: Transport | None = None,
        timeout: float = 120.0,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.transport = transport or urllib_transport
        self.timeout = timeout

    def complete(self, request: CompletionRequest) -> Completion:
        payload: dict = {
            "model": self.model,
            "messages": [_ollama_message(m) for m in request.messages],
            "stream": False,
            "options": {"temperature": 0, "seed": 42},
        }
        if request.tools:
            payload["tools"] = request.tools
        try:
            data = self.transport(f"{self.host}/api/chat", payload, self.timeout)
        except ProviderOutage:
            raise
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as exc:
            raise ProviderOutage(f"ollama request failed: {exc}") from exc
        message = data.get("message") or {}
        content = message.get("content") or ""
        tool_calls = [_parse_tool_call(raw) for raw in message.get("tool_calls") or []]
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        if not isinstance(prompt_tokens, int):
            prompt_tokens = estimate_messages(request.messages)
        if not isinstance(completion_tokens, int):
            completion_tokens = estimate_text_tokens(content)
        return Completion(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            provider_model=self.model,
        )


def _ollama_message(message: Message) -> dict:
    payload: dict = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.name and message.role == "tool":
        payload["name"] = message.name
    return payload


def _parse_tool_call(raw: object) -> ToolCall:
    if not isinstance(raw, dict):
        raise ProviderError("tool call was not an object")
    function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
    if not isinstance(function, dict) or "name" not in function:
        raise ProviderError("tool call is missing a function name")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as exc:
            raise ProviderError("tool call arguments were not JSON") from exc
    if not isinstance(arguments, dict):
        raise ProviderError("tool call arguments were not an object")
    return ToolCall(name=str(function["name"]), arguments=arguments)


class RoutingProvider:
    """Frontier and mid stay on the mock. The local tier can be a live Ollama."""

    def __init__(self, mock: MockReplayProvider, prices: PriceTable, ollama: OllamaProvider | None):
        self.mock = mock
        self.prices = prices
        self.ollama = ollama

    def complete(self, request: CompletionRequest) -> Completion:
        tier = self.prices.tier(request.tier)
        if self.ollama is not None and tier.provider == "ollama":
            return self.ollama.complete(request)
        return self.mock.complete(request)


def ollama_from_env(prices: PriceTable) -> OllamaProvider | None:
    host = os.environ.get("HL_OLLAMA_HOST", "").strip()
    if not host:
        return None
    configured = prices.tier("local").ollama_model or "llama3.2"
    model = os.environ.get("HL_OLLAMA_MODEL", "").strip() or configured
    return OllamaProvider(host, model)
