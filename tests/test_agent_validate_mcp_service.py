import argparse
import asyncio
import json
import sys

import pytest

from scripts import agent_validate_mcp_service as agent_validate_module
from scripts.agent_validate_mcp_service import build_parser, rank_tool_candidates, result_matches_expectation, select_tool_for_task


class Tool:
    def __init__(self, name, description="", schema=None):
        self.name = name
        self.description = description
        self.inputSchema = schema or {}


def _scenario_args(repo_root, **overrides):
    values = {
        "repo_root": str(repo_root),
        "task": "call leaky",
        "expect_tool": "leaky",
        "arguments": "{}",
        "arguments_file": None,
        "expect_contains": None,
        "require_success": True,
        "require_meaningful_result": True,
        "min_selection_score": 1,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _repo_with_service(tmp_path, source: str = "def create_app():\n    return object()\n"):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text(source, encoding="utf-8")
    return repo_root


def test_select_tool_for_task_uses_task_overlap():
    tools = [
        Tool("natural_list", "Format a list naturally"),
        Tool("naturalsize", "Format byte sizes as human-readable text"),
    ]

    selected = select_tool_for_task(tools, "format 1536 bytes as a natural size")

    assert selected.name == "naturalsize"


def test_select_tool_for_task_weights_tool_name_over_schema_noise():
    tools = [
        Tool("describe", "Describe anything", {"properties": {"bytes": {"type": "integer"}}}),
        Tool("naturalSize", "Format a value", {"properties": {"value": {"type": "integer"}}}),
    ]

    selected = select_tool_for_task(tools, "format 1536 bytes as a natural size")
    candidates = rank_tool_candidates(tools, "format 1536 bytes as a natural size")

    assert selected.name == "naturalSize"
    assert candidates[0]["name"] == "naturalSize"
    assert candidates[0]["matches"]["name"]


def test_select_tool_for_task_rejects_ambiguous_top_score():
    tools = [
        Tool("format_text", "Format text"),
        Tool("format_value", "Format value"),
    ]

    with pytest.raises(ValueError, match="Ambiguous tool selection"):
        select_tool_for_task(tools, "format")


def test_select_tool_for_task_honors_expected_tool():
    tools = [Tool("a"), Tool("b")]

    assert select_tool_for_task(tools, "anything", "b").name == "b"


def test_select_tool_for_task_rejects_missing_expected_tool():
    with pytest.raises(ValueError):
        select_tool_for_task([Tool("a")], "anything", "missing")


def test_result_matches_expectation_checks_success_and_text():
    report = {
        "is_error": False,
        "semantic_success": True,
        "semantic_evidence": True,
        "data": {"success": True, "result": "1.5 kB", "error": None},
    }

    passed, reason = result_matches_expectation(report, expect_contains="kB", require_success=True)

    assert passed is True
    assert reason == ""


def test_result_matches_expectation_rejects_semantic_failure():
    report = {
        "is_error": False,
        "semantic_success": False,
        "data": {"success": False, "result": None, "error": "bad input"},
    }

    passed, reason = result_matches_expectation(report, expect_contains=None, require_success=True)

    assert passed is False
    assert "success=true" in reason


def test_result_matches_expectation_rejects_empty_result_by_default():
    report = {
        "is_error": False,
        "semantic_success": True,
        "semantic_evidence": False,
        "data": {"success": True, "result": None, "error": None},
    }

    passed, reason = result_matches_expectation(report, expect_contains=None, require_success=True)

    assert passed is False
    assert "non-empty result" in reason


def test_result_matches_expectation_rejects_unknown_semantic_success_when_required():
    report = {
        "is_error": False,
        "semantic_success": None,
        "data": "plain text",
    }

    passed, reason = result_matches_expectation(report, expect_contains=None, require_success=True)

    assert passed is False
    assert "success=true" in reason


def test_agent_validation_cli_requires_success_by_default():
    parser = build_parser()

    strict = parser.parse_args(["--repo-root", "repo", "--task", "format bytes"])
    relaxed = parser.parse_args([
        "--repo-root",
        "repo",
        "--task",
        "format bytes",
        "--no-require-success",
        "--no-require-meaningful-result",
    ])

    assert strict.require_success is True
    assert strict.require_meaningful_result is True
    assert relaxed.require_success is False
    assert relaxed.require_meaningful_result is False


def test_agent_validation_reports_missing_fastmcp_dependency(tmp_path, monkeypatch):
    repo_root = _repo_with_service(tmp_path)

    monkeypatch.setitem(sys.modules, "fastmcp", None)

    report = asyncio.run(agent_validate_module._run_scenario(_scenario_args(repo_root)))

    assert report["passed"] is False
    assert report["tool_count"] == 0
    assert report["call"] is None
    assert "FastMCP validation dependency is not installed" in report["errors"][0]


def test_agent_validation_reports_generated_service_import_failure(tmp_path, monkeypatch):
    repo_root = _repo_with_service(tmp_path, "raise RuntimeError('OPENAI_API_KEY=sk-agent-import-secret-123456')\n")

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=object))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(agent_validate_module._run_scenario(_scenario_args(repo_root)))
    payload = json.dumps(report, ensure_ascii=False)

    assert report["passed"] is False
    assert report["tool_count"] == 0
    assert "Unable to import generated MCP service (RuntimeError)" in report["errors"][0]
    assert "sk-agent-import-secret-123456" not in payload


def test_agent_validation_reports_create_app_failure(tmp_path, monkeypatch):
    repo_root = _repo_with_service(
        tmp_path,
        "def create_app():\n"
        "    raise RuntimeError('password=agent-create-secret')\n",
    )

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=object))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(agent_validate_module._run_scenario(_scenario_args(repo_root)))
    payload = json.dumps(report, ensure_ascii=False)

    assert report["passed"] is False
    assert report["tool_count"] == 0
    assert "Generated MCP service create_app() failed (RuntimeError)" in report["errors"][0]
    assert "agent-create-secret" not in payload


def test_agent_validation_reports_client_session_failure(tmp_path, monkeypatch):
    repo_root = _repo_with_service(tmp_path)

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            raise RuntimeError("OPENAI_API_KEY=sk-agent-session-secret-123456")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(agent_validate_module._run_scenario(_scenario_args(repo_root)))
    payload = json.dumps(report, ensure_ascii=False)

    assert report["passed"] is False
    assert report["tool_count"] == 0
    assert report["call"] is None
    assert "FastMCP client session failed (RuntimeError)" in report["errors"][0]
    assert "sk-agent-session-secret-123456" not in payload


def test_agent_validation_reports_list_tools_failure(tmp_path, monkeypatch):
    repo_root = _repo_with_service(tmp_path)

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            raise RuntimeError("password=agent-list-secret")

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(agent_validate_module._run_scenario(_scenario_args(repo_root)))
    payload = json.dumps(report, ensure_ascii=False)

    assert report["passed"] is False
    assert report["tool_count"] == 0
    assert report["call"] is None
    assert "FastMCP list_tools() failed (RuntimeError)" in report["errors"][0]
    assert "agent-list-secret" not in payload


def test_agent_validation_marks_explicit_risky_tool_call(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text(
        "def create_app():\n"
        "    return object()\n",
        encoding="utf-8",
    )

    class FakeResult:
        data = {"success": True, "result": "ok", "error": None}
        structured_content = None
        is_error = False

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [
                Tool(
                    "read_file",
                    "Read a file",
                    {"type": "object", "properties": {"file_path": {"type": "string"}}},
                )
            ]

        async def call_tool(self, _tool_name, _arguments):
            return FakeResult()

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(
        agent_validate_module._run_scenario(
            argparse.Namespace(
                repo_root=str(repo_root),
                task="read a patient data file",
                expect_tool="read_file",
                arguments='{"file_path": "patient_data/example.csv"}',
                arguments_file=None,
                expect_contains=None,
                require_success=True,
                require_meaningful_result=True,
                min_selection_score=1,
            )
        )
    )

    assert report["passed"] is True
    assert report["warnings"]
    assert "explicit call" in report["warnings"][0]
    assert report["call"]["risk_override"] is True
    assert "file_path" in report["call"]["risk_reason"]


def test_agent_validation_run_scenario_redacts_report_object(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeResult:
        data = {
            "success": True,
            "result": "password=hunter2-secret",
            "token": "live-secret-123456",
        }
        structured_content = None
        is_error = False

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [Tool("leaky", "Return a leaky value")]

        async def call_tool(self, _tool_name, _arguments):
            return FakeResult()

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(
        agent_validate_module._run_scenario(
            argparse.Namespace(
                repo_root=str(repo_root),
                task="call leaky",
                expect_tool="leaky",
                arguments='{"api_key": "abc123456789"}',
                arguments_file=None,
                expect_contains="missing text",
                require_success=True,
                require_meaningful_result=True,
                min_selection_score=1,
            )
        )
    )

    payload = json.dumps(report, ensure_ascii=False)
    assert report["passed"] is False
    assert "abc123456789" not in payload
    assert "hunter2-secret" not in payload
    assert "live-secret-123456" not in payload
    assert "[REDACTED]" in payload
    assert report["call"]["arguments"]["api_key"] == "[REDACTED]"
    assert report["call"]["data"]["token"] == "[REDACTED]"
    assert "[REDACTED]" in report["errors"][0]


def test_agent_validation_run_scenario_redacts_call_exceptions(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [Tool("leaky", "Return a leaky value")]

        async def call_tool(self, _tool_name, _arguments):
            raise RuntimeError("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(
        agent_validate_module._run_scenario(
            argparse.Namespace(
                repo_root=str(repo_root),
                task="call leaky",
                expect_tool="leaky",
                arguments="{}",
                arguments_file=None,
                expect_contains=None,
                require_success=True,
                require_meaningful_result=True,
                min_selection_score=1,
            )
        )
    )

    payload = json.dumps(report, ensure_ascii=False)
    assert report["passed"] is False
    assert "abcdefghijklmnopqrstuvwxyz" not in payload
    assert "[REDACTED]" in report["errors"][0]


def test_agent_validation_imports_fresh_mcp_service_for_each_repo(tmp_path, monkeypatch):
    class FakeResult:
        data = {"success": True, "result": "ok", "error": None}
        structured_content = None
        is_error = False

    class FakeClient:
        def __init__(self, app):
            self.app = app

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [Tool(self.app["tool"], "Run the selected tool")]

        async def call_tool(self, _tool_name, _arguments):
            return FakeResult()

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.delitem(sys.modules, "helper", raising=False)

    def make_repo(name):
        repo_root = tmp_path / name
        source_dir = repo_root / "source"
        plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
        source_dir.mkdir(parents=True)
        plugin_dir.mkdir(parents=True)
        (source_dir / "helper.py").write_text(
            f"TOOL_NAME = {name!r}\n",
            encoding="utf-8",
        )
        (plugin_dir / "mcp_service.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "source_path = Path(__file__).resolve().parents[2] / 'source'\n"
            "sys.path.insert(0, str(source_path))\n"
            "import helper\n\n"
            "def create_app():\n"
            "    return {'tool': helper.TOOL_NAME}\n",
            encoding="utf-8",
        )
        return repo_root

    def args_for(repo_root, tool_name):
        return argparse.Namespace(
            repo_root=str(repo_root),
            task=f"run {tool_name}",
            expect_tool=tool_name,
            arguments="{}",
            arguments_file=None,
            expect_contains=None,
            require_success=True,
            require_meaningful_result=True,
            min_selection_score=1,
        )

    first = asyncio.run(agent_validate_module._run_scenario(args_for(make_repo("first"), "first")))
    second = asyncio.run(agent_validate_module._run_scenario(args_for(make_repo("second"), "second")))

    assert first["selected_tool"] == "first"
    assert second["selected_tool"] == "second"
    assert first["passed"] is True
    assert second["passed"] is True


def test_agent_validation_main_redacts_sensitive_report_output(monkeypatch, capsys, tmp_path):
    async def fake_run_scenario(_args):
        print("agent banner GITHUB_TOKEN=ghp_live_secret_123456")
        return {
            "passed": True,
            "repo_root": str(tmp_path),
            "call": {
                "tool": "leaky",
                "arguments": {"api_key": "abc123456789"},
                "data": {"success": True, "result": "password=hunter2-secret", "token": "live-secret-123456"},
            },
            "errors": ["Authorization: Bearer abcdefghijklmnopqrstuvwxyz"],
            "warnings": ["OPENAI_API_KEY=sk-live-secret-123456"],
        }

    monkeypatch.setattr(agent_validate_module, "_run_scenario", fake_run_scenario)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent_validate_mcp_service.py", "--repo-root", str(tmp_path), "--task", "call leaky"],
    )

    exit_code = agent_validate_module.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 0
    assert output.lstrip().startswith("{")
    assert "agent banner" not in output
    assert "agent banner" in captured.err
    assert "abc123456789" not in output
    assert "hunter2-secret" not in output
    assert "live-secret-123456" not in output
    assert "live_secret_123456" not in captured.err
    assert "abcdefghijklmnopqrstuvwxyz" not in output
    assert "sk-live-secret-123456" not in output
    assert "ghp_live_secret_123456" not in captured.err
    assert "[REDACTED]" in captured.err
    assert payload["call"]["arguments"]["api_key"] == "[REDACTED]"
    assert payload["call"]["data"]["token"] == "[REDACTED]"
