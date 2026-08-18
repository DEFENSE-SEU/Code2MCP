import json
from pathlib import Path

from src.nodes import run_node as run_module


def _run_state(tmp_path):
    repo_root = tmp_path / "repo"
    mcp_output = repo_root / "mcp_output"
    mcp_plugin = mcp_output / "mcp_plugin"
    mcp_plugin.mkdir(parents=True)
    start_mcp = mcp_output / "start_mcp.py"
    start_mcp.write_text("print('start')\n", encoding="utf-8")
    return {
        "repository": {
            "name": "demo",
            "local_paths": {
                "repo_root": str(repo_root),
                "mcp_logs": str(mcp_output / "logs"),
            },
        },
        "plugin": {"files": {"mcp_output/start_mcp.py": str(start_mcp)}},
        "analysis": {},
        "env": {"type": "venv", "exec_prefix": ["python"]},
        "options": {},
    }


def test_run_node_records_registered_tool_count(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["fix_applied"] = True
    state["review_decision"] = "run"
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=3\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 3,
                "tools": ["add"],
                "calls": [{"passed": True, "semantic_success": True, "semantic_evidence": True}],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is True
    assert result["tests"]["plugin"]["tool_count"] == 3
    assert result["tests"]["plugin"]["client_validation"]["passed"] is True
    assert result["tests"]["plugin"]["attempt"] == 1
    assert result["run_result"]["success"] is True
    assert "fix_applied" not in result
    assert "review_decision" not in result
    assert result["run_result"]["attempt"] == 1
    assert result["repair_loop"]["events"][-1]["event"] == "run_passed"
    smoke_script = Path(state["repository"]["local_paths"]["repo_root"]) / "mcp_output" / "tests_smoke" / "mcp_import_min.py"
    smoke_code = smoke_script.read_text(encoding="utf-8")
    assert "create_app()" in smoke_code
    assert "list_tools()" in smoke_code
    assert "asyncio.run(value)" in smoke_code
    assert "registered no tools" in smoke_code
    assert "no_import_available" in smoke_code
    validation_cmd = next(cmd for cmd in commands if any(str(part).endswith("validate_mcp_service.py") for part in cmd))
    assert "--semantic-policy" in validation_cmd
    assert "all" in validation_cmd
    assert "--require-semantic-success" in validation_cmd
    assert "--require-meaningful-result" in validation_cmd
    assert validation_cmd[validation_cmd.index("--max-calls") + 1] == "-1"


def test_run_node_redacts_sensitive_client_validation_report(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["env"]["api_key"] = "env-secret-123456"
    state["plugin"]["token"] = "plugin-secret-123456"

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=1\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 1,
                "tools": ["leaky"],
                "calls": [{
                    "tool": "leaky",
                    "semantic_success": True,
                    "semantic_evidence": True,
                    "data": {"result": "api_key=live-secret-123456", "api_key": "abc12"},
                }],
                "errors": ["Authorization: Bearer abcdefghijklmnopqrstuvwxyz"],
                "warnings": ["password=hunter2-secret"],
                "skipped_auto_calls": [{"reason": "OPENAI_API_KEY=sk-live-secret-123456"}],
            }), "HF_TOKEN=hf-secret-123456"
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)
    payload = json.dumps(result["tests"]["plugin"]["client_validation"], ensure_ascii=False)

    assert "live-secret-123456" not in payload
    assert "abcdefghijklmnopqrstuvwxyz" not in payload
    assert "hunter2-secret" not in payload
    assert "sk-live-secret-123456" not in payload
    assert "abc12" not in payload
    assert "hf-secret-123456" not in result["tests"]["plugin"]["client_validation"]["stderr"]
    assert "[REDACTED]" in payload

    run_log_path = Path(state["repository"]["local_paths"]["mcp_logs"]) / "run_log.json"
    run_log = run_log_path.read_text(encoding="utf-8")
    assert "live-secret-123456" not in run_log
    assert "abcdefghijklmnopqrstuvwxyz" not in run_log
    assert "hunter2-secret" not in run_log
    assert "sk-live-secret-123456" not in run_log
    assert "env-secret-123456" not in run_log
    assert "plugin-secret-123456" not in run_log
    assert "[REDACTED]" in run_log


def test_run_node_honors_explicit_client_call_limit(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["options"]["max_client_calls"] = 2
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=3\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 3,
                "tools": ["a", "b", "c"],
                "calls": [{"passed": True, "semantic_success": True, "semantic_evidence": True}],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["run_result"]["success"] is True
    validation_cmd = next(cmd for cmd in commands if any(str(part).endswith("validate_mcp_service.py") for part in cmd))
    assert validation_cmd[validation_cmd.index("--max-calls") + 1] == "2"


def test_run_node_can_disable_strict_semantic_success_for_diagnostics(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["options"]["client_validation_require_semantic_success"] = False
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=3\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 3,
                "tools": ["a"],
                "calls": [{"passed": True, "semantic_success": True, "semantic_evidence": True}],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["run_result"]["success"] is True
    validation_cmd = next(cmd for cmd in commands if any(str(part).endswith("validate_mcp_service.py") for part in cmd))
    assert "--require-semantic-success" not in validation_cmd


def test_run_node_preserves_explicit_any_semantic_policy_with_required_success(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["options"]["client_validation_semantic_policy"] = "any"
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=2\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 2,
                "tools": ["good", "bad_sample"],
                "calls": [
                    {"tool": "good", "passed": True, "semantic_success": True, "semantic_evidence": True},
                    {"tool": "bad_sample", "passed": False, "semantic_success": None, "semantic_evidence": None},
                ],
                "semantic_policy": "any",
                "require_semantic_success": True,
                "require_meaningful_result": True,
                "warnings": ["bad_sample failed: sample mismatch"],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["run_result"]["success"] is True
    client_validation = result["tests"]["plugin"]["client_validation"]
    assert client_validation["semantic_policy"] == "any"
    assert client_validation["require_semantic_success"] is True
    assert client_validation["require_meaningful_result"] is True
    validation_cmd = next(cmd for cmd in commands if any(str(part).endswith("validate_mcp_service.py") for part in cmd))
    assert validation_cmd[validation_cmd.index("--semantic-policy") + 1] == "any"
    assert "--require-semantic-success" in validation_cmd
    assert "--require-meaningful-result" in validation_cmd


def test_run_node_can_disable_meaningful_result_requirement_for_diagnostics(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["options"]["client_validation_require_meaningful_result"] = False
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=3\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 3,
                "tools": ["a"],
                "calls": [{"passed": True, "semantic_success": True}],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["run_result"]["success"] is True
    validation_cmd = next(cmd for cmd in commands if any(str(part).endswith("validate_mcp_service.py") for part in cmd))
    assert "--require-meaningful-result" not in validation_cmd


def test_run_node_rejects_zero_tool_service(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 1, "", "RuntimeError: FastMCP app registered no tools (count=0)"
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["run_result"]["success"] is False
    assert result["run_result"]["error_type"] == "RuntimeError"
    assert result["errors"][-1]["type"] == "PluginSmokeFailed"
    assert result["repair_loop"]["events"][-1]["event"] == "run_failed"


def test_run_node_rejects_zero_tool_service_even_with_explicit_option(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["options"]["allow_zero_tools"] = True
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=0\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 0,
                "tools": [],
                "calls": [],
                "zero_tools_allowed": True,
                "warnings": [
                    "FastMCP app registered zero tools; --allow-zero-tools records diagnostics only and does not satisfy validation"
                ],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["tool_count"] == 0
    assert result["tests"]["plugin"]["client_validation"]["zero_tools_allowed"] is True
    assert result["run_result"]["success"] is False
    assert "registered zero tools" in result["run_result"]["error"]
    assert result["tests"]["plugin"]["client_validation"]["evidence_errors"][0] == (
        "Client validation report registered zero tools"
    )
    validation_cmd = next(cmd for cmd in commands if any(str(part).endswith("validate_mcp_service.py") for part in cmd))
    assert validation_cmd[validation_cmd.index("--min-tools") + 1] == "0"
    assert "--allow-zero-tools" in validation_cmd
    assert "--require-call" in validation_cmd


def test_run_node_rejects_no_import_available_fallback(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 1, "", "RuntimeError: Generated MCP service only exposes a no_import_available fallback tool"
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["run_result"]["success"] is False
    assert "no_import_available fallback" in result["run_result"]["error"]


def test_run_node_rejects_failed_client_validation(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=2\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 1, json.dumps({
                "passed": False,
                "tool_count": 2,
                "tools": ["fragile"],
                "calls": [
                    {
                        "tool": "fragile",
                        "passed": False,
                        "transport_passed": False,
                        "semantic_success": False,
                        "data": {"success": False, "error": "sample returned success=false"},
                    }
                ],
                "errors": ["fragile returned success=false"],
            }), "INFO:mcp.server.lowlevel.server:Processing request of type CallToolRequest\n"
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["passed"] is False
    assert result["run_result"]["error_type"] == "RuntimeError"
    assert "fragile returned success=false" in result["run_result"]["error"]
    assert "sample returned success=false" in result["run_result"]["error"]
    assert "Processing request" in result["run_result"]["error"]


def test_run_node_rejects_passed_client_report_without_semantic_evidence(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=1\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 1,
                "tools": ["noop"],
                "calls": [{"tool": "noop", "passed": True}],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["passed"] is False
    assert result["run_result"]["success"] is False
    assert "successful semantic tool call" in result["run_result"]["error"]
    assert result["tests"]["plugin"]["client_validation"]["evidence_errors"] == [
        "Client validation report lacks a successful semantic tool call",
        "Client validation report lacks a successful semantic tool call with a non-empty result",
    ]


def test_run_node_rejects_passed_client_report_with_failed_semantic_call(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=1\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tool_count": 1,
                "tools": ["add"],
                "calls": [
                    {
                        "tool": "add",
                        "passed": False,
                        "is_error": False,
                        "semantic_success": True,
                        "semantic_evidence": True,
                    }
                ],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["passed"] is False
    assert result["run_result"]["success"] is False
    assert result["tests"]["plugin"]["client_validation"]["evidence_errors"] == [
        "Client validation report lacks a successful semantic tool call",
        "Client validation report lacks a successful semantic tool call with a non-empty result",
    ]


def test_client_validation_evidence_rejects_error_semantic_call():
    errors = run_module._client_validation_evidence_errors(
        {
            "passed": True,
            "tool_count": 1,
            "calls": [
                {
                    "tool": "add",
                    "passed": True,
                    "is_error": True,
                    "semantic_success": True,
                    "semantic_evidence": True,
                }
            ],
        },
        require_semantic_success=True,
        require_meaningful_result=True,
        allow_zero_tools=False,
    )

    assert errors == [
        "Client validation report lacks a successful semantic tool call",
        "Client validation report lacks a successful semantic tool call with a non-empty result",
    ]


def test_run_node_rejects_passed_client_report_without_tool_count(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=1\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, json.dumps({
                "passed": True,
                "tools": ["add"],
                "calls": [{"tool": "add", "passed": True, "semantic_success": True, "semantic_evidence": True}],
            }), ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["run_result"]["success"] is False
    assert result["tests"]["plugin"]["client_validation"]["evidence_errors"] == [
        "Client validation report did not include a registered tool count"
    ]


def test_run_node_rejects_disabled_client_validation_by_default(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["options"]["client_validation"] = False
    commands = []

    def fake_run(cmd, cwd=None, timeout=300):
        commands.append(cmd)
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=2\n", ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["reason"] == "disabled"
    assert result["run_result"]["success"] is False
    assert "Client validation is disabled" in result["run_result"]["error"]
    assert not any(any(str(part).endswith("validate_mcp_service.py") for part in cmd) for cmd in commands)


def test_run_node_rejects_unparseable_client_validation_output(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=2\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, "not json", ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["passed"] is False
    assert "not valid JSON" in result["run_result"]["error"]


def test_run_node_rejects_non_object_client_validation_json(tmp_path, monkeypatch):
    state = _run_state(tmp_path)

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 0, "OK tools=2\n", ""
        if any(str(part).endswith("validate_mcp_service.py") for part in cmd):
            return 0, "[]", ""
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["tests"]["plugin"]["passed"] is False
    assert result["tests"]["plugin"]["client_validation"]["passed"] is False
    assert "JSON was not an object" in result["run_result"]["error"]


def test_run_node_persists_run_attempt_budget_failure(tmp_path, monkeypatch):
    state = _run_state(tmp_path)
    state["run_attempt_count"] = run_module.MAX_RUN_ATTEMPTS - 1

    def fake_run(cmd, cwd=None, timeout=300):
        if "-c" in cmd:
            return 0, "ok\n", ""
        if str(cmd[-1]).endswith("mcp_import_min.py"):
            return 1, "", "RuntimeError: FastMCP app registered no tools (count=0)"
        return 0, "", ""

    monkeypatch.setattr(run_module, "_run", fake_run)

    result = run_module.run_node(state)

    assert result["workflow_status"] == "failed"
    assert result["status"] == "failed"
    assert "Maximum run attempts reached" in result["error"]
    assert result["repair_loop"]["events"][-1]["event"] == "run_attempt_budget_exhausted"
