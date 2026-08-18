# Run Node - Execute generated MCP service
from __future__ import annotations
import os
import subprocess
import time
import json
from typing import Dict, Any
from ..utils import setup_logging, write_file, get_llm_service

logger = setup_logging()

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


def run_node(state: Dict[str, Any]) -> Dict[str, Any]:
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
        smoke_code = f"""
import sys, os
sys.path.insert(0, r'{mcp_plugin_dir}')
from mcp_service import create_app
app = create_app()
print('OK')
"""
        write_file(smoke_script, smoke_code)
        if env_info.get("type") == "conda":
            rel_smoke = os.path.relpath(smoke_script, repo_root)
            code, out, err = _run(base_cmd + [rel_smoke], cwd=repo_root, timeout=60)
        else:
            code, out, err = _run(base_cmd + [smoke_script], cwd=repo_root, timeout=60)
        passed = (code == 0 and "OK" in (out or ""))
    
    plugin_test_result = {"passed": passed, "report_path": None, "stdout": out[-1000:] if 'out' in locals() else "", "stderr": err[-1000:] if 'err' in locals() else ""}
    state.setdefault("tests", {})["plugin"] = plugin_test_result

    run_result = {
        "success": passed,
        "test_passed": passed,
        "exit_code": code,
        "stdout": out[-1000:] if out else "",
        "stderr": err[-1000:] if err else "",
        "timestamp": time.time()
    }
    
    if not passed:
        error_message = err or out or "Unknown runtime error"
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
            "command": " ".join(base_cmd + [rel_mcp_py if env_info.get("type") == "conda" else mcp_py]),
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
            write_file(run_log_path, json.dumps(run_log, ensure_ascii=False, indent=2))
            logger.info(f"Run log saved to: {run_log_path}")
        except Exception as e:
            logger.warning(f"Failed to save run log: {e}")
        
        try:
            from ..utils import get_llm_statistics
            llm_stats = get_llm_statistics()
            llm_stats_path = os.path.join(mcp_logs_dir, "llm_statistics.json")
            write_file(llm_stats_path, json.dumps(llm_stats, ensure_ascii=False, indent=2))
        except Exception as e:
            pass

    if not passed:
        state.setdefault("errors", []).append({
            "node": "RunNode",
            "type": "PluginSmokeFailed",
            "severity": "high",
            "message": run_result.get("error", err or out),
            "action_taken": "record_only"
        })

    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state