import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from scripts import validate_mcp_service as validate_module
from scripts.validate_mcp_service import (
    _alternate_auto_call_arguments,
    _auto_calls_from_tools,
    _is_risky_auto_call,
    _result_to_jsonable,
    _sample_value,
    _sample_value_for_tool,
    _semantic_evidence,
    _semantic_errors_for_policy,
    _semantic_success,
    _transport_ok_for_policy,
    _validate,
)


class Tool:
    def __init__(self, name, schema):
        self.name = name
        self.inputSchema = schema


def test_sample_value_prefers_schema_types_over_empty_defaults():
    assert _sample_value("value", {"anyOf": [{"type": "number"}, {"type": "string"}], "default": ""}) == 1536.0
    assert _sample_value("binary", {"type": "boolean", "default": False}) is False
    assert _sample_value("items", {"type": "array"}) == ["one", "two", "three"]
    assert _sample_value("ii", {"type": "array"}) == [1, 2]
    assert _sample_value("sh", {"type": "array"}) == [1, 2]
    assert _sample_value("strides", {"type": "array"}) == [3, 1]
    assert _sample_value("file_path", {"type": "string"}) == ""
    assert _sample_value("counts", {"type": "string"}) == "test"
    assert _sample_value("counts", {"type": "array"}) == [1, 2, 3]
    assert _sample_value("field", {"type": "array"}) == [1.11, 2.22]
    assert _sample_value("xs", {"type": "array"}) == [1, 2, 3]
    assert _sample_value("code", {"type": "string"}) == "A"
    assert _sample_value("color", {"type": "string"}) == "red"
    assert _sample_value("values", {"type": "string"}) == "test"
    assert _sample_value("name", {"type": "string"}) == "test"
    assert _sample_value("city", {"type": "string"}) == "London"
    assert _sample_value("limit", {"type": "string"}) == "3"
    assert _sample_value("number", {"type": "string"}) == "3"
    assert _sample_value("number", {"type": "integer"}) == 3
    assert _sample_value("n", {"type": "integer"}) == 10
    assert _sample_value("n", {"type": "integer", "default": 0}) == 10
    assert _sample_value("n_sample", {"type": "integer", "default": 0}) == 10
    assert _sample_value("n_samples", {"type": "integer", "default": 0}) == 10
    assert _sample_value("num_samples", {"type": "number", "default": 0.0}) == 10.0
    assert _sample_value("m", {"type": "integer", "default": 0}) == 3
    assert _sample_value("D", {"type": "integer", "default": 0}) == 3
    assert _sample_value("i", {"type": "integer", "default": 0}) == 3
    assert _sample_value("radius", {"type": "integer", "default": 0}) == 3
    assert _sample_value("nbytes", {"type": "integer"}) == 3
    assert _sample_value("nx", {"type": "integer", "default": 0}) == 3
    assert _sample_value("ny", {"type": "integer", "default": 0}) == 3
    assert _sample_value("z1", {"type": "number", "default": 0.0}) == 3.0
    assert _sample_value("z2", {"type": "number", "default": 0.0}) == 3.0
    assert _sample_value("z3", {"type": "number", "default": 0.0}) == 3.0
    assert _sample_value("unit_size", {"type": "number", "default": 0.0}) == 5.0
    assert _sample_value("nom_opt", {"type": "number", "default": 0.0}) == 7.0
    assert _sample_value("nom_max", {"type": "number", "default": 0.0}) == 25.0
    assert _sample_value("threshold", {"type": "number", "default": 0.0}) == 0.1
    assert _sample_value("virtual_offset", {"type": "integer", "default": 0}) == 3
    assert _sample_value("wsize", {"type": "integer", "default": 0}) == 3
    assert _sample_value("seed", {"type": "integer"}) == 1
    assert _sample_value("sfreq", {"type": "number"}) == 1.0
    assert _sample_value("time", {"type": "string"}) == "60"
    assert _sample_value("xmlstring", {"type": "string"}) == "<root>test</root>"
    assert _sample_value("formula", {"type": "string"}) == "H2O"
    assert _sample_value("cov_type", {"type": "string"}) == "HC1"
    assert _sample_value("information_criterion", {"type": "string"}) == "aic"
    assert _sample_value("misc", {"type": "string"}) == "SpaceAfter=No"
    assert _sample_value("norm", {"type": "string"}) == "approximate"
    assert _sample_value("decl_code", {"type": "string"}) == "real(kind=dp), dimension(:, :)"
    assert _sample_value("half_nbw", {"type": "number"}) == 2.5
    assert _sample_value("half_nbw", {"type": "number", "default": 0.0}) == 2.5
    assert _sample_value("Kmax", {"type": "integer"}) == 3
    assert _sample_value("Kmax", {"type": "integer", "default": 0}) == 3
    assert _sample_value("verbose", {"type": "string"}) == "INFO"
    assert _sample_value("theta", {"type": "number"}) == 1.0
    assert _sample_value("nm", {"type": "integer"}) == 3
    assert _sample_value("grant_contributions", {"type": "array"}) == [
        ["grant_a", "user_a", 10.0],
        ["grant_a", "user_b", 20.0],
        ["grant_b", "user_a", 5.0],
    ]
    assert _sample_value("contrib_dict", {"type": "object"}) == {
        "grant_a": {"user_a": 10.0, "user_b": 20.0},
        "grant_b": {"user_a": 5.0},
    }
    assert _sample_value("gene_id_mapping", {"type": "object"}) == {"gene_a": "gene_b", "gene_c": "gene_d"}


def test_sample_value_for_time_series_list_tools():
    assert _sample_value_for_tool("getTimeSeriesInSecs", "ts_list", {"type": "array"}) == [
        "2015-01-01T00:00:00Z",
        "2015-01-01T03:00:00Z",
    ]
    assert _sample_value_for_tool("natural_list", "items", {"type": "array"}) == ["one", "two", "three"]


def test_sample_value_for_coordinate_parsers():
    assert _sample_value_for_tool("parse_latitude", "value", {"type": "string"}) == "N10"
    assert _sample_value_for_tool("parse_longitude", "value", {"type": "string"}) == "N10W010"
    assert _sample_value_for_tool("split_outside_parens", "s", {"type": "string"}) == "a(:,:), b, c(:)"


def test_sample_value_for_seasonal_order_validator():
    assert _sample_value_for_tool("check_seasonal_order", "order", {"type": "integer"}) == [0, 0, 0, 1]


def test_sample_value_for_tool_handles_financial_numeric_sequences():
    assert _sample_value_for_tool("cum_returns", "returns", {"type": "array"}) == [
        0.01,
        -0.02,
        0.015,
        0.005,
        0.012,
    ]
    assert _sample_value_for_tool("get_beta", "r", {"type": "array"}) == [
        0.01,
        -0.02,
        0.015,
        0.005,
        0.012,
    ]
    assert _sample_value_for_tool("get_beta", "b", {"type": "array"}) == [
        0.01,
        -0.02,
        0.015,
        0.005,
        0.012,
    ]
    assert _is_risky_auto_call(Tool("cum_returns", {"properties": {"returns": {"type": "array"}}})) == (False, "")
    assert _is_risky_auto_call(Tool("get_beta", {"properties": {"r": {"type": "array"}, "b": {"type": "array"}}})) == (False, "")


def test_auto_call_allows_iteration_count_params():
    assert _is_risky_auto_call(
        Tool("query", {"properties": {"original_query": {"type": "string"}, "max_iter": {"type": "integer"}}})
    ) == (False, "")

    risky, reason = _is_risky_auto_call(Tool("iterate", {"properties": {"iter": {"type": "object"}}}))

    assert risky is True
    assert reason == "parameter 'iter' appears to require a complex resource"


def test_auto_call_skips_package_extra_metadata_helpers():
    risky, reason = _is_risky_auto_call(
        Tool(
            "get_extra_groups",
            {"properties": {"groups": {"type": "array"}, "exclude_extras": {"type": "array"}}},
        )
    )

    assert risky is True
    assert reason == "package extras metadata helper is not a user-facing tool"


def test_auto_call_skips_internal_zero_arg_helpers():
    assert _is_risky_auto_call(Tool("init_python_session", {"properties": {}})) == (
        True,
        "interactive session initializer is not a user-facing tool",
    )
    assert _is_risky_auto_call(Tool("halt_ordering", {"properties": {}})) == (
        True,
        "dispatch ordering control helper is not a user-facing tool",
    )
    assert _is_risky_auto_call(Tool("sdm_zero", {"properties": {}})) == (
        True,
        "zero-value constructor returns an empty sentinel",
    )


def test_validate_records_zero_tools_but_still_rejects(tmp_path, monkeypatch):
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
            return []

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    base_args = dict(
        repo_root=str(repo_root),
        min_tools=1,
        tool=None,
        arguments="{}",
        call=None,
        call_file=None,
        auto_call=True,
        max_calls=-1,
        include_risky_auto_calls=False,
        require_call=True,
        require_semantic_success=True,
        require_meaningful_result=True,
        semantic_policy="all",
    )

    rejected = asyncio.run(_validate(argparse.Namespace(**base_args, allow_zero_tools=False)))
    accepted = asyncio.run(_validate(argparse.Namespace(**base_args, allow_zero_tools=True)))

    assert rejected["passed"] is False
    assert "FastMCP app registered zero tools; validation requires at least one registered tool" in rejected["errors"]
    assert accepted["passed"] is False
    assert accepted["tool_count"] == 0
    assert accepted["calls"] == []
    assert accepted["zero_tools_allowed"] is True
    assert accepted["warnings"] == [
        "FastMCP app registered zero tools; --allow-zero-tools records diagnostics only and does not satisfy validation"
    ]
    assert "FastMCP app registered zero tools; validation requires at least one registered tool" in accepted["errors"]
    assert "No tool calls were executed" in accepted["errors"]
    assert "No tool call returned semantic success" in accepted["errors"]


def test_require_semantic_success_preserves_any_policy(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeTool:
        def __init__(self, name):
            self.name = name
            self.inputSchema = {"type": "object", "properties": {}}

    class FakeResult:
        is_error = False

        def __init__(self, data):
            self.data = data
            self.structured_content = None

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [FakeTool("good"), FakeTool("bad")]

        async def call_tool(self, name, _arguments):
            if name == "good":
                return FakeResult({"success": True, "result": "ok", "error": None})
            return FakeResult({"success": False, "result": None, "error": "sample mismatch"})

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(
        _validate(
            argparse.Namespace(
                repo_root=str(repo_root),
                min_tools=1,
                tool=None,
                arguments="{}",
                call=None,
                call_file=None,
                auto_call=True,
                max_calls=-1,
                include_risky_auto_calls=False,
                require_call=True,
                require_semantic_success=True,
                require_meaningful_result=True,
                semantic_policy="any",
                allow_zero_tools=False,
            )
        )
    )

    assert report["passed"] is True
    assert report["semantic_policy"] == "any"
    assert report["require_semantic_success"] is True
    assert report["require_meaningful_result"] is True
    assert report["errors"] == []
    assert "bad returned success=false" in report["warnings"]


def test_validate_retries_empty_auto_sample_for_meaningful_result(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeTool:
        name = "fermat_coords"
        inputSchema = {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}}

    class FakeResult:
        is_error = False
        structured_content = None

        def __init__(self, data):
            self.data = data

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [FakeTool()]

        async def call_tool(self, _name, arguments):
            if arguments == {"n": 3}:
                return FakeResult({"success": True, "result": [3], "error": None})
            return FakeResult({"success": True, "result": None, "error": None})

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    report = asyncio.run(
        _validate(
            argparse.Namespace(
                repo_root=str(repo_root),
                min_tools=1,
                tool=None,
                arguments="{}",
                call=None,
                call_file=None,
                auto_call=True,
                max_calls=-1,
                include_risky_auto_calls=False,
                require_call=True,
                require_semantic_success=True,
                require_meaningful_result=True,
                semantic_policy="all",
                allow_zero_tools=False,
            )
        )
    )

    assert report["passed"] is True
    assert report["errors"] == []
    assert report["calls"][0]["arguments"] == {"n": 3}
    assert report["calls"][0]["sample_retries"][0]["arguments"] == {"n": 10}
    assert report["calls"][0]["sample_retries"][1]["arguments"] == {"n": 3}


def test_validate_redacts_auto_sample_retry_errors(tmp_path, monkeypatch, capsys):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeTool:
        name = "n_primes"
        inputSchema = {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}}

    class FakeResult:
        is_error = False
        structured_content = None

        def __init__(self, data):
            self.data = data

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [FakeTool()]

        async def call_tool(self, _name, arguments):
            if arguments == {"n": 10}:
                return FakeResult({"success": True, "result": None, "error": None})
            raise RuntimeError("OPENAI_API_KEY=sk-retry-secret-123456 password=hunter2-secret")

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_mcp_service.py",
            "--repo-root",
            str(repo_root),
            "--auto-call",
            "--require-semantic-success",
            "--require-meaningful-result",
        ],
    )

    exit_code = validate_module.main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "sk-retry-secret-123456" not in output
    assert "hunter2-secret" not in output
    payload = json.loads(output)
    retry_error = payload["calls"][0]["sample_retries"][1]["error"]
    assert "sk-retry-secret-123456" not in retry_error
    assert "hunter2-secret" not in retry_error


def test_validate_imports_fresh_mcp_service_for_each_repo(tmp_path, monkeypatch):
    class FakeTool:
        def __init__(self, name):
            self.name = name
            self.inputSchema = {"type": "object", "properties": {}}

    class FakeClient:
        def __init__(self, app):
            self.app = app

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [FakeTool(self.app["tool"])]

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

    def args_for(repo_root):
        return argparse.Namespace(
            repo_root=str(repo_root),
            min_tools=1,
            tool=None,
            arguments="{}",
            call=None,
            call_file=None,
            auto_call=False,
            max_calls=-1,
            include_risky_auto_calls=False,
            require_call=False,
            require_semantic_success=False,
            require_meaningful_result=False,
            semantic_policy="none",
            allow_zero_tools=False,
        )

    first = asyncio.run(_validate(args_for(make_repo("first"))))
    second = asyncio.run(_validate(args_for(make_repo("second"))))

    assert first["tools"] == ["first"]
    assert second["tools"] == ["second"]


def test_validate_script_help_imports_from_non_project_cwd(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_mcp_service.py"

    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert proc.returncode == 0
    assert "Validate a generated Code2MCP service" in proc.stdout


def test_validate_main_reports_missing_fastmcp_dependency(monkeypatch, capsys, tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "fastmcp", None)
    monkeypatch.setattr(sys, "argv", ["validate_mcp_service.py", "--repo-root", str(repo_root)])

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload["passed"] is False
    assert payload["tool_count"] == 0
    assert payload["calls"] == []
    assert "FastMCP validation dependency is not installed" in payload["errors"][0]


def test_validate_main_reports_generated_service_import_failure(monkeypatch, capsys, tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text(
        "raise RuntimeError('OPENAI_API_KEY=sk-import-secret-123456')\n",
        encoding="utf-8",
    )

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=object))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.setattr(sys, "argv", ["validate_mcp_service.py", "--repo-root", str(repo_root)])

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload["passed"] is False
    assert payload["tool_count"] == 0
    assert payload["calls"] == []
    assert "Unable to import generated MCP service (RuntimeError)" in payload["errors"][0]
    assert "sk-import-secret-123456" not in captured.out


def test_validate_main_reports_create_app_failure(monkeypatch, capsys, tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text(
        "def create_app():\n"
        "    raise RuntimeError('password=create-app-secret')\n",
        encoding="utf-8",
    )

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=object))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.setattr(sys, "argv", ["validate_mcp_service.py", "--repo-root", str(repo_root)])

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload["passed"] is False
    assert payload["tool_count"] == 0
    assert payload["calls"] == []
    assert "Generated MCP service create_app() failed (RuntimeError)" in payload["errors"][0]
    assert "create-app-secret" not in captured.out


def test_validate_main_reports_client_session_failure(monkeypatch, capsys, tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            raise RuntimeError("OPENAI_API_KEY=sk-session-secret-123456")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.setattr(sys, "argv", ["validate_mcp_service.py", "--repo-root", str(repo_root)])

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload["passed"] is False
    assert payload["tool_count"] == 0
    assert payload["calls"] == []
    assert "FastMCP client session failed (RuntimeError)" in payload["errors"][0]
    assert "sk-session-secret-123456" not in captured.out


def test_validate_main_reports_list_tools_failure(monkeypatch, capsys, tmp_path):
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
            raise RuntimeError("password=list-tools-secret")

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.setattr(sys, "argv", ["validate_mcp_service.py", "--repo-root", str(repo_root)])

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload["passed"] is False
    assert payload["tool_count"] == 0
    assert payload["calls"] == []
    assert "FastMCP list_tools() failed (RuntimeError)" in payload["errors"][0]
    assert "list-tools-secret" not in captured.out


def test_validate_main_redacts_call_tool_exceptions(monkeypatch, capsys, tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")

    class FakeTool:
        name = "leaky"
        inputSchema = {"type": "object", "properties": {}}

    class FakeClient:
        def __init__(self, _app):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def list_tools(self):
            return [FakeTool()]

        async def call_tool(self, _tool_name, _arguments):
            raise RuntimeError("OPENAI_API_KEY=sk-call-secret-123456 password=call-tool-secret")

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_mcp_service.py", "--repo-root", str(repo_root), "--tool", "leaky", "--require-call"],
    )

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload["passed"] is False
    assert payload["tool_count"] == 1
    assert payload["calls"][0]["tool"] == "leaky"
    assert "sk-call-secret-123456" not in captured.out
    assert "call-tool-secret" not in captured.out
    assert "sk-call-secret-123456" not in payload["calls"][0]["error"]


def test_validate_main_redacts_sensitive_report_output(monkeypatch, capsys, tmp_path):
    async def fake_validate(_args):
        print("generated banner OPENAI_API_KEY=sk-live-secret-123456")
        return {
            "passed": True,
            "repo_root": str(tmp_path),
            "calls": [
                {
                    "tool": "leaky",
                    "arguments": {"api_key": "abc123456789"},
                    "data": {"success": True, "result": "password=hunter2-secret", "token": "live-secret-123456"},
                }
            ],
            "errors": ["Authorization: Bearer abcdefghijklmnopqrstuvwxyz"],
            "warnings": ["OPENAI_API_KEY=sk-live-secret-123456"],
        }

    monkeypatch.setattr(validate_module, "_validate", fake_validate)
    monkeypatch.setattr(sys, "argv", ["validate_mcp_service.py", "--repo-root", str(tmp_path)])

    exit_code = validate_module.main()
    captured = capsys.readouterr()
    output = captured.out
    payload = json.loads(output)

    assert exit_code == 0
    assert output.lstrip().startswith("{")
    assert "generated banner" not in output
    assert "generated banner" in captured.err
    assert "abc123456789" not in output
    assert "hunter2-secret" not in output
    assert "live-secret-123456" not in output
    assert "live-secret-123456" not in captured.err
    assert "abcdefghijklmnopqrstuvwxyz" not in output
    assert "sk-live-secret-123456" not in output
    assert "sk-live-secret-123456" not in captured.err
    assert "[REDACTED]" in captured.err
    assert payload["calls"][0]["arguments"]["api_key"] == "[REDACTED]"
    assert payload["calls"][0]["data"]["token"] == "[REDACTED]"


def test_validate_flags_explicit_risky_calls_as_policy_overrides(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mcp_service.py").write_text(
        "def create_app():\n"
        "    return object()\n",
        encoding="utf-8",
    )

    class FakeResult:
        data = {"success": True, "result": "ok"}
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
                    {"type": "object", "properties": {"file_path": {"type": "string"}}},
                )
            ]

        async def call_tool(self, _tool_name, _arguments):
            return FakeResult()

    monkeypatch.setitem(sys.modules, "fastmcp", argparse.Namespace(Client=FakeClient))
    monkeypatch.delitem(sys.modules, "mcp_service", raising=False)

    result = asyncio.run(
        _validate(
            argparse.Namespace(
                repo_root=str(repo_root),
                min_tools=1,
                tool="read_file",
                arguments='{"file_path": "patient_data/example.csv"}',
                call=None,
                call_file=None,
                auto_call=False,
                max_calls=-1,
                include_risky_auto_calls=False,
                allow_zero_tools=False,
                require_call=True,
                require_semantic_success=True,
                require_meaningful_result=True,
                semantic_policy="all",
            )
        )
    )

    assert result["passed"] is True
    assert result["calls"][0]["risk_override"] is True
    assert result["calls"][0]["risk_reason"]
    assert "Explicit call to risky tool 'read_file'" in result["warnings"][0]
    assert "auto-call safety policy" in result["warnings"][0]


def test_semantic_success_parses_text_content_wrappers():
    assert _semantic_success('{"success": true, "result": 1}') is True
    assert _semantic_success("CallToolResult(content=[TextContent(text='{\"success\":false,\"error\":\"bad\"}')])") is False


def test_semantic_evidence_requires_non_empty_result():
    assert _semantic_evidence({"success": True, "result": 0, "error": None}) is True
    assert _semantic_evidence({"success": True, "result": False, "error": None}) is True
    assert _semantic_evidence({"success": True, "result": "ok", "error": None}) is True
    assert _semantic_evidence({"success": True, "result": None, "error": None}) is False
    assert _semantic_evidence({"success": True, "result": "", "error": None}) is False
    assert _semantic_evidence({"success": True, "result": [], "error": None}) is False
    assert _semantic_evidence({"success": False, "result": "ok", "error": "bad"}) is False
    assert _semantic_evidence('{"success": true, "result": null}') is False
    assert _semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\":1}')])") is True


def test_semantic_evidence_rejects_empty_stringified_results():
    assert _semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\":\"   \"}')])") is False
    assert _semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\": [ ]}')])") is False
    assert _semantic_evidence("CallToolResult(content=[TextContent(text='{\"success\":true,\"result\": { }}')])") is False


def test_result_to_jsonable_parses_stringified_call_results():
    class Result:
        data = None
        structured_content = None
        is_error = False

        def __str__(self):
            return "CallToolResult(content=[TextContent(text='{\"success\":true,\"result\":1}')])"

    parsed = _result_to_jsonable(Result())

    assert parsed["semantic_success"] is True
    assert parsed["semantic_evidence"] is True


def test_auto_calls_from_tool_schema():
    tools = [
        Tool(
            "naturalsize",
            {
                "type": "object",
                "properties": {
                    "value": {"anyOf": [{"type": "number"}, {"type": "string"}], "default": ""},
                    "binary": {"type": "boolean", "default": False},
                },
            },
        )
    ]

    calls, skipped = _auto_calls_from_tools(tools, 1)

    assert calls == [
        {
            "tool": "naturalsize",
            "arguments": {"value": 1536.0, "binary": False},
            "auto": True,
        }
    ]
    assert skipped == []


def test_auto_calls_sample_city_names_contextually():
    tools = [
        Tool(
            "city",
            {"type": "object", "properties": {"name": {"type": "string"}}},
        ),
        Tool(
            "rename_item",
            {"type": "object", "properties": {"name": {"type": "string"}}},
        ),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [
        {"tool": "city", "arguments": {"name": "London"}, "auto": True},
        {"tool": "rename_item", "arguments": {"name": "test"}, "auto": True},
    ]
    assert skipped == []


def test_auto_call_alternates_retry_number_theory_samples():
    alternates = _alternate_auto_call_arguments(
        "fermat_coords",
        {"n": 10},
        {"n": {"type": "integer", "default": 0}},
    )

    assert {"n": 3} in alternates
    assert {"n": 10} not in alternates


def test_auto_calls_negative_limit_calls_all_safe_tools():
    tools = [
        Tool("format_one", {"type": "object", "properties": {"value": {"type": "number"}}}),
        Tool("format_two", {"type": "object", "properties": {"text": {"type": "string"}}}),
        Tool("read_file", {"type": "object", "properties": {"file_path": {"type": "string"}}}),
    ]

    calls, skipped = _auto_calls_from_tools(tools, -1)

    assert [call["tool"] for call in calls] == ["format_one", "format_two"]
    assert [item["tool"] for item in skipped] == ["read_file"]


def test_transport_policy_allows_auto_sample_failures_after_semantic_success():
    calls = [
        {"tool": "good", "auto": True, "transport_passed": True, "semantic_success": True},
        {"tool": "bad_sample", "auto": True, "transport_passed": False, "semantic_success": None},
    ]

    assert _transport_ok_for_policy(calls, "any") is True
    assert _transport_ok_for_policy(calls, "none") is False
    assert _transport_ok_for_policy(calls, "all") is False


def test_transport_policy_requires_success_before_ignoring_auto_sample_failures():
    calls = [
        {"tool": "bad_sample", "auto": True, "transport_passed": False, "semantic_success": None},
    ]

    assert _transport_ok_for_policy(calls, "any") is False


def test_require_semantic_success_rejects_transport_only_calls():
    calls = [
        {"tool": "plain_text", "transport_passed": True, "semantic_success": None},
    ]

    assert _semantic_errors_for_policy(calls, "all", require_semantic_success=True) == [
        "No tool call returned semantic success"
    ]
    assert _semantic_errors_for_policy(calls, "all", require_semantic_success=False) == []


def test_require_semantic_evidence_rejects_empty_success_result():
    calls = [
        {"tool": "noop", "transport_passed": True, "semantic_success": True, "semantic_evidence": False},
    ]

    assert _semantic_errors_for_policy(calls, "all", require_semantic_evidence=True) == [
        "No tool call returned meaningful semantic evidence"
    ]


def test_require_semantic_evidence_policy_all_rejects_each_empty_success_result():
    calls = [
        {"tool": "good", "transport_passed": True, "semantic_success": True, "semantic_evidence": True},
        {"tool": "noop", "transport_passed": True, "semantic_success": True, "semantic_evidence": False},
        {"tool": "unknown", "transport_passed": True, "semantic_success": None, "semantic_evidence": None},
    ]

    assert _semantic_errors_for_policy(calls, "all", require_semantic_evidence=True) == [
        "Tool calls with success=true but no meaningful semantic evidence: noop"
    ]


def test_auto_calls_skip_stateful_and_resource_tools_by_default():
    tools = [
        Tool("activate", {"type": "object", "properties": {"locale": {"type": "string"}}}),
        Tool("append_to_file", {"type": "object", "properties": {"text": {"type": "string"}}}),
        Tool("get_redis_connection", {"type": "object", "properties": {}}),
        Tool("experiment_exception_hook", {"type": "object", "properties": {}}),
        Tool("set_global_logger_level", {"type": "object", "properties": {"level": {"type": "string"}}}),
        Tool("read_file", {"type": "object", "properties": {"file_path": {"type": "string"}}}),
        Tool("natural_list", {"type": "object", "properties": {"items": {"type": "array"}}}),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [{"tool": "natural_list", "arguments": {"items": ["one", "two", "three"]}, "auto": True}]
    assert [item["tool"] for item in skipped] == [
        "activate",
        "append_to_file",
        "get_redis_connection",
        "experiment_exception_hook",
        "set_global_logger_level",
        "read_file",
    ]


def test_auto_calls_can_include_risky_tools_when_requested():
    tool = Tool("activate", {"type": "object", "properties": {"locale": {"type": "string"}}})

    calls, skipped = _auto_calls_from_tools([tool], 5, include_risky=True)

    assert calls == [{"tool": "activate", "arguments": {"locale": "test"}, "auto": True}]
    assert skipped == []


def test_auto_calls_skip_projection_helpers_by_default():
    tools = [
        Tool(
            "get_projection_from_crs",
            {"type": "object", "properties": {"crs": {"type": "integer"}}},
        )
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == []
    assert skipped == [
        {
            "tool": "get_projection_from_crs",
            "reason": "projection helper often requires optional geospatial runtime",
        }
    ]


def test_auto_calls_skip_output_only_display_helpers_by_default():
    tools = [
        Tool("show_versions", {"type": "object", "properties": {"show_dirs": {"type": "boolean"}}}),
        Tool("print_summary", {"type": "object", "properties": {}}),
        Tool("n_primes", {"type": "object", "properties": {"n": {"type": "integer"}}}),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [{"tool": "n_primes", "arguments": {"n": 10}, "auto": True}]
    skipped_by_tool = {item["tool"]: item["reason"] for item in skipped}
    assert skipped_by_tool["show_versions"] == "tool name contains output-only verb 'show'"
    assert skipped_by_tool["print_summary"] == "tool name contains output-only verb 'print'"


def test_auto_calls_skip_domain_line_parsers_by_default():
    tools = [
        Tool(
            "parse_siteclass_omegas",
            {"type": "object", "properties": {"line": {"type": "string"}, "site_classes": {"type": "string"}}},
        ),
        Tool(
            "parse_freqs",
            {"type": "object", "properties": {"lines": {"type": "string"}, "parameters": {"type": "string"}}},
        ),
        Tool("split_jaspar_id", {"type": "object", "properties": {"id": {"type": "string"}}}),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [{"tool": "split_jaspar_id", "arguments": {"id": "test"}, "auto": True}]
    skipped_by_tool = {item["tool"]: item["reason"] for item in skipped}
    assert skipped_by_tool["parse_siteclass_omegas"] == "parser helper requires domain-specific input text"
    assert skipped_by_tool["parse_freqs"] == "parser helper requires domain-specific input text"


def test_risky_auto_call_detects_resource_params():
    risky, reason = _is_risky_auto_call(Tool("inspect", {"type": "object", "properties": {"file_path": {"type": "string"}}}))

    assert risky is True
    assert "file_path" in reason

    risky, reason = _is_risky_auto_call(Tool("read_tri", {"type": "object", "properties": {"fname_in": {"type": "string"}}}))

    assert risky is True
    assert "fname_in" in reason


def test_auto_calls_do_not_skip_profile_params_as_file_resources():
    tools = [
        Tool("normalize_profile", {"type": "object", "properties": {"profile": {"type": "string"}}}),
        Tool("format_profile_name", {"type": "object", "properties": {"profile_name": {"type": "string"}}}),
        Tool("select_transport", {"type": "object", "properties": {"transport": {"type": "string"}}}),
        Tool("read_module", {"type": "object", "properties": {"modulePath": {"type": "string"}}}),
        Tool("read_file", {"type": "object", "properties": {"file_path": {"type": "string"}}}),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [
        {"tool": "normalize_profile", "arguments": {"profile": "test"}, "auto": True},
        {"tool": "format_profile_name", "arguments": {"profile_name": "test"}, "auto": True},
        {"tool": "select_transport", "arguments": {"transport": "test"}, "auto": True},
        {"tool": "read_module", "arguments": {"modulePath": "test"}, "auto": True},
    ]
    assert skipped == [
        {
            "tool": "read_file",
            "reason": "parameter 'file_path' requires an external resource",
        }
    ]


def test_risky_auto_call_does_not_treat_format_tokens_as_secrets():
    risky, reason = _is_risky_auto_call(
        Tool("clamp", {"type": "object", "properties": {"floor_token": {"type": "string"}}})
    )

    assert risky is False
    assert reason == ""


def test_risky_auto_call_detects_sensitive_token_param():
    risky, reason = _is_risky_auto_call(
        Tool("request", {"type": "object", "properties": {"access_token": {"type": "string"}}})
    )

    assert risky is True
    assert "sensitive" in reason


def test_risky_auto_call_detects_username_param():
    risky, reason = _is_risky_auto_call(
        Tool("lookup_with_api", {"type": "object", "properties": {"username": {"type": "string"}}})
    )

    assert risky is True
    assert "sensitive" in reason


def test_auto_calls_skip_complex_dataframe_params():
    tools = [
        Tool(
            "get_reply_cascade_root_tweet",
            {"type": "object", "properties": {"df": {"type": "string"}}},
        ),
        Tool(
            "combine_and_sort_dataframes",
            {"type": "object", "properties": {"df1": {"type": "string"}, "df2": {"type": "string"}}},
        )
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == []
    assert skipped == [
        {
            "tool": "get_reply_cascade_root_tweet",
            "reason": "parameter 'df' appears to require a complex dataframe",
        },
        {
            "tool": "combine_and_sort_dataframes",
            "reason": "parameter 'df1' appears to require a complex dataframe",
        },
    ]


def test_auto_calls_sample_known_structured_contribution_params():
    tools = [
        Tool("aggregate_contributions", {"type": "object", "properties": {"grant_contributions": {"type": "array"}}}),
        Tool("get_totals_by_pair", {"type": "object", "properties": {"contrib_dict": {"type": "object"}}}),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [
        {
            "tool": "aggregate_contributions",
            "arguments": {
                "grant_contributions": [
                    ["grant_a", "user_a", 10.0],
                    ["grant_a", "user_b", 20.0],
                    ["grant_b", "user_a", 5.0],
                ]
            },
            "auto": True,
        },
        {
            "tool": "get_totals_by_pair",
            "arguments": {
                "contrib_dict": {
                    "grant_a": {"user_a": 10.0, "user_b": 20.0},
                    "grant_b": {"user_a": 5.0},
                }
            },
            "auto": True,
        },
    ]
    assert skipped == []


def test_auto_calls_skip_scientific_object_interfaces():
    tools = [
        Tool(
            "apply_dics",
            {
                "type": "object",
                "properties": {
                    "evoked": {"type": "string"},
                    "filters": {"type": "string"},
                    "verbose": {"type": "string"},
                },
            },
        ),
        Tool(
            "apply_dics_csd",
            {
                "type": "object",
                "properties": {
                    "csd": {"type": "string"},
                    "filters": {"type": "string"},
                },
            },
        ),
        Tool(
            "cosine_score",
            {
                "type": "object",
                "properties": {
                    "stc_true": {"type": "string"},
                    "stc_est": {"type": "string"},
                },
            },
        ),
        Tool(
            "getCentroid",
            {"type": "object", "properties": {"attribute_variants": {"type": "array"}, "comparator": {"type": "string"}}},
        ),
        Tool(
            "backends_dict_from_pkg",
            {"type": "object", "properties": {"entrypoints": {"type": "array"}}},
        ),
        Tool(
            "union_unordered_categorical_and_scalar",
            {"type": "object", "properties": {"categorical_dtypes": {"type": "array"}, "scalars": {"type": "array"}}},
        ),
        Tool(
            "TensorConstant",
            {"type": "object", "properties": {"domain": {"type": "string"}, "count": {"type": "integer"}}},
        ),
        Tool(
            "jump",
            {"type": "object", "properties": {"v": {"type": "string"}, "n": {"type": "integer"}}},
        ),
        Tool(
            "is_cellwise_constant",
            {"type": "object", "properties": {"expr": {"type": "string"}}},
        ),
        Tool(
            "as_ufl",
            {"type": "object", "properties": {"expression": {"type": "string"}}},
        ),
        Tool(
            "as_vector",
            {"type": "object", "properties": {"expressions": {"type": "string"}, "index": {"type": "integer"}}},
        ),
        Tool(
            "expr_equals",
            {"type": "object", "properties": {"other": {"type": "string"}}},
        ),
        Tool(
            "energy_norm",
            {"type": "object", "properties": {"form": {"type": "string"}, "coefficient": {"type": "string"}}},
        ),
        Tool(
            "And",
            {"type": "object", "properties": {"left": {"type": "string"}, "right": {"type": "string"}}},
        ),
        Tool(
            "atan2",
            {"type": "object", "properties": {"f1": {"type": "string"}, "f2": {"type": "string"}}},
        ),
        Tool(
            "Not",
            {"type": "object", "properties": {"condition": {"type": "string"}}},
        ),
        Tool(
            "variable",
            {"type": "object", "properties": {"e": {"type": "string"}}},
        ),
        Tool(
            "unwrap_list_tensor",
            {"type": "object", "properties": {"lt": {"type": "string"}}},
        ),
        Tool(
            "extract_sub_elements",
            {"type": "object", "properties": {"elements": {"type": "string"}}},
        ),
        Tool(
            "grad_to_reference_grad",
            {"type": "object", "properties": {"o": {"type": "string"}, "K": {"type": "string"}}},
        ),
        Tool(
            "compute_integrand_scaling_factor",
            {"type": "object", "properties": {"integral": {"type": "string"}}},
        ),
        Tool(
            "strip_coordinate_derivatives",
            {"type": "object", "properties": {"integrals": {"type": "string"}}},
        ),
        Tool(
            "interpret_ufl_namespace",
            {"type": "object", "properties": {"namespace": {"type": "string"}}},
        ),
        Tool(
            "read_lines_decoded",
            {"type": "object", "properties": {"fn": {"type": "string"}}},
        ),
        Tool(
            "tstr",
            {"type": "object", "properties": {"t": {"type": "string"}, "colsize": {"type": "integer"}}},
        ),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == []
    assert skipped == [
        {"tool": "apply_dics", "reason": "parameter 'evoked' appears to require a complex resource"},
        {"tool": "apply_dics_csd", "reason": "parameter 'csd' appears to require a complex resource"},
        {"tool": "cosine_score", "reason": "parameter 'stc_true' appears to require a complex resource"},
        {"tool": "getCentroid", "reason": "parameter 'attribute_variants' appears to require a complex resource"},
        {"tool": "backends_dict_from_pkg", "reason": "parameter 'entrypoints' appears to require a complex resource"},
        {"tool": "union_unordered_categorical_and_scalar", "reason": "parameter 'categorical_dtypes' appears to require a complex resource"},
        {"tool": "TensorConstant", "reason": "parameter 'domain' appears to require a complex resource"},
        {"tool": "jump", "reason": "parameter 'v' is an untyped scientific parameter"},
        {"tool": "is_cellwise_constant", "reason": "parameter 'expr' appears to require a complex resource"},
        {"tool": "as_ufl", "reason": "parameter 'expression' appears to require a complex resource"},
        {"tool": "as_vector", "reason": "parameter 'expressions' appears to require a complex resource"},
        {"tool": "expr_equals", "reason": "expression helper requires domain-specific objects"},
        {"tool": "energy_norm", "reason": "parameter 'form' appears to require a complex resource"},
        {"tool": "And", "reason": "symbolic expression helper is not safe to auto-call"},
        {"tool": "atan2", "reason": "parameter 'f1' is an untyped scientific parameter"},
        {"tool": "Not", "reason": "symbolic expression helper is not safe to auto-call"},
        {"tool": "variable", "reason": "symbolic expression helper is not safe to auto-call"},
        {"tool": "unwrap_list_tensor", "reason": "parameter 'lt' appears to require a complex resource"},
        {"tool": "extract_sub_elements", "reason": "parameter 'elements' appears to require a complex resource"},
        {"tool": "grad_to_reference_grad", "reason": "parameter 'o' is an untyped scientific parameter"},
        {"tool": "compute_integrand_scaling_factor", "reason": "parameter 'integral' appears to require a complex resource"},
        {"tool": "strip_coordinate_derivatives", "reason": "parameter 'integrals' appears to require a complex resource"},
        {"tool": "interpret_ufl_namespace", "reason": "parameter 'namespace' appears to require a complex resource"},
        {"tool": "read_lines_decoded", "reason": "parameter 'fn' appears to require a complex resource"},
        {"tool": "tstr", "reason": "structured table formatter requires nested tuple input"},
    ]


def test_auto_calls_skip_untyped_scientific_params_but_keep_numeric_params():
    tools = [
        Tool(
            "get_beta",
            {"type": "object", "properties": {"r": {"type": "string"}, "b": {"type": "string"}}},
        ),
        Tool(
            "get_calendar_day",
            {"type": "object", "properties": {"freq": {"type": "string"}}},
        ),
        Tool(
            "guess_plotly_rangebreaks",
            {"type": "object", "properties": {"dt_index": {"type": "string"}}},
        ),
        Tool(
            "parse_args",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "parse_lst20_args",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "assert_dig_allclose",
            {"type": "object", "properties": {"info_py": {"type": "string"}, "info_bin": {"type": "string"}}},
        ),
        Tool(
            "raises",
            {"type": "object", "properties": {"exception": {"type": "string"}}},
        ),
        Tool(
            "if_delegate_has_method",
            {"type": "object", "properties": {"attr": {"type": "string"}}},
        ),
        Tool(
            "add_safe_class",
            {"type": "object", "properties": {"module": {"type": "string"}, "name": {"type": "string"}}},
        ),
        Tool(
            "get_safe_classes",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "requires_openmeeg_mark",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "has_freesurfer",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "get_browser_backend",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "get_brain_class",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "set_cuda_device",
            {"type": "object", "properties": {"device_id": {"type": "string"}, "verbose": {"type": "string"}}},
        ),
        Tool(
            "ingest_historical_data",
            {"type": "object", "properties": {"dataset": {"type": "string"}}},
        ),
        Tool(
            "count_annotations",
            {"type": "object", "properties": {"annotations": {"type": "string"}}},
        ),
        Tool(
            "label_sign_flip",
            {"type": "object", "properties": {"label": {"type": "string"}, "src": {"type": "string"}}},
        ),
        Tool(
            "match_channel_orders",
            {"type": "object", "properties": {"insts": {"type": "string"}, "copy": {"type": "boolean"}}},
        ),
        Tool(
            "get_screen_visual_angle",
            {"type": "object", "properties": {"calibration": {"type": "number"}}},
        ),
        Tool(
            "get_fill_colors",
            {"type": "object", "properties": {"cols": {"type": "string"}, "n_fill": {"type": "integer"}}},
        ),
        Tool(
            "get_current_comp",
            {"type": "object", "properties": {"info": {"type": "string"}}},
        ),
        Tool(
            "check_jieba",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "check_cv",
            {"type": "object", "properties": {"cv": {"type": "string"}}},
        ),
        Tool(
            "guess_horizon",
            {"type": "object", "properties": {"label": {"type": "array"}}},
        ),
        Tool(
            "list_depparse",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "random_select",
            {"type": "object", "properties": {"doc": {"type": "string"}, "size": {"type": "integer"}, "seed": {"type": "integer"}}},
        ),
        Tool(
            "prepare_scores",
            {"type": "object", "properties": {"scores": {"type": "number"}}},
        ),
        Tool(
            "add_peft_args",
            {"type": "object", "properties": {"parser": {"type": "string"}}},
        ),
        Tool(
            "find_constituent_end",
            {"type": "object", "properties": {"gold_sequence": {"type": "string"}, "cur_index": {"type": "integer"}}},
        ),
        Tool(
            "split_trees",
            {"type": "object", "properties": {"all_lines": {"type": "string"}, "splits": {"type": "string"}}},
        ),
        Tool(
            "compare_signature_and_declarations",
            {"type": "object", "properties": {"arg_list": {"type": "string"}, "decls": {"type": "string"}}},
        ),
        Tool(
            "extract_multiline_signature",
            {"type": "object", "properties": {"block": {"type": "string"}}},
        ),
        Tool(
            "get_pyx_arg",
            {"type": "object", "properties": {"arg_list": {"type": "string"}, "decl_map": {"type": "string"}}},
        ),
        Tool(
            "get_meta_data",
            {"type": "object", "properties": {"header": {"type": "string"}, "supplementary_lines": {"type": "string"}}},
        ),
        Tool(
            "parse_lat_col",
            {"type": "object", "properties": {"column": {"type": "string"}, "latitude_column": {"type": "string"}}},
        ),
        Tool(
            "format_comments_and_history",
            {"type": "object", "properties": {"input_header": {"type": "string"}}},
        ),
        Tool(
            "dict_keys_same",
            {"type": "object", "properties": {"list_of_dicts": {"type": "string"}}},
        ),
        Tool(
            "read_struct_skeleton",
            {"type": "object", "properties": {"xdrdata": {"type": "string"}}},
        ),
        Tool(
            "from_helioviewer_project",
            {"type": "object", "properties": {"meta": {"type": "string"}}},
        ),
        Tool(
            "warn_deprecated",
            {"type": "object", "properties": {"msg": {"type": "string"}, "stacklevel": {"type": "integer"}}},
        ),
        Tool(
            "get_node_text",
            {"type": "object", "properties": {"node": {"type": "string"}}},
        ),
        Tool(
            "fix_duplicate_notes",
            {"type": "object", "properties": {"notes_to_add": {"type": "string"}, "docstring": {"type": "string"}}},
        ),
        Tool(
            "find_newest_version",
            {"type": "object", "properties": {"package": {"type": "string"}, "threshold": {"type": "number"}}},
        ),
        Tool(
            "get_min_version",
            {"type": "object", "properties": {"requirement": {"type": "string"}}},
        ),
        Tool(
            "get_package_releases",
            {"type": "object", "properties": {"package": {"type": "string"}}},
        ),
        Tool(
            "output_version_bumps",
            {"type": "object", "properties": {"package": {"type": "string"}, "threshold": {"type": "number"}}},
        ),
        Tool(
            "kegg_get",
            {"type": "object", "properties": {"dbentries": {"type": "string"}, "option": {"type": "string"}}},
        ),
        Tool(
            "get_sprot_raw",
            {"type": "object", "properties": {"id": {"type": "string"}}},
        ),
        Tool(
            "parse",
            {"type": "object", "properties": {"source": {"type": "string"}}},
        ),
        Tool(
            "get_indiv",
            {"type": "object", "properties": {"line": {"type": "string"}}},
        ),
        Tool(
            "mpl_hist_arg",
            {"type": "object", "properties": {"value": {"type": "boolean"}}},
        ),
        Tool(
            "get_daily_bin_group",
            {"type": "object", "properties": {"bench_values": {"type": "string"}}},
        ),
        Tool(
            "check_transform_proc",
            {"type": "object", "properties": {"proc_l": {"type": "string"}}},
        ),
        Tool(
            "build_processor",
            {"type": "object", "properties": {"processor": {"type": "object"}}},
        ),
        Tool(
            "score_stock",
            {"type": "object", "properties": {"stock": {"type": "string"}}},
        ),
        Tool(
            "rainbow",
            {"type": "object", "properties": {"n": {"type": "integer"}}},
        ),
        Tool(
            "randintw",
            {"type": "object", "properties": {"w": {"type": "string"}}},
        ),
        Tool(
            "today",
            {"type": "object", "properties": {"tzinfo": {"type": "string"}}},
        ),
        Tool(
            "within_delta",
            {"type": "object", "properties": {"dt1": {"type": "string"}, "dt2": {"type": "string"}, "delta": {"type": "string"}}},
        ),
        Tool(
            "load",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "deduplicate_results",
            {"type": "object", "properties": {"results": {"type": "array"}}},
        ),
        Tool(
            "split_docs_to_chunks",
            {"type": "object", "properties": {"documents": {"type": "array"}}},
        ),
        Tool(
            "mixture_rvs",
            {"type": "object", "properties": {"prob": {"type": "array"}, "dist": {"type": "array"}}},
        ),
        Tool(
            "handle_data_class_factory",
            {"type": "object", "properties": {"endog": {"type": "array"}, "exog": {"type": "array"}}},
        ),
        Tool(
            "contrast",
            {"type": "object", "properties": {"image": {"type": "string"}, "mask": {"type": "string"}}},
        ),
        Tool(
            "template_ellipsoid",
            {"type": "object", "properties": {"shape": {"type": "string"}}},
        ),
        Tool(
            "chebyshev",
            {"type": "object", "properties": {"h1": {"type": "string"}, "h2": {"type": "string"}}},
        ),
        Tool(
            "discretize_cmap",
            {"type": "object", "properties": {"cmap": {"type": "string"}, "N": {"type": "integer"}}},
        ),
        Tool(
            "uniform_sphere",
            {"type": "object", "properties": {"RAlim": {"type": "string"}, "DEClim": {"type": "string"}, "size": {"type": "integer"}}},
        ),
        Tool(
            "url_content_length",
            {"type": "object", "properties": {"fhandle": {"type": "string"}}},
        ),
        Tool(
            "BgzfBlocks",
            {"type": "object", "properties": {"handle": {"type": "string"}}},
        ),
        Tool(
            "get_prosite_raw",
            {"type": "object", "properties": {"id": {"type": "string"}, "cgi": {"type": "string"}}},
        ),
        Tool(
            "read_char",
            {"type": "object", "properties": {"fid": {"type": "string"}, "count": {"type": "integer"}}},
        ),
        Tool(
            "check_internet",
            {"type": "object", "properties": {"url": {"type": "string"}}},
        ),
        Tool(
            "cdf2prob_grid",
            {"type": "object", "properties": {"cdf": {"type": "string"}, "prepend": {"type": "integer"}}},
        ),
        Tool(
            "table_extend",
            {"type": "object", "properties": {"tables": {"type": "array"}}},
        ),
        Tool(
            "load_pickle",
            {"type": "object", "properties": {"fname": {"type": "string"}}},
        ),
        Tool(
            "corr2cov",
            {"type": "object", "properties": {"corr": {"type": "array"}, "std": {"type": "array"}}},
        ),
        Tool(
            "corr_ar",
            {"type": "object", "properties": {"k_vars": {"type": "integer"}, "ar": {"type": "array"}}},
        ),
        Tool(
            "getbranches",
            {"type": "object", "properties": {"tree": {"type": "string"}}},
        ),
        Tool(
            "convertlabels",
            {"type": "object", "properties": {"ys": {"type": "string"}, "indices": {"type": "array"}}},
        ),
        Tool(
            "anovadict",
            {"type": "object", "properties": {"res": {"type": "object"}}},
        ),
        Tool(
            "data2groupcont",
            {"type": "object", "properties": {"x1": {"type": "string"}, "x2": {"type": "string"}}},
        ),
        Tool(
            "dropname",
            {"type": "object", "properties": {"ss": {"type": "string"}, "li": {"type": "string"}}},
        ),
        Tool(
            "dummy_limits",
            {"type": "object", "properties": {"d": {"type": "string"}}},
        ),
        Tool(
            "breaks_cusumolsresid",
            {"type": "object", "properties": {"resid": {"type": "array"}, "ddof": {"type": "integer"}}},
        ),
        Tool(
            "on_press",
            {"type": "object", "properties": {"key": {"type": "string"}}},
        ),
        Tool(
            "keyboard_listener",
            {"type": "object", "properties": {}},
        ),
        Tool(
            "progress_bar",
            {"type": "object", "properties": {"it": {"type": "string"}, "prefix": {"type": "string"}, "size": {"type": "integer"}, "verbose": {"type": "boolean"}}},
        ),
        Tool(
            "mne_templateMRI",
            {"type": "object", "properties": {"verbose": {"type": "string"}}},
        ),
        Tool(
            "epochs_to_array",
            {"type": "object", "properties": {"epochs": {"type": "string"}}},
        ),
        Tool(
            "fig2img",
            {"type": "object", "properties": {"fig": {"type": "string"}}},
        ),
        Tool(
            "spawn_random_state",
            {"type": "object", "properties": {"rng": {"type": "string"}, "n_children": {"type": "integer"}}},
        ),
        Tool(
            "check_random_state_children",
            {"type": "object", "properties": {"random_state_parent": {"type": "string"}, "random_state_children": {"type": "string"}}},
        ),
        Tool(
            "eog_features",
            {"type": "object", "properties": {"eog_cleaned": {"type": "string"}, "peaks": {"type": "string"}, "sampling_rate": {"type": "integer"}}},
        ),
        Tool(
            "signal_synchrony",
            {"type": "object", "properties": {"signal1": {"type": "string"}, "signal2": {"type": "string"}}},
        ),
        Tool(
            "find_closest",
            {"type": "object", "properties": {"closest_to": {"type": "string"}, "list_to_search_in": {"type": "string"}}},
        ),
        Tool(
            "compare_xml_strings",
            {"type": "object", "properties": {"doc1": {"type": "string"}, "doc2": {"type": "string"}}},
        ),
        Tool(
            "add",
            {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
        ),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == [{"tool": "add", "arguments": {"a": 1.0, "b": 1.0}, "auto": True}]
    skipped_by_tool = {item["tool"]: item["reason"] for item in skipped}
    assert skipped_by_tool["get_beta"] == "parameter 'r' is an untyped scientific parameter"
    assert skipped_by_tool["get_calendar_day"] == "tool name contains 'calendar'"
    assert skipped_by_tool["guess_plotly_rangebreaks"] in {"tool name contains 'plot'", "tool name contains 'plotly'"}
    assert skipped_by_tool["parse_args"] == "tool name appears to parse command-line arguments"
    assert skipped_by_tool["parse_lst20_args"] == "tool name appears to parse command-line arguments"
    assert skipped_by_tool["assert_dig_allclose"] == "assertion helper is not a user-facing tool"
    assert skipped_by_tool["raises"] == "test exception context helper is not a user-facing tool"
    assert skipped_by_tool["if_delegate_has_method"] == "delegation decorator helper is not a user-facing tool"
    assert skipped_by_tool["add_safe_class"] == "safe-class whitelist helper mutates security policy"
    assert skipped_by_tool["get_safe_classes"] == "safe-class whitelist helper mutates security policy"
    assert skipped_by_tool["requires_openmeeg_mark"] == "test requirement marker is not a user-facing tool"
    assert skipped_by_tool["has_freesurfer"] == "zero-argument availability probe is not a user-facing tool"
    assert skipped_by_tool["get_browser_backend"] == "backend probe is not a user-facing tool"
    assert skipped_by_tool["get_brain_class"] == "class getter is not a user-facing tool"
    assert skipped_by_tool["set_cuda_device"] == "state-changing setter is not a user-facing tool"
    assert skipped_by_tool["ingest_historical_data"] == "data ingestion helper is not safe to auto-call"
    assert skipped_by_tool["count_annotations"] == "parameter 'annotations' appears to require a complex resource"
    assert skipped_by_tool["label_sign_flip"] == "parameter 'src' appears to require a complex resource"
    assert skipped_by_tool["match_channel_orders"] == "parameter 'insts' appears to require a complex resource"
    assert skipped_by_tool["get_screen_visual_angle"] == "parameter 'calibration' appears to require a complex resource"
    assert skipped_by_tool["get_fill_colors"] == "parameter 'cols' appears to require a complex resource"
    assert skipped_by_tool["get_current_comp"] == "parameter 'info' appears to require a complex resource"
    assert skipped_by_tool["check_jieba"] == "zero-argument check tool is likely an environment probe"
    assert skipped_by_tool["check_cv"] == "parameter 'cv' appears to require a complex resource"
    assert skipped_by_tool["guess_horizon"] == "horizon inference requires initialized domain data"
    assert skipped_by_tool["list_depparse"] == "zero-argument list tool is likely an external resource probe"
    assert skipped_by_tool["random_select"] == "parameter 'doc' appears to require a complex resource"
    assert skipped_by_tool["prepare_scores"] == "parameter 'scores' appears to require a complex resource"
    assert skipped_by_tool["add_peft_args"] == "parameter 'parser' appears to require a complex resource"
    assert skipped_by_tool["find_constituent_end"] == "parameter 'gold_sequence' appears to require a complex resource"
    assert skipped_by_tool["split_trees"] == "parameter 'all_lines' appears to require a complex resource"
    assert skipped_by_tool["compare_signature_and_declarations"] == "parameter 'arg_list' appears to require a complex resource"
    assert skipped_by_tool["extract_multiline_signature"] == "parameter 'block' appears to require a complex resource"
    assert skipped_by_tool["get_pyx_arg"] == "parameter 'arg_list' appears to require a complex resource"
    assert skipped_by_tool["get_meta_data"] == "parameter 'header' appears to require a complex resource"
    assert skipped_by_tool["parse_lat_col"] == "parameter 'column' appears to require a complex resource"
    assert skipped_by_tool["format_comments_and_history"] == "parameter 'input_header' appears to require a complex resource"
    assert skipped_by_tool["dict_keys_same"] == "parameter 'list_of_dicts' appears to require a complex resource"
    assert skipped_by_tool["read_struct_skeleton"] == "parameter 'xdrdata' appears to require a complex resource"
    assert skipped_by_tool["from_helioviewer_project"] == "parameter 'meta' appears to require a complex resource"
    assert skipped_by_tool["warn_deprecated"] == "warning helper is not a user-facing tool"
    assert skipped_by_tool["get_node_text"] == "parameter 'node' appears to require a complex resource"
    assert skipped_by_tool["fix_duplicate_notes"] == "parameter 'notes_to_add' appears to require a complex resource"
    assert skipped_by_tool["find_newest_version"] == "version lookup is likely to require an external package registry"
    assert skipped_by_tool["get_min_version"] == "parameter 'requirement' appears to require a complex resource"
    assert skipped_by_tool["get_package_releases"] == "dependency metadata lookup is likely to require an external package registry"
    assert skipped_by_tool["output_version_bumps"] == "package version lookup is likely to require external metadata"
    assert skipped_by_tool["kegg_get"] == "tool name appears to query a remote database or service"
    assert skipped_by_tool["get_sprot_raw"] == "tool name appears to query a remote database or service"
    assert skipped_by_tool["parse"] == "parameter 'source' appears to require a complex resource"
    assert skipped_by_tool["get_indiv"] == "single-line record parser requires domain-specific input"
    assert skipped_by_tool["mpl_hist_arg"] == "tool name contains 'mpl'"
    assert skipped_by_tool["get_daily_bin_group"] == "parameter 'bench_values' appears to require a complex resource"
    assert skipped_by_tool["check_transform_proc"] in {"tool name contains 'proc'", "tool name contains 'transform'"}
    assert skipped_by_tool["build_processor"] in {"tool name contains 'proc'", "tool name contains 'processor'"}
    assert skipped_by_tool["score_stock"] == "parameter 'stock' appears to require a complex resource"
    assert skipped_by_tool["rainbow"] == "tool name contains 'rainbow'"
    assert skipped_by_tool["randintw"] == "parameter 'w' is an untyped scientific parameter"
    assert skipped_by_tool["today"] == "parameter 'tzinfo' appears to require a complex resource"
    assert skipped_by_tool["within_delta"] == "parameter 'dt1' appears to require a complex resource"
    assert skipped_by_tool["load"] == "tool name contains 'load'"
    assert skipped_by_tool["deduplicate_results"] == "parameter 'results' appears to require a complex resource"
    assert skipped_by_tool["split_docs_to_chunks"] == "parameter 'documents' appears to require a complex resource"
    assert skipped_by_tool["mixture_rvs"] == "parameter 'prob' appears to require a complex resource"
    assert skipped_by_tool["handle_data_class_factory"] == "parameter 'endog' appears to require a complex resource"
    assert skipped_by_tool["contrast"] == "parameter 'image' appears to require a complex resource"
    assert skipped_by_tool["template_ellipsoid"] == "parameter 'shape' appears to require a complex resource"
    assert skipped_by_tool["chebyshev"] == "parameter 'h1' appears to require a complex histogram"
    assert skipped_by_tool["discretize_cmap"] == "parameter 'cmap' appears to require a complex resource"
    assert skipped_by_tool["uniform_sphere"] == "parameter 'RAlim' appears to require a complex resource"
    assert skipped_by_tool["url_content_length"] == "parameter 'fhandle' appears to require a complex resource"
    assert skipped_by_tool["BgzfBlocks"] == "parameter 'handle' appears to require a complex resource"
    assert skipped_by_tool["get_prosite_raw"] == "tool name appears to query a remote database or service"
    assert skipped_by_tool["read_char"] == "parameter 'fid' appears to require a complex resource"
    assert skipped_by_tool["check_internet"] == "parameter 'url' requires an external resource"
    assert skipped_by_tool["cdf2prob_grid"] == "parameter 'cdf' appears to require a complex resource"
    assert skipped_by_tool["table_extend"] == "parameter 'tables' appears to require a complex resource"
    assert skipped_by_tool["load_pickle"] in {"tool name contains 'load'", "tool name contains 'pickle'"}
    assert skipped_by_tool["corr2cov"] == "parameter 'corr' appears to require a complex resource"
    assert skipped_by_tool["corr_ar"] == "parameter 'ar' appears to require a complex resource"
    assert skipped_by_tool["getbranches"] == "parameter 'tree' appears to require a complex resource"
    assert skipped_by_tool["convertlabels"] == "parameter 'ys' appears to require a complex resource"
    assert skipped_by_tool["anovadict"] == "parameter 'res' appears to require a complex resource"
    assert skipped_by_tool["data2groupcont"] == "parameter 'x1' appears to require a complex resource"
    assert skipped_by_tool["dropname"] == "parameter 'li' appears to require a complex resource"
    assert skipped_by_tool["dummy_limits"] == "tool name contains 'dummy'"
    assert skipped_by_tool["breaks_cusumolsresid"] == "parameter 'resid' appears to require a complex resource"
    assert skipped_by_tool["on_press"] == "tool name contains 'on_press'"
    assert skipped_by_tool["keyboard_listener"] in {"tool name contains 'keyboard'", "tool name contains 'listener'"}
    assert skipped_by_tool["progress_bar"] == "progress helper is not a user-facing tool"
    assert skipped_by_tool["mne_templateMRI"] == "optional MNE integration helper requires external runtime"
    assert skipped_by_tool["epochs_to_array"] == "parameter 'epochs' appears to require a complex resource"
    assert skipped_by_tool["fig2img"] == "parameter 'fig' appears to require a complex resource"
    assert skipped_by_tool["spawn_random_state"] == "parameter 'rng' appears to require a complex resource"
    assert skipped_by_tool["check_random_state_children"] == "parameter 'random_state_parent' appears to require a complex resource"
    assert skipped_by_tool["eog_features"] == "parameter 'eog_cleaned' appears to require a signal-like array"
    assert skipped_by_tool["signal_synchrony"] == "parameter 'signal1' appears to require a signal-like array"
    assert skipped_by_tool["find_closest"] == "parameter 'list_to_search_in' appears to require a list-like resource"
    assert skipped_by_tool["compare_xml_strings"] == "parameter 'doc1' appears to require a complex document"


def test_auto_calls_skip_ambiguous_scientific_params():
    tools = [
        Tool(
            "get_beta",
            {"type": "object", "properties": {"r": {"type": "string"}, "b": {"type": "string"}}},
        ),
        Tool(
            "lookup_position",
            {"type": "object", "properties": {"positions": {"type": "array"}}},
        ),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == []
    assert skipped == [
        {
            "tool": "get_beta",
            "reason": "parameter 'r' is an untyped scientific parameter",
        },
        {
            "tool": "lookup_position",
            "reason": "parameter 'positions' appears to require a complex resource",
        },
    ]


def test_auto_calls_skip_opaque_payload_objects():
    tools = [
        Tool(
            "build_reconstruction",
            {"type": "object", "properties": {"payload": {"type": "object"}}},
        )
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == []
    assert skipped == [
        {
            "tool": "build_reconstruction",
            "reason": "tool name contains 'build'",
        }
    ]


def test_auto_calls_skip_domain_object_action_params():
    tools = [
        Tool(
            "serialize_action",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "molecule_store": {"type": "string"},
                },
            },
        ),
        Tool(
            "describe_molecule",
            {"type": "object", "properties": {"molecule": {"type": "string"}}},
        ),
    ]

    calls, skipped = _auto_calls_from_tools(tools, 5)

    assert calls == []
    assert skipped == [
        {
            "tool": "serialize_action",
            "reason": "parameter 'action' appears to require a complex resource",
        },
        {
            "tool": "describe_molecule",
            "reason": "parameter 'molecule' appears to require a complex resource",
        },
    ]


def test_auto_calls_sample_detailed_object_schema():
    tools = [
        Tool(
            "format_options",
            {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "enabled": {"type": "boolean"},
                        },
                    }
                },
            },
        )
    ]

    calls, skipped = _auto_calls_from_tools(tools, 1)

    assert calls == [
        {
            "tool": "format_options",
            "arguments": {"options": {"name": "test", "enabled": False}},
            "auto": True,
        }
    ]
    assert skipped == []
