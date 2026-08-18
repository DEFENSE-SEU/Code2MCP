import json

from src import codex_auth


def test_explicit_codex_auth_file_takes_precedence(monkeypatch, tmp_path):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"access_token": "token-from-explicit-file"}), encoding="utf-8")
    monkeypatch.delenv("OPENAI_CODEX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_CODEX_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_CODEX_AUTH_FILE", str(auth_file))

    auth = codex_auth.load_cached_codex_auth()

    assert auth is not None
    assert auth.access_token == "token-from-explicit-file"
    assert auth.source == str(auth_file)
