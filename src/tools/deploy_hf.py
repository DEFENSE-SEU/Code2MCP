import os
import shutil
import subprocess
from pathlib import Path


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
        
        def _collect_requirements() -> str:
            mcp_req = mcp_output / "requirements.txt"
            if mcp_req.exists():
                try:
                    return mcp_req.read_text(encoding="utf-8")
                except Exception:
                    pass
            return "fastmcp\nfastapi\nuvicorn[standard]\n"
        
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
        
        readme_content = f'''---
title: {repo_name.title()} MCP
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
sdk_version: "4.26.0"
app_file: app.py
pinned: false
---

# {repo_name.title()} MCP Service

Auto-generated MCP service for {repo_name}.

## Usage

```
https://{hf_username}-{repo_name}-mcp.hf.space/mcp
```

## Connect with Cursor

```json
{{
  "mcpServers": {{
    "{repo_name}": {{
      "url": "https://{hf_username}-{repo_name}-mcp.hf.space/mcp"
    }}
  }}
}}
```
'''
        
        with open(deploy_dir / "README.md", "w", encoding="utf-8") as f:
            f.write(readme_content)
        
        merged_requirements = _collect_requirements()
        with open(deploy_dir / "requirements.txt", "w", encoding="utf-8") as f:
            f.write(merged_requirements)

        try:
            (repo_deploy_dir / "mcp_output").mkdir(parents=True, exist_ok=True)
            with open(repo_deploy_dir / "mcp_output" / "requirements.txt", "w", encoding="utf-8") as f:
                f.write(merged_requirements)
        except Exception:
            pass
        
        
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
                "space_url": f"https://huggingface.co/spaces/{hf_username}/{space_name}",
                "repo_name": repo_name,
                "pushed": True,
                "deploy_dir": str(deploy_dir)
            }

        return {
            "success": True,
            "url": None,
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
                                 autorun: bool = True) -> dict:
    """Create platform scripts (run_docker.ps1/.sh) under deployment/ and optionally run them.

    - Scripts are generic (not hardcoding a specific service name). They default to the repo name and http://localhost:7860/mcp.
    - Both scripts update ~/.cursor or %USERPROFILE%\.cursor/mcp.json appending the entry last, then build and run Docker with -p 7860:7860.
    """
    try:
        workspace_path = Path(workspace_dir)
        if not workspace_path.exists():
            return {"success": False, "error": f"Workspace {workspace_dir} not found"}

        repo_name = workspace_path.name
        name = entry_name or os.getenv("MCP_ENTRY_NAME") or repo_name
        url = entry_url or os.getenv("MCP_ENTRY_URL") or "http://localhost:7860/mcp"
        image = image_name or os.getenv("MCP_IMAGE_NAME") or f"{repo_name}-mcp"

        deploy_dir = workspace_path / "deployment"
        deploy_dir.mkdir(exist_ok=True)

        sh_template = '''#!/usr/bin/env bash
set -euo pipefail

# Switch to the directory where this script is located
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

mcp_entry_name="${MCP_ENTRY_NAME:-__NAME__}"
mcp_entry_url="${MCP_ENTRY_URL:-__URL__}"
mcp_dir="${HOME}/.cursor"
mcp_path="${mcp_dir}/mcp.json"
mkdir -p "${mcp_dir}"

if command -v python3 >/dev/null 2>&1; then
python3 - "${mcp_path}" "${mcp_entry_name}" "${mcp_entry_url}" <<'PY'
import json, os, sys
path, name, url = sys.argv[1:4]
cfg = {"mcpServers": {}}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {"mcpServers": {}}
if not isinstance(cfg, dict):
    cfg = {"mcpServers": {}}
servers = cfg.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
ordered = {}
for k, v in servers.items():
    if k != name:
        ordered[k] = v
ordered[name] = {"url": url}
cfg = {"mcpServers": ordered}
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PY
elif command -v python >/dev/null 2>&1; then
python - "${mcp_path}" "${mcp_entry_name}" "${mcp_entry_url}" <<'PY'
import json, os, sys
path, name, url = sys.argv[1:4]
cfg = {"mcpServers": {}}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {"mcpServers": {}}
if not isinstance(cfg, dict):
    cfg = {"mcpServers": {}}
servers = cfg.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
ordered = {}
for k, v in servers.items():
    if k != name:
        ordered[k] = v
ordered[name] = {"url": url}
cfg = {"mcpServers": ordered}
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PY
elif command -v jq >/dev/null 2>&1; then
  name="${mcp_entry_name}"; url="${mcp_entry_url}"
  if [ -f "${mcp_path}" ]; then
    tmp="$(mktemp)"
    jq --arg name "$name" --arg url "$url" '
      .mcpServers = (.mcpServers // {})
      | .mcpServers as $s
      | ($s | with_entries(select(.key != $name))) as $base
      | .mcpServers = ($base + {($name): {"url": $url}})
    ' "${mcp_path}" > "${tmp}" && mv "${tmp}" "${mcp_path}"
  else
    printf '{ "mcpServers": { "%s": { "url": "%s" } } }\n' "$name" "$url" > "${mcp_path}"
  fi
else
  echo "Warning: neither python nor jq found; skipped updating ~/.cursor/mcp.json" >&2
fi

docker build -t __IMAGE__ .
docker run --rm -p 7860:7860 __IMAGE__
'''

        sh_content = (sh_template
                       .replace("__NAME__", name)
                       .replace("__URL__", url)
                       .replace("__IMAGE__", image))

        (deploy_dir / "run_docker.sh").write_text(sh_content, encoding="utf-8")

        ps1_template = '''cd $PSScriptRoot

$ErrorActionPreference = "Stop"

$entryName = if ($env:MCP_ENTRY_NAME) { $env:MCP_ENTRY_NAME } else { "__NAME__" }
$entryUrl  = if ($env:MCP_ENTRY_URL)  { $env:MCP_ENTRY_URL  } else { "__URL__" }
$imageName = if ($env:MCP_IMAGE_NAME) { $env:MCP_IMAGE_NAME } else { "__IMAGE__" }

$mcpDir = Join-Path $env:USERPROFILE ".cursor"
$mcpPath = Join-Path $mcpDir "mcp.json"
if (!(Test-Path $mcpDir)) { New-Item -ItemType Directory -Path $mcpDir | Out-Null }

$config = @{}
if (Test-Path $mcpPath) {
  try { $config = Get-Content $mcpPath -Raw | ConvertFrom-Json } catch { $config = @{} }
}

# Rebuild mcpServers as ordered and append the entry last
$serversOrdered = [ordered]@{}
if ($config -and ($config.PSObject.Properties.Name -contains "mcpServers") -and $config.mcpServers) {
  $existing = $config.mcpServers
  if ($existing -is [pscustomobject]) {
    foreach ($p in $existing.PSObject.Properties) { if ($p.Name -ne $entryName) { $serversOrdered[$p.Name] = $p.Value } }
  } elseif ($existing -is [System.Collections.IDictionary]) {
    foreach ($k in $existing.Keys) { if ($k -ne $entryName) { $serversOrdered[$k] = $existing[$k] } }
  }
}
$serversOrdered[$entryName] = @{ url = $entryUrl }
$config = @{ mcpServers = $serversOrdered }

$config | ConvertTo-Json -Depth 10 | Set-Content -Path $mcpPath -Encoding UTF8
Write-Host ("Updated $entryName in " + $mcpPath + " -> " + $entryUrl)

docker build -t $imageName .
docker run --rm -p 7860:7860 $imageName
'''

        ps1_content = (ps1_template
                        .replace("__NAME__", name)
                        .replace("__URL__", url)
                        .replace("__IMAGE__", image))

        (deploy_dir / "run_docker.ps1").write_text(ps1_content, encoding="utf-8")

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
            "image_name": image
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
