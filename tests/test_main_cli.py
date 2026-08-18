from types import SimpleNamespace

from main import _connect_agent_from_workflow_result
from src.tools import quick_connect


def test_connect_agent_failure_output_is_redacted(monkeypatch, capsys):
    def fake_connect_agent(*_args, **_kwargs):
        raise RuntimeError("OPENAI_API_KEY=sk-main-secret-123456 password=hunter2-secret")

    monkeypatch.setattr(quick_connect, "connect_agent", fake_connect_agent)

    result = _connect_agent_from_workflow_result(
        {
            "state": {
                "repository": {
                    "local_paths": {"repo_root": "workspace/demo"},
                }
            }
        },
        SimpleNamespace(
            connect_client="cursor",
            connect_name="demo",
            connect_write=False,
            allow_unvalidated_connect=False,
        ),
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "sk-main-secret-123456" not in output
    assert "hunter2-secret" not in output
    assert "[REDACTED]" in output
