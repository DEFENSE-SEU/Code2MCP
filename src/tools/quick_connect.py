from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from ..security.tool_policy import classify_auto_call_parameter, classify_auto_call_tool_name, name_tokens
from ..utils import redact_sensitive_data, redact_sensitive_text


class QuickConnectError(RuntimeError):
    """Raised when a generated MCP service cannot be connected safely."""


def _server_name(value: str | None, fallback: str) -> str:
    raw = (value or fallback or "code2mcp-service").strip()
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")
    return name[:80] or "code2mcp-service"


def _jsonable_path(path: Path) -> str:
    return str(path.resolve())


def _read_env_info(repo_root: Path) -> dict[str, Any]:
    env_path = repo_root / "mcp_output" / "env_info.json"
    if not env_path.exists():
        return {}
    try:
        return json.loads(env_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _python_from_env_info(repo_root: Path) -> str | None:
    env_info = _read_env_info(repo_root)
    environment = env_info.get("environment", env_info) if isinstance(env_info, dict) else {}
    exec_prefix = environment.get("exec_prefix") if isinstance(environment, dict) else None
    if isinstance(exec_prefix, list):
        for item in exec_prefix:
            candidate = Path(str(item)).expanduser()
            if candidate.is_file():
                return _jsonable_path(candidate)
    return None


def find_local_python(repo_root: str | Path, explicit: str | None = None) -> str:
    if explicit:
        return str(Path(explicit).expanduser())

    root = Path(repo_root).resolve()
    env_python = _python_from_env_info(root)
    if env_python:
        return env_python

    candidates = [
        root / "mcp_output" / ".venv" / "Scripts" / "python.exe",
        root / "mcp_output" / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return _jsonable_path(candidate)
    return sys.executable or "python"


def _read_summary(repo_root: Path) -> dict[str, Any]:
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _read_generation_error(repo_root: Path) -> dict[str, Any]:
    error_path = repo_root / "mcp_output" / "generation_error.json"
    if not error_path.exists():
        return {}
    try:
        data = json.loads(error_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_run_log(repo_root: Path) -> dict[str, Any]:
    run_log_path = repo_root / "mcp_output" / "mcp_logs" / "run_log.json"
    if not run_log_path.exists():
        return {}
    try:
        data = json.loads(run_log_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _newer_generation_error_invalidates_summary(repo_root: Path) -> bool:
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    error_path = repo_root / "mcp_output" / "generation_error.json"
    if not error_path.exists():
        return False
    generation_error = _read_generation_error(repo_root)
    if generation_error.get("type") != "UnsupportedRepository":
        return False
    if _validated_status_from_run_log(repo_root, newer_than=_mtime(error_path)):
        return False
    if not summary_path.exists():
        return True
    try:
        return error_path.stat().st_mtime > summary_path.stat().st_mtime
    except OSError:
        return False


def _client_validation_calls(client_validation: Any) -> list[dict[str, Any]]:
    if not isinstance(client_validation, dict):
        return []
    calls = client_validation.get("calls")
    if not isinstance(calls, list):
        return []
    return [call for call in calls if isinstance(call, dict)]


def _client_semantic_success_count(client_validation: Any) -> int:
    return sum(1 for call in _client_validation_calls(client_validation) if call.get("semantic_success") is True)


def _client_meaningful_success_count(client_validation: Any) -> int:
    return sum(
        1
        for call in _client_validation_calls(client_validation)
        if call.get("semantic_success") is True and call.get("semantic_evidence") is True
    )


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _registered_tool_count(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _reported_tool_count(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _validation_ready_for_agent(validation: dict[str, Any]) -> bool:
    return (
        validation.get("workflow_status") == "validated"
        and validation.get("validation_status") == "validated"
        and validation.get("verified") is True
        and validation.get("mcp_test_passed") is True
        and validation.get("client_validation_passed") is True
        and _registered_tool_count(validation.get("tool_count")) is not None
        and _as_int(validation.get("client_semantic_success_count")) > 0
        and _as_int(validation.get("client_meaningful_success_count")) > 0
    )


def _remote_validation_ready_for_agent(remote_validation: dict[str, Any]) -> bool:
    if not isinstance(remote_validation, dict) or remote_validation.get("passed") is not True:
        return False
    if _registered_tool_count(remote_validation.get("tool_count")) is None:
        return False
    if (
        _as_int(remote_validation.get("semantic_success_count")) > 0
        and _as_int(remote_validation.get("meaningful_success_count")) > 0
    ):
        return True
    calls = remote_validation.get("calls")
    if not isinstance(calls, list):
        return False
    return any(
        isinstance(call, dict)
        and call.get("passed") is True
        and call.get("semantic_success") is True
        and call.get("semantic_evidence") is True
        for call in calls
    )


def _validated_status_from_run_log(repo_root: Path, *, newer_than: float = 0.0) -> dict[str, Any] | None:
    run_log_path = repo_root / "mcp_output" / "mcp_logs" / "run_log.json"
    if _mtime(run_log_path) <= newer_than:
        return None
    run_log = _read_run_log(repo_root)
    test_result = run_log.get("test_result", {}) if isinstance(run_log, dict) else {}
    if not isinstance(test_result, dict) or test_result.get("passed") is not True:
        return None
    client_validation = test_result.get("client_validation", {})
    if not isinstance(client_validation, dict) or client_validation.get("passed") is not True:
        return None
    semantic_success_count = _client_semantic_success_count(client_validation)
    meaningful_success_count = _client_meaningful_success_count(client_validation)
    if semantic_success_count <= 0 or meaningful_success_count <= 0:
        return None
    tool_count = _registered_tool_count(client_validation.get("tool_count"))
    if tool_count is None:
        return None
    return {
        "workflow_status": "validated",
        "validation_status": "validated",
        "verified": True,
        "mcp_test_passed": True,
        "client_validation_passed": True,
        "client_call_count": len(_client_validation_calls(client_validation)),
        "client_semantic_success_count": semantic_success_count,
        "client_meaningful_success_count": meaningful_success_count,
        "tool_count": tool_count,
        "warnings": [
            "workflow_summary.json is older than runtime validation; using newer run_log.json validation evidence."
        ],
    }


def validation_status_from_summary(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    summary_path = root / "mcp_output" / "workflow_summary.json"
    error_path = root / "mcp_output" / "generation_error.json"
    newer_run_status = _validated_status_from_run_log(root, newer_than=max(_mtime(summary_path), _mtime(error_path)))
    if newer_run_status:
        return newer_run_status
    if _newer_generation_error_invalidates_summary(root):
        generation_error = _read_generation_error(root)
        return {
            "workflow_status": "failed",
            "validation_status": "unsupported_audited",
            "verified": False,
            "mcp_test_passed": False,
            "client_validation_passed": False,
            "client_call_count": 0,
            "client_semantic_success_count": 0,
            "client_meaningful_success_count": 0,
            "tool_count": 0,
            "warnings": [
                redact_sensitive_text(
                    generation_error.get("message")
                    or "Generation failed after the last workflow summary was written"
                )
            ],
        }
    summary = _read_summary(root)
    execution = summary.get("execution", {}) if isinstance(summary, dict) else {}
    tests = summary.get("tests", {}) if isinstance(summary, dict) else {}
    mcp_plugin = tests.get("mcp_plugin") if isinstance(tests, dict) else {}
    if not isinstance(mcp_plugin, dict) or not mcp_plugin:
        mcp_plugin = tests.get("plugin", {}) if isinstance(tests, dict) else {}
    details = mcp_plugin.get("details", {}) if isinstance(mcp_plugin, dict) else {}
    if not isinstance(details, dict):
        details = {}
    plugin_details = details or (mcp_plugin if isinstance(mcp_plugin, dict) else {})
    client_validation = plugin_details.get("client_validation", {}) if isinstance(plugin_details, dict) else {}
    warnings: list[str] = []
    for source in (
        summary.get("warnings") if isinstance(summary, dict) else None,
        execution.get("warnings") if isinstance(execution, dict) else None,
        plugin_details.get("warnings") if isinstance(plugin_details, dict) else None,
        client_validation.get("warnings") if isinstance(client_validation, dict) else None,
    ):
        if isinstance(source, list):
            warnings.extend(redact_sensitive_text(item) for item in source if item)
    client_calls = _client_validation_calls(client_validation)
    semantic_success_count = _client_semantic_success_count(client_validation)
    meaningful_success_count = _client_meaningful_success_count(client_validation)
    reported_client_tool_count = (
        _reported_tool_count(client_validation.get("tool_count")) if isinstance(client_validation, dict) else None
    )
    registered_client_tool_count = (
        _registered_tool_count(client_validation.get("tool_count")) if isinstance(client_validation, dict) else None
    )
    if (
        isinstance(client_validation, dict)
        and client_validation.get("passed") is True
        and registered_client_tool_count is None
    ):
        warnings.append("Client validation did not report a positive registered tool count.")
    return {
        "workflow_status": summary.get("workflow_status") or execution.get("workflow_status") or summary.get("status") or execution.get("status"),
        "validation_status": summary.get("validation_status") or execution.get("validation_status"),
        "verified": bool(summary.get("verified", execution.get("verified", False))),
        "mcp_test_passed": bool(mcp_plugin.get("passed")),
        "client_validation_passed": (
            bool(client_validation.get("passed")) and registered_client_tool_count is not None
            if isinstance(client_validation, dict)
            else False
        ),
        "client_call_count": len(client_calls),
        "client_semantic_success_count": semantic_success_count,
        "client_meaningful_success_count": meaningful_success_count,
        "tool_count": reported_client_tool_count,
        "warnings": warnings,
    }


def build_stdio_server(
    repo_root: str | Path,
    *,
    python_executable: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    start_mcp = root / "mcp_output" / "start_mcp.py"
    if not start_mcp.exists():
        raise QuickConnectError(f"Missing generated MCP entry point: {start_mcp}")

    env = {"MCP_TRANSPORT": "stdio"}
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items() if v is not None})

    return {
        "command": find_local_python(root, python_executable),
        "args": [_jsonable_path(start_mcp)],
        "cwd": _jsonable_path(root),
        "env": env,
    }


def build_remote_server(remote_url: str) -> dict[str, str]:
    parsed = urlparse(str(remote_url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise QuickConnectError("Remote MCP URL must be an http(s) URL with a host.")
    if parsed.username or parsed.password:
        raise QuickConnectError("Remote MCP URL must not contain embedded credentials.")
    if parsed.query or parsed.fragment:
        raise QuickConnectError("Remote MCP URL must not contain query strings or fragments.")

    host = (parsed.hostname or "").lower()
    is_loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and not is_loopback:
        raise QuickConnectError("Remote MCP URL must use HTTPS unless it points to localhost for local testing.")

    path = (parsed.path or "").rstrip("/")
    if not path.endswith("/mcp"):
        path = f"{path}/mcp"
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return {"url": urlunparse(normalized)}


def _remote_probe_error(message: str, remote_url: str) -> dict[str, Any]:
    return {
        "checked": True,
        "passed": False,
        "url": build_remote_server(remote_url)["url"],
        "transport": "http",
        "tool_count": 0,
        "tools": [],
        "error": redact_sensitive_text(message),
    }


def _tool_name(tool: Any) -> str | None:
    name = getattr(tool, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    if isinstance(tool, dict):
        value = tool.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


_REMOTE_SAMPLE_STRUCTURED_PARAM_NAMES = {
    "aggregated_contributions",
    "contrib_dict",
    "grant_contributions",
    "grant_contribs_curr",
    "grants_data",
    "gene_id_mapping",
    "id_mapping",
    "pair_totals",
}
_REMOTE_COMPLEX_PARAM_NAMES = {
    "annotation",
    "annotations",
    "array",
    "axis",
    "block",
    "chunk",
    "chunks",
    "client",
    "collection",
    "component",
    "components",
    "connection",
    "cursor",
    "data",
    "database",
    "dataframe",
    "dataset",
    "datasets",
    "db",
    "dicts",
    "distribution",
    "document",
    "documents",
    "executor",
    "file",
    "folder",
    "graph",
    "host",
    "matrix",
    "model",
    "object",
    "payload",
    "path",
    "paths",
    "session",
    "table",
    "url",
}
_REMOTE_COMPLEX_PARAM_PARTS = {
    "baseurl",
    "collection",
    "connection",
    "cursor",
    "dataframe",
    "database",
    "dataset",
    "document",
    "executor",
    "graph",
    "host",
    "matrix",
    "object",
    "payload",
    "processor",
    "series",
    "stock",
    "table",
    "url",
}
_REMOTE_SIGNAL_ARRAY_PARAM_NAMES = {
    "ecg",
    "eeg",
    "emg",
    "eog",
    "peaks",
    "ppg",
    "rpeaks",
    "rsp",
    "signal",
    "signal1",
    "signal2",
    "troughs",
}


def _remote_tool_schema(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    if schema is None and isinstance(tool, dict):
        schema = tool.get("inputSchema") or tool.get("input_schema")
    return schema if isinstance(schema, dict) else {}


def _remote_schema_type(schema: dict[str, Any]) -> str:
    if isinstance(schema.get("type"), str):
        return str(schema["type"])
    for item in schema.get("anyOf", []) or schema.get("oneOf", []) or []:
        if isinstance(item, dict) and item.get("type") != "null":
            return str(item.get("type", "string"))
    return "string"


def _remote_has_detailed_object_schema(schema: dict[str, Any]) -> bool:
    return isinstance(schema.get("properties"), dict) and bool(schema["properties"])


def _remote_sample_value(name: str, schema: dict[str, Any]) -> Any:
    schema_type = _remote_schema_type(schema)
    lowered = str(name).lower()
    if "default" in schema and schema.get("default") not in ("", None):
        return schema["default"]
    if lowered in {"returns", "benchmark_rets", "factor_returns", "values", "numbers", "xs"}:
        return [0.01, -0.02, 0.015, 0.005, 0.012]
    if lowered in {"grant_contributions"}:
        return [["grant_a", "user_a", 10.0], ["grant_a", "user_b", 20.0]]
    if lowered in {"contrib_dict", "aggregated_contributions"}:
        return {"grant_a": {"user_a": 10.0, "user_b": 20.0}}
    if lowered in {"pair_totals"}:
        return {"user_a": {"user_b": 14.14}, "user_b": {"user_a": 14.14}}
    if lowered in {"gene_id_mapping", "id_mapping"} or lowered.endswith("_mapping"):
        return {"gene_a": "gene_b"}
    if "date" in lowered:
        return "2024-01-01"
    if lowered in {"city", "location", "place"}:
        return "London"
    if "time" in lowered:
        return 60 if schema_type in {"integer", "number", "float"} else "60"
    if lowered == "misc":
        return "SpaceAfter=No"
    if lowered in {"text", "sentence", "query", "prompt", "locale", "name"}:
        return "test"
    if schema_type in {"number", "float"}:
        return 1.0
    if schema_type == "integer":
        return 1
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        return [1, 2, 3]
    if schema_type == "object":
        if _remote_has_detailed_object_schema(schema):
            return {
                prop_name: _remote_sample_value(prop_name, prop if isinstance(prop, dict) else {})
                for prop_name, prop in schema["properties"].items()
            }
        return {}
    return "test"


def _remote_sample_value_for_tool(tool_name: str, name: str, schema: dict[str, Any]) -> Any:
    lowered_name = str(name).lower()
    tool_tokens = name_tokens(tool_name)
    if lowered_name == "value" and {"parse", "latitude"}.issubset(tool_tokens):
        return "N10"
    if lowered_name == "value" and {"parse", "longitude"}.issubset(tool_tokens):
        return "N10W010"
    return _remote_sample_value(name, schema)


def _remote_tool_risk(tool: Any) -> tuple[bool, str]:
    name = _tool_name(tool) or ""
    if redact_sensitive_text(name) != name:
        return True, "tool name contains sensitive-looking text"
    schema = _remote_tool_schema(tool)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    decision = classify_auto_call_tool_name(name, properties=properties)
    if decision.unsafe:
        return True, decision.reason
    for param_name, param_schema in properties.items():
        param_schema = param_schema if isinstance(param_schema, dict) else {}
        param_decision = classify_auto_call_parameter(
            str(param_name),
            schema_type=_remote_schema_type(param_schema),
            has_detailed_object_schema=_remote_has_detailed_object_schema(param_schema),
            sample_structured_param_names=_REMOTE_SAMPLE_STRUCTURED_PARAM_NAMES,
            complex_param_names=_REMOTE_COMPLEX_PARAM_NAMES,
            complex_param_parts=_REMOTE_COMPLEX_PARAM_PARTS,
            signal_array_param_names=_REMOTE_SIGNAL_ARRAY_PARAM_NAMES,
        )
        if param_decision.unsafe:
            return True, param_decision.reason
    return False, ""


def _remote_auto_call_from_tools(tools: list[Any]) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    skipped: list[dict[str, str]] = []
    for tool in tools:
        tool_name = _tool_name(tool)
        if not tool_name:
            skipped.append({"tool": "<unknown>", "reason": "tool has no usable name"})
            continue
        risky, reason = _remote_tool_risk(tool)
        if risky:
            skipped.append({"tool": redact_sensitive_text(tool_name), "reason": reason})
            continue
        schema = _remote_tool_schema(tool)
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        arguments = {
            str(name): _remote_sample_value_for_tool(tool_name, str(name), prop if isinstance(prop, dict) else {})
            for name, prop in properties.items()
        }
        return {"tool": tool_name, "arguments": arguments, "auto": True}, skipped
    return None, skipped


def _remote_semantic_success(data: Any) -> bool | None:
    if isinstance(data, dict) and isinstance(data.get("success"), bool):
        return bool(data["success"])
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return _remote_semantic_success(parsed)
        except json.JSONDecodeError:
            pass
        match = re.search(r"[\"']success[\"']\s*:\s*(true|false|True|False)", data)
        if match:
            return match.group(1).lower() == "true"
    return None


def _remote_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _remote_semantic_evidence(data: Any) -> bool | None:
    if isinstance(data, dict) and isinstance(data.get("success"), bool):
        if data["success"] is False or data.get("error"):
            return False
        if "result" in data:
            return _remote_meaningful_value(data.get("result"))
        for key in ("data", "value", "items", "output"):
            if key in data:
                return _remote_meaningful_value(data.get(key))
        return False
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return _remote_semantic_evidence(parsed)
        except json.JSONDecodeError:
            pass
        success = _remote_semantic_success(data)
        if success is False:
            return False
        if success is True:
            null_result = re.search(r"[\"']result[\"']\s*:\s*(null|None)", data)
            empty_result = re.search(r"[\"']result[\"']\s*:\s*(?:[\"']\s*[\"']|\[\s*\]|\{\s*\})", data)
            has_result = re.search(r"[\"']result[\"']\s*:", data)
            return bool(has_result and not null_result and not empty_result)
    return None


def _remote_result_to_jsonable(result: Any) -> dict[str, Any]:
    data = getattr(result, "data", None)
    structured = getattr(result, "structured_content", None)
    is_error = bool(getattr(result, "is_error", False))
    payload = data if data is not None else structured if structured is not None else str(result)
    return redact_sensitive_data(
        {
            "is_error": is_error,
            "data": payload,
            "semantic_success": _remote_semantic_success(payload),
            "semantic_evidence": _remote_semantic_evidence(payload),
        }
    )


async def _probe_remote_mcp_endpoint_async(remote_url: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    remote_server = build_remote_server(remote_url)
    url = remote_server["url"]
    try:
        from fastmcp import Client  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional local install state
        return _remote_probe_error(f"FastMCP client is not available for remote probe: {exc}", remote_url)

    async def _list_tools() -> list[Any]:
        async with Client(url) as client:
            return list(await client.list_tools())

    try:
        tools = await asyncio.wait_for(_list_tools(), timeout=timeout_seconds)
    except Exception as exc:
        return _remote_probe_error(f"FastMCP remote probe failed: {exc}", remote_url)

    tool_names = [name for item in tools if (name := _tool_name(item))]
    call, skipped = _remote_auto_call_from_tools(tools)
    calls: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    if call:
        try:
            async def _call_tool() -> Any:
                async with Client(url) as client:
                    return await client.call_tool(call["tool"], call["arguments"])

            call_result = await asyncio.wait_for(_call_tool(), timeout=timeout_seconds)
            call_report = {
                "tool": call["tool"],
                "arguments": call["arguments"],
                "auto": True,
                "passed": False,
            }
            parsed = _remote_result_to_jsonable(call_result)
            call_report.update(parsed)
            transport_passed = not parsed.get("is_error", False)
            semantic_passed = (
                parsed.get("semantic_success") is True and parsed.get("semantic_evidence") is True
            )
            call_report["transport_passed"] = transport_passed
            call_report["semantic_passed"] = semantic_passed
            call_report["passed"] = transport_passed and semantic_passed
            calls.append(redact_sensitive_data(call_report))
            if not transport_passed:
                errors.append(f"Remote tool call '{call['tool']}' returned a transport error.")
            elif not semantic_passed:
                errors.append(
                    f"Remote tool call '{call['tool']}' did not return semantic success with a meaningful result."
                )
        except Exception as exc:
            calls.append(
                redact_sensitive_data(
                    {
                        "tool": call["tool"],
                        "arguments": call["arguments"],
                        "auto": True,
                        "passed": False,
                        "error": redact_sensitive_text(str(exc)),
                    }
                )
            )
            errors.append(f"Remote tool call failed: {redact_sensitive_text(exc)}")
    else:
        warnings.append("Remote endpoint listed tools, but none were safe for automatic validation call.")

    passed = any(item.get("passed") is True for item in calls)
    result: dict[str, Any] = redact_sensitive_data({
        "checked": True,
        "passed": passed,
        "url": url,
        "transport": "http",
        "tool_count": len(tool_names),
        "tools": tool_names[:50],
        "calls": calls,
        "skipped_auto_calls": skipped,
        "semantic_success_count": sum(1 for item in calls if item.get("semantic_success") is True),
        "meaningful_success_count": sum(1 for item in calls if item.get("semantic_evidence") is True),
        "errors": errors,
        "warnings": warnings,
    })
    if not tool_names:
        result["warnings"].append("Remote endpoint responded, but no callable MCP tools were listed.")
    return result


def probe_remote_mcp_endpoint(remote_url: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    try:
        return asyncio.run(_probe_remote_mcp_endpoint_async(remote_url, timeout_seconds=timeout_seconds))
    except RuntimeError as exc:
        return _remote_probe_error(f"Remote probe could not run in the current event loop: {exc}", remote_url)


def _stdio_server_with_type(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": server["command"],
        "args": server.get("args", []),
        "cwd": server.get("cwd"),
        "env": server.get("env", {}),
    }


def _strip_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _mcp_servers(name: str, server: dict[str, Any]) -> dict[str, Any]:
    return {"mcpServers": {name: server}}


def _vscode_servers(name: str, server: dict[str, Any]) -> dict[str, Any]:
    return {"servers": {name: _strip_none(server)}}


def _claude_code_stdio_command(name: str, server: dict[str, Any]) -> list[str]:
    command = ["claude", "mcp", "add"]
    for key, value in (server.get("env") or {}).items():
        command.extend(["--env", f"{key}={value}"])
    command.extend(["--transport", "stdio", name, "--", server["command"]])
    command.extend([str(arg) for arg in server.get("args", [])])
    return command


def _claude_code_http_command(name: str, remote_server: dict[str, str]) -> list[str]:
    return ["claude", "mcp", "add", "--transport", "http", name, remote_server["url"]]


def _gemini_stdio_command(name: str, server: dict[str, Any]) -> list[str]:
    command = ["gemini", "mcp", "add", name, server["command"]]
    command.extend([str(arg) for arg in server.get("args", [])])
    return command


def _gemini_http_command(name: str, remote_server: dict[str, str]) -> list[str]:
    return ["gemini", "mcp", "add", "--transport", "http", name, remote_server["url"]]


def _openai_mcp_tool(name: str, server_url: str | None = None) -> dict[str, Any]:
    return {
        "type": "mcp",
        "server_label": name,
        "server_description": f"MCP service generated from the {name} code repository.",
        "server_url": server_url or "https://<your-deployed-mcp-host>/mcp",
        "require_approval": "always",
    }


def _openai_responses_model() -> str:
    configured = os.getenv("OPENAI_RESPONSES_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"
    return configured.strip() or "gpt-5"


def build_connection_profile(
    repo_root: str | Path,
    *,
    server_name: str | None = None,
    remote_url: str | None = None,
    python_executable: str | None = None,
    validation: dict[str, Any] | None = None,
    remote_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    name = _server_name(server_name, root.name)
    local_server = build_stdio_server(root, python_executable=python_executable)
    validation_info = redact_sensitive_data(validation or validation_status_from_summary(root))
    validation_ready = _validation_ready_for_agent(validation_info)
    vscode_local_server = _stdio_server_with_type(local_server)
    gemini_local_server = {
        **local_server,
        "timeout": 30000,
        "trust": False,
    }

    profile: dict[str, Any] = {
        "version": 1,
        "server_name": name,
        "repo_root": _jsonable_path(root),
        "validation": validation_info,
        "local": {
            "transport": "stdio",
            "server": local_server,
        },
        "clients": {
            "generic_mcp_json": {
                "mcpServers": {
                    name: local_server,
                }
            },
            "cursor": {
                "config_path": _jsonable_path(cursor_config_path()),
                "mcpServers": {
                    name: local_server,
                },
            },
            "claude_desktop": {
                "config_path": _jsonable_path(claude_desktop_config_path()),
                "mcpServers": {
                    name: local_server,
                },
            },
            "claude_code_cli": {
                "command": _claude_code_stdio_command(name, local_server),
                "json": _mcp_servers(name, local_server),
                "notes": "Run from the project where you want Claude Code to use this MCP server.",
            },
            "vscode": {
                "config_path": ".vscode/mcp.json or the VS Code user MCP configuration",
                "servers": {
                    name: vscode_local_server,
                },
            },
            "windsurf": {
                "config_path": _jsonable_path(windsurf_config_path()),
                "mcpServers": {
                    name: local_server,
                },
            },
            "cline": {
                "config_path": _jsonable_path(cline_config_path()),
                "mcpServers": {
                    name: local_server,
                },
            },
            "gemini_cli": {
                "config_path": _jsonable_path(gemini_settings_path()),
                "mcpServers": {
                    name: gemini_local_server,
                },
                "command": _gemini_stdio_command(name, local_server),
            },
            "chatgpt_app": {
                "mode": "remote_mcp_only",
                "ready": False,
                "requires_remote_url": True,
                "server_url": "https://<your-deployed-mcp-host>/mcp",
                "steps": [
                    "Deploy this MCP service to an HTTPS endpoint first.",
                    "Open ChatGPT workspace settings and create an app/custom MCP connector.",
                    "Paste the remote MCP server URL.",
                    "Choose authentication if required, then scan tools.",
                    "Test the app in ChatGPT before publishing it to a workspace.",
                ],
                "notes": [
                    "ChatGPT does not consume local stdio command/args config directly.",
                    "For private servers, use a secure tunnel or deploy behind an authenticated HTTPS endpoint.",
                ],
            },
            "openai_responses_api": {
                "ready": False,
                "requires_remote_url": True,
                "tools": [_openai_mcp_tool(name)],
                "python_example": {
                    "model": _openai_responses_model(),
                    "tools": [_openai_mcp_tool(name)],
                    "input": "Use the MCP service when it is helpful.",
                },
            },
        },
        "quick_commands": {
            "print_config": [
                sys.executable or "python",
                "scripts/connect_agent.py",
                "--repo-root",
                _jsonable_path(root),
                "--client",
                "generic",
            ],
            "connect_cursor": [
                sys.executable or "python",
                "scripts/connect_agent.py",
                "--repo-root",
                _jsonable_path(root),
                "--client",
                "cursor",
                "--write",
            ],
            "open_connection_guide": [
                sys.executable or "python",
                "scripts/connect_agent.py",
                "--repo-root",
                _jsonable_path(root),
                "--open-guide",
            ],
        },
    }

    if remote_url:
        remote_server = build_remote_server(remote_url)
        remote_url_value = remote_server["url"]
        remote_validation_info = redact_sensitive_data(remote_validation or {})
        remote_endpoint_checked = bool(remote_validation_info)
        remote_endpoint_verified = _remote_validation_ready_for_agent(remote_validation_info)
        remote_ready = validation_ready and remote_endpoint_verified
        remote_warnings: list[str] = []
        if not validation_ready:
            remote_warnings.append(
                "Remote URL was provided, but this service has not passed required local runtime MCP client "
                "validation with a successful semantic tool call and non-empty result."
            )
        if not remote_endpoint_checked:
            remote_warnings.append(
                "Remote URL was provided, but the remote endpoint has not been probed with a FastMCP client."
            )
        elif not remote_endpoint_verified:
            remote_warnings.append("Remote endpoint probe did not pass; do not connect production agents yet.")
        if isinstance(remote_validation_info.get("warnings"), list):
            remote_warnings.extend(str(item) for item in remote_validation_info["warnings"] if item)
        if remote_validation_info.get("error"):
            remote_warnings.append(str(remote_validation_info["error"]))
        profile["remote"] = {
            "transport": "http",
            "server": remote_server,
            "ready": remote_ready,
            "local_validation_required": not validation_ready,
            "endpoint_checked": remote_endpoint_checked,
            "endpoint_verified": remote_endpoint_verified,
            "validation": remote_validation_info
            or {
                "checked": False,
                "passed": False,
                "url": remote_url_value,
                "transport": "http",
                "tool_count": None,
                "tools": [],
            },
        }
        if remote_warnings:
            profile["remote"]["warnings"] = remote_warnings
        profile["clients"]["generic_remote_json"] = {"mcpServers": {name: remote_server}}
        profile["clients"]["cursor_remote"] = {
            "config_path": _jsonable_path(cursor_config_path()),
            "mcpServers": {name: remote_server},
        }
        profile["clients"]["claude_desktop_remote"] = {
            "config_path": _jsonable_path(claude_desktop_config_path()),
            "mcpServers": {name: remote_server},
        }
        profile["clients"]["claude_code_remote_cli"] = {
            "command": _claude_code_http_command(name, remote_server),
        }
        profile["clients"]["vscode_remote"] = {
            "config_path": ".vscode/mcp.json or the VS Code user MCP configuration",
            "servers": {
                name: {
                    "type": "http",
                    "url": remote_url_value,
                }
            },
        }
        profile["clients"]["windsurf_remote"] = {
            "config_path": _jsonable_path(windsurf_config_path()),
            "mcpServers": {
                name: {
                    "serverUrl": remote_url_value,
                }
            },
        }
        profile["clients"]["cline_remote"] = {
            "config_path": _jsonable_path(cline_config_path()),
            "mcpServers": {
                name: {
                    "url": remote_url_value,
                }
            },
        }
        profile["clients"]["gemini_cli_remote"] = {
            "config_path": _jsonable_path(gemini_settings_path()),
            "mcpServers": {
                name: {
                    "httpUrl": remote_url_value,
                    "timeout": 30000,
                }
            },
            "command": _gemini_http_command(name, remote_server),
        }
        profile["clients"]["chatgpt_app"] = {
            **profile["clients"]["chatgpt_app"],
            "ready": remote_ready,
            "server_url": remote_url_value,
            "validation_required": not remote_ready,
            "endpoint_checked": remote_endpoint_checked,
            "endpoint_verified": remote_endpoint_verified,
        }
        if remote_warnings:
            profile["clients"]["chatgpt_app"]["warnings"] = remote_warnings
        profile["clients"]["openai_responses_api"] = {
            "ready": remote_ready,
            "requires_remote_url": True,
            "validation_required": not remote_ready,
            "endpoint_checked": remote_endpoint_checked,
            "endpoint_verified": remote_endpoint_verified,
            "warnings": remote_warnings,
            "tools": [_openai_mcp_tool(name, remote_url_value)],
            "python_example": {
                "model": _openai_responses_model(),
                "tools": [_openai_mcp_tool(name, remote_url_value)],
                "input": "Use the MCP service when it is helpful.",
            },
        }

    return profile


def cursor_config_path() -> Path:
    base = Path.home() / ".cursor"
    preferred = base / "mcp.json"
    legacy = base / "mcp_settings.json"
    return legacy if legacy.exists() and not preferred.exists() else preferred


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def windsurf_config_path() -> Path:
    if os.name == "nt":
        return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
    return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"


def cline_config_path() -> Path:
    return Path.home() / ".cline" / "mcp.json"


def gemini_settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _shell_command(command: list[Any]) -> str:
    pieces: list[str] = []
    for item in command:
        text = str(item)
        if re.search(r"\s|['\"]", text):
            text = '"' + text.replace('"', '\\"') + '"'
        pieces.append(text)
    return " ".join(pieces)


def _code_block(title: str, value: str, *, copy_label: str = "Copy") -> str:
    return f"""
      <div class="code-block">
        <div class="code-toolbar">
          <span>{escape(title)}</span>
          <button type="button" class="copy-button" data-copy="{escape(value, quote=True)}">{escape(copy_label)}</button>
        </div>
        <pre>{escape(value)}</pre>
      </div>
    """


def _detail_row(label: str, value: str) -> str:
    return f"""
      <div class="detail-row">
        <span>{escape(label)}</span>
        <strong>{escape(value)}</strong>
      </div>
    """


def _guide_panel(
    panel_id: str,
    title: str,
    eyebrow: str,
    description: str,
    details: list[tuple[str, str]],
    blocks: list[tuple[str, str, str]],
    *,
    active: bool = False,
) -> str:
    detail_markup = "".join(_detail_row(label, value) for label, value in details)
    block_markup = "".join(_code_block(label, value, copy_label=copy_label) for label, value, copy_label in blocks)
    active_class = " active" if active else ""
    return f"""
    <section class="panel{active_class}" id="panel-{escape(panel_id)}" data-panel="{escape(panel_id)}">
      <div class="panel-heading">
        <span class="eyebrow">{escape(eyebrow)}</span>
        <h2>{escape(title)}</h2>
        <p>{escape(description)}</p>
      </div>
      <div class="detail-grid">
        {detail_markup}
      </div>
      <div class="payloads">
        {block_markup}
      </div>
    </section>
    """


def _render_connection_guide_html_legacy(profile: dict[str, Any]) -> str:
    name = str(profile.get("server_name") or "code2mcp-service")
    validation = profile.get("validation") or {}
    verified = bool(
        validation.get("verified")
        and validation.get("mcp_test_passed")
        and validation.get("client_validation_passed")
        and _as_int(validation.get("client_semantic_success_count")) > 0
    )
    status_label = "Validated" if verified else "Generated, not validated"
    status_class = "ok" if verified else "warn"
    local_json = profile["clients"]["generic_mcp_json"]
    cursor = profile["clients"]["cursor"]
    claude = profile["clients"]["claude_desktop"]
    claude_code = profile["clients"]["claude_code_cli"]
    vscode = profile["clients"]["vscode"]
    windsurf = profile["clients"]["windsurf"]
    cline = profile["clients"]["cline"]
    gemini = profile["clients"]["gemini_cli"]
    chatgpt = profile["clients"]["chatgpt_app"]
    openai_api = profile["clients"]["openai_responses_api"]
    cursor_snippet = {"mcpServers": cursor["mcpServers"]}
    claude_snippet = {"mcpServers": claude["mcpServers"]}
    vscode_snippet = {"servers": vscode["servers"]}
    windsurf_snippet = {"mcpServers": windsurf["mcpServers"]}
    cline_snippet = {"mcpServers": cline["mcpServers"]}
    gemini_snippet = {"mcpServers": gemini["mcpServers"]}
    stdio_server = profile["local"]["server"]
    remote_json = None
    if "generic_remote_json" in profile.get("clients", {}):
        remote_json = profile["clients"]["generic_remote_json"]

    cards = [
        _guide_card(
            "Cursor",
            f"Paste this into {cursor['config_path']} under the top-level JSON object.",
            f"<pre>{escape(_json_block(cursor_snippet))}</pre>",
            _json_block(cursor_snippet),
        ),
        _guide_card(
            "Claude Desktop",
            f"Paste this into {claude['config_path']} and restart Claude Desktop.",
            f"<pre>{escape(_json_block(claude_snippet))}</pre>",
            _json_block(claude_snippet),
        ),
        _guide_card(
            "Claude Code",
            "Run this in the project where Claude Code should use the MCP server.",
            f"<pre>{escape(_shell_command(claude_code['command']))}</pre>",
            _shell_command(claude_code["command"]),
            "Copy command",
        ),
        _guide_card(
            "VS Code",
            f"Paste this into {vscode['config_path']}. VS Code uses servers with an explicit type field.",
            f"<pre>{escape(_json_block(vscode_snippet))}</pre>",
            _json_block(vscode_snippet),
        ),
        _guide_card(
            "Windsurf",
            f"Paste this into {windsurf['config_path']}.",
            f"<pre>{escape(_json_block(windsurf_snippet))}</pre>",
            _json_block(windsurf_snippet),
        ),
        _guide_card(
            "Cline",
            f"Paste this into {cline['config_path']} or the Cline MCP settings UI.",
            f"<pre>{escape(_json_block(cline_snippet))}</pre>",
            _json_block(cline_snippet),
        ),
        _guide_card(
            "Gemini CLI",
            "Use either the JSON settings entry or the CLI command shown here.",
            f"<pre>{escape(_json_block(gemini_snippet))}</pre><pre>{escape(_shell_command(gemini['command']))}</pre>",
            _json_block(gemini_snippet),
        ),
        _guide_card(
            "ChatGPT App",
            "ChatGPT needs a remote HTTPS MCP endpoint. Deploy first, then use this server URL in the ChatGPT app or connector setup.",
            f"<pre>{escape(str(chatgpt['server_url']))}</pre><pre>{escape(_json_block(chatgpt['steps']))}</pre>",
            str(chatgpt["server_url"]),
            "Copy URL",
        ),
        _guide_card(
            "OpenAI Responses API",
            "Use this MCP tool object in an OpenAI API request after the service is available at a remote MCP URL.",
            f"<pre>{escape(_json_block(openai_api))}</pre>",
            _json_block(openai_api),
        ),
        _guide_card(
            "Generic MCP Client",
            "Use this for agents that accept an MCP JSON configuration with mcpServers.",
            f"<pre>{escape(_json_block(local_json))}</pre>",
            _json_block(local_json),
        ),
        _guide_card(
            "Local Stdio Server",
            "Use these command details when an agent asks for command, args, cwd, and env separately.",
            f"<pre>{escape(_json_block(stdio_server))}</pre>",
            _json_block(stdio_server),
        ),
    ]
    if remote_json:
        remote_clients = profile["clients"]
        remote_extra = ""
        if "vscode_remote" in remote_clients:
            remote_extra += f"<pre>{escape(_json_block({'VS Code': {'servers': remote_clients['vscode_remote']['servers']}}))}</pre>"
        if "claude_code_remote_cli" in remote_clients:
            remote_extra += f"<pre>{escape(_shell_command(remote_clients['claude_code_remote_cli']['command']))}</pre>"
        cards.append(
            _guide_card(
                "Remote HTTP MCP",
                "Use this after deploying the service to a remote MCP endpoint such as Hugging Face Spaces.",
                f"<pre>{escape(_json_block(remote_json))}</pre>{remote_extra}",
                _json_block(remote_json),
            )
        )

    command = _shell_command(profile["quick_commands"]["connect_cursor"])
    cards.append(
        _guide_card(
            "Optional Auto-Write",
            "This command merges the Cursor config for you. It still refuses unvalidated services by default.",
            f"<pre>{escape(command)}</pre>",
            command,
            "Copy command",
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Code2MCP Agent Connection - {escape(name)}</title>
  <style>
    :root {{
      color-scheme: light;
      --text: #172026;
      --muted: #5f6b73;
      --line: #d9e0e6;
      --bg: #f7f9fb;
      --panel: #ffffff;
      --accent: #1769aa;
      --ok: #0b7a4b;
      --warn: #9a5b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    .wrap {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 3px 8px;
      background: #fff;
    }}
    .badge.ok {{ color: var(--ok); border-color: #b9dfcd; }}
    .badge.warn {{ color: var(--warn); border-color: #ecd29f; }}
    main.wrap {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .card-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 16px;
      border-bottom: 1px solid var(--line);
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: 0;
    }}
    p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    button {{
      height: 34px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: white;
      padding: 0 12px;
      cursor: pointer;
      white-space: nowrap;
      font-size: 13px;
    }}
    button.copied {{
      background: var(--ok);
      border-color: var(--ok);
    }}
    pre {{
      margin: 0;
      padding: 16px;
      overflow: auto;
      max-height: 420px;
      background: #0f1720;
      color: #e6edf3;
      font-size: 12px;
      line-height: 1.45;
    }}
    footer {{
      color: var(--muted);
      font-size: 13px;
      padding: 0 0 28px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>{escape(name)} MCP Connection</h1>
      <div class="meta">
        <span class="badge {status_class}">{escape(status_label)}</span>
        <span class="badge">Tools: {escape(str(validation.get("tool_count") or "unknown"))}</span>
        <span class="badge">Transport: stdio</span>
      </div>
    </div>
  </header>
  <main class="wrap">
    {"".join(cards)}
  </main>
  <footer class="wrap">
    Copy the card that matches your agent. Prefer local stdio for private code; use remote HTTP only after deployment.
  </footer>
  <script>
    for (const button of document.querySelectorAll('button[data-copy]')) {{
      button.addEventListener('click', async () => {{
        const original = button.textContent;
        try {{
          await navigator.clipboard.writeText(button.dataset.copy);
          button.textContent = 'Copied';
          button.classList.add('copied');
          setTimeout(() => {{
            button.textContent = original;
            button.classList.remove('copied');
          }}, 1400);
        }} catch (error) {{
          button.textContent = 'Select text';
          setTimeout(() => button.textContent = original, 1400);
        }}
      }});
    }}
  </script>
</body>
</html>
"""


def render_connection_guide_html(profile: dict[str, Any]) -> str:
    name = str(profile.get("server_name") or "code2mcp-service")
    validation = profile.get("validation") or {}
    runtime_checked = bool(validation.get("verified") and validation.get("mcp_test_passed"))
    client_validation_passed = bool(validation.get("client_validation_passed"))
    runtime_verified = runtime_checked and client_validation_passed
    semantic_success_count = _as_int(validation.get("client_semantic_success_count"))
    meaningful_success_count = _as_int(validation.get("client_meaningful_success_count"))
    raw_tool_count = validation.get("tool_count")
    tool_count_int = _registered_tool_count(raw_tool_count)
    has_registered_tools = tool_count_int is not None
    verified = runtime_verified and has_registered_tools and semantic_success_count > 0 and meaningful_success_count > 0
    if runtime_checked and not has_registered_tools:
        status_label = "Runtime checked, tool count missing" if raw_tool_count is None else "Runtime checked, no tools"
        status_class = "warn"
    elif verified:
        status_label = "Validated"
        status_class = "ok"
    elif runtime_checked and not client_validation_passed:
        status_label = "Runtime checked, client validation failed"
        status_class = "warn"
    elif runtime_checked:
        status_label = "Runtime checked, no verified call"
        status_class = "warn"
    else:
        status_label = "Generated, not validated"
        status_class = "warn"
    tool_count = str(raw_tool_count if raw_tool_count is not None else "unknown")
    repo_root = str(profile.get("repo_root") or "")
    clients = profile["clients"]
    warning_messages = [str(item) for item in validation.get("warnings", []) or [] if item]
    remote_profile = profile.get("remote") if isinstance(profile.get("remote"), dict) else {}
    if isinstance(remote_profile, dict):
        warning_messages.extend(str(item) for item in remote_profile.get("warnings", []) or [] if item)
    if not runtime_checked:
        warning_messages.insert(
            0,
            "This service has not passed runtime MCP client validation. Do not connect it to production agents yet.",
        )
    elif not has_registered_tools:
        warning_messages.insert(
            0,
            "Runtime validation did not report a positive registered tool count. Do not write this service into an agent config yet.",
        )
    elif semantic_success_count <= 0:
        warning_messages.insert(
            0,
            "Runtime validation did not include a successful semantic tool call. Do not write this service into an agent config yet.",
        )
    elif meaningful_success_count <= 0:
        warning_messages.insert(
            0,
            "Runtime validation did not include a successful tool call with a non-empty result. Do not write this service into an agent config yet.",
        )
    elif not client_validation_passed:
        warning_messages.insert(
            0,
            "Runtime MCP client validation did not pass. Do not write this service into an agent config yet.",
        )
    warning_notice = ""
    if warning_messages:
        warning_items = "".join(f"<li>{escape(message)}</li>" for message in warning_messages[:6])
        warning_notice = f"""
      <section class="notice warn-notice" role="status">
        <strong>Connection warning</strong>
        <ul>{warning_items}</ul>
      </section>
        """

    cursor = clients["cursor"]
    claude = clients["claude_desktop"]
    claude_code = clients["claude_code_cli"]
    vscode = clients["vscode"]
    windsurf = clients["windsurf"]
    cline = clients["cline"]
    gemini = clients["gemini_cli"]
    chatgpt = clients["chatgpt_app"]
    openai_api = clients["openai_responses_api"]
    local_json = clients["generic_mcp_json"]
    stdio_server = profile["local"]["server"]

    def panel_spec(panel_id: str, title: str, kind: str, summary: str, panel: str) -> dict[str, str]:
        return {"id": panel_id, "title": title, "kind": kind, "summary": summary, "panel": panel}

    specs = [
        panel_spec(
            "cursor",
            "Cursor",
            "Local JSON",
            "Uses mcpServers with a stdio command.",
            _guide_panel(
                "cursor",
                "Cursor",
                "Local stdio",
                "Paste this into the top-level Cursor MCP JSON file. Use this when the repository stays on your machine.",
                [("Config file", str(cursor["config_path"])), ("Shape", "mcpServers"), ("Transport", "stdio")],
                [("Cursor JSON", _json_block({"mcpServers": cursor["mcpServers"]}), "Copy JSON")],
                active=True,
            ),
        ),
        panel_spec(
            "claude-desktop",
            "Claude Desktop",
            "Local JSON",
            "Classic Claude Desktop mcpServers config.",
            _guide_panel(
                "claude-desktop",
                "Claude Desktop",
                "Local stdio",
                "Paste this into Claude Desktop config and restart the app. Packaged extensions are separate; this is the direct developer setup.",
                [("Config file", str(claude["config_path"])), ("Shape", "mcpServers"), ("Transport", "stdio")],
                [("Claude Desktop JSON", _json_block({"mcpServers": claude["mcpServers"]}), "Copy JSON")],
            ),
        ),
        panel_spec(
            "claude-code",
            "Claude Code",
            "CLI command",
            "Uses claude mcp add for project setup.",
            _guide_panel(
                "claude-code",
                "Claude Code",
                "Project command",
                "Run this in the project where Claude Code should have access to the generated MCP service.",
                [("Scope", "current project"), ("Transport", "stdio"), ("Command", "claude mcp add")],
                [
                    ("Claude Code command", _shell_command(claude_code["command"]), "Copy command"),
                    ("Equivalent JSON", _json_block(claude_code["json"]), "Copy JSON"),
                ],
            ),
        ),
        panel_spec(
            "vscode",
            "VS Code",
            "Typed JSON",
            "Uses servers and requires type.",
            _guide_panel(
                "vscode",
                "VS Code",
                "Typed MCP config",
                "Paste this into .vscode/mcp.json or the VS Code user MCP configuration. VS Code uses servers rather than mcpServers.",
                [("Config file", str(vscode["config_path"])), ("Shape", "servers"), ("Required field", "type: stdio")],
                [("VS Code JSON", _json_block({"servers": vscode["servers"]}), "Copy JSON")],
            ),
        ),
        panel_spec(
            "windsurf",
            "Windsurf",
            "Local JSON",
            "Windsurf/Cascade mcpServers config.",
            _guide_panel(
                "windsurf",
                "Windsurf",
                "Local stdio",
                "Paste this snippet into Windsurf's MCP configuration, then reload the client.",
                [("Config file", str(windsurf["config_path"])), ("Shape", "mcpServers"), ("Transport", "stdio")],
                [("Windsurf JSON", _json_block({"mcpServers": windsurf["mcpServers"]}), "Copy JSON")],
            ),
        ),
        panel_spec(
            "cline",
            "Cline",
            "Local JSON",
            "Cline MCP settings payload.",
            _guide_panel(
                "cline",
                "Cline",
                "Local stdio",
                "Paste this snippet into Cline MCP settings or the local MCP config file.",
                [("Config file", str(cline["config_path"])), ("Shape", "mcpServers"), ("Transport", "stdio")],
                [("Cline JSON", _json_block({"mcpServers": cline["mcpServers"]}), "Copy JSON")],
            ),
        ),
        panel_spec(
            "gemini",
            "Gemini CLI",
            "JSON or CLI",
            "Settings JSON plus an mcp add command.",
            _guide_panel(
                "gemini",
                "Gemini CLI",
                "Local stdio",
                "Use the JSON settings entry or run the command, depending on how you manage Gemini CLI tools.",
                [("Config file", str(gemini["config_path"])), ("Shape", "mcpServers"), ("Trust", "false by default")],
                [
                    ("Gemini settings JSON", _json_block({"mcpServers": gemini["mcpServers"]}), "Copy JSON"),
                    ("Gemini CLI command", _shell_command(gemini["command"]), "Copy command"),
                ],
            ),
        ),
        panel_spec(
            "chatgpt",
            "ChatGPT",
            "Remote URL",
            "Requires a deployed HTTPS MCP endpoint.",
            _guide_panel(
                "chatgpt",
                "ChatGPT App",
                "Remote MCP only",
                "ChatGPT is remote HTTPS MCP only and does not consume local stdio command/args config. Deploy the service first, then use the remote MCP URL in ChatGPT app or connector setup.",
                [("Server URL", str(chatgpt["server_url"])), ("Local stdio", "not supported directly"), ("Tool discovery", "scan tools")],
                [
                    ("Remote MCP URL", str(chatgpt["server_url"]), "Copy URL"),
                    ("Setup checklist", _json_block(chatgpt["steps"]), "Copy steps"),
                ],
            ),
        ),
        panel_spec(
            "openai",
            "OpenAI API",
            "Responses API",
            "Uses a tools entry with type mcp.",
            _guide_panel(
                "openai",
                "OpenAI Responses API",
                "Remote MCP tool",
                "Use this tool object in an OpenAI API request after the service is available at an HTTPS MCP URL.",
                [("Tool type", "mcp"), ("Required field", "server_url"), ("Approval", "always")],
                [("OpenAI tool payload", _json_block(openai_api), "Copy payload")],
            ),
        ),
        panel_spec(
            "generic",
            "Generic MCP",
            "Portable JSON",
            "For MCP-aware clients that accept mcpServers.",
            _guide_panel(
                "generic",
                "Generic MCP Client",
                "Portable local config",
                "Use this for agents that accept a plain MCP JSON configuration with mcpServers.",
                [("Shape", "mcpServers"), ("Transport", "stdio"), ("Use case", "custom agents")],
                [("Generic MCP JSON", _json_block(local_json), "Copy JSON")],
            ),
        ),
        panel_spec(
            "stdio",
            "Stdio Details",
            "Raw server",
            "Command, args, cwd, and env separately.",
            _guide_panel(
                "stdio",
                "Local Stdio Server",
                "Raw launch details",
                "Use these values when an agent asks for command, args, cwd, and environment separately.",
                [("Command", str(stdio_server.get("command"))), ("Working directory", str(stdio_server.get("cwd"))), ("Transport", "stdio")],
                [("Server launch object", _json_block(stdio_server), "Copy object")],
            ),
        ),
    ]

    if "generic_remote_json" in clients:
        remote_blocks = [("Generic remote MCP JSON", _json_block(clients["generic_remote_json"]), "Copy JSON")]
        if "vscode_remote" in clients:
            remote_blocks.append(("VS Code remote JSON", _json_block({"servers": clients["vscode_remote"]["servers"]}), "Copy JSON"))
        if "claude_code_remote_cli" in clients:
            remote_blocks.append(("Claude Code remote command", _shell_command(clients["claude_code_remote_cli"]["command"]), "Copy command"))
        specs.append(
            panel_spec(
                "remote",
                "Remote HTTP",
                "Deployed MCP",
                "For hosted endpoints such as Hugging Face Spaces.",
                _guide_panel(
                    "remote",
                    "Remote HTTP MCP",
                    "Hosted endpoint",
                    "Use this after deploying the service to an HTTPS MCP endpoint.",
                    [("Transport", "http"), ("Endpoint", str(profile["remote"]["server"]["url"]))],
                    remote_blocks,
                ),
            )
        )

    auto_write_command = _shell_command(profile["quick_commands"]["connect_cursor"])
    specs.append(
        panel_spec(
            "auto-write",
            "Auto-Write",
            "Optional",
            "Only for users who want Code2MCP to update Cursor config.",
            _guide_panel(
                "auto-write",
                "Optional Auto-Write",
                "Cursor helper",
                "This command merges the Cursor config for you. It refuses unvalidated services by default and creates a backup before writing.",
                [("Writes files", "yes"), ("Client", "Cursor"), ("Validation required", "yes")],
                [("Auto-write command", auto_write_command, "Copy command")],
            ),
        )
    )

    nav_items = "".join(
        f"""
        <button type="button" class="client-tab{' active' if index == 0 else ''}" data-target="{escape(item['id'])}">
          <span class="client-name">{escape(item['title'])}</span>
          <span class="client-kind">{escape(item['kind'])}</span>
        </button>
        """
        for index, item in enumerate(specs)
    )
    overview_items = "".join(
        f"""
        <li>
          <strong>{escape(item['title'])}</strong>
          <span>{escape(item['summary'])}</span>
        </li>
        """
        for item in specs[:9]
    )
    panels = "".join(item["panel"] for item in specs)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Code2MCP Agent Connection - {escape(name)}</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f4f6f8;
      --surface: #ffffff;
      --surface-soft: #f9fafb;
      --text: #141a20;
      --muted: #66727d;
      --line: #d9e0e7;
      --accent: #215f9a;
      --accent-soft: #e8f1fa;
      --ok: #137348;
      --ok-soft: #e9f7ef;
      --warn: #9a6100;
      --warn-soft: #fff6df;
      --code-bg: #111820;
      --code-line: #243240;
      --code-text: #e8edf2;
      --shadow: 0 18px 44px rgba(24, 36, 51, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--page);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      line-height: 1.5;
    }}
    .shell {{ width: min(1240px, calc(100% - 32px)); margin: 0 auto; }}
    header {{ background: var(--surface); border-bottom: 1px solid var(--line); }}
    .topbar {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 28px 0 24px; }}
    .title-group {{ min-width: 0; }}
    .product-label {{ display: inline-flex; align-items: center; gap: 8px; margin-bottom: 8px; color: var(--accent); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }}
    .mark {{ width: 9px; height: 9px; border-radius: 3px; background: var(--accent); display: inline-block; }}
    h1 {{ margin: 0; font-size: clamp(24px, 3vw, 38px); line-height: 1.12; letter-spacing: 0; }}
    .subtitle {{ margin: 10px 0 0; color: var(--muted); max-width: 760px; font-size: 15px; }}
    .status-stack {{ display: grid; gap: 8px; min-width: 220px; }}
    .badge {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-soft); color: var(--muted); font-size: 13px; }}
    .badge strong {{ color: var(--text); font-weight: 700; }}
    .badge.ok {{ background: var(--ok-soft); border-color: #b9dfcb; color: var(--ok); }}
    .badge.warn {{ background: var(--warn-soft); border-color: #efd38f; color: var(--warn); }}
    .layout {{ display: grid; grid-template-columns: 288px minmax(0, 1fr); gap: 18px; padding: 20px 0 32px; }}
    aside {{ align-self: start; position: sticky; top: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); overflow: hidden; }}
    .aside-head {{ padding: 16px; border-bottom: 1px solid var(--line); }}
    .aside-head h2 {{ margin: 0; font-size: 15px; letter-spacing: 0; }}
    .aside-head p {{ margin: 5px 0 0; color: var(--muted); font-size: 12px; }}
    .client-list {{ display: grid; padding: 8px; gap: 4px; }}
    .client-tab {{ display: grid; width: 100%; grid-template-columns: 1fr auto; gap: 10px; align-items: center; padding: 10px 11px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--text); cursor: pointer; text-align: left; font: inherit; }}
    .client-tab:hover {{ background: var(--surface-soft); }}
    .client-tab.active {{ background: var(--accent-soft); border-color: #b8cfe6; color: #123d67; }}
    .client-name {{ font-size: 14px; font-weight: 700; }}
    .client-kind {{ color: var(--muted); font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 2px 7px; background: var(--surface); white-space: nowrap; }}
    .content {{ min-width: 0; display: grid; gap: 18px; }}
    .notice, .overview, .panel {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); overflow: hidden; }}
    .notice {{ padding: 14px 16px; }}
    .notice strong {{ display: block; margin-bottom: 6px; font-size: 14px; }}
    .notice ul {{ margin: 0; padding-left: 18px; color: var(--muted); font-size: 13px; }}
    .notice li + li {{ margin-top: 4px; }}
    .warn-notice {{ background: var(--warn-soft); border-color: #efd38f; }}
    .overview {{ padding: 16px; }}
    .overview h2 {{ margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }}
    .overview ul {{ list-style: none; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; padding: 0; margin: 0; }}
    .overview li {{ border: 1px solid var(--line); border-radius: 7px; padding: 10px; background: var(--surface-soft); }}
    .overview strong {{ display: block; font-size: 13px; margin-bottom: 3px; }}
    .overview span {{ display: block; color: var(--muted); font-size: 12px; }}
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}
    .panel-heading {{ padding: 20px; border-bottom: 1px solid var(--line); }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }}
    .panel h2 {{ margin: 6px 0 0; font-size: 24px; letter-spacing: 0; }}
    .panel p {{ margin: 8px 0 0; color: var(--muted); max-width: 780px; font-size: 14px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); border-bottom: 1px solid var(--line); }}
    .detail-row {{ min-width: 0; display: grid; gap: 4px; padding: 14px 16px; border-right: 1px solid var(--line); background: var(--surface-soft); }}
    .detail-row:last-child {{ border-right: 0; }}
    .detail-row span {{ color: var(--muted); font-size: 12px; }}
    .detail-row strong {{ min-width: 0; overflow-wrap: anywhere; color: var(--text); font-size: 13px; font-weight: 700; }}
    .payloads {{ display: grid; gap: 14px; padding: 16px; }}
    .code-block {{ border: 1px solid var(--code-line); border-radius: 8px; overflow: hidden; background: var(--code-bg); }}
    .code-toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 42px; padding: 0 10px 0 14px; color: #b8c4cf; border-bottom: 1px solid var(--code-line); font-size: 12px; font-weight: 700; }}
    .copy-button {{ height: 30px; border: 1px solid #46627a; border-radius: 6px; background: #1c2a35; color: #f4f8fb; padding: 0 10px; font-size: 12px; cursor: pointer; white-space: nowrap; }}
    .copy-button:hover {{ background: #263745; }}
    .copy-button.copied {{ background: var(--ok); border-color: var(--ok); }}
    pre {{ margin: 0; max-height: 520px; overflow: auto; padding: 16px; color: var(--code-text); font-size: 12px; line-height: 1.55; white-space: pre; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; }}
    footer {{ color: var(--muted); font-size: 12px; padding: 0 0 28px; }}
    @media (max-width: 860px) {{
      .topbar {{ display: grid; }}
      .status-stack {{ min-width: 0; }}
      .layout {{ grid-template-columns: 1fr; }}
      aside {{ position: static; }}
      .client-list {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }}
      .client-tab {{ grid-template-columns: 1fr; }}
      .detail-row {{ border-right: 0; border-bottom: 1px solid var(--line); }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="shell topbar">
      <div class="title-group">
        <div class="product-label"><span class="mark"></span> Code2MCP connection console</div>
        <h1>{escape(name)} MCP Service</h1>
        <p class="subtitle">Choose the agent your users actually use, then copy the matching configuration. Local clients use stdio; GPT and hosted integrations use a remote HTTPS MCP URL.</p>
      </div>
      <div class="status-stack">
        <div class="badge {status_class}"><span>Status</span><strong>{escape(status_label)}</strong></div>
        <div class="badge"><span>Tools</span><strong>{escape(tool_count)}</strong></div>
        <div class="badge"><span>Default transport</span><strong>stdio</strong></div>
      </div>
    </div>
  </header>
  <div class="shell layout">
    <aside>
      <div class="aside-head">
        <h2>Agent targets</h2>
        <p>Each client has its own required shape.</p>
      </div>
      <nav class="client-list" aria-label="Agent targets">
        {nav_items}
      </nav>
    </aside>
    <main class="content">
      {warning_notice}
      <section class="overview">
        <h2>Connection map</h2>
        <ul>{overview_items}</ul>
      </section>
      {panels}
    </main>
  </div>
  <footer class="shell">
    Source workspace: {escape(repo_root)}. The guide page does not write client files; copy the payload that matches the selected agent.
  </footer>
  <script>
    const tabs = Array.from(document.querySelectorAll('.client-tab'));
    const panels = Array.from(document.querySelectorAll('.panel'));
    function activate(target) {{
      for (const tab of tabs) {{
        tab.classList.toggle('active', tab.dataset.target === target);
      }}
      for (const panel of panels) {{
        panel.classList.toggle('active', panel.dataset.panel === target);
      }}
    }}
    for (const tab of tabs) {{
      tab.addEventListener('click', () => activate(tab.dataset.target));
    }}
    for (const button of document.querySelectorAll('button[data-copy]')) {{
      button.addEventListener('click', async () => {{
        const original = button.textContent;
        try {{
          await navigator.clipboard.writeText(button.dataset.copy || '');
          button.textContent = 'Copied';
          button.classList.add('copied');
          setTimeout(() => {{
            button.textContent = original;
            button.classList.remove('copied');
          }}, 1400);
        }} catch (error) {{
          button.textContent = 'Select text';
          setTimeout(() => {{ button.textContent = original; }}, 1400);
        }}
      }});
    }}
  </script>
</body>
</html>
"""


def _merge_mcp_servers(config: dict[str, Any], servers: dict[str, Any]) -> dict[str, Any]:
    updated = dict(config) if isinstance(config, dict) else {}
    existing = updated.get("mcpServers")
    if not isinstance(existing, dict):
        existing = {}
    existing.update(servers)
    updated["mcpServers"] = existing
    return updated


def _read_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as exc:
        raise QuickConnectError(f"Invalid JSON config: {path}: {exc}") from exc


def _write_json_with_backup(path: Path, data: dict[str, Any]) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if path.exists():
        backup_path = path.with_suffix(path.suffix + f".bak.{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup_path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup_path


def write_connection_files(profile: dict[str, Any], repo_root: str | Path) -> dict[str, str]:
    root = Path(repo_root).resolve()
    output_dir = root / "mcp_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_profile = redact_sensitive_data(profile)

    profile_path = output_dir / "agent_connection.json"
    generic_path = output_dir / "agent_mcp_config.json"
    cursor_path = output_dir / "cursor_mcp_config.json"
    guide_path = output_dir / "agent_connect.html"

    generic = safe_profile["clients"]["generic_mcp_json"]
    cursor = {"mcpServers": safe_profile["clients"]["cursor"]["mcpServers"]}

    profile_path.write_text(json.dumps(safe_profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generic_path.write_text(json.dumps(generic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cursor_path.write_text(json.dumps(cursor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    guide_path.write_text(render_connection_guide_html(safe_profile), encoding="utf-8")

    return {
        "profile": _jsonable_path(profile_path),
        "generic_config": _jsonable_path(generic_path),
        "cursor_config_snippet": _jsonable_path(cursor_path),
        "connection_guide_html": _jsonable_path(guide_path),
    }


def open_connection_guide(repo_root: str | Path) -> bool:
    path = Path(repo_root).resolve() / "mcp_output" / "agent_connect.html"
    if not path.exists():
        return False
    return webbrowser.open(path.as_uri())


def assert_validated_for_write(repo_root: str | Path, *, allow_unvalidated: bool = False) -> dict[str, Any]:
    validation = validation_status_from_summary(repo_root)
    if allow_unvalidated:
        return validation
    if _validation_ready_for_agent(validation):
        return validation
    raise QuickConnectError(
        "Refusing to write agent configuration because this MCP service is not validated. "
        "A writable connection requires runtime MCP validation, at least one registered tool, "
        "and at least one successful semantic tool call with a non-empty result. "
        "Run the default workflow or pass --allow-unvalidated if you intentionally want to connect an unverified service."
    )


def connect_cursor(
    profile: dict[str, Any],
    *,
    write: bool,
    remote: bool = False,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    if remote and "cursor_remote" not in profile["clients"]:
        raise QuickConnectError("Cursor remote connection requires --remote-url")
    client_key = "cursor_remote" if remote and "cursor_remote" in profile["clients"] else "cursor"
    client_profile = profile["clients"][client_key]
    servers = client_profile["mcpServers"]
    target = Path(config_path).expanduser() if config_path else Path(client_profile["config_path"])

    result = {
        "client": "cursor",
        "write": write,
        "config_path": _jsonable_path(target),
        "mcpServers": servers,
        "backup_path": None,
    }
    if not write:
        return result

    current = _read_json_config(target)
    updated = _merge_mcp_servers(current, servers)
    backup = _write_json_with_backup(target, updated)
    result["backup_path"] = _jsonable_path(backup) if backup else None
    return result


def connect_claude_code(
    profile: dict[str, Any],
    *,
    write: bool,
    remote: bool = False,
    timeout: int = 60,
) -> dict[str, Any]:
    if remote:
        if "claude_code_remote_cli" not in profile["clients"]:
            raise QuickConnectError("Claude Code remote connection requires --remote-url")
        command = profile["clients"]["claude_code_remote_cli"]["command"]
        transport = "http"
    else:
        command = profile["clients"]["claude_code_cli"]["command"]
        transport = "stdio"
    result: dict[str, Any] = {
        "client": "claude-code",
        "write": write,
        "transport": transport,
        "command": command,
    }
    if not write:
        return result

    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    result.update(
        {
            "returncode": proc.returncode,
            "stdout": redact_sensitive_text(proc.stdout)[-2000:],
            "stderr": redact_sensitive_text(proc.stderr)[-2000:],
        }
    )
    if proc.returncode != 0:
        message = redact_sensitive_text(proc.stderr or proc.stdout)
        raise QuickConnectError(f"fastmcp install failed: {message}")
    return result


def _copy_only_readiness_metadata(profile: dict[str, Any], *, remote: bool, remote_only: bool = False) -> dict[str, Any]:
    warnings: list[str] = []
    if remote or remote_only:
        remote_profile = profile.get("remote") if isinstance(profile.get("remote"), dict) else {}
        ready = bool(remote_profile.get("ready")) if remote_profile else False
        metadata: dict[str, Any] = {
            "ready": ready,
            "validation_required": not ready,
        }
        if remote_profile:
            metadata["endpoint_checked"] = bool(remote_profile.get("endpoint_checked"))
            metadata["endpoint_verified"] = bool(remote_profile.get("endpoint_verified"))
            warnings.extend(str(item) for item in remote_profile.get("warnings", []) or [] if item)
        else:
            metadata["requires_remote_url"] = True
            warnings.append(
                "This client requires a remote HTTPS MCP endpoint; copy-only payload is unverified until "
                "a remote URL is provided and probed with semantic MCP tool-call evidence."
            )
        if not ready and not warnings:
            warnings.append(
                "Remote copy-only payload is unverified until local runtime validation and remote endpoint "
                "probing both pass with semantic MCP tool-call evidence and a non-empty result."
            )
        if warnings:
            metadata["warnings"] = warnings
        return metadata

    validation = profile.get("validation") if isinstance(profile.get("validation"), dict) else {}
    ready = _validation_ready_for_agent(validation)
    metadata = {
        "ready": ready,
        "validation_required": not ready,
    }
    warnings.extend(str(item) for item in validation.get("warnings", []) or [] if item)
    if not ready:
        warnings.insert(
            0,
            "Local copy-only payload is unverified until runtime MCP validation passes with registered tools, "
            "a successful semantic tool call, and a non-empty result.",
        )
    if warnings:
        metadata["warnings"] = warnings
    return metadata


def connect_agent(
    repo_root: str | Path,
    *,
    client: str,
    server_name: str | None = None,
    remote_url: str | None = None,
    python_executable: str | None = None,
    write: bool = False,
    allow_unvalidated: bool = False,
    remote: bool = False,
    config_path: str | Path | None = None,
    probe_remote: bool = False,
    remote_probe_timeout: float = 10.0,
) -> dict[str, Any]:
    normalized = client.lower().replace("_", "-")
    if write and normalized not in {"cursor", "claude", "claude-code"}:
        raise QuickConnectError(
            "Writing client configuration is only supported for Cursor and Claude Code. "
            "Run without --write to copy the generated configuration for this client."
        )

    validation = assert_validated_for_write(repo_root, allow_unvalidated=allow_unvalidated) if write else validation_status_from_summary(repo_root)
    remote_validation = None
    if remote_url and probe_remote:
        remote_validation = probe_remote_mcp_endpoint(remote_url, timeout_seconds=remote_probe_timeout)
    if write and remote:
        if not remote_url:
            raise QuickConnectError("Remote agent configuration writes require --remote-url.")
        if not probe_remote:
            raise QuickConnectError(
                "Writing remote agent configuration requires --probe-remote so the HTTP MCP endpoint is verified first."
            )
        if not isinstance(remote_validation, dict) or not _remote_validation_ready_for_agent(remote_validation):
            raise QuickConnectError(
                "Refusing to write remote agent configuration because the remote MCP endpoint probe did not pass."
            )
    profile = build_connection_profile(
        repo_root,
        server_name=server_name,
        remote_url=remote_url,
        python_executable=python_executable,
        validation=validation,
        remote_validation=remote_validation,
    )
    profile = redact_sensitive_data(profile)
    files = write_connection_files(profile, repo_root)

    clients = profile["clients"]

    def _select_client(local_key: str, remote_key: str, label: str) -> dict[str, Any]:
        if remote:
            if remote_key not in clients:
                raise QuickConnectError(f"{label} remote connection requires --remote-url")
            return clients[remote_key]
        return clients[local_key]

    if normalized in {"generic", "json", "mcp-json"}:
        selected = _select_client("generic_mcp_json", "generic_remote_json", "Generic MCP")
        connection = {
            "client": "generic",
            "write": False,
            **selected,
        }
    elif normalized in {"chatgpt", "gpt", "chatgpt-app"}:
        connection = {
            "client": "chatgpt",
            "write": False,
            **profile["clients"]["chatgpt_app"],
        }
    elif normalized in {"openai", "openai-api", "responses", "responses-api"}:
        connection = {
            "client": "openai_responses_api",
            "write": False,
            **profile["clients"]["openai_responses_api"],
        }
    elif normalized in {"vscode", "vs-code"}:
        selected = _select_client("vscode", "vscode_remote", "VS Code")
        connection = {
            "client": "vscode",
            "write": False,
            **selected,
        }
    elif normalized in {"windsurf", "cascade"}:
        selected = _select_client("windsurf", "windsurf_remote", "Windsurf")
        connection = {
            "client": "windsurf",
            "write": False,
            **selected,
        }
    elif normalized == "cline":
        selected = _select_client("cline", "cline_remote", "Cline")
        connection = {
            "client": "cline",
            "write": False,
            **selected,
        }
    elif normalized in {"gemini", "gemini-cli"}:
        selected = _select_client("gemini_cli", "gemini_cli_remote", "Gemini CLI")
        connection = {
            "client": "gemini_cli",
            "write": False,
            **selected,
        }
    elif normalized == "cursor":
        connection = connect_cursor(profile, write=write, remote=remote, config_path=config_path)
    elif normalized == "claude-desktop":
        selected = _select_client("claude_desktop", "claude_desktop_remote", "Claude Desktop")
        connection = {
            "client": "claude_desktop",
            "write": False,
            **selected,
        }
    elif normalized in {"claude", "claude-code"}:
        connection = connect_claude_code(profile, write=write, remote=remote)
    else:
        raise QuickConnectError(f"Unsupported agent client: {client}")

    remote_only_clients = {
        "chatgpt",
        "gpt",
        "chatgpt-app",
        "openai",
        "openai-api",
        "responses",
        "responses-api",
    }
    if not connection.get("write"):
        connection = {
            **connection,
            **_copy_only_readiness_metadata(
                profile,
                remote=remote,
                remote_only=normalized in remote_only_clients,
            ),
        }

    return {
        "success": True,
        "profile": profile,
        "files": files,
        "connection": connection,
    }
