import sys

import pytest

import src.nodes.review_node as review_module
from src.workflow import route_after_review
from src.nodes.review_node import (
    _apply_deterministic_fixes,
    _extract_code_or_plain,
    _extract_file_path,
    _fix_error_with_llm,
    _intelligent_error_analysis,
    _repair_change_is_scoped,
    _repair_system_prompt,
    _repair_user_prompt,
    _response_declines_fix,
    _post_repair_service_precheck,
    _safe_generated_file_path,
    _validate_repaired_file_whole,
)


def test_safe_generated_file_path_stays_inside_mcp_output(tmp_path):
    repo_root = tmp_path / "repo"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)

    allowed = _safe_generated_file_path(str(repo_root), "mcp_output/mcp_plugin/mcp_service.py")
    assert allowed is not None
    assert allowed.startswith(str(mcp_output))

    assert _safe_generated_file_path(str(repo_root), "../secret.txt") is None
    assert _safe_generated_file_path(str(repo_root), "source/module.py") is None
    assert _safe_generated_file_path(str(repo_root), str(tmp_path / "outside.py")) is None
    assert _safe_generated_file_path(str(repo_root), "file:///tmp/mcp_output/mcp_service.py") is None
    assert _safe_generated_file_path(str(repo_root), r"\\server\share\mcp_output\mcp_service.py") is None


def test_safe_generated_file_path_rejects_symlink_escape(tmp_path):
    repo_root = tmp_path / "repo"
    mcp_output = repo_root / "mcp_output"
    outside = tmp_path / "outside"
    mcp_output.mkdir(parents=True)
    outside.mkdir()
    link = mcp_output / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert _safe_generated_file_path(str(repo_root), "mcp_output/linked/escape.py") is None


def test_file_path_protocol_is_case_insensitive():
    response = "file path: mcp_output/mcp_plugin/mcp_service.py\nprint('ok')\n"

    assert _extract_file_path(response) == "mcp_output/mcp_plugin/mcp_service.py"
    assert _extract_code_or_plain(response) == "print('ok')"


def test_review_fail_action_stops_workflow(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {"success": False, "error": "unsafe dependency failure", "stderr": ""},
        "status": "running",
        "workflow_status": "running",
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "fail", "summary": "requires unsafe source changes"},
    )

    result = review_module.review_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["loop_summary"]["fixes"] == "not_safe_to_fix"


def test_review_regenerate_prepares_persistent_retry_state(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {
            "success": False,
            "attempt": 3,
            "error": "No tool call returned semantic success",
            "stderr": "",
            "client_validation": {
                "calls": [
                    {"tool": "bad_tool", "semantic_success": False, "transport_passed": True, "passed": False},
                    {"tool": "good_tool", "semantic_success": True, "transport_passed": True, "passed": True},
                ]
            },
        },
        "tests": {"plugin": {"passed": False, "attempt": 3}},
        "generation_retry_count": 0,
        "fix_retry_count": 2,
        "previous_run_results": [],
        "status": "running",
        "workflow_status": "running",
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "regenerate", "summary": "structural wrapper mismatch", "confidence": 0.9},
    )

    result = review_module.review_node(state)

    assert result["review_decision"] == "regenerate"
    assert result["regeneration_prepared"] is True
    assert result["generation_retry_count"] == 1
    assert result["fix_retry_count"] == 0
    assert "run_result" not in result
    assert result["previous_run_results"][0]["attempt"] == 3
    assert result["runtime_rejected_tools"] == [
        {"name": "bad_tool", "reason": "regenerate", "run_attempt": 3}
    ]
    assert route_after_review(result) == "generate"


def test_review_regeneration_rejects_empty_semantic_evidence(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {
            "success": False,
            "attempt": 2,
            "error": "No tool call returned meaningful semantic evidence",
            "stderr": "",
            "client_validation": {
                "errors": ["No tool call returned meaningful semantic evidence"],
                "calls": [
                    {
                        "tool": "noop",
                        "semantic_success": True,
                        "semantic_evidence": False,
                        "transport_passed": True,
                        "passed": True,
                    }
                ],
            },
        },
        "tests": {"plugin": {"passed": False, "attempt": 2}},
        "generation_retry_count": 0,
        "fix_retry_count": 0,
        "previous_run_results": [],
        "status": "running",
        "workflow_status": "running",
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "regenerate", "summary": "empty semantic result", "confidence": 0.9},
    )

    result = review_module.review_node(state)

    assert result["runtime_rejected_tools"] == [
        {"name": "noop", "reason": "regenerate", "run_attempt": 2}
    ]


def test_review_regeneration_budget_fails_in_node(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {"success": False, "attempt": 7, "error": "still broken", "stderr": ""},
        "tests": {"plugin": {"passed": False, "attempt": 7}},
        "generation_retry_count": review_module.MAX_GENERATION_RETRIES,
        "fix_retry_count": 0,
        "status": "running",
        "workflow_status": "running",
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "regenerate", "summary": "structural wrapper mismatch", "confidence": 0.9},
    )

    result = review_module.review_node(state)

    assert result["workflow_status"] == "failed"
    assert "Maximum regeneration attempts reached" in result["error"]


def test_review_without_run_evidence_fails(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "tests": {},
        "status": "running",
        "workflow_status": "running",
    }

    result = review_module.review_node(state)

    assert result["workflow_status"] == "failed"
    assert result["review_decision"] == "fail"
    assert result["errors"][-1]["type"] == "MissingRunEvidence"


def test_error_analysis_uses_heuristic_when_review_llm_disabled(monkeypatch):
    monkeypatch.delenv("CODE2MCP_REVIEW_LLM", raising=False)
    monkeypatch.setattr(
        review_module,
        "get_llm_service",
        lambda: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    result = _intelligent_error_analysis({
        "run_result": {
            "success": False,
            "error": "Runtime error: sample returned success=false",
            "stderr": "",
        }
    })

    assert result["source"] == "heuristic"
    assert result["llm_enabled"] is False


def test_review_successful_fix_archives_failed_run_and_requests_rerun(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {"success": False, "attempt": 9, "error": "SyntaxError", "stderr": ""},
        "tests": {"plugin": {"passed": False, "attempt": 9}},
        "status": "running",
        "workflow_status": "running",
        "previous_run_results": [],
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "fix_directly", "summary": "syntax", "confidence": 0.9},
    )
    monkeypatch.setattr(review_module, "_apply_incremental_fixes", lambda *_: True)

    result = review_module.review_node(state)

    assert result["review_decision"] == "run"
    assert result["fix_applied"] is True
    assert "run_result" not in result
    assert "plugin" not in result["tests"]
    assert result["previous_run_results"][0]["attempt"] == 9


def test_review_success_requires_client_semantic_evidence(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {
            "success": True,
            "attempt": 1,
            "client_validation": {
                "passed": True,
                "tool_count": 1,
                "tools": ["noop"],
                "calls": [{"tool": "noop", "passed": True}],
            },
        },
        "status": "running",
        "workflow_status": "running",
        "options": {},
    }

    result = review_module.review_node(state)

    assert result["review_decision"] == "run"
    assert result["runtime_validation_evidence_errors"] == [
        "Client validation report lacks a successful semantic tool call",
        "Client validation report lacks a successful semantic tool call with a non-empty result",
    ]
    assert result["loop_summary"]["task"] == "runtime_revalidation"
    assert route_after_review(result) == "run"
    assert "run_result" not in result


def test_review_success_rejects_zero_tool_client_report(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {
            "success": True,
            "attempt": 1,
            "client_validation": {
                "passed": True,
                "tool_count": 0,
                "tools": [],
                "calls": [],
            },
        },
        "status": "running",
        "workflow_status": "running",
        "options": {"allow_zero_tools": True},
    }

    result = review_module.review_node(state)

    assert result["review_decision"] == "run"
    assert "Client validation report registered zero tools" in result["runtime_validation_evidence_errors"]
    assert route_after_review(result) == "run"
    assert "run_result" not in result


def test_review_success_requires_registered_tool_count(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {
            "success": True,
            "attempt": 1,
            "client_validation": {
                "passed": True,
                "tools": ["add"],
                "calls": [{"tool": "add", "passed": True, "semantic_success": True, "semantic_evidence": True}],
            },
        },
        "status": "running",
        "workflow_status": "running",
        "options": {},
    }

    result = review_module.review_node(state)

    assert result["review_decision"] == "run"
    assert result["runtime_validation_evidence_errors"] == [
        "Client validation report did not include a registered tool count"
    ]
    assert route_after_review(result) == "run"
    assert "run_result" not in result


def test_review_plugin_result_fallback_preserves_client_validation_evidence(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    client_validation = {
        "passed": True,
        "tool_count": 1,
        "tools": ["add"],
        "calls": [{"tool": "add", "passed": True, "semantic_success": True, "semantic_evidence": True}],
    }
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "tests": {"plugin": {"passed": True, "attempt": 2, "client_validation": client_validation}},
        "status": "running",
        "workflow_status": "running",
        "options": {},
    }

    result = review_module.review_node(state)

    assert result["review_decision"] == "finalize"
    assert result["run_result"]["source"] == "plugin_test_result"
    assert result["run_result"]["client_validation"] == client_validation
    assert route_after_review(result) == "finalize"


def test_review_plugin_result_fallback_rejects_failed_semantic_call(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    client_validation = {
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
    }
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "tests": {"plugin": {"passed": True, "attempt": 2, "client_validation": client_validation}},
        "status": "running",
        "workflow_status": "running",
        "options": {},
    }

    result = review_module.review_node(state)

    assert result["review_decision"] == "run"
    assert result["runtime_validation_evidence_errors"] == [
        "Client validation report lacks a successful semantic tool call",
        "Client validation report lacks a successful semantic tool call with a non-empty result",
    ]
    assert route_after_review(result) == "run"


def test_review_failed_direct_fix_escalates_to_regeneration(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "mcp_output").mkdir(parents=True)
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "run_result": {"success": False, "attempt": 4, "error": "SyntaxError", "stderr": ""},
        "tests": {"plugin": {"passed": False, "attempt": 4}},
        "generation_retry_count": 0,
        "fix_retry_count": 0,
        "previous_run_results": [],
        "status": "running",
        "workflow_status": "running",
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "fix_directly", "summary": "syntax", "confidence": 0.9},
    )
    monkeypatch.setattr(review_module, "_apply_incremental_fixes", lambda *_: state.__setitem__("fix_retry_count", 1) or False)

    result = review_module.review_node(state)

    assert result["review_decision"] == "regenerate"
    assert result["regeneration_prepared"] is True
    assert result["generation_retry_count"] == 1
    assert result["loop_summary"]["fixes"] == "direct_fix_attempt_limit_reached"
    assert "run_result" not in result


def test_review_deterministic_fix_validates_whole_file_then_routes_to_run(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    service = repo_root / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    service.write_text(
        """from fastmcp import FastMCP
import core as _source

mcp = FastMCP("demo")

@mcp.tool(name="solve", description="solve")
def solve(value: str = ""):
    target = getattr(_source, "solve")
    return {"success": True, "result": target(value), "error": None}
""",
        encoding="utf-8",
    )
    state = {
        "repository": {"local_paths": {"repo_root": str(repo_root)}},
        "analysis": {
            "llm_analysis": {
                "core_modules": [
                    {
                        "package": "demo.core",
                        "module": "core",
                        "functions": ["solve"],
                        "classes": [],
                    }
                ]
            }
        },
        "run_result": {
            "success": False,
            "attempt": 2,
            "error": "ImportError: cannot import name 'create_app' from 'mcp_service'",
            "stderr": "",
        },
        "tests": {"plugin": {"passed": False, "attempt": 2}},
        "status": "running",
        "workflow_status": "running",
        "previous_run_results": [],
    }

    monkeypatch.setattr(
        review_module,
        "_intelligent_error_analysis",
        lambda _: {"next_action": "fix_directly", "summary": "missing create_app", "confidence": 0.9},
    )

    result = review_module.review_node(state)

    repaired = service.read_text(encoding="utf-8")
    assert "def create_app():" in repaired
    assert result["review_decision"] == "run"
    assert "run_result" not in result
    assert route_after_review(result) == "run"
    assert "fix_applied" not in result


def test_deterministic_fix_adds_missing_create_app(tmp_path):
    repo_root = tmp_path / "repo"
    service = repo_root / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    service.write_text(
        """from fastmcp import FastMCP

mcp = FastMCP('demo')

@mcp.tool(name="solve", description="solve")
def solve(value: str = ""):
    return {"success": True, "result": value, "error": None}
""",
        encoding="utf-8",
    )

    fixed = _apply_deterministic_fixes("cannot import name 'create_app' from 'mcp_service'", "", str(repo_root))

    assert fixed is True
    assert "def create_app():" in service.read_text(encoding="utf-8")


def test_llm_repair_rejects_noop(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    service = repo_root / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    original = "from fastmcp import FastMCP\n\nmcp = FastMCP('demo')\n\ndef create_app():\n    return mcp\n"
    service.write_text(original, encoding="utf-8")

    class FakeLLM:
        def generate_text(self, *_):
            return "file path: mcp_output/mcp_plugin/mcp_service.py\n" + original

    fixed = _fix_error_with_llm(
        "SyntaxError in mcp_service.py",
        "",
        str(repo_root),
        FakeLLM(),
        {"exit_code": 1},
        None,
    )

    assert fixed is False
    assert service.read_text(encoding="utf-8") == original


def test_repair_prompt_is_evidence_bound_and_has_safe_exit():
    system_prompt = _repair_system_prompt()
    user_prompt = _repair_user_prompt(
        repo_root="E:/code/Code2MCP/workspace/demo",
        target_path="mcp_output/mcp_plugin/mcp_service.py",
        current_text="from fastmcp import FastMCP\n",
        error_message="ImportError: cannot import name 'create_app'",
        stderr="traceback",
        run_result={"exit_code": 1, "stdout": "boom"},
        analysis_result={
            "llm_analysis": {
                "core_modules": [
                    {
                        "package": "demo.core",
                        "module": "core",
                        "functions": ["solve"],
                        "classes": [],
                        "function_signatures": {"solve": ["value"]},
                    }
                ]
            }
        },
    )

    assert "cannot fix safely" in system_prompt
    assert "Never modify source/" in system_prompt
    assert "Do not invent repository APIs" in system_prompt
    assert "Do not use *args or **kwargs" in system_prompt
    assert "_safe_resolve_path" in system_prompt
    assert "URL/URI schemes" in system_prompt
    assert "sensitive path segments" in system_prompt
    assert "coherent complete file" in system_prompt
    assert "duplicate create_app" in system_prompt
    assert "never return success=True from an exception path" in system_prompt
    assert "Verified wrapper contract" in user_prompt
    assert "solve" in user_prompt
    assert "Runtime failure evidence" in user_prompt
    assert "full replacement file is internally consistent" in user_prompt
    assert "mcp_output/mcp_plugin/mcp_service.py" in user_prompt


def test_repair_prompt_redacts_sensitive_runtime_evidence():
    user_prompt = _repair_user_prompt(
        repo_root="E:/code/Code2MCP/workspace/demo",
        target_path="mcp_output/mcp_plugin/mcp_service.py",
        current_text="API_KEY = 'source-secret-123456'\n",
        error_message="OPENAI_API_KEY=sk-testsecret123456",
        stderr="Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        run_result={"exit_code": 1, "stdout": "password=hunter2-secret"},
        analysis_result={"llm_analysis": {"core_modules": []}},
    )

    assert "sk-testsecret123456" not in user_prompt
    assert "abcdefghijklmnopqrstuvwxyz" not in user_prompt
    assert "hunter2-secret" not in user_prompt
    assert "source-secret-123456" not in user_prompt
    assert "[REDACTED]" in user_prompt


def test_error_analysis_prompt_redacts_sensitive_history(monkeypatch):
    captured = {}

    def fake_retry(_llm_service, user_prompt, _system_prompt):
        captured["prompt"] = user_prompt
        return '{"status":"FAIL","next_action":"fail","confidence":0.9,"summary":"blocked","target_file":"","safety_notes":[]}'

    monkeypatch.setenv("CODE2MCP_REVIEW_LLM", "true")
    monkeypatch.setattr(review_module, "get_llm_service", lambda: object())
    monkeypatch.setattr(review_module, "_retry_generate_text", fake_retry)

    _intelligent_error_analysis({
        "run_result": {
            "error": "OPENAI_API_KEY=sk-live-secret-123456",
            "stderr": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        },
        "errors": [{"message": "password=hunter2-secret"}],
        "previous_run_results": [{"stdout": "api_key=previous-secret-123456"}],
    })

    prompt = captured["prompt"]
    assert "sk-live-secret-123456" not in prompt
    assert "abcdefghijklmnopqrstuvwxyz" not in prompt
    assert "hunter2-secret" not in prompt
    assert "previous-secret-123456" not in prompt
    assert "[REDACTED]" in prompt


def test_llm_repair_respects_cannot_fix_safely(tmp_path):
    repo_root = tmp_path / "repo"
    service = repo_root / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    original = "from fastmcp import FastMCP\n\nmcp = FastMCP('demo')\n"
    service.write_text(original, encoding="utf-8")

    class RefusingLLM:
        def generate_text(self, *_):
            return "cannot fix safely\nreason: source code change required"

    fixed = _fix_error_with_llm(
        "requires editing source/module.py",
        "",
        str(repo_root),
        RefusingLLM(),
        {"exit_code": 1},
        None,
    )

    assert fixed is False
    assert _response_declines_fix("cannot fix safely\nreason: nope")
    assert service.read_text(encoding="utf-8") == original


def test_repair_change_scope_rejects_unexplained_rewrite():
    before = "\n".join(f"line_{i}" for i in range(50))
    after = "\n".join(f"new_line_{i}" for i in range(50))

    scoped, reason = _repair_change_is_scoped(before, after, "RuntimeError: one call failed", "")

    assert scoped is False
    assert "changed too much" in reason


def test_repair_change_scope_allows_import_related_rewrite():
    before = "\n".join(f"line_{i}" for i in range(50))
    after = "\n".join(f"new_line_{i}" for i in range(40)) + "\n" + "\n".join(f"line_{i}" for i in range(40, 50))

    scoped, reason = _repair_change_is_scoped(before, after, "ImportError: cannot import name 'x'", "")

    assert scoped is True
    assert reason == ""


def test_whole_file_validation_rejects_incomplete_mcp_service(tmp_path):
    service = tmp_path / "repo" / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    code = "from fastmcp import FastMCP\n\nmcp = FastMCP('demo')\n"

    errors = _validate_repaired_file_whole(str(service), code, None)

    assert any("create_app" in error for error in errors)
    assert any("at least one FastMCP tool" in error for error in errors)


def test_whole_file_validation_uses_tool_quality_gate(tmp_path):
    service = tmp_path / "repo" / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="weather", description="not backed")
def weather(*args, **kwargs):
    return {"success": True}

def create_app():
    return mcp
'''
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "demo.core",
                    "module": "core",
                    "functions": ["solve"],
                    "classes": [],
                }
            ]
        }
    }

    errors = _validate_repaired_file_whole(str(service), code, analysis)

    assert any("not backed by analysis_result" in error for error in errors)
    assert any("uses *args" in error for error in errors)


def test_whole_file_validation_rejects_exception_success_masking_without_analysis(tmp_path):
    service = tmp_path / "repo" / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    service.parent.mkdir(parents=True)
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="solve", description="solve")
def solve(value: int = 0):
    try:
        raise RuntimeError("boom")
    except Exception:
        return {"success": True, "result": None, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_repaired_file_whole(str(service), code, None)

    assert any("broad exception handler returns success=True" in error for error in errors)


def test_post_repair_service_precheck_imports_create_app_and_counts_tools(tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "        self._tools = {}\n"
        "    def tool(self, name=None, description=None):\n"
        "        def decorator(func):\n"
        "            self._tools[name or func.__name__] = func\n"
        "            return func\n"
        "        return decorator\n"
        "class Client:\n"
        "    def __init__(self, app):\n"
        "        self.app = app\n"
        "    async def __aenter__(self):\n"
        "        return self\n"
        "    async def __aexit__(self, exc_type, exc, tb):\n"
        "        return False\n"
        "    async def list_tools(self):\n"
        "        return list(self.app._tools.values())\n",
        encoding="utf-8",
    )
    (plugin_dir / "mcp_service.py").write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('demo')\n"
        "@mcp.tool(name='ping', description='ping')\n"
        "def ping():\n"
        "    return {'success': True, 'result': 'pong'}\n"
        "def create_app():\n"
        "    return mcp\n",
        encoding="utf-8",
    )

    ok, message = _post_repair_service_precheck(
        str(repo_root),
        {"type": "venv", "exec_prefix": [sys.executable]},
    )

    assert ok is True
    assert "OK client_tools=1" in message


def test_post_repair_service_precheck_uses_client_visible_tools(tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "        self._tools = {'internal_only': object()}\n"
        "    def tool(self, name=None, description=None):\n"
        "        def decorator(func):\n"
        "            self._tools[name or func.__name__] = func\n"
        "            return func\n"
        "        return decorator\n"
        "class Client:\n"
        "    def __init__(self, app):\n"
        "        self.app = app\n"
        "    async def __aenter__(self):\n"
        "        return self\n"
        "    async def __aexit__(self, exc_type, exc, tb):\n"
        "        return False\n"
        "    async def list_tools(self):\n"
        "        return []\n",
        encoding="utf-8",
    )
    (plugin_dir / "mcp_service.py").write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('demo')\n"
        "@mcp.tool(name='ping', description='ping')\n"
        "def ping():\n"
        "    return {'success': True, 'result': 'pong'}\n"
        "def create_app():\n"
        "    return mcp\n",
        encoding="utf-8",
    )

    ok, message = _post_repair_service_precheck(
        str(repo_root),
        {"type": "venv", "exec_prefix": [sys.executable]},
    )

    assert ok is False
    assert "client listed no tools" in message


def test_post_repair_service_precheck_rejects_zero_tool_service(tmp_path):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "        self._tools = {}\n"
        "    def tool(self, name=None, description=None):\n"
        "        def decorator(func):\n"
        "            self._tools[name or func.__name__] = func\n"
        "            return func\n"
        "        return decorator\n"
        "class Client:\n"
        "    def __init__(self, app):\n"
        "        self.app = app\n"
        "    async def __aenter__(self):\n"
        "        return self\n"
        "    async def __aexit__(self, exc_type, exc, tb):\n"
        "        return False\n"
        "    async def list_tools(self):\n"
        "        return list(self.app._tools.values())\n",
        encoding="utf-8",
    )
    (plugin_dir / "mcp_service.py").write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('demo')\n"
        "def create_app():\n"
        "    return mcp\n",
        encoding="utf-8",
    )

    ok, message = _post_repair_service_precheck(
        str(repo_root),
        {"type": "venv", "exec_prefix": [sys.executable]},
    )

    assert ok is False
    assert "client listed no tools" in message
