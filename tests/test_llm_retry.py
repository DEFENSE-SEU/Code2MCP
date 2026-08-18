import pytest

from src.codex_client import CodexBackendError
from src.utils import LLMService, ModelConfig


def test_codex_non_retryable_error_fails_fast(monkeypatch):
    service = LLMService(
        ModelConfig(
            provider="openai-codex",
            model_version="unsupported-model",
            api_key="",
            base_url="https://chatgpt.com/backend-api/codex",
        )
    )

    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise CodexBackendError(400, "model is not supported")

    monkeypatch.setattr(service, "_invoke_codex", fail_once)

    with pytest.raises(CodexBackendError):
        service.invoke("hello", max_retries=10)

    assert calls == 1
    assert service.retry_count == 1
