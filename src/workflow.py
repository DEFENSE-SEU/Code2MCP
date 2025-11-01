
import time
from typing import Dict, Any
from langgraph.graph import StateGraph, START, END
from .nodes.download_node import download_node
from .nodes.analysis_node import analysis_node
from .nodes.env_node import env_node
from .nodes.generate_node import generate_node
from .nodes.run_node import run_node
from .nodes.review_node import review_node
from .nodes.finalize_node import finalize_node
from .utils import setup_logging, should_retry_generation, should_stop_workflow

logger = setup_logging()

MAX_GENERATION_RETRIES = 5

def _route_or_end(state: Dict[str, Any], next_node: str) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return END
    return next_node

def route_after_download(state: Dict[str, Any]) -> str:
    return _route_or_end(state, "analysis")

def route_after_analysis(state: Dict[str, Any]) -> str:
    # Skip environment setup; go directly to code generation
    return _route_or_end(state, "generate")

def route_after_env(state: Dict[str, Any]) -> str:
    return _route_or_end(state, "generate")

def route_after_generate(state: Dict[str, Any]) -> str:
    return _route_or_end(state, "finalize")

def route_after_run(state: Dict[str, Any]) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return END
    
    run_result = state.get("run_result", {})
    
    if not run_result.get("success", False):
        error_info = {
            "node": "RunNode",
            "type": "RuntimeError", 
            "severity": "high",
            "message": run_result.get("error", "Execution failed"),
            "details": run_result.get("details", {}),
            "action_taken": "needs_regeneration"
        }
        state.setdefault("errors", []).append(error_info)  
        return "review"
    
    return _route_or_end(state, "review")

def route_after_review(state: Dict[str, Any]) -> str:
    if state.get("workflow_status") == "failed" or state.get("status") == "failed":
        return END
    
    # Skip retry logic, go directly to finalize
    return _route_or_end(state, "finalize")
    
    should_stop, reason = should_stop_workflow(state)
    if should_stop:
        logger.warning(f"Stopping workflow: {reason}")
        state["workflow_status"] = "failed"
        state["status"] = "failed"
        return END
    
    error_analysis = state.get("error_analysis", {})
    run_result = state.get("run_result", {})
    
    if error_analysis:
        if state.get("fix_applied") and state.get("status") == "running":
            logger.info("Review node has fixed errors, re-running tests for validation")
            if "error_analysis" in state:
                del state["error_analysis"]
            if "fix_applied" in state:
                del state["fix_applied"]
            return "run"
        
        fix_retry_count = state.get("fix_retry_count", 0)
        max_fix_retries = 10 
        
        if fix_retry_count < max_fix_retries:
            return "review"  
        
        if should_retry_generation(state, MAX_GENERATION_RETRIES):
            return "generate"
        else:
            logger.warning("Maximum retry count reached, stopping workflow")
            state["workflow_status"] = "failed"
            state["status"] = "failed"
            return END
    
    logger.info("Code execution successful, review passed, entering finalize phase")
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
            repo_name = repo_url.split("/")[-1].replace(".git", "")
            initial_state = {
                "repository": {
                    "url": repo_url,
                    "name": repo_name,
                },
                "options": options or {},
                "status": "running",
                "workflow_status": "running",
                "workflow_start_time": time.time(),
                "errors": [],
                "generation_retry_count": 0,
                "previous_run_results": [],
                "retry_reasons": [],
            }

            config = {"configurable": {"thread_id": "workflow"}}
            result = await self.app.ainvoke(initial_state, config)

            if result.get("workflow_status") == "success":
                return {"success": True, "state": result, "message": "MCP service generated successfully"}
            else:
                error_msg = result.get("error", "Unknown error")
                return {"success": False, "state": result, "message": f"Workflow failed: {error_msg}"}
        except Exception as e:
            return {"success": False, "state": None, "message": f"Workflow exception: {str(e)}"}

    def get_workflow_status(self) -> Dict[str, Any]:
        return {
            "status": "running",
            "output_dir": self.output_dir,
            "model_config": self.model_config.provider if self.model_config else None,
        }