import json
from pathlib import Path

from src.tools.deploy_hf import _merge_requirements, create_and_run_local_scripts, deploy_to_huggingface


def test_merge_requirements_preserves_existing_and_adds_runtime_baseline():
    merged = _merge_requirements("numpy==2.0.0\nfastmcp>=0.1.0\n")

    assert "numpy==2.0.0" in merged
    assert merged.count("fastmcp") == 1
    assert "pydantic>=2.0.0" in merged


def test_deploy_to_huggingface_prepares_docker_manifest_without_push(tmp_path):
    workspace = tmp_path / "demo"
    mcp_output = workspace / "mcp_output"
    source = workspace / "source"
    mcp_output.mkdir(parents=True)
    source.mkdir()
    (mcp_output / "start_mcp.py").write_text("print('start')\n", encoding="utf-8")
    (mcp_output / "requirements.txt").write_text("numpy==2.0.0\n", encoding="utf-8")
    (source / "api.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")

    result = deploy_to_huggingface(str(workspace), push=False)

    assert result["success"] is True
    assert result["pushed"] is False
    assert result["mcp_url"] is None
    deploy_dir = Path(result["deploy_dir"])
    dockerfile = (deploy_dir / "Dockerfile").read_text(encoding="utf-8")
    requirements = (deploy_dir / "requirements.txt").read_text(encoding="utf-8")
    manifest = json.loads((deploy_dir / "deployment_manifest.json").read_text(encoding="utf-8"))

    assert 'ENV MCP_TRANSPORT=http' in dockerfile
    assert 'ENV MCP_PORT=7860' in dockerfile
    assert 'CMD ["python", "demo/mcp_output/start_mcp.py"]' in dockerfile
    assert "numpy==2.0.0" in requirements
    assert "fastmcp>=0.1.0" in requirements
    assert manifest["entrypoint"] == "demo/mcp_output/start_mcp.py"
    assert manifest["mcp_path"] == "/mcp"


def test_local_docker_scripts_do_not_modify_client_config(tmp_path):
    workspace = tmp_path / "demo"
    mcp_output = workspace / "mcp_output"
    mcp_output.mkdir(parents=True)
    (mcp_output / "agent_connect.html").write_text("<html>guide</html>", encoding="utf-8")

    result = create_and_run_local_scripts(str(workspace), autorun=False)

    assert result["success"] is True
    deploy_dir = Path(result["scripts_dir"])
    ps1 = (deploy_dir / "run_docker.ps1").read_text(encoding="utf-8")
    sh = (deploy_dir / "run_docker.sh").read_text(encoding="utf-8")
    hint = json.loads((deploy_dir / "connection_hint.json").read_text(encoding="utf-8"))

    assert ".cursor" not in ps1
    assert ".cursor" not in sh
    assert "mcp.json" not in ps1
    assert "mcp.json" not in sh
    assert "This script does not modify agent/client config files." in ps1
    assert "This script does not modify agent/client config files." in sh
    assert "-e MCP_TRANSPORT=http" in ps1
    assert "-e MCP_TRANSPORT=http" in sh
    assert hint["does_not_modify_client_config"] is True
    assert hint["entry_url"].endswith("/mcp")
    assert all("--probe-remote" in command for command in hint["write_client_config_with"])
    assert any("--remote --remote-url" in command and "--write" in command for command in hint["write_client_config_with"])
    assert result["connection_hint"] == str(deploy_dir / "connection_hint.json")
