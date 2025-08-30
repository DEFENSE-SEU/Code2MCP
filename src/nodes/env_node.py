# Environment Node - Create isolated environment and run original project minimal validation
from __future__ import annotations
import os
import subprocess
from typing import Dict, Any
import sys
import json
import time
from ..utils import setup_logging, ensure_directory, write_file

logger = setup_logging()


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 1800) -> tuple[int, str, str]:
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
        return 1, "", str(e)

def _install_pip_from_env_yml(python_cmd: list[str], yml_paths: list[str], cwd: str):
    try:
        import re, io, os
        pkgs: list[str] = []
        for y in yml_paths:
            if not y or not os.path.isfile(y):
                continue
            with open(y, 'r', encoding='utf-8') as f:
                text = f.read()
            m = re.search(r"(?m)^\s*-\s*pip\s*:\s*\n([\s\S]*?)(?=^\S|\Z)", text)
            if not m:
                continue
            block = m.group(1)
            for line in io.StringIO(block):
                s = line.strip()
                if not s.startswith('-'):
                    continue
                pkg = s.lstrip('-').strip()
                if pkg:
                    pkgs.append(pkg)
        if not pkgs:
            return
        for p in pkgs:
            if p.startswith('-r ') or p.startswith('--requirement '):
                req = p.split(None, 1)[1].strip()
                _run(python_cmd + ["-m", "pip", "install", "-r", req], cwd=cwd, timeout=1800)
            else:
                _run(python_cmd + ["-m", "pip", "install", p], cwd=cwd, timeout=1800)
    except Exception:
        pass

def _env_name(repo_name: str) -> str:
    timestamp = str(int(time.time()))[-6:] 
    return f"{repo_name}_{timestamp}_env"


def _cleanup_old_envs(repo_name: str):
    try:
        conda_exe = os.environ.get("CONDA_EXE")
        if not conda_exe or not os.path.exists(conda_exe):
            logger.warning("Conda executable not found, skipping environment cleanup")
            return
        
        code, out, err = _run([conda_exe, "env", "list", "--json"])
        if code == 0:
            try:
                envs_data = json.loads(out)
                if isinstance(envs_data, list):
                    for env_path in envs_data:
                        if isinstance(env_path, str):
                            env_name = os.path.basename(env_path)
                            if env_name.startswith(f"{repo_name}_") and env_name.endswith("_env"):
                                logger.info(f"Cleaning up old environment: {env_name}")
                                _run([conda_exe, "env", "remove", "-n", env_name, "--yes"])
                elif isinstance(envs_data, dict):
                    for env in envs_data.get("envs", []):
                        if isinstance(env, dict):
                            env_path = env.get("prefix", "")
                        elif isinstance(env, str):
                            env_path = env
                        else:
                            continue
                        
                        if env_path:
                            env_name = os.path.basename(env_path)
                            if env_name.startswith(f"{repo_name}_") and env_name.endswith("_env"):
                                _run([conda_exe, "env", "remove", "-n", env_name, "--yes"])
                else:
                    logger.warning(f"Unknown conda environment list format: {type(envs_data)}")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse conda environment list JSON: {e}")
            except Exception as e:
                logger.warning(f"Failed to process conda environment list: {e}")
    except Exception as e:
        logger.warning(f"Failed to cleanup old environments: {e}")


def _check_conda_available() -> bool:
    try:
        code, out, err = _run(["conda", "--version"])
        if code == 0:
            logger.info(f"Conda available: {out.strip()}")
            return True
    except Exception:
        pass
    
    if os.name == "nt":
        try:
            code, out, err = _run(["conda.exe", "--version"])
            if code == 0:
                logger.info(f"conda.exe available: {out.strip()}")
                return True
        except Exception:
            pass
    
    conda_paths = [
        os.path.expanduser("~/anaconda3/bin/conda"),
        os.path.expanduser("~/miniconda3/bin/conda"),
        os.path.expanduser("~/anaconda/bin/conda"),
        os.path.expanduser("~/miniconda/bin/conda"),
    ]
    
    if os.name == "nt":
        username = os.environ.get("USERNAME", "")
        windows_paths = [
            f"C:/Users/{username}/anaconda3/Scripts/conda.exe",
            f"C:/Users/{username}/miniconda3/Scripts/conda.exe",
            f"C:/Users/{username}/anaconda/Scripts/conda.exe",
            f"C:/Users/{username}/miniconda/Scripts/conda.exe",
            "C:/ProgramData/Anaconda3/Scripts/conda.exe",
            "C:/ProgramData/Miniconda3/Scripts/conda.exe",
            "C:/Anaconda3/Scripts/conda.exe",
            "C:/Miniconda3/Scripts/conda.exe",
        ]
        conda_paths.extend(windows_paths)
    
    # Check conda paths in environment variables
    conda_env_paths = [
        os.environ.get("CONDA_EXE"),
        os.environ.get("CONDA_PREFIX") + "/bin/conda" if os.environ.get("CONDA_PREFIX") else None,
    ]
    conda_paths.extend([p for p in conda_env_paths if p and os.path.exists(p)])
    
    for conda_path in conda_paths:
        if os.path.exists(conda_path):
            try:
                code, out, err = _run([conda_path, "--version"])
                if code == 0:
                    logger.info(f"Found conda: {conda_path}")
                    return True
            except Exception:
                continue
    
    logger.warning("Conda not available, will use venv as fallback")
    return False


def _create_conda_env(env_name: str, repo_root: str, deps: Dict[str, Any]) -> Dict[str, Any]:
    env_info = {"type": "conda", "name": env_name, "files": {}, "python": "3.10", "exec_prefix": []}
    
    conda_exe = os.environ.get("CONDA_EXE")
    if not conda_exe or not os.path.exists(conda_exe):
        if _check_conda_available():
            conda_exe = os.environ.get("CONDA_EXE")
        if not conda_exe or not os.path.exists(conda_exe):
            logger.error("Conda executable not found")
            return None
    
    logger.info(f"Using conda: {conda_exe}")
    
    env_yml = os.path.join(repo_root, "environment.yml")
    source_env_yml = os.path.join(repo_root, "source", "environment.yml")
    
    if deps.get("has_environment_yml"):
        if os.path.exists(env_yml):
            env_yml_path = env_yml
        elif os.path.exists(source_env_yml):
            env_yml_path = source_env_yml
        else:
            env_yml_path = None
            
        if env_yml_path:
            logger.info(f"Creating conda environment using environment.yml: {env_name}")
            code, out, err = _run([conda_exe, "env", "create", "-n", env_name, "-f", env_yml_path])
            if code == 0:
                env_info["files"]["environment_yml"] = env_yml_path
                logger.info(f"Conda environment created successfully: {env_name}")
                return env_info
            else:
                logger.warning(f"Failed to create conda environment: {err or out}")
    
    logger.info(f"Creating base conda environment: {env_name}")
    code, out, err = _run([conda_exe, "create", "-n", env_name, "python=3.10", "--yes"])
    if code == 0:
        logger.info(f"Base conda environment created successfully: {env_name}")
        
        if deps.get("pyproject"):
            pyproject_path = None
            pyproject_root = os.path.join(repo_root, "pyproject.toml")
            source_pyproject = os.path.join(repo_root, "source", "pyproject.toml")
            
            if os.path.exists(pyproject_root):
                pyproject_path = pyproject_root
            elif os.path.exists(source_pyproject):
                pyproject_path = source_pyproject
                
            if pyproject_path:
                logger.info("Installing pyproject.toml dependencies in conda environment")
                code, out, err = _run([conda_exe, "run", "-n", env_name, "pip", "install", "-e", os.path.dirname(pyproject_path)])
                if code == 0:
                    env_info["files"]["pyproject_toml"] = pyproject_path
                    logger.info("pyproject.toml dependencies installed successfully")
                else:
                    logger.warning(f"Failed to install pyproject.toml dependencies: {err or out}")
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib
                    
                    try:
                        with open(pyproject_path, 'rb') as f:
                            pyproject_data = tomllib.load(f)
                        
                        dependencies = pyproject_data.get("project", {}).get("dependencies", [])
                        if dependencies:
                            for dep in dependencies:
                                code, out, err = _run([conda_exe, "run", "-n", env_name, "pip", "install", dep])
                                if code != 0:
                                    logger.warning(f"Failed to install dependency {dep}: {err or out}")
                    except Exception as e:
                        logger.warning(f"Failed to parse pyproject.toml: {e}")
        
        if deps.get("has_requirements_txt"):
            req_txt = os.path.join(repo_root, "requirements.txt")
            source_req_txt = os.path.join(repo_root, "source", "requirements.txt")
            
            req_txt_path = None
            if os.path.exists(req_txt):
                req_txt_path = req_txt
            elif os.path.exists(source_req_txt):
                req_txt_path = source_req_txt
                
            if req_txt_path:
                logger.info("Installing pip dependencies in conda environment")
                code, out, err = _run([conda_exe, "run", "-n", env_name, "pip", "install", "-r", req_txt_path])
                if code == 0:
                    env_info["files"]["requirements_txt"] = req_txt_path
                    logger.info("Pip dependencies installed successfully")
                else:
                    logger.warning(f"Failed to install pip dependencies: {err or out}")

        yml_paths = [os.path.join(repo_root, "environment.yml"), os.path.join(repo_root, "source", "environment.yml")]
        python_cmd = [conda_exe, "run", "-n", env_name, "python"]
        _install_pip_from_env_yml(python_cmd, yml_paths, repo_root)
        
        return env_info
    else:
        logger.error(f"Failed to create conda environment: {err or out}")
        return None


# Create unique environment name and path for each repository
def _create_venv_env(repo_root: str, repo_name: str, deps: Dict[str, Any]) -> Dict[str, Any]:
    timestamp = str(int(time.time()))[-6:]
    env_name = f"{repo_name}_{timestamp}_venv"
    env_path = os.path.join(repo_root, env_name)
    
    env_info = {"type": "venv", "name": env_name, "path": env_path, "files": {}, "python": "3.10", "exec_prefix": []}
    
    venv_py = _venv_python_path(env_path)
    if not os.path.isfile(venv_py):
        logger.info(f"Creating isolated venv environment: {env_name}")
        code, out, err = _run([sys.executable, "-m", "venv", env_path], cwd=repo_root)
        if code != 0:
            logger.warning(f"Failed to create venv: {err or out}")
            return None

    if os.path.isfile(venv_py):
        logger.info(f"Upgrading pip: {env_name}")
        _run([venv_py, "-m", "pip", "install", "-U", "pip"], cwd=repo_root)
        
        installed_deps = False
        if deps.get("pyproject"):
            pyproject_path = next((p for p in [os.path.join(repo_root, "pyproject.toml"), os.path.join(repo_root, "source", "pyproject.toml")] if os.path.exists(p)), None)
            if pyproject_path:
                logger.info(f"Installing pyproject.toml dependencies in venv environment: {env_name}")
                code, out, err = _run([venv_py, "-m", "pip", "install", f"-e {os.path.dirname(pyproject_path)}"], cwd=repo_root)
                if code == 0:
                    env_info["files"]["pyproject_toml"] = pyproject_path
                    installed_deps = True

        if deps.get("has_requirements_txt"):
            req_txt_path = next((p for p in [os.path.join(repo_root, "requirements.txt"), os.path.join(repo_root, "source", "requirements.txt")] if os.path.exists(p)), None)
            if req_txt_path:
                code, out, err = _run([venv_py, "-m", "pip", "install", "-r", req_txt_path])
                if code == 0:
                    env_info["files"]["requirements_txt"] = req_txt_path
                    installed_deps = True

        yml_paths = [os.path.join(repo_root, "environment.yml"), os.path.join(repo_root, "source", "environment.yml")]
        _install_pip_from_env_yml([venv_py], yml_paths, repo_root)
        
        env_info["exec_prefix"] = [venv_py]
        logger.info(f"Isolated venv environment created successfully: {env_name}")
        return env_info

    return None

def _venv_python_path(env_path: str) -> str:
    """Get Python path in venv environment"""
    if os.name == "nt":
        return os.path.join(env_path, "Scripts", "python.exe")
    return os.path.join(env_path, "bin", "python")

def env_node(state: Dict[str, Any]) -> Dict[str, Any]:
    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    repo_name = repo.get("name")
    if not (repo_root and os.path.isdir(repo_root) and repo_name):
        state.setdefault("errors", []).append({
            "node": "EnvNode",
            "type": "InvalidInput",
            "message": "Missing repo_root path or repo_name",
            "action_taken": "abort"
        })
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    deps = (state.get("analysis") or {}).get("dependencies", {})
    
    env = None
    if _check_conda_available():
        _cleanup_old_envs(repo_name)
        

        env_name = _env_name(repo_name)
        env = _create_conda_env(env_name, repo_root, deps)
        
        if env:
            logger.info(f"Successfully created conda environment: {env_name}")
        else:
            logger.warning("Failed to create conda environment, falling back to venv")
    
    if not env:
        env = _create_venv_env(repo_root, repo_name, deps)
    
    if not env:
        state.setdefault("errors", []).append({
            "node": "EnvNode",
            "type": "EnvSetupFailed",
            "message": "Unable to create any type of environment",
            "action_taken": "continue"
        })
        env = {"type": "none", "name": "none", "files": {}, "python": "3.10", "exec_prefix": []}

    cpp_info = (state.get("analysis") or {}).get("cpp_info", {})
    if cpp_info.get("has_cpp_files"):
        source_dir = os.path.join(repo_root, "source")
        build_system = cpp_info.get("build_system")
        if build_system == "cmake":
            _run(["cmake", "-S", source_dir, "-B", os.path.join(source_dir, "build")], cwd=repo_root, timeout=1800)
            _run(["cmake", "--build", os.path.join(source_dir, "build"), "--config", "Release", "-j"], cwd=repo_root, timeout=3600)
        elif build_system == "make":
            _run(["make", "-j"], cwd=source_dir, timeout=3600)
        elif build_system == "setup_py":
            if env.get("type") == "conda":
                conda_exe = os.environ.get("CONDA_EXE")
                if not conda_exe or not os.path.exists(conda_exe):
                    if _check_conda_available():
                        conda_exe = os.environ.get("CONDA_EXE")
                if conda_exe and os.path.exists(conda_exe):
                    _run([conda_exe, "run", "-n", env.get("name",""), "python", "setup.py", "build_ext", "-i"], cwd=source_dir, timeout=3600)
            elif env.get("type") == "venv" and env.get("exec_prefix"):
                _run([env["exec_prefix"][0], "setup.py", "build_ext", "-i"], cwd=source_dir, timeout=3600)
            else:
                _run(["python", "setup.py", "build_ext", "-i"], cwd=source_dir, timeout=3600)
    tests = {"passed": False, "report_path": None}
    if os.path.isdir(os.path.join(repo_root, "tests")):
        logger.info("Attempting to run pytest for original project validation")
        if env["type"] == "conda":
            conda_exe = os.environ.get("CONDA_EXE")
            if not conda_exe or not os.path.exists(conda_exe):
                if _check_conda_available():
                    conda_exe = os.environ.get("CONDA_EXE")
            if not conda_exe or not os.path.exists(conda_exe):
                logger.error("Conda executable not found, skipping pytest")
                tests["passed"] = False
                tests["report_path"] = None
            else:
                cmd = [conda_exe, "run", "-n", env["name"], "python", "-m", "pytest", "-q"]
        elif env["type"] == "venv" and env["exec_prefix"]:
            cmd = env["exec_prefix"] + ["-m", "pytest", "-q"]
        else:
            cmd = ["python", "-m", "pytest", "-q"]
        code, out, err = _run(cmd, cwd=repo_root, timeout=1800)
        if code == 0:
            tests["passed"] = True
            logger.info("Pytest tests passed")
        else:
            logger.warning("Pytest failed, falling back to simple import validation")

    if not tests["passed"]:
        mcp_output_dir = os.path.join(repo_root, "mcp_output")
        os.makedirs(mcp_output_dir, exist_ok=True)
        
        smoke_dir = os.path.join(mcp_output_dir, "tests_smoke")
        ensure_directory(smoke_dir)
        smoke_py = os.path.join(smoke_dir, "test_smoke.py")
        try:
            pkgs = (state.get("analysis") or {}).get("structure", {}).get("packages", [])
            
            pkgs = [pkg for pkg in pkgs if "tests" not in pkg.lower()]
            
            target_pkg = None
            if pkgs:
                target_pkg = min(pkgs, key=lambda p: p.count("."))
                if target_pkg.startswith("source."):
                    parts = target_pkg.split(".")
                    if len(parts) >= 3:  
                        target_pkg = ".".join(parts[1:])  
                    elif len(parts) == 2:  
                        target_pkg = parts[1]  
            
            content = """import importlib, sys
import os

# Add current directory to Python path
sys.path.insert(0, os.getcwd())

source_dir = os.path.join(os.getcwd(), "source")
if os.path.exists(source_dir):
    sys.path.insert(0, source_dir)

"""
            
            if target_pkg:
                content += f"""
try:
    importlib.import_module("{target_pkg}")
    print("OK - Successfully imported {target_pkg}")
except ImportError as e:
    print(f"Failed to import {target_pkg}: {{e}}")
    fallback_packages = []
"""
                
                fallback_packages = []
                
                if target_pkg.startswith("source."):
                    parts = target_pkg.split(".")
                    if len(parts) >= 3:  
                        fallback_packages.append(".".join(parts[1:])) 
                        fallback_packages.append(parts[-1])  
                    elif len(parts) == 2:  
                        fallback_packages.append(parts[1]) 
                elif target_pkg.startswith("src."):
                    fallback_packages.append(target_pkg.replace("src.", ""))
                elif "." in target_pkg:
                    fallback_packages.append(target_pkg.split(".")[-1])
                
                fallback_packages.append(target_pkg)
                fallback_packages = list(dict.fromkeys([pkg for pkg in fallback_packages if pkg]))
                
                content += f"""
    fallback_packages = {fallback_packages}
"""
                
                content += """
    for pkg in fallback_packages:
        try:
            importlib.import_module(pkg)
            print(f"OK - Successfully imported {pkg}")
            break
        except ImportError:
            continue
    else:
        print("All import attempts failed")
"""
            else:
                content += """
print("NO_PACKAGE - No testable package found")
"""
            
            with open(smoke_py, "w", encoding="utf-8") as f:
                f.write(content)
            
            if env["type"] == "conda":
                conda_exe = os.environ.get("CONDA_EXE")
                if not conda_exe or not os.path.exists(conda_exe):
                    if _check_conda_available():
                        conda_exe = os.environ.get("CONDA_EXE")
                if not conda_exe or not os.path.exists(conda_exe):
                    logger.error("Conda executable not found, skipping smoke test")
                    tests["passed"] = False
                else:
                    cmd = [conda_exe, "run", "-n", env["name"], "python", smoke_py]
            elif env["type"] == "venv" and env["exec_prefix"]:
                cmd = [env["exec_prefix"][0], smoke_py]
            else:
                cmd = ["python", smoke_py]
            
            code, out, err = _run(cmd, cwd=repo_root)
            tests["passed"] = (code == 0 and "OK" in out)
            if tests["passed"]:
                logger.info("Smoke test passed")
            else:
                logger.warning(f"Smoke test failed: {err or out}")
                
        except Exception as e:
            logger.warning(f"Failed to generate/execute smoke test: {e}")

    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    os.makedirs(mcp_output_dir, exist_ok=True)
    
    env_info_path = os.path.join(mcp_output_dir, "env_info.json")
    env_info = {
        "environment": env,
        "original_tests": tests,
        "timestamp": time.time(),
        "conda_available": _check_conda_available()
    }
    try:
        write_file(env_info_path, json.dumps(env_info, ensure_ascii=False, indent=2))
        logger.info(f"Environment information saved to: {env_info_path}")
    except Exception as e:
        logger.warning(f"Failed to save env_info.json: {e}")

    state["env"] = env
    state.setdefault("tests", {})["original"] = tests
    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    
    logger.info(f"Environment setup completed: {env['type']} environment '{env['name']}'")
    return state

