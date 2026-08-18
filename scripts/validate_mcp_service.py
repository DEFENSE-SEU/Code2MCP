from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.security.tool_policy import (
    classify_auto_call_parameter,
    classify_auto_call_tool_name,
    looks_resource_parameter,
    name_tokens,
)
from src.utils import redact_sensitive_data, redact_sensitive_text

COMPLEX_PARAM_NAMES = {
    "all_lines",
    "annotation",
    "annotations",
    "action",
    "ar",
    "arg_list",
    "arg_names",
    "array",
    "attribute_variants",
    "ax",
    "axes",
    "axis",
    "bench",
    "block",
    "calibration",
    "categorical_dtypes",
    "chunk",
    "chunks",
    "cdf",
    "cgi",
    "client",
    "cmap",
    "column",
    "columns",
    "cols",
    "collection",
    "component",
    "components",
    "coefficient",
    "comparator",
    "condition",
    "connection",
    "cosmo",
    "cursor",
    "csd",
    "cv",
    "data",
    "database",
    "dataframe",
    "dataset",
    "datasets",
    "db",
    "dicts",
    "delta",
    "declim",
    "decls",
    "decl_map",
    "dist",
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
    "endog",
    "element",
    "elements",
    "epoch",
    "epochs",
    "entrypoints",
    "expr",
    "expression",
    "expressions",
    "estimator",
    "evoked",
    "executor",
    "exog",
    "factors",
    "fhandle",
    "fid",
    "fig",
    "filters",
    "fn",
    "footprint",
    "form",
    "frame",
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
    "image",
    "img",
    "indices",
    "info",
    "info_bin",
    "info_py",
    "integral",
    "integrals",
    "insts",
    "iter",
    "li",
    "logl",
    "lt",
    "ma",
    "mask",
    "matrix",
    "meta",
    "metadata",
    "model",
    "molecule",
    "molecules",
    "molecule_store",
    "namespace",
    "network",
    "node",
    "nodes",
    "notes_to_add",
    "obj",
    "object",
    "paral",
    "parser",
    "payload",
    "prob",
    "probs",
    "ralim",
    "random_state",
    "random_state_children",
    "random_state_parent",
    "position",
    "positions",
    "pred",
    "proc",
    "processor",
    "record",
    "records",
    "res",
    "resid",
    "requirement",
    "requirements",
    "result",
    "results",
    "rng",
    "row",
    "rows",
    "scores",
    "series",
    "session",
    "shape",
    "source",
    "splits",
    "src",
    "stock",
    "stream",
    "stc",
    "stc1",
    "stc2",
    "stc_est",
    "stc_true",
    "supplementary_lines",
    "table",
    "tables",
    "task",
    "tasks",
    "template",
    "timedelta",
    "tz",
    "tzinfo",
    "tree",
    "url",
    "v",
    "x1",
    "x2",
    "xdrdata",
    "ys",
}
COMPLEX_PARAM_PARTS = {
    "baseurl",
    "collection",
    "connection",
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
    "timedelta",
    "timezone",
    "tzinfo",
    "url",
}
SIGNAL_ARRAY_PARAM_NAMES = {
    "amplitude",
    "ecg",
    "ecg_cleaned",
    "eda",
    "eda_cleaned",
    "eeg",
    "emg",
    "emg_cleaned",
    "eog",
    "eog_cleaned",
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
}
SEMANTIC_POLICIES = {"none", "any", "all"}
SAMPLE_STRUCTURED_PARAM_NAMES = {
    "aggregated_contributions",
    "contrib_dict",
    "grant_contributions",
    "grant_contribs_curr",
    "grants_data",
    "gene_id_mapping",
    "id_mapping",
    "pair_totals",
}
SAMPLE_NUMERIC_SEQUENCE_PARAM_NAMES = {
    "b",
    "benchmark_rets",
    "factor_returns",
    "is_returns",
    "r",
    "returns",
    "underwater",
}


def _json_loads(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {label}: {exc}") from exc


def _path_parts(path: Path) -> set[str]:
    return {part.lower() for part in path.parts}


def _is_generated_plugin_path(path: Path) -> bool:
    parts = _path_parts(path)
    return "mcp_output" in parts and "mcp_plugin" in parts


def _is_generated_source_path(path: Path) -> bool:
    parts = _path_parts(path)
    if "source" not in parts:
        return False

    workspace_root = (PROJECT_ROOT / "workspace").resolve()
    try:
        path.relative_to(workspace_root)
        return True
    except ValueError:
        pass

    for candidate in (path, *path.parents):
        if candidate.name.lower() != "source":
            continue
        try:
            if (candidate.parent / "mcp_output").exists():
                return True
        except OSError:
            continue
    return False


def _is_generated_import_path(value: str, plugin_dir: Path) -> bool:
    try:
        path = Path(value).resolve()
    except Exception:
        return False
    return path == plugin_dir or _is_generated_plugin_path(path) or _is_generated_source_path(path)


def _is_generated_plugin_module(module: Any) -> bool:
    if getattr(module, "__code2mcp_source_subset__", False) or getattr(module, "__code2mcp_namespace__", False):
        return True
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        path = Path(module_file).resolve()
    except Exception:
        return False
    if _is_generated_plugin_path(path) or _is_generated_source_path(path):
        return True
    return False


def _prepare_plugin_import(plugin_dir: Path) -> None:
    plugin_dir = plugin_dir.resolve()
    stale_modules = [
        name
        for name, module in list(sys.modules.items())
        if name == "mcp_service"
        or name.startswith("_code2mcp_")
        or _is_generated_plugin_module(module)
    ]
    for name in stale_modules:
        sys.modules.pop(name, None)
    sys.path[:] = [item for item in sys.path if not _is_generated_import_path(item, plugin_dir)]
    sys.path.insert(0, str(plugin_dir))


def load_create_app_from_plugin(plugin_dir: Path):
    _prepare_plugin_import(plugin_dir)
    from mcp_service import create_app  # type: ignore

    return create_app


def _result_to_jsonable(result: Any) -> dict[str, Any]:
    data = getattr(result, "data", None)
    structured = getattr(result, "structured_content", None)
    is_error = bool(getattr(result, "is_error", False))
    if data is not None:
        return {
            "is_error": is_error,
            "data": data,
            "semantic_success": _semantic_success(data),
            "semantic_evidence": _semantic_evidence(data),
        }
    if structured is not None:
        return {
            "is_error": is_error,
            "data": structured,
            "semantic_success": _semantic_success(structured),
            "semantic_evidence": _semantic_evidence(structured),
        }
    text_result = str(result)
    return {
        "is_error": is_error,
        "data": text_result,
        "semantic_success": _semantic_success(text_result),
        "semantic_evidence": _semantic_evidence(text_result),
    }


def _semantic_success(data: Any) -> bool | None:
    if isinstance(data, dict) and isinstance(data.get("success"), bool):
        return bool(data["success"])
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return _semantic_success(parsed)
        except json.JSONDecodeError:
            pass
        match = re.search(r"[\"']success[\"']\s*:\s*(true|false|True|False)", data)
        if match:
            return match.group(1).lower() == "true"
    return None


def _meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _semantic_evidence(data: Any) -> bool | None:
    if isinstance(data, dict) and isinstance(data.get("success"), bool):
        if data["success"] is False:
            return False
        if data.get("error"):
            return False
        if "result" in data:
            return _meaningful_value(data.get("result"))
        for key in ("data", "value", "items", "output"):
            if key in data:
                return _meaningful_value(data.get(key))
        return False
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return _semantic_evidence(parsed)
        except json.JSONDecodeError:
            pass
        success = _semantic_success(data)
        if success is False:
            return False
        if success is True:
            null_result = re.search(r"[\"']result[\"']\s*:\s*(null|None)", data)
            empty_result = re.search(r"[\"']result[\"']\s*:\s*(?:[\"']\s*[\"']|\[\s*\]|\{\s*\})", data)
            has_result = re.search(r"[\"']result[\"']\s*:", data)
            return bool(has_result and not null_result and not empty_result)
    return None


def _schema_type(schema: dict[str, Any]) -> str:
    if "type" in schema and isinstance(schema["type"], str):
        return schema["type"]
    for item in schema.get("anyOf", []) or schema.get("oneOf", []) or []:
        if isinstance(item, dict) and item.get("type") != "null":
            return str(item.get("type", "string"))
    return "string"


def _name_tokens(name: str) -> set[str]:
    return name_tokens(name)


def _has_detailed_object_schema(schema: dict[str, Any]) -> bool:
    return isinstance(schema.get("properties"), dict) and bool(schema["properties"])


def _is_complex_auto_param(param_name: str, schema: dict[str, Any]) -> tuple[bool, str]:
    decision = classify_auto_call_parameter(
        param_name,
        schema_type=_schema_type(schema),
        has_detailed_object_schema=_has_detailed_object_schema(schema),
        sample_structured_param_names=SAMPLE_STRUCTURED_PARAM_NAMES,
        complex_param_names=COMPLEX_PARAM_NAMES,
        complex_param_parts=COMPLEX_PARAM_PARTS,
        signal_array_param_names=SIGNAL_ARRAY_PARAM_NAMES,
    )
    return decision.unsafe, decision.reason


def _sample_value(name: str, schema: dict[str, Any]) -> Any:
    lowered = name.lower()
    schema_type = _schema_type(schema)
    if "default" in schema:
        default = schema["default"]
        numeric_placeholder = (
            schema_type in {"integer", "number", "float"}
            and default in (0, 0.0, "0", "0.0")
            and lowered in {
                "count",
                "d",
                "dimensions",
                "dpi",
                "fontsize",
                "half_nbw",
                "i",
                "k",
                "kmax",
                "m",
                "n",
                "nbytes",
                "n_sample",
                "n_samples",
                "nm",
                "nom_max",
                "nom_opt",
                "num_samples",
                "num",
                "number",
                "nx",
                "ny",
                "radius",
                "size",
                "threshold",
                "limit",
                "unit_size",
                "virtual_offset",
                "wsize",
                "z1",
                "z2",
                "z3",
            }
        )
        if default not in ("", None) and not numeric_placeholder:
            return default

    if looks_resource_parameter(name):
        return ""
    if lowered == "grant_contributions":
        return [["grant_a", "user_a", 10.0], ["grant_a", "user_b", 20.0], ["grant_b", "user_a", 5.0]]
    if lowered in {"contrib_dict", "aggregated_contributions"}:
        return {"grant_a": {"user_a": 10.0, "user_b": 20.0}, "grant_b": {"user_a": 5.0}}
    if lowered in {"gene_id_mapping", "id_mapping"} or lowered.endswith("_mapping"):
        return {"gene_a": "gene_b", "gene_c": "gene_d"}
    if lowered == "pair_totals":
        return {"user_a": {"user_a": 15.0, "user_b": 14.14}, "user_b": {"user_a": 14.14, "user_b": 20.0}}
    if lowered in {"grants_data", "grant_contribs_curr"}:
        return [
            {"id": "grant_a", "contributions": [{"user_a": 10.0}, {"user_b": 20.0}]},
            {"id": "grant_b", "contributions": [{"user_a": 5.0}]},
        ]
    if "date" in lowered:
        return "2024-01-01"
    if lowered in {"city", "location", "place"}:
        return "London"
    if "time" in lowered:
        return 60 if schema_type in {"integer", "number", "float"} else "60"
    if lowered in {"xml", "xmlstring", "xml_string"}:
        return "<root>test</root>"
    if lowered in {"formula", "chemical_formula", "molecular_formula"}:
        return "H2O"
    if lowered == "cov_type":
        return "HC1"
    if lowered in {"criterion", "information_criterion"}:
        return "aic"
    if lowered == "misc":
        return "SpaceAfter=No"
    if lowered == "norm":
        return "approximate"
    if lowered == "decl_code":
        return "real(kind=dp), dimension(:, :)"
    if lowered == "half_nbw":
        return 2.5 if schema_type in {"number", "float"} else "2.5"
    if lowered in {"alpha", "beta", "gamma", "rho", "theta"}:
        return 1.0 if schema_type in {"integer", "number", "float"} else "1.0"
    if lowered == "color":
        return "red"
    if lowered == "code":
        return "A"
    if lowered == "field" and schema_type == "array":
        return [1.11, 2.22]
    if lowered in SAMPLE_NUMERIC_SEQUENCE_PARAM_NAMES and schema_type == "array":
        return [0.01, -0.02, 0.015, 0.005, 0.012]
    if lowered in {"counts", "values", "numbers", "observations", "samples", "xs"} and schema_type == "array":
        return [1, 2, 3]
    if lowered in {"n_sample", "n_samples", "num_samples"}:
        if schema_type == "integer":
            return 10
        if schema_type in {"number", "float"}:
            return 10.0
        return "10"
    if lowered in {
        "count",
        "d",
        "dimensions",
        "dpi",
        "fontsize",
        "i",
        "k",
        "kmax",
        "m",
        "n",
        "nbytes",
        "n_sample",
        "n_samples",
        "nm",
        "nom_max",
        "nom_opt",
        "num_samples",
        "num",
        "number",
        "nx",
        "ny",
        "radius",
        "size",
        "threshold",
        "limit",
        "unit_size",
        "virtual_offset",
        "wsize",
        "z1",
        "z2",
        "z3",
    }:
        if schema_type == "integer":
            return 10 if lowered == "n" else 3
        if schema_type in {"number", "float"}:
            if lowered == "threshold":
                return 0.1
            if lowered == "nom_max":
                return 25.0
            if lowered == "nom_opt":
                return 7.0
            if lowered == "unit_size":
                return 5.0
            return 3.0
        return "3"
    if lowered in {"text", "sentence", "query", "prompt", "locale"}:
        return "test"
    if lowered == "verbose":
        return "INFO"
    if lowered in {"items", "values", "list"} and schema_type == "array":
        return ["one", "two", "three"]
    if lowered in {"ii", "sh"} and schema_type == "array":
        return [1, 2]
    if lowered == "strides" and schema_type == "array":
        return [3, 1]

    if schema_type in {"number", "float"}:
        return 1536.0 if lowered in {"value", "size", "bytes"} else 1.0
    if schema_type == "integer":
        return 1
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        return ["one", "two", "three"]
    if schema_type == "object":
        if _has_detailed_object_schema(schema):
            return {
                prop_name: _sample_value(prop_name, prop if isinstance(prop, dict) else {})
                for prop_name, prop in schema["properties"].items()
            }
        return {}
    return "test"


def _sample_value_for_tool(tool_name: str, name: str, schema: dict[str, Any]) -> Any:
    lowered_name = name.lower()
    tool_tokens = _name_tokens(tool_name)
    if lowered_name == "order" and {"seasonal", "order"}.issubset(tool_tokens):
        return [0, 0, 0, 1]
    if lowered_name == "value" and {"parse", "latitude"}.issubset(tool_tokens):
        return "N10"
    if lowered_name == "value" and {"parse", "longitude"}.issubset(tool_tokens):
        return "N10W010"
    if lowered_name == "s" and tool_name in {"split_outside_parens"}:
        return "a(:,:), b, c(:)"
    if lowered_name in {"name", "q", "query"} and tool_tokens.intersection({"city", "cities", "geocode", "geonames"}):
        return "London"
    schema_type = _schema_type(schema)
    param_tokens = _name_tokens(name)
    if (
        schema_type == "array"
        and tool_tokens.intersection({"time", "timeseries", "series", "secs", "seconds"})
        and (
            lowered_name in {"ts_list", "time_list", "times", "timestamps"}
            or param_tokens.intersection({"time", "times", "timestamp", "timestamps"})
        )
    ):
        return ["2015-01-01T00:00:00Z", "2015-01-01T03:00:00Z"]
    return _sample_value(name, schema)


def _alternate_numeric_sample_values(
    tool_name: str,
    param_name: str,
    schema: dict[str, Any],
    current_value: Any,
) -> list[Any]:
    schema_type = _schema_type(schema)
    if schema_type not in {"integer", "number", "float"}:
        return []

    lowered_name = param_name.lower()
    tool_tokens = _name_tokens(tool_name)
    if "fermat" in tool_tokens and lowered_name == "n":
        candidates: list[Any] = [3, 5, 15, 17]
    elif lowered_name in {
        "count",
        "d",
        "dimensions",
        "i",
        "k",
        "m",
        "n",
        "num",
        "number",
        "size",
        "value",
    }:
        candidates = [3, 5, 10, 2, 1]
    else:
        candidates = [1, 2, 3]

    if schema_type in {"number", "float"}:
        candidates = [float(value) for value in candidates]
    unique: list[Any] = []
    for value in candidates:
        if value == current_value or value in unique:
            continue
        unique.append(value)
    return unique


def _alternate_auto_call_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    properties: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return conservative alternate samples after a safe auto-call has no evidence."""
    alternates: list[dict[str, Any]] = []
    for name, schema in properties.items():
        prop_schema = schema if isinstance(schema, dict) else {}
        for value in _alternate_numeric_sample_values(tool_name, name, prop_schema, arguments.get(name)):
            retry_args = dict(arguments)
            retry_args[name] = value
            alternates.append(retry_args)
    return alternates[:4]


def _is_risky_auto_call(tool: Any) -> tuple[bool, str]:
    name = str(getattr(tool, "name", "")).lower()
    schema = getattr(tool, "inputSchema", {}) or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    decision = classify_auto_call_tool_name(name, properties=properties)
    if decision.unsafe:
        return True, decision.reason
    for param_name in properties:
        schema = properties[param_name] if isinstance(properties[param_name], dict) else {}
        complex_param, reason = _is_complex_auto_param(param_name, schema)
        if complex_param:
            return True, reason
    return False, ""


def _auto_calls_from_tools(
    tools: list[Any],
    max_calls: int,
    *,
    include_risky: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for tool in tools:
        risky, reason = _is_risky_auto_call(tool)
        if risky and not include_risky:
            skipped.append({"tool": tool.name, "reason": reason})
            continue
        if max_calls >= 0 and len(calls) >= max_calls:
            break
        schema = getattr(tool, "inputSchema", {}) or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        arguments = {
            name: _sample_value_for_tool(tool.name, name, prop if isinstance(prop, dict) else {})
            for name, prop in properties.items()
        }
        calls.append({"tool": tool.name, "arguments": arguments, "auto": True})
    return calls, skipped


def _transport_ok_for_policy(calls: list[dict[str, Any]], semantic_policy: str) -> bool:
    has_semantic_success = any(call.get("semantic_success") is True for call in calls)
    for call in calls:
        transport_passed = call.get("transport_passed", call.get("passed", False))
        if transport_passed:
            continue
        if semantic_policy == "any" and call.get("auto") and has_semantic_success:
            continue
        return False
    return True


def _semantic_errors_for_policy(
    calls: list[dict[str, Any]],
    semantic_policy: str,
    *,
    require_semantic_success: bool = False,
    require_semantic_evidence: bool = False,
) -> list[str]:
    semantic_values = [call.get("semantic_success") for call in calls]
    if require_semantic_success and True not in semantic_values:
        return ["No tool call returned semantic success"]
    if require_semantic_evidence and True not in [call.get("semantic_evidence") for call in calls]:
        return ["No tool call returned meaningful semantic evidence"]
    if require_semantic_evidence and semantic_policy == "all":
        missing_evidence = [
            str(call.get("tool") or "<unknown>")
            for call in calls
            if call.get("semantic_success") is True and call.get("semantic_evidence") is not True
        ]
        if missing_evidence:
            return [
                "Tool calls with success=true but no meaningful semantic evidence: "
                + ", ".join(missing_evidence)
            ]
    if semantic_policy == "any" and calls and True not in semantic_values:
        return ["No tool call returned semantic success"]
    if semantic_policy == "all" and calls and False in semantic_values:
        return ["At least one tool call returned success=false"]
    return []


def _parse_calls(args: argparse.Namespace) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for file_name in args.call_file or []:
        path = Path(file_name)
        item = _json_loads(path.read_text(encoding="utf-8-sig"), f"--call-file {path}")
        items = item if isinstance(item, list) else [item]
        for entry in items:
            if not isinstance(entry, dict) or not entry.get("tool"):
                raise SystemExit("--call-file entries must be JSON objects with a 'tool' field")
            arguments = entry.get("arguments", {})
            if not isinstance(arguments, dict):
                raise SystemExit("--call-file entry arguments must be JSON objects")
            calls.append({"tool": str(entry["tool"]), "arguments": arguments})

    for raw in args.call or []:
        item = _json_loads(raw, "--call")
        if not isinstance(item, dict) or not item.get("tool"):
            raise SystemExit("--call must be a JSON object with a 'tool' field")
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            raise SystemExit("--call.arguments must be a JSON object")
        calls.append({"tool": str(item["tool"]), "arguments": arguments})

    if args.tool:
        arguments = _json_loads(args.arguments or "{}", "--arguments")
        if not isinstance(arguments, dict):
            raise SystemExit("--arguments must be a JSON object")
        calls.append({"tool": args.tool, "arguments": arguments})
    return calls


def _base_report(
    repo_root: Path,
    plugin_dir: Path,
    *,
    semantic_policy: str,
    require_semantic_success: bool,
    require_meaningful_result: bool,
    allow_zero_tools: bool,
) -> dict[str, Any]:
    return {
        "passed": False,
        "repo_root": str(repo_root),
        "plugin_dir": str(plugin_dir),
        "tool_count": 0,
        "tools": [],
        "calls": [],
        "skipped_auto_calls": [],
        "semantic_policy": semantic_policy,
        "require_semantic_success": require_semantic_success,
        "require_meaningful_result": require_meaningful_result,
        "zero_tools_allowed": allow_zero_tools,
        "errors": [],
        "warnings": [],
    }


def _validation_error(prefix: str, exc: Exception) -> str:
    message = redact_sensitive_text(str(exc)).strip()
    if message:
        return f"{prefix} ({type(exc).__name__}): {message}"
    return f"{prefix} ({type(exc).__name__})"


async def _validate(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    if not plugin_dir.is_dir():
        raise SystemExit(f"MCP plugin directory not found: {plugin_dir}")

    semantic_policy = str(getattr(args, "semantic_policy", "none") or "none").lower()
    require_semantic_success = bool(getattr(args, "require_semantic_success", False))
    require_meaningful_result = bool(getattr(args, "require_meaningful_result", False))
    allow_zero_tools = bool(getattr(args, "allow_zero_tools", False))
    if semantic_policy not in SEMANTIC_POLICIES:
        raise SystemExit(f"Invalid semantic policy: {semantic_policy}")

    report = _base_report(
        repo_root,
        plugin_dir,
        semantic_policy=semantic_policy,
        require_semantic_success=require_semantic_success,
        require_meaningful_result=require_meaningful_result,
        allow_zero_tools=allow_zero_tools,
    )

    try:
        from fastmcp import Client  # type: ignore
    except ModuleNotFoundError as exc:
        if exc.name != "fastmcp":
            raise
        report["errors"].append(
            "FastMCP validation dependency is not installed in this Python environment. "
            "Install fastmcp or run this validator with the generated service environment."
        )
        return report

    try:
        create_app = load_create_app_from_plugin(plugin_dir)
    except Exception as exc:
        report["errors"].append(_validation_error("Unable to import generated MCP service", exc))
        return report

    try:
        app = create_app()
    except Exception as exc:
        report["errors"].append(_validation_error("Generated MCP service create_app() failed", exc))
        return report

    async with contextlib.AsyncExitStack() as stack:
        try:
            client = await stack.enter_async_context(Client(app))
        except Exception as exc:
            report["errors"].append(_validation_error("FastMCP client session failed", exc))
            return report

        try:
            tools = await client.list_tools()
        except Exception as exc:
            report["errors"].append(_validation_error("FastMCP list_tools() failed", exc))
            return report
        tool_names = [tool.name for tool in tools]
        tools_by_name = {tool.name: tool for tool in tools}
        report["tool_count"] = len(tool_names)
        report["tools"] = tool_names

        if not tool_names:
            if allow_zero_tools:
                report["warnings"].append(
                    "FastMCP app registered zero tools; --allow-zero-tools records diagnostics only and does not satisfy validation"
                )
            report["errors"].append("FastMCP app registered zero tools; validation requires at least one registered tool")
        elif len(tool_names) < args.min_tools:
            report["errors"].append(f"Expected at least {args.min_tools} tools, found {len(tool_names)}")

        calls = _parse_calls(args)
        if args.auto_call:
            auto_calls, skipped = _auto_calls_from_tools(
                tools,
                args.max_calls,
                include_risky=args.include_risky_auto_calls,
            )
            calls.extend(auto_calls)
            report["skipped_auto_calls"] = skipped

        for call in calls:
            tool_name = call["tool"]
            auto_call = bool(call.get("auto"))
            risk_override = False
            risk_reason = ""
            if not auto_call and tool_name in tools_by_name:
                risk_override, risk_reason = _is_risky_auto_call(tools_by_name[tool_name])
            call_report = {
                "tool": tool_name,
                "arguments": call["arguments"],
                "auto": auto_call,
                "passed": False,
            }
            if risk_override:
                call_report["risk_override"] = True
                call_report["risk_reason"] = risk_reason
                report["warnings"].append(
                    f"Explicit call to risky tool '{tool_name}' bypassed auto-call safety policy: {risk_reason}"
                )
            try:
                result = await client.call_tool(tool_name, call["arguments"])
                parsed = _result_to_jsonable(result)
                if (
                    auto_call
                    and parsed.get("semantic_success") is True
                    and parsed.get("semantic_evidence") is not True
                    and tool_name in tools_by_name
                ):
                    schema = getattr(tools_by_name[tool_name], "inputSchema", {}) or {}
                    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
                    sample_retries = [
                        {
                            "arguments": call["arguments"],
                            "semantic_success": parsed.get("semantic_success"),
                            "semantic_evidence": parsed.get("semantic_evidence"),
                            "transport_passed": not parsed.get("is_error", False),
                        }
                    ]
                    for retry_arguments in _alternate_auto_call_arguments(tool_name, call["arguments"], properties):
                        try:
                            retry_result = await client.call_tool(tool_name, retry_arguments)
                            retry_parsed = _result_to_jsonable(retry_result)
                        except Exception as retry_exc:
                            sample_retries.append(
                                {
                                    "arguments": retry_arguments,
                                    "error": redact_sensitive_text(str(retry_exc)),
                                }
                            )
                            continue
                        retry_transport_passed = not retry_parsed.get("is_error", False)
                        sample_retries.append(
                            {
                                "arguments": retry_arguments,
                                "semantic_success": retry_parsed.get("semantic_success"),
                                "semantic_evidence": retry_parsed.get("semantic_evidence"),
                                "transport_passed": retry_transport_passed,
                            }
                        )
                        if (
                            retry_transport_passed
                            and retry_parsed.get("semantic_success") is True
                            and retry_parsed.get("semantic_evidence") is True
                        ):
                            call_report["arguments"] = retry_arguments
                            parsed = retry_parsed
                            break
                    if len(sample_retries) > 1:
                        call_report["sample_retries"] = sample_retries
                call_report.update(parsed)
                transport_passed = not parsed.get("is_error", False)
                call_report["transport_passed"] = transport_passed
                call_report["passed"] = transport_passed
                if parsed.get("semantic_success") is False:
                    message = f"{tool_name} returned success=false"
                    if semantic_policy == "all":
                        call_report["passed"] = False
                        report["errors"].append(message)
                    else:
                        report["warnings"].append(message)
                if parsed.get("semantic_success") is True:
                    call_report["semantic_passed"] = True
                elif parsed.get("semantic_success") is False:
                    call_report["semantic_passed"] = False
                else:
                    call_report["semantic_passed"] = None
                call_report["semantic_evidence"] = parsed.get("semantic_evidence")
            except Exception as exc:
                redacted_error = redact_sensitive_text(str(exc))
                call_report["error"] = redacted_error
                call_report["transport_passed"] = False
                call_report["semantic_passed"] = None
                call_report["semantic_evidence"] = None
                message = f"{tool_name} failed: {redacted_error}"
                if call.get("auto") and semantic_policy == "any":
                    report["warnings"].append(message)
                else:
                    report["errors"].append(message)
            report["calls"].append(call_report)

    if args.require_call and not report["calls"]:
        report["errors"].append("No tool calls were executed")

    transport_ok = _transport_ok_for_policy(report["calls"], semantic_policy)
    for error in _semantic_errors_for_policy(
        report["calls"],
        semantic_policy,
        require_semantic_success=require_semantic_success,
        require_semantic_evidence=require_meaningful_result,
    ):
        if error == "At least one tool call returned success=false" and any("returned success=false" in existing for existing in report["errors"]):
            continue
        report["errors"].append(error)

    report["passed"] = not report["errors"] and transport_ok
    return report


def _run_with_captured_stdout(async_fn: Any, args: argparse.Namespace) -> dict[str, Any]:
    stdout_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer):
        report = asyncio.run(async_fn(args))
    noisy_stdout = stdout_buffer.getvalue()
    if noisy_stdout:
        redacted = redact_sensitive_text(noisy_stdout)
        print(redacted, file=sys.stderr, end="" if redacted.endswith("\n") else "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a generated Code2MCP service with a real FastMCP client.")
    parser.add_argument("--repo-root", required=True, help="Workspace repo root, e.g. workspace/humanize")
    parser.add_argument("--min-tools", type=int, default=1, help="Minimum registered tool count")
    parser.add_argument("--tool", help="Tool name to call")
    parser.add_argument("--arguments", default="{}", help="JSON object passed to --tool")
    parser.add_argument("--call", action="append", help="JSON object: {'tool': name, 'arguments': {...}}")
    parser.add_argument("--call-file", action="append", help="Path to a JSON call object or list of call objects")
    parser.add_argument("--auto-call", action="store_true", help="Generate sample arguments from tool schemas and call tools")
    parser.add_argument("--max-calls", type=int, default=-1, help="Maximum auto-generated tool calls; use -1 for all safely sampleable tools")
    parser.add_argument("--include-risky-auto-calls", action="store_true", help="Include tools with path/file/network/stateful names in auto-call mode")
    parser.add_argument("--allow-zero-tools", action="store_true", help="Record diagnostics for a service with zero registered tools; validation still requires tool-call evidence")
    parser.add_argument("--require-call", action="store_true", help="Fail if no explicit or auto-generated calls were executed")
    parser.add_argument("--require-semantic-success", action="store_true", help="Fail unless at least one called tool returns {'success': true}")
    parser.add_argument(
        "--require-meaningful-result",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fail unless at least one successful tool call returns a non-empty result payload",
    )
    parser.add_argument(
        "--semantic-policy",
        choices=sorted(SEMANTIC_POLICIES),
        default="none",
        help="Semantic validation policy: none=transport only, any=require at least one success=true call, all=fail any success=false call",
    )
    args = parser.parse_args()

    report = _run_with_captured_stdout(_validate, args)
    print(json.dumps(redact_sensitive_data(report), ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
