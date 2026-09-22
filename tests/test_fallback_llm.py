import pytest
from google.adk.models.base_llm import BaseLlm
from google.genai.errors import APIError

from travel_adviser.fallback_llm import FallbackLlm, _is_transient


def _err(code: int, message: str) -> APIError:
    return APIError(code, {"error": {"code": code, "message": message}})


def test_quota_overload_and_missing_model_are_transient():
    for code in (404, 429, 499, 503, 504):
        assert _is_transient(_err(code, "x"))


def test_missing_thought_signature_400_is_transient():
    assert _is_transient(
        _err(400, "Function call is missing a thought_signature in functionCall parts.")
    )


def test_other_400s_still_raise():
    assert not _is_transient(_err(400, "Invalid JSON payload received."))


def test_auth_errors_still_raise():
    assert not _is_transient(_err(401, "API key not valid."))


class _FakeLlm(BaseLlm):
    """A minimal BaseLlm that either raises once or yields a fixed response."""

    to_raise: Exception | None = None
    response: object = None

    async def generate_content_async(self, llm_request, stream=False):
        if self.to_raise is not None:
            raise self.to_raise
        yield self.response


@pytest.mark.anyio
async def test_bare_timeout_error_cascades_to_fallback():
    # A bare TimeoutError (e.g. asyncio.TimeoutError from aiohttp on our own
    # http_options timeout) isn't a GenAIAPIError/OpenAIAPIError at all, so
    # it must be caught by its own except arm rather than _is_transient.
    primary = _FakeLlm(model="primary-model", to_raise=TimeoutError())
    fallback = _FakeLlm(model="fallback-model", response="ok")
    chain = FallbackLlm(primary=primary, fallback=fallback)

    from google.adk.models.llm_request import LlmRequest

    llm_request = LlmRequest(model="primary-model", contents=[])
    results = [r async for r in chain.generate_content_async(llm_request)]
    assert results == ["ok"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
