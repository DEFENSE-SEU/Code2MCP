from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_mcp_service import (
    _is_risky_auto_call,
    _result_to_jsonable,
    _run_with_captured_stdout,
    load_create_app_from_plugin,
)
from src.utils import redact_sensitive_data, redact_sensitive_text


def _json_loads(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {label}: {exc}") from exc


def _tokens(value: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    stop_words = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "use", "using", "with"}
    raw_tokens = [
        token
        for token in re.split(r"[^a-zA-Z0-9]+", spaced.lower().replace("_", " "))
        if token and token not in stop_words
    ]
    normalized: set[str] = set()
    for token in raw_tokens:
        normalized.add(token)
        if token.endswith("s") and len(token) > 3:
            normalized.add(token[:-1])
    for width in (2, 3):
        for index in range(0, max(0, len(raw_tokens) - width + 1)):
            normalized.add("".join(raw_tokens[index:index + width]))
    compact = "".join(raw_tokens)
    if compact:
        normalized.add(compact)
    return normalized


def _tool_score(tool: Any, task_tokens: set[str]) -> tuple[int, dict[str, list[str]]]:
    name_tokens = _tokens(str(getattr(tool, "name", "") or ""))
    description_tokens = _tokens(str(getattr(tool, "description", "") or ""))
    schema_tokens = _tokens(json.dumps(getattr(tool, "inputSchema", {}) or {}, ensure_ascii=False))
    matches = {
        "name": sorted(task_tokens & name_tokens),
        "description": sorted(task_tokens & description_tokens),
        "schema": sorted(task_tokens & schema_tokens),
    }
    score = (len(matches["name"]) * 4) + (len(matches["description"]) * 2) + len(matches["schema"])
    return score, matches


def rank_tool_candidates(tools: list[Any], task: str) -> list[dict[str, Any]]:
    task_tokens = _tokens(task)
    ranked: list[dict[str, Any]] = []
    for tool in tools:
        score, matches = _tool_score(tool, task_tokens)
        ranked.append({
            "name": str(getattr(tool, "name", "")),
            "score": score,
            "matches": matches,
        })
    ranked.sort(key=lambda item: (-int(item["score"]), item["name"]))
    return ranked


def select_tool_for_task(
    tools: list[Any],
    task: str,
    expected_tool: str | None = None,
    *,
    min_score: int = 1,
) -> Any:
    if not tools:
        raise ValueError("No MCP tools are registered")
    if expected_tool:
        for tool in tools:
            if tool.name == expected_tool:
                return tool
        raise ValueError(f"Expected tool '{expected_tool}' was not registered")

    task_tokens = _tokens(task)
    scored: list[tuple[int, str, Any, dict[str, list[str]]]] = []
    for tool in tools:
        score, matches = _tool_score(tool, task_tokens)
        scored.append((score, tool.name, tool, matches))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored[0][0] < min_score:
        raise ValueError("Could not select a tool from the task text; provide --expect-tool")
    top_score = scored[0][0]
    tied = [name for score, name, _tool, _matches in scored if score == top_score]
    if len(tied) > 1:
        raise ValueError(f"Ambiguous tool selection among {', '.join(tied)}; provide --expect-tool")
    return scored[0][2]


def _extract_result_text(data: Any) -> str:
    if isinstance(data, dict):
        if "result" in data:
            return str(data.get("result"))
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    return str(data)


def result_matches_expectation(
    call_report: dict[str, Any],
    *,
    expect_contains: str | None,
    require_success: bool,
    require_meaningful_result: bool = True,
) -> tuple[bool, str]:
    if call_report.get("is_error"):
        return False, "MCP call returned is_error=true"
    semantic = call_report.get("semantic_success")
    if require_success and semantic is not True:
        return False, "Tool did not return success=true"
    if require_meaningful_result and call_report.get("semantic_evidence") is not True:
        return False, "Tool did not return a non-empty result"
    if expect_contains:
        text = _extract_result_text(call_report.get("data"))
        if expect_contains.lower() not in text.lower():
            return False, f"Expected result to contain {expect_contains!r}, got {text!r}"
    return True, ""


def _base_report(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "passed": False,
        "repo_root": str(repo_root),
        "task": args.task,
        "selected_tool": None,
        "tool_count": 0,
        "tools": [],
        "selection_candidates": [],
        "call": None,
        "errors": [],
        "warnings": [],
    }


def _agent_error(prefix: str, exc: Exception) -> str:
    message = redact_sensitive_text(str(exc)).strip()
    if message:
        return f"{prefix} ({type(exc).__name__}): {message}"
    return f"{prefix} ({type(exc).__name__})"


async def _run_scenario(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    if not plugin_dir.is_dir():
        raise SystemExit(f"MCP plugin directory not found: {plugin_dir}")

    report = _base_report(repo_root, args)

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
        report["errors"].append(_agent_error("Unable to import generated MCP service", exc))
        return report

    if args.arguments_file:
        arguments = _json_loads(Path(args.arguments_file).read_text(encoding="utf-8-sig"), f"--arguments-file {args.arguments_file}")
    else:
        arguments = _json_loads(args.arguments or "{}", "--arguments")
    if not isinstance(arguments, dict):
        raise SystemExit("--arguments must be a JSON object")

    try:
        app = create_app()
    except Exception as exc:
        report["errors"].append(_agent_error("Generated MCP service create_app() failed", exc))
        return report

    async with contextlib.AsyncExitStack() as stack:
        try:
            client = await stack.enter_async_context(Client(app))
        except Exception as exc:
            report["errors"].append(_agent_error("FastMCP client session failed", exc))
            return report

        try:
            tools = await client.list_tools()
        except Exception as exc:
            report["errors"].append(_agent_error("FastMCP list_tools() failed", exc))
            return report
        report["tool_count"] = len(tools)
        report["tools"] = [tool.name for tool in tools]
        report["selection_candidates"] = rank_tool_candidates(tools, args.task)[:5]
        try:
            selected = select_tool_for_task(
                tools,
                args.task,
                args.expect_tool,
                min_score=args.min_selection_score,
            )
        except ValueError as exc:
            report["errors"].append(redact_sensitive_text(str(exc)))
            return report
        report["selected_tool"] = selected.name
        risky_call, risk_reason = _is_risky_auto_call(selected)
        if risky_call:
            report["warnings"].append(
                f"Agent validation selected risky tool '{selected.name}'; this is an explicit call, not auto-safe sampling: {risk_reason}"
            )
        try:
            result = await client.call_tool(selected.name, arguments)
            call_report = {
                "tool": selected.name,
                "arguments": arguments,
                **_result_to_jsonable(result),
            }
            if risky_call:
                call_report["risk_override"] = True
                call_report["risk_reason"] = risk_reason
            passed, reason = result_matches_expectation(
                call_report,
                expect_contains=args.expect_contains,
                require_success=args.require_success,
                require_meaningful_result=args.require_meaningful_result,
            )
            call_report["passed"] = passed
            if not passed:
                report["errors"].append(redact_sensitive_text(reason))
            report["call"] = redact_sensitive_data(call_report)
        except Exception as exc:
            report["errors"].append(redact_sensitive_text(f"{selected.name} failed: {exc}"))

    report["passed"] = not report["errors"]
    return redact_sensitive_data(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a generated MCP service through an agent-style tool call.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--task", required=True, help="Natural-language task the agent should solve")
    parser.add_argument("--expect-tool", help="Expected selected tool; if omitted, the harness selects by task/tool overlap")
    parser.add_argument("--arguments", default="{}", help="JSON object passed to the selected MCP tool")
    parser.add_argument("--arguments-file", help="Path to a JSON object passed to the selected MCP tool")
    parser.add_argument("--expect-contains", help="Case-insensitive substring expected in the tool result")
    parser.add_argument(
        "--require-success",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require the selected tool to return {'success': true}; use --no-require-success for transport-only diagnostics",
    )
    parser.add_argument(
        "--require-meaningful-result",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require the selected tool to return a non-empty result payload",
    )
    parser.add_argument("--min-selection-score", type=int, default=1, help="Minimum weighted tool-selection score when --expect-tool is omitted")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    report = _run_with_captured_stdout(_run_scenario, args)
    print(json.dumps(redact_sensitive_data(report), ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
