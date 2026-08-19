"""The litellm layer.

Everything that talks to a model goes through a single `Router`. That buys us,
for free and provider-agnostically:
  * named logical models ("scorer" / "grouper") so the rest of the code never
    hardcodes a vendor string,
  * automatic retries with backoff,
  * cross-model fallbacks when a deployment 429s or dies,
  * cooldowns so a flapping deployment stops getting traffic,
  * a uniform usage/cost surface across providers.

Swap Anthropic for Bedrock, Azure, or a self-hosted vLLM by editing MODELS below
(or the env vars) — no other file changes.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

import litellm
from litellm import Router

litellm.suppress_debug_info = True

# Cheap + fast for the per-mention fan-out; strong for the one synthesis call.
SCORER = os.getenv("SQUIDWARD_SCORER_MODEL", "anthropic/claude-haiku-4-5")
SCORER_BACKUP = os.getenv("SQUIDWARD_SCORER_BACKUP", "anthropic/claude-sonnet-5")
GROUPER = os.getenv("SQUIDWARD_GROUPER_MODEL", "anthropic/claude-sonnet-5")
GROUPER_BACKUP = os.getenv("SQUIDWARD_GROUPER_BACKUP", "anthropic/claude-opus-5")


def build_router() -> Router:
    return Router(
        model_list=[
            {"model_name": "scorer",
             "litellm_params": {"model": SCORER, "max_tokens": 4096}},
            {"model_name": "scorer-backup",
             "litellm_params": {"model": SCORER_BACKUP, "max_tokens": 4096}},
            {"model_name": "grouper",
             "litellm_params": {"model": GROUPER, "max_tokens": 16384}},
            {"model_name": "grouper-backup",
             "litellm_params": {"model": GROUPER_BACKUP, "max_tokens": 16384}},
        ],
        fallbacks=[{"scorer": ["scorer-backup"]}, {"grouper": ["grouper-backup"]}],
        num_retries=3,
        timeout=120,
        allowed_fails=3,
        cooldown_time=30,
        routing_strategy="simple-shuffle",
    )


def supports_json_schema(model: str) -> bool:
    """Ask litellm whether this model can be handed a JSON schema directly.

    litellm knows this per-model, so we can degrade to prompt-coerced JSON on
    models that don't — rather than discovering it as a 400 in production.
    """
    try:
        return bool(litellm.supports_response_schema(model=model))
    except Exception:
        return False


class Spend:
    """Running tally of what this run cost, computed by litellm's price map."""

    def __init__(self) -> None:
        self.calls = 0
        self.usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0

    def record(self, response: Any) -> None:
        self.calls += 1
        try:
            self.usd += float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:
            pass  # unknown model in the price map — tokens still count
        usage = getattr(response, "usage", None)
        if usage:
            self.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.output_tokens += getattr(usage, "completion_tokens", 0) or 0

    def __str__(self) -> str:
        return (f"{self.calls} calls · {self.input_tokens:,} in / "
                f"{self.output_tokens:,} out tokens · ${self.usd:.4f}")
