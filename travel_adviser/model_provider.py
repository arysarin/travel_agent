"""Resolves the model every agent is built with: a fallback chain.

Tries, in order, however many of these are configured: the primary Gemini
model, a second Gemini model (separate free-tier quota bucket, same key),
Groq, then OpenRouter's free models. Each rung is independent and optional
— with none of the fallback rungs configured, this is just the plain
primary model, unchanged from a single-provider setup.
"""

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

from .config import (
    GEMINI_FALLBACK_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    MODEL_NAME,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)
from .fallback_llm import FallbackLlm

# attempts=1 disables the google-genai SDK's own internal retry loop on a
# Gemini 429/503 — without this, a single quota-exhausted call can sit
# retrying with backoff for 20+ minutes before FallbackLlm's own except
# block ever gets a chance to move to the next rung, defeating the point
# of having a fast fallback chain in the first place. The explicit
# http_options timeout matters separately: attempts=1 only stops *retries*
# after a response comes back — a request that never gets a response at
# all (a hung connection) has nothing bounding it without this.
#
# 60s, not 30s: a first pass at 30s turned out to cut off some Gemini
# calls that were just slow (large accumulated context late in the
# pipeline, e.g. final_merge_agent), not actually stuck — those got
# cancelled (a bare TimeoutError, or Gemini's own 499 CANCELLED) and
# bounced to the next rung for no reason. 60s still bounds the worst
# case (the un-timed-out hang that motivated this was 20+ minutes) while
# giving a legitimately slow-but-working call room to finish.
_FAST_FAIL_RETRY = types.HttpRetryOptions(attempts=1)
_FAST_FAIL_HTTP = types.HttpOptions(timeout=60_000)  # milliseconds

# Same idea for LiteLLM-backed rungs (Groq/OpenRouter): its default
# per-request timeout is 6000 seconds, and it has its own retry behavior
# independent of ours — both work against a fast-failing chain, so pin
# them down explicitly rather than inherit whatever LiteLLM defaults to.
_FAST_FAIL_LITELLM_KWARGS = {"timeout": 60, "num_retries": 0}


def _build_chain(rungs: list[BaseLlm]):
    """Folds a list of models, tried in order, into nested FallbackLlms."""
    result = rungs[-1]
    for rung in reversed(rungs[:-1]):
        result = FallbackLlm(primary=rung, fallback=result)
    return result


def get_model():
    rungs: list[BaseLlm] = [
        Gemini(
            model=MODEL_NAME,
            retry_options=_FAST_FAIL_RETRY,
            client_kwargs={"http_options": _FAST_FAIL_HTTP},
        )
    ]

    if GEMINI_FALLBACK_MODEL:
        rungs.append(
            Gemini(
                model=GEMINI_FALLBACK_MODEL,
                retry_options=_FAST_FAIL_RETRY,
                client_kwargs={"http_options": _FAST_FAIL_HTTP},
            )
        )

    if GROQ_API_KEY:
        rungs.append(LiteLlm(model=f"groq/{GROQ_MODEL}", **_FAST_FAIL_LITELLM_KWARGS))

    if OPENROUTER_API_KEY:
        rungs.append(LiteLlm(model=f"openrouter/{OPENROUTER_MODEL}", **_FAST_FAIL_LITELLM_KWARGS))

    return _build_chain(rungs)
