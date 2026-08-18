import json
import sys

from scripts import connect_agent as connect_agent_script
from src.tools import connect_mcp


def test_connect_mcp_wrapper_defaults_to_dry_run(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_connect_agent(project, **kwargs):
        calls.append((project, kwargs))
        return {"success": True, "connection": {"client": kwargs["client"], "write": kwargs["write"]}}

    monkeypatch.setattr(connect_mcp, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_mcp.py",
            "--client",
            "cursor",
            "--name",
            "demo",
            "--project",
            str(tmp_path),
        ],
    )

    assert connect_mcp.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["connection"]["write"] is False
    assert calls == [
        (
            str(tmp_path),
            {
                "client": "cursor",
                "server_name": "demo",
                "remote_url": None,
                "python_executable": None,
                "write": False,
                "allow_unvalidated": False,
                "remote": False,
                "config_path": None,
                "probe_remote": False,
                "remote_probe_timeout": 10.0,
            },
        )
    ]


def test_connect_mcp_wrapper_uses_remote_when_url_is_present(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_connect_agent(project, **kwargs):
        calls.append((project, kwargs))
        return {"success": True, "connection": {"client": kwargs["client"], "remote": kwargs["remote"]}}

    monkeypatch.setattr(connect_mcp, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_mcp.py",
            "--client",
            "vscode",
            "--name",
            "demo",
            "--project",
            str(tmp_path),
            "--url",
            "https://example.com",
            "--write",
        ],
    )

    assert connect_mcp.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["connection"]["remote"] is True
    assert calls[0][1]["remote"] is True
    assert calls[0][1]["write"] is True
    assert calls[0][1]["probe_remote"] is False


def test_connect_mcp_wrapper_passes_remote_probe_flags(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_connect_agent(project, **kwargs):
        calls.append((project, kwargs))
        return {"success": True, "connection": {"client": kwargs["client"], "remote": kwargs["remote"]}}

    monkeypatch.setattr(connect_mcp, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_mcp.py",
            "--client",
            "vscode",
            "--project",
            str(tmp_path),
            "--url",
            "https://example.com",
            "--probe-remote",
            "--remote-probe-timeout",
            "3.5",
        ],
    )

    assert connect_mcp.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert calls[0][1]["probe_remote"] is True
    assert calls[0][1]["remote_probe_timeout"] == 3.5


def test_connect_mcp_wrapper_redacts_success_output(monkeypatch, tmp_path, capsys):
    def fake_connect_agent(project, **kwargs):
        return {
            "success": True,
            "profile": {
                "api_key": "sk-live-secret-123456",
                "command": "OPENAI_API_KEY=sk-command-secret-123456 python start_mcp.py",
            },
            "connection": {"header": "Bearer hf_secret_token_123456789"},
        }

    monkeypatch.setattr(connect_mcp, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_mcp.py",
            "--client",
            "cursor",
            "--project",
            str(tmp_path),
        ],
    )

    assert connect_mcp.main() == 0

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["success"] is True
    assert "sk-live-secret-123456" not in raw
    assert "sk-command-secret-123456" not in raw
    assert "hf_secret_token_123456789" not in raw
    assert "[REDACTED]" in raw


def test_connect_mcp_wrapper_redacts_quick_connect_errors(monkeypatch, tmp_path, capsys):
    def fake_connect_agent(project, **kwargs):
        raise connect_mcp.QuickConnectError(
            "install failed: OPENAI_API_KEY=sk-error-secret-123456 password=hunter2-secret"
        )

    monkeypatch.setattr(connect_mcp, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_mcp.py",
            "--client",
            "cursor",
            "--project",
            str(tmp_path),
        ],
    )

    assert connect_mcp.main() == 1

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["success"] is False
    assert "sk-error-secret-123456" not in raw
    assert "hunter2-secret" not in raw
    assert "[REDACTED]" in output["error"]


def test_connect_agent_script_redacts_output(monkeypatch, tmp_path, capsys):
    def fake_connect_agent(repo_root, **kwargs):
        return {
            "success": True,
            "profile": {"token": "ghp_script_secret_123456789"},
            "connection": {"command": "HF_TOKEN=hf_script_secret_123456 python start_mcp.py"},
        }

    monkeypatch.setattr(connect_agent_script, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_agent.py",
            "--repo-root",
            str(tmp_path),
            "--client",
            "generic",
        ],
    )

    assert connect_agent_script.main() == 0

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["success"] is True
    assert "ghp_script_secret_123456789" not in raw
    assert "hf_script_secret_123456" not in raw
    assert "[REDACTED]" in raw


def test_connect_agent_script_passes_remote_probe_flags(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_connect_agent(repo_root, **kwargs):
        calls.append((repo_root, kwargs))
        return {"success": True, "connection": {"client": kwargs["client"]}}

    monkeypatch.setattr(connect_agent_script, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_agent.py",
            "--repo-root",
            str(tmp_path),
            "--client",
            "openai",
            "--remote-url",
            "https://example.com",
            "--probe-remote",
            "--remote-probe-timeout",
            "4.25",
        ],
    )

    assert connect_agent_script.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert calls[0][1]["probe_remote"] is True
    assert calls[0][1]["remote_probe_timeout"] == 4.25


def test_connect_agent_script_redacts_quick_connect_errors(monkeypatch, tmp_path, capsys):
    def fake_connect_agent(repo_root, **kwargs):
        raise connect_agent_script.QuickConnectError(
            "invalid config: GITHUB_TOKEN=ghp_error_secret_123456 password=script-secret"
        )

    monkeypatch.setattr(connect_agent_script, "connect_agent", fake_connect_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_agent.py",
            "--repo-root",
            str(tmp_path),
            "--client",
            "generic",
        ],
    )

    assert connect_agent_script.main() == 1

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["success"] is False
    assert "ghp_error_secret_123456" not in raw
    assert "script-secret" not in raw
    assert "[REDACTED]" in output["error"]


def test_connect_mcp_wrapper_rejects_local_chatgpt(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_mcp.py",
            "--client",
            "chatgpt",
            "--project",
            str(tmp_path),
        ],
    )

    try:
        connect_mcp.main()
    except SystemExit as exc:
        assert str(exc) == "ChatGPT/OpenAI API clients require --url because they use remote HTTPS MCP."
    else:
        raise AssertionError("Expected SystemExit")
