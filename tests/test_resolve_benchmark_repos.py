import json
import sys

import scripts.resolve_benchmark_repos as resolver


def test_git_ls_remote_redacts_sensitive_errors(monkeypatch):
    class Proc:
        returncode = 128
        stdout = ""
        stderr = (
            "fatal: could not read from https://ghp_secret_123456:password123@github.com/example/private.git "
            "OPENAI_API_KEY=sk-live-secret-123456"
        )

    monkeypatch.setattr(resolver.subprocess, "run", lambda *_args, **_kwargs: Proc())

    result = resolver._git_ls_remote("https://github.com/example/private")

    assert result["ok"] is False
    assert "ghp_secret_123456" not in result["error"]
    assert "password123" not in result["error"]
    assert "sk-live-secret-123456" not in result["error"]
    assert "[REDACTED]" in result["error"]


def test_load_overrides_accepts_utf8_bom(tmp_path):
    overrides = tmp_path / "overrides.json"
    overrides.write_text("\ufeff" + json.dumps({"demo": "https://github.com/example/demo"}), encoding="utf-8")

    assert resolver._load_overrides(overrides) == {"demo": "https://github.com/example/demo"}


def test_resolver_main_writes_redacted_manifest_and_console(monkeypatch, tmp_path, capsys):
    csv_path = tmp_path / "repos.csv"
    output_path = tmp_path / "resolved.json"
    override_path = tmp_path / "overrides.json"
    csv_path.write_text(
        "repo\nhttps://ghp_csv_secret_123456:password123@github.com/example/private.git?token=query-secret-123456\n",
        encoding="utf-8",
    )
    override_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(resolver, "_repo_api_info", lambda url: None)
    monkeypatch.setattr(
        resolver,
        "_git_ls_remote",
        lambda url: {
            "ok": True,
            "error": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "default_branch": "main",
            "latest_commit": "abc123",
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resolve_benchmark_repos.py",
            "--csv",
            str(csv_path),
            "--output",
            str(output_path),
            "--overrides",
            str(override_path),
            "--sleep",
            "0",
        ],
    )

    assert resolver.main() == 0

    console = capsys.readouterr().out
    manifest_text = output_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    combined = console + manifest_text
    assert "ghp_csv_secret_123456" not in combined
    assert "password123" not in combined
    assert "query-secret-123456" not in combined
    assert "abcdefghijklmnopqrstuvwxyz" not in combined
    assert manifest[0]["resolved_github_url"] == "https://github.com/example/private"
    assert manifest[0]["is_valid"] is True


def test_manual_override_url_is_canonicalized_without_credentials(monkeypatch):
    row = {
        "repo_name": "private",
        "nature_category": "",
        "subcategory": "",
        "description": "",
        "expected_count": "",
    }
    monkeypatch.setattr(resolver, "_repo_api_info", lambda url: None)
    monkeypatch.setattr(
        resolver,
        "_git_ls_remote",
        lambda url: {
            "ok": True,
            "error": "",
            "default_branch": "main",
            "latest_commit": "abc123",
        },
    )

    result = resolver._resolve_one(
        row,
        {"private": "https://ghp_override_secret_123456:password123@github.com/example/private.git"},
    )

    assert result["resolved_github_url"] == "https://github.com/example/private"
