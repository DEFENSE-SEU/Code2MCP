from src.loop_control import clear_runtime_validation


def test_clear_runtime_validation_removes_legacy_plugin_keys():
    state = {
        "run_result": {"success": False},
        "tests": {
            "plugin": {"passed": False},
            "mcp_plugin": {"passed": True},
            "original": {"passed": True},
        },
    }

    clear_runtime_validation(state)

    assert "run_result" not in state
    assert "plugin" not in state["tests"]
    assert "mcp_plugin" not in state["tests"]
    assert state["tests"]["original"]["passed"] is True
