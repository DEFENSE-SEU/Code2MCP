# Review Node - Code review and error fixing node
from __future__ import annotations
import json
import os
import re
import difflib
import subprocess
from pathlib import Path
from typing import Dict, Any
from ..utils import (
    setup_logging,
    write_file,
    ensure_directory,
    get_llm_service,
    is_non_retryable_llm_error,
    redact_sensitive_data,
    redact_sensitive_text,
)
from ..loop_control import append_loop_event, archive_failed_run_once, clear_runtime_validation
from .run_node import (
    _client_validation_evidence_errors,
    _client_validation_requires_meaningful_result,
    _client_validation_requires_semantic_success,
)

logger = setup_logging()

MAX_FIX_RETRIES = int(os.getenv("CODE2MCP_MAX_FIX_RETRIES", "5"))
MAX_GENERATION_RETRIES = int(os.getenv("CODE2MCP_MAX_GENERATION_RETRIES", "5"))
MAX_DIRECT_FIX_ATTEMPTS_PER_RUN = int(os.getenv("CODE2MCP_MAX_DIRECT_FIX_ATTEMPTS_PER_RUN", "1"))


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _review_llm_enabled() -> bool:
    return _truthy_env("CODE2MCP_REVIEW_LLM", "false")


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
            if is_non_retryable_llm_error(e):
                setattr(llm_service, "last_non_retryable_error", last)
                return ""
        if i < retries:
            import time as _t
            _t.sleep(delay)
            delay = min(delay * 2, 4.0)
    return last


def _runtime_error_text(run_result: Dict[str, Any]) -> str:
    return "\n".join(
        str(run_result.get(key, "") or "")
        for key in ("error", "stderr", "stdout")
    )


def _heuristic_error_analysis(run_result: Dict[str, Any]) -> Dict[str, Any]:
    text = _runtime_error_text(run_result)
    lowered = text.lower()

    result = {
        "status": "FAIL",
        "next_action": "fix_directly",
        "confidence": 0.55,
        "summary": (run_result.get("error") or "Runtime validation failed")[:500],
        "target_file": "mcp_output/mcp_plugin/mcp_service.py",
        "safety_notes": ["Only generated files under mcp_output/ may be edited."],
        "source": "heuristic",
    }

    if "fastmcp app registered no tools" in lowered or "registered no tools" in lowered:
        result.update({
            "next_action": "regenerate",
            "confidence": 0.9,
            "summary": "Generated FastMCP service registered no usable tools.",
            "target_file": "",
        })
    elif "syntaxerror" in lowered or "indentationerror" in lowered:
        result.update({
            "next_action": "fix_directly",
            "confidence": 0.9,
            "summary": "Generated Python service is not syntactically valid.",
        })
    elif "cannot import name" in lowered or "has no attribute" in lowered:
        result.update({
            "next_action": "fix_directly",
            "confidence": 0.75,
            "summary": "Generated service references an import or symbol that is not available at runtime.",
        })
    elif "no module named" in lowered or "modulenotfounderror" in lowered:
        if "fastmcp" in lowered:
            result.update({
                "next_action": "fail",
                "confidence": 0.85,
                "summary": "FastMCP is unavailable in the execution environment after installation attempt.",
                "target_file": "",
            })
        else:
            result.update({
                "next_action": "fix_directly",
                "confidence": 0.75,
                "summary": "Generated service import path is likely wrong or missing source path setup.",
            })
    elif "outside the allowed directory" in lowered or "path traversal" in lowered:
        result.update({
            "next_action": "fail",
            "confidence": 0.9,
            "summary": "Runtime failed because an unsafe path was rejected; this should not be bypassed automatically.",
            "target_file": "",
        })
    return result


def _normalize_error_analysis(value: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return fallback
    next_action = str(value.get("next_action") or "").strip().lower()
    if next_action not in {"fix_directly", "regenerate", "fail"}:
        value["next_action"] = fallback.get("next_action", "fix_directly")
    confidence = value.get("confidence")
    try:
        value["confidence"] = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        value["confidence"] = fallback.get("confidence", 0.5)
    if not value.get("summary"):
        value["summary"] = fallback.get("summary", "Runtime validation failed")
    value.setdefault("status", "FAIL")
    value.setdefault("target_file", fallback.get("target_file", ""))
    value.setdefault("safety_notes", fallback.get("safety_notes", []))
    return value


def _plugin_client_validation_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    plugin_result = ((state.get("tests") or {}).get("plugin") or {})
    if not isinstance(plugin_result, dict):
        return {}
    client_validation = plugin_result.get("client_validation")
    if isinstance(client_validation, dict):
        return client_validation
    details = plugin_result.get("details")
    if isinstance(details, dict) and isinstance(details.get("client_validation"), dict):
        return details["client_validation"]
    return {}


def _runtime_success_evidence_errors(state: Dict[str, Any], run_result: Dict[str, Any]) -> list[str]:
    client_validation = run_result.get("client_validation")
    if not isinstance(client_validation, dict):
        client_validation = _plugin_client_validation_from_state(state)
    if not isinstance(client_validation, dict) or client_validation.get("passed") is not True:
        return ["Runtime validation did not include a passing FastMCP client report"]
    return _client_validation_evidence_errors(
        client_validation,
        require_semantic_success=_client_validation_requires_semantic_success(state),
        require_meaningful_result=_client_validation_requires_meaningful_result(state),
        allow_zero_tools=bool((state.get("options") or {}).get("allow_zero_tools", False)),
    )

def _intelligent_error_analysis(state: Dict[str, Any]) -> Dict[str, Any]:
    run_result = state.get("run_result", {})
    heuristic = _heuristic_error_analysis(run_result)
    if not _review_llm_enabled():
        heuristic["llm_enabled"] = False
        return heuristic
    try:
        llm_service = get_llm_service()
        
        errors = state.get("errors", [])
        previous_run_results = state.get("previous_run_results", [])
        retry_count = state.get("fix_retry_count", 0)
        
        system_prompt = """You are a senior Python engineer reviewing a generated FastMCP service failure.

Analyze only the runtime error evidence. Do not speculate about unrelated product features.
Choose the smallest safe next action:
- fix_directly: only when the failure can be fixed by editing generated files under mcp_output/
- regenerate: when imports/signatures/tool selection are structurally wrong
- fail: when the problem requires changing original source code, installing unavailable system dependencies, or accessing unavailable data

Return JSON only. No Markdown."""

        error_message = redact_sensitive_text(run_result.get("error", ""))
        stderr = redact_sensitive_text(run_result.get("stderr", ""))
        safe_errors = redact_sensitive_data(errors[-3:])
        safe_previous_run_results = redact_sensitive_data(previous_run_results[-3:])
        
        user_prompt = f"""Analyze the following code execution error:

Error message: {error_message}
Detailed output: {stderr}
Retry count: {retry_count}/5
Historical errors: {json.dumps(safe_errors, ensure_ascii=False)}
Historical run results: {json.dumps(safe_previous_run_results, ensure_ascii=False)}

Please return JSON analysis only:
{{
    "status": "FAIL",
    "next_action": "fix_directly|regenerate|fail",
    "confidence": 0.8,
    "summary": "Short evidence-based root cause",
    "target_file": "mcp_output/... or empty",
    "safety_notes": ["Do not edit source/ or files outside mcp_output/"]
}}"""
        
        response = _retry_generate_text(llm_service, user_prompt, system_prompt)
        non_retryable_error = getattr(llm_service, "last_non_retryable_error", "")
        if non_retryable_error:
            heuristic["summary"] = f"{heuristic.get('summary', '')} LLM repair analysis unavailable: {non_retryable_error}"
            heuristic["llm_unavailable"] = True
            return heuristic
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = _normalize_error_analysis(json.loads(json_match.group()), heuristic)
                result.setdefault("source", "llm")
                logger.info(f"Error analysis completed")
                return result
        except Exception as e:
            logger.warning(f"Error analysis parsing failed: {e}")
        
        return heuristic
        
    except Exception as e:
        logger.error(f"Error analysis failed: {e}")
        heuristic["llm_unavailable"] = True
        return heuristic

def _apply_incremental_fixes(state: Dict[str, Any], error_analysis: Dict[str, Any]) -> bool:
    try:
        run_result = state.get("run_result", {})
        error_message = run_result.get("error", "")
        stderr = run_result.get("stderr", "")
        
        if not error_message and not stderr:
            return False
        
        repo = state.get("repository", {})
        repo_root = repo.get("local_paths", {}).get("repo_root")
        
        if not repo_root:
            return False

        attempt = int(state.get("fix_retry_count", 0)) + 1
        state["fix_retry_count"] = attempt
        append_loop_event(
            state,
            "fix_attempt_started",
            attempt=attempt,
            run_attempt=run_result.get("attempt"),
            next_action=error_analysis.get("next_action"),
            summary=error_analysis.get("summary"),
        )

        if _apply_deterministic_fixes(error_message, stderr, repo_root, state.get("analysis", {})):
            precheck_ok, precheck_message = _post_repair_service_precheck(repo_root, state.get("env", {}))
            append_loop_event(
                state,
                "post_repair_precheck_passed" if precheck_ok else "post_repair_precheck_failed",
                attempt=attempt,
                method="deterministic",
                message=precheck_message[:500],
            )
            if not precheck_ok:
                state.setdefault("errors", []).append({
                    "node": "ReviewNode",
                    "type": "PostRepairValidationFailed",
                    "severity": "high",
                    "message": precheck_message,
                    "action_taken": "reject_fix",
                    "attempt": attempt,
                })
                return False
            append_loop_event(
                state,
                "fix_applied",
                attempt=attempt,
                method="deterministic",
                run_attempt=run_result.get("attempt"),
            )
            return True

        if not _review_llm_enabled():
            state["non_retryable_review_error"] = "CODE2MCP_REVIEW_LLM is disabled"
            append_loop_event(
                state,
                "llm_direct_fix_skipped",
                attempt=attempt,
                reason=state["non_retryable_review_error"],
            )
            return False

        try:
            llm_service = get_llm_service()
        except Exception as exc:
            state["non_retryable_review_error"] = str(exc)
            append_loop_event(
                state,
                "fix_unavailable",
                attempt=attempt,
                reason=str(exc)[:500],
            )
            return False

        fixed = _fix_error_with_llm(error_message, stderr, repo_root, llm_service, run_result, state.get("analysis", {}))
        non_retryable_error = getattr(llm_service, "last_non_retryable_error", "")
        if not fixed and non_retryable_error:
            state["non_retryable_review_error"] = non_retryable_error
        if fixed:
            precheck_ok, precheck_message = _post_repair_service_precheck(repo_root, state.get("env", {}))
            append_loop_event(
                state,
                "post_repair_precheck_passed" if precheck_ok else "post_repair_precheck_failed",
                attempt=attempt,
                method="llm",
                message=precheck_message[:500],
            )
            if not precheck_ok:
                state.setdefault("errors", []).append({
                    "node": "ReviewNode",
                    "type": "PostRepairValidationFailed",
                    "severity": "high",
                    "message": precheck_message,
                    "action_taken": "reject_fix",
                    "attempt": attempt,
                })
                return False
        append_loop_event(
            state,
            "fix_applied" if fixed else "fix_failed",
            attempt=attempt,
            method="llm",
            run_attempt=run_result.get("attempt"),
            reason=(non_retryable_error or "")[:500],
        )
        return fixed
            
    except Exception as e:
        logger.error(f"LLM repair failed: {e}")
        return False


def _review_python_command(env_info: Dict[str, Any] | None) -> list[str] | None:
    env_info = env_info or {}
    exec_prefix = env_info.get("exec_prefix")
    if isinstance(exec_prefix, list) and exec_prefix and os.path.isfile(str(exec_prefix[0])):
        return [str(part) for part in exec_prefix]
    if env_info.get("type") in {"venv", "conda"}:
        env_path = env_info.get("path")
        if env_path:
            candidate = os.path.join(str(env_path), "Scripts", "python.exe")
            if os.path.isfile(candidate):
                return [candidate]
            candidate = os.path.join(str(env_path), "bin", "python")
            if os.path.isfile(candidate):
                return [candidate]
    return None


def _post_repair_service_precheck(repo_root: str, env_info: Dict[str, Any] | None) -> tuple[bool, str]:
    """Run an immediate whole-service import check after accepting a repair."""
    command = _review_python_command(env_info)
    if not command:
        return True, "skipped: target environment python is not available in review state"

    mcp_plugin_dir = os.path.join(repo_root, "mcp_output", "mcp_plugin")
    service_path = os.path.join(mcp_plugin_dir, "mcp_service.py")
    if not os.path.isfile(service_path):
        return False, "mcp_service.py is missing after repair"

    script = f"""
import asyncio
import os
import sys
sys.path.insert(0, r'{mcp_plugin_dir}')
service_path = r'{service_path}'
with open(service_path, 'r', encoding='utf-8-sig', errors='ignore') as handle:
    source = handle.read()
if 'no_import_available' in source:
    raise RuntimeError('repaired service still exposes no_import_available fallback')
from mcp_service import create_app
from fastmcp import Client
app = create_app()
async def _count_tools_with_client(mcp_app):
    async with Client(mcp_app) as client:
        value = await client.list_tools()
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return -1
tool_count = asyncio.run(_count_tools_with_client(app))
if tool_count <= 0:
    raise RuntimeError(f'repaired FastMCP client listed no tools (count={{tool_count}})')
print(f'OK client_tools={{tool_count}}')
"""
    try:
        proc = subprocess.run(
            [*command, "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            shell=False,
            check=False,
        )
    except Exception as exc:
        return False, f"post-repair precheck could not run: {exc}"
    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        return False, f"post-repair precheck failed: {output[-1000:]}"
    return True, (proc.stdout or "post-repair precheck passed").strip()


def _failed_runtime_tool_names(run_result: Dict[str, Any] | None) -> list[str]:
    if not isinstance(run_result, dict):
        return []
    client_validation = run_result.get("client_validation")
    if not isinstance(client_validation, dict):
        return []
    errors = [
        str(item or "").lower()
        for item in client_validation.get("errors", []) or []
    ]
    missing_meaningful_evidence = any(
        "no tool call returned meaningful semantic evidence" in item
        for item in errors
    )
    names: list[str] = []
    for call in client_validation.get("calls", []) or []:
        if not isinstance(call, dict):
            continue
        failed = (
            call.get("semantic_success") is False
            or call.get("semantic_passed") is False
            or call.get("transport_passed") is False
            or call.get("passed") is False
            or (missing_meaningful_evidence and call.get("semantic_evidence") is False)
        )
        name = str(call.get("tool", "") or "")
        if failed and name and name not in names:
            names.append(name)
    return names


def _record_runtime_rejected_tools(state: Dict[str, Any], run_result: Dict[str, Any] | None, reason: str) -> list[str]:
    names = _failed_runtime_tool_names(run_result)
    if not names:
        return []
    existing = state.setdefault("runtime_rejected_tools", [])
    existing_names = {
        str(item.get("name", "") if isinstance(item, dict) else item).lower()
        for item in existing
    }
    added: list[str] = []
    for name in names:
        lowered = name.lower()
        if lowered in existing_names:
            continue
        existing.append({
            "name": name,
            "reason": reason,
            "run_attempt": (run_result or {}).get("attempt"),
        })
        existing_names.add(lowered)
        added.append(name)
    if added:
        append_loop_event(
            state,
            "runtime_tools_rejected",
            tools=added,
            reason=reason,
            run_attempt=(run_result or {}).get("attempt"),
        )
    return added


def _prepare_regeneration(state: Dict[str, Any], reason: str, run_result: Dict[str, Any] | None = None) -> bool:
    generation_retry_count = int(state.get("generation_retry_count", 0))
    if generation_retry_count >= MAX_GENERATION_RETRIES:
        message = f"Maximum regeneration attempts reached ({MAX_GENERATION_RETRIES}) after {reason}"
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        state["review_decision"] = "fail"
        state["error"] = message
        append_loop_event(
            state,
            "regeneration_budget_exhausted",
            reason=reason,
            generation_attempt=generation_retry_count,
            run_attempt=(run_result or {}).get("attempt"),
        )
        return False

    _record_runtime_rejected_tools(state, run_result, reason)
    archive_failed_run_once(state, reason=reason)
    state["generation_retry_count"] = generation_retry_count + 1
    state["fix_retry_count"] = 0
    state["regeneration_prepared"] = True
    state["review_decision"] = "regenerate"
    state["status"] = "running"
    clear_runtime_validation(state)
    state.pop("error_analysis", None)
    append_loop_event(
        state,
        "regeneration_started",
        generation_attempt=state.get("generation_retry_count", 0),
        reason=reason,
        run_attempt=(run_result or {}).get("attempt"),
    )
    return True


def _apply_deterministic_fixes(
    error_message: str,
    stderr: str,
    repo_root: str,
    analysis_result: Dict[str, Any] | None = None,
) -> bool:
    text = f"{error_message}\n{stderr}".lower()
    service_path = _safe_generated_file_path(repo_root, "mcp_output/mcp_plugin/mcp_service.py")
    if not service_path or not os.path.exists(service_path):
        return False

    try:
        with open(service_path, "r", encoding="utf-8") as handle:
            current = handle.read()
    except Exception:
        return False

    updated = current
    if (
        ("cannot import name 'create_app'" in text or 'cannot import name "create_app"' in text or "has no attribute 'create_app'" in text)
        and "def create_app(" not in current
        and re.search(r"\bmcp\s*=\s*FastMCP\(", current)
    ):
        updated = current.rstrip() + "\n\n\ndef create_app():\n    return mcp\n"

    if updated == current:
        return False

    validation_errors = _validate_repaired_file_whole(service_path, updated, analysis_result)
    if validation_errors:
        logger.warning(f"Rejected deterministic repair that failed whole-file validation: {validation_errors}")
        return False

    write_file(service_path, _sanitize_python_source(updated))
    return True


def _safe_generated_file_path(repo_root: str, file_path: str | None) -> str | None:
    if not repo_root or not file_path:
        return None
    raw_path = str(file_path).strip()
    if (
        not raw_path
        or "://" in raw_path
        or raw_path.lower().startswith(("file:", "http:", "https:", "s3:", "gs:"))
        or raw_path.startswith(("~", "\\\\", "//"))
    ):
        return None
    try:
        repo_abs = Path(repo_root).resolve()
        mcp_abs = (repo_abs / "mcp_output").resolve()
        candidate = Path(raw_path)
        candidate_abs = candidate.resolve(strict=False) if candidate.is_absolute() else (repo_abs / candidate).resolve(strict=False)
        candidate_abs.relative_to(mcp_abs)
    except (OSError, RuntimeError, ValueError):
        return None
    return str(candidate_abs)


def _repair_contract_for_prompt(analysis_result: Dict[str, Any] | None) -> str:
    if not analysis_result:
        return "No verified analysis contract was provided. Do not invent tools or imports."
    try:
        from .generate_node import _tool_contract_for_prompt
        contract = _tool_contract_for_prompt(analysis_result)
    except Exception:
        try:
            contract = json.dumps(analysis_result.get("llm_analysis", {}).get("core_modules", []), ensure_ascii=False, indent=2)
        except Exception:
            contract = ""
    contract = contract or "No verified symbols were available."
    return contract[:6000]


def _repair_system_prompt() -> str:
    return """You are a strict runtime repair engineer for generated FastMCP services.

Your only job is to repair a generated file using the runtime evidence and verified analysis contract provided by the user.

Output protocol:
- If a safe direct repair is possible, output exactly:
  file path: mcp_output/relative/path.py
  <complete replacement content for that file>
- If a safe direct repair is not possible, output exactly:
  cannot fix safely
  reason: <one short evidence-based reason>

Hard constraints:
- Only modify one generated file under mcp_output/.
- Never modify source/, tests outside mcp_output/, project config, credentials, data files, or user files.
- Do not invent repository APIs, modules, tool names, demo behavior, health checks, monitoring, weather, sentiment, sample tools, or placeholder business logic.
- Every FastMCP tool must remain backed by a function/class in the verified analysis contract.
- Do not use *args or **kwargs in @mcp.tool functions.
- Preserve existing tool names and explicit parameter names unless the runtime evidence proves they are wrong.
- If a tool exposes path-like parameters, keep or add the generated _safe_resolve_path guard. It must reject absolute paths, URL/URI schemes, "~", UNC/network paths, ".." traversal, hidden path segments, sensitive path segments such as secret/token/password/key/credential/private/auth/patient/pii/phi/dob/mrn, and anything resolving outside source_path.
- Do not print secrets, credential values, patient data, or file contents in logs.
- Keep the smallest change that fixes the observed runtime failure.
- The replacement Python file must parse with ast.parse and must include create_app() when repairing mcp_service.py.
- Return a coherent complete file, not a diff, snippet, appended helper, or partial patch.
- Re-read the whole target file before finalizing: do not leave duplicate FastMCP apps, duplicate create_app definitions, stale imports, unreachable wrappers, or tools that still point at missing targets.
- Never mask a failed import by returning fabricated success. Return a structured failure dictionary when the real underlying call is unavailable.
- In any except handler inside a tool, return success=False with the real error; never return success=True from an exception path.

Decision rules:
- Use a direct fix for syntax errors, missing create_app(), wrong local import path, missing sys.path setup, or a small API reference mistake evidenced by the traceback.
- Refuse direct fix when the issue requires changing original source code, installing system packages, downloading unavailable data, bypassing a security guard, or inventing behavior not present in the contract.
- Prefer refusing over guessing."""


def _repair_user_prompt(
    repo_root: str,
    target_path: str | None,
    current_text: str,
    error_message: str,
    stderr: str,
    run_result: Dict[str, Any] | None,
    analysis_result: Dict[str, Any] | None,
    hint: str = "",
) -> str:
    rc = (run_result or {}).get("exit_code")
    out = redact_sensitive_text((run_result or {}).get("stdout", ""))
    safe_error_message = redact_sensitive_text(error_message)
    safe_stderr = redact_sensitive_text(stderr)
    safe_current_text = redact_sensitive_text(current_text)
    contract = _repair_contract_for_prompt(analysis_result)
    target = target_path or "mcp_output/mcp_plugin/mcp_service.py"
    return f"""Project root:
{repo_root}

Allowed repair target:
{target}

Verified wrapper contract:
{contract}

Runtime failure evidence:
- exit_code: {rc}
- error_message:
{safe_error_message}
- stderr:
{safe_stderr}
- stdout:
{out}

Current target file path:
{target_path or ''}

Current target file content start:
{safe_current_text[:7000]}
Current target file content end

Repair checklist before output:
1. The proposed change is directly explained by the runtime evidence.
2. The file path is under mcp_output/.
3. mcp_service.py still imports FastMCP, registers only contract-backed tools, and exposes create_app().
4. Tool parameters stay explicit and typed; no *args/**kwargs.
5. Path-like parameters stay guarded by directory containment checks.
6. No source files, credentials, user data, or unrelated behavior are changed.
7. The full replacement file is internally consistent: no duplicate app/create_app/tool definitions, no stale broken imports, and no registered tool is knowingly left as unavailable.

{hint}

Return either the complete safe replacement using the exact file-path protocol, or the cannot-fix-safely protocol."""


def _response_declines_fix(text: str) -> bool:
    first = (text or "").strip().splitlines()[0:1]
    return bool(first and first[0].strip().lower() == "cannot fix safely")


def _changed_line_ratio(before: str, after: str) -> float:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    if not before_lines and not after_lines:
        return 0.0
    changed = 0
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changed += max(i2 - i1, j2 - j1)
    return changed / max(len(before_lines), len(after_lines), 1)


def _repair_change_is_scoped(before: str, after: str, error_message: str, stderr: str) -> tuple[bool, str]:
    if not before:
        return True, ""
    ratio = _changed_line_ratio(before, after)
    text = f"{error_message}\n{stderr}".lower()
    broad_rewrite_allowed = any(
        marker in text
        for marker in (
            "syntaxerror",
            "indentationerror",
            "no module named",
            "cannot import name",
            "has no attribute",
        )
    )
    limit = 0.85 if broad_rewrite_allowed else 0.35
    if ratio > limit and len(before.splitlines()) > 20:
        return False, f"repair changed too much of the generated file ({ratio:.0%})"
    return True, ""


def _is_mcp_service_file(full_path: str) -> bool:
    normalized = full_path.replace("\\", "/")
    return normalized.endswith("/mcp_output/mcp_plugin/mcp_service.py") or normalized.endswith("/mcp_service.py")


def _validate_repaired_file_whole(
    full_path: str,
    source: str,
    analysis_result: Dict[str, Any] | None = None,
) -> list[str]:
    """Validate the complete repaired file before accepting it."""
    errors: list[str] = []
    if not source or not source.strip():
        return ["repaired file is empty"]

    tree = None
    if full_path.endswith(".py"):
        try:
            import ast
            tree = ast.parse(source)
        except Exception as exc:
            return [f"repaired Python file does not parse: {exc}"]

    if not _is_mcp_service_file(full_path):
        return errors

    if tree is None:
        return ["mcp_service.py must be valid Python"]

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "create_app" not in function_names:
        errors.append("mcp_service.py must define create_app()")
    if "FastMCP" not in source:
        errors.append("mcp_service.py must use FastMCP")
    if "@mcp.tool" not in source:
        errors.append("mcp_service.py must register at least one FastMCP tool")

    if analysis_result:
        try:
            from .generate_node import _validate_mcp_service_source
            errors.extend(_validate_mcp_service_source(source, analysis_result))
        except Exception as exc:
            errors.append(f"mcp_service.py quality gate unavailable: {exc}")
    else:
        try:
            from .generate_node import _tool_exception_success_errors
            errors.extend(_tool_exception_success_errors(tree))
        except Exception as exc:
            errors.append(f"mcp_service.py exception masking gate unavailable: {exc}")

    return errors


def _fix_error_with_llm(
    error_message: str,
    stderr: str,
    repo_root: str,
    llm_service,
    run_result: Dict[str, Any] | None = None,
    analysis_result: Dict[str, Any] | None = None,
) -> bool:
    try:
        system_prompt = _repair_system_prompt()

        target_path = _infer_error_file_path(error_message, stderr, repo_root)
        if not target_path and os.path.exists(os.path.join(repo_root, "mcp_output", "mcp_plugin", "mcp_service.py")):
            target_path = "mcp_output/mcp_plugin/mcp_service.py"
        current_text = ""
        if target_path:
            full_path = _safe_generated_file_path(repo_root, target_path)
            if full_path and os.path.exists(full_path):
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

        user_prompt = _repair_user_prompt(
            repo_root=repo_root,
            target_path=target_path,
            current_text=current_text,
            error_message=error_message,
            stderr=stderr,
            run_result=run_result,
            analysis_result=analysis_result,
            hint=hint,
        )

        response = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not response:
            logger.warning("LLM did not return a response")
            return False
        if _response_declines_fix(response):
            logger.warning("LLM refused unsafe direct repair")
            return False
        
        file_path = _extract_file_path(response) or target_path
        if not file_path:
            logger.warning("Could not determine file path")
            return False
        full_path = _safe_generated_file_path(repo_root, file_path)
        if not full_path:
            logger.warning(f"Rejected unsafe or non-generated repair target: {file_path}")
            return False
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
                    if _response_declines_fix(retry_response):
                        logger.warning("LLM refused unsafe direct repair after syntax retry")
                        return False
                    retry_file_path = _extract_file_path(retry_response) or file_path
                    if not retry_file_path:
                        return False
                    retry_full_path = _safe_generated_file_path(repo_root, retry_file_path)
                    if not retry_full_path:
                        return False
                    retry_new_text = _extract_code_or_plain(retry_response)
                    if retry_new_text:
                        try:
                            retry_new_text = _sanitize_python_source(retry_new_text)
                            ast.parse(retry_new_text)
                            new_text = retry_new_text
                            full_path = retry_full_path
                        except Exception as e2:
                            return False
                    else:
                        return False
                else:
                    return False
        if current and new_text.strip() == current.strip():
            logger.warning("Rejected no-op repair; generated file was unchanged")
            return False
        scoped, scoped_reason = _repair_change_is_scoped(current, new_text, error_message, stderr)
        if not scoped:
            logger.warning(f"Rejected broad repair: {scoped_reason}")
            return False
        whole_file_errors = _validate_repaired_file_whole(full_path, new_text, analysis_result)
        if whole_file_errors:
            logger.warning(f"Rejected repaired file that failed whole-file validation: {whole_file_errors}")
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
    m = re.search(r"file path:\s*([^\n`\"\']+)\s*", text, re.IGNORECASE)
    if m:
        p = m.group(1).strip().strip(' \t`"\'')
        return p
    m2 = re.search(r"^\+\+\+\s+([ab]/)?([^\n]+)$", text, re.MULTILINE)
    if m2:
        return m2.group(2).strip()
    return None

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
    if lines[0].strip().lower().startswith("file path:"):
        return "\n".join(lines[1:])
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
        plugin_result = (state.get("tests") or {}).get("plugin", {})
        if isinstance(plugin_result, dict) and plugin_result.get("passed") is True:
            run_result = {
                "success": True,
                "test_passed": True,
                "attempt": plugin_result.get("attempt"),
                "source": "plugin_test_result",
                "client_validation": _plugin_client_validation_from_state(state),
            }
            state["run_result"] = run_result
        else:
            message = "ReviewNode has no runtime validation evidence; refusing to mark workflow as successful"
            state.setdefault("errors", []).append({
                "node": "ReviewNode",
                "type": "MissingRunEvidence",
                "severity": "critical",
                "message": message,
                "action_taken": "fail",
            })
            state["error"] = message
            state["review_decision"] = "fail"
            state["status"] = "failed"
            state["workflow_status"] = "failed"
            append_loop_event(state, "review_failed", reason=message)
            return state
    
    if not run_result.get("success", False):
        logger.info("Detected runtime error, starting deep error analysis...")
        error_analysis = _intelligent_error_analysis(state)
        
        state["error_analysis"] = error_analysis
        append_loop_event(
            state,
            "review_analyzed_failure",
            run_attempt=run_result.get("attempt"),
            next_action=error_analysis.get("next_action"),
            confidence=error_analysis.get("confidence"),
            summary=error_analysis.get("summary"),
        )
        
        error_analysis_path = os.path.join(mcp_output_dir, "error_analysis.json")
        try:
            write_file(error_analysis_path, json.dumps(error_analysis, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save error analysis report: {e}")

        next_action = error_analysis.get("next_action", "fix_directly")

        if next_action == "fail":
            logger.warning("Review determined the failure cannot be safely fixed automatically")
            state["loop_summary"] = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "not_safe_to_fix",
                "deps_change": False,
                "risks": ["automatic repair would require unsafe or unsupported changes"],
                "next_focus": "manual_review"
            }
            state["review_decision"] = "fail"
            state["status"] = "failed"
            state["workflow_status"] = "failed"
            state["error"] = error_analysis.get("summary", "Runtime validation failed and cannot be repaired automatically")
            append_loop_event(state, "review_marked_failed", run_attempt=run_result.get("attempt"), summary=state["error"])
            return state

        if next_action == "regenerate":
            logger.info("Review requested MCP service regeneration")
            state["loop_summary"] = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "regenerate_requested",
                "deps_change": False,
                "risks": ["generated service must be rebuilt"],
                "next_focus": "regenerate"
            }
            append_loop_event(state, "review_requested_regenerate", run_attempt=run_result.get("attempt"))
            _prepare_regeneration(state, "regenerate", run_result)
            return state

        if int(state.get("fix_retry_count", 0)) >= MAX_FIX_RETRIES:
            logger.warning("Direct fix budget exhausted before another repair attempt; requesting regeneration")
            error_analysis["next_action"] = "regenerate"
            state["error_analysis"] = error_analysis
            state["loop_summary"] = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "direct_fix_budget_exhausted",
                "deps_change": False,
                "risks": ["generated service must be rebuilt"],
                "next_focus": "regenerate"
            }
            append_loop_event(
                state,
                "fix_budget_exhausted",
                run_attempt=run_result.get("attempt"),
                fix_attempts=state.get("fix_retry_count", 0),
            )
            _prepare_regeneration(state, "fix_budget_exhausted", run_result)
            return state

        logger.info("Attempting to automatically fix...")
        fix_success = _apply_incremental_fixes(state, error_analysis)
        if fix_success:
            logger.info("Automatic fix successful!")
            state["fix_applied"] = True
            state["review_decision"] = "run"
            archive_failed_run_once(state, reason="fixed")
            clear_runtime_validation(state)
            summary = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "applied",
                "deps_change": False,
                "risks": [],
                "next_focus": "re-run tests",
                "fix_attempts": state.get("fix_retry_count", 0),
            }
            state["loop_summary"] = summary
            state["status"] = "running"
            return state
        else:
            logger.warning("Automatic fix failed, please check the logs above")
            if state.get("non_retryable_review_error"):
                error_analysis["next_action"] = "regenerate"
                error_analysis["summary"] = f"Direct LLM repair unavailable: {state['non_retryable_review_error']}"
                state["error_analysis"] = error_analysis
                state["loop_summary"] = {
                    "task": "runtime_fix",
                    "errors": error_analysis,
                    "root_cause": error_analysis.get("summary", ""),
                    "fixes": "not_available",
                    "deps_change": False,
                    "risks": ["manual LLM/provider configuration is required"],
                    "next_focus": "regenerate"
                }
                append_loop_event(
                    state,
                    "direct_fix_unavailable_regenerate",
                    run_attempt=run_result.get("attempt"),
                    reason=state["non_retryable_review_error"][:500],
                )
                _prepare_regeneration(state, "direct_fix_unavailable", run_result)
                return state

        current_fix_retries = state.get("fix_retry_count", 0)
        if current_fix_retries >= MAX_DIRECT_FIX_ATTEMPTS_PER_RUN:
            logger.warning("Direct fix attempt limit reached for this runtime failure; requesting regeneration")
            error_analysis["next_action"] = "regenerate"
            state["error_analysis"] = error_analysis
            state["loop_summary"] = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "direct_fix_attempt_limit_reached",
                "deps_change": False,
                "risks": ["repeating the same direct repair evidence is unlikely to help"],
                "next_focus": "regenerate",
                "fix_attempts": current_fix_retries,
                "max_direct_fix_attempts_per_run": MAX_DIRECT_FIX_ATTEMPTS_PER_RUN,
            }
            append_loop_event(
                state,
                "direct_fix_attempt_limit_reached",
                run_attempt=run_result.get("attempt"),
                fix_attempts=current_fix_retries,
            )
            _prepare_regeneration(state, "direct_fix_attempt_limit", run_result)
            return state

        if current_fix_retries >= MAX_FIX_RETRIES:
            logger.warning("Reached maximum direct fix attempts; requesting regeneration")
            error_analysis["next_action"] = "regenerate"
            state["error_analysis"] = error_analysis
            state["loop_summary"] = {
                "task": "runtime_fix",
                "errors": error_analysis,
                "root_cause": error_analysis.get("summary", ""),
                "fixes": "failed_budget_exhausted",
                "deps_change": False,
                "risks": ["direct repair budget exhausted"],
                "next_focus": "regenerate"
            }
            append_loop_event(
                state,
                "fix_budget_exhausted",
                run_attempt=run_result.get("attempt"),
                fix_attempts=current_fix_retries,
            )
            _prepare_regeneration(state, "fix_budget_exhausted", run_result)
            return state

        logger.info(f"Direct fix failed, preparing retry {current_fix_retries}")
        state["review_decision"] = "review"
        state["loop_summary"] = {
            "task": "runtime_fix",
            "errors": error_analysis,
            "root_cause": error_analysis.get("summary", ""),
            "fixes": "failed",
            "deps_change": False,
            "risks": ["further regeneration may be needed"],
            "next_focus": "retry direct repair",
            "fix_attempts": current_fix_retries,
            "max_fix_attempts": MAX_FIX_RETRIES,
        }
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
        evidence_errors = _runtime_success_evidence_errors(state, run_result)
        if evidence_errors:
            state["review_decision"] = "run"
            state["runtime_validation_evidence_errors"] = evidence_errors
            state["loop_summary"] = {
                "task": "runtime_revalidation",
                "errors": {"runtime_validation_evidence_errors": evidence_errors},
                "root_cause": "Runtime success state is missing required client validation evidence",
                "fixes": "none",
                "deps_change": False,
                "risks": ["finalize is blocked until run_node records real client validation evidence"],
                "next_focus": "re-run validation",
            }
            append_loop_event(
                state,
                "review_requested_runtime_revalidation",
                run_attempt=run_result.get("attempt"),
                errors=evidence_errors,
            )
            state["status"] = "running"
            state["workflow_status"] = state.get("workflow_status", "running")
            return state

        state["fix_retry_count"] = 0
        state["generation_retry_count"] = state.get("generation_retry_count", 0)
        state["review_decision"] = "finalize"
        state["loop_summary"] = {
            "task": "runtime_ok",
            "errors": {},
            "root_cause": "",
            "fixes": "none",
            "deps_change": False,
            "risks": [],
            "next_focus": "finalize"
        }
        append_loop_event(
            state,
            "review_confirmed_runtime_ok",
            run_attempt=run_result.get("attempt"),
            tool_count=((state.get("tests") or {}).get("plugin") or {}).get("tool_count"),
        )

    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state
