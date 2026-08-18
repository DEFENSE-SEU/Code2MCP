import os
import shutil
import subprocess
import socket
import json
import re
import time
from pathlib import Path


BASE_DEPLOYMENT_REQUIREMENTS = ("fastmcp>=0.1.0", "pydantic>=2.0.0")


def _merge_requirements(raw_requirements: str) -> str:
    lines = []
    seen = set()
    for raw in (raw_requirements or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    for requirement in BASE_DEPLOYMENT_REQUIREMENTS:
        key = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].strip().lower()
        if key not in seen:
            seen.add(key)
            lines.append(requirement)
    return "\n".join(lines) + "\n"


def _collect_deployment_requirements(mcp_output: Path) -> str:
    mcp_req = mcp_output / "requirements.txt"
    if mcp_req.exists():
        try:
            return _merge_requirements(mcp_req.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _merge_requirements("")


def load_env_file():
    env_file = '.env'
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


def deploy_to_huggingface(workspace_dir, hf_username=None, hf_token=None, push=None):
    load_env_file()

    if push is None:
        push = os.getenv("HF_PUSH", "false").lower() == "true"

    if push:
        if hf_token is None:
            hf_token = os.getenv("HF_TOKEN")
        if hf_username is None:
            hf_username = os.getenv("HF_USERNAME")
        if not hf_token or not hf_username:
            return {
                "success": False,
                "error": "HuggingFace credentials not configured"
            }
    
    workspace_path = Path(workspace_dir)
    if not workspace_path.exists():
        return {
            "success": False,
            "error": f"Workspace {workspace_dir} not found"
        }
    
    repo_name = workspace_path.name
    mcp_output = workspace_path / "mcp_output"
    source_dir = workspace_path / "source"
    
    if not mcp_output.exists():
        return {
            "success": False,
            "error": f"mcp_output not found in {workspace_dir}"
        }
    
    try:
        deploy_dir = workspace_path / "deployment"
        deploy_dir.mkdir(exist_ok=True)
        
        repo_deploy_dir = deploy_dir / repo_name
        repo_deploy_dir.mkdir(exist_ok=True)
        
        if (repo_deploy_dir / "mcp_output").exists():
            shutil.rmtree(repo_deploy_dir / "mcp_output")
        shutil.copytree(mcp_output, repo_deploy_dir / "mcp_output")
        
        if source_dir.exists():
            if (repo_deploy_dir / "source").exists():
                shutil.rmtree(repo_deploy_dir / "source")
            try:
                shutil.copytree(
                    source_dir,
                    repo_deploy_dir / "source",
                    ignore=shutil.ignore_patterns('.git', '.git*', '__pycache__')
                )
            except Exception:
                pass
        
        dockerfile_content = f'''FROM python:3.10

RUN useradd -m -u 1000 user && python -m pip install --upgrade pip
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app
ENV MCP_TRANSPORT=http
ENV MCP_PORT=7860

EXPOSE 7860

CMD ["python", "{repo_name}/mcp_output/start_mcp.py"]
'''
        
        with open(deploy_dir / "Dockerfile", "w", encoding="utf-8") as f:
            f.write(dockerfile_content)
        
        app_content = f'''from fastapi import FastAPI
import os
import sys

mcp_plugin_path = os.path.join(os.path.dirname(__file__), "{repo_name}", "mcp_output", "mcp_plugin")
sys.path.insert(0, mcp_plugin_path)

app = FastAPI(
    title="{repo_name.title()} MCP Service",
    description="Auto-generated MCP service for {repo_name}",
    version="1.0.0"
)

@app.get("/")
def root():
    return {{
        "service": "{repo_name.title()} MCP Service",
        "version": "1.0.0",
        "status": "running",
        "transport": os.environ.get("MCP_TRANSPORT", "http")
    }}

@app.get("/health")
def health_check():
    return {{"status": "healthy", "service": "{repo_name} MCP"}}

@app.get("/tools")
def list_tools():
    try:
        from mcp_service import create_app
        mcp_app = create_app()
        tools = []
        for tool_name, tool_func in mcp_app.tools.items():
            tools.append({{
                "name": tool_name,
                "description": tool_func.__doc__ or "No description available"
            }})
        return {{"tools": tools}}
    except Exception as e:
        return {{"error": f"Failed to load tools: {{str(e)}}"}}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
'''
        
        with open(deploy_dir / "app.py", "w", encoding="utf-8") as f:
            f.write(app_content)
        
        merged_requirements = _collect_deployment_requirements(mcp_output)
        with open(deploy_dir / "requirements.txt", "w", encoding="utf-8") as f:
            f.write(merged_requirements)

        try:
            (repo_deploy_dir / "mcp_output").mkdir(parents=True, exist_ok=True)
            with open(repo_deploy_dir / "mcp_output" / "requirements.txt", "w", encoding="utf-8") as f:
                f.write(merged_requirements)
        except Exception:
            pass

        manifest = {
            "repo_name": repo_name,
            "transport": "http",
            "port": 7860,
            "entrypoint": f"{repo_name}/mcp_output/start_mcp.py",
            "mcp_path": "/mcp",
            "dockerfile": "Dockerfile",
            "requirements": "requirements.txt",
            "push_requested": bool(push),
        }
        with open(deploy_dir / "deployment_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        
        if push:
            try:
                from huggingface_hub import HfApi
            except Exception:
                return {
                    "success": False,
                    "error": "huggingface_hub not installed. Please: pip install huggingface_hub"
                }

            space_name = f"{repo_name}-mcp"
            space_id = f"{hf_username}/{space_name}"
            api = HfApi(token=hf_token)
            try:
                api.create_repo(repo_id=space_id, repo_type="space", space_sdk="docker", exist_ok=True)
            except Exception:
                pass

            try:
                api.upload_folder(
                    repo_id=space_id,
                    repo_type="space",
                    folder_path=str(deploy_dir),
                    path_in_repo="",
                    commit_message=f"Deploy {repo_name} MCP service"
                )
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Upload failed: {str(e)}"
                }

            return {
                "success": True,
                "url": f"https://{hf_username}-{space_name}.hf.space",
                "mcp_url": f"https://{hf_username}-{space_name}.hf.space/mcp",
                "space_url": f"https://huggingface.co/spaces/{hf_username}/{space_name}",
                "repo_name": repo_name,
                "pushed": True,
                "deploy_dir": str(deploy_dir)
            }

        return {
            "success": True,
            "url": None,
            "mcp_url": None,
            "space_url": None,
            "repo_name": repo_name,
            "pushed": False,
            "deploy_dir": str(deploy_dir)
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def create_and_run_local_scripts(workspace_dir: str,
                                 entry_name=None,
                                 image_name=None,
                                 entry_url=None,
                                 autorun: bool = False) -> dict:
    """Create platform scripts (run_docker.ps1/.sh) under deployment/ and optionally run them.

    The generated launchers only build/run the local HTTP MCP service and print the
    connection URL. Client-specific config is handled by scripts/connect_agent.py
    or the generated agent_connect.html guide so users can choose Cursor, Claude,
    VS Code, ChatGPT/OpenAI, Gemini, Cline, Windsurf, or a generic MCP client
    explicitly.
    """
    try:
        workspace_path = Path(workspace_dir)
        if not workspace_path.exists():
            return {"success": False, "error": f"Workspace {workspace_dir} not found"}

        repo_name = workspace_path.name
        name = entry_name or os.getenv("MCP_ENTRY_NAME") or repo_name
        image = image_name or os.getenv("MCP_IMAGE_NAME") or f"{repo_name}-mcp"

        def _preferred_port(name: str, base: int = 7860, upper: int = 7999) -> int:
            h = abs(hash(name))
            span = max(1, upper - base + 1)
            return base + (h % span)

        def _port_available(port: int) -> bool:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", port))
                s.close()
                return True
            except OSError:
                try:
                    s.close()
                except Exception:
                    pass
                return False

        def _pick_port(name: str, base: int = 7860, upper: int = 7999) -> int:
            p = _preferred_port(name, base, upper)
            for i in range(upper - base + 1):
                candidate = base + ((p - base + i) % (upper - base + 1))
                if _port_available(candidate):
                    return candidate
            return base

        host_port = _pick_port(repo_name)
        url = entry_url or os.getenv("MCP_ENTRY_URL") or f"http://localhost:{host_port}/mcp"

        deploy_dir = workspace_path / "deployment"
        deploy_dir.mkdir(exist_ok=True)

        sh_template = '''#!/usr/bin/env bash
set -euo pipefail
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_entry_name="${MCP_ENTRY_NAME:-__NAME__}"
mcp_entry_url="${MCP_ENTRY_URL:-__URL__}"
guide_path="$(cd .. && pwd)/mcp_output/agent_connect.html"
echo "MCP service: ${mcp_entry_name}"
echo "HTTP MCP URL: ${mcp_entry_url}"
echo "Connection guide: ${guide_path}"
echo "This script does not modify agent/client config files."
docker build -t __IMAGE__ .
docker run --rm -p __HOST_PORT__:7860 -e MCP_TRANSPORT=http -e MCP_PORT=7860 __IMAGE__
'''

        sh_content = (sh_template
                       .replace("__NAME__", name)
                       .replace("__URL__", url)
                       .replace("__IMAGE__", image)
                       .replace("__HOST_PORT__", str(host_port)))

        (deploy_dir / "run_docker.sh").write_text(sh_content, encoding="utf-8")

        ps1_template = '''cd $PSScriptRoot
$ErrorActionPreference = "Stop"
$entryName = if ($env:MCP_ENTRY_NAME) { $env:MCP_ENTRY_NAME } else { "__NAME__" }
$entryUrl  = if ($env:MCP_ENTRY_URL)  { $env:MCP_ENTRY_URL  } else { "__URL__" }
$imageName = if ($env:MCP_IMAGE_NAME) { $env:MCP_IMAGE_NAME } else { "__IMAGE__" }
$guidePath = Join-Path (Split-Path $PSScriptRoot -Parent) "mcp_output\agent_connect.html"
Write-Host "MCP service: $entryName"
Write-Host "HTTP MCP URL: $entryUrl"
Write-Host "Connection guide: $guidePath"
Write-Host "This script does not modify agent/client config files."
docker build -t $imageName .
docker run --rm -p __HOST_PORT__:7860 -e MCP_TRANSPORT=http -e MCP_PORT=7860 $imageName
'''

        ps1_content = (ps1_template
                        .replace("__NAME__", name)
                        .replace("__URL__", url)
                        .replace("__IMAGE__", image)
                        .replace("__HOST_PORT__", str(host_port)))

        (deploy_dir / "run_docker.ps1").write_text(ps1_content, encoding="utf-8")

        try:
            port_log = {
                "repo": repo_name,
                "port": host_port,
                "timestamp": int(time.time())
            }
            (deploy_dir / "port.json").write_text(json.dumps(port_log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        connection_hint = {
            "entry_name": name,
            "entry_url": url,
            "transport": "http",
            "host_port": host_port,
            "guide_path": str((workspace_path / "mcp_output" / "agent_connect.html").resolve()),
            "does_not_modify_client_config": True,
            "write_client_config_with": [
                f"python scripts/connect_agent.py --repo-root {workspace_path} --client cursor --remote --remote-url {url} --probe-remote --write",
                f"python scripts/connect_agent.py --repo-root {workspace_path} --client vscode --remote --remote-url {url} --probe-remote",
                f"python scripts/connect_agent.py --repo-root {workspace_path} --client openai --remote-url {url} --probe-remote",
            ],
        }
        (deploy_dir / "connection_hint.json").write_text(
            json.dumps(connection_hint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if autorun:
            dockerfile_path = deploy_dir / "Dockerfile"
            req_path = deploy_dir / "requirements.txt"
            if not dockerfile_path.exists() or not req_path.exists():
                return {
                    "success": False,
                    "error": "Deployment files missing. Ensure Dockerfile and requirements.txt are generated before running.",
                    "scripts_dir": str(deploy_dir)
                }
            try:
                if os.name == 'nt':
                    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(deploy_dir / "run_docker.ps1")], check=False)
                else:
                    os.chmod(deploy_dir / "run_docker.sh", 0o755)
                    subprocess.run(["/bin/bash", str(deploy_dir / "run_docker.sh")], check=False)
            except Exception:
                pass

        return {
            "success": True,
            "scripts_dir": str(deploy_dir),
            "entry_name": name,
            "entry_url": url,
            "image_name": image,
            "connection_hint": str(deploy_dir / "connection_hint.json"),
            "host_port": host_port,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
