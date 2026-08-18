import src.nodes.generate_node as generate_module
from src.nodes.review_node import _repair_system_prompt


def test_generation_prompt_mentions_patient_path_tokens(monkeypatch):
    captured = {}

    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": True},
        "structure": {"packages": ["demo"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "demo",
                    "module": "core",
                    "functions": ["normalize_text"],
                    "classes": [],
                    "file_path": "demo/core.py",
                }
            ]
        },
    }

    monkeypatch.setattr(generate_module, "get_llm_service", lambda: object())

    def capture_prompt(_llm_service, user_prompt, _system_prompt=None, retries=2):
        captured["user_prompt"] = user_prompt
        return generate_module._generate_mcp_service_fallback(analysis)

    monkeypatch.setattr(generate_module, "_retry_generate_text", capture_prompt)

    generate_module._generate_mcp_service(analysis)

    prompt = captured["user_prompt"]
    assert "sensitive path segments" in prompt
    assert "patient" in prompt
    assert "pii" in prompt
    assert "phi" in prompt
    assert "dob" in prompt
    assert "mrn" in prompt


def test_repair_prompt_mentions_patient_path_tokens():
    prompt = _repair_system_prompt()

    assert "sensitive path segments" in prompt
    assert "patient" in prompt
    assert "pii" in prompt
    assert "phi" in prompt
    assert "dob" in prompt
    assert "mrn" in prompt
