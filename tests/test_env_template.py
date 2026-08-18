from pathlib import Path


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path("env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_env_example_uses_safe_deployment_defaults():
    values = _env_example_values()

    assert values["AUTO_DEPLOY_HF"] == "false"
    assert values["HF_PUSH"] == "false"
    assert values["AUTO_CONNECT_CLIENT"] == ""


def test_env_example_is_the_only_environment_template():
    assert Path("env.example").is_file()
    assert not Path("env_example.txt").exists()
