from pathlib import Path

from src.nodes import download_node as download_module


def test_download_clones_directly_to_source(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, timeout=600):
        calls.append(cmd)
        return 0, "ok", ""

    monkeypatch.setattr(download_module, "get_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(download_module, "_run", fake_run)

    state = {"repository": {"url": "https://github.com/example/project", "name": "project"}}
    result = download_module.download_node(state)

    source_dir = tmp_path / "workspace" / "project" / "source"
    assert calls == [["git", "clone", "--depth", "1", "https://github.com/example/project", str(source_dir)]]
    assert "temp_clone" not in " ".join(calls[0])
    assert result["repository"]["local_paths"]["source_root"] == str(source_dir)
    assert result["workflow_status"] == "running"


def test_download_aborts_when_existing_source_cannot_be_removed(tmp_path, monkeypatch):
    source_dir = tmp_path / "workspace" / "project" / "source"
    source_dir.mkdir(parents=True)

    monkeypatch.setattr(download_module, "get_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(download_module, "_remove_tree", lambda path: (False, "locked"))

    state = {"repository": {"url": "https://github.com/example/project", "name": "project"}}
    result = download_module.download_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["errors"][-1]["type"] == "SourceCleanupFailed"


def test_download_fails_instead_of_analyzing_empty_source(tmp_path, monkeypatch):
    def fake_run(cmd, cwd=None, timeout=600):
        return 128, "", "network failed"

    monkeypatch.setattr(download_module, "get_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(download_module, "_run", fake_run)

    state = {"repository": {"url": "https://github.com/example/project", "name": "project"}}
    result = download_module.download_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["errors"][-1]["type"] == "CloneFailed"
    assert result["errors"][-1]["action_taken"] == "abort"


def test_download_copies_local_file_url_to_isolated_source(tmp_path, monkeypatch):
    local_repo = tmp_path / "local project"
    local_repo.mkdir()
    (local_repo / "tools.py").write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    (local_repo / ".git").mkdir()
    generated = local_repo / "mcp_output"
    generated.mkdir()
    (generated / "stale.py").write_text("def fake():\n    return 1\n", encoding="utf-8")

    def fail_run(cmd, cwd=None, timeout=600):
        raise AssertionError("local file URLs should not call git clone")

    monkeypatch.setattr(download_module, "get_project_root", lambda: str(tmp_path / "project_root"))
    monkeypatch.setattr(download_module, "_run", fail_run)

    state = {"repository": {"url": local_repo.as_uri()}}
    result = download_module.download_node(state)

    source_dir = Path(result["repository"]["local_paths"]["source_root"])
    assert result["workflow_status"] == "running"
    assert result["repository"]["name"] == "local_project"
    assert (source_dir / "tools.py").exists()
    assert not (source_dir / ".git").exists()
    assert not (source_dir / "mcp_output").exists()
