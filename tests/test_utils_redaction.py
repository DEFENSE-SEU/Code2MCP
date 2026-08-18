from src.utils import redact_sensitive_data, redact_sensitive_text


def test_redact_sensitive_text_masks_url_userinfo():
    value = "clone failed for https://ghp_secret_123456:password123@github.com/example/private.git"

    redacted = redact_sensitive_text(value)

    assert "ghp_secret_123456" not in redacted
    assert "password123" not in redacted
    assert "https://[REDACTED]@github.com/example/private.git" in redacted


def test_redact_sensitive_data_masks_url_userinfo_in_nested_values():
    payload = {
        "repo_name": "https://token-secret-123456@github.com/example/private",
        "items": ["https://user:pass-secret-123456@example.com/repo.git"],
    }

    redacted = redact_sensitive_data(payload)

    dumped = str(redacted)
    assert "token-secret-123456" not in dumped
    assert "pass-secret-123456" not in dumped
    assert "[REDACTED]" in dumped


def test_redact_sensitive_text_masks_bare_provider_tokens():
    value = (
        "OpenAI rejected sk-proj-abcdefghijklmnopqrstuvwxyz123456 "
        "GitHub token ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "HF token hf_abcdefghijklmnopqrstuvwxyz"
    )

    redacted = redact_sensitive_text(value)

    assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "hf_abcdefghijklmnopqrstuvwxyz" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_redact_sensitive_text_masks_tokens_embedded_after_separators():
    value = (
        "module finance_sk-finalize-secret-123456 "
        "path src/sk-finalize-secret-123456/private.py"
    )

    redacted = redact_sensitive_text(value)

    assert "sk-finalize-secret-123456" not in redacted
    assert redacted.count("[REDACTED]") == 2
