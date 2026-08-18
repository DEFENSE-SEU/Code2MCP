import json
import time
from pathlib import Path

import src.nodes.finalize_node as finalize


def _patch_expensive_finalize(monkeypatch):
    monkeypatch.setattr(finalize, "_extract_project_type_from_analysis", lambda analysis: "Python library")
    monkeypatch.setattr(finalize, "_extract_features_from_analysis", lambda analysis: "Basic functionality")
    monkeypatch.setattr(finalize, "_extract_tech_stack_from_analysis", lambda analysis: "Python")
    monkeypatch.setattr(finalize, "_generate_recommendations", lambda state: [])
    monkeypatch.setattr(finalize, "_generate_llm_summary", lambda state, summary: {})
    monkeypatch.setattr(finalize, "_generate_technical_report", lambda state, summary, llm: "")
    monkeypatch.setattr(finalize, "_save_final_reports", lambda state, summary, report: None)
    monkeypatch.setattr(finalize, "deploy_to_huggingface", lambda repo_root, push=False: {"success": True})
    monkeypatch.setattr(finalize, "create_and_run_local_scripts", lambda repo_root, autorun=True: {"success": True})


def _base_state(tmp_path):
    return {
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(tmp_path)},
        },
        "analysis": {},
        "plugin": {"files": {"mcp_output/start_mcp.py": str(tmp_path / "start_mcp.py")}},
        "tests": {},
        "errors": [],
        "warnings": [],
        "workflow_start_time": time.time(),
        "options": {},
    }


def _validated_plugin(tool_count: int = 2, attempt=None):
    result = {
        "passed": True,
        "tool_count": tool_count,
        "client_validation": {
            "passed": True,
            "tool_count": tool_count,
            "warnings": [],
            "calls": [{"tool": "add", "passed": True, "is_error": False, "semantic_success": True, "semantic_evidence": True}],
        },
    }
    if attempt is not None:
        result["attempt"] = attempt
    return result


def _validated_run_result(attempt: int = 1):
    return {
        "success": True,
        "attempt": attempt,
        "client_validation": {
            "passed": True,
            "tool_count": 2,
            "calls": [{"tool": "add", "passed": True, "is_error": False, "semantic_success": True, "semantic_evidence": True}],
        },
    }


def test_finalize_does_not_succeed_without_plugin_test(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)

    result = finalize.finalize_node(state)

    assert result["workflow_status"] == "failed"
    assert result["summary"]["execution"]["verified"] is False


def test_finalize_generate_only_is_unvalidated(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["options"] = {"generate_only": True}

    result = finalize.finalize_node(state)

    assert result["workflow_status"] == "generated"
    assert result["summary"]["execution"]["validation_status"] == "generated_unvalidated"
    assert result["summary"]["execution"]["verified"] is False


def test_finalize_validated_requires_plugin_pass(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin()}

    result = finalize.finalize_node(state)

    assert result["status"] == "validated"
    assert result["workflow_status"] == "validated"
    assert result["summary"]["status"] == "validated"
    assert result["summary"]["execution"]["status"] == "validated"
    assert result["summary"]["execution"]["verified"] is True
    assert result["summary"]["workflow_status"] == "validated"
    assert result["summary"]["validation_status"] == "validated"
    assert result["summary"]["verified"] is True
    assert result["summary"]["success"] is True
    assert result["summary"]["tests"]["original_project"]["test_coverage"] == "not measured"
    assert result["summary"]["deployment_info"]["python_versions"] == ["3.10", "3.11", "3.12", "3.13"]
    assert result["summary"]["deployment_info"]["monitoring_support"] == "basic_healthcheck"


def test_finalize_rejects_stale_plugin_pass_after_latest_run_failed(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin(attempt=1)}
    state["run_result"] = {
        "success": False,
        "attempt": 2,
        "client_validation": {"passed": False, "calls": []},
        "error": "latest runtime evidence failed",
    }

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_rejects_plugin_pass_from_prior_attempt(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin(attempt=1)}
    state["run_result"] = _validated_run_result(attempt=2)

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_rejects_plugin_pass_missing_attempt_when_latest_run_has_attempt(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin()}
    state["run_result"] = _validated_run_result(attempt=2)

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_rejects_latest_run_without_client_validation(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin(attempt=2)}
    state["run_result"] = {"success": True, "attempt": 2}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_rejects_latest_run_without_successful_semantic_call(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin(attempt=2)}
    state["run_result"] = {
        "success": True,
        "attempt": 2,
        "client_validation": {
            "passed": True,
            "tool_count": 1,
            "calls": [
                {
                    "tool": "add",
                    "passed": False,
                    "is_error": False,
                    "semantic_success": True,
                    "semantic_evidence": True,
                }
            ],
        },
    }

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_moves_retry_errors_to_recovered_when_validated(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    retry_error = {
        "node": "RunNode",
        "type": "PluginSmokeFailed",
        "severity": "high",
        "message": "first runtime smoke failed",
        "attempt": 1,
    }
    state["errors"] = [retry_error]
    state["tests"] = {"plugin": _validated_plugin()}

    result = finalize.finalize_node(state)

    summary = result["summary"]
    assert summary["workflow_status"] == "validated"
    assert summary["errors"] == []
    assert summary["recovered_errors"] == [retry_error]
    assert summary["execution"]["unresolved_error_count"] == 0
    assert summary["execution"]["recovered_error_count"] == 1


def test_finalize_keeps_errors_unresolved_when_not_validated(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    error = {
        "node": "RunNode",
        "type": "PluginSmokeFailed",
        "severity": "high",
        "message": "runtime smoke failed",
    }
    state["errors"] = [error]

    result = finalize.finalize_node(state)

    summary = result["summary"]
    assert summary["workflow_status"] == "failed"
    assert summary["errors"] == [error]
    assert summary["recovered_errors"] == []
    assert summary["execution"]["unresolved_error_count"] == 1
    assert summary["execution"]["recovered_error_count"] == 0


def test_finalize_preserves_unsupported_audited_status(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    error = {
        "node": "GenerateNode",
        "type": "UnsupportedRepository",
        "severity": "high",
        "message": "No verified public functions/classes or supported build targets were found for MCP generation",
        "details": {
            "likely_reason": "candidate_targets_rejected_by_generation_safety_filters",
            "rejected_targets": [
                {
                    "kind": "function",
                    "module": "SCT_CS_04.main",
                    "name": "on_press",
                    "file_path": "SCT_CS_04/main.py",
                    "reasons": ["imports keyboard listener dependency: pynput"],
                }
            ],
        },
        "action_taken": "abort_before_runtime",
    }
    state["errors"] = [error]

    result = finalize.finalize_node(state)

    summary = result["summary"]
    assert result["workflow_status"] == "failed"
    assert result["validation_status"] == "unsupported_audited"
    assert summary["workflow_status"] == "failed"
    assert summary["validation_status"] == "unsupported_audited"
    assert summary["execution"]["validation_status"] == "unsupported_audited"
    assert summary["verified"] is False
    assert summary["success"] is False
    assert summary["errors"] == [error]


def test_finalize_does_not_validate_without_client_validation(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": {"passed": True, "tool_count": 2}}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_does_not_validate_without_semantic_success_call(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    plugin = _validated_plugin()
    plugin["client_validation"]["calls"] = [
        {"tool": "add", "semantic_success": False},
        {"tool": "slugify", "semantic_success": None},
    ]
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": plugin}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_does_not_validate_without_meaningful_result(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    plugin = _validated_plugin()
    plugin["client_validation"]["calls"] = [
        {"tool": "noop", "passed": True, "is_error": False, "semantic_success": True, "semantic_evidence": False},
    ]
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": plugin}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_does_not_validate_failed_semantic_call(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    plugin = _validated_plugin()
    plugin["client_validation"]["calls"] = [
        {"tool": "add", "passed": False, "is_error": False, "semantic_success": True, "semantic_evidence": True},
    ]
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": plugin}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_does_not_validate_error_semantic_call(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    plugin = _validated_plugin()
    plugin["client_validation"]["calls"] = [
        {"tool": "add", "passed": True, "is_error": True, "semantic_success": True, "semantic_evidence": True},
    ]
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": plugin}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_does_not_validate_without_client_tool_count(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    plugin = _validated_plugin()
    plugin["client_validation"].pop("tool_count")
    state = _base_state(tmp_path)
    state["tests"] = {"plugin": plugin}

    result = finalize.finalize_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["summary"]["verified"] is False
    assert result["summary"]["success"] is False


def test_finalize_records_real_file_and_tool_metrics(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    start_mcp = tmp_path / "mcp_output" / "start_mcp.py"
    service = tmp_path / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    start_mcp.parent.mkdir(parents=True)
    service.parent.mkdir(parents=True)
    start_mcp.write_text("from mcp_plugin.mcp_service import create_app\n", encoding="utf-8")
    service.write_text("def create_app():\n    return None\n", encoding="utf-8")

    state = _base_state(tmp_path)
    state["analysis"] = {"summary": {"stats": {"total_files": 2}}}
    state["plugin"] = {
        "files": {
            "mcp_output/start_mcp.py": str(start_mcp),
            "mcp_output/mcp_plugin/mcp_service.py": str(service),
        },
        "endpoints": ["add", "slugify"],
        "requirements": ["fastmcp>=0.1.0"],
    }
    state["tests"] = {"plugin": _validated_plugin()}

    result = finalize.finalize_node(state)

    execution = result["summary"]["execution"]
    generation = result["summary"]["plugin_generation"]
    assert execution["total_files_processed"] == 2
    assert generation["total_lines_of_code"] == 3
    assert generation["generated_files_size"] > 0
    assert generation["tool_endpoints"] == 2
    assert generation["generated_tools"] == ["add", "slugify"]


def test_finalize_agent_connection_uses_client_tool_count(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    start_mcp = tmp_path / "mcp_output" / "start_mcp.py"
    start_mcp.parent.mkdir(parents=True)
    start_mcp.write_text("print('start')\n", encoding="utf-8")
    plugin = _validated_plugin(tool_count=1)
    plugin["tool_count"] = 99
    state = _base_state(tmp_path)
    state["plugin"]["files"] = {"mcp_output/start_mcp.py": str(start_mcp)}
    state["tests"] = {"plugin": plugin}

    result = finalize.finalize_node(state)

    profile_path = Path(result["agent_connection"]["profile_path"])
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert result["workflow_status"] == "validated"
    assert profile["validation"]["tool_count"] == 1


def test_finalize_local_does_not_autorun_or_hf_deploy(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    deploy_calls = []
    local_calls = []
    monkeypatch.setattr(finalize, "deploy_to_huggingface", lambda repo_root, push=False: deploy_calls.append((repo_root, push)) or {"success": True})
    monkeypatch.setattr(finalize, "create_and_run_local_scripts", lambda repo_root, autorun=True: local_calls.append((repo_root, autorun)) or {"success": True})
    monkeypatch.delenv("AUTO_DEPLOY_HF", raising=False)
    monkeypatch.delenv("CODE2MCP_LOCAL_AUTORUN", raising=False)

    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin()}
    state["options"] = {"deploy_target": "local"}

    result = finalize.finalize_node(state)

    assert result["workflow_status"] == "validated"
    assert deploy_calls == []
    assert local_calls == [(str(tmp_path), False)]


def test_finalize_hf_target_prepares_hf_scaffold_without_push_by_default(monkeypatch, tmp_path):
    _patch_expensive_finalize(monkeypatch)
    deploy_calls = []
    local_calls = []
    monkeypatch.setattr(finalize, "deploy_to_huggingface", lambda repo_root, push=False: deploy_calls.append((repo_root, push)) or {"success": True})
    monkeypatch.setattr(finalize, "create_and_run_local_scripts", lambda repo_root, autorun=True: local_calls.append((repo_root, autorun)) or {"success": True})
    monkeypatch.delenv("AUTO_DEPLOY_HF", raising=False)
    monkeypatch.delenv("HF_PUSH", raising=False)
    monkeypatch.delenv("CODE2MCP_LOCAL_AUTORUN", raising=False)

    state = _base_state(tmp_path)
    state["tests"] = {"plugin": _validated_plugin()}
    state["options"] = {"deploy_target": "hf"}

    result = finalize.finalize_node(state)

    assert result["workflow_status"] == "validated"
    assert deploy_calls == [(str(tmp_path), False)]
    assert local_calls == [(str(tmp_path), False)]


def test_extract_generated_tools_does_not_invent_defaults():
    assert finalize._extract_generated_tools({}, {}) == []
    assert finalize._extract_generated_tools({"endpoints": ["solve", "integrate"]}, {}) == ["solve", "integrate"]


def test_finalize_llm_enrichment_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    monkeypatch.setattr(
        finalize,
        "get_llm_service",
        lambda: (_ for _ in ()).throw(AssertionError("LLM should not be called by default")),
    )
    summary = {
        "execution": {"status": "validated", "workflow_status": "validated", "validation_status": "validated", "verified": True},
        "tests": {"mcp_plugin": {"passed": True}},
    }

    assert finalize._extract_project_type_from_analysis({"deepwiki_analysis": {"analysis": "x" * 500}}) == "Python library"
    assert finalize._extract_features_from_analysis({"deepwiki_analysis": {"analysis": "x" * 500}}) == "Basic functionality"
    assert finalize._extract_tech_stack_from_analysis({"deepwiki_analysis": {"analysis": "x" * 500}}) == "Python"
    assert finalize._generate_llm_summary({}, summary)["execution_analysis"]["overall_assessment"] == "good"
    report = finalize._generate_technical_report({"repository": {"name": "demo"}}, summary, {})
    assert "Technical Report" in report
    assert "passed runtime/client validation" in report


def test_finalize_project_type_uses_static_file_tree(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    analysis = {
        "summary": {
            "file_tree": {
                "Package.swift": {"size": 120},
                "Sources/SnapKit/Constraint.swift": {"size": 240},
            }
        }
    }

    assert finalize._extract_project_type_from_analysis(analysis) == "Swift package"
    assert finalize._repository_language_from_analysis(analysis) == "Swift"


def test_default_reports_include_unsupported_audit_details(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    unsupported_error = {
        "node": "GenerateNode",
        "type": "UnsupportedRepository",
        "severity": "high",
        "message": "No verified public functions/classes or supported build targets were found for MCP generation",
        "details": {
            "project_type": "Python",
            "stage": "pre_generation_target_selection",
            "likely_reason": "candidate_targets_rejected_by_generation_safety_filters",
            "original_core_module_count": 1,
            "original_function_count": 3,
            "original_class_count": 0,
            "filtered_core_module_count": 0,
            "filtered_function_count": 0,
            "filtered_class_count": 0,
            "rejected_target_count": 1,
            "rejected_targets": [
                {
                    "kind": "function",
                    "module": "SCT_CS_04.main",
                    "name": "on_press",
                    "file_path": "SCT_CS_04/main.py",
                    "reasons": ["imports keyboard listener dependency: pynput"],
                }
            ],
        },
        "action_taken": "abort_before_runtime",
    }
    summary = {
        "workflow_status": "failed",
        "validation_status": "unsupported_audited",
        "verified": False,
        "errors": [unsupported_error],
    }
    state = {
        "repository": {"name": "Key_stroke_Analyser", "url": "https://github.com/example/Key_stroke_Analyser"},
        "analysis": {"summary": {"file_tree": {"SCT_CS_04/main.py": {"size": 200}}}},
        "plugin": {},
        "tests": {},
        "workflow_status": "failed",
        "errors": [unsupported_error],
    }

    technical = finalize._generate_technical_report(state, summary, {})
    diff = finalize._generate_diff_report(state)

    assert "Unsupported Repository Audit" in technical
    assert "on_press" in technical
    assert "imports keyboard listener dependency: pynput" in technical
    assert "Unsupported (audited)" in diff
    assert "candidate_targets_rejected_by_generation_safety_filters" in diff
    assert "Expose side-effect-free functions/classes" in diff


def test_unsupported_reports_redact_sensitive_audit_details(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    raw_token = "sk-finalize-secret-123456"
    raw_password = "hunter2-secret"
    unsupported_error = {
        "type": "UnsupportedRepository",
        "message": f"No target found with OPENAI_API_KEY={raw_token}",
        "details": {
            "project_type": "Python",
            "stage": f"pre_generation_target_selection GITHUB_TOKEN=ghp_abcdefghijklmnop",
            "likely_reason": f"unsupported_project_type password={raw_password}",
            "original_core_module_count": 1,
            "original_function_count": 1,
            "original_class_count": 0,
            "filtered_core_module_count": 0,
            "filtered_function_count": 0,
            "filtered_class_count": 0,
            "rejected_target_count": 1,
            "rejected_targets": [
                {
                    "kind": "function",
                    "module": f"finance_{raw_token}",
                    "name": "load_secret",
                    "file_path": f"src/{raw_token}/private.py",
                    "reasons": [f"rejected because password={raw_password}"],
                }
            ],
        },
        "action_taken": f"abort_before_runtime HF_TOKEN=hf_abcdefghijkl",
    }
    summary = {
        "workflow_status": "failed",
        "validation_status": "unsupported_audited",
        "verified": False,
        "errors": [unsupported_error],
    }
    state = {
        "repository": {"name": "secret-fixture", "url": "https://github.com/example/secret-fixture"},
        "analysis": {"summary": {"file_tree": {"src/main.py": {"size": 20}}}},
        "plugin": {},
        "tests": {},
        "workflow_status": "failed",
        "errors": [unsupported_error],
    }

    rendered = "\n".join(
        [
            finalize._generate_technical_report(state, summary, {}),
            finalize._generate_diff_report(state),
            "\n".join(finalize._generate_recommendations(state)),
        ]
    )

    assert "Unsupported Repository Audit" in rendered
    assert "[REDACTED]" in rendered
    assert raw_token not in rendered
    assert raw_password not in rendered
    assert "ghp_abcdefghijklmnop" not in rendered
    assert "hf_abcdefghijkl" not in rendered


def test_diff_report_uses_static_project_type_for_unsupported_swift(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    unsupported_error = {
        "type": "UnsupportedRepository",
        "message": "No verified public functions/classes or supported build targets were found for MCP generation",
        "details": {
            "project_type": "Swift",
            "stage": "pre_generation_target_selection",
            "likely_reason": "unsupported_project_type",
            "original_core_module_count": 0,
            "original_function_count": 0,
            "original_class_count": 0,
            "filtered_core_module_count": 0,
            "filtered_function_count": 0,
            "filtered_class_count": 0,
        },
        "action_taken": "abort_before_runtime",
    }
    state = {
        "repository": {"name": "SnapKit", "url": "https://github.com/SnapKit/SnapKit"},
        "analysis": {
            "summary": {
                "file_tree": {
                    "Package.swift": {"size": 120},
                    "Sources/SnapKit/Constraint.swift": {"size": 240},
                }
            }
        },
        "plugin": {},
        "tests": {},
        "workflow_status": "failed",
        "errors": [unsupported_error],
    }

    report = finalize._generate_diff_report(state)

    assert "**Project Type**: Swift package" in report
    assert "unsupported_project_type" in report
    assert "Add Code2MCP generator support for `Swift`" in report


def test_default_llm_summary_requires_verified_validation():
    unverified_validated = {
        "execution": {
            "status": "validated",
            "workflow_status": "validated",
            "validation_status": "validated",
            "verified": False,
        },
        "tests": {"mcp_plugin": {"passed": True}},
    }
    legacy_success = {
        "execution": {"status": "success", "verified": True},
        "tests": {"mcp_plugin": {"passed": True}},
    }

    assert finalize._generate_llm_summary({}, unverified_validated)["execution_analysis"]["overall_assessment"] == "poor"
    assert finalize._generate_llm_summary({}, legacy_success)["execution_analysis"]["overall_assessment"] == "poor"


def test_default_technical_report_does_not_overstate_unvalidated_status(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    generated_summary = {
        "workflow_status": "generated",
        "validation_status": "generated_unvalidated",
        "verified": False,
    }
    failed_summary = {
        "workflow_status": "failed",
        "validation_status": "failed",
        "verified": False,
    }

    generated = finalize._generate_technical_report({"repository": {"name": "demo"}}, generated_summary, {})
    failed = finalize._generate_technical_report({"repository": {"name": "demo"}}, failed_summary, {})

    assert "successfully converted" not in generated
    assert "runtime/client validation was skipped" in generated
    assert "Production readiness: not validated" in generated
    assert "successfully converted" not in failed
    assert "could not prove the service is runnable" in failed
    assert "diagnostic artifacts" in failed


def test_diff_report_does_not_mark_validated_workflow_as_failed(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    state = {
        "repository": {"name": "demo", "url": "https://github.com/example/demo"},
        "analysis": {},
        "plugin": {"files": {"mcp_output/start_mcp.py": "x"}},
        "tests": {"plugin": _validated_plugin()},
        "workflow_status": "validated",
    }

    report = finalize._generate_diff_report(state)

    assert "**Analysis Status**: Validated" in report
    assert "**Analysis Status**: Failed" not in report
    assert "MCP runtime/client validation passed" in report


def test_diff_report_does_not_praise_failed_workflow(monkeypatch):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    state = {
        "repository": {"name": "demo", "url": "https://github.com/example/demo"},
        "analysis": {},
        "plugin": {"files": {"mcp_output/start_mcp.py": "x"}},
        "tests": {"plugin": {"passed": False, "client_validation": {"passed": False, "calls": []}}},
        "workflow_status": "failed",
    }

    report = finalize._generate_diff_report(state)

    assert "**Analysis Status**: Failed" in report
    assert "performs well" not in report
    assert "could not prove the demo service is ready" in report
    assert "do not treat generated files as production-ready" in report


def test_llm_readme_failure_fallback_has_no_placeholders(monkeypatch):
    monkeypatch.setenv("CODE2MCP_FINALIZE_LLM", "true")
    monkeypatch.setattr(
        finalize,
        "get_llm_service",
        lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    readme = finalize._generate_readme_mcp(
        {},
        {
            "workflow_status": "validated",
            "validation_status": "validated",
            "verified": True,
            "tests": {"mcp_plugin": {"details": {"tool_count": 2}}},
        },
    )

    assert "please add" not in readme.lower()
    assert "Main function 1" not in readme
    assert "Workflow status: `validated`" in readme
    assert "passed runtime smoke tests and FastMCP client validation" in readme


def test_readme_mcp_generate_only_warns_unvalidated():
    readme = finalize._generate_readme_mcp(
        {},
        {
            "workflow_status": "generated",
            "validation_status": "generated_unvalidated",
            "verified": False,
            "tests": {"mcp_plugin": {"details": {"tool_count": 0}}},
        },
    )

    assert "Workflow status: `generated`" in readme
    assert "runtime validation was skipped" in readme
    assert "Do not connect this service to production agents" in readme


def test_save_final_reports_mirrors_key_files_to_output_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("CODE2MCP_FINALIZE_LLM", raising=False)
    repo_root = tmp_path / "repo"
    output_dir = tmp_path / "requested-output"
    mcp_output = repo_root / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "agent_connection.json").write_text('{"ok": true}', encoding="utf-8")
    (mcp_output / "agent_connect.html").write_text("<html>guide</html>", encoding="utf-8")
    (mcp_output / "agent_mcp_config.json").write_text('{"mcpServers": {}}', encoding="utf-8")

    state = {
        "repository": {
            "name": "demo",
            "url": "https://github.com/example/demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "analysis": {},
        "plugin": {"files": {"mcp_output/start_mcp.py": "x"}},
        "tests": {"plugin": {"passed": True}},
        "workflow_status": "validated",
        "options": {"output_dir": str(output_dir)},
    }
    summary = {
        "workflow_status": "validated",
        "validation_status": "validated",
        "verified": True,
        "repository": {"name": "demo"},
        "execution": {"workflow_status": "validated", "validation_status": "validated", "verified": True},
    }

    finalize._save_final_reports(state, summary, "# Technical")

    mirrored = output_dir / "demo"
    assert (mirrored / "workflow_summary.json").exists()
    assert (mirrored / "technical_report.md").read_text(encoding="utf-8") == "# Technical"
    assert (mirrored / "agent_connection.json").exists()
    assert (mirrored / "agent_connect.html").exists()
    index = json.loads((mirrored / "artifact_index.json").read_text(encoding="utf-8"))
    assert index["workflow_status"] == "validated"
    assert index["verified"] is True
    assert Path(index["artifacts"]["workflow_summary"]).exists()


def test_finalize_llm_flag_parsing(monkeypatch):
    monkeypatch.setenv("CODE2MCP_FINALIZE_LLM", "true")
    assert finalize._finalize_llm_enabled() is True
    assert "optional LLM" in finalize._finalize_summary_log_message()
    monkeypatch.setenv("CODE2MCP_FINALIZE_LLM", "false")
    assert finalize._finalize_llm_enabled() is False
    assert "LLM disabled" in finalize._finalize_summary_log_message()


def test_auto_connect_uses_quick_connect_remote_write_for_supported_clients(monkeypatch, tmp_path):
    calls = []

    def fake_connect_agent(repo_root, **kwargs):
        calls.append((repo_root, kwargs))
        return {"connection": {"client": kwargs["client"], "ready": True}, "files": {"profile": "agent_connection.json"}}

    monkeypatch.setattr(finalize, "connect_agent", fake_connect_agent)

    result = finalize._connect_mcp_client(
        "cursor",
        "demo",
        "https://example.hf.space",
        str(tmp_path),
    )

    assert result["success"] is True
    assert result["write_attempted"] is True
    assert result["mode"] == "installed"
    assert calls == [
        (
            str(tmp_path),
            {
                "client": "cursor",
                "server_name": "demo",
                "remote_url": "https://example.hf.space",
                "write": True,
                "remote": True,
                "probe_remote": True,
                "remote_probe_timeout": 30.0,
            },
        )
    ]


def test_auto_connect_prepares_copy_payload_for_copy_only_clients(monkeypatch, tmp_path):
    calls = []

    def fake_connect_agent(repo_root, **kwargs):
        calls.append((repo_root, kwargs))
        return {
            "connection": {"client": kwargs["client"], "ready": True},
            "files": {"connection_guide_html": "agent_connect.html"},
        }

    monkeypatch.setattr(finalize, "connect_agent", fake_connect_agent)

    result = finalize._connect_mcp_client(
        "vscode",
        "demo",
        "https://example.hf.space",
        str(tmp_path),
    )

    assert result["success"] is True
    assert result["write_attempted"] is False
    assert result["mode"] == "copy_config"
    assert result["files"] == {"connection_guide_html": "agent_connect.html"}
    assert calls == [
        (
            str(tmp_path),
            {
                "client": "vscode",
                "server_name": "demo",
                "remote_url": "https://example.hf.space",
                "write": False,
                "remote": True,
                "probe_remote": True,
                "remote_probe_timeout": 30.0,
            },
        )
    ]


def test_auto_connect_reports_quick_connect_failure(monkeypatch, tmp_path):
    def fake_connect_agent(*_args, **_kwargs):
        raise finalize.QuickConnectError("not validated")

    monkeypatch.setattr(finalize, "connect_agent", fake_connect_agent)

    result = finalize._connect_mcp_client("cursor", "demo", "https://example.hf.space", str(tmp_path))

    assert result == {"success": False, "client": "cursor", "error": "not validated"}


def test_auto_connect_redacts_quick_connect_failure(monkeypatch, tmp_path):
    def fake_connect_agent(*_args, **_kwargs):
        raise finalize.QuickConnectError("OPENAI_API_KEY=sk-finalize-secret-123456 password=hunter2-secret")

    monkeypatch.setattr(finalize, "connect_agent", fake_connect_agent)

    result = finalize._connect_mcp_client("cursor", "demo", "https://example.hf.space", str(tmp_path))
    payload = json.dumps(result, ensure_ascii=False)

    assert result["success"] is False
    assert "sk-finalize-secret-123456" not in payload
    assert "hunter2-secret" not in payload
    assert "[REDACTED]" in result["error"]
