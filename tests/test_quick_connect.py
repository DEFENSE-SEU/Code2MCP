import json
import os
import sys
import types
from pathlib import Path
from typing import Optional

import pytest

from src.tools.quick_connect import (
    QuickConnectError,
    _remote_sample_value,
    _remote_sample_value_for_tool,
    _remote_semantic_evidence,
    build_connection_profile,
    connect_agent,
    connect_cursor,
    find_local_python,
    probe_remote_mcp_endpoint,
    validation_status_from_summary,
    write_connection_files,
)


def _repo(tmp_path: Path, *, validated: bool = True, tool_count: Optional[int] = None, warnings: Optional[list[str]] = None) -> Path:
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    resolved_tool_count = tool_count if tool_count is not None else 2 if validated else 0
    client_validation = {"passed": validated, "warnings": warnings or []}
    client_validation["tool_count"] = resolved_tool_count
    if validated:
        client_validation["calls"] = [{"tool": "add", "semantic_success": True, "semantic_evidence": True}]
    summary = {
        "execution": {
            "workflow_status": "validated" if validated else "generated",
            "validation_status": "validated" if validated else "generated_unvalidated",
            "verified": validated,
        },
        "tests": {
            "mcp_plugin": {
                "passed": validated,
                "details": {
                    "tool_count": resolved_tool_count,
                    "client_validation": client_validation,
                },
            }
        },
    }
    (mcp_output / "workflow_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return repo_root


def test_remote_sample_value_uses_valid_misc_annotation():
    assert _remote_sample_value("misc", {"type": "string"}) == "SpaceAfter=No"


def test_remote_sample_value_for_tool_uses_valid_coordinate_strings():
    assert _remote_sample_value_for_tool("parse_latitude", "value", {"type": "string"}) == "N10"
    assert _remote_sample_value_for_tool("parse_longitude", "value", {"type": "string"}) == "N10W010"


def test_build_connection_profile_uses_stdio_entrypoint(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(repo_root, server_name="Demo Service", python_executable="python")

    assert profile["server_name"] == "Demo-Service"
    server = profile["clients"]["generic_mcp_json"]["mcpServers"]["Demo-Service"]
    assert server["command"] == "python"
    assert server["args"] == [str((repo_root / "mcp_output" / "start_mcp.py").resolve())]
    assert server["cwd"] == str(repo_root.resolve())
    assert server["env"]["MCP_TRANSPORT"] == "stdio"
    assert profile["clients"]["vscode"]["servers"]["Demo-Service"]["type"] == "stdio"
    assert profile["clients"]["openai_responses_api"]["tools"][0]["type"] == "mcp"
    assert profile["clients"]["chatgpt_app"]["mode"] == "remote_mcp_only"


def test_find_local_python_uses_generated_env_info(tmp_path):
    repo_root = _repo(tmp_path)
    env_python = repo_root / "demo_123_venv" / "Scripts" / "python.exe"
    env_python.parent.mkdir(parents=True)
    env_python.write_text("", encoding="utf-8")
    (repo_root / "mcp_output" / "env_info.json").write_text(
        json.dumps({"environment": {"exec_prefix": [str(env_python)]}}),
        encoding="utf-8",
    )

    assert find_local_python(repo_root) == str(env_python.resolve())


def test_validation_status_reads_top_level_summary_fields(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps({
            "workflow_status": "validated",
            "validation_status": "validated",
            "verified": True,
            "tests": {
                "mcp_plugin": {
                    "passed": True,
                    "details": {
                        "tool_count": 1,
                        "client_validation": {
                            "passed": True,
                            "tool_count": 1,
                            "calls": [{"tool": "add", "semantic_success": True, "semantic_evidence": True}],
                        },
                    },
                }
            },
        }),
        encoding="utf-8",
    )

    status = validation_status_from_summary(repo_root)

    assert status["workflow_status"] == "validated"
    assert status["validation_status"] == "validated"
    assert status["verified"] is True
    assert status["client_validation_passed"] is True
    assert status["client_call_count"] == 1
    assert status["client_semantic_success_count"] == 1
    assert status["client_meaningful_success_count"] == 1


def test_validation_status_requires_client_tool_count_even_when_summary_has_count(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps({
            "workflow_status": "validated",
            "validation_status": "validated",
            "verified": True,
            "tests": {
                "mcp_plugin": {
                    "passed": True,
                    "details": {
                        "tool_count": 1,
                        "client_validation": {
                            "passed": True,
                            "calls": [{"tool": "add", "semantic_success": True, "semantic_evidence": True}],
                        },
                    },
                }
            },
        }),
        encoding="utf-8",
    )

    status = validation_status_from_summary(repo_root)

    assert status["client_validation_passed"] is False
    assert status["tool_count"] is None
    assert "positive registered tool count" in status["warnings"][0]
    with pytest.raises(QuickConnectError, match="registered tool"):
        connect_agent(repo_root, client="cursor", write=True, config_path=tmp_path / "cursor.json")


def test_validation_status_rejects_stale_validated_summary_after_generation_error(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    summary_path = mcp_output / "workflow_summary.json"
    error_path = mcp_output / "generation_error.json"
    summary_path.write_text(
        json.dumps(
            {
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
                "tests": {
                    "mcp_plugin": {
                        "passed": True,
                        "details": {
                            "tool_count": 1,
                            "client_validation": {
                                "passed": True,
                                "calls": [{"tool": "unsafe", "semantic_success": True, "semantic_evidence": True}],
                            },
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    error_path.write_text(
        json.dumps({"type": "UnsupportedRepository", "message": "No safe targets"}),
        encoding="utf-8",
    )
    os.utime(summary_path, (1000, 1000))
    os.utime(error_path, (2000, 2000))

    status = validation_status_from_summary(repo_root)

    assert status["workflow_status"] == "failed"
    assert status["validation_status"] == "unsupported_audited"
    assert status["verified"] is False
    assert status["client_validation_passed"] is False
    assert status["client_semantic_success_count"] == 0
    assert status["tool_count"] == 0
    assert status["warnings"] == ["No safe targets"]


def test_validation_status_prefers_newer_validated_run_log_over_stale_error(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    logs_dir = mcp_output / "mcp_logs"
    logs_dir.mkdir(parents=True)
    summary_path = mcp_output / "workflow_summary.json"
    error_path = mcp_output / "generation_error.json"
    run_log_path = logs_dir / "run_log.json"
    summary_path.write_text(
        json.dumps(
            {
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
                "tests": {
                    "mcp_plugin": {
                        "passed": True,
                        "details": {
                            "tool_count": 12,
                            "client_validation": {
                                "passed": True,
                                "calls": [{"tool": "old", "semantic_success": True, "semantic_evidence": True}],
                            },
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    error_path.write_text(
        json.dumps({"type": "UnsupportedRepository", "message": "No safe targets"}),
        encoding="utf-8",
    )
    run_log_path.write_text(
        json.dumps(
            {
                "test_result": {
                    "passed": True,
                    "tool_count": 2,
                    "client_validation": {
                        "passed": True,
                        "tool_count": 2,
                        "calls": [
                            {"tool": "lowerstrip", "semantic_success": True, "semantic_evidence": True},
                            {"tool": "strip_punc", "semantic_success": True, "semantic_evidence": True},
                        ],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    os.utime(summary_path, (1000, 1000))
    os.utime(error_path, (2000, 2000))
    os.utime(run_log_path, (3000, 3000))

    status = validation_status_from_summary(repo_root)

    assert status["workflow_status"] == "validated"
    assert status["validation_status"] == "validated"
    assert status["verified"] is True
    assert status["client_validation_passed"] is True
    assert status["client_semantic_success_count"] == 2
    assert status["client_meaningful_success_count"] == 2
    assert status["tool_count"] == 2
    assert status["warnings"] == [
        "workflow_summary.json is older than runtime validation; using newer run_log.json validation evidence."
    ]


def test_validation_status_does_not_trust_run_log_without_meaningful_evidence(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    logs_dir = mcp_output / "mcp_logs"
    logs_dir.mkdir(parents=True)
    summary_path = mcp_output / "workflow_summary.json"
    error_path = mcp_output / "generation_error.json"
    run_log_path = logs_dir / "run_log.json"
    summary_path.write_text(
        json.dumps({"workflow_status": "validated", "validation_status": "validated", "verified": True}),
        encoding="utf-8",
    )
    error_path.write_text(
        json.dumps({"type": "UnsupportedRepository", "message": "No safe targets"}),
        encoding="utf-8",
    )
    run_log_path.write_text(
        json.dumps(
            {
                "test_result": {
                    "passed": True,
                    "tool_count": 1,
                    "client_validation": {
                        "passed": True,
                        "tool_count": 1,
                        "calls": [{"tool": "legacy", "semantic_success": True}],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    os.utime(summary_path, (1000, 1000))
    os.utime(error_path, (2000, 2000))
    os.utime(run_log_path, (3000, 3000))

    status = validation_status_from_summary(repo_root)

    assert status["workflow_status"] == "failed"
    assert status["validation_status"] == "unsupported_audited"
    assert status["client_semantic_success_count"] == 0
    assert status["client_meaningful_success_count"] == 0
    assert status["warnings"] == ["No safe targets"]


def test_validation_status_exposes_top_level_summary_warnings(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps(
            {
                "workflow_status": "failed",
                "validation_status": "unsupported_audited",
                "verified": False,
                "warnings": ["Generation failed before runtime validation"],
            }
        ),
        encoding="utf-8",
    )

    status = validation_status_from_summary(repo_root)

    assert status["warnings"] == ["Generation failed before runtime validation"]


def test_validation_status_prefers_explicit_top_level_workflow_status(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps(
            {
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
                "execution": {"status": "success"},
                "tests": {
                    "mcp_plugin": {
                        "passed": True,
                        "details": {
                            "tool_count": 1,
                            "client_validation": {
                                "passed": True,
                                "tool_count": 1,
                                "calls": [{"tool": "add", "semantic_success": True, "semantic_evidence": True}],
                            },
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    status = validation_status_from_summary(repo_root)

    assert status["workflow_status"] == "validated"
    assert status["validation_status"] == "validated"
    assert status["verified"] is True
    assert status["client_validation_passed"] is True
    assert status["client_semantic_success_count"] == 1
    assert status["client_meaningful_success_count"] == 1


def test_validation_status_accepts_legacy_plugin_test_shape(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps(
            {
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
                "tests": {
                    "plugin": {
                        "passed": True,
                        "tool_count": 1,
                        "client_validation": {
                            "passed": True,
                            "tool_count": 1,
                            "warnings": ["semantic validation ok"],
                            "calls": [{"tool": "add", "semantic_success": True, "semantic_evidence": True}],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    status = validation_status_from_summary(repo_root)
    result = connect_agent(repo_root, client="cursor", write=True, config_path=tmp_path / "cursor" / "mcp.json")

    assert status["workflow_status"] == "validated"
    assert status["mcp_test_passed"] is True
    assert status["client_validation_passed"] is True
    assert status["client_semantic_success_count"] == 1
    assert status["client_meaningful_success_count"] == 1
    assert status["tool_count"] == 1
    assert status["warnings"] == ["semantic validation ok"]
    assert result["success"] is True


def test_write_connection_files_outputs_reusable_configs(tmp_path):
    repo_root = _repo(tmp_path)
    profile = build_connection_profile(repo_root, server_name="demo", python_executable="python")

    files = write_connection_files(profile, repo_root)

    assert Path(files["profile"]).exists()
    assert Path(files["generic_config"]).exists()
    assert Path(files["cursor_config_snippet"]).exists()
    assert Path(files["connection_guide_html"]).exists()
    generic = json.loads(Path(files["generic_config"]).read_text(encoding="utf-8"))
    assert "demo" in generic["mcpServers"]
    guide = Path(files["connection_guide_html"]).read_text(encoding="utf-8")
    assert "ChatGPT App" in guide
    assert "OpenAI Responses API" in guide
    assert "VS Code" in guide
    assert "client-tab" in guide
    assert "Connection map" in guide
    assert "Code2MCP connection console" in guide
    assert "ChatGPT is remote HTTPS MCP only" in guide


def test_connection_guide_warns_when_service_is_unvalidated(tmp_path):
    repo_root = _repo(tmp_path, validated=False)
    profile = build_connection_profile(repo_root, server_name="demo", python_executable="python")

    files = write_connection_files(profile, repo_root)
    guide = Path(files["connection_guide_html"]).read_text(encoding="utf-8")

    assert "Connection warning" in guide
    assert "not passed runtime MCP client validation" in guide


def test_connection_guide_warns_when_zero_tools_are_registered(tmp_path):
    repo_root = _repo(tmp_path, validated=True, tool_count=0)
    profile = build_connection_profile(repo_root, server_name="demo", python_executable="python")

    files = write_connection_files(profile, repo_root)
    guide = Path(files["connection_guide_html"]).read_text(encoding="utf-8")

    assert "Runtime checked, no tools" in guide
    assert "positive registered tool count" in guide


def test_connection_guide_warns_without_semantic_success_call(tmp_path):
    repo_root = _repo(tmp_path, validated=True)
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tests"]["mcp_plugin"]["details"]["client_validation"]["calls"] = [
        {"tool": "add", "semantic_success": False}
    ]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    profile = build_connection_profile(repo_root, server_name="demo", python_executable="python")
    files = write_connection_files(profile, repo_root)
    guide = Path(files["connection_guide_html"]).read_text(encoding="utf-8")

    assert "Runtime checked, no verified call" in guide
    assert "successful semantic tool call" in guide


def test_connection_guide_warns_without_meaningful_result(tmp_path):
    repo_root = _repo(tmp_path, validated=True)
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tests"]["mcp_plugin"]["details"]["client_validation"]["calls"] = [
        {"tool": "noop", "semantic_success": True, "semantic_evidence": False}
    ]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    profile = build_connection_profile(repo_root, server_name="demo", python_executable="python")
    files = write_connection_files(profile, repo_root)
    guide = Path(files["connection_guide_html"]).read_text(encoding="utf-8")

    assert "Runtime checked, no verified call" in guide
    assert "non-empty result" in guide


def test_remote_profile_uses_gpt_server_url_and_vscode_http(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
    )

    assert profile["remote"]["ready"] is False
    assert profile["remote"]["endpoint_checked"] is False
    assert profile["remote"]["endpoint_verified"] is False
    assert "remote endpoint has not been probed" in profile["remote"]["warnings"][0]
    assert profile["clients"]["chatgpt_app"]["server_url"] == "https://example.com/mcp"
    assert profile["clients"]["chatgpt_app"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["tools"][0]["server_url"] == "https://example.com/mcp"
    assert profile["clients"]["vscode_remote"]["servers"]["demo"] == {
        "type": "http",
        "url": "https://example.com/mcp",
    }


def test_remote_profile_marks_payloads_ready_after_remote_probe_validation(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
        remote_validation={
            "checked": True,
            "passed": True,
            "url": "https://example.com/mcp",
            "transport": "http",
            "tool_count": 1,
            "tools": ["add"],
            "semantic_success_count": 1,
            "meaningful_success_count": 1,
            "calls": [
                {
                    "tool": "add",
                    "passed": True,
                    "semantic_success": True,
                    "semantic_evidence": True,
                }
            ],
        },
    )

    assert profile["remote"]["ready"] is True
    assert profile["remote"]["endpoint_checked"] is True
    assert profile["remote"]["endpoint_verified"] is True
    assert profile["clients"]["chatgpt_app"]["ready"] is True
    assert profile["clients"]["openai_responses_api"]["ready"] is True
    assert profile["clients"]["openai_responses_api"]["warnings"] == []


def test_remote_profile_rejects_probe_with_zero_tool_count(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
        remote_validation={
            "checked": True,
            "passed": True,
            "url": "https://example.com/mcp",
            "transport": "http",
            "tool_count": 0,
            "tools": [],
            "semantic_success_count": 1,
            "meaningful_success_count": 1,
            "calls": [
                {
                    "tool": "stale",
                    "passed": True,
                    "semantic_success": True,
                    "semantic_evidence": True,
                }
            ],
        },
    )

    assert profile["remote"]["ready"] is False
    assert profile["remote"]["endpoint_checked"] is True
    assert profile["remote"]["endpoint_verified"] is False
    assert profile["clients"]["chatgpt_app"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["ready"] is False


def test_remote_profile_rejects_probe_without_semantic_call_evidence(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
        remote_validation={
            "checked": True,
            "passed": True,
            "url": "https://example.com/mcp",
            "transport": "http",
            "tool_count": 1,
            "tools": ["add"],
        },
    )

    assert profile["remote"]["ready"] is False
    assert profile["remote"]["endpoint_checked"] is True
    assert profile["remote"]["endpoint_verified"] is False
    assert profile["clients"]["chatgpt_app"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["ready"] is False


def test_probe_remote_mcp_endpoint_lists_remote_tools(monkeypatch):
    class FakeClient:
        def __init__(self, url):
            self.url = url

        async def __aenter__(self):
            assert self.url == "https://example.com/mcp"
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def list_tools(self):
            return [
                types.SimpleNamespace(
                    name="add",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                    },
                )
            ]

        async def call_tool(self, tool_name, arguments):
            assert tool_name == "add"
            assert arguments == {"x": 1, "y": 1}
            return types.SimpleNamespace(data={"success": True, "result": 2}, is_error=False)

    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(Client=FakeClient))

    result = probe_remote_mcp_endpoint("https://example.com", timeout_seconds=1.0)

    assert result["checked"] is True
    assert result["passed"] is True
    assert result["url"] == "https://example.com/mcp"
    assert result["tool_count"] == 1
    assert result["tools"] == ["add"]
    assert result["calls"][0]["tool"] == "add"
    assert result["calls"][0]["semantic_success"] is True
    assert result["calls"][0]["semantic_evidence"] is True


def test_probe_remote_mcp_endpoint_redacts_sensitive_remote_tool_names(monkeypatch):
    class FakeClient:
        def __init__(self, url):
            self.url = url

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def list_tools(self):
            return [types.SimpleNamespace(name="OPENAI_API_KEY=sk-remote-secret-123456")]

    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(Client=FakeClient))

    result = probe_remote_mcp_endpoint("https://example.com", timeout_seconds=1.0)
    payload = json.dumps(result, ensure_ascii=False)

    assert result["passed"] is False
    assert "sk-remote-secret-123456" not in payload
    assert result["tools"] == ["OPENAI_API_KEY=[REDACTED]"]
    assert result["skipped_auto_calls"][0]["tool"] == "OPENAI_API_KEY=[REDACTED]"


def test_probe_remote_mcp_endpoint_requires_meaningful_semantic_result(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def list_tools(self):
            return [types.SimpleNamespace(name="noop", inputSchema={"type": "object", "properties": {}})]

        async def call_tool(self, tool_name, arguments):
            return types.SimpleNamespace(data={"success": True, "result": ""}, is_error=False)

    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(Client=lambda _url: FakeClient()))

    result = probe_remote_mcp_endpoint("https://example.com", timeout_seconds=1.0)

    assert result["passed"] is False
    assert result["calls"][0]["semantic_success"] is True
    assert result["calls"][0]["semantic_evidence"] is False
    assert "meaningful result" in result["errors"][0]


def test_remote_semantic_evidence_rejects_empty_stringified_results():
    assert _remote_semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\":\"   \"}')])") is False
    assert _remote_semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\": [ ]}')])") is False
    assert _remote_semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\": { }}')])") is False


def test_probe_remote_mcp_endpoint_skips_risky_remote_tools(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def list_tools(self):
            return [
                types.SimpleNamespace(
                    name="read_file",
                    inputSchema={
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                    },
                )
            ]

        async def call_tool(self, tool_name, arguments):
            raise AssertionError("risky remote tool should not be called")

    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(Client=lambda _url: FakeClient()))

    result = probe_remote_mcp_endpoint("https://example.com", timeout_seconds=1.0)

    assert result["passed"] is False
    assert result["calls"] == []
    assert result["skipped_auto_calls"][0]["tool"] == "read_file"
    assert "external resource" in result["skipped_auto_calls"][0]["reason"]


def test_remote_profile_does_not_mark_unvalidated_chatgpt_openai_payloads_ready(tmp_path):
    repo_root = _repo(tmp_path, validated=False)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
    )

    assert profile["remote"]["ready"] is False
    assert profile["remote"]["local_validation_required"] is True
    assert profile["clients"]["chatgpt_app"]["server_url"] == "https://example.com/mcp"
    assert profile["clients"]["chatgpt_app"]["ready"] is False
    assert profile["clients"]["chatgpt_app"]["validation_required"] is True
    assert profile["clients"]["openai_responses_api"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["validation_required"] is True
    assert "local runtime MCP client validation" in profile["clients"]["openai_responses_api"]["warnings"][0]


def test_remote_profile_requires_meaningful_semantic_evidence_before_ready(tmp_path):
    repo_root = _repo(tmp_path, validated=True)
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tests"]["mcp_plugin"]["details"]["client_validation"]["calls"] = [
        {"tool": "noop", "semantic_success": True, "semantic_evidence": False}
    ]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
    )

    assert profile["remote"]["ready"] is False
    assert profile["clients"]["chatgpt_app"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["ready"] is False
    assert profile["clients"]["openai_responses_api"]["tools"][0]["server_url"] == "https://example.com/mcp"


def test_connection_guide_warns_when_remote_endpoint_is_not_probed(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
    )
    files = write_connection_files(profile, repo_root)
    guide = Path(files["connection_guide_html"]).read_text(encoding="utf-8")

    assert "remote endpoint has not been probed" in guide


def test_remote_profile_rejects_unsafe_remote_urls(tmp_path):
    repo_root = _repo(tmp_path)

    unsafe_urls = [
        "example.com/mcp",
        "file:///tmp/server",
        "http://example.com/mcp",
        "https://user:password@example.com/mcp",
        "https://example.com/mcp?token=secret-token-123456",
        "https://example.com/mcp#fragment",
    ]

    for remote_url in unsafe_urls:
        with pytest.raises(QuickConnectError):
            build_connection_profile(repo_root, server_name="demo", python_executable="python", remote_url=remote_url)


def test_remote_profile_allows_localhost_http_for_docker_testing(tmp_path):
    repo_root = _repo(tmp_path)

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="http://localhost:7860",
    )

    assert profile["remote"]["server"]["url"] == "http://localhost:7860/mcp"
    assert profile["clients"]["openai_responses_api"]["tools"][0]["server_url"] == "http://localhost:7860/mcp"


def test_openai_responses_example_model_is_configurable(tmp_path, monkeypatch):
    repo_root = _repo(tmp_path)
    monkeypatch.setenv("OPENAI_RESPONSES_MODEL", "gpt-custom")

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
    )

    assert profile["clients"]["openai_responses_api"]["python_example"]["model"] == "gpt-custom"


def test_openai_responses_example_model_does_not_use_codex_default(tmp_path, monkeypatch):
    repo_root = _repo(tmp_path)
    monkeypatch.delenv("OPENAI_RESPONSES_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_CODEX_MODEL", "gpt-5.5")

    profile = build_connection_profile(
        repo_root,
        server_name="demo",
        python_executable="python",
        remote_url="https://example.com/mcp",
    )

    assert profile["clients"]["openai_responses_api"]["python_example"]["model"] == "gpt-5"


def test_connect_agent_refuses_to_write_unvalidated_service(tmp_path):
    repo_root = _repo(tmp_path, validated=False)

    with pytest.raises(QuickConnectError):
        connect_agent(repo_root, client="cursor", write=True)


def test_connect_agent_write_requires_complete_validation_evidence(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps(
            {
                "workflow_status": "validated",
                "validation_status": "generated_unvalidated",
                "verified": False,
                "tests": {"mcp_plugin": {"passed": True, "details": {"tool_count": 1}}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(QuickConnectError):
        connect_agent(repo_root, client="cursor", write=True)


def test_connect_agent_write_requires_client_validation_passed(tmp_path):
    repo_root = tmp_path / "demo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    (mcp_output / "workflow_summary.json").write_text(
        json.dumps(
            {
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
                "tests": {"mcp_plugin": {"passed": True, "details": {"tool_count": 1}}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(QuickConnectError):
        connect_agent(repo_root, client="cursor", write=True)


def test_connect_agent_write_requires_semantic_success_call(tmp_path):
    repo_root = _repo(tmp_path, validated=True)
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tests"]["mcp_plugin"]["details"]["client_validation"]["calls"] = []
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(QuickConnectError, match="successful semantic tool call"):
        connect_agent(repo_root, client="cursor", write=True)


def test_connect_agent_write_requires_meaningful_result(tmp_path):
    repo_root = _repo(tmp_path, validated=True)
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tests"]["mcp_plugin"]["details"]["client_validation"]["calls"] = [
        {"tool": "noop", "semantic_success": True, "semantic_evidence": False}
    ]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(QuickConnectError, match="non-empty result"):
        connect_agent(repo_root, client="cursor", write=True)


def test_connect_agent_write_requires_registered_tools(tmp_path):
    repo_root = _repo(tmp_path, validated=True, tool_count=0)

    with pytest.raises(QuickConnectError, match="registered tool"):
        connect_agent(repo_root, client="cursor", write=True)


def test_connect_cursor_merges_config_and_creates_backup(tmp_path):
    repo_root = _repo(tmp_path)
    profile = build_connection_profile(repo_root, server_name="demo", python_executable="python")
    config_path = tmp_path / "cursor" / "mcp.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({"mcpServers": {"existing": {"command": "old"}}}),
        encoding="utf-8",
    )

    result = connect_cursor(profile, write=True, config_path=config_path)

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert "existing" in updated["mcpServers"]
    assert "demo" in updated["mcpServers"]
    assert result["backup_path"]
    assert Path(result["backup_path"]).exists()


def test_connect_agent_dry_run_still_writes_profile_files(tmp_path):
    repo_root = _repo(tmp_path)

    result = connect_agent(repo_root, client="generic", write=False)

    assert result["success"] is True
    assert result["connection"]["client"] == "generic"
    assert Path(result["files"]["profile"]).exists()


def test_connect_agent_rejects_write_for_copy_only_clients(tmp_path):
    repo_root = _repo(tmp_path)

    with pytest.raises(QuickConnectError, match="only supported for Cursor and Claude Code"):
        connect_agent(repo_root, client="generic", write=True)


def test_connect_agent_outputs_chatgpt_and_openai_api_payloads(tmp_path):
    repo_root = _repo(tmp_path)

    chatgpt = connect_agent(repo_root, client="chatgpt", write=False)
    openai = connect_agent(repo_root, client="openai", write=False)

    assert chatgpt["connection"]["client"] == "chatgpt"
    assert chatgpt["connection"]["mode"] == "remote_mcp_only"
    assert chatgpt["connection"]["ready"] is False
    assert chatgpt["connection"]["requires_remote_url"] is True
    assert chatgpt["connection"]["validation_required"] is True
    assert "remote HTTPS MCP endpoint" in chatgpt["connection"]["warnings"][0]
    assert "server_url" in chatgpt["connection"]
    assert openai["connection"]["client"] == "openai_responses_api"
    assert openai["connection"]["ready"] is False
    assert openai["connection"]["validation_required"] is True
    assert "remote HTTPS MCP endpoint" in openai["connection"]["warnings"][0]
    assert openai["connection"]["tools"][0]["type"] == "mcp"
    assert "mcpServers" not in openai["connection"]


def test_connect_agent_copy_only_local_payload_warns_when_unvalidated(tmp_path):
    repo_root = _repo(tmp_path, validated=False)

    result = connect_agent(repo_root, client="generic", write=False)

    assert result["success"] is True
    assert result["connection"]["ready"] is False
    assert result["connection"]["validation_required"] is True
    assert "Local copy-only payload is unverified" in result["connection"]["warnings"][0]


def test_connect_agent_remote_flag_selects_remote_payloads(tmp_path):
    repo_root = _repo(tmp_path)

    generic = connect_agent(repo_root, client="generic", remote=True, remote_url="https://example.com")
    vscode = connect_agent(repo_root, client="vscode", remote=True, remote_url="https://example.com")
    gemini = connect_agent(repo_root, client="gemini", remote=True, remote_url="https://example.com")
    claude = connect_agent(repo_root, client="claude-code", remote=True, remote_url="https://example.com")

    assert generic["connection"]["mcpServers"]["demo"]["url"] == "https://example.com/mcp"
    assert generic["connection"]["ready"] is False
    assert generic["connection"]["validation_required"] is True
    assert generic["connection"]["endpoint_checked"] is False
    assert generic["connection"]["endpoint_verified"] is False
    assert "remote endpoint has not been probed" in generic["connection"]["warnings"][0]
    assert vscode["connection"]["servers"]["demo"] == {"type": "http", "url": "https://example.com/mcp"}
    assert vscode["connection"]["ready"] is False
    assert "remote endpoint has not been probed" in vscode["connection"]["warnings"][0]
    assert gemini["connection"]["mcpServers"]["demo"]["httpUrl"] == "https://example.com/mcp"
    assert gemini["connection"]["ready"] is False
    assert claude["connection"]["transport"] == "http"
    assert claude["connection"]["ready"] is False
    assert claude["connection"]["command"] == ["claude", "mcp", "add", "--transport", "http", "demo", "https://example.com/mcp"]


def test_connect_agent_remote_copy_payload_uses_verified_probe(tmp_path, monkeypatch):
    repo_root = _repo(tmp_path)
    monkeypatch.setattr(
        "src.tools.quick_connect.probe_remote_mcp_endpoint",
        lambda *_args, **_kwargs: {
            "checked": True,
            "passed": True,
            "url": "https://example.com/mcp",
            "transport": "http",
            "tool_count": 1,
            "tools": ["add"],
            "semantic_success_count": 1,
            "meaningful_success_count": 1,
            "calls": [
                {
                    "tool": "add",
                    "passed": True,
                    "semantic_success": True,
                    "semantic_evidence": True,
                }
            ],
        },
    )

    result = connect_agent(
        repo_root,
        client="generic",
        remote=True,
        remote_url="https://example.com",
        probe_remote=True,
    )

    assert result["connection"]["ready"] is True
    assert result["connection"]["validation_required"] is False
    assert result["connection"]["endpoint_checked"] is True
    assert result["connection"]["endpoint_verified"] is True
    assert "warnings" not in result["connection"]


def test_connect_agent_remote_write_requires_remote_probe(tmp_path):
    repo_root = _repo(tmp_path)

    with pytest.raises(QuickConnectError, match="requires --probe-remote"):
        connect_agent(
            repo_root,
            client="cursor",
            remote=True,
            remote_url="https://example.com",
            write=True,
            config_path=tmp_path / "cursor" / "mcp.json",
        )


def test_connect_agent_remote_write_requires_successful_remote_probe(tmp_path, monkeypatch):
    repo_root = _repo(tmp_path)
    monkeypatch.setattr(
        "src.tools.quick_connect.probe_remote_mcp_endpoint",
        lambda *_args, **_kwargs: {
            "checked": True,
            "passed": False,
            "url": "https://example.com/mcp",
            "transport": "http",
            "tool_count": 0,
            "tools": [],
            "error": "connection refused",
        },
    )

    with pytest.raises(QuickConnectError, match="remote MCP endpoint probe did not pass"):
        connect_agent(
            repo_root,
            client="cursor",
            remote=True,
            remote_url="https://example.com",
            write=True,
            probe_remote=True,
            config_path=tmp_path / "cursor" / "mcp.json",
        )


def test_connect_agent_remote_write_uses_verified_remote_probe(tmp_path, monkeypatch):
    repo_root = _repo(tmp_path)
    config_path = tmp_path / "cursor" / "mcp.json"
    monkeypatch.setattr(
        "src.tools.quick_connect.probe_remote_mcp_endpoint",
        lambda *_args, **_kwargs: {
            "checked": True,
            "passed": True,
            "url": "https://example.com/mcp",
            "transport": "http",
            "tool_count": 1,
            "tools": ["add"],
            "semantic_success_count": 1,
            "meaningful_success_count": 1,
            "calls": [
                {
                    "tool": "add",
                    "passed": True,
                    "semantic_success": True,
                    "semantic_evidence": True,
                }
            ],
        },
    )

    result = connect_agent(
        repo_root,
        client="cursor",
        remote=True,
        remote_url="https://example.com",
        write=True,
        probe_remote=True,
        config_path=config_path,
    )

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert result["connection"]["write"] is True
    assert result["profile"]["remote"]["ready"] is True
    assert updated["mcpServers"]["demo"]["url"] == "https://example.com/mcp"


def test_connect_agent_remote_flag_requires_remote_url(tmp_path):
    repo_root = _repo(tmp_path)

    with pytest.raises(QuickConnectError, match="requires --remote-url"):
        connect_agent(repo_root, client="vscode", remote=True)


def test_validation_status_accepts_utf8_bom_summary(tmp_path):
    repo_root = _repo(tmp_path)
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    raw = summary_path.read_text(encoding="utf-8")
    summary_path.write_text("\ufeff" + raw, encoding="utf-8")

    status = validation_status_from_summary(repo_root)

    assert status["workflow_status"] == "validated"
    assert status["mcp_test_passed"] is True


def test_validation_status_exposes_client_validation_warnings(tmp_path):
    repo_root = _repo(tmp_path, warnings=["semantic validation was skipped"])

    status = validation_status_from_summary(repo_root)

    assert status["warnings"] == ["semantic validation was skipped"]


def test_connection_outputs_redact_sensitive_validation_warnings(tmp_path):
    repo_root = _repo(
        tmp_path,
        warnings=[
            "OPENAI_API_KEY=sk-live-secret-123456",
            "password=hunter2-secret",
        ],
    )

    result = connect_agent(repo_root, client="generic", write=False)

    payload = json.dumps(result, ensure_ascii=False)
    assert "sk-live-secret-123456" not in payload
    assert "hunter2-secret" not in payload
    assert "[REDACTED]" in payload

    for path in result["files"].values():
        text = Path(path).read_text(encoding="utf-8")
        assert "sk-live-secret-123456" not in text
        assert "hunter2-secret" not in text


def test_connect_claude_code_redacts_failed_cli_output(tmp_path, monkeypatch):
    repo_root = _repo(tmp_path)

    class FailedProcess:
        returncode = 1
        stdout = "stdout OPENAI_API_KEY=sk-stdout-secret-123456"
        stderr = "stderr password=hunter2-secret"

    def fake_run(*args, **kwargs):
        return FailedProcess()

    monkeypatch.setattr("src.tools.quick_connect.subprocess.run", fake_run)

    with pytest.raises(QuickConnectError) as exc_info:
        connect_agent(repo_root, client="claude-code", write=True)

    message = str(exc_info.value)
    assert "sk-stdout-secret-123456" not in message
    assert "hunter2-secret" not in message
    assert "[REDACTED]" in message
