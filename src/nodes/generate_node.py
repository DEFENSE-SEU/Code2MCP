# Code Generation Node - Use LLM to generate service code, adapters, and related files
from __future__ import annotations
import os
import json
import time
import keyword
import re
import ast
import sys
import subprocess
import tempfile
from typing import Dict, Any
from ..utils import setup_logging, ensure_directory, write_file, get_llm_service, is_non_retryable_llm_error
from ..loop_control import append_loop_event, clear_runtime_validation
from ..security.tool_policy import (
    OUTPUT_ONLY_TOOL_TOKENS,
    REMOTE_LOOKUP_TOOL_TOKENS,
    classify_wrapper_parameter_name,
    looks_resource_parameter,
    looks_sensitive_parameter,
)

logger = setup_logging()

def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _adapter_llm_enabled() -> bool:
    return _truthy_env("CODE2MCP_ADAPTER_LLM", "false")


def _readme_llm_enabled() -> bool:
    return _truthy_env("CODE2MCP_README_LLM", "false")


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
    if last:
        logger.warning(f"LLM generation failed after retries: {last}")
    return ""
def _generate_mcp_py() -> str:
    content = """
\"\"\"
MCP Service Startup Entry
\"\"\"
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
mcp_plugin_dir = os.path.join(project_root, "mcp_plugin")
if mcp_plugin_dir not in sys.path:
    sys.path.insert(0, mcp_plugin_dir)

from mcp_service import create_app

def main():
    \"\"\"Start FastMCP service\"\"\"
    app = create_app()
    # Use environment variable to configure port, default 8000
    port = int(os.environ.get("MCP_PORT", "8000"))

    # Choose transport mode based on environment variable
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        app.run(transport="http", host="0.0.0.0", port=port)
    else:
        # Default to STDIO mode
        app.run()

if __name__ == "__main__":
    main()
"""
    return content

def _analyze_retry_reason(errors: list, run_results: list) -> str:
    """Analyze retry reason"""
    reasons = []

    for error in errors:
        message = str(error.get("message", ""))
        if "No module named" in message:
            reasons.append("Module import failed")
        elif "ImportError" in message:
            reasons.append("Import error")
        elif "SyntaxError" in message:
            reasons.append("Syntax error")
        elif error.get("severity") == "high":
            reasons.append(f"High severity error: {error.get('type', 'Unknown')}")

    for result in run_results:
        if not result.get("success", False):
            error_type = result.get("error_type", "Unknown")
            reasons.append(f"Execution failed: {error_type}")

    return "; ".join(reasons) if reasons else "Unknown error"

def _detect_project_type(analysis_result: Dict[str, Any]) -> str:
    """Detect project type"""
    ci = analysis_result.get("cpp_info", {})
    if ci and ci.get("has_cpp_files"):
        return "C/C++"
    try:
        llm_analysis = analysis_result.get("llm_analysis", {})
        core_modules = llm_analysis.get("core_modules", [])
        deps = analysis_result.get("dependencies", {}) if isinstance(analysis_result.get("dependencies", {}), dict) else {}
        structure = analysis_result.get("structure", {}) if isinstance(analysis_result.get("structure", {}), dict) else {}
        if deps.get("pyproject") or deps.get("setup_py") or deps.get("setup_cfg") or structure.get("packages"):
            return "Python"

        cpp_files = []
        python_files = []
        summary = analysis_result.get("summary", {}) if isinstance(analysis_result.get("summary", {}), dict) else {}
        file_tree = summary.get("file_tree", {}) if isinstance(summary.get("file_tree", {}), dict) else {}
        source_paths = [str(path).replace("\\", "/").strip("/") for path in file_tree.keys()]

        for module in core_modules:
            package = module.get("package", "")
            file_path = module.get("file_path", "")
            package_lower = package.lower()
            file_path_lower = file_path.lower()
            if file_path_lower.endswith((".cpp", ".hpp", ".cc", ".cxx", ".c", ".h")) or package_lower.endswith((".cpp", ".hpp", ".cc", ".cxx", ".c", ".h")):
                cpp_files.append(file_path or package)
            elif package or file_path:
                if file_path.endswith(".py") or any(ext in package for ext in ['.py']):
                    python_files.append(file_path or package)

        lower_paths = [path.lower() for path in source_paths]
        basenames = {os.path.basename(path) for path in lower_paths}
        if any(path.endswith(".py") for path in lower_paths):
            python_files.extend(path for path in lower_paths if path.endswith(".py"))
        if any(path.endswith((".cpp", ".hpp", ".cc", ".cxx", ".c", ".h")) for path in lower_paths):
            cpp_files.extend(path for path in lower_paths if path.endswith((".cpp", ".hpp", ".cc", ".cxx", ".c", ".h")))
        if "package.swift" in basenames or any(path.endswith(".swift") for path in lower_paths):
            return "Swift"
        if "cargo.toml" in basenames or any(path.endswith(".rs") for path in lower_paths):
            return "Rust"
        if "pom.xml" in basenames or "build.gradle" in basenames or "build.gradle.kts" in basenames or any(path.endswith(".java") for path in lower_paths):
            return "Java"
        if "package.json" in basenames or any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in lower_paths):
            return "JavaScript/TypeScript"
        if any(path.endswith((".r", ".rmd")) for path in lower_paths):
            return "R"

        repo_name = analysis_result.get("repository_name", "")
        source_dir = f"workspace/{repo_name}/source" if repo_name else ""

        if not python_files and source_dir and os.path.exists(source_dir):
            build_files = [
                "CMakeLists.txt", "Makefile", "configure", "build.sh",
                "Cargo.toml"
            ]

            for build_file in build_files:
                if os.path.exists(os.path.join(source_dir, build_file)):
                    if build_file in ["CMakeLists.txt", "Makefile", "configure", "build.sh"]:
                        cpp_files.append(f"Build file: {build_file}")
                    elif build_file == "Cargo.toml":
                        cpp_files.append(f"Build file: {build_file}")
        if cpp_files:
            return "C/C++"
        elif python_files:
            return "Python"
        else:
            return "Unknown"

    except Exception as e:
        logger.warning(f"Project type detection failed: {e}")
        return "Unknown"


def _has_verified_generation_targets(analysis_result: Dict[str, Any]) -> bool:
    if _detect_project_type(analysis_result) == "C/C++":
        return True
    modules = (analysis_result.get("llm_analysis") or {}).get("core_modules", []) or []
    for module in modules:
        candidate_functions = _module_wrapper_candidate_names(module, "function")
        candidate_classes = _module_wrapper_candidate_names(module, "class")
        if candidate_functions is not None or candidate_classes is not None:
            if candidate_functions or candidate_classes:
                return True
            continue
        functions = [name for name in module.get("functions", []) or [] if str(name).strip()]
        classes = [name for name in module.get("classes", []) or [] if str(name).strip()]
        if functions or classes:
            return True
    return False


def _generation_target_counts(analysis_result: Dict[str, Any]) -> dict[str, int]:
    modules = (analysis_result.get("llm_analysis") or {}).get("core_modules", []) or []
    return {
        "core_module_count": len(modules),
        "function_count": sum(len(module.get("functions", []) or []) for module in modules if isinstance(module, dict)),
        "class_count": sum(len(module.get("classes", []) or []) for module in modules if isinstance(module, dict)),
    }


def _module_identity(module: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(module.get("package", "") or ""),
        str(module.get("module", "") or ""),
        _normalized_relative_file_path(str(module.get("file_path", "") or "")),
    )


def _kept_generation_symbols(filtered_analysis: Dict[str, Any]) -> dict[tuple[str, str, str], dict[str, set[str]]]:
    kept: dict[tuple[str, str, str], dict[str, set[str]]] = {}
    modules = (filtered_analysis.get("llm_analysis") or {}).get("core_modules", []) or []
    for module in modules:
        if not isinstance(module, dict):
            continue
        kept[_module_identity(module)] = {
            "function": {str(name).rstrip("*") for name in module.get("functions", []) or [] if str(name).rstrip("*")},
            "class": {str(name).rstrip("*") for name in module.get("classes", []) or [] if str(name).rstrip("*")},
        }
    return kept


def _source_function_nodes_for_module(module: dict[str, Any], repo_root: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    file_path = _normalized_relative_file_path(str(module.get("file_path", "") or ""))
    if not repo_root or not file_path:
        return {}
    source_dir = os.path.join(repo_root, "source")
    target = os.path.join(source_dir, file_path)
    if not os.path.isfile(target):
        return {}
    try:
        with open(target, "r", encoding="utf-8-sig", errors="ignore") as handle:
            tree = ast.parse(handle.read() or "", filename=target)
    except Exception:
        return {}
    return {
        node.name: node
        for node in getattr(tree, "body", []) or []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _target_rejection_reasons(
    module: dict[str, Any],
    name: str,
    kind: str,
    function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[str]:
    reasons: list[str] = []
    lowered_name = str(name or "").lower()
    name_tokens = _name_tokens(name)
    imports = {str(item).split(".")[0].lower() for item in module.get("imports", []) or []}
    if module.get("import_side_effect_risk"):
        side_effects = [str(item) for item in module.get("import_side_effect_reasons", []) or [] if str(item)]
        suffix = f": {', '.join(side_effects[:3])}" if side_effects else ""
        reasons.append(f"module has import-time side effects{suffix}")
    if "pynput" in imports:
        reasons.append("imports keyboard listener dependency: pynput")
    if imports.intersection({"matplotlib", "plotly"}):
        reasons.append("module depends on interactive plotting")

    if kind == "function":
        if lowered_name.startswith("on_"):
            reasons.append("event handler/callback function name")
        unsafe_name_tokens = {
            "axes",
            "dummy",
            "executor",
            "keylog",
            "keylogger",
            "keyboard",
            "listener",
            "log",
            "pickle",
            "plot",
            "plots",
            "plotly",
            "proc",
            "processor",
            "simulator",
            "transform",
            "unpickle",
        }
        unsafe_tokens = sorted(name_tokens.intersection(unsafe_name_tokens))
        if unsafe_tokens:
            reasons.append("unsafe tool name token: " + ", ".join(unsafe_tokens))
        side_effect_tokens = sorted(part for part in SIDE_EFFECT_NAME_PARTS if part in lowered_name)
        if side_effect_tokens:
            reasons.append("name suggests side-effect operation: " + ", ".join(side_effect_tokens[:3]))

        details = module.get("function_details", {}) if isinstance(module.get("function_details", {}), dict) else {}
        detail = details.get(name, {}) if isinstance(details, dict) else {}
        analysis_risk_messages = {
            "background_execution": "starts background execution",
            "dynamic_code_execution": "can execute dynamic code",
            "environment_mutation": "mutates process environment",
            "environment_probe_name": "environment probe helper",
            "file_mutation": "mutates files or directories",
            "file_read": "reads files or directories",
            "framework_entrypoint_decorator": "framework entrypoint decorator",
            "global_state_dependency": "depends on imported global state",
            "interactive_input": "requires interactive stdin input",
            "network_operation": "performs network requests",
            "operational_tool_name": "operational helper name",
            "process_execution": "can execute external processes",
            "process_state_mutation": "mutates process state",
            "unsupported_placeholder": "unsupported placeholder function",
        }
        for risk in detail.get("risk_reasons", []) or []:
            message = analysis_risk_messages.get(str(risk))
            if message:
                reasons.append(message)
        params = _detail_param_names(
            (module.get("function_signatures", {}) or {}).get(name) if isinstance(module.get("function_signatures", {}), dict) else None,
            detail if isinstance(detail, dict) else {},
        ) or []
        lookup = _param_detail_lookup(detail if isinstance(detail, dict) else {})
        for param in params:
            if _is_path_like_param(param):
                reasons.append(f"path-like parameter requires guard: {param}")
            decision = classify_wrapper_parameter_name(
                param,
                complex_param_names=COMPLEX_WRAPPER_PARAM_NAMES,
                complex_param_parts=COMPLEX_WRAPPER_PARAM_PARTS,
            )
            if decision.unsafe:
                reasons.append(f"unsafe parameter {param}: {decision.reason}")
            param_detail = lookup.get(param, {})
            if _param_is_complex(param, param_detail):
                reasons.append(f"complex parameter not exposed: {param}")
        lowered_params = {str(param).lower() for param in params}
        if name_tokens.intersection({"extra", "extras"}) and lowered_params.intersection({"groups", "exclude_extras"}):
            reasons.append("package extras metadata helper is not a user-facing tool")
        if not params and lowered_name.startswith("init_") and "session" in name_tokens:
            reasons.append("interactive session initializer is not a user-facing tool")
        if not params and "ordering" in name_tokens and name_tokens.intersection({"halt", "restart"}):
            reasons.append("dispatch ordering control helper is not a user-facing tool")
        if not params and lowered_name.endswith("_zero"):
            reasons.append("zero-value constructor returns an empty sentinel")

        node = function_nodes.get(name)
        if node is not None:
            if _function_body_returns_empty_default_factory(node):
                reasons.append("returns empty default-factory container")
            if _function_body_returns_empty_literal_container(node):
                reasons.append("returns empty literal container")
            reasons.extend(_function_body_unsafe_runtime_side_effect_reasons(node))

    elif kind == "class":
        if name_tokens.intersection({"auth", "credential", "credentials", "login", "password", "secret", "token"}):
            reasons.append("class name suggests credentials or authentication")
        if not _truthy_env("CODE2MCP_ENABLE_CLASS_WRAPPERS", "false"):
            reasons.append("class wrappers are disabled by default")

    unique = []
    for reason in reasons:
        if reason and reason not in unique:
            unique.append(reason)
    if unique:
        return unique[:8]
    if kind == "function":
        return ["not selected by callable wrapper policy"]
    return ["rejected by generation safety filters"]


def _rejected_generation_targets(
    original_analysis: Dict[str, Any],
    filtered_analysis: Dict[str, Any],
    repo_root: str = "",
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    kept = _kept_generation_symbols(filtered_analysis)
    rejected: list[dict[str, Any]] = []
    modules = (original_analysis.get("llm_analysis") or {}).get("core_modules", []) or []
    for module in modules:
        if not isinstance(module, dict):
            continue
        identity = _module_identity(module)
        kept_module = kept.get(identity, {"function": set(), "class": set()})
        function_nodes = _source_function_nodes_for_module(module, repo_root)
        module_label = ".".join(part for part in [str(module.get("package", "") or ""), str(module.get("module", "") or "")] if part)
        for kind, field in (("function", "functions"), ("class", "classes")):
            for raw_name in module.get(field, []) or []:
                name = str(raw_name).rstrip("*")
                if not name or name in kept_module.get(kind, set()):
                    continue
                rejected.append(
                    {
                        "kind": kind,
                        "module": module_label,
                        "name": name,
                        "file_path": _normalized_relative_file_path(str(module.get("file_path", "") or "")),
                        "reasons": _target_rejection_reasons(module, name, kind, function_nodes),
                    }
                )
                if len(rejected) >= limit:
                    return rejected
    return rejected


def _unsupported_generation_details(
    original_analysis: Dict[str, Any],
    filtered_analysis: Dict[str, Any],
    *,
    stage: str,
    repo_root: str = "",
) -> dict[str, Any]:
    original_counts = _generation_target_counts(original_analysis)
    filtered_counts = _generation_target_counts(filtered_analysis)
    project_type = _detect_project_type(filtered_analysis)
    original_symbols = original_counts["function_count"] + original_counts["class_count"]
    filtered_symbols = filtered_counts["function_count"] + filtered_counts["class_count"]
    if original_symbols and not filtered_symbols:
        likely_reason = "candidate_targets_rejected_by_generation_safety_filters"
    elif project_type == "Unknown":
        likely_reason = "no_supported_python_api_targets"
    elif project_type not in {"Python", "C/C++"}:
        likely_reason = "unsupported_project_type"
    else:
        likely_reason = "no_public_api_targets"
    details = {
        "core_module_count": filtered_counts["core_module_count"],
        "project_type": project_type,
        "stage": stage,
        "likely_reason": likely_reason,
        "original_core_module_count": original_counts["core_module_count"],
        "original_function_count": original_counts["function_count"],
        "original_class_count": original_counts["class_count"],
        "filtered_core_module_count": filtered_counts["core_module_count"],
        "filtered_function_count": filtered_counts["function_count"],
        "filtered_class_count": filtered_counts["class_count"],
    }
    rejected_targets = _rejected_generation_targets(original_analysis, filtered_analysis, repo_root)
    if rejected_targets:
        details["rejected_target_count"] = len(rejected_targets)
        details["rejected_targets"] = rejected_targets
    return details


def _write_generation_failure_summary(
    mcp_output_dir: str,
    state: Dict[str, Any],
    error_info: Dict[str, Any],
    *,
    validation_status: str = "unsupported_audited",
) -> str:
    repo = state.get("repository", {}) if isinstance(state.get("repository", {}), dict) else {}
    options = state.get("options", {}) if isinstance(state.get("options", {}), dict) else {}
    now = time.time()
    start_time = state.get("start_time", now) or now
    try:
        duration = max(0.0, now - float(start_time))
    except (TypeError, ValueError):
        duration = 0.0
    client_validation = {
        "passed": False,
        "skipped": True,
        "reason": "unsupported_repository_audited",
    }
    summary = {
        "status": "failed",
        "repository": {
            "name": repo.get("name", "unknown"),
            "url": repo.get("url", ""),
            "local_path": (repo.get("local_paths") or {}).get("repo_root", ""),
        },
        "execution": {
            "start_time": start_time,
            "end_time": now,
            "duration": duration,
            "status": "failed",
            "workflow_status": "failed",
            "validation_status": validation_status,
            "verified": False,
            "generate_only": bool(options.get("generate_only", False)),
            "nodes_executed": ["download", "analysis", "env", "generate"],
        },
        "workflow_status": "failed",
        "validation_status": validation_status,
        "verified": False,
        "success": False,
        "tests": {
            "mcp_plugin": {
                "passed": False,
                "details": {
                    "tool_count": 0,
                    "client_validation": client_validation,
                },
            }
        },
        "generation_error": error_info,
        "errors": [error_info],
        "warnings": [
            "Generation failed before runtime validation; stale generated services and connection configs must not be treated as validated."
        ],
    }
    summary_path = os.path.join(mcp_output_dir, "workflow_summary.json")
    write_file(summary_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary_path


def _safe_identifier(name: str, fallback: str) -> str:
    candidate = re.sub(r"\W+", "_", str(name or "").strip()).strip("_")
    if not candidate or candidate[0].isdigit() or keyword.iskeyword(candidate):
        candidate = fallback
    return candidate


def _clean_param_names(params: list | None, *, skip_implicit_receiver: bool = True) -> list[str] | None:
    if params is None:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in params:
        name = _safe_identifier(str(raw), "param")
        if skip_implicit_receiver and name in {"self", "cls"}:
            continue
        base = name
        idx = 2
        while name in seen:
            name = f"{base}_{idx}"
            idx += 1
        seen.add(name)
        cleaned.append(name)
    return cleaned


NUMERIC_PARAM_NAMES = {
    "alpha",
    "angle",
    "base",
    "bandwidth",
    "beta",
    "degree",
    "dec",
    "dim",
    "dmu_0",
    "dmu_1",
    "gamma",
    "half_nbw",
    "index",
    "indents",
    "rho",
    "n",
    "n_sample",
    "num",
    "ra",
    "radius",
    "rate",
    "ratio",
    "score",
    "number",
    "sfreq",
    "start_index",
    "theta",
    "threshold",
    "valence",
    "weight",
    "z0",
}
INTEGER_PARAM_NAMES = {
    "base",
    "count",
    "cur_index",
    "current_index",
    "d",
    "degree",
    "dimensions",
    "dim",
    "dpi",
    "end_idx",
    "fieldn",
    "fontsize",
    "idx",
    "i",
    "index",
    "indents",
    "kmax",
    "k_vars",
    "limit",
    "m",
    "n",
    "n_coeffs",
    "nbytes",
    "nm",
    "n_sample",
    "n_vars",
    "num",
    "nx",
    "ny",
    "position",
    "seed",
    "size",
    "start_idx",
    "start_index",
    "virtual_offset",
    "wsize",
}
INTEGER_CONTEXT_NAME_PARTS = {
    "bin",
    "count",
    "degree",
    "even",
    "index",
    "integer",
    "odd",
    "order",
    "prime",
    "rank",
    "size",
}
LIST_LIKE_PARAM_NAMES = {
    "benchmark_rets",
    "counts",
    "factor_returns",
    "grant_contributions",
    "grant_contribs_curr",
    "grants_data",
    "ii",
    "is_returns",
    "numbers",
    "observations",
    "returns",
    "samples",
    "sh",
    "strides",
    "underwater",
    "values",
    "xs",
}
DICT_LIKE_PARAM_NAMES = {
    "aggregated_contributions",
    "contrib_dict",
    "gene_id_mapping",
    "pair_totals",
}


def _annotation_to_tool_type(
    annotation: str,
    default: str = "",
    param_name: str = "",
    context_name: str = "",
) -> str:
    annotation = (annotation or "").replace("typing.", "").strip()
    lowered = annotation.lower()
    default_text = (default or "").strip()
    param_lower = str(param_name or "").lower()
    param_tokens = _name_tokens(param_name)
    context_tokens = _name_tokens(context_name)

    if not annotation:
        if param_lower in {"default", "seasonal", "stepwise", "trace", "with_intercept"}:
            return "bool"
        if param_lower == "order" and {"seasonal", "order"}.issubset(context_tokens):
            return "list"
        if param_lower.startswith(("is_", "has_", "use_", "allow_", "enable_", "disable_")) or (
            param_tokens.intersection({"allow", "disable", "enable", "has", "is", "use"})
            and re.match(r"^(allow|disable|enable|has|is|use)[A-Z_]", str(param_name or ""))
        ):
            return "bool"
        if param_lower in LIST_LIKE_PARAM_NAMES or param_lower.endswith("_list") or param_tokens.intersection({"list", "lists"}):
            return "list"
        if (
            param_lower in DICT_LIKE_PARAM_NAMES
            or param_lower.endswith(("_dict", "_mapping"))
            or param_tokens.intersection({"dict", "dictionary", "mapping", "mappings"})
        ):
            return "dict"
        if default_text in {"True", "False"}:
            return "bool"
        if re.fullmatch(r"-?\d+", default_text):
            return "int"
        if re.fullmatch(r"-?\d+\.\d+", default_text):
            return "float"
        if param_lower in INTEGER_PARAM_NAMES or param_lower.startswith("n_") or param_tokens.intersection(INTEGER_CONTEXT_NAME_PARTS):
            return "int"
        if "clamp" in context_tokens and param_lower in {"max", "max_value", "min", "min_value", "value"}:
            return "float"
        if context_tokens.intersection({"color", "hsl", "hsla", "hsv", "hsva", "rgb", "rgba"}) and param_lower in {
            "alpha",
            "b",
            "g",
            "h",
            "l",
            "r",
            "s",
            "v",
        }:
            return "float"
        if "percentile" in context_tokens and param_lower == "p":
            return "float"
        if "quantile" in context_tokens and param_lower == "q":
            return "float"
        if param_lower in {"d"} and context_tokens.intersection(INTEGER_CONTEXT_NAME_PARTS):
            return "int"
        if param_lower in NUMERIC_PARAM_NAMES or any(part in param_lower for part in ("score", "ratio", "rate", "threshold")):
            return "float"
        return "str"

    if lowered in {"str", "builtins.str"}:
        return "str"
    if lowered in {"bool", "builtins.bool"}:
        return "bool"
    if lowered in {"int", "builtins.int"}:
        return "int"
    if lowered in {"float", "builtins.float"}:
        return "float"
    if "supportsindex" in lowered or "integer" in lowered:
        return "int"
    if "float" in lowered and "str" in lowered:
        return "float | str"
    if "int" in lowered and "str" in lowered:
        return "int | str"
    if "bool" in lowered:
        return "bool"
    if "list" in lowered or "sequence" in lowered or "iterable" in lowered:
        return "list"
    if "dict" in lowered or "mapping" in lowered:
        return "dict"
    if "tuple" in lowered or "set" in lowered:
        return "list"
    if "float" in lowered:
        return "float"
    if "int" in lowered:
        return "int"
    if "str" in lowered:
        return "str"
    return "str"


POSITIVE_INTEGER_DEFAULTS = {"k_vars": "3", "kmax": "3", "nm": "3"}
POSITIVE_FLOAT_DEFAULTS = {"half_nbw": "2.5"}


def _default_expression_is_literal(default: str) -> bool:
    text = str(default or "").strip()
    if text in {"True", "False"}:
        return True
    try:
        ast.literal_eval(text)
    except Exception:
        return False
    return True


def _literal_default_value(default: str) -> tuple[bool, Any]:
    try:
        return True, ast.literal_eval(str(default or "").strip())
    except Exception:
        return False, None


def _default_for_tool_type(tool_type: str, default: str = "", required: bool = True, param_name: str = "") -> str:
    default = (default or "").strip()
    if default and default not in {"None", "Ellipsis"}:
        if tool_type == "str" and not (default.startswith(("'", '"')) and default.endswith(("'", '"'))):
            return repr(default)
        literal_ok, literal_value = _literal_default_value(default)
        if not literal_ok:
            default = ""
        elif tool_type == "bool" and not isinstance(literal_value, bool):
            default = ""
        elif tool_type == "int" and (not isinstance(literal_value, int) or isinstance(literal_value, bool)):
            default = ""
        elif tool_type == "float" and (not isinstance(literal_value, (int, float)) or isinstance(literal_value, bool)):
            default = ""
        elif tool_type == "str" and not isinstance(literal_value, str):
            default = ""
        elif tool_type == "list" and isinstance(literal_value, tuple):
            return repr(list(literal_value))
        else:
            return default
    if "|" in tool_type and "str" in tool_type:
        return '""'
    if tool_type == "bool":
        return "False"
    if tool_type == "int":
        positive_default = POSITIVE_INTEGER_DEFAULTS.get(str(param_name or "").lower())
        if positive_default:
            return positive_default
        return "0"
    if tool_type == "float":
        positive_default = POSITIVE_FLOAT_DEFAULTS.get(str(param_name or "").lower())
        if positive_default:
            return positive_default
        return "0.0"
    if tool_type in {"list", "dict"}:
        return "None"
    return '""'


def _tool_signature_and_call(
    params: list | None,
    param_details: list[dict[str, Any]] | None = None,
    function_name: str = "",
    function_detail: dict[str, Any] | None = None,
    module_imports: list[str] | None = None,
) -> tuple[str, str, list[str]]:
    if params is None:
        return "payload: dict = None", "payload", ["payload"]
    details_by_name = {
        str(detail.get("name", "")): detail
        for detail in (param_details or [])
        if isinstance(detail, dict)
    }
    param_pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in params or []:
        raw_name = str(raw)
        clean = _safe_identifier(raw_name, "param")
        if clean in {"self", "cls"}:
            continue
        detail = details_by_name.get(raw_name, {})
        if detail.get("kind") in {"vararg", "kwarg"}:
            continue
        base = clean
        idx = 2
        while clean in seen:
            clean = f"{base}_{idx}"
            idx += 1
        seen.add(clean)
        param_pairs.append((raw_name, clean))
    cleaned = [clean for _, clean in param_pairs]
    signature_parts = []
    call_parts = []
    for raw, clean in param_pairs:
        detail = details_by_name.get(str(raw), {})
        uses_numeric_sequence = _param_uses_numeric_sequence_adapter(
            str(raw),
            str((function_detail or {}).get("docstring", "") or ""),
            module_imports,
            detail,
        )
        uses_scalar_numeric = _param_uses_scalar_numeric_context(
            str(raw),
            str((function_detail or {}).get("docstring", "") or ""),
            detail,
        )
        uses_scientific_sequence = _param_is_scientific_array_input(
            str(raw),
            str((function_detail or {}).get("docstring", "") or ""),
            module_imports,
        ) and _param_has_numeric_sequence_type_evidence(
            str(raw),
            str((function_detail or {}).get("docstring", "") or ""),
            detail,
        )
        tool_type = _annotation_to_tool_type(
            str(detail.get("annotation", "")),
            str(detail.get("default", "")),
            str(raw),
            function_name,
        )
        if uses_numeric_sequence or uses_scientific_sequence:
            tool_type = "list"
        elif uses_scalar_numeric and not str(detail.get("annotation", "") or "").strip():
            tool_type = "float"
        default = _default_for_tool_type(tool_type, str(detail.get("default", "")), bool(detail.get("required", True)), str(raw))
        signature_parts.append(f"{clean}: {tool_type} = {default}")
        call_value = clean
        if uses_numeric_sequence:
            call_value = f"_coerce_numeric_sequence({clean}, {raw!r})"
        elif uses_scientific_sequence:
            call_value = f"_coerce_numeric_list({clean}, {raw!r})"
        if detail.get("kind") == "keyword_only":
            original_name = str(raw)
            keyword_name = original_name if original_name.isidentifier() and not keyword.iskeyword(original_name) else clean
            call_parts.append(f"{keyword_name}={call_value}")
        else:
            call_parts.append(call_value)
    signature = ", ".join(signature_parts)
    call_args = ", ".join(call_parts)
    return signature, call_args, cleaned


def _is_path_like_param(name: str) -> bool:
    lowered = name.lower()
    if not looks_resource_parameter(name):
        return False
    return (
        lowered in {"path", "file", "dir", "directory", "filepath", "file_path", "filename", "file_name", "fname"}
        or "fname" in lowered
        or lowered.startswith("dir_")
        or lowered.startswith("fname_")
        or lowered.endswith("_path")
        or lowered.endswith("_file")
        or lowered.endswith("_dir")
        or lowered.endswith("_directory")
        or lowered in {"input_file", "output_file", "data_file", "config_file"}
    )


def _function_call_line(func_name: str, call_args: str) -> str:
    positional_args: list[str] = []
    keyword_args: list[str] = []
    if call_args == "payload":
        positional_args = ["payload"]
    elif call_args:
        for raw_part in [part.strip() for part in call_args.split(",") if part.strip()]:
            if "=" in raw_part:
                key, value = raw_part.split("=", 1)
                keyword_args.append(f"{key.strip()!r}: {value.strip()}")
            else:
                positional_args.append(raw_part)
    positional_literal = "[" + ", ".join(positional_args) + "]"
    keyword_literal = "{" + ", ".join(keyword_args) + "}"
    return (
        f"        raw_result = _call_quietly({func_name}, {positional_literal}, {keyword_literal})\n"
        "        result = _to_jsonable_result(raw_result)\n"
    )


def _quiet_call_helper_source() -> str:
    return r'''
def _call_quietly(func, positional_args=None, keyword_args=None):
    positional_args = list(positional_args or [])
    keyword_args = dict(keyword_args or {})
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        return func(*positional_args, **keyword_args)
'''


def _runtime_value_helper_source() -> str:
    return r'''
def _coerce_numeric_list(value, name="value"):
    import math as _code2mcp_math

    if value is None:
        value = [0.01, -0.02, 0.015, 0.005, 0.012]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            value = []
        else:
            try:
                value = json.loads(text)
            except Exception:
                value = [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(value, dict):
        raise ValueError(f"{name} must be a one-dimensional numeric sequence, not an object")
    try:
        items = list(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be a one-dimensional numeric sequence") from exc
    if not items:
        raise ValueError(f"{name} must not be empty")
    if len(items) > 5000:
        raise ValueError(f"{name} is too large for a generated MCP tool call")
    numbers = []
    for item in items:
        if isinstance(item, bool) or isinstance(item, (list, tuple, dict, set)):
            raise ValueError(f"{name} must contain only numeric scalar values")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} contains a non-numeric value") from exc
        if not _code2mcp_math.isfinite(number):
            raise ValueError(f"{name} contains a non-finite numeric value")
        numbers.append(number)
    return numbers


def _coerce_numeric_sequence(value, name="value"):
    numbers = _coerce_numeric_list(value, name)
    try:
        import pandas as _code2mcp_pandas

        return _code2mcp_pandas.Series(
            numbers,
            index=_code2mcp_pandas.date_range("2024-01-01", periods=len(numbers), freq="D"),
        )
    except Exception:
        return numbers


def _to_jsonable_result(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        import math as _code2mcp_math

        return value if _code2mcp_math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _to_jsonable_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable_result(item) for item in value]
    if hasattr(value, "to_dict"):
        try:
            return _to_jsonable_result(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return _to_jsonable_result(value.tolist())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return _to_jsonable_result(value.item())
        except Exception:
            pass
    return str(value)
'''


def _normalize_import_path(package: str, module_name: str = "") -> str:
    package = (package or "").strip().strip(".")
    module_name = (module_name or "").strip().strip(".")
    if package.startswith("source."):
        package = package[7:]
    if package.startswith("src."):
        package = package[4:]
    if module_name.startswith("source."):
        module_name = module_name[7:]
    if module_name.startswith("src."):
        module_name = module_name[4:]

    if module_name and module_name != package and not package.endswith(f".{module_name}") and package != module_name:
        return f"{package}.{module_name}" if package else module_name
    return package or module_name


def _import_path_from_file_path(file_path: str) -> str:
    cleaned = _normalized_relative_file_path(file_path)
    if not cleaned.endswith(".py"):
        return ""
    cleaned = cleaned[:-3]
    if cleaned.startswith("src/"):
        cleaned = cleaned[4:]
    if cleaned.endswith("/__init__"):
        cleaned = cleaned[: -len("/__init__")]
    import_path = cleaned.replace("/", ".")
    return import_path if _is_valid_import_path(import_path) else ""


def _import_path_from_module_metadata(package: str, module_name: str, file_path: str = "") -> str:
    file_import_path = _import_path_from_file_path(file_path)
    if file_import_path:
        return file_import_path
    return _normalize_import_path(package, module_name)


def _is_valid_import_path(import_path: str) -> bool:
    parts = [part for part in (import_path or "").split(".") if part]
    return bool(parts) and all(part.isidentifier() and not keyword.iskeyword(part) for part in parts)


def _module_alias(import_path: str) -> str:
    return "_code2mcp_module_" + _safe_identifier(import_path.replace(".", "_"), "module")


def _normalized_relative_file_path(file_path: str) -> str:
    cleaned = str(file_path or "").replace("\\", "/").strip("/")
    if cleaned.startswith("source/"):
        cleaned = cleaned[len("source/"):]
    return cleaned


GENERATION_EXCLUDED_SOURCE_DIRS = {
    ".cache",
    ".eggs",
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "benchmark",
    "benchmarks",
    "bin",
    "build",
    "cli",
    "deployment",
    "dist",
    "doc",
    "docs",
    "env",
    "example",
    "examples",
    "histories",
    "history",
    "mcp_output",
    "node_modules",
    "sample",
    "samples",
    "script",
    "scripts",
    "site-packages",
    "test",
    "tests",
    "tutorial",
    "tutorials",
    ".venv",
    "venv",
}
GENERATION_EXCLUDED_SOURCE_FILES = {"conftest.py", "setup.py", "versioneer.py", "_version.py"}


def _module_is_test_support(module: dict[str, Any]) -> bool:
    file_path = _normalized_relative_file_path(module.get("file_path", ""))
    parts = [part.lower() for part in file_path.replace("\\", "/").split("/") if part]
    filename = parts[-1] if parts else ""
    if filename in GENERATION_EXCLUDED_SOURCE_FILES or filename.startswith("test_") or filename.endswith("_test.py"):
        return True
    if any(part in GENERATION_EXCLUDED_SOURCE_DIRS or part.startswith("test") for part in parts[:-1]):
        return True
    package = str(module.get("package", "") or "").lower()
    module_name = str(module.get("module", "") or "").lower()
    return module_name == "conftest" or package.endswith(".conftest")


def _prefer_installed_package_imports(analysis_result: Dict[str, Any]) -> bool:
    runtime = analysis_result.get("_runtime", {}) if isinstance(analysis_result, dict) else {}
    env = runtime.get("env", {}) if isinstance(runtime, dict) else {}
    dependency_installation = env.get("dependency_installation", {}) if isinstance(env, dict) else {}
    return bool(
        dependency_installation.get("passed")
        and dependency_installation.get("strategy") == "package"
        and dependency_installation.get("package")
    )


def _source_bootstrap_source(prefer_installed: bool) -> str:
    prefer_literal = "True" if prefer_installed else "False"
    return f'''source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
src_layout_path = os.path.join(source_path, "src")
_code2mcp_prefer_installed_packages = {prefer_literal}

def _code2mcp_add_source_paths():
    for _code2mcp_path in (source_path, src_layout_path):
        if os.path.isdir(_code2mcp_path) and _code2mcp_path not in sys.path:
            sys.path.insert(0, _code2mcp_path)

if not _code2mcp_prefer_installed_packages:
    _code2mcp_add_source_paths()
'''


def _module_loader_source() -> str:
    return '''
_code2mcp_import_errors = {}

def _code2mcp_require_symbols(module, module_label: str, symbols: tuple[str, ...]):
    missing = [name for name in symbols if getattr(module, name, None) is None]
    if missing:
        raise ImportError(f"{module_label} missing expected symbols: {', '.join(missing)}")
    return module

def _code2mcp_load_selected_symbols_from_file(alias: str, relative_file_path: str, symbols: tuple[str, ...]):
    """Load only selected source definitions when optional top-level imports are unavailable."""
    import ast
    import types
    from pathlib import Path

    base = Path(source_path).resolve()
    target = (base / relative_file_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ImportError(f"Module path escapes source directory: {relative_file_path}") from exc
    source = target.read_text(encoding="utf-8-sig", errors="ignore")
    tree = ast.parse(source, filename=str(target))
    selected_symbols = {str(symbol) for symbol in symbols if str(symbol).isidentifier()}
    if not selected_symbols:
        raise ImportError("No selected symbols were available for source-only loading")
    selected_body = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in selected_symbols
    ]
    if not selected_body:
        raise ImportError("Selected symbols were not found in source file")

    module = types.ModuleType(alias)
    module.__file__ = str(target)
    module.__package__ = ""
    module.__code2mcp_source_subset__ = True
    sys.modules[alias] = module
    _code2mcp_add_source_paths()
    target_dir = str(target.parent)
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)

    def _imported_names(node):
        names = set()
        if isinstance(node, ast.Import):
            for item in node.names:
                names.add(item.asname or item.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name == "*":
                    continue
                names.add(item.asname or item.name.split(".")[0])
        return names

    def _global_load_names(nodes):
        loads = set()
        local = set()
        for definition in nodes:
            if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = definition.args
                for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                    local.add(arg.arg)
                if args.vararg:
                    local.add(args.vararg.arg)
                if args.kwarg:
                    local.add(args.kwarg.arg)
            for child in ast.walk(definition):
                if isinstance(child, ast.Name):
                    if isinstance(child.ctx, ast.Load):
                        loads.add(child.id)
                    elif isinstance(child.ctx, (ast.Store, ast.Del)):
                        local.add(child.id)
        return loads - local

    failed_import_names = set()
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        try:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(target), "exec"), module.__dict__)
        except ImportError:
            failed_import_names.update(_imported_names(node))
            continue

    missing_refs = failed_import_names.intersection(_global_load_names(selected_body))
    if missing_refs:
        raise ImportError(f"Selected symbols reference unavailable imports: {', '.join(sorted(missing_refs))}")

    subset = ast.Module(body=selected_body, type_ignores=[])
    ast.fix_missing_locations(subset)
    exec(compile(subset, str(target), "exec"), module.__dict__)
    return module

def _load_module_from_file(alias: str, relative_file_path: str, import_path: str = "", symbols: tuple[str, ...] = ()):
    """Load a source module by file path when its directory is not a valid Python package name."""
    import importlib.util
    import types
    from pathlib import Path

    base = Path(source_path).resolve()
    target = (base / relative_file_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ImportError(f"Module path escapes source directory: {relative_file_path}") from exc
    if not target.is_file():
        raise ImportError(f"Module file not found: {relative_file_path}")
    module_name = import_path or alias
    package_parts = module_name.split(".")[:-1] if import_path else []
    package_dirs = []
    cursor = target.parent.parent if target.name == "__init__.py" else target.parent
    for _part in reversed(package_parts):
        package_dirs.insert(0, cursor)
        cursor = cursor.parent
    for index, package_dir in enumerate(package_dirs):
        package_name = ".".join(package_parts[: index + 1])
        existing = sys.modules.get(package_name)
        if existing is not None and not getattr(existing, "__code2mcp_namespace__", False):
            continue
        namespace = types.ModuleType(package_name)
        namespace.__package__ = package_name
        namespace.__path__ = [str(package_dir)]
        namespace.__file__ = str(package_dir / "__init__.py")
        namespace.__code2mcp_namespace__ = True
        sys.modules[package_name] = namespace
    spec = importlib.util.spec_from_file_location(module_name, str(target))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for: {relative_file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    _code2mcp_add_source_paths()
    target_dir = str(target.parent)
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        if symbols:
            return _code2mcp_load_selected_symbols_from_file(alias, relative_file_path, symbols)
        raise exc
    return module
'''


def _module_import_lines(import_path: str, alias: str, file_path: str = "", symbols: list[str] | None = None) -> str:
    relative_file_path = _normalized_relative_file_path(file_path)
    clean_symbols = tuple(dict.fromkeys(symbol for symbol in (symbols or []) if str(symbol).isidentifier()))
    symbols_literal = repr(clean_symbols)
    require_line = (
        f'\n    _code2mcp_require_symbols({alias}, "{import_path or alias}", {symbols_literal})'
        if clean_symbols
        else ""
    )
    fallback_require_line = (
        f'\n        _code2mcp_require_symbols({alias}, "{import_path or alias}", {symbols_literal})'
        if clean_symbols
        else ""
    )
    if _is_valid_import_path(import_path):
        fallback_lines = (
            f'{alias} = _load_module_from_file("{alias}", {relative_file_path!r}, "{import_path}", {symbols_literal})\n'
            f'        _code2mcp_require_symbols({alias}, "{import_path}", {symbols_literal})\n'
            f'        _code2mcp_import_errors.pop("{alias}", None)'
            if relative_file_path
            else f'_code2mcp_add_source_paths()\n        sys.modules.pop("{import_path}", None)\n        import {import_path} as {alias}{fallback_require_line}\n'
            f'        _code2mcp_import_errors.pop("{alias}", None)'
        )
        return f"""try:
    import {import_path} as {alias}{require_line}
except Exception as exc:
    _code2mcp_import_errors["{alias}"] = str(exc)
    try:
        {fallback_lines}
    except Exception as source_exc:
        {alias} = None
        _code2mcp_import_errors["{alias}"] = f"{{exc}}; source fallback: {{source_exc}}"
"""
    if relative_file_path:
        return f"""try:
    {alias} = _load_module_from_file("{alias}", {relative_file_path!r}, "", {symbols_literal})
    _code2mcp_require_symbols({alias}, "{relative_file_path}", {symbols_literal})
except Exception as exc:
    {alias} = None
    _code2mcp_import_errors["{alias}"] = str(exc)"""
    return (
        f"{alias} = None\n"
        f"_code2mcp_import_errors[{alias!r}] = "
        "\"No valid import path or source file was available\""
    )


def _symbol_import_lines(import_path: str, alias: str, file_path: str, symbols: list[str]) -> str:
    clean_symbols = [symbol for symbol in symbols if str(symbol).isidentifier()]
    if not clean_symbols:
        return ""
    unavailable_assignments = "\n".join(f"{symbol} = None" for symbol in clean_symbols)
    relative_file_path = _normalized_relative_file_path(file_path)
    if _is_valid_import_path(import_path):
        return f"""try:
    from {import_path} import {', '.join(clean_symbols)}
except Exception:
    {unavailable_assignments.replace(chr(10), chr(10) + '    ')}"""
    if relative_file_path:
        symbol_assignments = "\n".join(
            f'{symbol} = getattr({alias}, "{symbol}", None)' for symbol in clean_symbols
        )
        return f"""try:
    {alias} = _load_module_from_file("{alias}", {relative_file_path!r}, "", {repr(tuple(clean_symbols))})
    {symbol_assignments.replace(chr(10), chr(10) + '    ')}
except Exception:
    {unavailable_assignments.replace(chr(10), chr(10) + '    ')}"""
    return unavailable_assignments


def _path_guard_lines(param_names: list[str]) -> str:
    lines = []
    for name in param_names:
        if _is_path_like_param(name):
            lines.append(f"        {name} = _safe_resolve_path(source_path, {name})")
    return "\n".join(lines)


def _class_detail_requires_arguments(detail: dict[str, Any] | None) -> bool:
    if not isinstance(detail, dict):
        return False
    return bool(
        detail.get("constructor_requires_args")
        or detail.get("constructor_has_varargs")
        or detail.get("constructor_has_kwargs")
    )


def _safe_path_helper_source() -> str:
    return '''
def _safe_resolve_path(base_dir: str, user_path: str):
    """Resolve a user path under base_dir and reject unsafe user-controlled paths."""
    if not user_path:
        return user_path
    import re
    from pathlib import Path, PureWindowsPath

    raw_path = str(user_path).strip()
    if not raw_path:
        return raw_path
    if any(ord(ch) < 32 for ch in raw_path):
        raise ValueError(f"Control characters are not allowed in paths: {user_path}")
    if "://" in raw_path or raw_path.lower().startswith(("file:", "http:", "https:", "s3:", "gs:")):
        raise ValueError(f"URI/path schemes are not allowed: {user_path}")
    if raw_path.startswith(("~", "\\\\", "//")):
        raise ValueError(f"Home, UNC, and network paths are not allowed: {user_path}")

    base = Path(base_dir).resolve()
    candidate = Path(raw_path)
    windows_candidate = PureWindowsPath(raw_path)
    normalized_parts = [part for part in re.split(r"[\\\\/]+", raw_path) if part not in {"", "."}]
    sensitive_tokens = {
        "auth",
        "credential",
        "credentials",
        "email",
        "emails",
        "key",
        "keys",
        "dob",
        "medical_record_number",
        "mrn",
        "national",
        "national_id",
        "password",
        "passwords",
        "patient",
        "patient_id",
        "patient_name",
        "patientid",
        "patientname",
        "phi",
        "phone",
        "phones",
        "pii",
        "private",
        "secret",
        "secrets",
        "ssn",
        "token",
        "tokens",
    }
    reserved_windows_names = {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }

    if candidate.is_absolute() or windows_candidate.is_absolute() or windows_candidate.drive:
        raise ValueError(f"Absolute paths are not allowed: {user_path}")
    if ".." in normalized_parts:
        raise ValueError(f"Parent directory traversal is not allowed: {user_path}")
    for part in normalized_parts:
        lowered = part.lower()
        if ":" in part:
            raise ValueError(f"Windows drive/stream separators are not allowed: {user_path}")
        if lowered.startswith("."):
            raise ValueError(f"Hidden path segments are not allowed: {user_path}")
        stem = lowered.rsplit(".", 1)[0]
        if stem in reserved_windows_names:
            raise ValueError(f"Reserved Windows device names are not allowed: {user_path}")
        part_tokens = {token for token in re.split(r"[^a-z0-9]+", lowered) if token}
        stem_tokens = {token for token in re.split(r"[^a-z0-9]+", stem) if token}
        if (
            lowered in sensitive_tokens
            or stem in sensitive_tokens
            or part_tokens.intersection(sensitive_tokens)
            or stem_tokens.intersection(sensitive_tokens)
        ):
            raise ValueError(f"Sensitive path segment is not allowed: {user_path}")

    candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path is outside the allowed directory: {user_path}") from exc
    return str(resolved)
'''


def _is_mcp_tool_decorator(decorator: ast.AST) -> bool:
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "tool"
        and isinstance(func.value, ast.Name)
        and func.value.id == "mcp"
    )


def _decorator_tool_name(decorator: ast.AST) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None
    if not _is_mcp_tool_decorator(decorator):
        return None
    for keyword_node in decorator.keywords:
        if keyword_node.arg == "name" and isinstance(keyword_node.value, ast.Constant):
            value = keyword_node.value.value
            if isinstance(value, str):
                return value
    return None


def _exception_handler_returns_success_true(handler: ast.ExceptHandler) -> bool:
    for child in ast.walk(handler):
        if not isinstance(child, ast.Return):
            continue
        value = child.value
        if isinstance(value, ast.Dict):
            for key, item in zip(value.keys, value.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "success"
                    and isinstance(item, ast.Constant)
                    and item.value is True
                ):
                    return True
        if isinstance(value, ast.Call) and _call_name(value.func) == "dict":
            for keyword_node in value.keywords:
                if (
                    keyword_node.arg == "success"
                    and isinstance(keyword_node.value, ast.Constant)
                    and keyword_node.value.value is True
                ):
                    return True
    return False


def _is_broad_exception_handler(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names: list[str] = []
    if isinstance(handler.type, ast.Tuple):
        names.extend(_call_name(item) for item in handler.type.elts)
    else:
        names.append(_call_name(handler.type))
    return any(name in {"Exception", "BaseException"} or name.endswith(".Exception") for name in names)


def _tool_exception_success_errors(tree: ast.AST) -> list[str]:
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        tool_decorators = [decorator for decorator in node.decorator_list if _is_mcp_tool_decorator(decorator)]
        if not tool_decorators:
            continue
        declared_name = _decorator_tool_name(tool_decorators[0]) or node.name
        for child in ast.walk(node):
            if (
                isinstance(child, ast.ExceptHandler)
                and _is_broad_exception_handler(child)
                and _exception_handler_returns_success_true(child)
            ):
                errors.append(
                    f"Tool '{declared_name}' broad exception handler returns success=True instead of surfacing failure"
                )
                break
    return errors


def _allowed_tool_names_from_analysis(analysis_result: Dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    llm_analysis = analysis_result.get("llm_analysis", {})
    for module in llm_analysis.get("core_modules", []) or []:
        candidate_functions = _module_wrapper_candidate_names(module, "function")
        candidate_classes = _module_wrapper_candidate_names(module, "class")
        for func in (candidate_functions if candidate_functions is not None else module.get("functions", []) or []):
            raw_name = str(func).rstrip("*")
            if raw_name.isidentifier():
                allowed.add(raw_name)
            name = _safe_identifier(raw_name, "tool")
            allowed.add(name)
        for cls in (candidate_classes if candidate_classes is not None else module.get("classes", []) or []):
            raw_name = str(cls).rstrip("*")
            if raw_name.isidentifier():
                allowed.add(raw_name)
            name = _safe_identifier(raw_name, "tool")
            allowed.add(name)
            allowed.add(name.lower())

    if _detect_project_type(analysis_result) == "C/C++":
        allowed.add("compile_status")
    if not allowed:
        allowed.add("core")
    return allowed


def _backing_symbols_by_tool_name(analysis_result: Dict[str, Any]) -> dict[str, set[str]]:
    symbols: dict[str, set[str]] = {}
    llm_analysis = analysis_result.get("llm_analysis", {})
    for module in llm_analysis.get("core_modules", []) or []:
        candidate_functions = _module_wrapper_candidate_names(module, "function")
        candidate_classes = _module_wrapper_candidate_names(module, "class")
        for func in (candidate_functions if candidate_functions is not None else module.get("functions", []) or []):
            raw_name = str(func).rstrip("*")
            if not raw_name:
                continue
            for tool_name in {raw_name, _safe_identifier(raw_name, "tool")}:
                symbols.setdefault(tool_name, set()).add(raw_name)
        for cls in (candidate_classes if candidate_classes is not None else module.get("classes", []) or []):
            raw_name = str(cls).rstrip("*")
            if not raw_name:
                continue
            safe_name = _safe_identifier(raw_name, "tool")
            for tool_name in {raw_name, safe_name, safe_name.lower()}:
                symbols.setdefault(tool_name, set()).add(raw_name)
    return symbols


def _module_wrapper_candidate_names(module: dict[str, Any], kind: str) -> set[str] | None:
    candidates = module.get("wrapper_candidates")
    if not isinstance(candidates, list):
        return None
    names = {
        str(item.get("name", "")).rstrip("*")
        for item in candidates
        if isinstance(item, dict) and item.get("kind") == kind and str(item.get("name", "")).strip()
    }
    return names


def _import_aliases_for_symbols(tree: ast.AST, symbols: set[str]) -> set[str]:
    aliases = set(symbols)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name in symbols and alias.asname:
                aliases.add(alias.asname)
    return aliases


def _module_aliases_for_backing_calls(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases.add(alias.asname or alias.name.split(".")[0])
            continue
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call_name = _call_name(node.value.func)
        if call_name not in {"_load_module_from_file", "importlib.import_module"}:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return aliases


def _getattr_symbol_from_module_call(call: ast.Call, symbols: set[str], module_aliases: set[str]) -> str | None:
    if _call_name(call.func) != "getattr" or len(call.args) < 2:
        return None
    obj_name = _call_name(call.args[0])
    if obj_name.split(".")[0] not in module_aliases:
        return None
    attr = call.args[1]
    if isinstance(attr, ast.Constant) and attr.value in symbols:
        return str(attr.value)
    return None


def _tool_runtime_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    class RuntimeVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is node:
                for statement in child.body:
                    self.visit(statement)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is node:
                for statement in child.body:
                    self.visit(statement)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return None

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return None

        def generic_visit(self, child: ast.AST) -> None:
            nodes.append(child)
            super().generic_visit(child)

    RuntimeVisitor().visit(node)
    return nodes


def _assigned_target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_assigned_target_names(item))
        return names
    return []


def _local_backing_callables(
    runtime_nodes: list[ast.AST],
    symbols: set[str],
    module_aliases: set[str],
) -> set[str]:
    callables: set[str] = set()
    for child in runtime_nodes:
        if not isinstance(child, ast.Assign) or not isinstance(child.value, ast.Call):
            continue
        if _getattr_symbol_from_module_call(child.value, symbols, module_aliases) is None:
            continue
        for target in child.targets:
            callables.update(_assigned_target_names(target))
    return callables


def _call_uses_backing_symbol(
    call: ast.Call,
    *,
    tool_name: str,
    aliases: set[str],
    module_aliases: set[str],
    local_backing_callables: set[str],
    symbols: set[str],
) -> bool:
    call_name = _call_name(call.func)
    if (
        "." in call_name
        and call_name.split(".")[0] in module_aliases
        and call_name.split(".")[-1] in aliases
    ):
        return True
    if call_name in aliases and call_name != tool_name:
        return True
    if call_name in local_backing_callables:
        return True
    if (
        call_name == "_call_quietly"
        and call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id in local_backing_callables
    ):
        return True
    if isinstance(call.func, ast.Call) and _call_name(call.func.func) == "getattr" and len(call.func.args) >= 2:
        return _getattr_symbol_from_module_call(call.func, symbols, module_aliases) is not None
    return False


def _expression_uses_backing_result(
    expression: ast.AST | None,
    *,
    tool_name: str,
    aliases: set[str],
    module_aliases: set[str],
    local_backing_callables: set[str],
    symbols: set[str],
    tainted_names: set[str],
) -> bool:
    if expression is None:
        return False
    found = False

    class BackingResultVisitor(ast.NodeVisitor):
        def visit_Name(self, child: ast.Name) -> None:
            nonlocal found
            if child.id in tainted_names:
                found = True

        def visit_Call(self, child: ast.Call) -> None:
            nonlocal found
            if _call_uses_backing_symbol(
                child,
                tool_name=tool_name,
                aliases=aliases,
                module_aliases=module_aliases,
                local_backing_callables=local_backing_callables,
                symbols=symbols,
            ):
                found = True
                return
            self.generic_visit(child)

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return None

    BackingResultVisitor().visit(expression)
    return found


def _tool_references_backing_symbol(node: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.AST, symbols: set[str]) -> bool:
    if not symbols:
        return True
    aliases = _import_aliases_for_symbols(tree, symbols)
    module_aliases = _module_aliases_for_backing_calls(tree)
    runtime_nodes = _tool_runtime_nodes(node)
    local_backing_callables = _local_backing_callables(runtime_nodes, symbols, module_aliases)
    tainted_names: set[str] = set()
    for child in runtime_nodes:
        assigned_names: list[str] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            value = child.value
            for target in child.targets:
                assigned_names.extend(_assigned_target_names(target))
        elif isinstance(child, ast.AnnAssign):
            value = child.value
            assigned_names.extend(_assigned_target_names(child.target))
        if assigned_names:
            if _expression_uses_backing_result(
                value,
                tool_name=node.name,
                aliases=aliases,
                module_aliases=module_aliases,
                local_backing_callables=local_backing_callables,
                symbols=symbols,
                tainted_names=tainted_names,
            ):
                tainted_names.update(assigned_names)
            else:
                tainted_names.difference_update(assigned_names)
            continue
        if isinstance(child, ast.Return) and _expression_uses_backing_result(
            child.value,
            tool_name=node.name,
            aliases=aliases,
            module_aliases=module_aliases,
            local_backing_callables=local_backing_callables,
            symbols=symbols,
            tainted_names=tainted_names,
        ):
            return True
    return False


def _validate_safe_path_helper_runtime(source: str, tree: ast.AST) -> list[str]:
    helper_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_safe_resolve_path"
        ),
        None,
    )
    if helper_node is None:
        return ["missing _safe_resolve_path helper"]
    if isinstance(helper_node, ast.AsyncFunctionDef):
        return ["_safe_resolve_path must be a synchronous function"]
    helper_source = ast.get_source_segment(source, helper_node) or ""
    if not helper_source.strip():
        return ["cannot inspect _safe_resolve_path helper source"]
    namespace: dict[str, Any] = {}
    try:
        exec(compile(helper_source, "<code2mcp-safe-path-helper>", "exec"), namespace)
        helper = namespace.get("_safe_resolve_path")
    except Exception as exc:
        return [f"_safe_resolve_path does not compile independently: {exc}"]
    if not callable(helper):
        return ["_safe_resolve_path helper is not callable"]

    unsafe_cases = {
        "../secrets/national_id.csv": "parent traversal",
        "secrets/national_id.csv": "sensitive path segment",
        "patient_data/stroke_clean.csv": "sensitive path segment",
        ".env": "hidden path segment",
        "file:///etc/passwd": "URI/path scheme",
        r"C:\Users\demo\secret.csv": "absolute path",
        "records/report.csv:secret": "Windows stream separator",
        "NUL.txt": "reserved Windows device name",
        "data\x00.csv": "control character",
    }
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = os.path.join(tmp_dir, "source")
        os.makedirs(base, exist_ok=True)
        try:
            allowed = helper(base, "data.csv")
            resolved_allowed = os.path.abspath(str(allowed))
            resolved_base = os.path.abspath(base)
            if os.path.commonpath([resolved_base, resolved_allowed]) != resolved_base:
                failures.append("allowed relative path resolved outside source")
        except Exception as exc:
            failures.append(f"allowed relative path produced invalid result: {exc}")
        for raw_path, label in unsafe_cases.items():
            try:
                helper(base, raw_path)
            except ValueError:
                continue
            except Exception as exc:
                failures.append(f"{label} raised {type(exc).__name__} instead of ValueError")
            else:
                failures.append(f"{label} was accepted")
    return failures


def _validate_mcp_service_source(source: str, analysis_result: Dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"mcp_service.py syntax error: {exc}"]

    allowed_names = _allowed_tool_names_from_analysis(analysis_result)
    backing_symbols = _backing_symbols_by_tool_name(analysis_result)
    require_backing_reference = _detect_project_type(analysis_result) != "C/C++"
    fastmcp_app_vars: list[str] = []
    create_app_defs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    tool_count = 0
    path_guard_runtime_errors: list[str] | None = None
    if "def _load_module_from_file" in source:
        if "Path(project_root).resolve()" in source or "Module path escapes project directory" in source:
            errors.append("Module file loader must resolve relative to source_path, not project_root")
    errors.extend(_tool_exception_success_errors(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if isinstance(value, ast.Call) and _call_name(value.func).endswith("FastMCP"):
                for target in targets:
                    if isinstance(target, ast.Name):
                        fastmcp_app_vars.append(target.id)

        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if node.name == "create_app":
            create_app_defs.append(node)

        tool_decorators = [decorator for decorator in node.decorator_list if _is_mcp_tool_decorator(decorator)]
        if not tool_decorators:
            continue

        tool_count += 1
        declared_name = _decorator_tool_name(tool_decorators[0]) or node.name
        if allowed_names and declared_name not in allowed_names and node.name not in allowed_names:
            errors.append(f"Tool '{declared_name}' is not backed by analysis_result functions/classes")
        tool_symbols = backing_symbols.get(declared_name) or backing_symbols.get(node.name) or set()
        if require_backing_reference and tool_symbols and not _tool_references_backing_symbol(node, tree, tool_symbols):
            errors.append(
                f"Tool '{declared_name}' does not reference backing analysis symbol result(s) in its returned value: "
                + ", ".join(sorted(tool_symbols))
            )

        if node.args.vararg is not None:
            errors.append(f"Tool '{declared_name}' uses *args")
        if node.args.kwarg is not None:
            errors.append(f"Tool '{declared_name}' uses **kwargs")

        args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        untyped_args = [arg.arg for arg in args if arg.annotation is None]
        if untyped_args:
            errors.append(
                f"Tool '{declared_name}' has untyped parameters: "
                + ", ".join(untyped_args)
            )
        sensitive_args = [arg.arg for arg in args if looks_sensitive_parameter(arg.arg)]
        if sensitive_args:
            errors.append(
                f"Tool '{declared_name}' exposes sensitive-looking parameters: "
                + ", ".join(sensitive_args)
            )
        unsafe_runtime_reasons = _function_body_unsafe_runtime_side_effect_reasons(node, _runtime_call_aliases(tree))
        if unsafe_runtime_reasons:
            errors.append(
                f"Tool '{declared_name}' performs unsafe runtime operations: "
                + ", ".join(unsafe_runtime_reasons)
            )
        path_args = [
            arg.arg
            for arg in args
            if _is_path_like_param(arg.arg)
        ]
        if path_args:
            function_source = ast.get_source_segment(source, node) or ""
            if "_safe_resolve_path" not in function_source:
                joined = ", ".join(path_args)
                errors.append(f"Tool '{declared_name}' exposes path-like parameters without safe resolution: {joined}")
            required_path_guard_fragments = [
                "Absolute paths are not allowed",
                "Control characters are not allowed",
                "Hidden path segments are not allowed",
                "Parent directory traversal is not allowed",
                "Reserved Windows device names are not allowed",
                "Sensitive path segment is not allowed",
                "URI/path schemes are not allowed",
                "Windows drive/stream separators are not allowed",
            ]
            missing_fragments = [
                fragment
                for fragment in required_path_guard_fragments
                if fragment not in source
            ]
            if missing_fragments:
                errors.append(
                    f"Tool '{declared_name}' exposes path-like parameters but _safe_resolve_path is incomplete: "
                    + ", ".join(missing_fragments)
                )
            if path_guard_runtime_errors is None:
                path_guard_runtime_errors = _validate_safe_path_helper_runtime(source, tree)
            if path_guard_runtime_errors:
                errors.append(
                    f"Tool '{declared_name}' exposes path-like parameters but _safe_resolve_path failed runtime policy checks: "
                    + "; ".join(path_guard_runtime_errors)
                )

    if tool_count == 0:
        errors.append("mcp_service.py does not register any FastMCP tools")
    unique_app_vars = sorted(set(fastmcp_app_vars))
    if len(unique_app_vars) != 1:
        errors.append(f"mcp_service.py must define exactly one FastMCP app instance, found {len(unique_app_vars)}")
    if len(create_app_defs) != 1:
        errors.append(f"mcp_service.py must define exactly one create_app(), found {len(create_app_defs)}")
    elif len(unique_app_vars) == 1:
        app_var = unique_app_vars[0]
        returns_app = any(
            isinstance(child, ast.Return)
            and isinstance(child.value, ast.Name)
            and child.value.id == app_var
            for child in ast.walk(create_app_defs[0])
        )
        if not returns_app:
            errors.append(f"create_app() must return the FastMCP app instance '{app_var}'")
    return errors


def _tool_contract_for_prompt(analysis_result: Dict[str, Any]) -> str:
    llm_analysis = analysis_result.get("llm_analysis", {})
    contract = []
    for module in llm_analysis.get("core_modules", []) or []:
        functions = [str(name).rstrip("*") for name in module.get("functions", []) or []]
        classes = [str(name).rstrip("*") for name in module.get("classes", []) or []]
        if not functions and not classes:
            continue
        contract.append({
            "package": module.get("package", ""),
            "module": module.get("module", ""),
            "file_path": module.get("file_path", ""),
            "allowed_functions": functions,
            "allowed_classes": classes,
            "function_signatures": module.get("function_signatures", {}),
            "function_details": module.get("function_details", {}),
            "class_details": module.get("class_details", {}),
            "wrapper_candidates": module.get("wrapper_candidates", []),
        })
    return json_dumps_safe(contract)


def json_dumps_safe(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _generate_mcp_service(analysis_result: Dict[str, Any], retry_info: Dict[str, Any] = None, loop_summary: Dict[str, Any] | None = None) -> str:
    try:
        llm_service = get_llm_service()

        project_type = _detect_project_type(analysis_result)
        deps = analysis_result.get("dependencies", {})
        has_pyproject = bool(deps.get("pyproject"))
        packages = (analysis_result.get("structure") or {}).get("packages") or []
        core_modules = (analysis_result.get("llm_analysis") or {}).get("core_modules", [])
        has_signatures = any(isinstance(m.get("function_signatures"), dict) and m.get("function_signatures") for m in core_modules)
        tool_contract = _tool_contract_for_prompt(analysis_result)

        if project_type != "C/C++" and (not has_pyproject or not packages or has_signatures):
            return _generate_mcp_service_fallback(analysis_result)

        system_prompt = """You are a production Python engineer generating a FastMCP service from verified repository analysis.

Return Python source code only. Do not include Markdown fences or commentary.
Favor small, verifiable wrappers over broad demos. If evidence is insufficient, generate a minimal safe service instead of inventing behavior."""

        if project_type == "C/C++":
            base_prompt = f"""Generate MCP (Model Context Protocol) service code for C/C++ projects:

Analysis result: {analysis_result}

Project type: C/C++ project

Allowed wrapper contract:
{tool_contract}

Requirements:
1. Generate a complete MCP service file using fastmcp library
2. Do not try to directly import C++ source code, but create a Python wrapper
3. Use subprocess to call the compiled executable file, or use ctypes/cffi to call dynamic libraries
4. Include necessary import statements: from fastmcp import FastMCP, subprocess, ctypes
5. Use FastMCP class to create the service application: mcp = FastMCP("service_name")
6. Create tool endpoints for each core function, using @mcp.tool decorator
7. Focus on core functionality endpoints only
8. Must include create_app() function, which returns FastMCP instance
9. Tool functions must return a standard dictionary, containing success/result/error fields
10. Do not use *args or **kwargs in any @mcp.tool function; all parameters must be explicit and typed
11. Do not generate unrelated demonstration tools. Every MCP tool must wrap a function/class listed in the allowed wrapper contract.
12. If a tool exposes a file_path/path parameter, validate it with _safe_resolve_path before calling project code. Reject absolute paths, URL/URI schemes, "~", UNC/network paths, ".." segments, hidden path segments, sensitive path segments such as secret/token/password/key/credential/private/auth/patient/pii/phi/dob/mrn, and anything resolving outside source_path.
13. Do not add health, weather, monitoring, sentiment, example, placeholder, or tutorial tools unless they are explicitly listed in the allowed wrapper contract.

C/C++ project specific requirements:
- Create a Python wrapper, do not directly import C++ code
- Use subprocess to call executable files or ctypes to call dynamic libraries
- Provide compilation status check and error handling
- If compilation fails, return a structured failure dictionary with the real error
- For C++ module import errors, do not simulate success; expose the unavailable build/import state as a structured failure
- Support multiple build systems: CMake, Makefile, configure, etc."""

        else:
            base_prompt = f"""Generate MCP (Model Context Protocol) service code:

Analysis result: {analysis_result}

Project type: {project_type} project

Allowed wrapper contract:
{tool_contract}

Requirements:
1. Generate a complete MCP (Model Context Protocol) service file using fastmcp library
2. Include necessary import statements: from fastmcp import FastMCP
3. Add path settings at the top with source fallback support:
   - import os, import sys
   - source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
   - if runtime dependency_installation.strategy == "package" and passed == true, import the installed package first and only add source_path if that import fails
   - otherwise add source_path/src_layout_path before repository imports
4. Use FastMCP class to create the service application: mcp = FastMCP("service_name")
5. Generate tool endpoints only for functions/classes listed in the allowed wrapper contract, using @mcp.tool decorator, including name and description parameters
6. Focus on verified core functionality endpoints only
7. Must include create_app() function, which returns FastMCP instance
8. Tool functions must return a standard dictionary, containing success/result/error fields, do not add description or other extra fields
9. Do not use *args or **kwargs in any @mcp.tool function; all parameters must be explicit and typed
10. Do not generate unrelated demonstration tools. Every MCP tool must wrap a real function/class listed in the allowed wrapper contract.
11. If a tool exposes a file_path/path parameter, validate it with _safe_resolve_path before calling project code. Reject absolute paths, URL/URI schemes, "~", UNC/network paths, ".." segments, hidden path segments, sensitive path segments such as secret/token/password/key/credential/private/auth/patient/pii/phi/dob/mrn, and anything resolving outside source_path.
12. Do not add health, weather, monitoring, sentiment, example, placeholder, or tutorial tools unless they are explicitly listed in the allowed wrapper contract.

CRITICAL Import Requirements:
- If pyproject.toml exists with a valid package name, you may import using that package name.
- If pyproject.toml does NOT exist or the package cannot be imported, import modules using local paths after sys.path injection (e.g., "from scripts.SequencePatternMatching import ...").
- Do NOT invent new top-level package names that do not exist.
- If you implement _load_module_from_file, resolve relative_file_path under source_path, never under project_root.
- You may remove any leading "source." or "src." prefix from analysis results when importing locally after sys.path injection.
- When env installed the repository by package name, avoid putting source_path before site-packages because unbuilt source trees can shadow compiled wheels.
- All imports must work out-of-the-box without requiring packaging when pyproject.toml is absent."""

        if retry_info:
            error_analysis = retry_info.get('error_analysis', {})
            fix_strategy = retry_info.get('fix_strategy', {})
            specific_fixes = retry_info.get('specific_fixes', [])

            retry_guidance = f"""

Smart Error Fix Guidance

Retry Information:
- Retry Count: {retry_info.get('retry_count', 0)}
- Error Type: {error_analysis.get('error_analysis', {}).get('error_type', 'Unknown')}
- Severity: {error_analysis.get('error_analysis', {}).get('severity', 'Unknown')}
- Root Cause: {error_analysis.get('error_analysis', {}).get('root_cause', 'Unknown')}

Specific Fix Strategy:
Fix Approach: {fix_strategy.get('approach', 'Generic Fix')}

Specific Modifications to be Executed:"""

            for i, fix in enumerate(specific_fixes, 1):
                retry_guidance += f"""
{i}. File: {fix.get('file', 'unknown')}
    Action: {fix.get('action', 'modify')}
    Content: {fix.get('content', 'Not specified')}
    Reason: {fix.get('reason', 'Not specified')}"""

            import_fixes = fix_strategy.get('import_fixes', [])
            if import_fixes:
                retry_guidance += f"""

Import Statement Fix Requirements:
{chr(10).join(f'- {fix}' for fix in import_fixes)}"""

            path_fixes = fix_strategy.get('path_fixes', [])
            if path_fixes:
                retry_guidance += f"""

Path Configuration Fix Requirements:
{chr(10).join(f'- {fix}' for fix in path_fixes)}"""

            prevention = error_analysis.get('prevention', {})
            if prevention:
                retry_guidance += f"""

Required Preventive Measures:
- Error Handling: {', '.join(prevention.get('error_handling', []))}
- Validation Logic: {', '.join(prevention.get('validation', []))}
- Fallback Scheme: {', '.join(prevention.get('fallback', []))}"""

            retry_guidance += f"""

Key Requirements:
1. Must strictly follow the above repair strategy
2. Add module existence verification
3. Provide fallback import scheme
4. Ensure basic operation even when dependencies are missing

Confidence: {error_analysis.get('confidence', 0):.2f}
"""

            base_prompt += retry_guidance

        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + base_prompt + """

Decorator Usage Guidelines:
- Use @mcp.tool(name="tool_name", description="Tool description") format
- name parameter must match an allowed function/class-derived tool name
- description parameter provides a concise function description
- function docstring provides detailed parameter and return value descriptions

Output requirements:
- Return Python code only.
- Do not include Markdown.
- Do not invent tools.
- Do not use *args or **kwargs in @mcp.tool functions.
- If a wrapper cannot be implemented safely, return a clear error dictionary inside that wrapper rather than fabricating behavior."""
        if state := locals().get('state'):
            loop_summary = state.get("loop_summary") if isinstance(state, dict) else None
        else:
            loop_summary = None
        if loop_summary:
            user_prompt = f"Loop summary: {loop_summary}\n\n" + user_prompt
        generated_code = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not generated_code or len(generated_code.strip()) < 100:
            logger.warning("LLM code generation failed, using fallback template")
            return _generate_mcp_service_fallback(analysis_result)
        generated_code = _strip_code_fences(generated_code)
        validation_errors = _validate_mcp_service_source(generated_code, analysis_result)
        if validation_errors:
            logger.warning(f"Generated MCP service failed static quality gate, using fallback: {validation_errors}")
            return _generate_mcp_service_fallback(analysis_result)
        return generated_code

    except Exception as e:
        logger.error(f"LLM code generation error: {e}")
        return _generate_mcp_service_fallback(analysis_result)

def _generate_mcp_service_fallback(analysis_result: Dict[str, Any]) -> str:
    llm_analysis = analysis_result.get("llm_analysis", {})
    core_modules = llm_analysis.get("core_modules", [])
    repo_name = analysis_result.get("repository_name", "unknown")
    service_name = f"{repo_name.lower()}_service"

    project_type = _detect_project_type(analysis_result)
    prefer_installed_imports = _prefer_installed_package_imports(analysis_result)

    imports = []
    tools_code = ""

    # C/C++ project specific handling
    if project_type == "C/C++":
        imports.append("import subprocess")
        imports.append("import os")
        imports.append("import sys")

        for module in core_modules:
            package = module.get("package", "")
            functions = module.get("functions", [])
            classes = module.get("classes", [])

            if package:
                if package.startswith("source."):
                    package = package[7:]

                for func in functions:
                    if func.endswith("*"):
                        func = func[:-1]

                    tools_code += f"""
@mcp.tool(name="{func}", description="{func} function (C++ wrapper)")
def {func}(command_args: list[str] = None):
    \"\"\"Call C++ function {func}\"\"\"
    try:
        # This needs to be adjusted based on the actual C++ executable file path
        executable_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source", "build", "{func}")

        if not os.path.exists(executable_path):
            return {{"success": False, "error": f"C++ executable file not found: {{executable_path}}", "result": None}}

        # Call C++ executable file
        result = subprocess.run([executable_path] + list(command_args or []),
                              capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return {{"success": True, "result": result.stdout.strip(), "error": None}}
        else:
            return {{"success": False, "error": result.stderr.strip(), "result": None}}

    except Exception as e:
        return {{"success": False, "error": f"C++ function call failed: {{str(e)}}", "result": None}}
"""

    else:
        # Python project handling
        for module in core_modules:
            package = module.get("package", "")
            module_name = module.get("module", "")
            functions = module.get("functions", [])
            classes = module.get("classes", [])
            confidence = module.get("import_confidence", "medium")

            file_path = module.get("file_path", "")

            if package or file_path:
                import_path = _import_path_from_module_metadata(package, module_name, file_path)
                if not import_path and file_path:
                    import_path = _normalized_relative_file_path(file_path).removesuffix(".py").replace("/", ".")
                alias = _module_alias(import_path)

                clean_functions = []
                clean_classes = []
                candidate_functions = _module_wrapper_candidate_names(module, "function")
                candidate_classes = _module_wrapper_candidate_names(module, "class")

                for func in functions:
                    clean_name = func[:-1] if func.endswith("*") else func
                    if candidate_functions is None or clean_name in candidate_functions:
                        clean_functions.append(clean_name)

                func_sigs = module.get("function_signatures", {})
                func_details = module.get("function_details", {}) if isinstance(module.get("function_details", {}), dict) else {}
                class_details = module.get("class_details", {}) if isinstance(module.get("class_details", {}), dict) else {}
                module_imports = module.get("imports", []) if isinstance(module.get("imports", []), list) else []
                filtered_functions = []
                for func in clean_functions:
                    detail = func_details.get(func, {}) if isinstance(func_details, dict) else {}
                    raw_params = func_sigs.get(func, []) if isinstance(func_sigs, dict) else []
                    score_params = raw_params if isinstance(detail, dict) and detail else (_clean_param_names(raw_params) or [])
                    if _function_wrapper_score(
                        func,
                        score_params,
                        detail,
                        None,
                        module_imports,
                    ) is not None:
                        filtered_functions.append(func)
                clean_functions = filtered_functions
                for cls in classes:
                    if cls.endswith("*"):
                        cls = cls[:-1]
                    if candidate_classes is not None and cls not in candidate_classes:
                        continue
                    cls_detail = class_details.get(cls, {}) if isinstance(class_details, dict) else {}
                    if _class_detail_requires_arguments(cls_detail):
                        logger.info(f"Skipping class wrapper for {cls}: constructor requires explicit arguments")
                        continue
                    if _class_wrapper_score(cls, cls_detail, None, module_imports) is None:
                        logger.info(f"Skipping class wrapper for {cls}: class is not a safe default wrapper candidate")
                        continue
                    clean_classes.append(cls)

                all_items = list(set(clean_functions + clean_classes))
                if all_items:
                    imports.append(_module_import_lines(import_path, alias, file_path, all_items))

                # Deterministic wrappers using function_signatures from analysis
                for func in clean_functions:
                    raw_params = func_sigs.get(func) if isinstance(func_sigs, dict) else None
                    detail = func_details.get(func, {}) if isinstance(func_details, dict) else {}
                    param_details = detail.get("parameter_details", []) if isinstance(detail, dict) else []
                    param_list, call_args, param_names = _tool_signature_and_call(
                        raw_params,
                        param_details,
                        func,
                        detail,
                        module.get("imports", []) if isinstance(module.get("imports", []), list) else [],
                    )
                    guard_lines = _path_guard_lines(param_names)
                    if guard_lines:
                        guard_lines = guard_lines + "\n"
                    call_line = _function_call_line("_code2mcp_target", call_args)
                    tools_code += f"""
@mcp.tool(name="{func}", description="Auto-wrapped function {func}")
def {func}({param_list}):
    try:
        _code2mcp_target = getattr({alias}, "{func}", None)
        if _code2mcp_target is None:
            return {{"success": False, "result": None, "error": "Function {func} is not available"}}
{guard_lines}{call_line}        return {{"success": True, "result": result, "error": None}}
    except SystemExit as e:
        return {{"success": False, "result": None, "error": f"SystemExit: {{e}}"}}
    except Exception as e:
        return {{"success": False, "result": None, "error": str(e)}}
"""

                for cls in clean_classes:
                    tools_code += f"""
@mcp.tool(name="{cls.lower()}", description="{cls} class")
def {cls.lower()}():
    \"\"\"{cls} class\"\"\"
    try:
        _code2mcp_target = getattr({alias}, "{cls}", None)
        if _code2mcp_target is None:
            return {{"success": False, "result": None, "error": "Class {cls} is not available, path may need adjustment"}}
        instance = _code2mcp_target()
        return {{"success": True, "result": str(instance), "error": None}}
    except SystemExit as e:
        return {{"success": False, "result": None, "error": f"SystemExit: {{e}}"}}
    except Exception as e:
        return {{"success": False, "result": None, "error": str(e)}}
"""


    if not imports:
        imports = ["# No imports available"]
        tools_code = """
@mcp.tool(name="core", description="Default core function")
def core(payload: dict = None):
    return {"success": False, "result": None, "error": "no_import_available"}
"""

    if project_type == "C/C++":
        content = f"""import contextlib
import io
import json
import os
import sys
import subprocess
import ctypes
from pathlib import Path

{_source_bootstrap_source(False)}

from fastmcp import FastMCP

{chr(10).join(imports)}
{_safe_path_helper_source()}
{_quiet_call_helper_source()}
{_runtime_value_helper_source()}

mcp = FastMCP("{service_name}")

{tools_code}

@mcp.tool(name="compile_status", description="Check C++ compilation status")
def compile_status():
    \"\"\"Check C++ compilation status\"\"\"
    try:
        build_dir = os.path.join(source_path, "build")
        if os.path.exists(build_dir):
            return {{"success": True, "result": {{"status": "compiled", "build_dir": build_dir}}}}
        else:
            return {{"success": True, "result": {{"status": "not_compiled", "message": "C++ code needs to be compiled"}}}}
    except Exception as e:
        return {{"success": False, "error": f"Compilation status check failed: {{str(e)}}"}}

def create_app():
    \"\"\"Create and return FastMCP application instance\"\"\"
    return mcp

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8000"))
    transport = os.environ.get("MCP_TRANSPORT", "http")
    if transport == "http":
        mcp.run(transport="http", host="0.0.0.0", port=port)
    else:
        mcp.run()
"""

    else:
        content = f"""import contextlib
import io
import json
import os
import sys

{_source_bootstrap_source(prefer_installed_imports)}

from fastmcp import FastMCP

{_module_loader_source()}
{chr(10).join(imports)}
{_safe_path_helper_source()}
{_quiet_call_helper_source()}
{_runtime_value_helper_source()}

mcp = FastMCP("{service_name}")

{tools_code}


def create_app():
    \"\"\"Create and return FastMCP application instance\"\"\"
    return mcp

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8000"))
    transport = os.environ.get("MCP_TRANSPORT", "http")
    if transport == "http":
        mcp.run(transport="http", host="0.0.0.0", port=port)
    else:
        mcp.run()
"""
    return content

def _generate_adapter_import(analysis_result: Dict[str, Any], loop_summary: Dict[str, Any] | None = None) -> str:
    if not _adapter_llm_enabled():
        return _generate_adapter_import_fallback(analysis_result)

    try:
        llm_service = get_llm_service()

        system_prompt = """You are a production Python engineer generating a minimal import adapter for verified repository symbols.

Return Python source code only. Do not include Markdown fences or commentary. Do not invent APIs."""

        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        tool_contract = _tool_contract_for_prompt(analysis_result)
        user_prompt = prefix + f"""Generate Import mode adapter code for MCP plugin:

Analysis result: {analysis_result}

Allowed wrapper contract:
{tool_contract}

Important requirements:
1. Generate a complete adapter class, the class name must be Adapter
2. Add path settings at the beginning of the file: import os, import sys, source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source"), sys.path.insert(0, source_path)
3. Import statements must use the package/module paths from the allowed wrapper contract, do not invent package names
4. Create methods only for functions/classes in the allowed wrapper contract
5. Include error handling and status return
6. Handle import failure cases, provide graceful fallback
7. The class must include a mode attribute, initialized to "import"
8. The code structure must be clear, use separators to group different functional modules
9. All methods must return a unified dictionary format, containing the status field
10. Error messages must be in English only; provide clear, concise, actionable guidance.
11. Do not add demo, health, monitoring, weather, sentiment, or tutorial methods unless they are explicitly listed in the allowed wrapper contract

Function generation requirements:
- Generate corresponding methods based on the allowed_functions and allowed_classes fields only
- Create an instance method for each allowed class only when it can be instantiated safely
- Create a call method for each allowed function
- Keep wrappers small and verifiable
- Each method must have a concise docstring and parameter description
- Include complete error handling and status return

Import path requirements:
- Since sys.path is already pointing to the source directory, import statements should remove the "source." prefix from the package field
- Import all identified classes and functions in the analysis result
- Do not simplify to short package names
- Ensure the call is the actual implementation of the original repository, not an external package installation

Method implementation requirements:
- Create a dedicated instance method for each imported class
- Create a dedicated call method for each imported function
- Each method must have a clear parameter definition and return value description
- Include complete error handling and exception capture
- Provide actionable error messages in fallback mode
- Ensure all imported functions have corresponding method implementations

Code structure requirements:
- Add a clear module description at the beginning of the file
- Use separators to group different functional modules
- Each method must have a detailed docstring
- Unified error handling pattern
- Actionable error messages in fallback mode
- Clear code structure, easy to maintain and extend

Note: Directly return Python code, do not include any Markdown format. The class name must be Adapter. The code must be clear and readable, with a reasonable structure. Do not invent methods or imports."""

        generated_code = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not generated_code or len(generated_code.strip()) < 100:
            logger.warning("LLM adapter code generation failed, using fallback template")
            return _generate_adapter_import_fallback(analysis_result)
        return _strip_code_fences(generated_code)

    except Exception as e:
        logger.error(f"LLM adapter code generation error: {e}")
        return _generate_adapter_import_fallback(analysis_result)

def _generate_adapter_import_fallback(analysis_result: Dict[str, Any]) -> str:
    llm_analysis = analysis_result.get("llm_analysis", {})
    core_modules = llm_analysis.get("core_modules", [])

    imports = []
    methods = []

    for module in core_modules:
        package = module.get("package", "")
        module_name = module.get("module", "")
        functions = module.get("functions", [])
        classes = module.get("classes", [])
        file_path = module.get("file_path", "")

        if package or file_path:

            if package.startswith("source."):
                package = package[7:]

            import_path = _import_path_from_module_metadata(package, module_name, file_path)
            if not import_path and file_path:
                import_path = _normalized_relative_file_path(file_path).removesuffix(".py").replace("/", ".")
            alias = _module_alias(import_path)

            all_items = list(set(functions + classes))
            if all_items:
                imports.append(_symbol_import_lines(import_path, alias, file_path, all_items))

            for func in functions:
                methods.append(f"""
    def {func}(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Call {import_path}.{func}\"\"\"
        try:
            payload = payload or {{}}
            # Check if function is available
            if {func} is None:
                return {{"success": False, "result": None, "error": "Function {func} is not available"}}
            result = {func}(**payload)
            return {{"success": True, "result": result, "error": None}}
        except Exception as e:
            return {{"success": False, "result": None, "error": str(e)}}
""")

            for cls in classes:
                methods.append(f"""
    def {cls.lower()}(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Call {import_path}.{cls}\"\"\"
        try:
            payload = payload or {{}}
            # Check if class is available
            if {cls} is None:
                return {{"success": False, "result": None, "error": "Class {cls} is not available"}}
            instance = {cls}(**payload)
            return {{"success": True, "result": str(instance), "error": None}}
        except Exception as e:
            return {{"success": False, "result": None, "error": str(e)}}
""")

    if not imports:
        imports = []
        methods = ["""
    def core(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Default core function\"\"\"
        return {"success": False, "result": None, "error": "no_import_available"}
"""]

    content = f"""
\"\"\"
FastMCP Import mode adapter
Provides module import and function call services
\"\"\"

import json
import logging
import os
import sys
from typing import Dict, Any

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

{_module_loader_source()}
{chr(10).join(imports)}

class Adapter:
    \"\"\"Import mode adapter, supports dynamic module import and function call\"\"\"

    def __init__(self):
        \"\"\"Initialize adapter\"\"\"
        self.mode = "import"
        self._initialize_imports()

    def _initialize_imports(self):
        \"\"\"Initialize module imports\"\"\"
        # Modules required will be dynamically imported here
        pass

    # ==================== Function Methods ====================
{chr(10).join(methods)}

    def get_status(self) -> Dict[str, Any]:
        \"\"\"Get adapter status\"\"\"
        return {{
            "mode": self.mode,
            "success": True,
            "error": None,
            "available_functions": {len([m for m in methods if "def " in m])}
        }}
"""
    return content

def _generate_adapter_cli(analysis_result: Dict[str, Any], loop_summary: Dict[str, Any] | None = None) -> str:
    """Generate CLI mode adapter code using LLM"""
    if not _adapter_llm_enabled():
        return _generate_adapter_cli_fallback(analysis_result)

    try:
        llm_service = get_llm_service()

        system_prompt = """You are a production Python engineer generating a minimal CLI adapter from verified entry points.

Return Python source code only. Do not include Markdown fences or commentary. Do not invent commands."""

        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + f"""Generate CLI mode adapter code for MCP plugin:

Analysis result: {analysis_result}

Requirements:
1. Generate a complete CLI mode adapter class
2. Add path settings at the beginning of the file: import os, import sys, source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source"), sys.path.insert(0, source_path)
3. Include only necessary import statements
4. Generate corresponding methods only for CLI commands listed in analysis_result["llm_analysis"]["cli_commands"]
5. Include error handling and status return
6. Use subprocess to execute CLI commands
7. Do not add demo, monitoring, weather, sentiment, or tutorial commands

Note: Directly return Python code, do not include any Markdown format."""

        generated_code = _retry_generate_text(llm_service, user_prompt, system_prompt)
        if not generated_code or len(generated_code.strip()) < 100:
            logger.warning("LLM CLI adapter code generation failed, using fallback template")
            return _generate_adapter_cli_fallback(analysis_result)
        return _strip_code_fences(generated_code)

    except Exception as e:
        logger.error(f"LLM CLI adapter code generation error: {e}")
        return _generate_adapter_cli_fallback(analysis_result)

def _generate_adapter_cli_fallback(analysis_result: Dict[str, Any]) -> str:
    """Fallback CLI mode adapter generation function"""
    llm_analysis = analysis_result.get("llm_analysis", {})
    cli_commands = llm_analysis.get("cli_commands", [])

    methods = []
    for cmd in cli_commands:
        name = cmd.get("name", "unknown")
        module = cmd.get("module", "")
        methods.append(f"""
    def {name}(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Execute CLI command: {name}\"\"\"
        try:
            import subprocess
            cmd = ["python", "-m", "{module}"]
            if payload:
                cmd.extend(["--input", json.dumps(payload)])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return {{"success": True, "result": result.stdout, "error": None}}
            else:
                return {{"success": False, "result": None, "error": result.stderr}}
        except Exception as e:
            return {{"success": False, "result": None, "error": str(e)}}
""")

    if not methods:
        methods = ["""
    def core(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Default CLI function\"\"\"
        return {"success": False, "result": None, "error": "no_cli_available"}
"""]

    content = f"""import json
import subprocess
from typing import Dict, Any

class Adapter:
    \"\"\"CLI mode adapter\"\"\"

    def __init__(self):
        self.mode = "cli"
{chr(10).join(methods)}
"""
    return content

def _generate_adapter_blackbox(analysis_result: Dict[str, Any]) -> str:
    content = """import json
import subprocess
import os
import sys
from typing import Dict, Any

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

class Adapter:
    \"\"\"Blackbox mode adapter\"\"\"

    def __init__(self):
        self.mode = "blackbox"

    def core(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"Blackbox mode core function\"\"\"
        try:
            scripts = [
                ["python", "main.py"],
                ["python", "-m", "pytest", "--help"],
                ["python", "setup.py", "test"]
            ]

            for script in scripts:
                try:
                    result = subprocess.run(script, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        return {"success": True, "result": f"Script {script} executed successfully", "error": None}
                except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as script_error:
                    print(f"Script execution failed {script}: {script_error}")
                    continue

            return {"success": False, "result": None, "error": "no_executable_script_found"}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}
"""
    return content

def _generate_requirements_txt(analysis_result: Dict[str, Any], repo_root: str) -> str:
    import os
    from pathlib import Path
    reqs: list[str] = []
    def add_line(line: str):
        s = (line or "").strip()
        if not s or s.startswith('#'):
            return
        if s.lower().startswith('python'):
            return
        if s not in reqs:
            reqs.append(s)

    add_line("fastmcp")
    add_line("fastapi")
    add_line("uvicorn[standard]")
    add_line("pydantic>=2.0.0")

    root = Path(repo_root)
    src = root / "source"

    def read_lines(p: Path):
        try:
            for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                add_line(ln)
        except Exception:
            pass

    for p in [root / "requirements.txt", src / "requirements.txt"]:
        if p.exists():
            read_lines(p)

    # pyproject.toml dependencies
    for p in [root / "pyproject.toml", src / "pyproject.toml"]:
        if p.exists():
            try:
                try:
                    import tomllib as _toml  # type: ignore
                except Exception:
                    import tomli as _toml  # type: ignore
                with open(p, "rb") as fp:
                    data = _toml.load(fp)
                for item in (data.get("project", {}).get("dependencies", []) or []):
                    add_line(item)
            except Exception:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    import re
                    m = re.search(r"\[project\][\s\S]*?dependencies\s*=\s*\[(.*?)\]", text, re.IGNORECASE | re.DOTALL)
                    if m:
                        body = m.group(1)
                        for item in re.findall(r"\"([^\"]+)\"", body):
                            add_line(item)
                except Exception:
                    pass

    # setup.cfg install_requires
    for p in [root / "setup.cfg", src / "setup.cfg"]:
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                import re
                m = re.search(r"\[options\][\s\S]*?install_requires\s*=\s*(.*?)\n\[", text + "\n[", re.IGNORECASE | re.DOTALL)
                if m:
                    block = m.group(1)
                    for ln in block.splitlines():
                        add_line(ln)
            except Exception:
                pass

    # setup.py install_requires
    for p in [root / "setup.py", src / "setup.py"]:
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                import re
                m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.IGNORECASE | re.DOTALL)
                if m:
                    body = m.group(1)
                    for a, b in re.findall(r"\"([^\"]+)\"|'([^']+)'", body):
                        add_line(a or b)
            except Exception:
                pass

    # environment.yml pip deps
    for p in [root / "environment.yml", src / "environment.yml"]:
        if p.exists():
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(p.read_text(encoding="utf-8", errors="ignore")) or {}
                for d in data.get("dependencies", []) or []:
                    if isinstance(d, dict) and "pip" in d:
                        for pkg in d.get("pip", []) or []:
                            add_line(pkg)
            except Exception:
                pass

    # merge LLM detected dependencies
    llm_analysis = analysis_result.get("llm_analysis", {})
    dependencies = llm_analysis.get("dependencies", {})
    for dep in (dependencies.get("required", []) or []):
        if dep and isinstance(dep, str):
            add_line(dep)
    for dep in ((analysis_result.get("dependencies") or {}).get("import_packages", []) or []):
        if dep and isinstance(dep, str):
            add_line(dep)

    # de-duplicate by package key
    seen = set()
    ordered: list[str] = []
    for r in reqs:
        key = r.split('==')[0].split('>=')[0].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(r)
    return "\n".join(ordered) + "\n"


def _generate_readme_mcp(analysis_result: Dict[str, Any], loop_summary: Dict[str, Any] | None = None) -> str:
    """Generate README document using LLM"""
    if not _readme_llm_enabled():
        return _generate_readme_mcp_fallback(analysis_result)

    try:
        llm_service = get_llm_service()

        system_prompt = """You are a professional technical documentation writer.

Please generate Markdown documentation directly, do not include any code block tags or other format instructions.

Focus on creating clear, well-structured Markdown documentation."""

        prefix = f"Loop summary: {loop_summary}\n\n" if loop_summary else ""
        user_prompt = prefix + f"""Generate MCP plugin README:

Analysis result: {analysis_result}

Requirements:
1. Generate a complete README.md document
2. Include project overview, installation instructions, and usage methods
3. List all available tool endpoints
4. Include notes and troubleshooting
5. Use Markdown format, clear structure

Note: Directly return Markdown document content, do not include any code block tags."""

        generated_doc = _retry_generate_text(llm_service, user_prompt, system_prompt)

        if not generated_doc or len(generated_doc.strip()) < 100:
            logger.warning("LLM README generation failed, using fallback template")
            return _generate_readme_mcp_fallback(analysis_result)
        return generated_doc.strip()

    except Exception as e:
        logger.error(f"LLM README generation error: {e}")
        return _generate_readme_mcp_fallback(analysis_result)

def _generate_readme_mcp_fallback(analysis_result: Dict[str, Any]) -> str:
    """Fallback README generation function"""
    repo_name = analysis_result.get("repository_name", "unknown")
    llm_analysis = analysis_result.get("llm_analysis", {})
    import_strategy = llm_analysis.get("import_strategy", {})

    content = f"""# {repo_name} MCP Plugin

## Overview
This is an MCP plugin generated for the {repo_name} project, implemented using {import_strategy.get('primary', 'unknown')} mode.

## Installation Dependencies
```bash
pip install -r requirements.txt
```

## Start Service
```bash
python start_mcp.py
```

## Usage
After the service starts, you can call the following tools via MCP client:

"""

    core_modules = llm_analysis.get("core_modules", [])
    for module in core_modules:
        functions = module.get("functions", [])
        classes = module.get("classes", [])

        for func in functions:
            content += f"- `{func}(payload)`: {module.get('description', '')} - {func} function\n"

        for cls in classes:
            content += f"- `{cls.lower()}(payload)`: {module.get('description', '')} - {cls} class\n"

    content += """
## Notes
- Plugin adopts minimal invasive design, does not modify original project code
- If issues arise, please check if the original project is running normally
"""

    return content

def _strip_code_fences(content: str) -> str:
    import re
    content = re.sub(r'^```(?:python)?\s*\n?', '', content)
    content = re.sub(r'\n?\s*```\s*$', '', content)
    return content.strip()


COMPLEX_WRAPPER_PARAM_NAMES = {
    "all_lines",
    "alignment",
    "annotation",
    "annotations",
    "action",
    "all_inst",
    "app",
    "ar",
    "arg_list",
    "arg_names",
    "args",
    "array",
    "attribute_variants",
    "ax",
    "axes",
    "axis",
    "bench",
    "bonds",
    "bottom_left",
    "bounds",
    "binop",
    "block",
    "callback",
    "callbacks",
    "callable",
    "calibration",
    "categorical_dtypes",
    "cdf",
    "cgi",
    "client",
    "cls",
    "cmap",
    "chunk",
    "chunks",
    "collection",
    "consensus",
    "component",
    "components",
    "coeff",
    "coeffs",
    "coefficient",
    "column",
    "columns",
    "cols",
    "config",
    "condition",
    "connection",
    "comparator",
    "coordinate",
    "coordinate_on_solar_disk",
    "coordinates",
    "coord",
    "cosmo",
    "cursor",
    "cv",
    "data",
    "database",
    "dataframe",
    "dataset",
    "dicts",
    "delta",
    "declim",
    "decls",
    "decl_map",
    "degrees",
    "dist",
    "dictionary",
    "doc",
    "distribution",
    "document",
    "documents",
    "docstring",
    "dt",
    "dt1",
    "dt2",
    "dt_index",
    "df",
    "domain",
    "dupes",
    "edge",
    "edge_list",
    "edgelist",
    "edges",
    "edges1",
    "edges2",
    "edges_counted",
    "embedding",
    "endog",
    "element",
    "elements",
    "entity_list",
    "epoch",
    "epochs",
    "estimator",
    "entrypoints",
    "expr",
    "expression",
    "expressions",
    "evoked",
    "executor",
    "exog",
    "f",
    "faces",
    "fact",
    "factors",
    "fhandle",
    "fieldvals",
    "fid",
    "file_lines",
    "fig",
    "filters",
    "fn",
    "footprint",
    "form",
    "func",
    "function",
    "fwd",
    "generator",
    "generators",
    "gold_sequence",
    "graph",
    "handle",
    "hdr",
    "hdr_from",
    "hdr_to",
    "header",
    "headers",
    "hsp",
    "image",
    "img",
    "infile",
    "indices",
    "index_fields",
    "inrec",
    "info",
    "info_bin",
    "info_py",
    "init",
    "input_lines",
    "inputs",
    "integral",
    "integrals",
    "insts",
    "iter",
    "keys",
    "kwargs",
    "li",
    "line_floats",
    "lines",
    "logits",
    "logl",
    "lt",
    "ma",
    "many_to_one",
    "mask",
    "matrix",
    "mapping",
    "mappings",
    "meta",
    "metadata",
    "mesh",
    "model",
    "molecule",
    "molecules",
    "molecule_store",
    "motif",
    "namespace",
    "network",
    "node",
    "nodes",
    "notes_to_add",
    "obj",
    "object",
    "observer",
    "outer_face",
    "paral",
    "parser",
    "precedence_list",
    "params",
    "points",
    "prob",
    "probs",
    "pseq",
    "payload",
    "position",
    "positions",
    "pred",
    "proc",
    "processor",
    "ralim",
    "random_state",
    "random_state_children",
    "random_state_parent",
    "record",
    "records",
    "response",
    "res",
    "resid",
    "residue",
    "rbinop",
    "requirement",
    "requirements",
    "package_versions",
    "result",
    "results",
    "row",
    "rows",
    "rng",
    "raw",
    "raws",
    "rsa_data",
    "scores",
    "scored_pairs",
    "seq",
    "session",
    "self",
    "sequence",
    "source",
    "series",
    "shape",
    "site_classes",
    "splits",
    "stock",
    "stream",
    "smap",
    "csd",
    "stc",
    "stc1",
    "stc2",
    "stc_est",
    "stc_true",
    "surf",
    "surface",
    "subjects_dir",
    "supplementary_lines",
    "superset",
    "table",
    "tables",
    "task",
    "tasks",
    "tensor",
    "tensors",
    "template",
    "text_lines",
    "timedelta",
    "top_right",
    "tz",
    "tzinfo",
    "tree",
    "tree_constructor",
    "trees",
    "src",
    "url",
    "vertices",
    "v",
    "vcf",
    "vcf_genotypes",
    "vulgar_comp",
    "x1",
    "x2",
    "xdrdata",
    "ys",
}
COMPLEX_WRAPPER_PARAM_PARTS = {
    "baseurl",
    "collection",
    "connection",
    "coord",
    "corr",
    "cov",
    "cursor",
    "dataframe",
    "database",
    "dataset",
    "datetime",
    "dist",
    "document",
    "endog",
    "executor",
    "exog",
    "generator",
    "graph",
    "host",
    "matrix",
    "object",
    "paral",
    "payload",
    "position",
    "pred",
    "proc",
    "processor",
    "relativedelta",
    "result",
    "rrule",
    "series",
    "stock",
    "task",
    "table",
    "tensor",
    "timedelta",
    "timezone",
    "tzinfo",
    "url",
}
RUNTIME_OBJECT_ANNOTATION_PARTS = {
    "datetime",
    "dateutil",
    "parserinfo",
    "relativedelta",
    "rrule",
    "timedelta",
    "timezone",
    "tzfile",
    "tzinfo",
    "tzrange",
    "network",
}
HEAVY_MODULE_IMPORTS = {
    "deepspeed",
    "jax",
    "lightning",
    "pytorch_lightning",
    "tensorflow",
    "torch",
    "torchvision",
}
SCIENTIFIC_ARRAY_IMPORTS = {
    "cv2",
    "cupy",
    "numpy",
    "pandas",
    "scipy",
    "skimage",
    "torch",
}
SCIENTIFIC_ARRAY_PARAM_NAMES = {
    "amplitude",
    "arr",
    "array",
    "data",
    "ecg",
    "ecg_cleaned",
    "eda",
    "eda_cleaned",
    "eeg",
    "emg",
    "emg_cleaned",
    "eog",
    "eog_cleaned",
    "footprint",
    "i1",
    "i2",
    "input",
    "inputs",
    "output",
    "outputs",
    "peaks",
    "ppg",
    "ppg_cleaned",
    "ppg_raw",
    "rpeaks",
    "rsp",
    "rsp_cleaned",
    "signal",
    "signal1",
    "signal2",
    "troughs",
    "values",
    "weight",
    "weights",
}
SAMPLE_FRIENDLY_PARAM_NAMES = {"value", "text", "sentence", "limit", "count", "n", "number", "size"}
SAMPLEABLE_SINGLE_LETTER_PARAM_NAMES = {"d", "i", "k", "m", "n", "p", "q", "r", "x", "y", "z"}
SAMPLE_HOSTILE_PARAM_NAMES = {
    "address",
    "api_key",
    "auth",
    "key",
    "password",
    "secret",
    "token",
    "username",
}
SAMPLE_AMBIGUOUS_PARAM_NAMES = {"name", "q", "query"}
SIDE_EFFECT_NAME_PARTS = {
    "append",
    "attach",
    "build",
    "create",
    "delete",
    "download",
    "ensure",
    "fit",
    "install",
    "monkey",
    "patch",
    "post",
    "rebuild",
    "remove",
    "save",
    "send",
    "train",
    "update",
    "upload",
    "write",
}
CLI_HELPER_NAME_PARTS = {
    "argparser",
    "optparser",
    "parser",
}
CLI_ARGUMENT_NAME_TOKENS = {
    "args",
    "arguments",
}
EXECUTION_TOOL_NAME_PARTS = {
    "cmd",
    "command",
    "execute",
    "popen",
    "run",
    "shell",
    "subprocess",
    "system",
}
STATEFUL_TOOL_NAME_PARTS = {
    "clear",
    "close",
    "kill",
    "launch",
    "reset",
    "shutdown",
    "start",
    "stop",
}
CONNECTION_TOOL_NAME_PARTS = {
    "connect",
    "connection",
    "database",
    "handler",
    "hook",
    "logger",
    "mongodb",
    "redis",
}
ENVIRONMENT_PROBE_TOOL_NAMES = {
    "array_type",
    "data_path",
    "guess_engine",
    "get_config",
    "get_include",
    "get_keywords",
    "get_libraries",
    "get_library_dirs",
    "get_user_config_file",
    "get_versions",
    "has_c",
    "has_cpp",
    "has_cuda",
    "has_cxx",
    "has_fortran",
    "has_gpu",
    "list_engines",
    "mod_version",
    "netcdf_and_hdf5_versions",
    "package_path",
    "refresh_engines",
}
DOMAIN_SPECIFIC_HELPER_TOOL_NAMES = {
    "get_extensions",
    "get_resource_mappings",
    "inds_to_season_string",
    "season_to_month_tuple",
}
ENVIRONMENT_PROBE_NAME_PARTS = {
    "availability",
    "backend",
    "compilation",
    "compiler",
}
NON_LIBRARY_PATH_SEGMENTS = {
    "benchmark",
    "benchmarks",
    "ci",
    "compilation",
    "compiler",
    "compilers",
    "doc",
    "docs",
    "example",
    "examples",
    "release",
    "releases",
    "sample",
    "samples",
    "script",
    "scripts",
    "test",
    "tests",
    "tutorial",
    "tutorials",
}
IMPORT_PACKAGE_ALIASES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "pil": "pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}
SAFE_TOP_LEVEL_CALLS = {"collections.namedtuple", "dict", "frozenset", "list", "logging.getLogger", "re.compile", "re.escape", "set", "tuple"}

COMMON_STDLIB_IMPORT_ROOTS = {
    "__future__",
    "_thread",
    "abc",
    "argparse",
    "array",
    "atexit",
    "base64",
    "binascii",
    "bisect",
    "bz2",
    "calendar",
    "cmath",
    "collections",
    "configparser",
    "contextlib",
    "copy",
    "csv",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "email",
    "enum",
    "errno",
    "fnmatch",
    "functools",
    "glob",
    "gzip",
    "hashlib",
    "heapq",
    "html",
    "http",
    "importlib",
    "inspect",
    "io",
    "itertools",
    "json",
    "keyword",
    "logging",
    "lzma",
    "math",
    "operator",
    "os",
    "os.path",
    "pathlib",
    "pickle",
    "pkgutil",
    "platform",
    "pprint",
    "queue",
    "random",
    "re",
    "select",
    "shlex",
    "shutil",
    "signal",
    "socket",
    "sqlite3",
    "statistics",
    "string",
    "struct",
    "subprocess",
    "sys",
    "sysconfig",
    "tarfile",
    "tempfile",
    "textwrap",
    "time",
    "token",
    "tokenize",
    "traceback",
    "types",
    "typing",
    "urllib",
    "uuid",
    "warnings",
    "weakref",
    "xml",
    "zipfile",
}


def _stdlib_import_roots() -> set[str]:
    names = {str(name).lower() for name in getattr(sys, "builtin_module_names", ())}
    names.update(str(name).lower() for name in getattr(sys, "stdlib_module_names", ()) or ())
    names.update(COMMON_STDLIB_IMPORT_ROOTS)
    try:
        import sysconfig

        stdlib_dir = sysconfig.get_paths().get("stdlib", "")
        if stdlib_dir and os.path.isdir(stdlib_dir):
            for entry in os.listdir(stdlib_dir):
                if entry in {"__pycache__", "site-packages", "dist-packages"}:
                    continue
                path = os.path.join(stdlib_dir, entry)
                root, ext = os.path.splitext(entry)
                if os.path.isdir(path) and os.path.isfile(os.path.join(path, "__init__.py")):
                    names.add(entry.lower())
                elif ext in {".py", ".pyd", ".so", ".dll"} and root:
                    names.add(root.lower())
    except Exception:
        pass
    return names


def _has_non_library_path_segment(*values: str) -> bool:
    for value in values:
        normalized = str(value or "").lower().replace("\\", "/")
        path_parts = [part for part in re.split(r"[/.]+", normalized) if part]
        if any(part in GENERATION_EXCLUDED_SOURCE_DIRS or part in NON_LIBRARY_PATH_SEGMENTS for part in path_parts):
            return True
        token_parts = [part for part in re.split(r"[\\/._-]+", normalized) if part]
        if any(part in NON_LIBRARY_PATH_SEGMENTS for part in token_parts):
            return True
    return False


def _runtime_installed_packages(analysis_result: Dict[str, Any]) -> set[str] | None:
    runtime = analysis_result.get("_runtime", {}) if isinstance(analysis_result, dict) else {}
    env = runtime.get("env", {}) if isinstance(runtime, dict) else {}
    dependency_installation = env.get("dependency_installation", {}) if isinstance(env, dict) else {}
    if dependency_installation.get("strategy") != "import_packages":
        return None
    installed = dependency_installation.get("installed", [])
    if not isinstance(installed, list):
        return None
    return {str(pkg).lower() for pkg in installed if str(pkg).strip()}


def _local_import_roots(core_modules: list[dict[str, Any]]) -> set[str]:
    roots: set[str] = set()
    for module in core_modules:
        package = str(module.get("package", "") or "")
        if package:
            roots.add(package.split(".")[0].lower())
        module_name = str(module.get("module", "") or "")
        if module_name:
            roots.add(module_name.split(".")[0].lower())
        file_path = _normalized_relative_file_path(str(module.get("file_path", "") or ""))
        if file_path.endswith(".py"):
            roots.add(os.path.splitext(os.path.basename(file_path))[0].lower())
    return roots


def _module_missing_runtime_imports(
    module: dict[str, Any],
    installed_packages: set[str] | None,
    local_roots: set[str],
) -> list[str]:
    if installed_packages is None:
        return []
    missing: list[str] = []
    for raw in module.get("imports", []) or []:
        root = str(raw or "").split(".")[0].strip()
        if not root:
            continue
        lowered = root.lower()
        if lowered in local_roots or lowered in _stdlib_import_roots():
            continue
        package = IMPORT_PACKAGE_ALIASES.get(lowered, lowered)
        if package.lower() not in installed_packages:
            missing.append(package)
    return sorted(set(missing))


def _source_file_import_roots(src_dir: str, file_path: str) -> set[str]:
    relative_file_path = _normalized_relative_file_path(file_path)
    if not relative_file_path:
        return set()
    path = os.path.join(src_dir, relative_file_path)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as handle:
            tree = ast.parse(handle.read() or "", filename=path)
    except Exception:
        return set()

    roots: set[str] = set()
    for node in tree.body:
        root = ""
        if isinstance(node, ast.Import) and node.names:
            root = str(node.names[0].name or "").split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = str(node.module or "").split(".")[0]
        root = root.strip().lower()
        if not root:
            continue
        roots.add(root)
        roots.add(IMPORT_PACKAGE_ALIASES.get(root, root).lower())
    return roots


def _runtime_env(analysis_result: Dict[str, Any]) -> dict[str, Any]:
    runtime = analysis_result.get("_runtime", {}) if isinstance(analysis_result, dict) else {}
    env = runtime.get("env", {}) if isinstance(runtime, dict) else {}
    return env if isinstance(env, dict) else {}


def _runtime_python_executable(analysis_result: Dict[str, Any]) -> str:
    env = _runtime_env(analysis_result)
    exec_prefix = env.get("exec_prefix")
    if isinstance(exec_prefix, list) and exec_prefix:
        candidate = str(exec_prefix[0])
        if candidate and os.path.exists(candidate):
            return candidate
    for key in ("python_executable", "venv_python"):
        candidate = str(env.get(key, "") or "")
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def _runtime_precheck_timeout() -> int:
    try:
        return max(2, min(120, int(os.getenv("CODE2MCP_RUNTIME_PRECHECK_TIMEOUT", "30"))))
    except ValueError:
        return 30


def _module_runtime_symbols_available(
    analysis_result: Dict[str, Any],
    repo_root: str,
    module: dict[str, Any],
    symbols: list[str],
) -> tuple[bool, str]:
    python_exe = _runtime_python_executable(analysis_result)
    clean_symbols = [symbol for symbol in dict.fromkeys(symbols) if str(symbol).isidentifier()]
    if not python_exe or not clean_symbols:
        return True, "runtime_precheck_unavailable"
    source_dir = os.path.join(repo_root, "source")
    file_path = module.get("file_path", "")
    import_path = _import_path_from_module_metadata(module.get("package", ""), module.get("module", ""), file_path)
    relative_file_path = _normalized_relative_file_path(file_path)
    prefer_installed = _prefer_installed_package_imports(analysis_result)
    probe = f"""
import ast
import importlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

SOURCE_PATH = {source_dir!r}
SRC_LAYOUT_PATH = os.path.join(SOURCE_PATH, "src")
IMPORT_PATH = {import_path!r}
RELATIVE_FILE_PATH = {relative_file_path!r}
SYMBOLS = {clean_symbols!r}
PREFER_INSTALLED = {prefer_installed!r}

def add_source_paths():
    for path in (SOURCE_PATH, SRC_LAYOUT_PATH):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

def require_symbols(module):
    missing = [name for name in SYMBOLS if getattr(module, name, None) is None]
    if missing:
        raise ImportError("missing expected symbols: " + ", ".join(missing))
    return module

def load_selected_symbols_from_file(alias, relative_file_path, symbols):
    base = Path(SOURCE_PATH).resolve()
    target = (base / relative_file_path).resolve()
    target.relative_to(base)
    source = target.read_text(encoding="utf-8-sig", errors="ignore")
    tree = ast.parse(source, filename=str(target))
    selected_symbols = {{str(symbol) for symbol in symbols if str(symbol).isidentifier()}}
    selected_body = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in selected_symbols
    ]
    if not selected_body:
        raise ImportError("selected symbols were not found in source file")
    module = types.ModuleType(alias)
    module.__file__ = str(target)
    module.__package__ = ""
    module.__code2mcp_source_subset__ = True
    sys.modules[alias] = module
    add_source_paths()
    target_dir = str(target.parent)
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)
    def imported_names(node):
        names = set()
        if isinstance(node, ast.Import):
            for item in node.names:
                names.add(item.asname or item.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name == "*":
                    continue
                names.add(item.asname or item.name.split(".")[0])
        return names
    def global_load_names(nodes):
        loads = set()
        local = set()
        for definition in nodes:
            if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = definition.args
                for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                    local.add(arg.arg)
                if args.vararg:
                    local.add(args.vararg.arg)
                if args.kwarg:
                    local.add(args.kwarg.arg)
            for child in ast.walk(definition):
                if isinstance(child, ast.Name):
                    if isinstance(child.ctx, ast.Load):
                        loads.add(child.id)
                    elif isinstance(child.ctx, (ast.Store, ast.Del)):
                        local.add(child.id)
        return loads - local
    failed_import_names = set()
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        try:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(target), "exec"), module.__dict__)
        except ImportError:
            failed_import_names.update(imported_names(node))
            continue
    missing_refs = failed_import_names.intersection(global_load_names(selected_body))
    if missing_refs:
        raise ImportError("selected symbols reference unavailable imports: " + ", ".join(sorted(missing_refs)))
    subset = ast.Module(body=selected_body, type_ignores=[])
    ast.fix_missing_locations(subset)
    exec(compile(subset, str(target), "exec"), module.__dict__)
    return module

def load_module_from_file(alias, relative_file_path, import_path="", symbols=()):
    base = Path(SOURCE_PATH).resolve()
    target = (base / relative_file_path).resolve()
    target.relative_to(base)
    if not target.is_file():
        raise ImportError(f"module file not found: {{relative_file_path}}")
    module_name = import_path or alias
    package_parts = module_name.split(".")[:-1] if import_path else []
    package_dirs = []
    cursor = target.parent.parent if target.name == "__init__.py" else target.parent
    for _part in reversed(package_parts):
        package_dirs.insert(0, cursor)
        cursor = cursor.parent
    for index, package_dir in enumerate(package_dirs):
        package_name = ".".join(package_parts[: index + 1])
        existing = sys.modules.get(package_name)
        if existing is not None and not getattr(existing, "__code2mcp_namespace__", False):
            continue
        namespace = types.ModuleType(package_name)
        namespace.__package__ = package_name
        namespace.__path__ = [str(package_dir)]
        namespace.__file__ = str(package_dir / "__init__.py")
        namespace.__code2mcp_namespace__ = True
        sys.modules[package_name] = namespace
    spec = importlib.util.spec_from_file_location(module_name, str(target))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create module spec for: {{relative_file_path}}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    add_source_paths()
    target_dir = str(target.parent)
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        if symbols:
            return load_selected_symbols_from_file(alias, relative_file_path, symbols)
        raise exc
    return module

def import_from_source():
    if RELATIVE_FILE_PATH:
        return load_module_from_file("_code2mcp_probe_module", RELATIVE_FILE_PATH, IMPORT_PATH, tuple(SYMBOLS))
    add_source_paths()
    if not IMPORT_PATH:
        raise ImportError("no import path or source file available")
    sys.modules.pop(IMPORT_PATH, None)
    return importlib.import_module(IMPORT_PATH)

first_error = None
try:
    if PREFER_INSTALLED and IMPORT_PATH:
        try:
            module = importlib.import_module(IMPORT_PATH)
            require_symbols(module)
        except Exception as exc:
            first_error = str(exc)
            module = import_from_source()
            require_symbols(module)
    else:
        module = import_from_source()
        require_symbols(module)
    print(json.dumps({{"ok": True, "file": getattr(module, "__file__", None)}}))
except Exception as exc:
    print(json.dumps({{"ok": False, "error": str(exc), "first_error": first_error}}))
"""
    try:
        proc = subprocess.run(
            [python_exe, "-c", probe],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=_runtime_precheck_timeout(),
        )
    except subprocess.TimeoutExpired:
        return False, "runtime import precheck timed out"
    except Exception as exc:
        return False, f"runtime import precheck failed: {exc}"
    output = (proc.stdout or "").strip().splitlines()
    payload = {}
    if output:
        try:
            payload = json.loads(output[-1])
        except Exception:
            payload = {}
    if proc.returncode == 0 and payload.get("ok"):
        return True, str(payload.get("file") or "")
    reason = payload.get("error") or (proc.stderr or proc.stdout or "runtime import precheck failed")
    first_error = payload.get("first_error")
    if first_error and first_error != reason:
        reason = f"{first_error}; source fallback: {reason}"
    return False, str(reason).strip()


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    if not isinstance(left, ast.Name) or left.id != "__name__":
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    return isinstance(right, ast.Constant) and right.value == "__main__"


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _safe_call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _safe_call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _safe_top_level_value(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, (ast.Constant, ast.Name, ast.Attribute)):
        return True
    if isinstance(node, ast.JoinedStr):
        return all(_safe_top_level_value(item) for item in node.values)
    if isinstance(node, ast.FormattedValue):
        return _safe_top_level_value(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_safe_top_level_value(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(_safe_top_level_value(item) for item in list(node.keys) + list(node.values) if item is not None)
    if isinstance(node, ast.UnaryOp):
        return _safe_top_level_value(node.operand)
    if isinstance(node, ast.BinOp):
        return _safe_top_level_value(node.left) and _safe_top_level_value(node.right)
    if isinstance(node, ast.Compare):
        return _safe_top_level_value(node.left) and all(_safe_top_level_value(item) for item in node.comparators)
    if isinstance(node, ast.Call):
        if _safe_call_name(node.func) in SAFE_TOP_LEVEL_CALLS:
            return all(_safe_top_level_value(arg) for arg in node.args) and all(
                _safe_top_level_value(keyword.value) for keyword in node.keywords
            )
    return False


def _safe_top_level_statement(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Pass)):
        return True
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return True
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return _safe_top_level_value(node.value)
    if isinstance(node, ast.If) and (_is_type_checking_guard(node) or _safe_top_level_value(node.test)):
        return all(_safe_top_level_statement(item) for item in node.body + node.orelse)
    if isinstance(node, ast.Try):
        return (
            all(_safe_top_level_statement(item) for item in node.body)
            and all(_safe_top_level_statement(item) for handler in node.handlers for item in handler.body)
            and all(_safe_top_level_statement(item) for item in node.orelse)
            and all(_safe_top_level_statement(item) for item in node.finalbody)
        )
    return False


def _module_import_side_effect_reasons(tree: ast.AST) -> list[str]:
    reasons: list[str] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value if isinstance(node, ast.AnnAssign) else node.value
            if _safe_top_level_value(value):
                continue
            reasons.append(f"top_level_assignment_call:line_{getattr(node, 'lineno', 0)}")
            continue
        if isinstance(node, ast.If) and (_is_main_guard(node) or _is_type_checking_guard(node)):
            continue
        if isinstance(node, (ast.If, ast.Try)) and _safe_top_level_statement(node):
            continue
        reasons.append(f"top_level_{type(node).__name__.lower()}:line_{getattr(node, 'lineno', 0)}")
    return reasons[:8]


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return ""


def _root_name(node: ast.AST | None) -> str:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Call):
        return _root_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _function_body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(getattr(node, "body", []) or [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _function_body_is_unsupported_placeholder(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _function_body_without_docstring(node)
    if not body:
        return True
    if all(
        isinstance(statement, ast.Pass)
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        )
        for statement in body
    ):
        return True
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Raise):
        exc_name = _call_name(statement.exc)
        return exc_name.endswith("NotImplementedError")
    if isinstance(statement, ast.Return):
        value = statement.value
        if value is None:
            return True
        if isinstance(value, ast.Constant) and value.value is None:
            return True
        return isinstance(value, ast.Name) and value.id == "NotImplemented"
    return False


def _return_name(statement: ast.stmt) -> str:
    if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Name):
        return statement.value.id
    return ""


def _function_body_is_callable_factory(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _function_body_without_docstring(node)
    nested_names = {
        statement.name
        for statement in body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not nested_names:
        return False
    return any(_return_name(statement) in nested_names for statement in body)


def _function_body_returns_generator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in ast.walk(node))


def _function_body_returns_empty_default_factory(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _function_body_without_docstring(node)
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    value = body[0].value
    if not isinstance(value, ast.Call):
        return False
    call_name = _call_name(value).lower()
    if call_name not in {"defaultdict", "collections.defaultdict"}:
        return False
    if not value.args:
        return False
    if len(value.args) == 1:
        return True
    initializer = value.args[1]
    if isinstance(initializer, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return not getattr(initializer, "elts", None) and not getattr(initializer, "keys", None)
    return False


def _function_body_returns_empty_literal_container(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _function_body_without_docstring(node)
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    value = body[0].value
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    if not isinstance(value, ast.Call) or value.args or value.keywords:
        return False
    return _call_name(value).lower() in {
        "collections.counter",
        "collections.deque",
        "collections.ordereddict",
        "counter",
        "deque",
        "dict",
        "frozenset",
        "list",
        "ordereddict",
        "set",
        "tuple",
    }


def _has_framework_entrypoint_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {_call_name(decorator.func if isinstance(decorator, ast.Call) else decorator).lower() for decorator in getattr(node, "decorator_list", [])}
    for name in names:
        if name in {"click.command", "click.group", "typer.command", "typer.callback"}:
            return True
        if name.endswith((".api_route", ".command", ".delete", ".get", ".group", ".patch", ".post", ".put", ".route", ".task", ".websocket")):
            return True
    return False


UNSAFE_FILE_READ_CALLS = {
    "bz2.open",
    "configparser.configparser.read",
    "fileinput.fileinput",
    "fileinput.fileinput.input",
    "fileinput.input",
    "glob.glob",
    "glob.iglob",
    "gzip.open",
    "h5py.file",
    "joblib.load",
    "lzma.open",
    "numpy.fromfile",
    "numpy.genfromtxt",
    "numpy.load",
    "numpy.loadtxt",
    "numpy.memmap",
    "os.lstat",
    "os.listdir",
    "os.path.exists",
    "os.path.getatime",
    "os.path.getctime",
    "os.path.getmtime",
    "os.path.getsize",
    "os.path.isdir",
    "os.path.isfile",
    "os.path.islink",
    "os.path.ismount",
    "os.path.lexists",
    "os.path.samefile",
    "os.readlink",
    "os.scandir",
    "os.stat",
    "os.statvfs",
    "os.walk",
    "pandas.read_csv",
    "pandas.read_excel",
    "pandas.read_feather",
    "pandas.read_hdf",
    "pandas.read_json",
    "pandas.read_orc",
    "pandas.read_parquet",
    "pandas.read_pickle",
    "pandas.read_sas",
    "pandas.read_stata",
    "pathlib.path.read_bytes",
    "pathlib.path.read_text",
    "pathlib.path.exists",
    "pathlib.path.glob",
    "pathlib.path.group",
    "pathlib.path.is_block_device",
    "pathlib.path.is_char_device",
    "pathlib.path.is_dir",
    "pathlib.path.is_fifo",
    "pathlib.path.is_file",
    "pathlib.path.is_mount",
    "pathlib.path.is_socket",
    "pathlib.path.is_symlink",
    "pathlib.path.iterdir",
    "pathlib.path.lstat",
    "pathlib.path.owner",
    "pathlib.path.rglob",
    "pathlib.path.readlink",
    "pathlib.path.samefile",
    "pathlib.path.stat",
    "pathlib.path.walk",
    "pickle.load",
    "polars.read_csv",
    "polars.read_excel",
    "polars.read_ipc",
    "polars.read_json",
    "polars.read_parquet",
    "scipy.io.loadmat",
    "tarfile.open",
    "linecache.getline",
    "linecache.getlines",
    "tokenize.open",
    "torch.load",
    "zipfile.zipfile",
}
OS_OPEN_FILE_MUTATION_FLAGS = {
    "os.o_append",
    "os.o_creat",
    "os.o_excl",
    "os.o_rdwr",
    "os.o_trunc",
    "os.o_wronly",
}
OS_OPEN_FILE_MUTATION_FLAG_VALUES = tuple(
    value
    for value in (
        getattr(os, "O_APPEND", None),
        getattr(os, "O_CREAT", None),
        getattr(os, "O_EXCL", None),
        getattr(os, "O_RDWR", None),
        getattr(os, "O_TRUNC", None),
        getattr(os, "O_WRONLY", None),
    )
    if isinstance(value, int)
)
MODE_SENSITIVE_FILE_OPEN_CALLS = {
    "bz2.open",
    "builtins.open",
    "gzip.open",
    "h5py.file",
    "io.fileio",
    "io.open",
    "lzma.open",
    "open",
    "os.fdopen",
    "pathlib.path.open",
    "tarfile.open",
    "zipfile.zipfile",
}
FILE_BACKED_STORE_MUTATION_CALLS = {
    "dbm.dumb.open",
    "dbm.gnu.open",
    "dbm.ndbm.open",
    "dbm.open",
    "shelve.open",
}
RUNTIME_PATH_OBJECT_RETURNING_METHODS = {
    "absolute",
    "expanduser",
    "joinpath",
    "relative_to",
    "resolve",
    "with_name",
    "with_stem",
    "with_suffix",
}
RUNTIME_PATH_OBJECT_RETURNING_ATTRIBUTES = {"parent"}
RUNTIME_PATH_SEQUENCE_ATTRIBUTES = {"parents"}
RUNTIME_ALIAS_MODULES = {
    "_thread",
    "aiohttp",
    "atexit",
    "asyncio",
    "builtins",
    "bz2",
    "concurrent.futures",
    "configparser",
    "dbm",
    "dbm.dumb",
    "dbm.gnu",
    "dbm.ndbm",
    "fileinput",
    "functools",
    "ftplib",
    "glob",
    "gzip",
    "h5py",
    "http.client",
    "http.server",
    "httpx",
    "imaplib",
    "importlib",
    "io",
    "joblib",
    "linecache",
    "logging",
    "lzma",
    "multiprocessing",
    "mysql.connector",
    "numpy",
    "os",
    "os.path",
    "pandas",
    "pathlib",
    "pickle",
    "polars",
    "poplib",
    "psycopg",
    "psycopg2",
    "pymongo",
    "redis",
    "requests",
    "requests.sessions",
    "scipy.io",
    "shutil",
    "signal",
    "socket",
    "socketserver",
    "shelve",
    "smtplib",
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlite3",
    "subprocess",
    "sys",
    "tarfile",
    "telnetlib",
    "tempfile",
    "threading",
    "tokenize",
    "torch",
    "urllib.request",
    "urllib3",
    "warnings",
    "webbrowser",
    "wsgiref.simple_server",
    "xmlrpc.client",
    "zipfile",
}
UNSAFE_DYNAMIC_CODE_CALLS = {"builtins.compile", "builtins.eval", "builtins.exec", "compile", "eval", "exec"}
UNSAFE_BACKGROUND_EXECUTION_CALLS = {
    "_thread.start_new_thread",
    "asyncio.create_task",
    "asyncio.ensure_future",
    "asyncio.run_coroutine_threadsafe",
    "thread.start_new_thread",
    "multiprocessing.process.start",
    "threading.thread.start",
    "threading.timer.start",
}
RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS = {
    "concurrent.futures.processpoolexecutor",
    "concurrent.futures.threadpoolexecutor",
    "multiprocessing.pool",
    "multiprocessing.process",
    "threading.thread",
    "threading.timer",
}
RUNTIME_BACKGROUND_EXECUTION_METHODS = {
    "apply",
    "apply_async",
    "imap",
    "imap_unordered",
    "map",
    "map_async",
    "starmap",
    "starmap_async",
    "start",
    "submit",
}
UNSAFE_NETWORK_CALLS = {
    "aiohttp.request",
    "httpx.delete",
    "httpx.get",
    "httpx.head",
    "httpx.options",
    "httpx.patch",
    "httpx.post",
    "httpx.put",
    "httpx.request",
    "httpx.stream",
    "requests.delete",
    "requests.get",
    "requests.head",
    "requests.options",
    "requests.patch",
    "requests.post",
    "requests.put",
    "requests.request",
    "socket.create_connection",
    "socket.create_server",
    "urllib.request.urlretrieve",
    "urllib.request.urlopen",
    "urllib3.request",
}
RUNTIME_NETWORK_CLIENT_CONSTRUCTORS = {
    "aiohttp.clientsession",
    "ftplib.ftp",
    "ftplib.ftp_tls",
    "http.client.httpconnection",
    "http.client.httpsconnection",
    "httpx.asyncclient",
    "httpx.client",
    "imaplib.imap4",
    "imaplib.imap4_ssl",
    "mysql.connector.connect",
    "poplib.pop3",
    "poplib.pop3_ssl",
    "psycopg.connect",
    "psycopg2.connect",
    "pymongo.mongoclient",
    "redis.from_url",
    "redis.redis",
    "redis.strictredis",
    "requests.session",
    "requests.sessions.session",
    "smtplib.smtp",
    "smtplib.smtp_ssl",
    "sqlalchemy.create_engine",
    "sqlalchemy.engine.create_engine",
    "telnetlib.telnet",
    "urllib.request.build_opener",
    "urllib3.poolmanager",
    "urllib3.proxymanager",
    "xmlrpc.client.serverproxy",
}
RUNTIME_NETWORK_CLIENT_METHODS = {
    "command",
    "commit",
    "connect",
    "cursor",
    "delete_one",
    "execute",
    "executemany",
    "fetch",
    "find",
    "find_one",
    "get",
    "getresponse",
    "insert_one",
    "login",
    "open",
    "ping",
    "query",
    "request",
    "retrbinary",
    "rollback",
    "search",
    "send",
    "sendmail",
    "set",
    "storbinary",
    "update_one",
    "write",
}
RUNTIME_NETWORK_SOCKET_CONSTRUCTORS = {"socket.socket"}
RUNTIME_NETWORK_SOCKET_METHODS = {
    "accept",
    "bind",
    "connect",
    "connect_ex",
    "listen",
    "recv",
    "recv_into",
    "recvfrom",
    "recvfrom_into",
    "send",
    "sendall",
    "sendmsg",
    "sendto",
}
RUNTIME_NETWORK_SERVER_CONSTRUCTORS = {
    "http.server.httpserver",
    "http.server.threadinghttpserver",
    "socketserver.tcpserver",
    "socketserver.threadingtcpserver",
    "socketserver.threadingudpserver",
    "socketserver.udpserver",
    "wsgiref.simple_server.make_server",
}
RUNTIME_NETWORK_SERVER_METHODS = {
    "handle_request",
    "serve_forever",
    "server_activate",
    "server_bind",
}
UNSAFE_PROCESS_STATE_MUTATION_CALLS = {
    "atexit.register",
    "atexit.unregister",
    "logging.basicconfig",
    "logging.config.dictconfig",
    "logging.config.fileconfig",
    "os.chdir",
    "os.chroot",
    "os.fchdir",
    "os.nice",
    "os.setegid",
    "os.seteuid",
    "os.setgid",
    "os.setgroups",
    "os.setpgid",
    "os.setpgrp",
    "os.setsid",
    "os.setuid",
    "os.umask",
    "signal.signal",
    "warnings.filterwarnings",
    "warnings.resetwarnings",
    "warnings.simplefilter",
}
RUNTIME_PROCESS_STATE_MUTATION_TARGETS = {
    "sys.meta_path",
    "sys.modules",
    "sys.path",
    "sys.path_hooks",
    "sys.path_importer_cache",
}
RUNTIME_PROCESS_STATE_MUTATION_METHODS = {
    "__delitem__",
    "__iadd__",
    "__ior__",
    "__setitem__",
    "append",
    "clear",
    "extend",
    "insert",
    "pop",
    "popitem",
    "remove",
    "reverse",
    "setdefault",
    "sort",
    "update",
}
RUNTIME_PATH_LITERAL_EXTENSIONS = {
    ".bz2",
    ".cfg",
    ".conf",
    ".csv",
    ".db",
    ".feather",
    ".gif",
    ".gz",
    ".htm",
    ".html",
    ".h5",
    ".hdf",
    ".hdf5",
    ".ini",
    ".joblib",
    ".json",
    ".jsonl",
    ".mat",
    ".md",
    ".npy",
    ".npz",
    ".parquet",
    ".pickle",
    ".pkl",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".svg",
    ".pt",
    ".pth",
    ".safetensors",
    ".tar",
    ".tex",
    ".tif",
    ".tiff",
    ".toml",
    ".tsv",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
    ".xz",
    ".yaml",
    ".yml",
    ".webp",
    ".zip",
}


def _runtime_call_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                canonical = alias.name
                if canonical in RUNTIME_ALIAS_MODULES:
                    if alias.asname:
                        aliases[alias.asname.lower()] = canonical
                    elif "." not in canonical:
                        aliases[canonical.lower()] = canonical
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in RUNTIME_ALIAS_MODULES:
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[(alias.asname or alias.name).lower()] = f"{node.module}.{alias.name}"
    return aliases


def _resolve_runtime_call_name(call_name: str, aliases: dict[str, str] | None = None) -> str:
    call_lower = str(call_name or "").lower()
    aliases = aliases or {}
    if call_lower in aliases:
        return aliases[call_lower].lower()
    if "." not in call_lower:
        return call_lower
    root, rest = call_lower.split(".", 1)
    if root in aliases:
        alias_target = aliases[root].lower()
        first, _, tail = rest.partition(".")
        if "." in alias_target and alias_target.rsplit(".", 1)[-1] == first:
            return f"{alias_target}.{tail}" if tail else alias_target
        return f"{alias_target}.{rest}"
    return call_lower


def _literal_getattr_runtime_call_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(call, ast.Call) or _call_name(call.func) != "getattr" or len(call.args) < 2:
        return ""
    attr = call.args[1]
    if not isinstance(attr, ast.Constant) or not isinstance(attr.value, str) or not attr.value:
        return ""
    root = _call_name(call.args[0])
    if not root:
        return ""
    return _resolve_runtime_call_name(f"{root}.{attr.value}", runtime_call_aliases)


def _literal_getattr_attribute_runtime_call_name(
    func: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    attrs: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    base = _literal_getattr_runtime_call_name(node if isinstance(node, ast.Call) else None, runtime_call_aliases)
    if not base or not attrs:
        return ""
    return _resolve_runtime_call_name(".".join([base, *reversed(attrs)]), runtime_call_aliases)


def _literal_partial_runtime_call_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if (
        not isinstance(call, ast.Call)
        or _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases) != "functools.partial"
        or not call.args
    ):
        return ""
    target = call.args[0]
    return (
        _literal_getattr_attribute_runtime_call_name(target, runtime_call_aliases)
        or _literal_getattr_runtime_call_name(target if isinstance(target, ast.Call) else None, runtime_call_aliases)
        or _resolve_runtime_call_name(
            _call_name(target),
            runtime_call_aliases,
        )
    )


def _literal_dynamic_import_module_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(call, ast.Call) or not call.args:
        return ""
    call_lower = _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases)
    if call_lower not in {"__import__", "builtins.__import__", "importlib.import_module"}:
        return ""
    module_arg = call.args[0]
    if not isinstance(module_arg, ast.Constant) or not isinstance(module_arg.value, str):
        return ""
    module_name = module_arg.value.strip()
    if module_name not in RUNTIME_ALIAS_MODULES:
        return ""
    return module_name


def _literal_dynamic_import_runtime_call_name(
    func: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    attrs: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    module_name = _literal_dynamic_import_module_name(node if isinstance(node, ast.Call) else None, runtime_call_aliases)
    if not module_name or not attrs:
        return ""
    return _resolve_runtime_call_name(".".join([module_name, *reversed(attrs)]), runtime_call_aliases)


def _path_object_returning_call_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(call, ast.Call):
        return ""
    call_lower = _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases)
    if call_lower in {"pathlib.path", "pathlib.path.cwd", "pathlib.path.home"}:
        return "pathlib.path"
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr.lower() in RUNTIME_PATH_OBJECT_RETURNING_METHODS
        and _node_resolves_to_path_object(call.func.value, runtime_call_aliases)
    ):
        return "pathlib.path"
    return ""


def _node_resolves_to_path_object(
    node: ast.AST | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> bool:
    if isinstance(node, ast.Name):
        return _resolve_runtime_call_name(node.id, runtime_call_aliases) == "pathlib.path"
    if isinstance(node, ast.Call):
        return bool(_path_object_returning_call_name(node, runtime_call_aliases))
    if (
        isinstance(node, ast.Attribute)
        and node.attr.lower() in RUNTIME_PATH_OBJECT_RETURNING_ATTRIBUTES
        and _node_resolves_to_path_object(node.value, runtime_call_aliases)
    ):
        return True
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr.lower() in RUNTIME_PATH_SEQUENCE_ATTRIBUTES
        and _node_resolves_to_path_object(node.value.value, runtime_call_aliases)
    ):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _node_resolves_to_path_object(node.left, runtime_call_aliases) or _node_resolves_to_path_object(
            node.right,
            runtime_call_aliases,
        )
    return False


def _path_object_runtime_call_name(
    func: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(func, ast.Attribute) or not _node_resolves_to_path_object(func.value, runtime_call_aliases):
        return ""
    return _resolve_runtime_call_name(f"pathlib.path.{func.attr}", runtime_call_aliases)


def _literal_looks_like_runtime_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text or "\n" in text or "\r" in text:
        return False
    lowered = text.lower().rstrip("*?")
    if lowered.startswith(("http://", "https://")):
        return False
    if "://" in lowered or "/" in text or "\\" in text:
        return True
    if lowered.startswith((".", "~")):
        return True
    return os.path.splitext(lowered)[1] in RUNTIME_PATH_LITERAL_EXTENSIONS


def _node_contains_runtime_path_literal(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _literal_looks_like_runtime_path(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_node_contains_runtime_path_literal(item) for item in node.elts)
    return False


def _node_contains_runtime_database_path_literal(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip()
        lowered = text.lower()
        if lowered == ":memory:" or lowered.startswith("file::memory:"):
            return False
        if lowered.startswith("file:"):
            return True
        return _literal_looks_like_runtime_path(text)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_node_contains_runtime_database_path_literal(item) for item in node.elts)
    return False


def _call_reads_runtime_path_literal(call: ast.Call) -> bool:
    call_name = _call_name(call.func).lower()
    if not call_name.endswith(".read"):
        return False
    candidates: list[ast.AST] = list(call.args[:1])
    candidates.extend(
        keyword.value
        for keyword in call.keywords or []
        if keyword.arg in {"file", "filename", "filenames", "path", "source"}
    )
    return any(_node_contains_runtime_path_literal(candidate) for candidate in candidates)


def _call_connects_runtime_database_path(call: ast.Call, call_lower: str) -> bool:
    if call_lower != "sqlite3.connect":
        return False
    candidates: list[ast.AST] = list(call.args[:1])
    candidates.extend(keyword.value for keyword in call.keywords or [] if keyword.arg == "database")
    return any(_node_contains_runtime_database_path_literal(candidate) for candidate in candidates)


def _open_call_mode(call: ast.Call, call_lower: str) -> str:
    if call_lower == "pathlib.path.open":
        positional_mode_index = 0
    else:
        positional_mode_index = 1
    if len(call.args) > positional_mode_index and isinstance(call.args[positional_mode_index], ast.Constant):
        return str(call.args[positional_mode_index].value or "")
    for keyword_node in call.keywords or []:
        if keyword_node.arg == "mode" and isinstance(keyword_node.value, ast.Constant):
            return str(keyword_node.value.value or "")
    return ""


def _call_is_mode_sensitive_file_open(call_name: str, call_lower: str) -> bool:
    return call_lower in MODE_SENSITIVE_FILE_OPEN_CALLS or call_name.endswith(".open")


def _call_file_open_mode_writes(call: ast.Call, call_lower: str) -> bool:
    mode = _open_call_mode(call, call_lower)
    return bool(mode and any(flag in mode for flag in ("a", "w", "x", "+")))


def _node_int_bit_or_value(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _node_int_bit_or_value(node.left)
        right = _node_int_bit_or_value(node.right)
        if left is not None and right is not None:
            return left | right
    return None


def _node_contains_os_open_mutation_flag(
    node: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _node_contains_os_open_mutation_flag(
            node.left,
            runtime_call_aliases,
        ) or _node_contains_os_open_mutation_flag(node.right, runtime_call_aliases)
    flag_name = _resolve_runtime_call_name(_call_name(node), runtime_call_aliases)
    if flag_name in OS_OPEN_FILE_MUTATION_FLAGS:
        return True
    flag_value = _node_int_bit_or_value(node)
    return flag_value is not None and any(flag_value & value for value in OS_OPEN_FILE_MUTATION_FLAG_VALUES)


def _os_open_call_mutates_file(call: ast.Call, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    candidates: list[ast.AST] = list(call.args[1:2])
    candidates.extend(keyword.value for keyword in call.keywords or [] if keyword.arg == "flags")
    return any(_node_contains_os_open_mutation_flag(candidate, runtime_call_aliases) for candidate in candidates)


def _call_exports_runtime_path_literal(call: ast.Call, call_lower: str) -> bool:
    if not (
        call_lower in {
            "joblib.dump",
            "numpy.save",
            "numpy.savetxt",
            "numpy.savez",
            "numpy.savez_compressed",
            "scipy.io.savemat",
            "shutil.unpack_archive",
            "torch.save",
        }
        or call_lower.endswith(
            (
                ".extract",
                ".extractall",
                ".to_csv",
                ".to_excel",
                ".to_feather",
                ".to_hdf",
                ".to_html",
                ".to_json",
                ".to_latex",
                ".to_markdown",
                ".to_orc",
                ".to_parquet",
                ".to_pickle",
                ".to_stata",
                ".to_xml",
                ".save",
                ".savefig",
                ".write_csv",
                ".write_excel",
                ".write_ipc",
                ".write_json",
                ".write_parquet",
            )
        )
    ):
        return False
    candidates: list[ast.AST] = list(call.args[:2])
    candidates.extend(
        keyword.value
        for keyword in call.keywords or []
        if keyword.arg in {"buf", "file", "filename", "path", "path_or_buf", "path_or_buffer", "excel_writer"}
    )
    return any(_node_contains_runtime_path_literal(candidate) for candidate in candidates)


def _call_mutates_runtime_environment(call_lower: str) -> bool:
    if call_lower in {"os.putenv", "os.unsetenv"}:
        return True
    prefix = "os.environ."
    if call_lower.startswith(prefix):
        return call_lower[len(prefix) :] in {"__delitem__", "__ior__", "__setitem__", "clear", "pop", "popitem", "setdefault", "update"}
    return False


def _reflected_runtime_state_target(call: ast.Call, runtime_call_aliases: dict[str, str] | None = None) -> str:
    call_lower = _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases)
    if call_lower not in {"builtins.delattr", "builtins.setattr", "delattr", "setattr"} or len(call.args) < 2:
        return ""
    attr = call.args[1]
    if not isinstance(attr, ast.Constant) or not isinstance(attr.value, str) or not attr.value:
        return ""
    root = _call_name(call.args[0])
    if not root:
        return ""
    return _resolve_runtime_call_name(f"{root}.{attr.value}", runtime_call_aliases)


def _target_mutates_runtime_environment(target: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_mutates_runtime_environment(item, runtime_call_aliases) for item in target.elts)
    if isinstance(target, ast.Name):
        return False
    candidate = target.value if isinstance(target, ast.Subscript) else target
    name = _literal_getattr_runtime_call_name(
        candidate if isinstance(candidate, ast.Call) else None,
        runtime_call_aliases,
    ) or _resolve_runtime_call_name(_call_name(candidate), runtime_call_aliases)
    return name == "os.environ"


def _node_mutates_runtime_environment(node: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(node, ast.Call):
        return _reflected_runtime_state_target(node, runtime_call_aliases) == "os.environ"
    if isinstance(node, ast.Assign):
        return any(_target_mutates_runtime_environment(target, runtime_call_aliases) for target in node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return _target_mutates_runtime_environment(node.target, runtime_call_aliases)
    if isinstance(node, ast.Delete):
        return any(_target_mutates_runtime_environment(target, runtime_call_aliases) for target in node.targets)
    return False


def _call_mutates_runtime_process_state(call_lower: str) -> bool:
    if call_lower in UNSAFE_PROCESS_STATE_MUTATION_CALLS:
        return True
    for target in RUNTIME_PROCESS_STATE_MUTATION_TARGETS:
        prefix = f"{target}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_PROCESS_STATE_MUTATION_METHODS
    return False


def _target_mutates_runtime_process_state(target: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_mutates_runtime_process_state(item, runtime_call_aliases) for item in target.elts)
    if isinstance(target, ast.Name):
        return False
    candidate = target.value if isinstance(target, ast.Subscript) else target
    name = _literal_getattr_runtime_call_name(
        candidate if isinstance(candidate, ast.Call) else None,
        runtime_call_aliases,
    ) or _resolve_runtime_call_name(_call_name(candidate), runtime_call_aliases)
    return name in RUNTIME_PROCESS_STATE_MUTATION_TARGETS


def _node_mutates_runtime_process_state(node: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(node, ast.Call):
        return _reflected_runtime_state_target(node, runtime_call_aliases) in RUNTIME_PROCESS_STATE_MUTATION_TARGETS
    if isinstance(node, ast.Assign):
        return any(_target_mutates_runtime_process_state(target, runtime_call_aliases) for target in node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return _target_mutates_runtime_process_state(node.target, runtime_call_aliases)
    if isinstance(node, ast.Delete):
        return any(_target_mutates_runtime_process_state(target, runtime_call_aliases) for target in node.targets)
    return False


def _call_performs_runtime_network_operation(call_lower: str) -> bool:
    if call_lower in UNSAFE_NETWORK_CALLS:
        return True
    if call_lower in RUNTIME_NETWORK_CLIENT_CONSTRUCTORS:
        return True
    if call_lower in RUNTIME_NETWORK_SERVER_CONSTRUCTORS:
        return True
    for constructor in RUNTIME_NETWORK_CLIENT_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_NETWORK_CLIENT_METHODS
    for constructor in RUNTIME_NETWORK_SOCKET_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_NETWORK_SOCKET_METHODS
    for constructor in RUNTIME_NETWORK_SERVER_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_NETWORK_SERVER_METHODS
    return False


def _assigned_call_target_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None,
    constructors: set[str],
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                value = item.context_expr
                if not isinstance(value, ast.Call):
                    continue
                call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
                if call_lower in constructors and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
            continue
        if not isinstance(value, ast.Call):
            continue
        call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
        if call_lower not in constructors:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _runtime_network_socket_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    return _assigned_call_target_names(node, runtime_call_aliases, RUNTIME_NETWORK_SOCKET_CONSTRUCTORS)


def _runtime_network_client_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    return _assigned_call_target_names(node, runtime_call_aliases, RUNTIME_NETWORK_CLIENT_CONSTRUCTORS)


def _runtime_network_server_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    return _assigned_call_target_names(node, runtime_call_aliases, RUNTIME_NETWORK_SERVER_CONSTRUCTORS)


def _call_starts_runtime_background_execution(call_lower: str) -> bool:
    if call_lower in UNSAFE_BACKGROUND_EXECUTION_CALLS:
        return True
    for constructor in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_BACKGROUND_EXECUTION_METHODS
    return False


def _runtime_background_worker_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                value = item.context_expr
                if not isinstance(value, ast.Call):
                    continue
                call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
                if call_lower in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
            continue
        if not isinstance(value, ast.Call):
            continue
        call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
        if call_lower not in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _runtime_getattr_call_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if value is None:
            continue
        call_lower = (
            _literal_getattr_attribute_runtime_call_name(value, runtime_call_aliases)
            or _literal_getattr_runtime_call_name(
                value if isinstance(value, ast.Call) else None,
                runtime_call_aliases,
            )
        )
        if not call_lower:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = call_lower
    return aliases


def _runtime_partial_call_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if not isinstance(value, ast.Call):
            continue
        call_lower = _literal_partial_runtime_call_name(value, runtime_call_aliases)
        if not call_lower:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = call_lower
    return aliases


def _runtime_dynamic_import_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if not isinstance(value, ast.Call):
            continue
        module_name = _literal_dynamic_import_module_name(value, runtime_call_aliases)
        if not module_name:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = module_name
    return aliases


def _runtime_path_object_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        combined_aliases = {**(runtime_call_aliases or {}), **aliases}
        if not _node_resolves_to_path_object(value, combined_aliases):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = "pathlib.path"
    return aliases


def _runtime_state_object_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    targets = {"os.environ", *RUNTIME_PROCESS_STATE_MUTATION_TARGETS}
    for child in ast.walk(node):
        assign_targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            assign_targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            assign_targets = [child.target]
            value = child.value
        if value is None:
            continue
        target_name = _literal_getattr_runtime_call_name(
            value if isinstance(value, ast.Call) else None,
            runtime_call_aliases,
        ) or _resolve_runtime_call_name(_call_name(value), runtime_call_aliases)
        if target_name not in targets:
            continue
        for target in assign_targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = target_name
    return aliases


def _function_body_unsafe_runtime_side_effect_reasons(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    dynamic_import_aliases = _runtime_dynamic_import_aliases(node, runtime_call_aliases)
    state_object_aliases = _runtime_state_object_aliases(node, {**(runtime_call_aliases or {}), **dynamic_import_aliases})
    path_object_aliases = _runtime_path_object_aliases(node, {**(runtime_call_aliases or {}), **dynamic_import_aliases})
    combined_runtime_aliases = {
        **(runtime_call_aliases or {}),
        **dynamic_import_aliases,
        **state_object_aliases,
        **path_object_aliases,
    }
    network_client_names = _runtime_network_client_names(node, combined_runtime_aliases)
    network_server_names = _runtime_network_server_names(node, combined_runtime_aliases)
    network_socket_names = _runtime_network_socket_names(node, combined_runtime_aliases)
    background_worker_names = _runtime_background_worker_names(node, combined_runtime_aliases)
    getattr_call_aliases = _runtime_getattr_call_aliases(node, combined_runtime_aliases)
    partial_call_aliases = _runtime_partial_call_aliases(node, combined_runtime_aliases)
    for child in ast.walk(node):
        if isinstance(child, ast.Global):
            reasons.append("mutates global state")
            continue
        if _node_mutates_runtime_environment(child, combined_runtime_aliases):
            reasons.append("mutates process environment")
            continue
        if _node_mutates_runtime_process_state(child, combined_runtime_aliases):
            reasons.append("mutates process state")
            continue
        if not isinstance(child, ast.Call):
            continue
        call_name = _call_name(child.func)
        call_lower = (
            _literal_dynamic_import_runtime_call_name(child.func, combined_runtime_aliases)
            or _literal_getattr_attribute_runtime_call_name(child.func, combined_runtime_aliases)
            or _path_object_runtime_call_name(child.func, combined_runtime_aliases)
            or _literal_getattr_runtime_call_name(child.func, combined_runtime_aliases)
            or _literal_partial_runtime_call_name(child.func, combined_runtime_aliases)
            or _resolve_runtime_call_name(
                call_name,
                combined_runtime_aliases,
            )
        )
        call_lower = getattr_call_aliases.get(call_lower, call_lower)
        call_lower = partial_call_aliases.get(call_lower, call_lower)
        if call_lower in {"exit", "quit", "sys.exit"}:
            reasons.append("can terminate the interpreter")
            continue
        if call_lower in {"input", "builtins.input"}:
            reasons.append("requires interactive stdin input")
            continue
        if call_lower in UNSAFE_DYNAMIC_CODE_CALLS:
            reasons.append("can execute dynamic code")
            continue
        if _call_mutates_runtime_environment(call_lower):
            reasons.append("mutates process environment")
            continue
        if _call_mutates_runtime_process_state(call_lower):
            reasons.append("mutates process state")
            continue
        if _call_starts_runtime_background_execution(call_lower) or (
            _root_name(child.func) in background_worker_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_BACKGROUND_EXECUTION_METHODS
        ):
            reasons.append("starts background execution")
            continue
        if call_lower in {
            "compile_run_strings",
            "os.execl",
            "os.execle",
            "os.execlp",
            "os.execlpe",
            "os.execv",
            "os.execve",
            "os.execvp",
            "os.execvpe",
            "os.fork",
            "os.forkpty",
            "os.popen",
            "os.spawnl",
            "os.spawnle",
            "os.spawnlp",
            "os.spawnlpe",
            "os.spawnv",
            "os.spawnve",
            "os.spawnvp",
            "os.spawnvpe",
            "os.startfile",
            "os.system",
            "subprocess.call",
            "subprocess.check_call",
            "subprocess.check_output",
            "subprocess.getoutput",
            "subprocess.getstatusoutput",
            "subprocess.popen",
            "subprocess.run",
            "webbrowser.open",
            "webbrowser.open_new",
            "webbrowser.open_new_tab",
        }:
            reasons.append("can execute external processes")
            continue
        if _call_performs_runtime_network_operation(call_lower) or (
            _root_name(child.func) in network_socket_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_NETWORK_SOCKET_METHODS
        ) or (
            _root_name(child.func) in network_client_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_NETWORK_CLIENT_METHODS
        ) or (
            _root_name(child.func) in network_server_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_NETWORK_SERVER_METHODS
        ):
            reasons.append("performs network requests")
            continue
        if call_lower in FILE_BACKED_STORE_MUTATION_CALLS:
            reasons.append("mutates files or directories")
            continue
        if _call_is_mode_sensitive_file_open(call_name, call_lower) and _call_file_open_mode_writes(child, call_lower):
            reasons.append("opens files in write/append mode")
            continue
        if (
            call_lower in UNSAFE_FILE_READ_CALLS
            or call_lower in MODE_SENSITIVE_FILE_OPEN_CALLS
            or call_lower.endswith((".read_bytes", ".read_text"))
            or _call_reads_runtime_path_literal(child)
            or _call_connects_runtime_database_path(child, call_lower)
        ):
            reasons.append("reads files or directories")
            continue
        if call_lower in {
            "os.chmod",
            "os.chown",
            "os.link",
            "os.makedirs",
            "os.mkdir",
            "os.remove",
            "os.rename",
            "os.replace",
            "os.rmdir",
            "os.symlink",
            "os.unlink",
            "os.utime",
            "shutil.chown",
            "shutil.copy",
            "shutil.copy2",
            "shutil.copyfile",
            "shutil.copyfileobj",
            "shutil.copymode",
            "shutil.copystat",
            "shutil.copytree",
            "shutil.make_archive",
            "shutil.move",
            "shutil.rmtree",
            "tempfile.mkdtemp",
            "tempfile.mkstemp",
            "tempfile.namedtemporaryfile",
            "tempfile.spooledtemporaryfile",
            "tempfile.temporarydirectory",
            "tempfile.temporaryfile",
        } or call_lower.endswith(
            (
                ".chmod",
                ".hardlink_to",
                ".lchmod",
                ".mkdir",
                ".rename",
                ".replace",
                ".rmdir",
                ".symlink_to",
                ".touch",
                ".unlink",
                ".write_bytes",
                ".write_text",
            )
        ) or _call_exports_runtime_path_literal(child, call_lower):
            reasons.append("mutates files or directories")
            continue
        if call_name.endswith((".write", ".writelines")):
            reasons.append("writes files or streams")
            continue
        if call_lower == "os.open":
            if _os_open_call_mutates_file(child, combined_runtime_aliases):
                reasons.append("mutates files or directories")
                continue
            reasons.append("reads files or directories")
            continue
        if _call_is_mode_sensitive_file_open(call_name, call_lower):
            reasons.append("reads files or directories")
            continue
    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique[:8]


def _function_body_has_unsafe_runtime_side_effect(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> bool:
    return bool(_function_body_unsafe_runtime_side_effect_reasons(node, runtime_call_aliases))


def _name_tokens(value: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return {part.lower() for part in re.findall(r"[A-Za-z0-9]+", spaced)}


def _detail_param_names(raw_params: list | None, detail: dict[str, Any] | None) -> list[str]:
    if isinstance(detail, dict) and isinstance(detail.get("parameters"), list):
        return [str(name) for name in detail.get("parameters", [])]
    return _clean_param_names(raw_params, skip_implicit_receiver=False) or []


def _param_detail_lookup(detail: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(detail, dict):
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for item in detail.get("parameter_details", []) or []:
        if isinstance(item, dict) and item.get("name"):
            lookup[str(item["name"])] = item
    return lookup


def _non_variadic_param_names(raw_params: list | None, detail: dict[str, Any] | None) -> list[str]:
    lookup = _param_detail_lookup(detail)
    names: list[str] = []
    for raw in _detail_param_names(raw_params, detail):
        clean = _safe_identifier(str(raw), "param")
        if clean in {"self", "cls"}:
            continue
        if lookup.get(str(raw), {}).get("kind") in {"vararg", "kwarg"}:
            continue
        names.append(str(raw))
    return names


def _looks_like_runtime_default(default: str) -> bool:
    text = str(default or "").strip()
    if not text or text in {"None", "True", "False", "Ellipsis"}:
        return False
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return False
    if text.startswith(("'", '"')) and text.endswith(("'", '"')):
        return False
    if text.startswith(("[", "{", "(")) and text.endswith(("]", "}", ")")):
        return False
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\.]*", text))


def _param_is_complex(name: str, detail: dict[str, Any] | None = None) -> bool:
    lowered = name.lower()
    decision = classify_wrapper_parameter_name(
        name,
        complex_param_names=COMPLEX_WRAPPER_PARAM_NAMES,
        complex_param_parts=COMPLEX_WRAPPER_PARAM_PARTS,
    )
    if decision.unsafe:
        return True
    annotation = str((detail or {}).get("annotation", "")).lower()
    numeric_markers = {"decimal", "double", "float", "int", "number"}
    if lowered in {"a", "b", "c", "e", "f1", "f2", "o", "r", "v", "w", "x", "y", "z"} and not any(marker in annotation for marker in numeric_markers):
        return True
    if lowered == "sentence" and "str" not in annotation:
        return True
    compact_annotation = re.sub(r"[^a-z0-9]+", "", annotation)
    if compact_annotation in {"indexlist", "scores"}:
        return True
    if any(marker in annotation for marker in RUNTIME_OBJECT_ANNOTATION_PARTS):
        return True
    if _looks_like_runtime_default(str((detail or {}).get("default", ""))):
        return True
    return any(
        marker in annotation
        for marker in (
            "array",
            "baseexecutor",
            "callable",
            "dataframe",
            "dataset",
            "datetimeindex",
            "dict",
            "iterable",
            "module",
            "network",
            "ndarray",
            "object",
            "parallel",
            "series",
            "tensor",
            "torch.",
        )
    )


def _docstring_declares_complex_param(docstring: str, param_name: str) -> bool:
    if not docstring or not param_name:
        return False
    declared_type = _docstring_param_declared_type(docstring, param_name)
    if not declared_type:
        return False
    return any(
        marker in declared_type
        for marker in (
            "array",
            "array-like",
            "array_like",
            "callable",
            "dataframe",
            "dict",
            "image",
            "instance",
            "list",
            "mapping",
            "mne.",
            "network",
            "matrix",
            "ndarray",
            "source space",
            "sequence",
            "series",
            "tensor",
            "vector",
        )
    )


NUMERIC_SEQUENCE_ADAPTER_PARAM_NAMES = {
    "b",
    "benchmark_rets",
    "factor_returns",
    "is_returns",
    "r",
    "returns",
    "underwater",
}
NUMERIC_SEQUENCE_TYPE_MARKERS = {
    "array",
    "array-like",
    "array_like",
    "list",
    "ndarray",
    "sequence",
    "series",
}
NUMERIC_SEQUENCE_IMPORT_ROOTS = {"empyrical", "numpy", "pandas", "scipy", "sklearn"}


def _docstring_param_declared_type(docstring: str, param_name: str) -> str:
    if not docstring or not param_name:
        return ""
    escaped = re.escape(param_name.lower())
    text = docstring.lower()
    patterns = (
        rf"(?im)^\s*{escaped}\s*:\s*([^\n]+)",
        rf"(?im)^\s*[-*]\s*{escaped}\s*[-:]\s*([^\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _param_uses_numeric_sequence_adapter(
    param_name: str,
    docstring: str,
    module_imports: list[str] | None,
    param_detail: dict[str, Any] | None = None,
) -> bool:
    lowered = str(param_name or "").lower()
    if lowered not in NUMERIC_SEQUENCE_ADAPTER_PARAM_NAMES:
        return False
    declared_type = _docstring_param_declared_type(docstring, lowered)
    if declared_type and not any(marker in declared_type for marker in NUMERIC_SEQUENCE_TYPE_MARKERS):
        return False
    if lowered in {"b", "r"} and not declared_type:
        return False
    default = str((param_detail or {}).get("default", "") or "").strip()
    if default and re.fullmatch(r"-?\d+(?:\.\d+)?", default):
        return False
    imports = {str(item).split(".")[0].lower() for item in (module_imports or [])}
    return bool(imports.intersection(NUMERIC_SEQUENCE_IMPORT_ROOTS) or declared_type)


def _param_has_numeric_sequence_type_evidence(
    param_name: str,
    docstring: str,
    param_detail: dict[str, Any] | None = None,
    *,
    require_annotation: bool = False,
) -> bool:
    annotation = str((param_detail or {}).get("annotation", "") or "").lower().replace("typing.", "")
    if any(marker in annotation for marker in NUMERIC_SEQUENCE_TYPE_MARKERS):
        return True
    if require_annotation:
        return False
    declared_type = _docstring_param_declared_type(docstring, str(param_name or "").lower())
    return any(marker in declared_type.lower() for marker in NUMERIC_SEQUENCE_TYPE_MARKERS)


def _param_uses_scalar_numeric_context(
    param_name: str,
    docstring: str,
    param_detail: dict[str, Any] | None = None,
) -> bool:
    lowered = str(param_name or "").lower()
    if lowered != "r":
        return False
    declared_type = _docstring_param_declared_type(docstring, lowered)
    if declared_type and any(marker in declared_type for marker in NUMERIC_SEQUENCE_TYPE_MARKERS):
        return False
    default = str((param_detail or {}).get("default", "") or "").strip()
    if default and re.fullmatch(r"-?\d+(?:\.\d+)?", default):
        return True
    text = str(docstring or "").lower()
    return "radius" in text or "sphere" in text


def _param_uses_integer_axis_context(param_name: str, param_detail: dict[str, Any] | None = None) -> bool:
    if str(param_name or "").lower() != "axis":
        return False
    annotation = str((param_detail or {}).get("annotation", "") or "").lower().replace("typing.", "")
    if "int" in annotation or "integer" in annotation or "supportsindex" in annotation:
        return True
    default = str((param_detail or {}).get("default", "") or "").strip()
    return bool(re.fullmatch(r"-?\d+", default))


def _docstring_suggests_array_context(docstring: str) -> bool:
    text = docstring.lower()
    return any(
        marker in text
        for marker in (
            "array",
            "array-like",
            "array_like",
            "convolution",
            "filter",
            "histogram",
            "image",
            "matrix",
            "ndarray",
            "pixel",
            "tensor",
        )
    )


def _param_is_scientific_array_input(param_name: str, docstring: str, module_imports: list[str] | None) -> bool:
    lowered = param_name.lower()
    if lowered not in SCIENTIFIC_ARRAY_PARAM_NAMES:
        return False
    imports = {str(item).split(".")[0].lower() for item in (module_imports or [])}
    return bool(imports.intersection(SCIENTIFIC_ARRAY_IMPORTS) or _docstring_suggests_array_context(docstring))


def _runtime_rejected_tool_names(analysis_result: Dict[str, Any]) -> set[str]:
    rejected = analysis_result.get("_runtime_rejected_tools", [])
    if not isinstance(rejected, list):
        return set()
    names: set[str] = set()
    for item in rejected:
        if isinstance(item, dict):
            name = str(item.get("name", "") or "")
        else:
            name = str(item or "")
        if name:
            names.add(name.lower())
    return names


def _docstring_mentions_external_file_resource(docstring: str, path_params: list[str]) -> bool:
    text = " ".join(str(docstring or "").lower().replace("_", " ").replace("-", " ").split())
    if not text:
        return False
    resource_phrases = (
        "directory containing",
        "file containing",
        "file name",
        "file path",
        "file to be read",
        "file to be hashed",
        "filename of",
        "full path",
        "from a file",
        "from file",
        "in a file",
        "name of file",
        "name of the file",
        "path like",
        "path to the",
        "path of the file",
        "path to a",
        "path to an",
        "path to surface",
        "output file",
        "source file",
        "the file to be",
        "the filename",
        "the full path",
    )
    if any(phrase in text for phrase in resource_phrases):
        return True
    if path_params and any(word in text for word in ("directory", "file", "path")):
        return True
    for param in path_params:
        param_text = str(param or "").lower().replace("_", " ")
        if param_text and param_text in text and any(word in text for word in ("directory", "file", "path")):
            return True
    return False


def _looks_external_file_resource_wrapper(
    lowered_name: str,
    name_tokens: set[str],
    params: list[str],
    detail: dict[str, Any],
) -> bool:
    docstring = str(detail.get("docstring", "") or "")
    doc_text = " ".join(docstring.lower().split())
    if _docstring_mentions_external_file_resource(docstring, params) and any(
        phrase in doc_text for phrase in ("load ", "open ", "parse ", "read ")
    ):
        return True
    if lowered_name.startswith(("get_", "load_", "open_", "parse_", "read_")) and _docstring_mentions_external_file_resource(docstring, params):
        return True
    path_params = [param for param in params if _is_path_like_param(param)]
    if not path_params:
        return False
    if len(path_params) == len(params) and not lowered_name.startswith(("open_", "read_", "normalize_")):
        return True
    lowered_params = {str(param).lower() for param in params}
    if lowered_name in {"hash_file", "is_dir", "is_file", "replacement_filename"}:
        return True
    if lowered_name == "what":
        return True
    if "open_file" in lowered_params:
        return True
    if "open" in name_tokens and _docstring_mentions_external_file_resource(docstring, path_params):
        return True
    if "make" in name_tokens and _docstring_mentions_external_file_resource(docstring, path_params):
        return True
    if name_tokens.intersection({"checksum", "digest", "hash"}):
        return True
    if lowered_name.startswith(("check_", "has_", "is_")) and name_tokens.intersection({"dir", "directory", "file", "path"}):
        return True
    if name_tokens.intersection({"replace", "replacement"}) and name_tokens.intersection({"file", "filename", "path"}):
        return True
    if (
        lowered_name.startswith(("get_", "load_", "open_", "parse_", "read_"))
        and _docstring_mentions_external_file_resource(docstring, path_params)
    ):
        return True
    return False


def _function_wrapper_score(
    name: str,
    raw_params: list | None,
    detail: dict[str, Any] | None,
    candidate_score: int | float | None,
    module_imports: list[str] | None = None,
) -> int | None:
    detail = detail if isinstance(detail, dict) else {}
    if (detail.get("has_varargs") or detail.get("has_kwargs")) and not _non_variadic_param_names(raw_params, detail):
        return None
    if detail.get("is_async"):
        return None
    if set(detail.get("risk_reasons") or []).intersection(
        {
            "unsupported_placeholder",
            "interactive_input",
            "async_function",
            "global_state_dependency",
            "background_execution",
            "dynamic_code_execution",
            "process_execution",
            "network_operation",
            "file_read",
            "file_mutation",
            "environment_mutation",
            "process_state_mutation",
            "framework_entrypoint_decorator",
            "environment_probe_name",
            "operational_tool_name",
            "opaque_runtime_parameter",
        }
    ):
        return None
    lowered_name = name.lower()
    name_tokens = _name_tokens(name)
    docstring = str(detail.get("docstring", "") or "").lower()
    if "decorator" in docstring and ("decorated" in docstring or "returns" in docstring or "return" in docstring):
        return None
    if "custom type for the argparse" in docstring or "parser.add_argument" in docstring:
        return None
    if lowered_name.startswith("get_") and "callable" in docstring and "return" in docstring:
        return None
    if lowered_name in {"raises", "if_delegate_has_method"}:
        return None
    if lowered_name.startswith("raise_"):
        return None
    if lowered_name in {"and", "not", "or", "variable"}:
        return None
    if lowered_name == "tstr":
        return None
    if str(detail.get("return_annotation", "")).strip().lower() in {"none", "nonetype"}:
        return None
    if "expr" in name_tokens:
        return None
    params = _detail_param_names(raw_params, detail)
    if len(params) > 8:
        return None
    if _looks_external_file_resource_wrapper(lowered_name, name_tokens, params, detail):
        return None
    if (
        lowered_name.startswith("get_")
        and [param.lower() for param in params] == ["line"]
        and any(phrase in docstring for phrase in ("from line", "from a line", "on the line"))
    ):
        return None

    score = int(candidate_score if candidate_score is not None else detail.get("wrapper_score", 70) or 70)
    if lowered_name in {"main", "cli", "run", "execute"}:
        return None
    if lowered_name == "init":
        return None
    if lowered_name.startswith("assert_"):
        return None
    if lowered_name.startswith("set_"):
        return None
    if lowered_name.startswith("attach_"):
        return None
    if lowered_name.startswith("update_") and name_tokens.intersection({"attribute", "attributes", "attrs"}):
        return None
    if lowered_name.startswith("ingest_") or lowered_name in {"load_dataset", "load_datasets"}:
        return None
    if lowered_name.startswith("requires_") or lowered_name.endswith("_mark"):
        return None
    if not params and lowered_name.startswith("get_") and lowered_name.endswith("_class"):
        return None
    if lowered_name.startswith("on_"):
        return None
    if lowered_name in {"load", "load_data", "load_pandas"}:
        return None
    reader_resource_params = {str(param).lower() for param in params}
    if lowered_name.startswith("read_raw") or (
        lowered_name.startswith(("open_", "read_"))
        and reader_resource_params.intersection({"binfile", "file_name", "filename", "fname"})
    ):
        return None
    name_tokens = _name_tokens(name)
    if "progress" in name_tokens or lowered_name.startswith("progress"):
        return None
    if lowered_name.startswith("mne_"):
        return None
    if not params and lowered_name.startswith("init_") and "session" in name_tokens:
        return None
    if not params and "ordering" in name_tokens and name_tokens.intersection({"halt", "restart"}):
        return None
    if not params and lowered_name.endswith("_zero"):
        return None
    if name_tokens.intersection(CLI_HELPER_NAME_PARTS):
        return None
    if "parse" in name_tokens and name_tokens.intersection(CLI_ARGUMENT_NAME_TOKENS):
        return None
    if name_tokens.intersection(EXECUTION_TOOL_NAME_PARTS):
        return None
    if name_tokens.intersection(STATEFUL_TOOL_NAME_PARTS):
        return None
    if name_tokens.intersection(CONNECTION_TOOL_NAME_PARTS):
        return None
    if "delegate" in name_tokens:
        return None
    if "safe" in name_tokens and name_tokens.intersection({"class", "classes"}):
        return None
    if name_tokens.intersection(REMOTE_LOOKUP_TOOL_TOKENS):
        return None
    if name_tokens.intersection(OUTPUT_ONLY_TOOL_TOKENS):
        return None
    if not params and lowered_name.startswith("load_"):
        return None
    if lowered_name in ENVIRONMENT_PROBE_TOOL_NAMES:
        return None
    if lowered_name in DOMAIN_SPECIFIC_HELPER_TOOL_NAMES:
        return None
    if name_tokens.intersection(ENVIRONMENT_PROBE_NAME_PARTS):
        return None
    if not params and lowered_name.startswith(("has_", "is_")):
        return None
    if lowered_name.startswith(("check_", "has_", "is_")) and name_tokens.intersection({"compiler", "cpp", "cuda", "cxx", "fortran", "gpu"}):
        return None
    if lowered_name.startswith("check_") and not params:
        return None
    if lowered_name.startswith("list_") and not params:
        return None
    if lowered_name.startswith(("warn_", "warning_")):
        return None
    if "version" in name_tokens and name_tokens.intersection({"latest", "newest"}):
        return None
    if lowered_name == "version":
        return None
    if "version" in name_tokens and "package" in {str(param).lower() for param in params}:
        return None
    if name_tokens.intersection({"extra", "extras"}) and {str(param).lower() for param in params}.intersection(
        {"groups", "exclude_extras"}
    ):
        return None
    if "package" in {str(param).lower() for param in params} and name_tokens.intersection({"dependencies", "dependency", "releases", "requirements"}):
        return None
    if "proc" in lowered_name:
        return None
    if name_tokens.intersection({"axes", "calendar", "dummy", "executor", "keylog", "keylogger", "keyboard", "listener", "log", "matplotlib", "movorder", "mpl", "pickle", "plot", "plots", "plotly", "proc", "processor", "rainbow", "simulator", "transform", "unpickle"}):
        return None
    module_import_roots = {str(item).split(".")[0].lower() for item in (module_imports or [])}
    if "search" in name_tokens and (
        module_import_roots.intersection({"http", "httpx", "requests", "urllib"})
        or "http://" in docstring
        or "https://" in docstring
    ):
        return None
    if module_import_roots.intersection({"matplotlib", "plotly"}):
        return None
    if lowered_name.startswith(("next_", "previous_")):
        score += 20
    if any(part in lowered_name for part in SIDE_EFFECT_NAME_PARTS):
        return None
    if len(lowered_name) <= 2 and params:
        return None
    if not params:
        score += 35
    elif len(params) <= 2:
        score += 10
    elif len(params) > 4:
        score -= (len(params) - 4) * 10

    lookup = _param_detail_lookup(detail)
    lowered_params = {str(param).lower() for param in params}
    if "horizon" in name_tokens and "label" in lowered_params:
        return None
    for param in params:
        param_lower = param.lower()
        param_detail = lookup.get(param, {})
        if param_lower in SAMPLE_FRIENDLY_PARAM_NAMES:
            score += 15
        if param_lower in SAMPLE_HOSTILE_PARAM_NAMES:
            score -= 45
        elif param_lower in SAMPLE_AMBIGUOUS_PARAM_NAMES:
            score -= 15
        if _is_path_like_param(param):
            score -= 25
        if param_lower == "ss" and "secondary structure" in docstring:
            return None
        uses_numeric_sequence = _param_uses_numeric_sequence_adapter(param, docstring, module_imports, param_detail)
        looks_scientific_sequence = _param_is_scientific_array_input(
            param_lower,
            docstring,
            module_imports,
        )
        uses_scientific_sequence = looks_scientific_sequence and _param_has_numeric_sequence_type_evidence(
            param_lower,
            docstring,
            param_detail,
            require_annotation=True,
        )
        uses_scalar_numeric = _param_uses_scalar_numeric_context(param, docstring, param_detail)
        uses_integer_axis = _param_uses_integer_axis_context(param, param_detail)
        param_annotation = str(param_detail.get("annotation", "") or "").strip()
        param_default = str(param_detail.get("default", "") or "").strip()
        if (
            len(param_lower) == 1
            and param_lower not in SAMPLEABLE_SINGLE_LETTER_PARAM_NAMES
            and not param_annotation
            and not param_default
            and not uses_numeric_sequence
        ):
            return None
        if _docstring_declares_complex_param(docstring, param_lower) and not (uses_numeric_sequence or uses_scientific_sequence):
            return None
        if looks_scientific_sequence and not (uses_numeric_sequence or uses_scientific_sequence):
            return None
        if (
            _param_is_complex(param, param_detail)
            and not uses_numeric_sequence
            and not uses_scalar_numeric
            and not uses_scientific_sequence
            and not uses_integer_axis
        ):
            return None

    heavy_imports = set(module_imports or []).intersection(HEAVY_MODULE_IMPORTS)
    if heavy_imports:
        score -= 25 * len(heavy_imports)

    if "private_name" in (detail.get("risk_reasons") or []):
        return None
    if name_tokens.intersection({"fetch", "retrieve"}) and any(_is_path_like_param(param) for param in params):
        return None
    return score if score >= 35 else None


def _class_wrapper_score(
    name: str,
    detail: dict[str, Any] | None,
    candidate_score: int | float | None,
    module_imports: list[str] | None = None,
) -> int | None:
    if not _truthy_env("CODE2MCP_ENABLE_CLASS_WRAPPERS", "false"):
        return None
    class_tokens = _name_tokens(name)
    if class_tokens.intersection({"auth", "credential", "credentials", "login", "password", "secret", "token"}):
        return None
    if not isinstance(detail, dict) or not detail:
        return None
    rejection_reasons = {
        "complex_constructor_parameter",
        "data_container_class",
        "data_model_class",
        "enum_class",
        "no_public_methods",
        "tuple_container_class",
        "typed_dict_class",
    }
    risk_reasons = {str(reason) for reason in detail.get("risk_reasons", []) or []}
    if risk_reasons.intersection(rejection_reasons):
        return None
    if detail.get("constructor_requires_args") or detail.get("constructor_has_varargs") or detail.get("constructor_has_kwargs"):
        return None
    constructor_param_names = {
        str(item.get("name", ""))
        for item in detail.get("constructor_parameter_details", []) or []
        if isinstance(item, dict) and item.get("name")
    }
    constructor_param_names.update(str(name) for name in detail.get("constructor_parameters", []) or [] if str(name))
    for param_name in constructor_param_names:
        decision = classify_wrapper_parameter_name(
            param_name,
            complex_param_names=COMPLEX_WRAPPER_PARAM_NAMES,
            complex_param_parts=COMPLEX_WRAPPER_PARAM_PARTS,
        )
        if decision.unsafe:
            return None
    score = int(candidate_score if candidate_score is not None else detail.get("wrapper_score", 55) or 55)
    if not detail.get("public_methods"):
        return None
    heavy_imports = set(module_imports or []).intersection(HEAVY_MODULE_IMPORTS)
    if heavy_imports:
        score -= 25 * len(heavy_imports)
    return score if score >= 45 else None


def _prune_analysis_for_generation(analysis_result: Dict[str, Any], repo_root: str, max_total: int = 12) -> Dict[str, Any]:
    llm = analysis_result.get("llm_analysis", {})
    core_modules = llm.get("core_modules", [])
    if not repo_root:
        return analysis_result
    src_dir = os.path.join(repo_root, "source")
    module_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    installed_packages = _runtime_installed_packages(analysis_result)
    local_roots = _local_import_roots(core_modules)
    runtime_rejected_tools = _runtime_rejected_tool_names(analysis_result)

    for module_index, m in enumerate(core_modules):
        if _module_is_test_support(m):
            continue
        pkg = m.get("package", "")
        conf = m.get("import_confidence", "medium")
        file_path = m.get("file_path", "")
        module_name = m.get("module", "")
        if _has_non_library_path_segment(pkg, module_name, file_path):
            continue
        missing_runtime_imports = _module_missing_runtime_imports(m, installed_packages, local_roots)
        if missing_runtime_imports:
            source_import_roots = _source_file_import_roots(src_dir, file_path)
            if not set(missing_runtime_imports).intersection(source_import_roots):
                continue
        if (not pkg and not file_path and not m.get("module")) or "tests" in pkg.lower():
            continue
        rel_pkg = pkg[7:].replace(".", os.sep) if pkg.startswith("source.") else pkg.replace(".", os.sep)
        mod_file_pkg = os.path.join(src_dir, rel_pkg + ".py")
        init_file = os.path.join(src_dir, rel_pkg, "__init__.py")
        rel_mod = (pkg + "." + module_name) if module_name and pkg else module_name or pkg
        rel_mod_path = rel_mod.replace(".", os.sep) if rel_mod else ""
        mod_file_mod = os.path.join(src_dir, rel_mod_path + ".py") if rel_mod_path else None
        file_path = m.get("file_path", "")
        mod_file_evidence = os.path.join(src_dir, file_path) if file_path else None
        target_file = None
        if mod_file_evidence and os.path.isfile(mod_file_evidence):
            target_file = mod_file_evidence
        elif mod_file_mod and os.path.isfile(mod_file_mod):
            target_file = mod_file_mod
        elif mod_file_pkg and os.path.isfile(mod_file_pkg):
            target_file = mod_file_pkg
        elif init_file and os.path.isfile(init_file):
            target_file = init_file
        if not target_file:
            continue
        try:
            with open(target_file, "r", encoding="utf-8-sig", errors="ignore") as f:
                tree = ast.parse(f.read() or "")
            runtime_call_aliases = _runtime_call_aliases(tree)
            side_effect_reasons = _module_import_side_effect_reasons(tree)
            if side_effect_reasons:
                logger.info(
                    "Skipping module with import-time side effect risk: %s (%s)",
                    target_file,
                    ", ".join(side_effect_reasons),
                )
                continue
            defs_func_nodes = {
                n.name: n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
            }
            defs_funcs = set(defs_func_nodes)
            defs_classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith("_")}
        except Exception as exc:
            logger.warning(f"Failed to parse Python source during generation pruning: {target_file}: {exc}")
            defs_func_nodes, defs_funcs, defs_classes = {}, set(), set()
            runtime_call_aliases = {}
        candidate_function_names = _module_wrapper_candidate_names(m, "function")
        candidate_class_names = _module_wrapper_candidate_names(m, "class")
        cand_funcs = [x.rstrip("*") for x in m.get("functions", []) if x and not x.startswith("_")]
        cand_classes = [x.rstrip("*") for x in m.get("classes", []) if x and not x.startswith("_")]
        if candidate_function_names is not None:
            cand_funcs = [name for name in cand_funcs if name in candidate_function_names]
        if candidate_class_names is not None:
            cand_classes = [name for name in cand_classes if name in candidate_class_names]
        inter_funcs = [
            x
            for x in cand_funcs
            if x in defs_funcs
            and "test" not in x.lower()
            and "example" not in x.lower()
            and not _function_body_is_unsupported_placeholder(defs_func_nodes[x])
            and not _function_body_is_callable_factory(defs_func_nodes[x])
            and not _function_body_returns_generator(defs_func_nodes[x])
            and not _function_body_returns_empty_default_factory(defs_func_nodes[x])
            and not _function_body_returns_empty_literal_container(defs_func_nodes[x])
            and not _has_framework_entrypoint_decorator(defs_func_nodes[x])
            and not _function_body_has_unsafe_runtime_side_effect(defs_func_nodes[x], runtime_call_aliases)
        ]
        inter_classes = [x for x in cand_classes if x in defs_classes and "test" not in x.lower() and "example" not in x.lower()]
        if not inter_funcs and not inter_classes:
            continue

        module_row = {
            "package": m.get("package", ""),
            "module": m.get("module", ""),
            "functions": [],
            "classes": [],
            "description": m.get("description", ""),
            "import_confidence": conf,
            "function_signatures": {},
            "file_path": m.get("file_path", ""),
            "imports": m.get("imports", []),
            "function_details": {},
            "class_details": {},
            "wrapper_candidates": [],
        }
        module_rows.append({"index": module_index, "source": m, "row": module_row})

        wrapper_score = {
            (str(item.get("kind", "")), str(item.get("name", ""))): item.get("score")
            for item in (m.get("wrapper_candidates", []) or [])
            if isinstance(item, dict)
        }
        function_details = m.get("function_details", {}) if isinstance(m.get("function_details", {}), dict) else {}
        class_details = m.get("class_details", {}) if isinstance(m.get("class_details", {}), dict) else {}
        func_sigs = m.get("function_signatures", {}) if isinstance(m.get("function_signatures", {}), dict) else {}
        module_imports = m.get("imports", []) if isinstance(m.get("imports", []), list) else []
        confidence_bonus = 8 if conf == "high" else 0 if conf == "medium" else -10

        for func in inter_funcs:
            if func.lower() in runtime_rejected_tools:
                continue
            detail = function_details.get(func, {}) if isinstance(function_details, dict) else {}
            score = _function_wrapper_score(
                func,
                func_sigs.get(func, []) if isinstance(func_sigs, dict) else [],
                detail,
                wrapper_score.get(("function", func)),
                module_imports,
            )
            if score is not None:
                candidate_rows.append({
                    "module_index": module_index,
                    "kind": "function",
                    "name": func,
                    "score": score + confidence_bonus,
                })

        for cls in inter_classes:
            if cls.lower() in runtime_rejected_tools:
                continue
            detail = class_details.get(cls, {}) if isinstance(class_details, dict) else {}
            score = _class_wrapper_score(cls, detail, wrapper_score.get(("class", cls)), module_imports)
            if score is not None:
                candidate_rows.append({
                    "module_index": module_index,
                    "kind": "class",
                    "name": cls,
                    "score": score + confidence_bonus,
                })

    ranked_candidates = sorted(
        candidate_rows,
        key=lambda item: (-int(item["score"]), item["module_index"], item["kind"], item["name"].lower()),
    )
    selected = []
    selected_tool_names: set[str] = set()
    modules_by_index = {item["index"]: item["source"] for item in module_rows}
    symbols_by_module: dict[int, list[str]] = {}
    for item in ranked_candidates:
        symbols_by_module.setdefault(int(item["module_index"]), []).append(str(item["name"]))
    selected_symbols_by_module: dict[int, list[str]] = {}
    runtime_check_cache: dict[tuple[int, tuple[str, ...]], tuple[bool, str]] = {}
    module_batch_runtime_cache: dict[int, tuple[bool, str]] = {}
    runtime_skipped_candidates: list[dict[str, Any]] = []
    runtime_precheck_count = 0

    def run_runtime_precheck(module_index: int, symbols: list[str]) -> tuple[bool, str]:
        nonlocal runtime_precheck_count
        module = modules_by_index.get(module_index)
        if not module:
            return True, "module metadata unavailable"
        clean_symbols = list(dict.fromkeys(str(symbol) for symbol in symbols if str(symbol)))
        key = (module_index, tuple(clean_symbols))
        if key not in runtime_check_cache:
            runtime_precheck_count += 1
            runtime_check_cache[key] = _module_runtime_symbols_available(
                analysis_result,
                repo_root,
                module,
                clean_symbols,
            )
        return runtime_check_cache[key]

    def candidate_runtime_available(module_index: int, symbol: str) -> tuple[bool, str]:
        module = modules_by_index.get(module_index)
        if not module:
            return True, "module metadata unavailable"
        if module_batch_runtime_cache.get(module_index, (False, ""))[0]:
            return module_batch_runtime_cache[module_index]
        if module_index not in module_batch_runtime_cache:
            module_batch_runtime_cache[module_index] = run_runtime_precheck(
                module_index,
                symbols_by_module.get(module_index, []),
            )
            if module_batch_runtime_cache[module_index][0]:
                return module_batch_runtime_cache[module_index]
        current_symbols = selected_symbols_by_module.get(module_index, [])
        proposed_symbols = list(dict.fromkeys([*current_symbols, symbol]))
        ok, reason = run_runtime_precheck(module_index, proposed_symbols)
        if ok or not current_symbols:
            return ok, reason

        return run_runtime_precheck(module_index, [symbol])

    for item in ranked_candidates:
        module_index = int(item["module_index"])
        tool_name = item["name"].lower()
        if tool_name in selected_tool_names:
            continue
        ok, reason = candidate_runtime_available(module_index, str(item["name"]))
        if not ok:
            module = modules_by_index.get(module_index)
            logger.info(
                "Skipping unavailable runtime symbol: %s.%s.%s (%s)",
                module.get("package", "") if module else "",
                module.get("module", "") if module else "",
                item["name"],
                reason,
            )
            if len(runtime_skipped_candidates) < 20:
                runtime_skipped_candidates.append({
                    "module": ".".join(
                        part
                        for part in [
                            str(module.get("package", "") if module else ""),
                            str(module.get("module", "") if module else ""),
                        ]
                        if part
                    ),
                    "file_path": _normalized_relative_file_path(str(module.get("file_path", "") if module else "")),
                    "kind": item["kind"],
                    "name": item["name"],
                    "reason": reason,
                })
            continue
        selected_tool_names.add(tool_name)
        selected.append(item)
        selected_symbols_by_module.setdefault(module_index, []).append(str(item["name"]))
        if len(selected) >= max_total:
            break
    selected_by_module: dict[int, list[dict[str, Any]]] = {}
    selected_rank: dict[tuple[int, str, str], int] = {}
    for rank, item in enumerate(selected):
        selected_by_module.setdefault(item["module_index"], []).append(item)
        selected_rank[(item["module_index"], item["kind"], item["name"])] = rank

    kept = []
    for module_info in module_rows:
        module_index = module_info["index"]
        selected_items = selected_by_module.get(module_index, [])
        if not selected_items:
            continue
        original = module_info["source"]
        row = module_info["row"]
        functions = [item["name"] for item in selected_items if item["kind"] == "function"]
        classes = [item["name"] for item in selected_items if item["kind"] == "class"]
        func_sigs = original.get("function_signatures", {}) if isinstance(original.get("function_signatures", {}), dict) else {}
        row["functions"] = functions
        row["classes"] = classes
        row["function_signatures"] = {name: func_sigs.get(name, []) for name in functions}
        row["function_details"] = {
            name: detail
            for name, detail in (original.get("function_details", {}) or {}).items()
            if name in functions
        }
        row["class_details"] = {
            name: detail
            for name, detail in (original.get("class_details", {}) or {}).items()
            if name in classes
        }
        row["wrapper_candidates"] = [
            {
                "name": item["name"],
                "kind": item["kind"],
                "score": item["score"],
            }
            for item in selected_items
        ]
        row["_generation_rank"] = min(
            selected_rank.get((module_index, item["kind"], item["name"]), 999999)
            for item in selected_items
        )
        kept.append(row)
    kept.sort(key=lambda row: int(row.get("_generation_rank", 999999)))
    for row in kept:
        row.pop("_generation_rank", None)

    pruned_llm = dict(llm)
    pruned_llm["core_modules"] = kept
    pruned_llm["generation_selection"] = {
        "candidate_count": len(candidate_rows),
        "selected_count": len(selected),
        "max_total": max_total,
        "runtime_precheck_count": runtime_precheck_count,
        "runtime_skipped_count": len(runtime_skipped_candidates),
        "runtime_skipped_candidates": runtime_skipped_candidates,
    }
    out = dict(analysis_result)
    out["llm_analysis"] = pruned_llm
    return out

def generate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    clear_runtime_validation(state)
    state.pop("review_decision", None)
    state.pop("fix_applied", None)
    state.pop("regeneration_prepared", None)

    repo = state.get("repository", {})
    repo_root = repo.get("local_paths", {}).get("repo_root")
    mcp_plugin_dir = repo.get("local_paths", {}).get("mcp_plugin")
    tests_mcp_dir = repo.get("local_paths", {}).get("tests_mcp")
    analysis = state.get("analysis", {})
    analysis["repository_name"] = repo.get("name", analysis.get("repository_name", "unknown"))
    analysis_for_generation = dict(analysis)
    if state.get("env"):
        analysis_for_generation["_runtime"] = {"env": state.get("env")}
    if state.get("runtime_rejected_tools"):
        analysis_for_generation["_runtime_rejected_tools"] = list(state.get("runtime_rejected_tools") or [])
    analysis_pruned = _prune_analysis_for_generation(analysis_for_generation, repo_root)
    analysis_pruned["repository_name"] = analysis["repository_name"]

    retry_count = state.get("generation_retry_count", 0)
    append_loop_event(state, "generation_started", generation_attempt=retry_count)
    previous_errors = state.get("errors", [])
    previous_run_results = state.get("previous_run_results", [])

    if retry_count > 0:
        logger.info(f"Starting {retry_count}th generation attempt, improving based on previous errors")
        retry_reason = _analyze_retry_reason(previous_errors, previous_run_results)
        state.setdefault("retry_reasons", []).append({
            "retry_count": retry_count,
            "reason": retry_reason,
            "timestamp": time.time()
        })

    if not repo_root:
        state.setdefault("errors", []).append({
            "node": "GenerateNode",
            "type": "InvalidInput",
            "message": "repo_root path missing, attempting to use default path",
            "action_taken": "continue"
        })
        repo_root = os.path.join("workspace", repo.get("name", "unknown"))
        repo["local_paths"] = repo.get("local_paths", {})
        repo["local_paths"]["repo_root"] = repo_root

    llm_analysis = analysis_pruned.get("llm_analysis", {})
    import_strategy = llm_analysis.get("import_strategy", {})
    adapter_mode = import_strategy.get("primary", "import")

    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    ensure_directory(mcp_output_dir)

    mcp_plugin_dir = os.path.join(mcp_output_dir, "mcp_plugin")
    tests_mcp_dir = os.path.join(mcp_output_dir, "tests_mcp")

    ensure_directory(mcp_plugin_dir)

    source_dir = os.path.join(repo_root, "source")
    if not _has_verified_generation_targets(analysis_pruned):
        message = "No verified public functions/classes or supported build targets were found for MCP generation"
        error_info = {
            "node": "GenerateNode",
            "type": "UnsupportedRepository",
            "severity": "high",
            "message": message,
            "details": _unsupported_generation_details(
                analysis,
                analysis_pruned,
                stage="pre_generation_target_selection",
                repo_root=repo_root,
            ),
            "action_taken": "abort_before_runtime",
        }
        state.setdefault("errors", []).append(error_info)
        for stale_name in ("mcp_service.py", "adapter.py", "main.py"):
            stale_path = os.path.join(mcp_plugin_dir, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)
        generation_error_path = os.path.join(mcp_output_dir, "generation_error.json")
        write_file(generation_error_path, json.dumps(error_info, ensure_ascii=False, indent=2) + "\n")
        workflow_summary_path = _write_generation_failure_summary(mcp_output_dir, state, error_info)
        state["plugin"] = {
            "files": {
                "mcp_output/generation_error.json": generation_error_path,
                "mcp_output/workflow_summary.json": workflow_summary_path,
            },
            "adapter_mode": adapter_mode,
            "endpoints": [],
            "mcp_dir": mcp_plugin_dir,
            "tests_dir": tests_mcp_dir,
            "main_entry": "start_mcp.py",
            "readme_path": "",
            "requirements": ["fastmcp>=0.1.0", "pydantic>=2.0.0"],
        }
        state["error"] = message
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        append_loop_event(
            state,
            "generation_no_supported_targets",
            project_type=_detect_project_type(analysis_pruned),
        )
        return state

    source_init_path = os.path.join(source_dir, "__init__.py")
    if not os.path.exists(source_init_path):
        repo_name = repo.get("name", "unknown")
        write_file(source_init_path, f"# -*- coding: utf-8 -*-\n\"\"\"\n{repo_name} Project Package Initialization File\n\"\"\"\n")

    # Dynamically ensure package __init__.py along core module import paths
    try:
        llm_analysis = analysis.get("llm_analysis", {})
        core_modules = llm_analysis.get("core_modules", [])
        def _ensure_pkg_inits(abs_dir: str):
            if not abs_dir or not abs_dir.startswith(source_dir):
                return
            parts = []
            rel = os.path.relpath(abs_dir, source_dir)
            if rel == ".":
                return
            for segment in rel.split(os.sep):
                parts.append(segment)
                cur = os.path.join(source_dir, *parts)
                if os.path.isdir(cur):
                    init_p = os.path.join(cur, "__init__.py")
                    if not os.path.exists(init_p):
                        write_file(init_p, "# -*- coding: utf-8 -*-\n")
        for m in core_modules:
            pkg = m.get("package", "") or ""
            mod = m.get("module", "") or ""
            # Normalize prefixed paths
            if pkg.startswith("source."):
                pkg = pkg[7:]
            if pkg.startswith("src."):
                pkg = pkg[4:]
            pkg_path = os.path.join(source_dir, *[p for p in pkg.split(".") if p]) if pkg else None
            if pkg_path and os.path.exists(pkg_path):
                _ensure_pkg_inits(pkg_path)
            # If module is a submodule under package
            if mod and mod not in (pkg or ""):
                mod_path = os.path.join(source_dir, *[p for p in mod.split(".") if p])
                if os.path.exists(mod_path):
                    _ensure_pkg_inits(mod_path)
    except Exception:
        # Best-effort; do not fail generation on init creation
        pass

    llm_analysis = analysis_pruned.get("llm_analysis", {})
    core_modules = llm_analysis.get("core_modules", [])

    for module in core_modules:
        package = module.get("package", "")
        if package and "src." in package:
            source_src_dir = os.path.join(source_dir, "src")
            source_src_init_path = os.path.join(source_src_dir, "__init__.py")
            if not os.path.exists(source_src_init_path):
                write_file(source_src_init_path, "# -*- coding: utf-8 -*-\n\"\"\"\nsrc Package Initialization File\n\"\"\"\n")
            break

    files = {}

    mcp_py_path = os.path.join(mcp_output_dir, "start_mcp.py")
    write_file(mcp_py_path, _generate_mcp_py())
    files["mcp_output/start_mcp.py"] = mcp_py_path

    init_path = os.path.join(mcp_plugin_dir, "__init__.py")
    write_file(init_path, "")
    files["mcp_output/mcp_plugin/__init__.py"] = init_path

    service_path = os.path.join(mcp_plugin_dir, "mcp_service.py")
    retry_info = None

    error_analysis = state.get("error_analysis", {})
    if error_analysis:
        retry_info = {
            "retry_count": retry_count,
            "reason": state.get("retry_reasons", [])[-1].get("reason", "Unknown") if state.get("retry_reasons") else "Unknown",
            "previous_errors": previous_errors,
            "previous_run_results": previous_run_results,
            "error_analysis": error_analysis,
            "fix_strategy": error_analysis.get("fix_strategy", {}),
            "specific_fixes": error_analysis.get("fix_strategy", {}).get("specific_changes", [])
        }
    elif retry_count > 0:
        retry_info = {
            "retry_count": retry_count,
            "reason": state.get("retry_reasons", [])[-1].get("reason", "Unknown") if state.get("retry_reasons") else "Unknown",
            "previous_errors": previous_errors,
            "previous_run_results": previous_run_results,
            "error_analysis": {},
            "fix_strategy": {},
            "specific_fixes": []
        }

    loop_summary = state.get("loop_summary")
    service_content = _strip_code_fences(_generate_mcp_service(analysis_pruned, retry_info, loop_summary))
    service_validation_errors = _validate_mcp_service_source(service_content, analysis_pruned)
    write_file(service_path, service_content)
    files["mcp_output/mcp_plugin/mcp_service.py"] = service_path

    if service_validation_errors:
        state.setdefault("errors", []).append({
            "node": "GenerateNode",
            "type": "GeneratedServiceValidationFailed",
            "severity": "high",
            "message": "Generated mcp_service.py failed static quality gate",
            "details": service_validation_errors,
            "action_taken": "abort_before_runtime"
        })
        state["plugin"] = {
            "files": files,
            "adapter_mode": adapter_mode,
            "endpoints": [],
            "mcp_dir": mcp_plugin_dir,
            "tests_dir": tests_mcp_dir,
            "main_entry": "start_mcp.py",
            "readme_path": "",
            "requirements": ["fastmcp>=0.1.0", "pydantic>=2.0.0"],
            "generation_quality_errors": service_validation_errors,
        }
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    adapter_path = os.path.join(mcp_plugin_dir, "adapter.py")
    if adapter_mode == "import":
        adapter_content = _generate_adapter_import(analysis_pruned, loop_summary)
    elif adapter_mode == "cli":
        adapter_content = _generate_adapter_cli(analysis_pruned, loop_summary)
    else:
        adapter_content = _generate_adapter_blackbox(analysis_pruned)

    write_file(adapter_path, _strip_code_fences(adapter_content))
    files["mcp_output/mcp_plugin/adapter.py"] = adapter_path

    main_path = os.path.join(mcp_plugin_dir, "main.py")
    main_content = '''"""
MCP Service Auto-Wrapper - Auto-generated
"""
from mcp_service import create_app

def main():
    """Main entry point"""
    app = create_app()
    return app

if __name__ == "__main__":
    app = main()
    app.run()
'''
    write_file(main_path, _strip_code_fences(main_content))
    files["mcp_output/mcp_plugin/main.py"] = main_path

    req_path = os.path.join(mcp_output_dir, "requirements.txt")
    write_file(req_path, _generate_requirements_txt(analysis, repo_root))
    files["mcp_output/requirements.txt"] = req_path

    readme_path = os.path.join(mcp_output_dir, "README_MCP.md")
    analysis["repository_name"] = repo.get("name", "unknown")
    write_file(readme_path, _generate_readme_mcp(analysis_pruned, loop_summary))
    files["mcp_output/README_MCP.md"] = readme_path

    # removed tests generation block per user request

    endpoints = []
    core_modules = llm_analysis.get("core_modules", [])
    for module in core_modules:
        functions = module.get("functions", [])
        classes = module.get("classes", [])
        endpoints.extend(functions)
        endpoints.extend([cls.lower() for cls in classes])

    if not endpoints:
        message = "No callable MCP tools remained after generation safety filtering"
        error_info = {
            "node": "GenerateNode",
            "type": "UnsupportedRepository",
            "severity": "high",
            "message": message,
            "details": _unsupported_generation_details(
                analysis,
                analysis_pruned,
                stage="post_generation_safety_validation",
                repo_root=repo_root,
            ),
            "action_taken": "abort_before_runtime",
        }
        state.setdefault("errors", []).append(error_info)
        for stale_name in ("mcp_service.py", "adapter.py", "main.py"):
            stale_path = os.path.join(mcp_plugin_dir, stale_name)
            if os.path.isfile(stale_path):
                os.remove(stale_path)
        generation_error_path = os.path.join(mcp_output_dir, "generation_error.json")
        write_file(generation_error_path, json.dumps(error_info, ensure_ascii=False, indent=2) + "\n")
        files["mcp_output/generation_error.json"] = generation_error_path
        files["mcp_output/workflow_summary.json"] = _write_generation_failure_summary(mcp_output_dir, state, error_info)
        state["plugin"] = {
            "files": files,
            "adapter_mode": adapter_mode,
            "endpoints": [],
            "mcp_dir": mcp_plugin_dir,
            "tests_dir": tests_mcp_dir,
            "main_entry": "start_mcp.py",
            "readme_path": readme_path,
            "requirements": ["fastmcp>=0.1.0", "pydantic>=2.0.0"],
        }
        state["error"] = message
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        append_loop_event(
            state,
            "generation_no_callable_tools",
            project_type=_detect_project_type(analysis_pruned),
        )
        return state

    state["plugin"] = {
        "files": files,
        "adapter_mode": adapter_mode,
        "endpoints": endpoints,
        "mcp_dir": mcp_plugin_dir,
        "tests_dir": tests_mcp_dir,
        "main_entry": "start_mcp.py",
        "readme_path": readme_path,
        "requirements": ["fastmcp>=0.1.0", "pydantic>=2.0.0"]
    }
    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state
