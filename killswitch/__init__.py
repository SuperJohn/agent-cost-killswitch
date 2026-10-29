"""Cost and loop-depth kill switch for agent loops.

The middleware meters depth, repeated tool calls, tokens, and projected spend.
A soft budget steps the model down a tier. A hard budget, a depth ceiling, or
a repeated tool call opens the breaker and returns a structured reason.
"""

__version__ = "0.1.0"
