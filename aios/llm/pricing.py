"""Model prices used for *estimated* cost. Actual cost is stored separately when a provider reports it.

Source: https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-05).
Prices are USD per million tokens, which equals micro-dollars per token.
"""

from __future__ import annotations

from dataclasses import dataclass

PRICING_VERSION = "anthropic-2026-10-05"
WEB_SEARCH_MICROS = 10_000  # $10 per 1,000 searches


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write_5m: float
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(10, 50, 12.50, 0.25),
    "claude-opus-5-5": Price(4, 20, 5, 0.20),
    "claude-sonnet-5-5": Price(2, 10, 2.50, 0.20),
    "claude-haiku-4-5": Price(1, 5, 1.25, 0.10),
    "claude-opus-5": Price(5, 25, 6.25, 0.50),
    "claude-sonnet-5": Price(2, 10, 2.50, 0.20),
}

TIER_ORDER = ["FAST", "BALANCED", "DEEP"]


def price_for(model: str) -> Price | None:
    if model in PRICES:
        return PRICES[model]
    # dated snapshots, e.g. claude-haiku-4-5-20251001
    for key in sorted(PRICES, key=len, reverse=True):
        if model.startswith(key):
            return PRICES[key]
    return None


def estimate_micros(model: str, *, input_tokens: int, output_tokens: int, cache_write: int = 0,
                    cache_read: int = 0, web_searches: int = 0) -> int:
    p = price_for(model)
    if p is None:  # unknown model: price as the most expensive we know rather than as free
        p = max(PRICES.values(), key=lambda x: x.output)
    total = (input_tokens * p.input + output_tokens * p.output + cache_write * p.cache_write_5m
             + cache_read * p.cache_read)
    return int(round(total)) + web_searches * WEB_SEARCH_MICROS


def projected_micros(model: str, prompt_chars: int, max_tokens: int, web_searches: int = 0) -> int:
    """Upper-bound estimate before a call: ~4 chars/token for input, full max_tokens for output."""
    return estimate_micros(model, input_tokens=prompt_chars // 4 + 200, output_tokens=max_tokens,
                           web_searches=web_searches)
