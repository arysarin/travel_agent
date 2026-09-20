"""A BaseLlm that retries on a second model/provider when the primary fails.

Built after repeatedly hitting the Gemini free tier's 20 requests/day quota
during development (429 RESOURCE_EXHAUSTED), plus occasional 503 "model
overloaded" responses. Both are transient/account-level failures, not
correctness bugs, so falling back rather than failing the whole run is the
right response. Instances nest (model_provider.py chains several of these
together — a second Gemini model, then Groq, then OpenRouter), so this
also has to recognize failures from a LiteLLM-backed rung (Groq/OpenRouter),
not just Gemini's own native client, or the chain would stop cascading
after the first LiteLLM rung.
"""

from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai.errors import APIError as GenAIAPIError
from openai import APIError as OpenAIAPIError
from openai import APIStatusError as OpenAIAPIStatusError

from .logging_utils import _write_event

# HTTP status worth falling back on: 429 = quota exhausted/rate limited,
# 503 = model temporarily overloaded, 404 = model retired/not available to
# this account. That last one looks like it should be a loud config bug,
# but in practice every provider used here has hit it during development
# (Gemini retired gemini-2.0-flash, then gemini-2.5-flash turned out to be
# "no longer available to new users" despite still being listed by the
# models endpoint; Groq retired llama-3.3-70b-versatile) — for a chain
# whose whole purpose is resilience, "this rung is unreachable" should
# always mean "try the next one," not "break the entire chain." Genuine
# misconfiguration (bad API key, malformed request) still surfaces
# normally since those aren't in this set.
_FALLBACK_STATUSES = {404, 429, 503}


def _is_transient(exc: Exception) -> bool:
    """Whether `exc` is worth failing over on rather than raising."""
    if isinstance(exc, GenAIAPIError):
        # Every LLM call restarts the chain at the first rung. If an earlier
        # call in the same conversation fell through to Groq/OpenRouter and
        # made a tool call, Gemini receives that function call without the
        # thought_signature it requires and rejects the whole request with
        # a 400. That's a rung that can't handle this history, not a bug in
        # the request — cascading keeps the tool-calling turn on the rung
        # that produced the call.
        if exc.code == 400 and "thought_signature" in str(exc):
            return True
        return exc.code in _FALLBACK_STATUSES
    if isinstance(exc, OpenAIAPIStatusError):
        # Covers LiteLLM's mapped RateLimitError/InternalServerError/etc.
        # from a Groq or OpenRouter rung — LiteLLM re-raises provider
        # errors as this same OpenAI-shaped hierarchy regardless of the
        # underlying provider.
        return exc.status_code in _FALLBACK_STATUSES
    if isinstance(exc, OpenAIAPIError):
        # No HTTP status at all (e.g. a connection error) — still a pure
        # availability problem, not a logic bug, so still worth cascading.
        return True
    return False


def _resolves_to_litellm(model: BaseLlm) -> bool:
    """Whether `model` (unwrapping any nested FallbackLlm) is LiteLLM-backed."""
    while isinstance(model, FallbackLlm):
        model = model.primary
    return isinstance(model, LiteLlm)


class FallbackLlm(BaseLlm):
    primary: BaseLlm
    fallback: BaseLlm

    def __init__(self, primary: BaseLlm, fallback: BaseLlm):
        super().__init__(model=primary.model, primary=primary, fallback=fallback)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        try:
            async for response in self.primary.generate_content_async(llm_request, stream):
                yield response
            return
        except (GenAIAPIError, OpenAIAPIError) as exc:
            if not _is_transient(exc):
                raise
            # If the whole chain ends up exhausted, only the last rung's
            # error reaches the caller — log each hop so the earlier rungs'
            # failures are still diagnosable afterwards.
            _write_event(
                {
                    "event": "model_fallback",
                    "from": self.primary.model,
                    "to": self.fallback.model,
                    "error": str(exc)[:300],
                }
            )

        # LiteLlm resolves its model as `llm_request.model or self.model`,
        # and llm_request.model is still the primary's name (set upstream by
        # ADK before this call) — without overwriting it here, the fallback
        # would silently try to call itself under the *primary's* model name.
        llm_request.model = self.fallback.model

        # Earlier turns in this conversation may have been answered by
        # Gemini in thinking mode, leaving "thought" parts in the history.
        # ADK always carries those into a replayed assistant message's
        # reasoning_content field, and Groq's/OpenRouter's APIs flatly
        # reject that field on a replayed message ("property
        # 'reasoning_content' is unsupported"), unlike Anthropic/Azure
        # which accept it. Strip thought parts before replaying history to
        # the fallback — but only when the fallback is actually
        # LiteLLM-backed. Doing this unconditionally broke Gemini-to-Gemini
        # fallback (e.g. GEMINI_FALLBACK_MODEL): Gemini's own API requires
        # a thought_signature on replayed function-call parts and rejects
        # the request outright if one is missing ("Function call is
        # missing a thought_signature"), so stripping content ahead of
        # another Gemini call does more harm than good.
        if _resolves_to_litellm(self.fallback):
            for content in llm_request.contents or []:
                if content.parts:
                    content.parts = [p for p in content.parts if not p.thought]

        async for response in self.fallback.generate_content_async(llm_request, stream):
            yield response
