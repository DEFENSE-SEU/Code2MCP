# Clone GitHub repository to isolated workspace
from __future__ import annotations
import os
import subprocess
import shutil
import stat
import time
from typing import Dict, Any
from ..utils import derive_repo_name, local_path_from_repo_url, setup_logging, ensure_directory, get_project_root

logger = setup_logging()

def _run(cmd: list[str], cwd: str | None = None, timeout: int = 600) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 1, "", str(e)


def _remove_tree(path: str, retries: int = 5, delay: float = 0.5) -> tuple[bool, str]:
    """Remove a tree with Windows-friendly retries for read-only or locked files."""
    if not os.path.exists(path):
        return True, ""

    def _onerror(func, value, exc_info):
        try:
            os.chmod(value, stat.S_IWRITE)
            func(value)
        except Exception:
            raise

    last_error = ""
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return True, ""
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return False, last_error


def _clone_repository(repo_url: str, source_dir: str) -> tuple[int, str, str]:
    depth = (os.getenv("CODE2MCP_GIT_DEPTH") or "1").strip()
    base_cmd = ["git", "clone"]
    if depth and depth != "0":
        base_cmd.extend(["--depth", depth])
    base_cmd.extend([repo_url, source_dir])

    attempts = int(os.getenv("CODE2MCP_GIT_CLONE_RETRIES", "3"))
    last: tuple[int, str, str] = (1, "", "clone not attempted")
    for attempt in range(max(1, attempts)):
        code, out, err = _run(base_cmd)
        last = (code, out, err)
        if code == 0:
            return last

        removed, remove_error = _remove_tree(source_dir)
        if not removed:
            return 1, out, f"{err}\nFailed to remove partial clone: {remove_error}".strip()
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    return last


def _copy_local_repository(local_path: str, source_dir: str) -> tuple[int, str, str]:
    source_abs = os.path.abspath(local_path)
    target_abs = os.path.abspath(source_dir)
    if not os.path.isdir(source_abs):
        return 1, "", f"Local repository path is not a directory: {source_abs}"
    try:
        common = os.path.commonpath([source_abs, target_abs])
    except ValueError:
        common = ""
    if common == source_abs:
        return 1, "", "Refusing to copy a repository into a child of itself"

    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        "mcp_output",
        "deployment",
        ".venv",
        "venv",
        "env",
        "build",
        "dist",
    )
    try:
        shutil.copytree(source_abs, target_abs, ignore=ignore)
        return 0, f"Copied local repository from {source_abs}", ""
    except Exception as exc:
        return 1, "", str(exc)


def download_node(state: Dict[str, Any]) -> Dict[str, Any]:
    repo_url = state.get("repository", {}).get("url")
    if not repo_url:
        state.setdefault("errors", []).append({
            "node": "DownloadNode",
            "type": "InvalidInput",
            "message": "Missing repository.url",
            "action_taken": "abort"
        })
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    repo_name = state.get("repository", {}).get("name")
    if not repo_name:
        repo_name = derive_repo_name(repo_url)

    project_root = get_project_root()
    repo_root = os.path.join(project_root, "workspace", repo_name)
    source_dir = os.path.join(repo_root, "source")  
    
    ensure_directory(repo_root)

    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    ensure_directory(mcp_output_dir)
    
    mcp_plugin_dir = os.path.join(mcp_output_dir, "mcp_plugin")
    tests_mcp_dir = os.path.join(mcp_output_dir, "tests_mcp")
    mcp_logs_dir = os.path.join(mcp_output_dir, "mcp_logs")
    
    ensure_directory(mcp_plugin_dir)
    ensure_directory(tests_mcp_dir)
    ensure_directory(mcp_logs_dir)

    local_source = local_path_from_repo_url(repo_url)
    source_git_dir = os.path.join(source_dir, ".git")
    if local_source or not os.path.exists(source_git_dir):
        logger.info(f"Preparing repository source at: {source_dir}")

        if os.path.exists(source_dir):
            removed, remove_error = _remove_tree(source_dir)
            if not removed:
                state.setdefault("errors", []).append({
                    "node": "DownloadNode",
                    "type": "SourceCleanupFailed",
                    "message": remove_error,
                    "action_taken": "abort"
                })
                state["status"] = "failed"
                state["workflow_status"] = "failed"
                return state

        legacy_temp_clone_dir = os.path.join(repo_root, "temp_clone")
        if os.path.exists(legacy_temp_clone_dir):
            removed, remove_error = _remove_tree(legacy_temp_clone_dir)
            if not removed:
                state.setdefault("warnings", []).append(
                    f"Could not clean legacy temp clone directory: {remove_error}"
                )

        if local_source:
            logger.info(f"Copying local repository source from: {local_source}")
            code, out, err = _copy_local_repository(local_source, source_dir)
        else:
            code, out, err = _clone_repository(repo_url, source_dir)
        if code != 0:
            logger.warning(f"Repository source preparation failed. Error: {err}")
            state.setdefault("warnings", []).append(f"repository source preparation failed: {err or out}")
            state.setdefault("errors", []).append({
                "node": "DownloadNode",
                "type": "SourcePreparationFailed" if local_source else "CloneFailed",
                "message": err or out,
                "action_taken": "abort"
            })
            state["status"] = "failed"
            state["workflow_status"] = "failed"
            return state
        else:
            logger.info(f"Repository source prepared successfully to: {source_dir}")
    else:
        logger.info(f"Source code already exists: {source_dir}")

    state.setdefault("repository", {})
    state["repository"].update({
        "url": repo_url,
        "name": repo_name,
        "local_paths": {
            "repo_root": repo_root,
            "source_root": source_dir,  
            "mcp_plugin": mcp_plugin_dir,
            "tests_mcp": tests_mcp_dir,
            "mcp_logs": mcp_logs_dir,
        }
    })
    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state

