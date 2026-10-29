"""Deterministic token estimates.

This is a character counter, not a model tokenizer. Bills from a real provider
will differ. The same text always yields the same count, which is what the
replay and the tests need.
"""

import json


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 3) // 4


def text_with_token_count(n: int, seed: str = "synthetic") -> str:
    """Build an obvious synthetic string whose estimate is exactly ``n``."""
    if n < 0:
        raise ValueError("token count must be >= 0")
    if n == 0:
        return ""
    target_len = 4 * n
    phrase = f"synthetic {seed} row "
    text = (phrase * (target_len // len(phrase) + 1))[:target_len]
    got = estimate_text_tokens(text)
    if got != n:
        raise RuntimeError(f"token filler produced {got}, wanted {n}")
    return text


def _chunk(length: int, seed: str) -> str:
    if length <= 0:
        return ""
    phrase = f"synthetic {seed} row "
    return (phrase * (length // len(phrase) + 1))[:length]


def fit_to_tokens(prefix: str, n: int, seed: str = "synthetic") -> str:
    """Return ``prefix`` plus synthetic filler so the whole string estimates to ``n``."""
    if n < 0:
        raise ValueError("token count must be >= 0")
    have = estimate_text_tokens(prefix)
    if have > n:
        raise ValueError(f"prefix is already {have} tokens; target is {n}")
    lo, hi = 0, 4 * n + 4
    best: str | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        filler = _chunk(mid, seed)
        total = estimate_text_tokens(prefix + filler)
        if total == n:
            best = filler
            hi = mid - 1
        elif total < n:
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        raise RuntimeError(f"could not fit text to {n} tokens")
    result = prefix + best
    if estimate_text_tokens(result) != n:
        raise RuntimeError("fit check failed")
    return result


def estimate_messages(messages) -> int:
    """Token estimate for a chat, including tool-call arguments on assistant turns."""
    total = 0
    for message in messages:
        total += estimate_text_tokens(message.content)
        for call in message.tool_calls:
            total += estimate_text_tokens(call.name)
            total += estimate_text_tokens(canonical_args(call.arguments))
    return total


def canonical_args(arguments: dict) -> str:
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_tool_key(name: str, arguments: dict) -> str:
    """Identity of a tool call. Key order does not make a call look new."""
    return f"{name}:{canonical_args(arguments)}"
