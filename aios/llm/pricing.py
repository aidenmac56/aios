"""Model prices used for *estimated* cost. Actual cost is stored separately when a provider reports it.

Sources (USD per million tokens):
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-05)
- OpenAI: https://openai.com/api/pricing/ (checked 2026-10-09; no published cache-write price, so the
  input price is used for it)
- Meta Model API (Muse Spark): https://www.promptfoo.dev/docs/providers/meta/ and Meta's launch post
  (checked 2026-10-09). `muse-spark-*-contributor` is cheaper but lets Meta train on your data; not priced
  here on purpose, so it is costed as the most expensive model if someone uses it.
- Ollama (local) and macOS Shortcuts: no per-token charge. Apple/ChatGPT daily limits apply to Shortcuts.
Prices are USD per million tokens, which equals micro-dollars per token.
"""

from __future__ import annotations

from dataclasses import dataclass

PRICING_VERSION = "multi-2026-10-09"
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
    "muse-spark-1.3": Price(1.25, 4.25, 1.25, 0.15),
    "muse-spark-1.1": Price(1.25, 4.25, 1.25, 0.15),
    "gpt-5.6-sol": Price(5, 30, 5, 5),
    "gpt-5.6-terra": Price(2, 12, 2, 2),
    "gpt-5.6-luna": Price(0.20, 1.20, 0.20, 0.20),
    "jev-latest": Price(0.042, 0, 0, 0),  # TypeSafe AI, routing decisions only; output tokens free
    "ollama/": Price(0, 0, 0, 0),
    "shortcut:": Price(0, 0, 0, 0),
}

TIER_ORDER = ["FAST", "BALANCED", "DEEP"]


def price_for(model: str) -> Price | None:
    if model in PRICES:
        return PRICES[model]
    # dated snapshots, e.g. claude-haiku-4-5-20251001
    for key in sorted(PRICES, key=len, reverse=True):
        if model.startswith(key) and not model.endswith("-contributor"):
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
