import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import scripts.run_benchmark as benchmark


def _args(**overrides):
    values = {
        "generate_only": False,
        "skip_client_validation": False,
        "min_tools": 1,
        "auto_call": True,
        "max_client_calls": 2,
        "require_semantic_success": True,
        "require_meaningful_result": True,
        "semantic_policy": "all",
        "client_timeout": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_load_json_accepts_utf8_bom(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('\ufeff[{"repo_name": "demo"}]', encoding="utf-8")

    assert benchmark._load_json(path, [], strict=True) == [{"repo_name": "demo"}]


def test_client_validation_invokes_real_fastmcp_client_script(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    (repo_root / "mcp_output" / "mcp_plugin").mkdir(parents=True)
    calls = []

    class Proc:
        returncode = 0
        stdout = json.dumps({"passed": True, "tool_count": 2, "tools": ["a", "b"], "calls": []})
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return Proc()

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)

    result = benchmark._run_client_validation(
        "https://github.com/example/demo",
        {"environment": {"exec_prefix": []}},
        _args(),
    )

    assert result["passed"] is True
    assert result["tool_count"] == 2
    assert str(tmp_path / "scripts" / "validate_mcp_service.py") in calls[0]
    assert "--auto-call" in calls[0]
    assert "--require-call" in calls[0]
    assert "--semantic-policy" in calls[0]
    assert "all" in calls[0]
    assert "--require-semantic-success" in calls[0]
    assert "--require-meaningful-result" in calls[0]


def test_client_validation_redacts_sensitive_report_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    (repo_root / "mcp_output" / "mcp_plugin").mkdir(parents=True)

    class Proc:
        returncode = 0
        stdout = json.dumps({
            "passed": True,
            "tool_count": 1,
            "tools": ["leaky"],
            "calls": [{"tool": "leaky", "data": {"api_key": "abc12", "result": "token=live-secret-123456"}}],
            "errors": ["Authorization: Bearer abcdefghijklmnopqrstuvwxyz"],
            "warnings": ["password=hunter2-secret"],
            "skipped_auto_calls": [{"tool": "read_file", "reason": "OPENAI_API_KEY=sk-live-secret-123456"}],
        })
        stderr = "HF_TOKEN=hf-secret-123456"

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *_args, **_kwargs: Proc())

    result = benchmark._run_client_validation(
        "https://github.com/example/demo",
        {"environment": {"exec_prefix": []}},
        _args(),
    )
    payload = json.dumps(result, ensure_ascii=False)

    assert result["passed"] is True
    assert "abc12" not in payload
    assert "live-secret-123456" not in payload
    assert "abcdefghijklmnopqrstuvwxyz" not in payload
    assert "hunter2-secret" not in payload
    assert "sk-live-secret-123456" not in payload
    assert "hf-secret-123456" not in payload
    assert "[REDACTED]" in payload


def test_client_validation_uses_env_info_python_when_summary_lacks_exec_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    (repo_root / "mcp_output" / "mcp_plugin").mkdir(parents=True)
    env_python = repo_root / "demo_venv" / "Scripts" / "python.exe"
    env_python.parent.mkdir(parents=True)
    env_python.write_text("", encoding="utf-8")
    (repo_root / "mcp_output" / "env_info.json").write_text(
        json.dumps({"environment": {"exec_prefix": [str(env_python)]}}),
        encoding="utf-8",
    )
    calls = []

    class Proc:
        returncode = 0
        stdout = json.dumps({"passed": True, "tool_count": 1, "tools": ["add"], "calls": []})
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return Proc()

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)

    result = benchmark._run_client_validation(
        "https://github.com/example/demo",
        {},
        _args(),
    )

    assert result["passed"] is True
    assert calls[0][0] == str(env_python)


def test_env_python_falls_back_to_scanned_repo_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    venv_python = repo_root / "demo_venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    selected = benchmark._env_python_from_summary({}, "https://github.com/example/demo")

    assert selected == str(venv_python)


def test_stale_workflow_summary_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    summary_path = tmp_path / "workspace" / "demo" / "mcp_output" / "workflow_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps({"execution": {"workflow_status": "validated"}}), encoding="utf-8")
    stale_time = time.time() - 120
    os.utime(summary_path, (stale_time, stale_time))

    summary = benchmark._read_workflow_summary(
        "https://github.com/example/demo",
        min_mtime=time.time() - 10,
    )

    assert summary is None


def test_legacy_success_status_is_not_treated_as_validated():
    summary = {"execution": {"workflow_status": "success", "status": "success"}}

    assert benchmark._status_from_summary(summary, 0) == "legacy_success_unvalidated"


def test_top_level_validated_status_is_used_for_benchmark_validation():
    summary = {"workflow_status": "validated", "status": "validated"}

    assert benchmark._status_from_summary(summary, 0) == "validated"


def test_workflow_summary_reader_accepts_utf8_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    summary_path = tmp_path / "workspace" / "demo" / "mcp_output" / "workflow_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        "\ufeff" + json.dumps({"workflow_status": "validated"}),
        encoding="utf-8",
    )

    summary = benchmark._read_workflow_summary("https://github.com/example/demo")

    assert summary == {"workflow_status": "validated"}


def test_snapshot_run_artifacts_copies_fresh_first_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    logs = tmp_path / "logs"
    run_log = repo_root / "mcp_output" / "mcp_logs" / "run_log.json"
    run_log.parent.mkdir(parents=True)
    run_log.write_text('{"ok": true}', encoding="utf-8")
    summary = repo_root / "mcp_output" / "workflow_summary.json"
    summary.write_text('{"execution": {"workflow_status": "failed"}}', encoding="utf-8")
    generation_error = repo_root / "mcp_output" / "generation_error.json"
    generation_error.write_text('{"type": "UnsupportedRepository"}', encoding="utf-8")

    copied = benchmark._snapshot_run_artifacts(
        "https://github.com/example/demo",
        logs,
        min_mtime=time.time() - 10,
    )

    assert Path(copied["run_log"]).read_text(encoding="utf-8") == '{"ok": true}'
    assert Path(copied["workflow_summary"]).name == "workflow_summary.json"
    assert Path(copied["generation_error"]).name == "generation_error.json"
    assert str(logs / "demo_artifacts") in copied["run_log"]


def test_snapshot_run_artifacts_redacts_sensitive_json(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    logs = tmp_path / "logs"
    run_log = repo_root / "mcp_output" / "mcp_logs" / "run_log.json"
    run_log.parent.mkdir(parents=True)
    run_log.write_text(
        json.dumps({"ok": True, "api_key": "abc12", "message": "password=hunter2-secret"}),
        encoding="utf-8",
    )

    copied = benchmark._snapshot_run_artifacts(
        "https://github.com/example/demo",
        logs,
        min_mtime=time.time() - 10,
    )

    text = Path(copied["run_log"]).read_text(encoding="utf-8")
    assert "abc12" not in text
    assert "hunter2-secret" not in text
    assert "[REDACTED]" in text


def test_env_info_uses_fresh_file_only(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    env_python = repo_root / "demo_venv" / "Scripts" / "python.exe"
    env_python.parent.mkdir(parents=True)
    env_python.write_text("", encoding="utf-8")
    env_info = repo_root / "mcp_output" / "env_info.json"
    env_info.parent.mkdir(parents=True)
    env_info.write_text(json.dumps({"environment": {"exec_prefix": [str(env_python)]}}), encoding="utf-8")
    stale_time = time.time() - 120
    os.utime(env_info, (stale_time, stale_time))

    selected = benchmark._env_python_from_summary(
        {},
        "https://github.com/example/demo",
        min_mtime=time.time() - 10,
    )

    assert selected == str(env_python)


def test_client_validation_reports_missing_plugin_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)

    result = benchmark._run_client_validation("https://github.com/example/demo", {}, _args())

    assert result["passed"] is False
    assert "plugin directory not found" in result["reason"]


def test_client_validation_requires_parseable_json_report(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    (repo_root / "mcp_output" / "mcp_plugin").mkdir(parents=True)

    class Proc:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *_args, **_kwargs: Proc())

    result = benchmark._run_client_validation("https://github.com/example/demo", {}, _args())

    assert result["passed"] is False
    assert result["reason"] == "client_validation_invalid_report"
    assert any("not valid JSON" in error for error in result["errors"])


def test_client_validation_requires_json_output(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    (repo_root / "mcp_output" / "mcp_plugin").mkdir(parents=True)

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *_args, **_kwargs: Proc())

    result = benchmark._run_client_validation("https://github.com/example/demo", {}, _args())

    assert result["passed"] is False
    assert result["reason"] == "client_validation_invalid_report"
    assert result["errors"] == ["client validation produced no JSON output"]


def test_client_validation_requires_json_object_report(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)
    repo_root = tmp_path / "workspace" / "demo"
    (repo_root / "mcp_output" / "mcp_plugin").mkdir(parents=True)

    class Proc:
        returncode = 0
        stdout = "[]"
        stderr = ""

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *_args, **_kwargs: Proc())

    result = benchmark._run_client_validation("https://github.com/example/demo", {}, _args())

    assert result["passed"] is False
    assert result["reason"] == "client_validation_invalid_report"
    assert result["errors"] == ["client validation output JSON was not an object"]


def test_client_validation_can_be_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)

    result = benchmark._run_client_validation(
        "https://github.com/example/demo",
        {},
        _args(skip_client_validation=True),
    )

    assert result == {"passed": None, "skipped": True, "reason": "disabled"}


def test_run_streamed_writes_live_log_tail(tmp_path):
    log_path = tmp_path / "repo.log"
    command = [
        sys.executable,
        "-c",
        "print('line one'); print('line two')",
    ]

    exit_code, stdout, stderr, timed_out = benchmark._run_streamed(
        command,
        cwd=Path.cwd(),
        timeout=30,
        log_path=log_path,
    )

    assert exit_code == 0
    assert timed_out is False
    assert stderr == ""
    assert "line one" in stdout
    assert "line two" in log_path.read_text(encoding="utf-8")


def test_run_streamed_redacts_sensitive_output(tmp_path):
    log_path = tmp_path / "repo.log"
    command = [
        sys.executable,
        "-c",
        "print('OPENAI_API_KEY=sk-live-secret-123456'); print('safe line')",
    ]

    exit_code, stdout, stderr, timed_out = benchmark._run_streamed(
        command,
        cwd=Path.cwd(),
        timeout=30,
        log_path=log_path,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert timed_out is False
    assert stderr == ""
    assert "sk-live-secret-123456" not in stdout
    assert "sk-live-secret-123456" not in log_text
    assert "[REDACTED]" in stdout
    assert "[REDACTED]" in log_text
    assert "safe line" in stdout


def test_run_streamed_redacts_spawn_errors(tmp_path, monkeypatch):
    log_path = tmp_path / "repo.log"

    def fail_popen(*_args, **_kwargs):
        raise RuntimeError("OPENAI_API_KEY=sk-spawn-secret-123456")

    monkeypatch.setattr(benchmark.subprocess, "Popen", fail_popen)

    exit_code, stdout, stderr, timed_out = benchmark._run_streamed(
        [sys.executable, "-c", "print('x')"],
        cwd=Path.cwd(),
        timeout=30,
        log_path=log_path,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert exit_code == 125
    assert stdout == ""
    assert timed_out is False
    assert "sk-spawn-secret-123456" not in stderr
    assert "sk-spawn-secret-123456" not in log_text
    assert "[REDACTED]" in stderr
    assert "[REDACTED]" in log_text


def test_version_metadata_reads_git_state(monkeypatch):
    class Proc:
        returncode = 0

        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return Proc("abcdef1234567890\n")
        if command[-2:] == ["branch", "--show-current"]:
            return Proc("main\n")
        if command[-2:] == ["status", "--porcelain"]:
            return Proc(" M file.py\n")
        return Proc("")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)

    metadata = benchmark._code2mcp_version_metadata()

    assert metadata == {
        "code2mcp_commit": "abcdef1234567890",
        "code2mcp_branch": "main",
        "code2mcp_dirty": True,
    }


def test_report_includes_code_version_metadata(tmp_path):
    report = tmp_path / "report.md"
    benchmark._write_report(
        [
            {
                "repo_name": "demo",
                "nature_category": "CS",
                "benchmark_status": "validated",
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
                "client_validation": {"passed": True},
                "semantic_policy": "all",
                "success_true_call_count": 2,
                "meaningful_success_call_count": 2,
                "risk_override_call_count": 0,
                "skipped_auto_call_count": 1,
                "client_warning_count": 0,
                "client_error_count": 0,
                "tool_count": 2,
                "duration_seconds": 1.2,
                "code2mcp_commit": "abcdef1234567890",
                "code2mcp_dirty": True,
                "log_path": str(tmp_path / "demo.log"),
            },
            {
                "repo_name": "callback-only",
                "nature_category": "Health",
                "benchmark_status": "unsupported_audited",
                "workflow_status": "failed",
                "validation_status": "unsupported_audited",
                "verified": None,
                "client_validation": {"skipped": True},
                "success_true_call_count": 0,
                "meaningful_success_call_count": 0,
                "risk_override_call_count": 0,
                "skipped_auto_call_count": 0,
                "client_warning_count": 0,
                "client_error_count": 0,
                "duration_seconds": 2.5,
                "code2mcp_commit": "abcdef1234567890",
                "code2mcp_dirty": False,
                "log_path": str(tmp_path / "callback.log"),
                "unsupported_details": {
                    "likely_reason": "candidate_targets_rejected_by_generation_safety_filters",
                    "original_function_count": 3,
                    "original_class_count": 0,
                    "filtered_function_count": 0,
                    "filtered_class_count": 0,
                },
            }
        ],
        report,
    )

    text = report.read_text(encoding="utf-8")
    assert "Code2MCP commits: abcdef123456" in text
    assert "Dirty working tree results: 1" in text
    assert "Meaningful Calls" in text
    assert "Risk Overrides" in text
    assert "Skipped Auto" in text
    assert "| demo | CS | validated | validated | validated | yes | passed | all | 2 | 2 | 0 | 1 | 2 | 0 | 0 | 1.2 | abcdef123456 | yes | demo.log |" in text
    assert "## Audited Unsupported Repositories" in text
    assert "| callback-only | candidate_targets_rejected_by_generation_safety_filters | 3 | 0 | callback.log |" in text


def test_report_escapes_and_redacts_markdown_cells(tmp_path):
    report = tmp_path / "report.md"
    benchmark._write_report(
        [
            {
                "repo_name": "demo|pipe",
                "nature_category": "CS\nML",
                "benchmark_status": "unsupported_audited",
                "workflow_status": "failed",
                "validation_status": "unsupported_audited",
                "verified": None,
                "client_validation": {"skipped": True},
                "success_true_call_count": 0,
                "meaningful_success_call_count": 0,
                "risk_override_call_count": 0,
                "skipped_auto_call_count": 0,
                "client_warning_count": 0,
                "client_error_count": 0,
                "duration_seconds": 1,
                "code2mcp_commit": "abcdef1234567890",
                "code2mcp_dirty": False,
                "log_path": str(tmp_path / "pipe|log.md"),
                "unsupported_details": {
                    "likely_reason": "OPENAI_API_KEY=sk-report-secret-123456",
                    "original_function_count": 1,
                    "filtered_function_count": 0,
                },
            }
        ],
        report,
    )

    text = report.read_text(encoding="utf-8")
    assert "demo\\|pipe" in text
    assert "CS ML" in text
    assert "pipe\\|log.md" in text
    assert "sk-report-secret-123456" not in text
    assert "[REDACTED]" in text


def test_run_one_expands_validation_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)

    def fake_run_streamed(command, *, cwd, timeout, log_path):
        return 0, "ok", "", False

    def fake_summary(repo_url, min_mtime=None):
        return {
            "workflow_status": "validated",
            "validation_status": "validated",
            "verified": True,
            "execution": {
                "workflow_status": "validated",
                "validation_status": "validated",
                "verified": True,
            },
            "tests": {"mcp_plugin": {"details": {"tool_count": 3}}},
        }

    def fake_client(repo_url, summary, args, min_mtime=None):
        return {
            "passed": True,
            "tool_count": 3,
            "semantic_policy": "all",
            "calls": [
                {"tool": "a", "semantic_success": True, "semantic_evidence": True},
                {"tool": "b", "semantic_success": False},
                {"tool": "c", "semantic_success": True, "semantic_evidence": False, "risk_override": True},
            ],
            "skipped_auto_calls": [{"tool": "read_file", "reason": "parameter 'file_path' requires an external resource"}],
            "warnings": ["b returned success=false"],
            "errors": [],
        }

    monkeypatch.setattr(benchmark, "_run_streamed", fake_run_streamed)
    monkeypatch.setattr(benchmark, "_read_workflow_summary", fake_summary)
    monkeypatch.setattr(benchmark, "_run_client_validation", fake_client)
    monkeypatch.setattr(benchmark, "_snapshot_run_artifacts", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        benchmark,
        "_code2mcp_version_metadata",
        lambda: {"code2mcp_commit": "abcdef", "code2mcp_branch": "main", "code2mcp_dirty": False},
    )

    result = benchmark._run_one(
        {"repo_name": "demo", "resolved_github_url": "https://github.com/example/demo"},
        SimpleNamespace(
            log_dir=str(tmp_path / "logs"),
            output_dir=str(tmp_path / "output"),
            target="local",
            generate_only=False,
            timeout=30,
        ),
    )

    assert result["validation_status"] == "validated"
    assert result["verified"] is True
    assert result["semantic_policy"] == "all"
    assert result["success_true_call_count"] == 2
    assert result["meaningful_success_call_count"] == 1
    assert result["risk_override_call_count"] == 1
    assert result["skipped_auto_call_count"] == 1
    assert result["client_warning_count"] == 1
    assert result["client_error_count"] == 0


def test_run_one_reports_unsupported_repository_as_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)

    monkeypatch.setattr(benchmark, "_run_streamed", lambda *args, **kwargs: (1, "unsupported", "", False))
    monkeypatch.setattr(benchmark, "_read_workflow_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        benchmark,
        "_read_generation_error",
        lambda *args, **kwargs: {
            "type": "UnsupportedRepository",
            "details": {
                "likely_reason": "candidate_targets_rejected_by_generation_safety_filters",
                "original_function_count": 3,
                "filtered_function_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_run_client_validation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported repositories must not run client validation")),
    )
    monkeypatch.setattr(benchmark, "_snapshot_run_artifacts", lambda *args, **kwargs: {"generation_error": "generation_error.json"})
    monkeypatch.setattr(
        benchmark,
        "_code2mcp_version_metadata",
        lambda: {"code2mcp_commit": "abcdef", "code2mcp_branch": "main", "code2mcp_dirty": False},
    )

    result = benchmark._run_one(
        {"repo_name": "callback-only", "resolved_github_url": "https://github.com/example/callback-only"},
        SimpleNamespace(
            log_dir=str(tmp_path / "logs"),
            output_dir=str(tmp_path / "output"),
            target="local",
            generate_only=False,
            timeout=30,
        ),
    )

    assert result["benchmark_status"] == "unsupported_audited"
    assert result["workflow_status"] == "failed"
    assert result["validation_status"] == "unsupported_audited"
    assert result["client_validation"] == {"passed": False, "skipped": True, "reason": "unsupported_repository_audited"}
    assert result["unsupported_details"]["original_function_count"] == 3
    assert result["artifact_snapshots"]["generation_error"] == "generation_error.json"


def test_run_one_reports_legacy_success_as_unvalidated(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)

    def fake_summary(repo_url, min_mtime=None):
        return {
            "execution": {"workflow_status": "success", "status": "success"},
            "tests": {"plugin": {"passed": True, "tool_count": 2}},
        }

    monkeypatch.setattr(benchmark, "_run_streamed", lambda *args, **kwargs: (0, "ok", "", False))
    monkeypatch.setattr(benchmark, "_read_workflow_summary", fake_summary)
    monkeypatch.setattr(
        benchmark,
        "_run_client_validation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy success must not trigger client validation")),
    )
    monkeypatch.setattr(benchmark, "_snapshot_run_artifacts", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        benchmark,
        "_code2mcp_version_metadata",
        lambda: {"code2mcp_commit": "abcdef", "code2mcp_branch": "main", "code2mcp_dirty": False},
    )

    result = benchmark._run_one(
        {"repo_name": "demo", "resolved_github_url": "https://github.com/example/demo"},
        SimpleNamespace(
            log_dir=str(tmp_path / "logs"),
            output_dir=str(tmp_path / "output"),
            target="local",
            generate_only=False,
            timeout=30,
        ),
    )

    assert result["benchmark_status"] == "legacy_success_unvalidated"
    assert result["workflow_status"] == "legacy_success_unvalidated"
    assert result["client_validation"]["skipped"] is True


def test_benchmark_results_are_written_atomically(tmp_path):
    results = tmp_path / "results.json"
    benchmark._write_json_atomic(results, [{"repo_name": "demo", "description": 'bad " quote', "api_key": "abc12"}])

    parsed = json.loads(results.read_text(encoding="utf-8"))

    assert parsed[0]["description"] == 'bad " quote'
    assert parsed[0]["api_key"] == "[REDACTED]"
    assert not list(tmp_path.glob("results.json.tmp.*"))


def test_resume_load_ignores_corrupt_results_file(tmp_path):
    results = tmp_path / "results.json"
    results.write_text('[{"repo_name": "partial"', encoding="utf-8")

    assert benchmark._load_json(results, []) == []


def test_select_repos_filters_size_and_heavy_dependencies():
    manifest = [
        {
            "repo_name": "small-a",
            "resolved_github_url": "https://github.com/example/small-a",
            "is_valid": True,
            "size_kb": 50,
            "nature_category": "CS",
        },
        {
            "repo_name": "pysam",
            "resolved_github_url": "https://github.com/pysam-developers/pysam",
            "is_valid": True,
            "size_kb": 80,
            "nature_category": "Biology",
        },
        {
            "repo_name": "large",
            "resolved_github_url": "https://github.com/example/large",
            "is_valid": True,
            "size_kb": 5000,
            "nature_category": "CS",
        },
    ]

    selected = benchmark._select_repos(manifest, 10, max_size_kb=100, exclude_heavy=True)

    assert [item["repo_name"] for item in selected] == ["small-a"]


def test_select_repos_random_seed_is_reproducible():
    manifest = [
        {
            "repo_name": f"repo-{index}",
            "resolved_github_url": f"https://github.com/example/repo-{index}",
            "is_valid": True,
            "size_kb": index,
            "nature_category": "CS",
        }
        for index in range(6)
    ]

    first = benchmark._select_repos(manifest, 4, random_seed=13)
    second = benchmark._select_repos(manifest, 4, random_seed=13)

    assert [item["repo_name"] for item in first] == [item["repo_name"] for item in second]
    assert {item["repo_name"] for item in first}.issubset({item["repo_name"] for item in manifest})


def test_select_repos_filters_language_fields():
    manifest = [
        {
            "repo_name": "py-direct",
            "resolved_github_url": "https://github.com/example/py-direct",
            "is_valid": True,
            "language": "Python",
            "size_kb": 10,
            "nature_category": "CS",
        },
        {
            "repo_name": "py-languages-map",
            "resolved_github_url": "https://github.com/example/py-languages-map",
            "is_valid": True,
            "languages": {"Python": 200, "Shell": 10},
            "size_kb": 20,
            "nature_category": "CS",
        },
        {
            "repo_name": "swift",
            "resolved_github_url": "https://github.com/example/swift",
            "is_valid": True,
            "language": "Swift",
            "size_kb": 5,
            "nature_category": "CS",
        },
    ]

    selected = benchmark._select_repos(manifest, 10, language="Python")

    assert [item["repo_name"] for item in selected] == ["py-direct", "py-languages-map"]
