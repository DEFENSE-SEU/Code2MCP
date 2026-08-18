from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import redact_sensitive_data, redact_sensitive_text

DEFAULT_MANIFEST = PROJECT_ROOT / "benchmark" / "repositories_resolved.json"
DEFAULT_RESULTS = PROJECT_ROOT / "benchmark" / "results.json"
DEFAULT_REPORT = PROJECT_ROOT / "benchmark" / "benchmark_report.md"
DEFAULT_LOG_DIR = PROJECT_ROOT / "benchmark" / "logs"


def _load_json(path: Path, default: Any, *, strict: bool = False) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        if strict:
            raise
        return default


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(redact_sensitive_data(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _repo_name(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    name = path.split("/")[-1].replace(".git", "")
    return name or "unknown"


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)[:120]


def _markdown_cell(value: Any) -> str:
    text = redact_sensitive_text(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    text = text.replace("\r", " ").replace("\n", " ").strip()
    return text


def _git_text(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _code2mcp_version_metadata() -> dict[str, Any]:
    status = _git_text(["status", "--porcelain"])
    return {
        "code2mcp_commit": _git_text(["rev-parse", "HEAD"]),
        "code2mcp_branch": _git_text(["branch", "--show-current"]),
        "code2mcp_dirty": bool(status),
    }


def _workspace_repo_root(repo_url: str) -> Path:
    return PROJECT_ROOT / "workspace" / _repo_name(repo_url)


def _summary_path(repo_url: str) -> Path:
    return _workspace_repo_root(repo_url) / "mcp_output" / "workflow_summary.json"


def _env_info_path(repo_url: str) -> Path:
    return _workspace_repo_root(repo_url) / "mcp_output" / "env_info.json"


def _generation_error_path(repo_url: str) -> Path:
    return _workspace_repo_root(repo_url) / "mcp_output" / "generation_error.json"


def _snapshot_run_artifacts(repo_url: str, log_dir: Path, min_mtime: float | None = None) -> dict[str, str]:
    repo_root = _workspace_repo_root(repo_url)
    mcp_output = repo_root / "mcp_output"
    artifact_dir = log_dir / f"{_safe_name(_repo_name(repo_url))}_artifacts"
    paths = {
        "workflow_summary": mcp_output / "workflow_summary.json",
        "generation_error": mcp_output / "generation_error.json",
        "run_log": mcp_output / "mcp_logs" / "run_log.json",
        "error_analysis": mcp_output / "error_analysis.json",
        "analysis": mcp_output / "analysis.json",
        "env_info": mcp_output / "env_info.json",
    }
    copied: dict[str, str] = {}
    for label, source in paths.items():
        if not source.exists() or not _is_fresh_file(source, min_mtime):
            continue
        artifact_dir.mkdir(parents=True, exist_ok=True)
        destination = artifact_dir / source.name
        _copy_redacted_artifact(source, destination)
        copied[label] = str(destination)
    return copied


def _redacted_artifact_text(source: Path) -> str:
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    try:
        loaded = json.loads(text)
    except Exception:
        return redact_sensitive_text(text)
    redacted = redact_sensitive_data(loaded)
    if redacted != loaded:
        return json.dumps(redacted, ensure_ascii=False, indent=2) + "\n"
    return redact_sensitive_text(text)


def _copy_redacted_artifact(source: Path, destination: Path) -> None:
    destination.write_text(_redacted_artifact_text(source), encoding="utf-8")


HEAVY_REPO_KEYWORDS = (
    "geopandas", "tensorflow", "torch", "opencv", "plantcv", "networkit",
    "rdkit", "pysam", "pyscf", "sagemath", "spacy", "scanpy", "psychopy",
    "rasterio", "scipy",
)


def _is_heavy_repo(item: dict[str, Any]) -> bool:
    haystack = f"{item.get('repo_name', '')} {item.get('resolved_github_url', '')}".lower()
    return any(word in haystack for word in HEAVY_REPO_KEYWORDS)


def _size_within_limit(item: dict[str, Any], max_size_kb: int | None) -> bool:
    if max_size_kb is None:
        return True
    size = item.get("size_kb")
    if size is None:
        return False
    try:
        return int(size) <= max_size_kb
    except (TypeError, ValueError):
        return False


def _language_matches(item: dict[str, Any], language: str | None) -> bool:
    if not language:
        return True
    expected = language.lower()
    fields = [item.get("language"), item.get("primary_language")]
    languages = item.get("languages")
    if isinstance(languages, list):
        fields.extend(languages)
    elif isinstance(languages, dict):
        fields.extend(languages.keys())
    return any(isinstance(value, str) and value.lower() == expected for value in fields)


def _select_repos(
    manifest: list[dict[str, Any]],
    limit: int | None,
    *,
    max_size_kb: int | None = None,
    exclude_heavy: bool = False,
    language: str | None = None,
    random_seed: int | None = None,
) -> list[dict[str, Any]]:
    valid = [item for item in manifest if item.get("is_valid") and item.get("resolved_github_url")]
    valid = [item for item in valid if _size_within_limit(item, max_size_kb)]
    valid = [item for item in valid if _language_matches(item, language)]
    if exclude_heavy:
        valid = [item for item in valid if not _is_heavy_repo(item)]

    valid = sorted(
        valid,
        key=lambda item: (
            1 if _is_heavy_repo(item) else 0,
            int(item.get("size_kb") or 0),
            str(item.get("repo_name") or ""),
        ),
    )

    if random_seed is not None:
        randomized = list(valid)
        random.Random(random_seed).shuffle(randomized)
        return randomized if not limit or limit >= len(randomized) else randomized[:limit]

    if not limit or limit >= len(valid):
        return valid

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in valid:
        by_category[item.get("nature_category") or "Uncategorized"].append(item)

    selected: list[dict[str, Any]] = []
    categories = sorted(by_category)
    while len(selected) < limit and any(by_category.values()):
        for category in categories:
            if by_category[category] and len(selected) < limit:
                selected.append(by_category[category].pop(0))
    return selected


def _is_fresh_file(path: Path, min_mtime: float | None) -> bool:
    if min_mtime is None:
        return True
    try:
        return path.stat().st_mtime >= min_mtime
    except OSError:
        return False


def _read_workflow_summary(repo_url: str, min_mtime: float | None = None) -> dict[str, Any] | None:
    path = _summary_path(repo_url)
    if not path.exists() or not _is_fresh_file(path, min_mtime):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _read_env_info(repo_url: str, min_mtime: float | None = None) -> dict[str, Any] | None:
    path = _env_info_path(repo_url)
    if not path.exists() or not _is_fresh_file(path, min_mtime):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _read_generation_error(repo_url: str, min_mtime: float | None = None) -> dict[str, Any] | None:
    path = _generation_error_path(repo_url)
    if not path.exists() or not _is_fresh_file(path, min_mtime):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _is_unsupported_generation_error(data: dict[str, Any] | None) -> bool:
    return isinstance(data, dict) and data.get("type") == "UnsupportedRepository"


def _status_from_summary(summary: dict[str, Any] | None, exit_code: int) -> str:
    if not summary:
        return "failed"
    execution = summary.get("execution", {})
    workflow_status = (
        summary.get("workflow_status")
        or execution.get("workflow_status")
        or summary.get("status")
        or execution.get("status")
    )
    if workflow_status in {"validated", "generated", "failed"}:
        return workflow_status
    if workflow_status == "success":
        return "legacy_success_unvalidated"
    return "failed" if exit_code else str(workflow_status or "unknown")


def _python_paths_from_value(value: Any) -> list[Path]:
    if isinstance(value, (list, tuple)):
        return [path for item in value for path in _python_paths_from_value(item)]
    if isinstance(value, str) and value.strip():
        return [Path(value).expanduser()]
    return []


def _existing_python(paths: list[Path]) -> str | None:
    for path in paths:
        if path.exists() and path.is_file():
            return str(path)
    return None


def _scan_repo_venv_python(repo_root: Path) -> str | None:
    candidates: list[Path] = []
    for pattern in (
        "*_venv/Scripts/python.exe",
        "*_venv/bin/python",
        ".venv/Scripts/python.exe",
        ".venv/bin/python",
    ):
        candidates.extend(repo_root.glob(pattern))
    if not candidates:
        return None
    newest = max(candidates, key=lambda path: path.stat().st_mtime)
    return str(newest)


def _env_python_from_summary(
    summary: dict[str, Any] | None,
    repo_url: str | None = None,
    min_mtime: float | None = None,
) -> str:
    summary_data = summary or {}

    env = summary_data.get("environment") or {}
    candidate = _existing_python(_python_paths_from_value(env.get("exec_prefix")))
    if candidate:
        return candidate

    local_server = (summary_data.get("agent_connection") or {}).get("local_server") or {}
    candidate = _existing_python(_python_paths_from_value(local_server.get("command")))
    if candidate:
        return candidate

    if repo_url:
        env_info = _read_env_info(repo_url, min_mtime=min_mtime) or {}
        env_info_env = env_info.get("environment") or {}
        candidate = _existing_python(_python_paths_from_value(env_info_env.get("exec_prefix")))
        if candidate:
            return candidate

        candidate = _scan_repo_venv_python(_workspace_repo_root(repo_url))
        if candidate:
            return candidate

    return sys.executable


def _run_client_validation(
    repo_url: str,
    summary: dict[str, Any] | None,
    args: argparse.Namespace,
    min_mtime: float | None = None,
) -> dict[str, Any]:
    if args.generate_only or args.skip_client_validation:
        return {"passed": None, "skipped": True, "reason": "disabled"}

    repo_root = _workspace_repo_root(repo_url)
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    if not plugin_dir.is_dir():
        return {"passed": False, "skipped": False, "reason": f"plugin directory not found: {plugin_dir}"}

    python_exe = _env_python_from_summary(summary, repo_url, min_mtime=min_mtime)
    command = [
        python_exe,
        str(PROJECT_ROOT / "scripts" / "validate_mcp_service.py"),
        "--repo-root",
        str(repo_root),
        "--min-tools",
        str(args.min_tools),
    ]
    if args.auto_call:
        command.extend(["--auto-call", "--max-calls", str(args.max_client_calls), "--require-call"])
    command.extend(["--semantic-policy", args.semantic_policy])
    if args.require_semantic_success:
        command.append("--require-semantic-success")
    if args.require_meaningful_result:
        command.append("--require-meaningful-result")

    try:
        proc = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.client_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_stdout = redact_sensitive_text(exc.stdout or "")
        timeout_stderr = redact_sensitive_text(exc.stderr or f"Timed out after {args.client_timeout} seconds")
        return {
            "passed": False,
            "skipped": False,
            "command": command,
            "exit_code": 124,
            "stdout": timeout_stdout,
            "stderr": timeout_stderr,
            "reason": "client_validation_timeout",
        }

    parsed: dict[str, Any] = {}
    parse_error = ""
    safe_stdout = redact_sensitive_text(proc.stdout or "")
    safe_stderr = redact_sensitive_text(proc.stderr or "")
    if proc.stdout:
        try:
            loaded = json.loads(proc.stdout)
            if isinstance(loaded, dict):
                parsed = loaded
                safe_stdout = json.dumps(redact_sensitive_data(parsed), ensure_ascii=False)
            else:
                parse_error = "client validation output JSON was not an object"
        except json.JSONDecodeError as exc:
            parsed = {}
            parse_error = f"client validation output was not valid JSON: {exc}"
    else:
        parse_error = "client validation produced no JSON output"
    errors = list(parsed.get("errors", [])) if isinstance(parsed.get("errors", []), list) else []
    if parse_error:
        errors.append(parse_error)
    passed = proc.returncode == 0 and not parse_error and parsed.get("passed") is True
    if passed:
        reason = "ok"
    elif parse_error:
        reason = "client_validation_invalid_report"
    else:
        reason = "client_validation_failed"
    return {
        "passed": passed,
        "skipped": False,
        "command": command,
        "exit_code": proc.returncode,
        "stdout": safe_stdout[-4000:],
        "stderr": safe_stderr[-4000:],
        "tool_count": parsed.get("tool_count"),
        "tools": redact_sensitive_data(parsed.get("tools", [])),
        "calls": redact_sensitive_data(parsed.get("calls", [])),
        "errors": redact_sensitive_data(errors),
        "warnings": redact_sensitive_data(parsed.get("warnings", [])),
        "skipped_auto_calls": redact_sensitive_data(parsed.get("skipped_auto_calls", [])),
        "semantic_policy": parsed.get("semantic_policy", args.semantic_policy),
        "requires_meaningful_result": bool(args.require_meaningful_result),
        "reason": reason,
    }


def _run_streamed(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    log_path: Path,
) -> tuple[int, str, str, bool]:
    """Run a workflow command while writing live combined output to log_path."""
    started = time.time()
    tail_lines: list[str] = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as handle:
        handle.write(redact_sensitive_text("$ " + " ".join(command)) + "\n\n")
        handle.flush()
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            message = redact_sensitive_text(str(exc))
            handle.write("[spawn-error]\n" + message + "\n")
            return 125, "", message, False

        timed_out = False
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if line:
                safe_line = redact_sensitive_text(line)
                handle.write(safe_line)
                handle.flush()
                tail_lines.append(safe_line)
                if len(tail_lines) > 200:
                    tail_lines = tail_lines[-200:]
            elif proc.poll() is not None:
                break

            if timeout and time.time() - started > timeout:
                timed_out = True
                try:
                    proc.kill()
                except Exception:
                    pass
                handle.write(f"\n[TIMEOUT after {timeout} seconds]\n")
                break

        try:
            proc.wait(timeout=10)
        except Exception:
            pass

    tail = "".join(tail_lines)[-8000:]
    return (124 if timed_out else int(proc.returncode or 0)), tail, "", timed_out


def _run_one(repo: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    url = repo["resolved_github_url"]
    name = _repo_name(url)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{_safe_name(name)}.log"

    command = [sys.executable, "main.py", url, args.target, "--output", str(Path(args.output_dir))]
    if args.generate_only:
        command.append("--generate-only")

    started = time.time()
    exit_code, stdout, stderr, timed_out = _run_streamed(
        command,
        cwd=PROJECT_ROOT,
        timeout=args.timeout,
        log_path=log_path,
    )

    summary = _read_workflow_summary(url, min_mtime=started)
    generation_error = _read_generation_error(url, min_mtime=started)
    workflow_status = "timeout" if timed_out else _status_from_summary(summary, exit_code)
    unsupported_audited = workflow_status == "failed" and _is_unsupported_generation_error(generation_error)
    if workflow_status == "validated":
        client_validation = _run_client_validation(url, summary, args, min_mtime=started)
    elif unsupported_audited:
        client_validation = {"passed": False, "skipped": True, "reason": "unsupported_repository_audited"}
    else:
        client_validation = {"passed": False, "skipped": True, "reason": f"workflow_status={workflow_status}"}
    status = workflow_status
    if workflow_status == "validated" and client_validation.get("passed") is True:
        status = "validated"
    elif workflow_status == "validated":
        status = "client_validation_failed"
    elif unsupported_audited:
        status = "unsupported_audited"
    plugin = ((summary or {}).get("tests") or {}).get("mcp_plugin", {}) or ((summary or {}).get("tests") or {}).get("plugin", {})
    artifact_snapshots = _snapshot_run_artifacts(url, log_dir, min_mtime=started)
    version_metadata = _code2mcp_version_metadata()
    calls = client_validation.get("calls", []) if isinstance(client_validation, dict) else []
    success_true_call_count = sum(1 for call in calls if isinstance(call, dict) and call.get("semantic_success") is True)
    meaningful_success_call_count = sum(
        1
        for call in calls
        if isinstance(call, dict)
        and call.get("semantic_success") is True
        and call.get("semantic_evidence") is True
    )
    risk_override_call_count = sum(1 for call in calls if isinstance(call, dict) and call.get("risk_override") is True)
    skipped_auto_call_count = (
        len(client_validation.get("skipped_auto_calls", []))
        if isinstance(client_validation, dict) and isinstance(client_validation.get("skipped_auto_calls"), list)
        else 0
    )
    validation_status = (summary or {}).get("validation_status") or ((summary or {}).get("execution") or {}).get("validation_status") or workflow_status
    if unsupported_audited:
        validation_status = "unsupported_audited"
    verified = (summary or {}).get("verified")
    if verified is None:
        verified = ((summary or {}).get("execution") or {}).get("verified")

    return {
        **repo,
        **version_metadata,
        "benchmark_status": status,
        "workflow_status": workflow_status,
        "validation_status": validation_status,
        "verified": verified,
        "unsupported_details": (generation_error or {}).get("details", {}) if unsupported_audited else {},
        "client_validation": client_validation,
        "semantic_policy": client_validation.get("semantic_policy") if isinstance(client_validation, dict) else None,
        "success_true_call_count": success_true_call_count,
        "meaningful_success_call_count": meaningful_success_call_count,
        "risk_override_call_count": risk_override_call_count,
        "skipped_auto_call_count": skipped_auto_call_count,
        "client_warning_count": len(client_validation.get("warnings", [])) if isinstance(client_validation, dict) else 0,
        "client_error_count": len(client_validation.get("errors", [])) if isinstance(client_validation, dict) else 0,
        "exit_code": exit_code,
        "duration_seconds": round(time.time() - started, 2),
        "tool_count": client_validation.get("tool_count") or plugin.get("details", {}).get("tool_count") or plugin.get("tool_count"),
        "summary_path": str(_summary_path(url)) if summary else "",
        "artifact_snapshots": artifact_snapshots,
        "log_path": str(log_path),
        "error_excerpt": (stderr or stdout or "\n".join(client_validation.get("errors", [])))[-1200:],
    }


def _write_report(results: list[dict[str, Any]], path: Path) -> None:
    status_counts = Counter(item.get("benchmark_status", "unknown") for item in results)
    category_counts: dict[str, Counter] = defaultdict(Counter)
    for item in results:
        category_counts[item.get("nature_category") or "Uncategorized"][item.get("benchmark_status", "unknown")] += 1
    commits = sorted({item.get("code2mcp_commit", "")[:12] for item in results if item.get("code2mcp_commit")})
    dirty_count = sum(1 for item in results if item.get("code2mcp_dirty") is True)

    lines = [
        "# Code2MCP Benchmark Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Repositories run: {len(results)}",
        f"Code2MCP commits: {', '.join(commits) if commits else 'unknown'}",
        f"Dirty working tree results: {dirty_count}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")

    lines.extend(["", "## By Nature Category", ""])
    for category, counts in sorted(category_counts.items()):
        pieces = ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
        lines.append(f"- {category}: {pieces}")

    lines.extend(["", "## Repository Results", ""])
    lines.append("| Repo | Category | Status | Workflow | Validation | Verified | Client | Policy | Success Calls | Meaningful Calls | Risk Overrides | Skipped Auto | Tools | Warnings | Errors | Duration | Commit | Dirty | Log |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |")
    for item in results:
        log_path = item.get("log_path", "")
        log_link = Path(log_path).name if log_path else ""
        client = item.get("client_validation") or {}
        client_status = "skipped" if client.get("skipped") else "passed" if client.get("passed") else "failed"
        lines.append(
            "| {repo} | {cat} | {status} | {workflow} | {validation} | {verified} | {client} | {policy} | {success_calls} | {meaningful_calls} | {risk_overrides} | {skipped_auto} | {tools} | {warnings} | {errors} | {duration} | {commit} | {dirty} | {log} |".format(
                repo=_markdown_cell(item.get("repo_name", "")),
                cat=_markdown_cell(item.get("nature_category", "")),
                status=_markdown_cell(item.get("benchmark_status", "")),
                workflow=_markdown_cell(item.get("workflow_status", "")),
                validation=_markdown_cell(item.get("validation_status", "")),
                verified="yes" if item.get("verified") is True else "no" if item.get("verified") is False else "",
                client=_markdown_cell(client_status),
                policy=_markdown_cell(item.get("semantic_policy", "")),
                success_calls=item.get("success_true_call_count", ""),
                meaningful_calls=item.get("meaningful_success_call_count", ""),
                risk_overrides=item.get("risk_override_call_count", ""),
                skipped_auto=item.get("skipped_auto_call_count", ""),
                tools=item.get("tool_count") if item.get("tool_count") is not None else "",
                warnings=item.get("client_warning_count", ""),
                errors=item.get("client_error_count", ""),
                duration=item.get("duration_seconds", ""),
                commit=_markdown_cell(str(item.get("code2mcp_commit", ""))[:12]),
                dirty="yes" if item.get("code2mcp_dirty") is True else "no" if item.get("code2mcp_dirty") is False else "",
                log=_markdown_cell(log_link),
            )
        )

    audited_unsupported = [item for item in results if item.get("benchmark_status") == "unsupported_audited"]
    if audited_unsupported:
        lines.extend(["", "## Audited Unsupported Repositories", ""])
        lines.append("| Repo | Reason | Original Targets | Filtered Targets | Log |")
        lines.append("| --- | --- | ---: | ---: | --- |")
        for item in audited_unsupported:
            details = item.get("unsupported_details") if isinstance(item.get("unsupported_details"), dict) else {}
            original_targets = int(details.get("original_function_count") or 0) + int(details.get("original_class_count") or 0)
            filtered_targets = int(details.get("filtered_function_count") or 0) + int(details.get("filtered_class_count") or 0)
            log_path = item.get("log_path", "")
            lines.append(
                "| {repo} | {reason} | {original} | {filtered} | {log} |".format(
                    repo=_markdown_cell(item.get("repo_name", "")),
                    reason=_markdown_cell(details.get("likely_reason", "unsupported_repository")),
                    original=original_targets,
                    filtered=filtered_targets,
                    log=_markdown_cell(Path(log_path).name if log_path else ""),
                )
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Code2MCP against resolved benchmark repositories.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "benchmark" / "workflow_output"))
    parser.add_argument("--target", choices=["hf", "local"], default="local")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all", action="store_true", help="Run all valid repositories in the manifest")
    parser.add_argument("--max-size-kb", type=int, default=None, help="Only run repositories with a known size at or below this value")
    parser.add_argument("--exclude-heavy", action="store_true", help="Skip repositories known to require heavy native/ML dependencies")
    parser.add_argument("--language", default=None, help="Only run repositories whose manifest language matches this value")
    parser.add_argument("--random-seed", type=int, default=None, help="Randomize selected repositories with a reproducible seed")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--skip-client-validation", action="store_true", help="Skip FastMCP Client validation after workflow success")
    parser.add_argument("--min-tools", type=int, default=1, help="Minimum tools required by client validation")
    parser.add_argument("--auto-call", action=argparse.BooleanOptionalAction, default=True, help="Call generated tools with schema-derived sample arguments")
    parser.add_argument("--max-client-calls", type=int, default=-1, help="Maximum generated tool calls for client validation; use -1 for all safely sampleable tools")
    parser.add_argument("--client-timeout", type=int, default=180, help="Timeout for client validation per repository")
    parser.add_argument(
        "--semantic-policy",
        choices=["none", "any", "all"],
        default="all",
        help="Client validation semantic policy: all rejects any executed tool returning success=false",
    )
    parser.add_argument(
        "--require-semantic-success",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require at least one called tool to return {'success': true}; use --no-require-semantic-success for transport-only diagnostics",
    )
    parser.add_argument(
        "--require-meaningful-result",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require at least one successful tool call to return a non-empty result payload",
    )
    args = parser.parse_args()

    manifest = _load_json(Path(args.manifest), [], strict=True)
    if not isinstance(manifest, list):
        raise SystemExit("Manifest must be a JSON list")
    selected = _select_repos(
        manifest,
        None if args.all else args.limit,
        max_size_kb=args.max_size_kb,
        exclude_heavy=args.exclude_heavy,
        language=args.language,
        random_seed=args.random_seed,
    )

    results_path = Path(args.results)
    existing = _load_json(results_path, []) if args.resume else []
    existing_by_url = {item.get("resolved_github_url"): item for item in existing if item.get("resolved_github_url")}
    results = list(existing)

    for index, repo in enumerate(selected, start=1):
        url = repo.get("resolved_github_url")
        if args.resume and url in existing_by_url:
            print(f"[{index}/{len(selected)}] skip existing {repo.get('repo_name')}")
            continue
        print(f"[{index}/{len(selected)}] run {repo.get('repo_name')} -> {url}", flush=True)
        result = _run_one(repo, args)
        results.append(result)
        _write_json_atomic(results_path, results)
        _write_report(results, Path(args.report))

    _write_report(results, Path(args.report))
    print(f"Wrote {results_path} and {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
