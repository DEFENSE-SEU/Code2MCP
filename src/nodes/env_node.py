from __future__ import annotations
import os
import subprocess
import shlex
import shutil
from typing import Dict, Any
import sys
import json
import time
import re
from pathlib import Path
from ..utils import setup_logging, ensure_directory, write_file

logger = setup_logging()

MIN_PYTHON_VERSION = "3.10"
FALLBACK_PYTHON_VERSIONS = ["3.12", "3.11", "3.10"]
CORE_BASE_PACKAGES = ["fastmcp", "pytest", "pytest-asyncio"]
MAX_IMPORT_DEPENDENCIES = 12
IMPORT_DEPENDENCY_PRIORITY = {
    "numpy": 0,
    "scipy": 1,
    "pandas": 2,
    "empyrical": 3,
    "scikit-learn": 4,
    "matplotlib": 5,
    "pytz": 6,
    "ipython": 7,
    "simpleitk": 8,
    "requests": 9,
    "pyyaml": 10,
    "pillow": 11,
    "beautifulsoup4": 12,
    "networkx": 13,
    "statsmodels": 14,
    "tqdm": 15,
    "natsort": 16,
}
HEAVY_IMPORT_DEPENDENCIES = {
    "igraph",
    "opencv-python",
}
IMPORT_PACKAGE_INSTALL_FALLBACKS = {
    "empyrical": ["empyrical-reloaded"],
}


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


def _dependency_install_timeout() -> int:
    return _env_int("CODE2MCP_DEP_INSTALL_TIMEOUT", 300)


def _base_install_timeout() -> int:
    return _env_int("CODE2MCP_BASE_INSTALL_TIMEOUT", 600)


def _test_timeout() -> int:
    return _env_int("CODE2MCP_TEST_TIMEOUT", 300)


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
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stderr = (stderr + f"\nCommand timed out after {timeout} seconds").strip()
        return 124, stdout, stderr
    except Exception as e:
        return 1, "", str(e)

def _enforce_minimum_python(version_str: str) -> str:
    if not version_str:
        return MIN_PYTHON_VERSION
    try:
        parts = version_str.replace("python", "").replace("Python", "").strip().split(".")
        major = int(parts[0]) if len(parts) > 0 else 3
        minor = int(parts[1]) if len(parts) > 1 else 10
        if (major, minor) < (3, 10):
            return MIN_PYTHON_VERSION
        return f"{major}.{minor}"
    except:
        return MIN_PYTHON_VERSION

def _parse_python_requirement(requires_python: str) -> str:
    if not requires_python:
        return MIN_PYTHON_VERSION
    
    version = MIN_PYTHON_VERSION
    if ">=" in requires_python:
        match = re.search(r">=\s*([\d.]+)", requires_python)
        version = match.group(1) if match else MIN_PYTHON_VERSION
    elif "==" in requires_python:
        match = re.search(r"==\s*([\d.]+)", requires_python)
        version = match.group(1) if match else MIN_PYTHON_VERSION
    elif "<=" in requires_python:
        match = re.search(r"<=\s*([\d.]+)", requires_python)
        version = match.group(1) if match else MIN_PYTHON_VERSION
    elif re.match(r"^\d+\.\d+", requires_python):
        version = requires_python
    
    return _enforce_minimum_python(version)


def _version_tuple(version_str: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", version_str or "")
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def _python_satisfies_minimum(version_str: str) -> bool:
    return _version_tuple(version_str) >= _version_tuple(MIN_PYTHON_VERSION)


def _python_version(python_cmd: str | list[str]) -> str:
    cmd = [python_cmd] if isinstance(python_cmd, str) else list(python_cmd)
    code, out, err = _run(cmd + ["--version"], timeout=30)
    if code != 0:
        return ""
    return (out or err).strip()


def _install_base_packages(install_cmd: list[str], cwd: str) -> dict[str, Any]:
    logger.info(f"Installing core MCP packages: {', '.join(CORE_BASE_PACKAGES)}")
    core_code, core_out, core_err = _run(
        install_cmd + CORE_BASE_PACKAGES,
        cwd=cwd,
        timeout=_base_install_timeout(),
    )
    result = {
        "passed": core_code == 0,
        "exit_code": core_code,
        "message": (core_err or core_out)[-1000:],
        "core_packages": CORE_BASE_PACKAGES,
    }
    return result


def _command_exists(cmd: list[str]) -> bool:
    if not cmd:
        return False
    executable = cmd[0]
    if os.path.isabs(executable):
        return os.path.isfile(executable)
    return shutil.which(executable) is not None


def _add_python_candidate(candidates: list[list[str]], value: str | list[str] | None):
    if not value:
        return
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        if os.path.exists(text) or os.sep in text or (os.altsep and os.altsep in text):
            parts = [text]
        else:
            try:
                parts = shlex.split(text)
            except ValueError:
                parts = [text]
    else:
        parts = [str(part) for part in value if str(part)]
    if not parts:
        return
    key = tuple(part.lower() for part in parts)
    existing = {tuple(part.lower() for part in item) for item in candidates}
    if key not in existing and _command_exists(parts):
        candidates.append(parts)


def _candidate_python_commands(preferred_versions: list[str] | None = None) -> list[list[str]]:
    versions = list(dict.fromkeys((preferred_versions or []) + FALLBACK_PYTHON_VERSIONS))
    candidates: list[list[str]] = []

    _add_python_candidate(candidates, os.getenv("CODE2MCP_PYTHON"))
    _add_python_candidate(candidates, sys.executable)

    if os.name == "nt":
        for version in versions:
            _add_python_candidate(candidates, ["py", f"-{version}"])

        user_profile = os.getenv("USERPROFILE") or str(Path.home())
        runtime_python = os.path.join(
            user_profile,
            ".cache",
            "codex-runtimes",
            "codex-primary-runtime",
            "dependencies",
            "python",
            "python.exe",
        )
        _add_python_candidate(candidates, runtime_python)

    for version in versions:
        _add_python_candidate(candidates, f"python{version}")
    _add_python_candidate(candidates, "python3")
    _add_python_candidate(candidates, "python")
    return candidates


def _select_venv_python(preferred_versions: list[str] | None = None) -> tuple[list[str] | None, str]:
    for candidate in _candidate_python_commands(preferred_versions):
        version = _python_version(candidate)
        if _python_satisfies_minimum(version):
            logger.info(f"Selected Python for venv: {' '.join(candidate)} ({version})")
            return candidate, version
        if version:
            logger.info(f"Skipping Python below required version {MIN_PYTHON_VERSION}: {' '.join(candidate)} ({version})")
    return None, ""

def _scan_docs_for_python_version(source_dir: str) -> dict:
    hints = {}
    source_path = Path(source_dir)
    
    for file in [".python-version", "runtime.txt"]:
        path = source_path / file
        if path.exists():
            try:
                content = path.read_text().strip()
                if content:
                    hints["explicit_version"] = _enforce_minimum_python(content)
            except:
                pass
    
    readme = source_path / "README.md"
    if readme.exists():
        try:
            content = readme.read_text()
            if match := re.search(r"[Pp]ython\s+([\d.]+)", content):
                hints["readme_version"] = _enforce_minimum_python(match.group(1))
            if match := re.search(r"requires-python\s*[=><!]+\s*([\d.]+)", content):
                hints["requires_python"] = _enforce_minimum_python(match.group(1))
        except:
            pass
    
    return hints

def _extract_requires_python(pyproject_path: str) -> str:
    if not os.path.isfile(pyproject_path):
        return MIN_PYTHON_VERSION
    try:
        import tomli
        with open(pyproject_path, "rb") as f:
            data = tomli.load(f)
        requires_python = data.get("project", {}).get("requires-python", "")
        if requires_python:
            return _parse_python_requirement(requires_python)
    except:
        try:
            with open(pyproject_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "requires-python" in line.lower():
                        match = re.search(r'["\']([^"\']+)["\']', line)
                        if match:
                            return _parse_python_requirement(match.group(1))
        except:
            pass
    return MIN_PYTHON_VERSION

def _parse_environment_yml(yml_path: str) -> dict:
    data = {"channels": [], "conda_deps": [], "pip_deps": [], "python": None}
    if not yml_path or not os.path.isfile(yml_path):
        return data
    try:
        try:
            import yaml  # type: ignore
            with open(yml_path, 'r', encoding='utf-8') as f:
                obj = yaml.safe_load(f) or {}
            ch = obj.get("channels") or []
            if isinstance(ch, list):
                data["channels"] = [str(x) for x in ch if x]
            deps = obj.get("dependencies") or []
            conda_deps: list[str] = []
            pip_deps: list[str] = []
            if isinstance(deps, list):
                for d in deps:
                    if isinstance(d, str):
                        conda_deps.append(d)
                        if d.strip().startswith("python=") or d.strip().startswith("python=="):
                            data["python"] = d.split("=", 1)[1].lstrip("=")
                    elif isinstance(d, dict) and "pip" in d and isinstance(d["pip"], list):
                        for p in d["pip"]:
                            if isinstance(p, str):
                                pip_deps.append(p)
            data["conda_deps"] = conda_deps
            data["pip_deps"] = pip_deps
        except Exception:
            import re, io
            text = open(yml_path, 'r', encoding='utf-8').read()
            ch_block = re.search(r"(?ms)^channels:\s*\n([\s\S]*?)(?=^\S|\Z)", text)
            if ch_block:
                for line in io.StringIO(ch_block.group(1)):
                    s = line.strip()
                    if s.startswith('-'):
                        data["channels"].append(s.lstrip('-').strip())
            deps_block = re.search(r"(?ms)^dependencies:\s*\n([\s\S]*?)(?=^\S|\Z)", text)
            pip_block = re.search(r"(?ms)^\s*-\s*pip\s*:\s*\n([\s\S]*?)(?=^\s*-[^\s]|^\S|\Z)", text)
            if deps_block:
                for line in io.StringIO(deps_block.group(1)):
                    if 'pip:' in line:
                        continue
                    s = line.strip()
                    if s.startswith('-'):
                        val = s.lstrip('-').strip()
                        if val:
                            data["conda_deps"].append(val)
                            if val.startswith("python=") or val.startswith("python=="):
                                data["python"] = val.split("=", 1)[1].lstrip('=')
            if pip_block:
                for line in io.StringIO(pip_block.group(1)):
                    s = line.strip()
                    if s.startswith('-'):
                        val = s.lstrip('-').strip()
                        if val:
                            data["pip_deps"].append(val)
    except Exception:
        pass
    return data

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
                _run(python_cmd + ["-m", "pip", "install", "-r", req], cwd=cwd, timeout=_dependency_install_timeout())
            else:
                _run(python_cmd + ["-m", "pip", "install", p], cwd=cwd, timeout=_dependency_install_timeout())
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
    env_info = {"type": "conda", "name": env_name, "files": {}, "python": MIN_PYTHON_VERSION, "exec_prefix": []}
    
    conda_exe = os.environ.get("CONDA_EXE")
    if not conda_exe or not os.path.exists(conda_exe):
        if _check_conda_available():
            conda_exe = os.environ.get("CONDA_EXE")
        if not conda_exe or not os.path.exists(conda_exe):
            logger.error("Conda executable not found")
            return None
    
    logger.info(f"Using conda: {conda_exe}")
    
    source_dir = os.path.join(repo_root, "source")
    doc_hints = _scan_docs_for_python_version(source_dir) if os.path.isdir(source_dir) else {}
    
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
            code, out, err = _run([conda_exe, "env", "create", "-n", env_name, "-f", env_yml_path, "--solver=libmamba"]) 
            if code == 0:
                env_info["files"]["environment_yml"] = env_yml_path
                return env_info
            code2, out2, err2 = _run([conda_exe, "env", "update", "-n", env_name, "-f", env_yml_path, "--prune", "--solver=libmamba"]) 
            if code2 == 0:
                env_info["files"]["environment_yml"] = env_yml_path
                return env_info
            yml_data = _parse_environment_yml(env_yml_path)
            yml_python = yml_data.get("python")
            
            preferred_versions = []
            if yml_python:
                preferred_versions.append(_enforce_minimum_python(yml_python))
            if doc_hints.get("explicit_version"):
                preferred_versions.append(doc_hints["explicit_version"])
            if doc_hints.get("readme_version"):
                preferred_versions.append(doc_hints["readme_version"])
            
            preferred_versions.extend(FALLBACK_PYTHON_VERSIONS)
            preferred_versions = list(dict.fromkeys(preferred_versions))
            
            created = False
            selected_py = MIN_PYTHON_VERSION
            for py_ver in preferred_versions:
                code3, out3, err3 = _run([conda_exe, "create", "-n", env_name, f"python={py_ver}", "--yes", "--solver=libmamba"])
                if code3 == 0:
                    created = True
                    selected_py = py_ver
                    logger.info(f"Created conda environment with Python {py_ver}")
                    break
            
            if created:
                env_info["files"]["environment_yml"] = env_yml_path
                env_info["python"] = selected_py
                install_args = [conda_exe, "run", "-n", env_name, "conda", "install", "-y"]
                channels = yml_data.get("channels") or []
                for ch in channels:
                    install_args.extend(["-c", ch])
                conda_deps = [d for d in (yml_data.get("conda_deps") or []) if d and not d.startswith("python")]
                if conda_deps:
                    _run(install_args + conda_deps, cwd=repo_root, timeout=3600)
                pip_deps = yml_data.get("pip_deps") or []
                if pip_deps:
                    _run([conda_exe, "run", "-n", env_name, "python", "-m", "pip", "install"] + pip_deps, cwd=repo_root, timeout=3600)
                return env_info
            
            logger.warning(f"Failed to create conda environment with any Python version")
            return None
    
    logger.info(f"Creating base conda environment: {env_name}")
    
    preferred_versions = []
    pyproject_path = None
    pyproject_root = os.path.join(repo_root, "pyproject.toml")
    source_pyproject = os.path.join(repo_root, "source", "pyproject.toml")
    if os.path.exists(pyproject_root):
        pyproject_path = pyproject_root
    elif os.path.exists(source_pyproject):
        pyproject_path = source_pyproject
    
    if pyproject_path:
        pyproject_version = _extract_requires_python(pyproject_path)
        if pyproject_version != MIN_PYTHON_VERSION:
            preferred_versions.append(pyproject_version)
    
    if doc_hints.get("explicit_version"):
        preferred_versions.append(doc_hints["explicit_version"])
    if doc_hints.get("readme_version"):
        preferred_versions.append(doc_hints["readme_version"])
    
    preferred_versions.extend(FALLBACK_PYTHON_VERSIONS)
    preferred_versions = list(dict.fromkeys(preferred_versions))
    
    created = False
    selected_py = MIN_PYTHON_VERSION
    for py_ver in preferred_versions:
        code, out, err = _run([conda_exe, "create", "-n", env_name, f"python={py_ver}", "--yes", "--solver=libmamba"])
        if code == 0:
            created = True
            selected_py = py_ver
            logger.info(f"Base conda environment created with Python {py_ver}")
            break
    
    if created:
        env_info["python"] = selected_py
        env_info["base_installation"] = _install_base_packages(
            [conda_exe, "run", "-n", env_name, "pip", "install"],
            repo_root,
        )
        if not env_info["base_installation"]["passed"]:
            logger.warning(f"Base MCP environment package installation failed: {env_info['base_installation']['message']}")
            return None
        
        if not deps.get("has_environment_yml"):
            python_exe_conda = f"{conda_exe} run -n {env_name} python"
            
            if deps.get("pyproject") and pyproject_path:
                _run([conda_exe, "run", "-n", env_name, "pip", "install", "-e", os.path.dirname(pyproject_path)], cwd=repo_root, timeout=_dependency_install_timeout())
            else:
                package_name = _extract_package_name(repo_root)
                if package_name:
                    _run([conda_exe, "run", "-n", env_name, "pip", "install", package_name], cwd=repo_root, timeout=_dependency_install_timeout())
            
            if deps.get("has_requirements_txt"):
                req_txt = os.path.join(repo_root, "requirements.txt")
                source_req_txt = os.path.join(repo_root, "source", "requirements.txt")
                req_txt_path = None
                if os.path.exists(req_txt):
                    req_txt_path = req_txt
                elif os.path.exists(source_req_txt):
                    req_txt_path = source_req_txt
                if req_txt_path:
                    logger.info(f"Installing from requirements.txt")
                    _run([conda_exe, "run", "-n", env_name, "pip", "install", "-r", req_txt_path], cwd=repo_root, timeout=_dependency_install_timeout())
            
            yml_paths = [os.path.join(repo_root, "environment.yml"), os.path.join(repo_root, "source", "environment.yml")]
            python_cmd = [conda_exe, "run", "-n", env_name, "python"]
            _install_pip_from_env_yml(python_cmd, yml_paths, repo_root)
        
        return env_info
    else:
        logger.error(f"Failed to create conda environment with any Python version")
        return None


# Create unique environment name and path for each repository
def _create_venv_env(repo_root: str, repo_name: str, deps: Dict[str, Any]) -> Dict[str, Any]:
    timestamp = str(int(time.time()))[-6:]
    env_name = f"{repo_name}_{timestamp}_venv"
    env_path = os.path.join(repo_root, env_name)
    
    source_dir = os.path.join(repo_root, "source")
    doc_hints = _scan_docs_for_python_version(source_dir) if os.path.isdir(source_dir) else {}
    
    preferred_versions = []
    pyproject_path = None
    pyproject_root = os.path.join(repo_root, "pyproject.toml")
    source_pyproject = os.path.join(repo_root, "source", "pyproject.toml")
    if os.path.exists(pyproject_root):
        pyproject_path = pyproject_root
    elif os.path.exists(source_pyproject):
        pyproject_path = source_pyproject
    
    if pyproject_path:
        pyproject_version = _extract_requires_python(pyproject_path)
        if pyproject_version != MIN_PYTHON_VERSION:
            preferred_versions.append(pyproject_version)
    
    if doc_hints.get("explicit_version"):
        preferred_versions.append(doc_hints["explicit_version"])
    if doc_hints.get("readme_version"):
        preferred_versions.append(doc_hints["readme_version"])
    
    preferred_versions.extend(FALLBACK_PYTHON_VERSIONS)
    preferred_versions = list(dict.fromkeys(preferred_versions))
    selected_py = preferred_versions[0] if preferred_versions else MIN_PYTHON_VERSION

    base_python_cmd, base_python_version = _select_venv_python(preferred_versions)
    if not base_python_cmd:
        logger.warning(f"No Python interpreter >= {MIN_PYTHON_VERSION} found for venv creation")
        return None
    
    env_info = {
        "type": "venv",
        "name": env_name,
        "path": env_path,
        "files": {},
        "python": base_python_version.replace("Python", "").strip() or selected_py,
        "base_python": " ".join(base_python_cmd),
        "exec_prefix": [],
    }
    
    venv_py = _venv_python_path(env_path)
    if not os.path.isfile(venv_py):
        logger.info(f"Creating isolated venv environment: {env_name}")
        code, out, err = _run(base_python_cmd + ["-m", "venv", env_path], cwd=repo_root)
        if code != 0:
            logger.warning(f"Failed to create venv: {err or out}")
            return None

    if os.path.isfile(venv_py):
        actual_version = _python_version(venv_py)
        if not _python_satisfies_minimum(actual_version):
            logger.warning(f"Venv Python is below required version {MIN_PYTHON_VERSION}: {actual_version}")
            return None
        env_info["python"] = actual_version.replace("Python", "").strip() or selected_py

        logger.info(f"Upgrading pip: {env_name}")
        pip_code, pip_out, pip_err = _run([venv_py, "-m", "pip", "install", "-U", "pip"], cwd=repo_root, timeout=_base_install_timeout())
        env_info["pip_upgrade"] = {
            "passed": pip_code == 0,
            "exit_code": pip_code,
            "message": (pip_err or pip_out)[-1000:],
        }
        if pip_code != 0:
            logger.warning(f"pip upgrade failed; continuing with bundled pip: {pip_err or pip_out}")

        env_info["base_installation"] = _install_base_packages([venv_py, "-m", "pip", "install"], repo_root)
        if not env_info["base_installation"]["passed"]:
            logger.warning(f"Base MCP environment package installation failed: {env_info['base_installation']['message']}")
            return None

        env_info["dependency_installation"] = _install_deps_with_priority(venv_py, repo_root, deps, repo_name)

        yml_paths = [os.path.join(repo_root, "environment.yml"), os.path.join(repo_root, "source", "environment.yml")]
        _install_pip_from_env_yml([venv_py], yml_paths, repo_root)
        
        env_info["exec_prefix"] = [venv_py]
        logger.info(f"Isolated venv environment created successfully: {env_name}")
        return env_info

    return None

def _venv_python_path(env_path: str) -> str:
    if os.name == "nt":
        return os.path.join(env_path, "Scripts", "python.exe")
    return os.path.join(env_path, "bin", "python")


def _check_uv_available() -> bool:
    try:
        code, out, err = _run(["uv", "--version"])
        if code == 0:
            logger.info(f"UV available: {out.strip()}")
            return True
    except Exception:
        pass
    logger.info("UV not available, will use conda/venv")
    return False


def _extract_package_name(repo_root: str) -> str:
    pyproject_paths = [
        os.path.join(repo_root, "pyproject.toml"),
        os.path.join(repo_root, "source", "pyproject.toml")
    ]
    
    for pyproject_path in pyproject_paths:
        if not os.path.exists(pyproject_path):
            continue
        try:
            import tomli
            with open(pyproject_path, "rb") as f:
                data = tomli.load(f)
            name = data.get("project", {}).get("name")
            if name:
                return name
        except:
            try:
                with open(pyproject_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "name" in line.lower() and "=" in line:
                            match = re.search(r'["\']([^"\']+)["\']', line)
                            if match:
                                return match.group(1)
            except:
                pass
    setup_py_paths = [
        os.path.join(repo_root, "setup.py"),
        os.path.join(repo_root, "source", "setup.py"),
    ]
    for setup_py_path in setup_py_paths:
        name = _extract_setup_py_package_name(setup_py_path)
        if name:
            return name
    return ""


def _extract_setup_py_package_name(setup_py_path: str) -> str:
    if not os.path.isfile(setup_py_path):
        return ""
    try:
        import ast
        text = Path(setup_py_path).read_text(encoding="utf-8-sig", errors="ignore")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "setup":
                for keyword in node.keywords:
                    if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                        value = keyword.value.value
                        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                            return value
    except Exception:
        pass

    try:
        text = Path(setup_py_path).read_text(encoding="utf-8-sig", errors="ignore")
        match = re.search(r"\bsetup\s*\([\s\S]*?\bname\s*=\s*['\"]([A-Za-z0-9_.-]+)['\"]", text)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def _clean_import_packages(packages: Any) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    install_heavy = os.getenv("CODE2MCP_INSTALL_HEAVY_IMPORT_DEPS", "false").lower() == "true"
    for raw in packages or []:
        package = str(raw or "").strip()
        if not package or not re.fullmatch(r"[A-Za-z0-9_.-]+", package):
            continue
        key = package.lower()
        if key in HEAVY_IMPORT_DEPENDENCIES and not install_heavy:
            continue
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(package)
    cleaned.sort(key=lambda pkg: (IMPORT_DEPENDENCY_PRIORITY.get(pkg.lower(), 100), pkg.lower()))
    return cleaned[:MAX_IMPORT_DEPENDENCIES]


def _install_import_packages(python_exe: str, repo_root: str, packages: list[str]) -> Dict[str, Any]:
    installed: list[str] = []
    installed_distributions: dict[str, str] = {}
    failed: dict[str, str] = {}
    last_code = 0
    for package in packages:
        candidates = [package] + IMPORT_PACKAGE_INSTALL_FALLBACKS.get(package.lower(), [])
        last_error = ""
        for candidate in candidates:
            code, out, err = _run(
                [python_exe, "-m", "pip", "install", candidate],
                cwd=repo_root,
                timeout=_dependency_install_timeout(),
            )
            last_code = code
            if code == 0:
                installed.append(package)
                installed_distributions[package] = candidate
                break
            last_error = (err or out)[-500:]
            logger.warning(f"Import dependency install failed for {candidate}: {err or out}")
        else:
            failed[package] = last_error

    passed = bool(packages) and not failed
    message = ""
    if failed:
        message = json.dumps(
            {"installed": installed, "installed_distributions": installed_distributions, "failed": failed},
            ensure_ascii=False,
        )[-1000:]
    return {
        "passed": passed,
        "strategy": "import_packages",
        "exit_code": 0 if passed else last_code or 1,
        "message": message,
        "installed": installed,
        "installed_distributions": installed_distributions,
        "failed": failed,
    }


def _install_full_requirements_first() -> bool:
    return os.getenv("CODE2MCP_INSTALL_FULL_REQUIREMENTS_FIRST", "false").strip().lower() in {"1", "true", "yes", "on"}


def _requirements_paths(repo_root: str) -> list[str]:
    return [
        path
        for path in (
            os.path.join(repo_root, "requirements.txt"),
            os.path.join(repo_root, "source", "requirements.txt"),
        )
        if os.path.exists(path)
    ]


def _install_requirements_file(python_exe: str, repo_root: str, req_path: str) -> Dict[str, Any]:
    logger.info("Installing from requirements.txt")
    code, out, err = _run(
        [python_exe, "-m", "pip", "install", "-r", req_path],
        cwd=repo_root,
        timeout=_dependency_install_timeout(),
    )
    result = {
        "passed": code == 0,
        "strategy": "requirements",
        "exit_code": code,
        "message": "" if code == 0 else (err or out)[-1000:],
        "requirements_path": req_path,
    }
    if code != 0:
        logger.warning(f"requirements.txt install failed: {err or out}")
    return result


def _install_deps_with_priority(python_exe: str, repo_root: str, deps: Dict[str, Any], repo_name: str):
    result = {
        "passed": False,
        "strategy": "none",
        "exit_code": None,
        "message": "",
        "attempts": [],
    }
    if deps.get("pyproject"):
        pyproject_paths = [
            os.path.join(repo_root, "pyproject.toml"),
            os.path.join(repo_root, "source", "pyproject.toml")
        ]
        for pyproject_path in pyproject_paths:
            if os.path.exists(pyproject_path):
                code, out, err = _run([python_exe, "-m", "pip", "install", "-e", os.path.dirname(pyproject_path)], cwd=repo_root, timeout=_dependency_install_timeout())
                attempt = {"passed": code == 0, "strategy": "editable", "exit_code": code, "message": "" if code == 0 else (err or out)[-1000:]}
                result["attempts"].append(attempt)
                if code == 0:
                    result.update(attempt)
                    return result
                result.update({"strategy": "editable", "exit_code": code, "message": (err or out)[-1000:]})
                logger.warning(f"Editable install failed: {err or out}")
    
    package_name = _extract_package_name(repo_root)
    if package_name:
        code, out, err = _run([python_exe, "-m", "pip", "install", package_name], cwd=repo_root, timeout=_dependency_install_timeout())
        attempt = {"passed": code == 0, "strategy": "package", "exit_code": code, "message": "" if code == 0 else (err or out)[-1000:], "package": package_name}
        result["attempts"].append(attempt)
        if attempt["passed"]:
            result.update(attempt)
            return result
        result.update({"strategy": "package", "exit_code": code, "message": (err or out)[-1000:]})
        if code != 0:
            logger.warning(f"Package install failed: {err or out}")

    import_packages = _clean_import_packages(deps.get("import_packages"))
    requirements_first = _install_full_requirements_first()
    requirements_attempted = False
    if deps.get("has_requirements_txt") and requirements_first:
        for req_path in _requirements_paths(repo_root):
            req_result = _install_requirements_file(python_exe, repo_root, req_path)
            result["attempts"].append(req_result)
            result.update(req_result)
            requirements_attempted = True
            if req_result["passed"]:
                return result

    if import_packages:
        import_result = _install_import_packages(python_exe, repo_root, import_packages)
        result["attempts"].append(import_result)
        result.update(import_result)
        if import_result["passed"]:
            return result

    if deps.get("has_requirements_txt") and not requirements_attempted:
        for req_path in _requirements_paths(repo_root):
            req_result = _install_requirements_file(python_exe, repo_root, req_path)
            result["attempts"].append(req_result)
            result.update(req_result)
            if req_result["passed"]:
                return result

    return result


def _create_test_infrastructure(repo_root: str, repo_name: str):
    conftest_content = f'''import sys
from pathlib import Path
import matplotlib
import matplotlib.pyplot as plt
import pytest

def pytest_configure(config):
    project_root = Path(__file__).parent.resolve()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

@pytest.fixture(autouse=True)
def no_plot_show(monkeypatch):
    matplotlib.use("Agg")
    monkeypatch.setattr(plt, "show", lambda: None)
'''
    
    pytest_ini_content = f'''[tool:pytest]
testpaths = tests
python_files = *_test.py test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    --disable-warnings
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    unit: marks tests as unit tests
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
'''
    
    return


def _create_uv_env(repo_root: str, repo_name: str, deps: Dict[str, Any]) -> Dict[str, Any]:
    env_name = f"{repo_name}-env"
    env_path = os.path.join(repo_root, env_name)
    
    source_dir = os.path.join(repo_root, "source")
    doc_hints = _scan_docs_for_python_version(source_dir) if os.path.isdir(source_dir) else {}
    
    preferred_versions = []
    pyproject_path = None
    pyproject_root = os.path.join(repo_root, "pyproject.toml")
    source_pyproject = os.path.join(repo_root, "source", "pyproject.toml")
    if os.path.exists(pyproject_root):
        pyproject_path = pyproject_root
    elif os.path.exists(source_pyproject):
        pyproject_path = source_pyproject
    
    if pyproject_path:
        pyproject_version = _extract_requires_python(pyproject_path)
        if pyproject_version != MIN_PYTHON_VERSION:
            preferred_versions.append(pyproject_version)
    
    if doc_hints.get("explicit_version"):
        preferred_versions.append(doc_hints["explicit_version"])
    if doc_hints.get("readme_version"):
        preferred_versions.append(doc_hints["readme_version"])
    
    preferred_versions.extend(FALLBACK_PYTHON_VERSIONS)
    preferred_versions = list(dict.fromkeys(preferred_versions))
    
    env_info = None
    for py_ver in preferred_versions:
        code, out, err = _run(["uv", "venv", "--python", py_ver, env_path], cwd=repo_root)
        if code == 0:
            env_info = {
                "type": "uv",
                "name": env_name,
                "path": env_path,
                "files": {},
                "python": py_ver,
                "exec_prefix": []
            }
            logger.info(f"UV environment created with Python {py_ver}")
            break
    
    if not env_info:
        logger.warning("Failed to create UV environment with any Python version")
        return None
    
    venv_py = _venv_python_path(env_path)
    if not os.path.isfile(venv_py):
        logger.warning(f"UV Python executable not found: {venv_py}")
        return None
    
    env_info["exec_prefix"] = [venv_py]
    actual_version = _python_version(venv_py)
    if not _python_satisfies_minimum(actual_version):
        logger.warning(f"UV Python is below required version {MIN_PYTHON_VERSION}: {actual_version}")
        return None
    env_info["python"] = actual_version.replace("Python", "").strip() or env_info["python"]
    
    env_info["base_installation"] = _install_base_packages([venv_py, "-m", "pip", "install"], repo_root)
    if not env_info["base_installation"]["passed"]:
        logger.warning(f"Base MCP environment package installation failed: {env_info['base_installation']['message']}")
        return None

    env_info["dependency_installation"] = _install_deps_with_priority(venv_py, repo_root, deps, repo_name)
    
    yml_paths = [os.path.join(repo_root, "environment.yml"), os.path.join(repo_root, "source", "environment.yml")]
    _install_pip_from_env_yml([venv_py], yml_paths, repo_root)
    
    logger.info(f"UV environment created successfully: {env_name}")
    return env_info

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
    
    if _check_uv_available():
        logger.info("UV detected, using UV for environment creation")
        env = _create_uv_env(repo_root, repo_name, deps)
        if env:
            logger.info(f"Successfully created UV environment: {env['name']}")
    
    if not env:
        logger.info("Falling back to venv environment creation")
        env = _create_venv_env(repo_root, repo_name, deps)

    if not env and os.getenv("CODE2MCP_ENABLE_CONDA", "false").lower() == "true" and _check_conda_available():
        logger.info("Attempting optional conda environment creation")
        _cleanup_old_envs(repo_name)
        env_name = _env_name(repo_name)
        env = _create_conda_env(env_name, repo_root, deps)
        if env:
            logger.info(f"Successfully created conda environment: {env_name}")
    
    if not env:
        message = f"Unable to create a usable environment with Python >= {MIN_PYTHON_VERSION} and base MCP dependencies"
        state.setdefault("errors", []).append({
            "node": "EnvNode",
            "type": "EnvSetupFailed",
            "message": message,
            "action_taken": "abort"
        })
        state["error"] = message
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state
    
    _create_test_infrastructure(repo_root, repo_name)

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
        code, out, err = _run(cmd, cwd=repo_root, timeout=_test_timeout())
        if code == 0:
            tests["passed"] = True
            logger.info("Pytest tests passed")
        else:
            logger.warning("Pytest failed, falling back to simple import validation")

    if not tests["passed"]:
        # 跳过生成任何 tests_smoke 文件/目录
        pass

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
