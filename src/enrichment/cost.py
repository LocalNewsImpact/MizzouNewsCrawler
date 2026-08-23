"""Per-call cost from token counts.

Rates live here as data, keyed by model id — not hardcoded at call sites
(docs/BACKFIELD_IMPLEMENTATION.md §5.7). Unknown models cost Decimal 0 and the
caller records the tokens regardless, so a rate gap is visible rather than
silently wrong.
"""

from __future__ import annotations

from decimal import Decimal

# USD per token.
RATES: dict[str, dict[str, Decimal]] = {
    "openrouter/deepseek/deepseek-v3.2": {
        "in": Decimal("0.25e-6"),
        "out": Decimal("0.95e-6"),
    },
}


def call_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    rate = RATES.get(model)
    if rate is None:
        return Decimal("0")
    return rate["in"] * input_tokens + rate["out"] * output_tokens
