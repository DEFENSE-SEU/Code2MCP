import os
import subprocess
import shutil
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


def deploy_to_huggingface(workspace_dir, hf_username=None, hf_token=None):
    load_env_file()
    
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
                # Continue even if copying source fails (e.g., Windows permission issues)
                pass
        
        def _collect_requirements() -> str:
            reqs = []
            def add_line(line: str):
                s = (line or "").strip()
                if not s or s.startswith('#'):
                    return
                if s.lower().startswith('python'):
                    return
                if s not in reqs:
                    reqs.append(s)
            # Base runtime
            add_line("fastmcp")
            add_line("fastapi")
            add_line("uvicorn[standard]")

            # Merge from generated MCP requirements
            mcp_req = mcp_output / "requirements.txt"
            if mcp_req.exists():
                with open(mcp_req, "r", encoding="utf-8") as f:
                    for line in f:
                        add_line(line)

            # Merge from source requirements.txt if present
            src_req = source_dir / "requirements.txt"
            if src_req.exists():
                with open(src_req, "r", encoding="utf-8") as f:
                    for line in f:
                        add_line(line)

            # Always try to parse pyproject.toml for [project].dependencies
            pyproject = source_dir / "pyproject.toml"
            if pyproject.exists():
                try:
                    try:
                        import tomllib as _toml  # py311+
                    except Exception:  # pragma: no cover
                        import tomli as _toml  # type: ignore
                    with open(pyproject, "rb") as fp:
                        data = _toml.load(fp)
                    for item in (data.get("project", {}).get("dependencies", []) or []):
                        add_line(item)
                except Exception:
                    # Fallback to regex if toml parsing unavailable
                    text = pyproject.read_text(encoding="utf-8", errors="ignore")
                    import re
                    m = re.search(r"\[project\][\s\S]*?dependencies\s*=\s*\[(.*?)\]", text, re.IGNORECASE | re.DOTALL)
                    if m:
                        body = m.group(1)
                        for item in re.findall(r"\"([^\"]+)\"", body):
                            add_line(item)

            return "\n".join(reqs) + "\n"
        
        dockerfile_content = f'''FROM python:3.10

RUN useradd -m -u 1000 user && python -m pip install --upgrade pip
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY --chown=user ./{repo_name}/mcp_output/requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app

ENV PYTHONPATH=/app/{repo_name}/source:$PYTHONPATH
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

source_path = os.path.join(os.path.dirname(__file__), "{repo_name}", "source")
mcp_plugin_path = os.path.join(os.path.dirname(__file__), "{repo_name}", "mcp_output", "mcp_plugin")
sys.path.insert(0, source_path)
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
        
        requirements_path = mcp_output / "requirements.txt"
        if requirements_path.exists():
            with open(requirements_path, "r", encoding="utf-8") as f:
                requirements = f.read()
            if "fastapi" not in requirements.lower():
                requirements += "\nfastapi\nuvicorn[standard]\n"
            with open(deploy_dir / "requirements.txt", "w", encoding="utf-8") as f:
                f.write(merged_requirements)
        else:
            with open(deploy_dir / "requirements.txt", "w", encoding="utf-8") as f:
                f.write(merged_requirements)
        
        gitattributes_content = '''*.7z filter=lfs diff=lfs merge=lfs -text
*.arrow filter=lfs diff=lfs merge=lfs -text
*.bin filter=lfs diff=lfs merge=lfs -text
*.bz2 filter=lfs diff=lfs merge=lfs -text
*.ckpt filter=lfs diff=lfs merge=lfs -text
*.gz filter=lfs diff=lfs merge=lfs -text
*.h5 filter=lfs diff=lfs merge=lfs -text
*.model filter=lfs diff=lfs merge=lfs -text
*.onnx filter=lfs diff=lfs merge=lfs -text
*.pb filter=lfs diff=lfs merge=lfs -text
*.pt filter=lfs diff=lfs merge=lfs -text
*.pth filter=lfs diff=lfs merge=lfs -text
*.safetensors filter=lfs diff=lfs merge=lfs -text
*.tar filter=lfs diff=lfs merge=lfs -text
*.zip filter=lfs diff=lfs merge=lfs -text
'''
        
        with open(deploy_dir / ".gitattributes", "w", encoding="utf-8") as f:
            f.write(gitattributes_content)
        
        gitignore_content = '''__pycache__/
*.py[cod]
.env
.venv
env/
venv/
.DS_Store
*.log
.git
'''
        
        with open(deploy_dir / ".gitignore", "w", encoding="utf-8") as f:
            f.write(gitignore_content)
        
        subprocess.run(
            ["huggingface-cli", "login", "--token", hf_token, "--add-to-git-credential"],
            capture_output=True,
            check=False
        )
        
        space_name = f"{repo_name}-mcp"
        subprocess.run(
            ["huggingface-cli", "repo", "create", space_name, "--type", "space", "--space_sdk", "docker"],
            capture_output=True,
            check=False
        )
        
        original_dir = os.getcwd()
        os.chdir(deploy_dir)
        
        try:
            if (deploy_dir / ".git").exists():
                shutil.rmtree(deploy_dir / ".git")
            
            subprocess.run(["git", "init"], capture_output=True, check=False)
            subprocess.run(["git", "add", "."], capture_output=True, check=False)
            subprocess.run(["git", "commit", "-m", f"Deploy {repo_name} MCP service"], capture_output=True, check=False)
            
            hf_remote = f"https://{hf_username}:{hf_token}@huggingface.co/spaces/{hf_username}/{space_name}"
            subprocess.run(["git", "remote", "add", "hf", hf_remote], capture_output=True, check=False)
            
            result = subprocess.run(["git", "push", "hf", "main", "--force"], capture_output=True, text=True)
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "url": f"https://{hf_username}-{space_name}.hf.space",
                    "space_url": f"https://huggingface.co/spaces/{hf_username}/{space_name}",
                    "repo_name": repo_name
                }
            else:
                return {
                    "success": False,
                    "error": f"Git push failed: {result.stderr}"
                }
        finally:
            os.chdir(original_dir)
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

