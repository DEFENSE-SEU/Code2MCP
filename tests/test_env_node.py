from pathlib import Path

from src.nodes import env_node as env_module


def test_dependency_install_timeout_is_recorded(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "requirements.txt").write_text("torch==1.4.0\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append((cmd, timeout))
        return 124, "", f"Command timed out after {timeout} seconds"

    monkeypatch.setenv("CODE2MCP_DEP_INSTALL_TIMEOUT", "7")
    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {"has_requirements_txt": True},
        "demo",
    )

    assert result["passed"] is False
    assert result["strategy"] == "requirements"
    assert result["exit_code"] == 124
    assert "timed out" in result["message"]
    assert calls[-1][1] == 7


def test_python_minimum_version_check():
    assert env_module._python_satisfies_minimum("Python 3.10.13")
    assert env_module._python_satisfies_minimum("3.11")
    assert not env_module._python_satisfies_minimum("Python 3.9.13")


def test_base_packages_only_install_core_runtime(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        return 0, "core ok", ""

    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_base_packages(["python", "-m", "pip", "install"], str(tmp_path))

    assert result["passed"] is True
    assert len(calls) == 1
    assert calls[0][-3:] == env_module.CORE_BASE_PACKAGES


def test_import_packages_are_installed_individually(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        return 0, "Successfully installed", ""

    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {"import_packages": ["pandas", "igraph", "numpy", "pandas", "../bad"]},
        "demo",
    )

    assert result["passed"] is True
    assert result["strategy"] == "import_packages"
    assert [call[-1] for call in calls] == ["numpy", "pandas"]


def test_import_packages_include_common_wheel_scientific_deps(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        return 0, "Successfully installed", ""

    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {
            "import_packages": [
                "scipy",
                "igraph",
                "SimpleITK",
                "numpy",
                "statsmodels",
                "tqdm",
                "natsort",
                "matplotlib",
                "scikit-learn",
                "empyrical",
                "pytz",
                "ipython",
            ]
        },
        "medpy",
    )

    assert result["passed"] is True
    assert result["strategy"] == "import_packages"
    assert [call[-1] for call in calls] == [
        "numpy",
        "scipy",
        "empyrical",
        "scikit-learn",
        "matplotlib",
        "pytz",
        "ipython",
        "SimpleITK",
        "statsmodels",
        "tqdm",
        "natsort",
    ]


def test_import_package_install_uses_distribution_fallback(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        if cmd[-1] == "empyrical":
            return 1, "", "legacy build failed"
        return 0, "Successfully installed", ""

    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {"import_packages": ["empyrical"]},
        "pyfolio",
    )

    assert result["passed"] is True
    assert result["installed"] == ["empyrical"]
    assert result["installed_distributions"] == {"empyrical": "empyrical-reloaded"}
    assert [call[-1] for call in calls] == ["empyrical", "empyrical-reloaded"]


def test_import_packages_are_preferred_over_full_requirements(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "requirements.txt").write_text("deepspeed\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        return 0, "Successfully installed", ""

    monkeypatch.delenv("CODE2MCP_INSTALL_FULL_REQUIREMENTS_FIRST", raising=False)
    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {"has_requirements_txt": True, "import_packages": ["numpy"]},
        "demo",
    )

    assert result["passed"] is True
    assert result["strategy"] == "import_packages"
    assert calls == [["python", "-m", "pip", "install", "numpy"]]


def test_setup_py_package_name_is_installed_before_requirements(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "setup.py").write_text(
        "from setuptools import setup\nsetup(name='ephem', version='1.0')\n",
        encoding="utf-8",
    )
    (source / "requirements.txt").write_text("sphinx\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        return 0, "Requirement already satisfied", ""

    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {"setup_py": True, "has_requirements_txt": True, "import_packages": ["numpy"]},
        "pyephem",
    )

    assert result["passed"] is True
    assert result["strategy"] == "package"
    assert result["package"] == "ephem"
    assert calls == [["python", "-m", "pip", "install", "ephem"]]


def test_setup_py_name_extraction_uses_regex_fallback(tmp_path, monkeypatch):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text("from setuptools import setup\nsetup(\n    name = 'demo_pkg',\n)\n", encoding="utf-8")

    assert env_module._extract_setup_py_package_name(str(setup_py)) == "demo_pkg"


def test_requirements_first_can_be_enabled(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "requirements.txt").write_text("package\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        return 0, "Successfully installed", ""

    monkeypatch.setenv("CODE2MCP_INSTALL_FULL_REQUIREMENTS_FIRST", "true")
    monkeypatch.setattr(env_module, "_run", fake_run)

    result = env_module._install_deps_with_priority(
        "python",
        str(tmp_path),
        {"has_requirements_txt": True, "import_packages": ["numpy"]},
        "demo",
    )

    assert result["passed"] is True
    assert result["strategy"] == "requirements"
    assert calls[0][:5] == ["python", "-m", "pip", "install", "-r"]


def test_create_venv_uses_configured_modern_python(tmp_path, monkeypatch):
    custom_python = tmp_path / "python312.exe"
    custom_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("CODE2MCP_PYTHON", str(custom_python))

    calls = []

    def fake_run(cmd, cwd=None, timeout=1800):
        calls.append(cmd)
        if cmd[:2] == [str(custom_python), "--version"]:
            return 0, "Python 3.12.0", ""
        if cmd[:3] == [str(custom_python), "-m", "venv"]:
            env_path = tmp_path / "demo_venv"
            actual_env_path = cmd[3]
            scripts_dir = tmp_path / Path(actual_env_path).name / ("Scripts" if env_module.os.name == "nt" else "bin")
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / ("python.exe" if env_module.os.name == "nt" else "python")).write_text("", encoding="utf-8")
            return 0, "", ""
        if len(cmd) >= 2 and cmd[1] == "--version":
            return 0, "Python 3.12.0", ""
        return 0, "Successfully installed", ""

    monkeypatch.setattr(env_module, "_run", fake_run)
    monkeypatch.setattr(env_module, "_scan_docs_for_python_version", lambda source_dir: {})
    monkeypatch.setattr(env_module, "_install_pip_from_env_yml", lambda python_cmd, yml_paths, cwd: None)

    (tmp_path / "source").mkdir()
    env = env_module._create_venv_env(str(tmp_path), "demo", {})

    assert env is not None
    assert env["base_python"] == str(custom_python)
    assert any(call[:3] == [str(custom_python), "-m", "venv"] for call in calls)


def test_env_node_fails_when_no_usable_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(env_module, "_check_uv_available", lambda: False)
    monkeypatch.setattr(env_module, "_create_venv_env", lambda repo_root, repo_name, deps: None)
    monkeypatch.setattr(env_module, "_check_conda_available", lambda: False)

    state = {
        "repository": {
            "name": "demo",
            "local_paths": {"repo_root": str(tmp_path)},
        },
        "analysis": {"dependencies": {}},
    }

    result = env_module.env_node(state)

    assert result["status"] == "failed"
    assert result["workflow_status"] == "failed"
    assert result["errors"][-1]["type"] == "EnvSetupFailed"
    assert result["errors"][-1]["action_taken"] == "abort"
    assert "Python >=" in result["error"]
