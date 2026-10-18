"""Published Cerebras Developer rates. API usage does not return USD."""

from __future__ import annotations

RATE_CARD_DATE = "2026-10-09"
RATE_CARD_SOURCE = (
    "Cerebras Developer public rate card as of 2026-10-09 "
    "(llmprice.com snapshot of the official models API; "
    "usagepricing.com 2026-10-05 packaging note). "
    "Developer tier is for evaluation, not production."
)
RATES_USD_PER_MILLION = {
    "gpt-oss-120b": {"input": 0.35, "output": 0.75},
    "qwen-3.8-27b": {"input": 0.99, "output": 1.49},
}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = RATES_USD_PER_MILLION.get(model)
    if rates is None:
        raise ValueError(f"no published Cerebras rate for {model}")
    return (
        prompt_tokens * rates["input"] + completion_tokens * rates["output"]
    ) / 1_000_000
