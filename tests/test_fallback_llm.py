from google.genai.errors import APIError

from travel_adviser.fallback_llm import _is_transient


def _err(code: int, message: str) -> APIError:
    return APIError(code, {"error": {"code": code, "message": message}})


def test_quota_overload_and_missing_model_are_transient():
    for code in (404, 429, 503):
        assert _is_transient(_err(code, "x"))


def test_missing_thought_signature_400_is_transient():
    assert _is_transient(
        _err(400, "Function call is missing a thought_signature in functionCall parts.")
    )


def test_other_400s_still_raise():
    assert not _is_transient(_err(400, "Invalid JSON payload received."))


def test_auth_errors_still_raise():
    assert not _is_transient(_err(401, "API key not valid."))
