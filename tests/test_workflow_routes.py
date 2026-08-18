import asyncio

from main import GENERATE_ONLY_HELP
from src.workflow import (
    WorkflowOrchestrator,
    _workflow_recursion_limit,
    route_after_analysis,
    route_after_generate,
    route_after_review,
    route_after_run,
)


def test_default_routes_include_env_and_run():
    state = {"status": "running", "workflow_status": "running", "options": {}}

    assert route_after_analysis(state) == "env"
    assert route_after_generate(state) == "run"


def test_generate_only_routes_to_finalize():
    state = {"status": "running", "workflow_status": "running", "options": {"generate_only": True}}

    assert route_after_generate(state) == "finalize"


def test_generate_only_still_runs_env_before_generate():
    state = {"status": "running", "workflow_status": "running", "options": {"generate_only": True}}

    assert route_after_analysis(state) == "env"


def test_generate_only_cli_help_matches_route_behavior():
    assert "analysis/env/generate" in GENERATE_ONLY_HELP
    assert "skip environment setup" not in GENERATE_ONLY_HELP.lower()


def test_workflow_recursion_limit_exceeds_retry_budgets(monkeypatch):
    monkeypatch.delenv("CODE2MCP_WORKFLOW_RECURSION_LIMIT", raising=False)

    assert _workflow_recursion_limit() >= 100

    monkeypatch.setenv("CODE2MCP_WORKFLOW_RECURSION_LIMIT", "40")

    assert _workflow_recursion_limit() == 40


def test_orchestrator_injects_output_dir_into_workflow_options(tmp_path):
    class FakeApp:
        async def ainvoke(self, initial_state, config):
            return {
                "workflow_status": "generated",
                "status": "generated",
                "options": initial_state["options"],
            }

    orchestrator = WorkflowOrchestrator(output_dir=str(tmp_path))
    orchestrator.app = FakeApp()

    result = asyncio.run(orchestrator.run_workflow("https://github.com/example/demo", options={}))

    assert result["success"] is False
    assert result["completed"] is True
    assert result["validated"] is False
    assert result["workflow_status"] == "generated"
    assert result["state"]["options"]["output_dir"] == str(tmp_path)


def test_orchestrator_marks_only_validated_workflow_successful(tmp_path):
    class FakeApp:
        async def ainvoke(self, initial_state, config):
            return {
                "workflow_status": "validated",
                "status": "validated",
                "options": initial_state["options"],
            }

    orchestrator = WorkflowOrchestrator(output_dir=str(tmp_path))
    orchestrator.app = FakeApp()

    result = asyncio.run(orchestrator.run_workflow("https://github.com/example/demo", options={}))

    assert result["success"] is True
    assert result["completed"] is True
    assert result["validated"] is True
    assert result["workflow_status"] == "validated"


def test_orchestrator_does_not_treat_legacy_success_as_validated(tmp_path):
    class FakeApp:
        async def ainvoke(self, _initial_state, _config):
            return {
                "workflow_status": "success",
                "status": "success",
                "error": "legacy ambiguous status",
            }

    orchestrator = WorkflowOrchestrator(output_dir=str(tmp_path))
    orchestrator.app = FakeApp()

    result = asyncio.run(orchestrator.run_workflow("https://github.com/example/demo", options={}))

    assert result["success"] is False
    assert "legacy ambiguous status" in result["message"]


def test_failed_state_routes_to_finalize_for_failed_summary():
    state = {"status": "failed", "workflow_status": "failed"}

    assert route_after_analysis(state) == "finalize"


def test_review_routes_fix_back_to_run():
    state = {"status": "running", "workflow_status": "running", "fix_applied": True}

    assert route_after_review(state) == "run"
    assert "fix_applied" not in state


def test_run_attempt_budget_stops_infinite_review_loop():
    state = {
        "status": "running",
        "workflow_status": "running",
        "run_result": {"success": False, "attempt": 12, "error": "still broken"},
        "repair_loop": {"events": []},
    }

    assert route_after_run(state) == "finalize"
    assert state["workflow_status"] == "failed"
    assert "Maximum run attempts reached" in state["error"]


def test_review_fail_action_stops_retry_loop():
    state = {
        "status": "running",
        "workflow_status": "running",
        "error_analysis": {"next_action": "fail", "summary": "LLM repair unavailable"},
    }

    assert route_after_review(state) == "finalize"
    assert state["workflow_status"] == "failed"
    assert "LLM repair unavailable" in state["error"]


def test_review_retry_keeps_failed_run_evidence():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "review",
        "run_result": {"success": False, "attempt": 3, "error": "SyntaxError"},
        "fix_retry_count": 1,
        "previous_run_results": [],
    }

    assert route_after_review(state) == "review"
    assert state["run_result"]["attempt"] == 3
    assert state["previous_run_results"] == []
    assert "review_decision" not in state


def test_review_retry_without_failed_run_evidence_fails():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "review",
        "run_result": {"success": True, "attempt": 1},
        "fix_retry_count": 1,
    }

    assert route_after_review(state) == "finalize"
    assert state["workflow_status"] == "failed"
    assert "without failed runtime evidence" in state["error"]


def test_review_finalize_with_failed_run_is_blocked():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "finalize",
        "run_result": {"success": False, "attempt": 2, "error": "still broken"},
    }

    assert route_after_review(state) == "finalize"
    assert state["workflow_status"] == "failed"
    assert "still failed" in state["error"]


def test_review_finalize_with_stale_success_evidence_reruns_validation():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "finalize",
        "run_result": {"success": True, "attempt": 2},
        "tests": {"plugin": {"passed": True, "attempt": 1}},
        "repair_loop": {"events": []},
    }

    assert route_after_review(state) == "run"
    assert "run_result" not in state
    assert "plugin" not in state["tests"]
    assert any("FastMCP client report" in error for error in state["runtime_validation_evidence_errors"])
    assert state["repair_loop"]["events"][-1]["event"] == "review_finalize_revalidation_required"


def test_review_finalize_with_current_runtime_evidence_routes_to_finalize():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "finalize",
        "run_result": {
            "success": True,
            "attempt": 2,
            "client_validation": {
                "passed": True,
                "tool_count": 1,
                "calls": [
                    {
                        "tool": "add",
                        "passed": True,
                        "is_error": False,
                        "semantic_success": True,
                        "semantic_evidence": True,
                    }
                ],
            },
        },
    }

    assert route_after_review(state) == "finalize"


def test_review_retry_budget_escalates_to_regenerate():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "review",
        "run_result": {"success": False, "attempt": 5, "error_type": "RuntimeError", "error": "broken"},
        "tests": {"plugin": {"passed": False, "attempt": 5}},
        "generation_retry_count": 0,
        "fix_retry_count": 5,
        "previous_run_results": [],
        "errors": [{"severity": "high", "message": "broken"}],
    }

    assert route_after_review(state) == "generate"
    assert state["generation_retry_count"] == 1
    assert state["fix_retry_count"] == 0
    assert "run_result" not in state
    assert state["previous_run_results"][0]["archived_reason"] == "fix_budget_exhausted"


def test_review_regenerate_budget_exhaustion_fails():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "regenerate",
        "run_result": {"success": False, "attempt": 6, "error": "broken"},
        "generation_retry_count": 5,
        "fix_retry_count": 5,
        "errors": [{"severity": "high", "message": "broken"}],
    }

    assert route_after_review(state) == "finalize"
    assert state["workflow_status"] == "failed"
    assert "retry policy rejected" in state["error"]


def test_review_regenerate_archives_failed_run_and_clears_stale_validation():
    state = {
        "status": "running",
        "workflow_status": "running",
        "review_decision": "regenerate",
        "run_result": {"success": False, "attempt": 4, "error_type": "RuntimeError", "error": "no tools"},
        "tests": {"plugin": {"passed": False, "attempt": 4}},
        "generation_retry_count": 0,
        "fix_retry_count": 5,
        "previous_run_results": [],
        "errors": [{"severity": "high", "message": "no tools"}],
    }

    assert route_after_review(state) == "generate"
    assert state["generation_retry_count"] == 1
    assert state["fix_retry_count"] == 0
    assert "run_result" not in state
    assert "plugin" not in state["tests"]
    assert state["previous_run_results"][0]["attempt"] == 4
