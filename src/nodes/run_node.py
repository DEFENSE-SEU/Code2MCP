# Run Node - Execute generated MCP service
from __future__ import annotations
import os
import subprocess
import time
import json
import re
from pathlib import Path
from typing import Dict, Any
from ..utils import setup_logging, write_file, get_llm_service, redact_sensitive_data, redact_sensitive_text
from ..loop_control import append_loop_event

logger = setup_logging()
MAX_RUN_ATTEMPTS = int(os.getenv("CODE2MCP_MAX_RUN_ATTEMPTS", "12"))

def _run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8', 
            errors='replace',  
            timeout=timeout,
            shell=False,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        logger.error(f"Command execution failed: {cmd}, error: {e}")
        return 1, "", str(e)


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


def _max_client_calls(state: Dict[str, Any]) -> int:
    options = state.get("options") or {}
    raw = options.get("max_client_calls", os.getenv("CODE2MCP_MAX_CLIENT_CALLS", "-1"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _semantic_policy(state: Dict[str, Any]) -> str:
    options = state.get("options") or {}
    raw = str(
        options.get(
            "client_validation_semantic_policy",
            os.getenv("CODE2MCP_CLIENT_VALIDATION_SEMANTIC_POLICY", "all"),
        )
        or "all"
    ).strip().lower()
    return raw if raw in {"none", "any", "all"} else "all"


def _client_validation_enabled(state: Dict[str, Any]) -> bool:
    options = state.get("options") or {}
    return bool(options.get("client_validation", True))


def _client_validation_requires_semantic_success(state: Dict[str, Any]) -> bool:
    options = state.get("options") or {}
    raw = options.get(
        "client_validation_require_semantic_success",
        os.getenv("CODE2MCP_CLIENT_VALIDATION_REQUIRE_SEMANTIC_SUCCESS", "true"),
    )
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _client_validation_requires_meaningful_result(state: Dict[str, Any]) -> bool:
    options = state.get("options") or {}
    raw = options.get(
        "client_validation_require_meaningful_result",
        os.getenv("CODE2MCP_CLIENT_VALIDATION_REQUIRE_MEANINGFUL_RESULT", "true"),
    )
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _client_validation_evidence_errors(
    report: Dict[str, Any],
    *,
    require_semantic_success: bool,
    require_meaningful_result: bool,
    allow_zero_tools: bool,
) -> list[str]:
    calls = report.get("calls")
    if not isinstance(calls, list):
        calls = []
    errors: list[str] = []
    tool_count = report.get("tool_count")
    if not isinstance(tool_count, int) or isinstance(tool_count, bool):
        errors.append("Client validation report did not include a registered tool count")
    elif tool_count <= 0:
        errors.append("Client validation report registered zero tools")
    if require_semantic_success and not any(_client_call_has_successful_semantics(call) for call in calls):
        errors.append("Client validation report lacks a successful semantic tool call")
    if require_meaningful_result and not any(
        _client_call_has_successful_semantics(call, require_meaningful_result=True)
        for call in calls
    ):
        errors.append("Client validation report lacks a successful semantic tool call with a non-empty result")
    return errors


def _client_call_has_successful_semantics(call: Any, *, require_meaningful_result: bool = False) -> bool:
    return bool(
        isinstance(call, dict)
        and call.get("passed") is True
        and call.get("is_error") is not True
        and call.get("semantic_success") is True
        and (not require_meaningful_result or call.get("semantic_evidence") is True)
    )


def _run_fastmcp_client_validation(base_cmd: list[str], repo_root: str, state: Dict[str, Any]) -> Dict[str, Any]:
    options = state.get("options") or {}
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "scripts" / "validate_mcp_service.py"
    max_calls = _max_client_calls(state)
    timeout = int(options.get("client_validation_timeout", _env_int("CODE2MCP_CLIENT_VALIDATION_TIMEOUT", 240)))
    require_semantic = _client_validation_requires_semantic_success(state)
    semantic_policy = _semantic_policy(state)
    require_meaningful = _client_validation_requires_meaningful_result(state)
    allow_zero_tools = bool(options.get("allow_zero_tools", False))

    command = [
        *base_cmd,
        str(script_path),
        "--repo-root",
        repo_root,
        "--min-tools",
        "0" if allow_zero_tools else "1",
        "--auto-call",
        "--max-calls",
        str(max_calls),
        "--require-call",
        "--semantic-policy",
        semantic_policy,
    ]
    if allow_zero_tools:
        command.append("--allow-zero-tools")
    if require_semantic:
        command.append("--require-semantic-success")
    if require_meaningful:
        command.append("--require-meaningful-result")

    code, out, err = _run(command, cwd=str(project_root), timeout=timeout)
    safe_out = redact_sensitive_text(out)
    safe_err = redact_sensitive_text(err)
    parsed: Dict[str, Any] = {}
    parse_error = ""
    if out:
        try:
            loaded = json.loads(out)
            if isinstance(loaded, dict):
                parsed = loaded
                safe_out = json.dumps(redact_sensitive_data(parsed), ensure_ascii=False)
            else:
                parse_error = "client validation output JSON was not an object"
        except json.JSONDecodeError as exc:
            parsed = {}
            parse_error = f"client validation output was not valid JSON: {exc}"
    else:
        parse_error = "client validation produced no JSON output"
    errors = list(parsed.get("errors", [])) if isinstance(parsed.get("errors", []), list) else []
    if parse_error:
        errors.append(parse_error)
    evidence_errors = []
    if parsed.get("passed") is True:
        evidence_errors = _client_validation_evidence_errors(
            parsed,
            require_semantic_success=require_semantic,
            require_meaningful_result=require_meaningful,
            allow_zero_tools=allow_zero_tools,
        )
        errors.extend(evidence_errors)
    return {
        "passed": code == 0 and not parse_error and not evidence_errors and parsed.get("passed") is True,
        "exit_code": code,
        "stdout": safe_out[-4000:] if safe_out else "",
        "stderr": safe_err[-4000:] if safe_err else "",
        "tool_count": parsed.get("tool_count"),
        "tools": redact_sensitive_data(parsed.get("tools", [])),
        "calls": redact_sensitive_data(parsed.get("calls", [])),
        "errors": redact_sensitive_data(errors),
        "evidence_errors": redact_sensitive_data(evidence_errors),
        "skipped_auto_calls": redact_sensitive_data(parsed.get("skipped_auto_calls", [])),
        "semantic_policy": parsed.get("semantic_policy", semantic_policy),
        "require_semantic_success": bool(parsed.get("require_semantic_success", require_semantic)),
        "require_meaningful_result": bool(parsed.get("require_meaningful_result", require_meaningful)),
        "zero_tools_allowed": bool(parsed.get("zero_tools_allowed")),
        "warnings": redact_sensitive_data(parsed.get("warnings", [])),
        "command": command,
    }


def _client_validation_failure_text(client_validation: Dict[str, Any]) -> str:
    """Build a compact, actionable failure summary from strict client validation."""
    parts: list[str] = []
    errors = client_validation.get("errors", [])
    if isinstance(errors, list):
        clean_errors = [str(item) for item in errors if str(item or "").strip()]
        if clean_errors:
            parts.append("Client validation errors: " + "; ".join(clean_errors))

    failed_calls: list[str] = []
    calls = client_validation.get("calls", [])
    if isinstance(calls, list):
        for call in calls:
            if not isinstance(call, dict):
                continue
            transport_failed = call.get("transport_passed", call.get("passed", True)) is False
            semantic_failed = call.get("semantic_success") is False or call.get("semantic_passed") is False
            evidence_failed = call.get("semantic_evidence") is False
            if not (transport_failed or semantic_failed or evidence_failed or call.get("is_error")):
                continue
            tool = str(call.get("tool") or "unknown")
            detail = ""
            data = call.get("data")
            if isinstance(data, dict):
                detail = str(data.get("error") or data.get("result") or "")
            if not detail:
                detail = str(call.get("error") or "")
            if not detail:
                if semantic_failed:
                    detail = "semantic success check failed"
                elif evidence_failed:
                    detail = "meaningful result check failed"
                else:
                    detail = "transport call failed"
            failed_calls.append(f"{tool}: {detail}")
    if failed_calls:
        parts.append("Failed client calls: " + "; ".join(failed_calls[:5]))

    warnings = client_validation.get("warnings", [])
    if isinstance(warnings, list):
        clean_warnings = [str(item) for item in warnings if str(item or "").strip()]
        if clean_warnings:
            parts.append("Client validation warnings: " + "; ".join(clean_warnings[:5]))

    stderr = str(client_validation.get("stderr") or "").strip()
    if stderr:
        parts.append("Client validation stderr: " + stderr[-1000:])
    return redact_sensitive_text("\n".join(parts))


def run_node(state: Dict[str, Any]) -> Dict[str, Any]:
    attempt = int(state.get("run_attempt_count", 0)) + 1
    state["run_attempt_count"] = attempt
    state.pop("fix_applied", None)
    state.pop("review_decision", None)
    append_loop_event(
        state,
        "run_started",
        attempt=attempt,
        generation_attempt=state.get("generation_retry_count", 0),
        fix_attempts=state.get("fix_retry_count", 0),
    )

    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    mcp_logs_dir = repo.get("local_paths", {}).get("mcp_logs")
    plugin = state.get("plugin", {}).get("files", {})
    mcp_py = plugin.get("mcp_output/start_mcp.py") or os.path.join(repo_root or "", "mcp_output", "start_mcp.py")
    if not (repo_root and os.path.isfile(mcp_py)):
        state.setdefault("errors", []).append({
            "node": "RunNode",
            "type": "InvalidInput",
            "message": "Missing start_mcp.py",
            "action_taken": "abort"
        })
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    logger.info("Checking start_mcp.py executability in target environment")
    env_info = state.get("env", {})
    if env_info.get("type") == "conda":
        # Prefer absolute python path recorded by env_node.exec_prefix to avoid slow conda run cold start
        exec_prefix = env_info.get("exec_prefix") or []
        if exec_prefix and os.path.isfile(exec_prefix[0]):
            base_cmd = [exec_prefix[0]]
            logger.info(f"Using env python: {exec_prefix[0]}")
        else:
            conda_exe = os.environ.get("CONDA_EXE")
            if not conda_exe or not os.path.exists(conda_exe):
                from .env_node import _check_conda_available
                if _check_conda_available():
                    conda_exe = os.environ.get("CONDA_EXE")
            if not conda_exe or not os.path.exists(conda_exe):
                logger.error("Conda executable not found, cannot execute conda commands")
                state.setdefault("errors", []).append({
                    "node": "RunNode",
                    "type": "CondaNotFound",
                    "message": "Conda executable not available",
                    "action_taken": "skip_conda_commands"
                })
                base_cmd = ["python"]
            else:
                conda_env_name = env_info.get("name", "")
                logger.info(f"Using conda environment: {conda_env_name}")
                logger.info(f"Conda executable: {conda_exe}")
                logger.info(f"Working directory: {repo_root}")
                base_cmd = [conda_exe, "run", "-n", conda_env_name, "--cwd", repo_root, "python"]
    elif env_info.get("type") == "venv" and env_info.get("exec_prefix"):
        base_cmd = env_info["exec_prefix"]
    else:
        base_cmd = ["python"]
    
    mcp_plugin_dir = os.path.join(repo_root, "mcp_output", "mcp_plugin")
    if not os.path.exists(mcp_plugin_dir):
        logger.warning("MCP service directory does not exist")

    code, out, err = _run(base_cmd + ["-c", "import fastmcp; print('ok')"], cwd=repo_root)
    if code != 0:
        _run(base_cmd + ["-m", "pip", "install", "-U", "pip"], cwd=repo_root)
        _run(base_cmd + ["-m", "pip", "install", "fastmcp>=0.1.0"], cwd=repo_root)
    
    smoke_dir = os.path.join(repo_root, "mcp_output", "tests_smoke")
    os.makedirs(smoke_dir, exist_ok=True)
    
    cpp = (state.get("analysis") or {}).get("cpp_info", {})
    if cpp.get("has_cpp_files"):
        pkg = cpp.get("main_package") or ""
        paths = []
        p1 = os.path.join(repo_root, "source", "build")
        if os.path.isdir(p1):
            paths.append(p1)
        paths.append(os.path.join(repo_root, "source"))
        script = os.path.join(smoke_dir, "test_cpp_import.py")
        lines = ["import sys,os"]
        for p in paths:
            lines.append(f"sys.path.insert(0, r'{p}')")
        if pkg:
            lines.append(f"import {pkg}")
        lines.append("print('OK')")
        write_file(script, "\n".join(lines))
        if env_info.get("type") == "conda":
            rel = os.path.relpath(script, repo_root)
            c2, o2, e2 = _run(base_cmd + [rel], cwd=repo_root)
        else:
            c2, o2, e2 = _run(base_cmd + [script], cwd=repo_root)
        if c2 != 0 or "OK" not in (o2 or ""):
            logger.warning(f"C++ import test failed: {e2 or o2}")
    
    tests_mcp_dir = repo.get("local_paths", {}).get("tests_mcp")
    passed = False
    code, out, err = 1, "", ""
    if tests_mcp_dir:
        test_basic_py = os.path.join(tests_mcp_dir, "test_mcp_basic.py")
        if os.path.isfile(test_basic_py):
            logger.info("Running MCP tests")
            if env_info.get("type") == "conda":
                rel_test_path = os.path.relpath(test_basic_py, repo_root)
                logger.info(f"Using relative path to run tests: {rel_test_path}")
                code, out, err = _run(base_cmd + [rel_test_path], cwd=repo_root)
            else:
                code, out, err = _run(base_cmd + [test_basic_py], cwd=repo_root)
            if code == 0:
                logger.info("MCP service test passed")
                passed = True
    if not passed:
        smoke_script = os.path.join(smoke_dir, "mcp_import_min.py")
        allow_zero_tools = bool((state.get("options") or {}).get("allow_zero_tools", False))
        smoke_code = f"""
import sys, os
import asyncio
import inspect
sys.path.insert(0, r'{mcp_plugin_dir}')
service_file = os.path.join(r'{mcp_plugin_dir}', 'mcp_service.py')
if os.path.isfile(service_file):
    with open(service_file, 'r', encoding='utf-8-sig', errors='ignore') as handle:
        service_source = handle.read()
    if 'no_import_available' in service_source:
        raise RuntimeError('Generated MCP service only exposes a no_import_available fallback tool')
from mcp_service import create_app
app = create_app()
def _count_tools(mcp_app):
    list_tools = getattr(mcp_app, 'list_tools', None)
    if callable(list_tools):
        value = list_tools()
        if inspect.isawaitable(value):
            value = asyncio.run(value)
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, (list, tuple, set)):
            return len(value)
    for attr in ('_tools', 'tools'):
        value = getattr(mcp_app, attr, None)
        if isinstance(value, dict):
            return len(value)
    manager = getattr(mcp_app, '_tool_manager', None)
    if manager is not None:
        value = getattr(manager, '_tools', None)
        if isinstance(value, dict):
            return len(value)
    return -1
tool_count = _count_tools(app)
if tool_count <= 0 and not {allow_zero_tools!r}:
    raise RuntimeError(f'FastMCP app registered no tools (count={{tool_count}})')
print(f'OK tools={{tool_count}}')
"""
        write_file(smoke_script, smoke_code)
        if env_info.get("type") == "conda":
            rel_smoke = os.path.relpath(smoke_script, repo_root)
            code, out, err = _run(base_cmd + [rel_smoke], cwd=repo_root, timeout=60)
        else:
            code, out, err = _run(base_cmd + [smoke_script], cwd=repo_root, timeout=60)
        passed = (code == 0 and "OK" in (out or ""))

    client_validation: Dict[str, Any] = {"passed": False, "skipped": True, "reason": "plugin_smoke_failed" if not passed else "disabled"}
    if passed:
        if _client_validation_enabled(state):
            client_validation = _run_fastmcp_client_validation(base_cmd, repo_root, state)
            if client_validation.get("tool_count") is not None:
                tool_count = client_validation.get("tool_count")
            if not client_validation.get("passed"):
                passed = False
                code = int(client_validation.get("exit_code") or 1)
                out = client_validation.get("stdout", "")
                err = _client_validation_failure_text(client_validation)
        else:
            passed = False
            code = 1
            err = "FastMCP Client validation is disabled; refusing to pass without real client tool-call evidence"
            client_validation["errors"] = [err]

    tool_count = None
    if out:
        match = re.search(r"tools=(-?\d+)", out)
        if match:
            tool_count = int(match.group(1))
    if client_validation.get("tool_count") is not None:
        tool_count = client_validation.get("tool_count")

    plugin_test_result = {
        "passed": passed,
        "report_path": None,
        "stdout": redact_sensitive_text(out)[-1000:] if 'out' in locals() else "",
        "stderr": redact_sensitive_text(err)[-1000:] if 'err' in locals() else "",
        "tool_count": tool_count,
        "attempt": attempt,
        "client_validation": client_validation,
    }
    state.setdefault("tests", {})["plugin"] = plugin_test_result

    run_result = {
        "success": passed,
        "test_passed": passed,
        "exit_code": code,
        "stdout": redact_sensitive_text(out)[-1000:] if out else "",
        "stderr": redact_sensitive_text(err)[-1000:] if err else "",
        "timestamp": time.time(),
        "attempt": attempt,
        "generation_attempt": state.get("generation_retry_count", 0),
        "fix_attempts": state.get("fix_retry_count", 0),
        "client_validation": client_validation,
    }
    
    if not passed:
        error_message = redact_sensitive_text(err or out or "Unknown runtime error")
        if "No module named" in error_message:
            run_result["error_type"] = "ImportError"
            run_result["error"] = f"Module import failed: {error_message}"
        elif "ImportError" in error_message:
            run_result["error_type"] = "ImportError" 
            run_result["error"] = f"Import error: {error_message}"
        elif "SyntaxError" in error_message:
            run_result["error_type"] = "SyntaxError"
            run_result["error"] = f"Syntax error: {error_message}"
        else:
            run_result["error_type"] = "RuntimeError"
            run_result["error"] = f"Runtime error: {error_message}"
        
        run_result["details"] = {
            "command": " ".join(base_cmd + [mcp_py]),
            "working_directory": repo_root,
            "environment_type": env_info.get("type", "unknown")
        }
    
    state["run_result"] = run_result

    if mcp_logs_dir:
        run_log = {
            "timestamp": time.time(),
            "node": "RunNode",
            "test_result": plugin_test_result,
            "run_result": run_result,
            "environment": state.get("env", {}),
            "plugin_info": state.get("plugin", {}),
            "fastmcp_installed": code == 0 or "fastmcp" in out
        }
        
        run_log_path = os.path.join(mcp_logs_dir, "run_log.json")
        try:
            write_file(run_log_path, json.dumps(redact_sensitive_data(run_log), ensure_ascii=False, indent=2))
            logger.info(f"Run log saved to: {run_log_path}")
        except Exception as e:
            logger.warning(f"Failed to save run log: {e}")
        
        try:
            from ..utils import get_llm_statistics
            llm_stats = get_llm_statistics()
            llm_stats_path = os.path.join(mcp_logs_dir, "llm_statistics.json")
            write_file(llm_stats_path, json.dumps(redact_sensitive_data(llm_stats), ensure_ascii=False, indent=2))
        except Exception as e:
            pass

    if not passed:
        state.setdefault("errors", []).append({
            "node": "RunNode",
            "type": "PluginSmokeFailed",
            "severity": "high",
            "message": run_result.get("error", err or out),
            "action_taken": "send_to_review",
            "attempt": attempt,
        })
        append_loop_event(
            state,
            "run_failed",
            attempt=attempt,
            error_type=run_result.get("error_type"),
            error=run_result.get("error", "")[:500],
        )
        if attempt >= MAX_RUN_ATTEMPTS:
            state["status"] = "failed"
            state["workflow_status"] = "failed"
            state["error"] = f"Maximum run attempts reached ({MAX_RUN_ATTEMPTS}) before successful validation"
            append_loop_event(
                state,
                "run_attempt_budget_exhausted",
                attempt=attempt,
                max_run_attempts=MAX_RUN_ATTEMPTS,
            )
    else:
        append_loop_event(
            state,
            "run_passed",
            attempt=attempt,
            tool_count=tool_count,
        )

    if state.get("workflow_status") != "failed":
        state["status"] = "running"
        state["workflow_status"] = state.get("workflow_status", "running")
    return state
