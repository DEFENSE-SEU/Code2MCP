
from __future__ import annotations

import os
import time
from typing import Dict, Any
from langgraph.graph import StateGraph, START, END
from .nodes.download_node import download_node
from .nodes.analysis_node import analysis_node
from .nodes.env_node import env_node
from .nodes.generate_node import generate_node
from .nodes.run_node import run_node
from .nodes.review_node import review_node, _runtime_success_evidence_errors
from .nodes.finalize_node import finalize_node
from .utils import derive_repo_name, setup_logging, should_retry_generation, should_stop_workflow
from .loop_control import append_loop_event, archive_failed_run_once, clear_runtime_validation

logger = setup_logging()

MAX_GENERATION_RETRIES = int(os.getenv("CODE2MCP_MAX_GENERATION_RETRIES", "5"))
MAX_FIX_RETRIES = int(os.getenv("CODE2MCP_MAX_FIX_RETRIES", "5"))
MAX_RUN_ATTEMPTS = int(os.getenv("CODE2MCP_MAX_RUN_ATTEMPTS", "12"))


def _workflow_recursion_limit() -> int:
    """Keep LangGraph's guard above Code2MCP's own retry budgets."""
    raw = os.getenv("CODE2MCP_WORKFLOW_RECURSION_LIMIT", "").strip()
    if raw:
        try:
            return max(25, int(raw))
        except ValueError:
            logger.warning("Ignoring invalid CODE2MCP_WORKFLOW_RECURSION_LIMIT=%r", raw)
    budgeted_steps = 20 + ((MAX_RUN_ATTEMPTS + MAX_GENERATION_RETRIES + MAX_FIX_RETRIES + 3) * 6)
    return max(100, budgeted_steps)

def _route_or_end(state: Dict[str, Any], next_node: str) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return "finalize"
    return next_node


def _fail_workflow(state: Dict[str, Any], reason: str, *, event: str = "workflow_failed") -> str:
    state["workflow_status"] = "failed"
    state["status"] = "failed"
    state["error"] = reason
    append_loop_event(state, event, reason=reason)
    return "finalize"


def _review_budget(state: Dict[str, Any]) -> tuple[int, int]:
    return int(state.get("fix_retry_count", 0)), int(state.get("generation_retry_count", 0))


def _start_regeneration(state: Dict[str, Any], reason: str) -> str:
    if state.pop("regeneration_prepared", False):
        append_loop_event(
            state,
            "route_review_to_generate",
            reason=reason,
            generation_attempt=state.get("generation_retry_count", 0),
        )
        logger.info("Review prepared regeneration; routing to generate")
        return "generate"

    fix_retry_count, generation_retry_count = _review_budget(state)
    if generation_retry_count >= MAX_GENERATION_RETRIES:
        return _fail_workflow(
            state,
            f"Maximum regeneration attempts reached ({MAX_GENERATION_RETRIES}) after {reason}",
            event="regeneration_budget_exhausted",
        )

    archive_failed_run_once(state, reason=reason)
    state["generation_retry_count"] = generation_retry_count + 1
    state["fix_retry_count"] = 0
    state.pop("review_decision", None)
    state.pop("error_analysis", None)
    clear_runtime_validation(state)
    append_loop_event(
        state,
        "regeneration_started",
        generation_attempt=state.get("generation_retry_count", 0),
        previous_fix_attempts=fix_retry_count,
        reason=reason,
    )
    logger.info("Review requested regeneration of MCP service")
    return "generate"


def _failed_run_pending(state: Dict[str, Any]) -> bool:
    run_result = state.get("run_result", {})
    return isinstance(run_result, dict) and bool(run_result) and not run_result.get("success", False)

def route_after_download(state: Dict[str, Any]) -> str:
    return _route_or_end(state, "analysis")

def route_after_analysis(state: Dict[str, Any]) -> str:
    return _route_or_end(state, "env")

def route_after_env(state: Dict[str, Any]) -> str:
    return _route_or_end(state, "generate")

def route_after_generate(state: Dict[str, Any]) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return "finalize"
    if (state.get("options") or {}).get("generate_only"):
        return "finalize"
    return "run"

def route_after_run(state: Dict[str, Any]) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return "finalize"
    
    run_result = state.get("run_result", {})
    
    if not run_result.get("success", False):
        attempt = run_result.get("attempt")
        if isinstance(attempt, int) and attempt >= MAX_RUN_ATTEMPTS:
            return _fail_workflow(
                state,
                f"Maximum run attempts reached ({MAX_RUN_ATTEMPTS}) before successful validation",
                event="run_attempt_budget_exhausted",
            )
        already_recorded = any(
            error.get("node") == "RunNode" and error.get("attempt") == attempt
            for error in state.get("errors", [])
        )
        if not already_recorded:
            error_info = {
                "node": "RunNode",
                "type": "RuntimeError",
                "severity": "high",
                "message": run_result.get("error", "Execution failed"),
                "details": run_result.get("details", {}),
                "action_taken": "send_to_review",
                "attempt": attempt,
            }
            state.setdefault("errors", []).append(error_info)
        return "review"
    
    return _route_or_end(state, "review")

def route_after_review(state: Dict[str, Any]) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return "finalize"

    decision = state.pop("review_decision", None)
    fix_retry_count, _generation_retry_count = _review_budget(state)

    if state.pop("fix_applied", False):
        logger.info("Review applied a fix; re-running generated MCP smoke tests")
        archive_failed_run_once(state, reason="fixed")
        clear_runtime_validation(state)
        state.pop("error_analysis", None)
        append_loop_event(
            state,
            "route_review_to_run",
            reason="fix_applied",
            fix_attempts=fix_retry_count,
        )
        return "run"

    if decision == "run":
        logger.info("Review requested re-run of generated MCP smoke tests")
        archive_failed_run_once(state, reason="review_requested_run")
        clear_runtime_validation(state)
        state.pop("error_analysis", None)
        append_loop_event(
            state,
            "route_review_to_run",
            reason="review_requested_run",
            fix_attempts=fix_retry_count,
        )
        return "run"

    if decision == "review":
        if not _failed_run_pending(state):
            return _fail_workflow(
                state,
                "Review requested another repair attempt without failed runtime evidence",
                event="review_missing_failed_run",
            )
        if fix_retry_count >= MAX_FIX_RETRIES:
            logger.info("Direct fix attempts exhausted; escalating to regeneration")
            return _start_regeneration(state, "fix_budget_exhausted")
        logger.info("Review requested another direct repair attempt with the same runtime evidence")
        append_loop_event(
            state,
            "route_review_retry",
            fix_attempts=fix_retry_count,
            max_fix_attempts=MAX_FIX_RETRIES,
        )
        return "review"

    if decision == "finalize":
        if _failed_run_pending(state):
            return _fail_workflow(
                state,
                "Review attempted to finalize while the latest runtime validation is still failed",
                event="review_finalize_blocked",
            )
        run_result = state.get("run_result")
        evidence_errors = (
            _runtime_success_evidence_errors(state, run_result)
            if isinstance(run_result, dict) and run_result.get("success") is True
            else ["Review attempted to finalize without successful runtime evidence"]
        )
        if evidence_errors:
            state["runtime_validation_evidence_errors"] = evidence_errors
            clear_runtime_validation(state)
            append_loop_event(
                state,
                "review_finalize_revalidation_required",
                errors=evidence_errors,
            )
            return "run"
        return _route_or_end(state, "finalize")

    if decision == "fail":
        error_analysis = state.get("error_analysis", {}) or {}
        return _fail_workflow(
            state,
            error_analysis.get("summary", "Review determined the workflow cannot be repaired automatically"),
            event="review_marked_failed",
        )

    should_stop, reason = should_stop_workflow(state)
    if should_stop:
        logger.warning(f"Stopping workflow: {reason}")
        return _fail_workflow(state, reason, event="review_stop_policy")

    error_analysis = state.get("error_analysis", {}) or {}

    if error_analysis.get("next_action") == "fail":
        logger.warning(f"Review marked failure as not automatically repairable: {error_analysis.get('summary', '')}")
        return _fail_workflow(
            state,
            error_analysis.get("summary", "Runtime validation failed and cannot be repaired automatically"),
            event="review_marked_failed",
        )

    if decision == "regenerate" or error_analysis.get("next_action") == "regenerate":
        if state.get("regeneration_prepared"):
            return _start_regeneration(state, "regenerate")
        if not should_retry_generation(state, MAX_GENERATION_RETRIES):
            return _fail_workflow(
                state,
                "Review requested regeneration, but retry policy rejected another generation attempt",
                event="regeneration_rejected",
            )
        return _start_regeneration(state, "regenerate")

    if _failed_run_pending(state):
        if fix_retry_count < MAX_FIX_RETRIES:
            logger.info("Review did not fix the error yet; retrying review")
            append_loop_event(
                state,
                "route_review_retry",
                fix_attempts=fix_retry_count,
                max_fix_attempts=MAX_FIX_RETRIES,
            )
            return "review"

        if should_retry_generation(state, MAX_GENERATION_RETRIES):
            logger.info("Direct fixes exhausted; regenerating MCP service")
            return _start_regeneration(state, "fix_budget_exhausted")

        logger.warning("Maximum review/regeneration attempts reached")
        return _fail_workflow(
            state,
            "Maximum review/regeneration attempts reached",
            event="repair_budget_exhausted",
        )

    return _route_or_end(state, "finalize")

def route_after_finalize(state: Dict[str, Any]) -> str:
    return END

class WorkflowOrchestrator:
    def __init__(self, output_dir: str = "./output", config: object = None):
        self.output_dir = output_dir
        self.config = config
        self.model_config = None
        self.workflow = self._create_workflow()
        self.app = self.workflow.compile()

    def _create_workflow(self) -> StateGraph:
        workflow = StateGraph(Dict[str, Any])
        workflow.add_node("download", download_node)
        workflow.add_node("analysis", analysis_node)
        workflow.add_node("env", env_node)
        workflow.add_node("generate", generate_node)
        workflow.add_node("run", run_node)
        workflow.add_node("review", review_node)
        workflow.add_node("finalize", finalize_node)
        workflow.add_edge(START, "download")
        workflow.add_conditional_edges("download", route_after_download)
        workflow.add_conditional_edges("analysis", route_after_analysis)
        workflow.add_conditional_edges("env", route_after_env)
        workflow.add_conditional_edges("generate", route_after_generate)
        workflow.add_conditional_edges("run", route_after_run)
        workflow.add_conditional_edges("review", route_after_review)
        workflow.add_conditional_edges("finalize", route_after_finalize)
        return workflow

    async def run_workflow(self, repo_url: str, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            repo_url = (repo_url or "").strip()
            if repo_url.startswith("@"):
                repo_url = repo_url[1:].strip()
            repo_name = derive_repo_name(repo_url)
            workflow_options = dict(options or {})
            workflow_options.setdefault("output_dir", self.output_dir)
            initial_state = {
                "repository": {
                    "url": repo_url,
                    "name": repo_name,
                },
                "options": workflow_options,
                "status": "running",
                "workflow_status": "running",
                "workflow_start_time": time.time(),
                "errors": [],
                "generation_retry_count": 0,
                "fix_retry_count": 0,
                "previous_run_results": [],
                "retry_reasons": [],
                "repair_loop": {
                    "budgets": {
                        "max_generation_retries": MAX_GENERATION_RETRIES,
                        "max_fix_retries": MAX_FIX_RETRIES,
                        "max_run_attempts": MAX_RUN_ATTEMPTS,
                    },
                    "events": [],
                },
            }

            config = {
                "configurable": {"thread_id": "workflow"},
                "recursion_limit": _workflow_recursion_limit(),
            }
            result = await self.app.ainvoke(initial_state, config)
            workflow_status = result.get("workflow_status")

            if workflow_status == "validated":
                return {
                    "success": True,
                    "completed": True,
                    "validated": True,
                    "workflow_status": "validated",
                    "state": result,
                    "message": "MCP service generated and validated successfully",
                }
            if workflow_status == "generated":
                return {
                    "success": False,
                    "completed": True,
                    "validated": False,
                    "workflow_status": "generated",
                    "state": result,
                    "message": "MCP service generated without runtime validation",
                }
            else:
                error_msg = result.get("error", "Unknown error")
                return {
                    "success": False,
                    "completed": False,
                    "validated": False,
                    "workflow_status": workflow_status or "failed",
                    "state": result,
                    "message": f"Workflow failed: {error_msg}",
                }
        except Exception as e:
            return {
                "success": False,
                "completed": False,
                "validated": False,
                "workflow_status": "failed",
                "state": None,
                "message": f"Workflow exception: {str(e)}",
            }

    def get_workflow_status(self) -> Dict[str, Any]:
        return {
            "status": "running",
            "output_dir": self.output_dir,
            "model_config": self.model_config.provider if self.model_config else None,
        }
