"""Deterministic synthetic tools. Results come from the catalog, not from a network."""

import json

from killswitch.models import ToolCall, ToolCatalog
from killswitch.tokens import text_with_token_count


class ToolExecutor:
    def __init__(self, catalog: ToolCatalog, overrides: dict | None = None):
        self.catalog = catalog
        self.overrides = overrides or {}
        self.executions = 0

    def schemas(self) -> list[dict]:
        tools = []
        for name, spec in self.catalog.tools.items():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
            )
        return tools

    def execute(self, call: ToolCall) -> str:
        self.executions += 1
        spec = self.catalog.tools.get(call.name)
        if spec is None:
            return json.dumps({"error": "unknown tool", "name": call.name}, sort_keys=True)
        override = self.overrides.get(call.name) or {}
        if spec.result_mode == "token_target" or "token_target" in override:
            count = int(override.get("token_target", spec.default_token_target))
            return text_with_token_count(count, seed=call.name)
        if spec.result is None:
            raise ValueError(f"tool {call.name} has no JSON result")
        return json.dumps(spec.result, sort_keys=True, separators=(",", ":"))
