# Analysis Node - Use gitingest, LLM, and DeepWiki to analyze repository structure
from __future__ import annotations
import os
import json
import re
from typing import Dict, Any, List
from ..utils import setup_logging, get_llm_service, write_file, fetch_deepwiki
from ..tools.gitingest_client import GitingestClient
from ..tools.deepwiki_client import get_deepwiki_client

logger = setup_logging()


def _is_valid_deepwiki_content(content: str) -> bool:
    if not content or len(content.strip()) < 50:
        return False
    
    loading_indicators = ["Loading...", "loading", "Please wait", "Analyzing", "Processing"]
    if any(indicator in content for indicator in loading_indicators):
        return False
    
    valid_indicators = ["Analysis", "Repository", "Functions", "Classes", "Dependencies", "Features", "Description", "Overview"]
    if any(indicator in content for indicator in valid_indicators):
        return True
    
    if len(content) > 200 and not content.strip().startswith("Warning:"):
        return True
    
    return False


def _scan_source_symbols_with_signatures(source_dir: str) -> Dict[str, Any]:
    symbols: Dict[str, Any] = {}
    if not (source_dir and os.path.isdir(source_dir)):
        return symbols
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not d.startswith('test') and d not in ['__pycache__', '.git']]
        for file in files:
            if not file.endswith('.py'):
                continue
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, source_dir)
            module_path = rel_path.replace(os.sep, '.').replace('.py', '')
            if module_path.endswith('.__init__'):
                module_path = module_path[:-9]
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code = f.read()
                import ast
                tree = ast.parse(code or '')
                funcs: Dict[str, list] = {}
                classes: set = set()
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                        params = [arg.arg for arg in node.args.args]
                        funcs[node.name] = params
                    elif isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                        classes.add(node.name)
                if funcs or classes:
                    symbols[module_path] = {
                        'functions': funcs,
                        'classes': classes,
                    }
            except Exception:
                continue
    return symbols

def _scan_python_packages(root_dir: str) -> List[str]:
    logger.info(f"Starting Python package scan, root directory: {root_dir}")
    packages: List[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            rel = os.path.relpath(dirpath, root_dir)
            if rel.count(os.sep) > 2:
                continue
            if "__init__.py" in filenames:
                pkg = rel.replace(os.sep, ".") if rel != "." else ""
                if pkg:
                    packages.append(pkg)
        return sorted(list(set(packages)))
    except Exception as e:
        logger.error(f"Error occurred while scanning Python packages: {e}")
        import traceback
        logger.error(f"Detailed error information: {traceback.format_exc()}")
        return []


def _scan_entry_points(working_dir: str) -> Dict[str, Any]:
    entry_points = {"imports": [], "cli": [], "modules": []}
    
    setup_py = os.path.join(working_dir, "setup.py")
    if os.path.exists(setup_py):
        try:
            with open(setup_py, 'r', encoding='utf-8') as f:
                content = f.read()
            
            matches = re.findall(r'console_scripts.*?\[(.*?)\]', content, re.DOTALL)
            for match in matches:
                scripts = re.findall(r'["\']([^"\']+)=([^"\']+)["\']', match)
                for script_match in scripts:
                    if len(script_match) == 2:
                        script_name, module_path = script_match
                        entry_points["cli"].append({
                            "name": script_name,
                            "module": module_path,
                            "type": "console_script"
                        })
        except Exception as e:
            logger.error(f"Failed to parse setup.py: {e}")
    
    pyproject_toml = os.path.join(working_dir, "pyproject.toml")

    if os.path.exists(pyproject_toml):

        try:
            with open(pyproject_toml, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"pyproject.toml file size: {len(content)} characters")
            
            script_patterns = [
                r'\[project\.scripts\]\s*\n(.*?)(?=\n\[|\n$)', 
                r'\[tool\.poetry\.scripts\]\s*\n(.*?)(?=\n\[|\n$)'
            ]
            
            for pattern_idx, pattern in enumerate(script_patterns):
                matches = re.findall(pattern, content, re.DOTALL)
                
                for match_idx, match in enumerate(matches):
                    scripts = re.findall(r'([^=]+)\s*=\s*["\']([^"\']+)["\']', match)
                    
                    for script_idx, script_match in enumerate(scripts):
                        if len(script_match) == 2:
                            script_name, module_path = script_match
                        else:
                            continue
                        entry_points["cli"].append({
                            "name": script_name.strip(),
                            "module": module_path.strip(),
                            "type": "pyproject_script"
                        })
        except Exception as e:
            logger.error(f"Failed to parse pyproject.toml: {e}")
            import traceback
            logger.error(f"Detailed error information: {traceback.format_exc()}")
    
    return entry_points


def _analyze_with_llm(llm_service, repo_url: str, summary: Dict[str, Any], packages: List[str], entry_points: Dict[str, Any], deepwiki_analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not llm_service:
        logger.warning("LLM service not available, using basic analysis")
        return _basic_analysis(packages, entry_points)
    
    try:
        logger.info(f"Summary size: {len(json.dumps(summary, ensure_ascii=False))} characters")
        
        deepwiki_url = repo_url.replace("github.com", "deepwiki.com") if "github.com" in repo_url else repo_url
        
        deepwiki_info = ""
        if deepwiki_analysis.get("success") and deepwiki_analysis.get("content") and _is_valid_deepwiki_content(deepwiki_analysis.get("content", "")):
            deepwiki_info = f"""
DeepWiki Analysis Results:
{deepwiki_analysis.get("content", "")}
"""
        elif deepwiki_analysis.get("status") == "failed":
            deepwiki_info = f"""
DeepWiki Analysis Failed: {deepwiki_analysis.get("error", "Unknown error")}
"""
        else:
            deepwiki_info = """
DeepWiki Analysis: Skipped or not enabled
"""

        prompt = f"""
Please analyze the following code repository, identify the most suitable MCP plugin implementation strategy:

Original Repository URL: {repo_url}
DeepWiki Analysis URL: {deepwiki_url}

Gitingest Summary:
{json.dumps(summary, indent=2, ensure_ascii=False)}

Python Package Structure:
{json.dumps(packages, indent=2, ensure_ascii=False)}

Identified Entry Points:
{json.dumps(entry_points, indent=2, ensure_ascii=False)}

{deepwiki_info}

Please analyze and output a detailed JSON analysis result, including:

1. Core Function Module Identification
2. List of importable functions/classes
3. CLI Command Identification
4. Dependency Analysis
5. Minimal Intrusion Strategy Suggestions

Important: The scanned Python package paths are accurate, please analyze strictly according to these paths.

Output Format:
{{
    "core_modules": [
        {{
            "package": "Full package path scanned",
            "module": "Specific module name", 
            "functions": ["Function1", "Function2"],
            "classes": ["Class1", "Class2"],
            "description": "Function description"
        }}
    ],
    "cli_commands": [
        {{
            "name": "Command name",
            "module": "Module path",
            "description": "Function description"
        }}
    ],
    "import_strategy": {{
        "primary": "Primary import strategy (import/cli/blackbox)",
        "fallback": "Fallback strategy",
        "confidence": 0.8
    }},
    "dependencies": {{
        "required": ["Dependency1", "Dependency2"],
        "optional": ["Optional dependency1"]
    }},
    "risk_assessment": {{
        "import_feasibility": 0.8,
        "intrusiveness_risk": "low/medium/high",
        "complexity": "simple/medium/complex"
    }}
}}

Note: The package field must use the full scanned package path, do not simplify or modify it. Keep the original package path.
"""
        
        response = llm_service.invoke(prompt)
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                analysis_result = json.loads(json_match.group())
                logger.info("LLM analysis completed")
                return analysis_result
            else:
                logger.warning("JSON format not found in LLM response")
                return _basic_analysis(packages, entry_points)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM response JSON parsing failed: {e}")
            return _basic_analysis(packages, entry_points)
            
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}")
        return _basic_analysis(packages, entry_points)


def _basic_analysis(packages: List[str], entry_points: Dict[str, Any]) -> Dict[str, Any]:
    core_modules = []
    if packages:
        top_package = min(packages, key=lambda p: p.count("."))
        core_modules.append({
            "package": top_package,
            "module": top_package,
            "functions": ["main"],
            "classes": [],
            "description": "Main function module"
        })
    
    return {
        "core_modules": core_modules,
        "cli_commands": entry_points.get("cli", []),
        "import_strategy": {
            "primary": "import" if packages else "cli" if entry_points.get("cli") else "blackbox",
            "fallback": "cli" if entry_points.get("cli") else "blackbox",
            "confidence": 0.5
        },
        "dependencies": {
            "required": [],
            "optional": []
        },
        "risk_assessment": {
            "import_feasibility": 0.5 if packages else 0.2,
            "intrusiveness_risk": "low" if packages else "medium",
            "complexity": "simple"
        }
    }

def analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:

    logger.info("=== Starting analysis node ===")
    
    repo = state.get("repository", {})
    repo_url = repo.get("url")
    repo_root = repo.get("local_paths", {}).get("repo_root")
    
    logger.info(f"Repository URL: {repo_url}")
    logger.info(f"Repository root directory: {repo_root}")
    
    if not (repo_url and repo_root and os.path.isdir(repo_root)):
        logger.error("Missing repo_url or repo_root path")
        state.setdefault("errors", []).append({
            "node": "AnalysisNode",
            "type": "InvalidInput",
            "message": "Missing repo_url or repo_root path",
            "action_taken": "abort"
        })
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    summary: Dict[str, Any] = {}
    try:
        logger.info("Starting gitingest client call...")
        client = GitingestClient()
        logger.info("gitingest client created successfully")
    
        summary = client.preprocess_repository_sync(repo_url)
        if summary is None:
            summary = {"status": "failed", "error": "gitingest preprocess returned None"}
            logger.warning("gitingest preprocess failed, returned None")
        logger.info("gitingest preprocess completed")
    except Exception as e:
        logger.error(f"gitingest preprocess failed: {e}")
        import traceback
        logger.error(f"Detailed error information: {traceback.format_exc()}")
        state.setdefault("warnings", []).append(f"gitingest preprocess failed: {e}")

    packages = _scan_python_packages(repo_root)
    entry_points = _scan_entry_points(repo_root)
    source_dir = os.path.join(repo_root, "source")
    dependencies = {
        "has_environment_yml": (
            os.path.exists(os.path.join(repo_root, "environment.yml")) or
            os.path.exists(os.path.join(source_dir, "environment.yml"))
        ),
        "has_requirements_txt": (
            os.path.exists(os.path.join(repo_root, "requirements.txt")) or
            os.path.exists(os.path.join(source_dir, "requirements.txt"))
        ),
        "pyproject": (
            os.path.exists(os.path.join(repo_root, "pyproject.toml")) or
            os.path.exists(os.path.join(source_dir, "pyproject.toml"))
        ),
        "setup_cfg": (
            os.path.exists(os.path.join(repo_root, "setup.cfg")) or
            os.path.exists(os.path.join(source_dir, "setup.cfg"))
        ),
        "setup_py": (
            os.path.exists(os.path.join(repo_root, "setup.py")) or
            os.path.exists(os.path.join(source_dir, "setup.py"))
        ),
    }
    logger.info(f"Dependency file check results: {dependencies}")

    deepwiki_analysis = {"status": "skipped"}
    deepwiki_model = state.get("options", {}).get("deepwiki_model")
    disable_deepwiki = os.getenv("DISABLE_DEEPWIKI", "false").lower() == "true"
    if deepwiki_model and not disable_deepwiki:
        try:
            model = deepwiki_model
            deepwiki_client = get_deepwiki_client(model=model)
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            deepwiki_analysis = deepwiki_client.analyze_repository(repo_url, repo_name)
            logger.info("DeepWiki analysis completed")
        except Exception as e:
            deepwiki_analysis = {"status": "failed", "error": "DeepWiki analysis failed"}
    else:
        logger.info("DeepWiki analysis skipped (model not configured)")

    try:
        if repo_url:
            dw_url = repo_url.replace("github.com", "deepwiki.com") if "github.com" in repo_url else repo_url
            r = fetch_deepwiki(dw_url)
            if r.get("success") and r.get("content"):
                content = r.get("content")
                if content and len(content.strip()) > 50:
                    deepwiki_analysis = deepwiki_analysis or {}
                    deepwiki_analysis["content"] = content
                    deepwiki_analysis["source"] = "jina_api"
                    deepwiki_analysis["status"] = deepwiki_analysis.get("status", "ok")
                    logger.info("Jina fetch success - content updated")
                else:
                    logger.warning(f"Jina content too short or empty, length: {len(content) if content else 0}")
    except Exception as e:
        logger.error(f"Jina fetch failed: {e}")
    
    logger.info("Starting LLM service...")
    llm_service = get_llm_service()
    logger.info("LLM service obtained")
    
    # Static AST-driven source scan to ensure correctness on script-style repos
    source_symbols = _scan_source_symbols_with_signatures(source_dir)
    static_core_modules: List[Dict[str, Any]] = []
    for module_path, sym in source_symbols.items():
        pkg = module_path.rsplit('.', 1)[0] if '.' in module_path else module_path
        mod = module_path.split('.')[-1]
        static_core_modules.append({
            "package": pkg,
            "module": mod,
            "functions": sorted(list(sym.get('functions', {}).keys())),
            "classes": sorted(list(sym.get('classes', []))),
            "function_signatures": sym.get('functions', {}),
            "description": "Discovered via AST scan"
        })

    logger.info("Starting LLM analysis...")
    llm_analysis = _analyze_with_llm(llm_service, repo_url, summary, packages, entry_points, deepwiki_analysis)
    logger.info("LLM analysis completed")

    # Prefer static modules when no pyproject or no packages found to avoid invented package names
    if (not packages) or (not dependencies.get("pyproject")):
        llm_analysis = dict(llm_analysis or {})
        llm_analysis["core_modules"] = static_core_modules or llm_analysis.get("core_modules", [])
        # Favor local import strategy
        llm_analysis["import_strategy"] = {
            "primary": "import",
            "fallback": llm_analysis.get("import_strategy", {}).get("fallback", "cli"),
            "confidence": 0.9,
        }

    analysis_result = {
        "summary": summary,
        "structure": {"packages": packages},
        "dependencies": dependencies,
        "entry_points": entry_points,
        "llm_analysis": llm_analysis,
        "deepwiki_analysis": deepwiki_analysis,
        "deepwiki_options": {
            "enabled": bool(deepwiki_model),
            "model": deepwiki_model,
        },
        "risk": llm_analysis.get("risk_assessment", {
            "import_feasibility": 0.5,
            "intrusiveness_risk": "low",
            "complexity": "simple"
        })
    }

    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    os.makedirs(mcp_output_dir, exist_ok=True)
    
    analysis_json_path = os.path.join(mcp_output_dir, "analysis.json")
    try:
        write_file(analysis_json_path, json.dumps(analysis_result, ensure_ascii=False, indent=2))
        logger.info(f"Analysis results saved to: {analysis_json_path}")
    except Exception as e:
        logger.warning(f"Failed to save analysis.json: {e}")
        state.setdefault("warnings", []).append(f"Failed to save analysis.json: {e}")

    state["analysis"] = analysis_result
    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state
