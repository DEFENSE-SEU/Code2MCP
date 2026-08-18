# Clone GitHub repository to isolated workspace
from __future__ import annotations
import os
import subprocess
import shutil
from typing import Dict, Any
from ..utils import setup_logging, ensure_directory, get_project_root

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
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

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

    source_git_dir = os.path.join(source_dir, ".git")
    if not os.path.exists(source_git_dir):
        logger.info(f"Cloning repository to: {source_dir}")
        
        if os.path.exists(source_dir):
            shutil.rmtree(source_dir)
        os.makedirs(source_dir)
        
        temp_clone_dir = os.path.join(repo_root, "temp_clone")
        if os.path.exists(temp_clone_dir):
            shutil.rmtree(temp_clone_dir)
        
        code, out, err = _run(["git", "clone", repo_url, temp_clone_dir])
        if code != 0:
            logger.warning(f"git clone failed. Error: {err}")
            state.setdefault("warnings", []).append(f"git clone failed: {err or out}")
            state.setdefault("errors", []).append({
                "node": "DownloadNode",
                "type": "CloneFailed",
                "message": err or out,
                "action_taken": "continue_with_empty"
            })
        else:
            try:

                for item in os.listdir(temp_clone_dir):
                    src_path = os.path.join(temp_clone_dir, item)
                    dst_path = os.path.join(source_dir, item)
                    if os.path.isdir(src_path):
                        shutil.move(src_path, dst_path)
                    else:
                        shutil.move(src_path, dst_path)
                
                shutil.rmtree(temp_clone_dir)
                logger.info(f"Repository cloned successfully to: {source_dir}")
            except Exception as e:
                logger.error(f"Failed to move files: {e}")
                state.setdefault("errors", []).append({
                    "node": "DownloadNode",
                    "type": "FileMoveFailed",
                    "message": str(e),
                    "action_taken": "continue_with_empty"
                })
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

