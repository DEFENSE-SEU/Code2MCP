# Review Node - Code review and error fixing node
from __future__ import annotations
import json
import os
import re
from typing import Dict, Any
from ..utils import setup_logging, write_file, ensure_directory, get_llm_service

logger = setup_logging()

def _retry_generate_text(llm_service, user_prompt: str, system_prompt: str | None = None, retries: int = 2) -> str:
    delay = 1.0
    last = ""
    for i in range(retries + 1):
        try:
            resp = llm_service.generate_text(user_prompt, system_prompt) if system_prompt is not None else llm_service.generate_text(user_prompt)
            if resp:
                return resp
            last = ""
        except Exception as e:
            last = str(e)
        if i < retries:
            import time as _t
            _t.sleep(delay)
            delay = min(delay * 2, 4.0)
    return last

def _intelligent_error_analysis(state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        llm_service = get_llm_service()
        
        run_result = state.get("run_result", {})
        if not run_result.get("success", False):
            state["fix_retry_count"] = 0
            state["generation_retry_count"] = state.get("generation_retry_count", 0)
            state["workflow_status"] = "failed"
            state["status"] = "failed"
            return state
        errors = state.get("errors", [])
        previous_run_results = state.get("previous_run_results", [])
        retry_count = state.get("fix_retry_count", 0)
        
        system_prompt = """You are a senior software engineer responsible for analyzing code execution errors and developing repair strategies.

Please analyze the error information and determine:
1. Whether the error can be fixed directly by modifying the code
2. What repair strategy needs to be taken

Return analysis results in JSON format."""

        error_message = run_result.get("error", "")
        stderr = run_result.get("stderr", "")
        
        user_prompt = f"""Analyze the following code execution error:

Error message: {error_message}
Detailed output: {stderr}
Retry count: {retry_count}/5
Historical errors: {json.dumps(errors[-3:], ensure_ascii=False)}
Historical run results: {json.dumps(previous_run_results[-3:], ensure_ascii=False)}

Please return JSON format analysis:
{{
    "status": "FAIL",
    "next_action": "fix_directly|regenerate",
    "confidence": 0.8,
    "summary": "Error analysis and repair suggestions"
}}"""
        
        response = _retry_generate_text(llm_service, user_prompt, system_prompt)
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                logger.info(f"Error analysis completed")
                return result
        except Exception as e:
            logger.warning(f"Error analysis parsing failed: {e}")
        
        return {}
        
    except Exception as e:
        logger.error(f"Error analysis failed: {e}")
        return {}

def _apply_incremental_fixes(state: Dict[str, Any], error_analysis: Dict[str, Any]) -> bool:
    try:
        llm_service = get_llm_service()
        
        run_result = state.get("run_result", {})
        error_message = run_result.get("error", "")
        stderr = run_result.get("stderr", "")
        
        if not error_message and not stderr:
            return False
        
        repo = state.get("repository", {})
        repo_root = repo.get("local_paths", {}).get("repo_root")
        
        if not repo_root:
            return False
        

        return _fix_error_with_llm(error_message, stderr, repo_root, llm_service, run_result)
            
    except Exception as e:
        logger.error(f"LLM repair failed: {e}")
        return False

def _fix_error_with_llm(error_message: str, stderr: str, repo_root: str, llm_service, run_result: Dict[str, Any] | None = None) -> bool:
    try:
        system_prompt = """You are a strict code fixer. Must output "complete file replacement" and strictly follow the following protocol:

Output protocol (only this one):
1) First line: file path: relative path
2) Immediately following is the complete new content of that file (pure text, only code, no Markdown fences or additional explanations allowed).

Hard constraints:
- Prohibit output of unified diff/patch/Markdown/excessive comments/natural language explanations
- Only modify the "inferred target file", do not create or modify other files
- Only make minimal necessary modifications; unchanged content is preserved (including whitespace and formatting)
- Code must be parsable by Python (ast.parse passes)
"""

        target_path = _infer_error_file_path(error_message, stderr, repo_root)
        current_text = ""
        if target_path:
            full_path = os.path.join(repo_root, target_path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        current_text = f.read()
                except Exception:
                    current_text = ""
        rc = (run_result or {}).get("exit_code")
        out = (run_result or {}).get("stdout", "")
        hint = ""
        name, module, mod_path = _extract_missing_import_info(error_message, stderr)
        if name and module:
            hint = f"\nHint: Detected from {module} import {name} failed. Please use the current public API of the project instead, and prioritize lazy import and existence check (getattr). \n"

        user_prompt = f"""Project root: {repo_root}
Error message: {error_message}
Error details: {stderr}
Exit code: {rc}
Standard output:
{out}
File path: {target_path or ''}
Current file content start:
{current_text[:4000]}
Current file content end

Please return unified patch or complete replacement content. {hint}"""

        response = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not response:
            logger.warning("LLM did not return a response")
            return False
        
        file_path = _extract_file_path(response) or target_path
        if not file_path:
            logger.warning("Could not determine file path")
            return False
        full_path = os.path.join(repo_root, file_path)
        current = ""
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    current = f.read()
            except Exception:
                current = ""
        new_text = _extract_code_or_plain(response)
        if new_text is None:
            logger.warning("Could not extract code from LLM response")
            return False
        
        new_text = _sanitize_python_source(new_text)
        if full_path.endswith('.py'):
            import ast
            try:
                ast.parse(new_text)
            except Exception as e:
                retry_response = _retry_generate_text(llm_service, f"{user_prompt}\n\nLast generation did not conform to protocol/syntax error: {e}\nPlease strictly follow the protocol and output only complete replacement.", system_prompt)
                if retry_response:
                    retry_file_path = _extract_file_path(retry_response) or file_path
                    if not retry_file_path:
                        return False
                    retry_full_path = os.path.join(repo_root, retry_file_path)
                    retry_new_text = _extract_code_block(retry_response)
                    if retry_new_text:
                        try:
                            retry_new_text = _sanitize_python_source(retry_new_text)
                            ast.parse(retry_new_text)
                            new_text = retry_new_text
                        except Exception as e2:
                            return False
                    else:
                        return False
                else:
                    return False
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        import tempfile
        dirpath = os.path.dirname(full_path)
        with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8', dir=dirpath) as tf:
            tmpname = tf.name
            tf.write(new_text)
        
        try:
            os.replace(tmpname, full_path)
        except Exception as e:
            logger.error(f"File write failed: {e}")
            try:
                os.remove(tmpname)
            except Exception:
                pass
            return False
        return True
        
    except Exception as e:
        logger.error(f"Exception occurred during repair: {e}")
        import traceback
        logger.error(f"Exception stack trace: {traceback.format_exc()}")
        return False

def _extract_file_path(text: str) -> str | None:
    import re
    m = re.search(r"File path:\s*([^\n`\"\']+)\s*", text)
    if m:
        p = m.group(1).strip().strip(' \t`"\'')
        return p
    m2 = re.search(r"^\+\+\+\s+([ab]/)?([^\n]+)$", text, re.MULTILINE)
    if m2:
        return m2.group(2).strip()
    return None

def _extract_patch_or_code(text: str, filename: str, current: str) -> str | None:
    return _extract_code_block(text)

def _extract_code_block(text: str) -> str | None:
    import re
    m = re.search(r"^```(?:python)?\n([\s\S]*?)\n```\s*$", text, re.MULTILINE)
    if m:
        return m.group(1)
    return None


def _extract_code_or_plain(text: str) -> str | None:
    code = _extract_code_block(text)
    if code is not None:
        return code
    lines = text.splitlines()
    if not lines:
        return None
    if lines[0].strip().startswith("File path:"):
        return "\n".join(lines[1:])
    return None

def _has_unified_diff(text: str) -> bool:
    import re
    return re.search(r"^--- .*$\n\+\+\+ .*$", text, re.MULTILINE) is not None

def _apply_unified_diff(original: str, diff_text: str) -> str | None:
    import shutil, subprocess, tempfile, os
    if shutil.which("patch"):
        try:
            with tempfile.TemporaryDirectory() as td:
                f = os.path.join(td, "file.txt")
                d = os.path.join(td, "diff.patch")
                with open(f, 'w', encoding='utf-8') as fh:
                    fh.write(original)
                with open(d, 'w', encoding='utf-8') as dh:
                    dh.write(diff_text)
                res = subprocess.run(["patch", f, d], capture_output=True, text=True)
                if res.returncode == 0:
                    with open(f, 'r', encoding='utf-8') as fh:
                        return fh.read()
                return None
        except Exception:
            return None
    return None

def _extract_missing_import_info(error_message: str, stderr: str) -> tuple[str | None, str | None, str | None]:
    import re
    text = f"{error_message}\n{stderr}"
    m = re.search(r"cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"] \(([^)]+)\)", text)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, None, None

def _infer_error_file_path(error_message: str, stderr: str, repo_root: str) -> str | None:
    import re, os, glob
    text = f"{error_message}\n{stderr}"
    
    m = re.search(r"([A-Za-z]:\\|/)?[\w\-_/\\.]*\.py", text)
    if not m:
        return None
    
    filename = os.path.basename(m.group(0))
    
    path_patterns = [
        r"([A-Za-z]:\\|/)?[\w\-_/\\./]*" + re.escape(filename),  
        r"([\w\-_/\\./]*" + re.escape(filename) + r")",  
    ]
    
    for pattern in path_patterns:
        path_match = re.search(pattern, text)
        if path_match:
            path = path_match.group(0)
            path = path.replace("\\", "/")
            
            if os.path.isabs(path) and path.startswith(repo_root.replace("\\", "/")):
                return os.path.relpath(path, repo_root)
            
            if not os.path.isabs(path):
                full_path = os.path.join(repo_root, path)
                if os.path.exists(full_path):
                    return path
    
    search_pattern = os.path.join(repo_root, "**", filename)
    matches = glob.glob(search_pattern, recursive=True)
    
    if matches:
        rel0 = os.path.relpath(matches[0], repo_root)
        if rel0.startswith("mcp_output" + os.sep):
            return rel0
    name, module, mod_path = _extract_missing_import_info(error_message, stderr)
    mcp_dir = os.path.join(repo_root, "mcp_output")
    if os.path.isdir(mcp_dir) and (name or module):
        pats = []
        if name and module:
            pats.append(f"from {module} import {name}")
            pats.append(f"{module}.{name}")
        elif name:
            pats.append(name)
        elif module:
            pats.append(module)
        for root, _, files in os.walk(mcp_dir):
            for f in files:
                if f.endswith('.py'):
                    p = os.path.join(root, f)
                    try:
                        with open(p, 'r', encoding='utf-8') as fh:
                            c = fh.read()
                        if any(s in c for s in pats):
                            return os.path.relpath(p, repo_root)
                    except Exception:
                        pass
    
    return None

def _parse_and_overwrite_file(llm_response: str, repo_root: str) -> bool:
    try:
        import re, ast, os
        path = _extract_file_path(llm_response)
        if not path:
            return False
        full_path = os.path.join(repo_root, path)
        code = _extract_code_block(llm_response)
        if not code:
            return False
        code = _clean_llm_output(code)
        if full_path.endswith('.py'):
            try:
                ast.parse(code)
            except Exception as e:
                return False
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(code)
        return True
    except Exception:
        return False

def _clean_llm_output(content: str) -> str:
    import re
    content = re.sub(r'^```(?:python)?\s*\n?', '', content)
    content = re.sub(r'\n?\s*```\s*$', '', content)
    return content.strip()

def _sanitize_python_source(src: str) -> str:
    if src and src[0] == '\ufeff':
        src = src[1:]
    src = src.replace('\r\n', '\n').replace('\r', '\n')
    return src if src.endswith('\n') else src + '\n'

def review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    repo = state.get("repository", {})
    paths = repo.get("local_paths", {})
    repo_root = paths.get("repo_root")
    
    if not (repo_root and os.path.isdir(repo_root)):
        state.setdefault("errors", []).append({
            "node": "ReviewNode",
            "type": "InvalidInput",
            "message": "repo_root path missing",
            "action_taken": "abort"
        })
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    ensure_directory(mcp_output_dir)
    
    run_result = state.get("run_result", {})
    if not run_result:
        run_result = {"success": True, "test_passed": True}
        state["run_result"] = run_result
    
    if not run_result.get("success", False):
        logger.info("Detected runtime error, starting deep error analysis...")
        error_analysis = _intelligent_error_analysis(state)
        
        state["error_analysis"] = error_analysis
        
        error_analysis_path = os.path.join(mcp_output_dir, "error_analysis.json")
        try:
            write_file(error_analysis_path, json.dumps(error_analysis, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save error analysis report: {e}")

        next_action = error_analysis.get("next_action", "fix_directly")

        logger.info("Attempting to automatically fix...")
        fix_success = _apply_incremental_fixes(state, error_analysis)
        if fix_success:
            logger.info("Automatic fix successful!")
            state["fix_retry_count"] = 0
            state["fix_applied"] = True
            summary = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "applied",
                "deps_change": False,
                "risks": [],
                "next_focus": "re-run tests"
            }
            state["loop_summary"] = summary
            state["status"] = "running"
            return state
        else:
            logger.warning("Automatic fix failed, please check the logs above")

        current_fix_retries = state.get("fix_retry_count", 0) + 1
        state["fix_retry_count"] = current_fix_retries
        if current_fix_retries >= 5:
            logger.warning("Reached maximum automatic fix attempts (5), stopping workflow")
            state["workflow_status"] = "failed"
            state["status"] = "failed"
            return state

        logger.info(f"Direct fix failed, preparing retry {current_fix_retries}")
        state["loop_summary"] = {
            "task": "runtime_fix",
            "errors": error_analysis,
            "root_cause": error_analysis.get("summary", ""),
            "fixes": "failed",
            "deps_change": False,
            "risks": ["further regeneration may be needed"],
            "next_focus": "analyze generation or deps"
        }
        if "run_result" in state:
            state["previous_run_results"] = state.get("previous_run_results", [])
            state["previous_run_results"].append(state["run_result"])
            del state["run_result"]
        
        state["code_review"] = {
            "report_path": error_analysis_path,
            "overall_score": 50,
            "issues_found": 1,
            "quality_assessment": {
                "structure": "needs_improvement",
                "functionality": "poor",
                "error_handling": "poor",
                "best_practices": "fair",
                "security": "good"
            },
            "recommendations": ["Direct fix failed, automatic fix retry recorded"],
            "error_analysis": error_analysis
        }
        
    else:
        state["fix_retry_count"] = 0
        state["generation_retry_count"] = state.get("generation_retry_count", 0)
        state["loop_summary"] = {
            "task": "runtime_ok",
            "errors": {},
            "root_cause": "",
            "fixes": "none",
            "deps_change": False,
            "risks": [],
            "next_focus": "finalize"
        }

    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state
