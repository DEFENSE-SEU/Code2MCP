import ast
import sys

import src.nodes.generate_node as generate_module
from src.nodes.generate_node import (
    _generate_adapter_blackbox,
    _generate_adapter_cli_fallback,
    _generate_adapter_import,
    _generate_adapter_import_fallback,
    _generate_mcp_service_fallback,
    _generate_readme_mcp,
    _generate_requirements_txt,
    _is_path_like_param,
    _safe_path_helper_source,
    _tool_contract_for_prompt,
    _validate_mcp_service_source,
)


def test_fallback_tools_use_explicit_parameters():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["load_file"],
                    "classes": [],
                    "function_signatures": {"load_file": ["self", "file_path", "limit"]},
                    "file_path": "loader.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "*args" not in code
    assert "**kwargs" not in code
    assert 'def load_file(file_path: str = "", limit: int = 0)' in code
    assert "_safe_resolve_path(source_path, file_path)" in code
    assert "import loader as _code2mcp_module_loader" in code
    assert 'getattr(_code2mcp_module_loader, "load_file", None)' in code
    assert "result = _call_quietly(_code2mcp_target, [file_path, limit], {})" in code


def test_fallback_direct_run_uses_environment_transport_and_port():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "tools",
                    "module": "tools",
                    "functions": ["ping"],
                    "classes": [],
                    "function_signatures": {"ping": []},
                    "file_path": "tools.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    ast.parse(code)
    assert 'os.environ.get("MCP_PORT", "8000")' in code
    assert 'os.environ.get("MCP_TRANSPORT", "http")' in code
    assert 'mcp.run(transport="http", host="0.0.0.0", port=port)' in code
    assert 'mcp.run(transport="http", host="0.0.0.0", port=8000)' not in code


def test_fallback_normalizes_src_layout_imports():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "src.humanize",
                    "module": "filesize",
                    "functions": ["naturalsize"],
                    "classes": [],
                    "function_signatures": {"naturalsize": ["value", "binary"]},
                    "file_path": "src/humanize/filesize.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "src_layout_path" in code
    assert "import humanize.filesize as _code2mcp_module_humanize_filesize" in code
    assert 'getattr(_code2mcp_module_humanize_filesize, "naturalsize", None)' in code


def test_fallback_prefers_file_path_for_package_submodule_imports():
    analysis = {
        "repository_name": "vaderSentiment",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["vaderSentiment"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "vaderSentiment",
                    "module": "vaderSentiment",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["score", "alpha"]},
                    "file_path": "vaderSentiment/vaderSentiment.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "import vaderSentiment.vaderSentiment as _code2mcp_module_vaderSentiment_vaderSentiment" in code
    assert 'getattr(_code2mcp_module_vaderSentiment_vaderSentiment, "normalize", None)' in code


def test_tool_signature_infers_numeric_names_without_annotations():
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["score", "alpha"],
        [
            {"name": "score", "annotation": "", "default": "", "required": True},
            {"name": "alpha", "annotation": "", "default": "15", "required": False},
        ],
    )

    assert signature == "score: float = 0.0, alpha: int = 15"
    assert call_args == "score, alpha"
    assert names == ["score", "alpha"]


def test_tool_signature_infers_boolean_and_valence_names_without_annotations():
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["valence", "is_cap_diff"],
        [
            {"name": "valence", "annotation": "", "default": "", "required": True},
            {"name": "is_cap_diff", "annotation": "", "default": "", "required": True},
        ],
    )

    assert signature == "valence: float = 0.0, is_cap_diff: bool = False"
    assert call_args == "valence, is_cap_diff"
    assert names == ["valence", "is_cap_diff"]


def test_tool_signature_handles_numeric_iterable_statistics_params():
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["xs", "p", "sort"],
        [
            {"name": "xs", "annotation": "", "default": "", "required": True},
            {"name": "p", "annotation": "", "default": "(25, 50, 75)", "required": False},
            {"name": "sort", "annotation": "", "default": "True", "required": False},
        ],
        function_name="percentile",
    )

    assert signature == "xs: list = None, p: float = 0.0, sort: bool = True"
    assert call_args == "xs, p, sort"
    assert names == ["xs", "p", "sort"]


def test_tool_signature_infers_mapping_params_as_dicts():
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["gpr_rule", "gene_id_mapping"],
        [
            {"name": "gpr_rule", "annotation": "str", "default": "", "required": True},
            {"name": "gene_id_mapping", "annotation": "", "default": "", "required": True},
        ],
        function_name="replace_gene_ids_in_gpr",
    )

    assert signature == 'gpr_rule: str = "", gene_id_mapping: dict = None'
    assert call_args == "gpr_rule, gene_id_mapping"
    assert names == ["gpr_rule", "gene_id_mapping"]


def test_tool_signature_replaces_runtime_default_expressions():
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["package", "threshold"],
        [
            {"name": "package", "annotation": "", "default": "", "required": True},
            {"name": "threshold", "annotation": "", "default": "timedelta(days=365 * 2)", "required": False},
        ],
    )

    assert signature == 'package: str = "", threshold: float = 0.0'
    assert "timedelta" not in signature
    assert call_args == "package, threshold"
    assert names == ["package", "threshold"]


def test_fallback_loads_submodule_by_file_when_package_init_fails(tmp_path):
    repo_root = tmp_path / "repo"
    source_pkg = repo_root / "source" / "pkg"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    source_pkg.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    (source_pkg / "__init__.py").write_text("raise RuntimeError('heavy init failed')\n", encoding="utf-8")
    (source_pkg / "sub.py").write_text("def ping():\n    return 'file-fallback'\n", encoding="utf-8")
    (plugin_dir / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def tool(self, **_kwargs):\n"
        "        def decorator(func):\n"
        "            return func\n"
        "        return decorator\n"
        "    def run(self, **_kwargs):\n"
        "        return None\n",
        encoding="utf-8",
    )
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "sub",
                    "functions": ["ping"],
                    "classes": [],
                    "function_signatures": {"ping": []},
                    "file_path": "pkg/sub.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)
    namespace = {"__file__": str(plugin_dir / "mcp_service.py")}
    old_path = list(sys.path)
    try:
        sys.path[:] = [str(plugin_dir)] + [path for path in old_path if path != str(repo_root / "source")]
        exec(compile(code, str(plugin_dir / "mcp_service.py"), "exec"), namespace)
        result = namespace["ping"]()
    finally:
        sys.path[:] = old_path

    assert "source fallback" in code
    assert "_load_module_from_file" in code
    assert result == {"success": True, "result": "file-fallback", "error": None}


def test_fallback_prefers_installed_package_when_package_install_succeeded(tmp_path):
    repo_root = tmp_path / "repo"
    source_pkg = repo_root / "source" / "shadowpkg"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    installed_dir = tmp_path / "installed"
    source_pkg.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    installed_dir.mkdir()
    (source_pkg / "__init__.py").write_text("def ping():\n    return 'source'\n", encoding="utf-8")
    installed_pkg = installed_dir / "shadowpkg"
    installed_pkg.mkdir()
    (installed_pkg / "__init__.py").write_text("def ping():\n    return 'installed'\n", encoding="utf-8")
    (installed_dir / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def tool(self, **_kwargs):\n"
        "        def decorator(func):\n"
        "            return func\n"
        "        return decorator\n"
        "    def run(self, **_kwargs):\n"
        "        return None\n",
        encoding="utf-8",
    )
    analysis = {
        "repository_name": "demo",
        "_runtime": {
            "env": {
                "dependency_installation": {
                    "passed": True,
                    "strategy": "package",
                    "package": "shadowpkg",
                }
            }
        },
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "shadowpkg",
                    "module": "shadowpkg",
                    "functions": ["ping"],
                    "classes": [],
                    "function_signatures": {"ping": []},
                    "file_path": "shadowpkg/__init__.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)
    namespace = {"__file__": str(plugin_dir / "mcp_service.py")}
    old_path = list(sys.path)
    try:
        sys.path[:] = [str(installed_dir)] + [path for path in old_path if path != str(repo_root / "source")]
        exec(compile(code, str(plugin_dir / "mcp_service.py"), "exec"), namespace)
        result = namespace["ping"]()
    finally:
        sys.path[:] = old_path

    assert "_code2mcp_prefer_installed_packages = True" in code
    assert result["success"] is True
    assert result["result"] == "installed"


def test_fallback_prefers_installed_package_when_env_installed_package():
    analysis = {
        "repository_name": "demo",
        "_runtime": {
            "env": {
                "dependency_installation": {
                    "passed": True,
                    "strategy": "package",
                    "package": "demo-pkg",
                }
            }
        },
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["demo_pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "demo_pkg",
                    "module": "tools",
                    "functions": ["ping"],
                    "classes": [],
                    "function_signatures": {"ping": []},
                    "file_path": "demo_pkg/tools.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "_code2mcp_prefer_installed_packages = True" in code
    assert "if not _code2mcp_prefer_installed_packages" in code
    assert "source fallback" in code


def test_fallback_class_wrappers_use_zero_argument_tools(monkeypatch):
    monkeypatch.setenv("CODE2MCP_ENABLE_CLASS_WRAPPERS", "true")
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "sentiment",
                    "functions": [],
                    "classes": ["Analyzer"],
                    "file_path": "pkg/sentiment.py",
                    "class_details": {
                        "Analyzer": {
                            "constructor_requires_args": False,
                            "constructor_has_varargs": False,
                            "constructor_has_kwargs": False,
                            "public_methods": [{"name": "run"}],
                            "wrapper_score": 75,
                        }
                    },
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def analyzer():" in code
    assert "def analyzer(payload: dict = None)" not in code


def test_fallback_skips_complex_function_wrappers():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "train",
                    "functions": ["train_model"],
                    "classes": [],
                    "file_path": "pkg/train.py",
                    "function_signatures": {"train_model": ["model", "dataset"]},
                    "function_details": {
                        "train_model": {
                            "parameters": ["model", "dataset"],
                            "parameter_details": [
                                {"name": "model", "annotation": "Any", "required": True},
                                {"name": "dataset", "annotation": "Any", "required": True},
                            ],
                        }
                    },
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def train_model(" not in code
    assert 'name="core"' in code


def test_fallback_uses_wrapper_candidates_when_available():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["normalize", "debug_helper"],
                    "classes": [],
                    "file_path": "pkg/tools.py",
                    "function_signatures": {
                        "normalize": ["value"],
                        "debug_helper": ["value"],
                    },
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def normalize(" in code
    assert "def debug_helper(" not in code


def test_fallback_respects_empty_wrapper_candidates():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["debug_helper"],
                    "classes": [],
                    "file_path": "pkg/tools.py",
                    "function_signatures": {"debug_helper": ["value"]},
                    "wrapper_candidates": [],
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def debug_helper(" not in code
    assert 'name="core"' in code


def test_fallback_skips_classes_with_required_constructor_arguments():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "sentiment",
                    "functions": [],
                    "classes": ["Analyzer"],
                    "file_path": "pkg/sentiment.py",
                    "class_details": {
                        "Analyzer": {
                            "constructor_requires_args": True,
                            "constructor_parameter_details": [
                                {"name": "model_path", "required": True, "annotation": "str"}
                            ],
                        }
                    },
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def analyzer():" not in code
    assert "Analyzer()" not in code
    assert 'name="core"' in code


def test_fallback_loads_hyphenated_module_path_by_file():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "december-measurements",
                    "module": "metrics",
                    "functions": ["calculate_metrics"],
                    "classes": [],
                    "function_signatures": {"calculate_metrics": ["value"]},
                    "file_path": "december-measurements/metrics.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    ast.parse(code)
    assert "import december-measurements" not in code
    assert "_load_module_from_file" in code
    assert "'december-measurements/metrics.py'" in code
    assert "target_dir = str(target.parent)" in code
    assert 'getattr(_code2mcp_module_december_measurements_metrics, "calculate_metrics", None)' in code


def test_fallback_uses_ast_parameter_types():
    analysis = {
        "repository_name": "humanize",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "src.humanize",
                    "module": "filesize",
                    "functions": ["naturalsize"],
                    "classes": [],
                    "function_signatures": {"naturalsize": ["value", "binary", "gnu", "format"]},
                    "function_details": {
                        "naturalsize": {
                            "parameter_details": [
                                {"name": "value", "annotation": "float | str", "required": True, "default": ""},
                                {"name": "binary", "annotation": "bool", "required": False, "default": "False"},
                                {"name": "gnu", "annotation": "bool", "required": False, "default": "False"},
                                {"name": "format", "annotation": "str", "required": False, "default": "'%.1f'"},
                            ]
                        }
                    },
                    "file_path": "src/humanize/filesize.py",
                },
                {
                    "package": "src.humanize",
                    "module": "lists",
                    "functions": ["natural_list"],
                    "classes": [],
                    "function_signatures": {"natural_list": ["items"]},
                    "function_details": {
                        "natural_list": {
                            "parameter_details": [
                                {"name": "items", "annotation": "list[Any]", "required": True, "default": ""},
                            ]
                        }
                    },
                    "file_path": "src/humanize/lists.py",
                },
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert 'def naturalsize(value: float | str = "", binary: bool = False, gnu: bool = False, format: str = \'%.1f\')' in code
    assert "def natural_list(items: list = None)" in code


def test_fallback_calls_keyword_only_parameters_by_name():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "search",
                    "module": "search",
                    "functions": ["find"],
                    "classes": [],
                    "function_signatures": {"find": ["query", "limit"]},
                    "function_details": {
                        "find": {
                            "parameter_details": [
                                {"name": "query", "kind": "positional", "annotation": "str", "required": True, "default": ""},
                                {"name": "limit", "kind": "keyword_only", "annotation": "int", "required": False, "default": "10"},
                            ]
                        }
                    },
                    "file_path": "search.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def find(query: str = \"\", limit: int = 10)" in code
    assert "result = _call_quietly(_code2mcp_target, [query], {'limit': limit})" in code


def test_fallback_skips_implicit_and_variadic_parameters_from_ast_details():
    analysis = {
        "repository_name": "demo",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "packs",
                    "module": "packs",
                    "functions": ["combine"],
                    "classes": [],
                    "function_signatures": {"combine": ["self", "value", "args", "kwargs"]},
                    "function_details": {
                        "combine": {
                            "parameters": ["value"],
                            "parameter_details": [
                                {"name": "value", "kind": "positional", "annotation": "int", "required": True, "default": ""},
                                {"name": "args", "kind": "vararg", "annotation": "", "required": False, "default": ""},
                                {"name": "kwargs", "kind": "kwarg", "annotation": "", "required": False, "default": ""},
                            ],
                        }
                    },
                    "file_path": "packs.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)

    assert "def combine(value: int = 0)" in code
    assert "args:" not in code
    assert "kwargs:" not in code
    assert "result = _call_quietly(_code2mcp_target, [value], {})" in code


def test_safe_path_helper_rejects_traversal(tmp_path):
    base = tmp_path / "source"
    base.mkdir()
    namespace = {}

    exec(_safe_path_helper_source(), namespace)
    safe_resolve_path = namespace["_safe_resolve_path"]

    allowed = safe_resolve_path(str(base), "data.csv")
    assert allowed.startswith(str(base))

    unsafe_cases = {
        "../secrets/national_id.csv": "Parent directory traversal is not allowed",
        "patient_data/../secrets/national_id.csv": "Parent directory traversal is not allowed",
        "secrets/national_id.csv": "Sensitive path segment is not allowed",
        "national_id.csv": "Sensitive path segment is not allowed",
        "api_key.json": "Sensitive path segment is not allowed",
        "dob.csv": "Sensitive path segment is not allowed",
        "mrn.csv": "Sensitive path segment is not allowed",
        "patient_data/stroke_clean.csv": "Sensitive path segment is not allowed",
        "patientName.csv": "Sensitive path segment is not allowed",
        "phi.json": "Sensitive path segment is not allowed",
        "passwords.txt": "Sensitive path segment is not allowed",
        "records/.hidden.csv": "Hidden path segments are not allowed",
        ".env": "Hidden path segments are not allowed",
        "https://example.com/data.csv": "URI/path schemes are not allowed",
        "file:///etc/passwd": "URI/path schemes are not allowed",
        "~/data.csv": "Home, UNC, and network paths are not allowed",
        r"C:\Users\demo\secret.csv": "Absolute paths are not allowed",
        "records/report.csv:secret": "Windows drive/stream separators are not allowed",
        "NUL.txt": "Reserved Windows device names are not allowed",
        "COM1.csv": "Reserved Windows device names are not allowed",
        "records/bad\x00name.csv": "Control characters are not allowed",
    }
    for raw_path, expected in unsafe_cases.items():
        try:
            safe_resolve_path(str(base), raw_path)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"unsafe path was not rejected: {raw_path}")


def test_generated_path_tool_rejects_patient_data_paths(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    source.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    (source / "records").mkdir()
    (source / "patient_data").mkdir()
    (source / "secrets").mkdir()
    (source / "patient_data" / "stroke_clean.csv").write_text("patient_id\np1\n", encoding="utf-8")
    (source / "records" / "stroke_clean.csv").write_text("return\n0.1\n", encoding="utf-8")
    (source / "secrets" / "national_id.csv").write_text("name,national_id\nAlice,123456\n", encoding="utf-8")
    (source / "reader.py").write_text(
        "def read_file(file_path):\n"
        "    with open(file_path, 'r', encoding='utf-8') as handle:\n"
        "        return handle.read()\n",
        encoding="utf-8",
    )
    (plugin_dir / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def tool(self, **_kwargs):\n"
        "        def decorator(func):\n"
        "            return func\n"
        "        return decorator\n"
        "    def run(self, **_kwargs):\n"
        "        return None\n",
        encoding="utf-8",
    )
    analysis = {
        "repository_name": "stroke",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "reader",
                    "module": "reader",
                    "functions": ["read_file"],
                    "classes": [],
                    "function_signatures": {"read_file": ["file_path"]},
                    "file_path": "reader.py",
                }
            ]
        },
    }

    code = _generate_mcp_service_fallback(analysis)
    namespace = {"__file__": str(plugin_dir / "mcp_service.py")}
    old_path = list(sys.path)
    try:
        sys.path[:] = [str(plugin_dir)] + [path for path in old_path if path != str(source)]
        exec(compile(code, str(plugin_dir / "mcp_service.py"), "exec"), namespace)
        allowed = namespace["read_file"]("records/stroke_clean.csv")
        blocked_cases = [
            namespace["read_file"]("patient_data/stroke_clean.csv"),
            namespace["read_file"]("records/../secrets/national_id.csv"),
            namespace["read_file"]("secrets/national_id.csv"),
            namespace["read_file"]("national_id.csv"),
            namespace["read_file"](".env"),
            namespace["read_file"]("file:///etc/passwd"),
            namespace["read_file"](r"C:\Users\demo\secret.csv"),
            namespace["read_file"]("records/report.csv:secret"),
            namespace["read_file"]("NUL.txt"),
            namespace["read_file"]("records/bad\x00name.csv"),
        ]
    finally:
        sys.path[:] = old_path

    assert allowed["success"] is True
    assert "return" in allowed["result"]
    assert all(blocked["success"] is False for blocked in blocked_cases)
    assert "Sensitive path segment is not allowed" in blocked_cases[0]["error"]
    assert "Parent directory traversal is not allowed" in blocked_cases[1]["error"]
    assert "Sensitive path segment is not allowed" in blocked_cases[2]["error"]
    assert "Sensitive path segment is not allowed" in blocked_cases[3]["error"]
    assert "Hidden path segments are not allowed" in blocked_cases[4]["error"]
    assert "URI/path schemes are not allowed" in blocked_cases[5]["error"]
    assert "Absolute paths are not allowed" in blocked_cases[6]["error"]
    assert "Windows drive/stream separators are not allowed" in blocked_cases[7]["error"]
    assert "Reserved Windows device names are not allowed" in blocked_cases[8]["error"]
    assert "Control characters are not allowed" in blocked_cases[9]["error"]
    assert "123456" not in str(blocked_cases)


def test_path_like_param_detection_avoids_profile_false_positive():
    assert _is_path_like_param("file_path")
    assert _is_path_like_param("input_file")
    assert _is_path_like_param("filename")
    assert not _is_path_like_param("profile")
    assert not _is_path_like_param("file_count")


def test_tool_contract_prompt_uses_verified_symbols_only():
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib.core",
                    "module": "core",
                    "file_path": "mathlib/core.py",
                    "functions": ["solve"],
                    "classes": ["Solver"],
                    "function_signatures": {"solve": ["expr"]},
                }
            ]
        }
    }

    contract = _tool_contract_for_prompt(analysis)

    assert "solve" in contract
    assert "Solver" in contract
    assert "mathlib/core.py" in contract
    assert "weather" not in contract


def test_adapter_import_fallback_is_valid_python():
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib.core",
                    "module": "core",
                    "functions": ["solve"],
                    "classes": ["Solver"],
                }
            ]
        }
    }

    code = _generate_adapter_import_fallback(analysis)

    ast.parse(code)
    assert "except Exception:" in code
    assert '"success": True' in code
    assert '"status": "success"' not in code
    assert '"status": "error"' not in code


def test_adapter_fallback_loads_hyphenated_module_path_by_file():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "bad-package",
                    "module": "tools",
                    "functions": ["slugify"],
                    "classes": [],
                    "file_path": "bad-package/tools.py",
                }
            ]
        },
    }

    code = _generate_adapter_import_fallback(analysis)

    ast.parse(code)
    assert "from bad-package" not in code
    assert "_load_module_from_file" in code
    assert "'bad-package/tools.py'" in code
    assert "def slugify(self, payload: Dict[str, Any])" in code


def test_adapter_fallbacks_use_semantic_success_contract():
    cli_code = _generate_adapter_cli_fallback({
        "llm_analysis": {
            "cli_commands": [{"name": "demo", "module": "demo.cli"}],
        }
    })
    blackbox_code = _generate_adapter_blackbox({})

    ast.parse(cli_code)
    ast.parse(blackbox_code)
    assert '"success": True' in cli_code
    assert '"success": False' in cli_code
    assert '"success": True' in blackbox_code
    assert '"success": False' in blackbox_code
    assert '"status": "success"' not in cli_code
    assert '"status": "error"' not in cli_code
    assert '"status": "warning"' not in cli_code
    assert '"status": "success"' not in blackbox_code
    assert '"status": "error"' not in blackbox_code
    assert '"status": "warning"' not in blackbox_code


def test_optional_adapter_and_readme_llm_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CODE2MCP_ADAPTER_LLM", raising=False)
    monkeypatch.delenv("CODE2MCP_README_LLM", raising=False)
    monkeypatch.setattr(
        generate_module,
        "get_llm_service",
        lambda: (_ for _ in ()).throw(AssertionError("LLM should not be called by default")),
    )
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "tools",
                    "module": "tools",
                    "functions": ["slugify"],
                    "classes": [],
                    "file_path": "tools.py",
                }
            ]
        },
    }

    ast.parse(_generate_adapter_import(analysis))
    assert _generate_readme_mcp(analysis).startswith("# demo MCP Plugin")


def test_generated_requirements_include_import_packages(tmp_path):
    analysis = {
        "dependencies": {"import_packages": ["numpy", "pandas"]},
        "llm_analysis": {"dependencies": {"required": []}},
    }

    requirements = _generate_requirements_txt(analysis, str(tmp_path))

    assert "numpy" in requirements
    assert "pandas" in requirements


def test_fallback_default_core_is_valid_python():
    analysis = {
        "repository_name": "empty",
        "dependencies": {"pyproject": False},
        "structure": {"packages": []},
        "llm_analysis": {"core_modules": []},
    }

    code = _generate_mcp_service_fallback(analysis)

    ast.parse(code)
    assert "def core(payload: dict = None)" in code
    assert '@mcp.tool(name="core"' in code


def test_service_quality_gate_rejects_varargs_unrelated_and_unguarded_paths():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["load_data"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="weather", description="unrelated")
def weather(*args, file_path: str = "", **kwargs):
    return {"success": True}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("not backed by analysis_result" in error for error in errors)
    assert any("uses *args" in error for error in errors)
    assert any("uses **kwargs" in error for error in errors)
    assert any("without safe resolution" in error for error in errors)


def test_service_quality_gate_rejects_sensitive_tool_parameters():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "client",
                    "functions": ["call_api"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="call_api", description="call")
def call_api(query: str = "", api_key: str = ""):
    return {"success": True, "result": query, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("sensitive-looking parameters" in error and "api_key" in error for error in errors)


def test_service_quality_gate_rejects_untyped_tool_parameters():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="add", description="add")
def add(a, b: int = 0):
    return {"success": True, "result": a + b, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("untyped parameters" in error and "a" in error for error in errors)


def test_service_quality_gate_rejects_tool_without_backing_symbol_reference():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    return {"success": True, "result": add(a, b), "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("does not reference backing analysis symbol" in error and "add" in error for error in errors)


def test_service_quality_gate_allows_import_alias_backing_symbol_reference():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
from mathlib import add as add_impl

mcp = FastMCP("demo")

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    return {"success": True, "result": add_impl(a, b), "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)


def test_service_quality_gate_rejects_nested_unused_backing_symbol_call():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
from mathlib import add as add_impl

mcp = FastMCP("demo")

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    def unused_helper():
        return add_impl(a, b)
    return {"success": True, "result": a + b, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("does not reference backing analysis symbol" in error and "add" in error for error in errors)


def test_service_quality_gate_rejects_discarded_backing_symbol_result():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
from mathlib import add as add_impl

mcp = FastMCP("demo")

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    _ignored = add_impl(a, b)
    return {"success": True, "result": a + b, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("returned value" in error and "add" in error for error in errors)


def test_service_quality_gate_rejects_unused_getattr_backing_symbol_reference():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP

mcp = FastMCP("demo")

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    _unused = getattr(object(), "add", None)
    return {"success": True, "result": a + b, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("does not reference backing analysis symbol" in error and "add" in error for error in errors)


def test_service_quality_gate_rejects_local_getattr_backing_symbol_call():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP

mcp = FastMCP("demo")
_fake = type("Fake", (), {"add": staticmethod(lambda a, b: a + b)})

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    target = getattr(_fake, "add")
    return {"success": True, "result": target(a, b), "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("does not reference backing analysis symbol" in error and "add" in error for error in errors)


def test_service_quality_gate_allows_loader_getattr_backing_symbol_call():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "mathlib",
                    "module": "mathlib",
                    "functions": ["add"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP

mcp = FastMCP("demo")
_module = _load_module_from_file("_module", "mathlib.py")

@mcp.tool(name="add", description="add")
def add(a: int, b: int):
    target = getattr(_module, "add")
    return {"success": True, "result": target(a, b), "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)


def test_service_quality_gate_rejects_tool_runtime_side_effects():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["run_job"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
import pathlib
import requests as rq
import subprocess
import urllib.request
import webbrowser
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="run_job", description="run")
def run_job():
    subprocess.run(["echo", "ok"], capture_output=True)
    subprocess.getoutput("echo ok")
    os.startfile("report.txt")
    rq.get("https://example.com")
    urllib.request.urlretrieve("https://example.com/report.csv", "report.csv")
    webbrowser.open("https://example.com")
    pathlib.Path("report.txt").write_text("done")
    return {"success": True, "result": "done", "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any(
        "unsafe runtime operations" in error
        and "can execute external processes" in error
        and "performs network requests" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_network_client_constructors():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["fetch_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import httpx
import requests as rq
import aiohttp
from aiohttp import ClientSession
from requests import Session
from fastmcp import FastMCP
from ops import fetch_status as fetch_status_impl
mcp = FastMCP("demo")

@mcp.tool(name="fetch_status", description="fetch")
def fetch_status(url: str = ""):
    result = fetch_status_impl(url)
    aio_session = aiohttp.ClientSession()
    aio_session.closed
    aio_alias_session = ClientSession()
    aio_alias_session.closed
    rq.Session().get(url)
    client = Session()
    client.get(url)
    with httpx.Client() as http_client:
        http_client.get(url)
    httpx.Client().post(url, json={})
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_direct_network_request_methods():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["fetch_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import httpx
import aiohttp
import requests
import requests as rq
from aiohttp import request as aiohttp_request
from httpx import request as httpx_request
from requests import head as requests_head
from fastmcp import FastMCP
from ops import fetch_status as fetch_status_impl
mcp = FastMCP("demo")

@mcp.tool(name="fetch_status", description="fetch")
def fetch_status(url: str = ""):
    result = fetch_status_impl(url)
    aiohttp.request("GET", url)
    aiohttp_request("POST", url, json={})
    requests.head(url)
    rq.options(url)
    requests.request("GET", url)
    requests_head(url)
    httpx.head(url)
    httpx.options(url)
    httpx_request("GET", url)
    with httpx.stream("GET", url) as response:
        response.read()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_url_opener_network_clients():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["fetch_bytes"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import urllib.request
import urllib3
from urllib.request import build_opener
from urllib3 import request as urllib3_request_alias
from fastmcp import FastMCP
from ops import fetch_bytes as fetch_bytes_impl
mcp = FastMCP("demo")

@mcp.tool(name="fetch_bytes", description="fetch")
def fetch_bytes(url: str = ""):
    result = fetch_bytes_impl(url)
    opener = urllib.request.build_opener()
    opener.open(url)
    alias_opener = build_opener()
    alias_opener.open(url)
    manager = urllib3.PoolManager()
    manager.request("GET", url)
    proxy = urllib3.ProxyManager("http://proxy.example")
    proxy.request("GET", url)
    urllib3.request("GET", url)
    urllib3_request_alias("POST", url)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_getattr_runtime_side_effects():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["status_code"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
import subprocess
import tempfile
import urllib.request as url_request
from fastmcp import FastMCP
from ops import status_code as status_code_impl
mcp = FastMCP("demo")

@mcp.tool(name="status_code", description="status")
def status_code():
    result = status_code_impl()
    getattr(os, "system")("echo ok")
    runner = getattr(subprocess, "run")
    runner(["echo", "ok"], capture_output=True)
    getattr(url_request, "urlretrieve")("https://example.com/a", "a")
    getattr(tempfile, "mkdtemp")()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "can execute external processes" in error
        and "performs network requests" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_partial_runtime_side_effects():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["status_code"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import functools
import os
import subprocess
import tempfile
import urllib.request as url_request
from functools import partial
from fastmcp import FastMCP
from ops import status_code as status_code_impl
mcp = FastMCP("demo")

@mcp.tool(name="status_code", description="status")
def status_code():
    result = status_code_impl()
    functools.partial(os.system, "echo ok")()
    runner = partial(subprocess.run, ["echo", "ok"], capture_output=True)
    runner()
    downloader = functools.partial(url_request.urlretrieve, "https://example.com/a", "a")
    downloader()
    maker = partial(tempfile.mkdtemp)
    maker()
    hidden_runner = functools.partial(getattr(os, "system"), "echo ok")
    hidden_runner()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "can execute external processes" in error
        and "performs network requests" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_dynamic_code_execution():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["formula_value"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import builtins
from builtins import eval as eval_expression
from fastmcp import FastMCP
from ops import formula_value as formula_value_impl
mcp = FastMCP("demo")

@mcp.tool(name="formula_value", description="formula")
def formula_value(expression: str = ""):
    result = formula_value_impl(expression)
    eval(expression)
    builtins.exec(expression)
    compile(expression, "<user>", "exec")
    eval_expression(expression)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error and "can execute dynamic code" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_dynamic_import_runtime_side_effects():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "ops",
                    "module": "ops",
                    "functions": ["alpha_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import importlib
from importlib import import_module
from fastmcp import FastMCP
from ops import alpha_status as alpha_status_impl
mcp = FastMCP("demo")

@mcp.tool(name="alpha_status", description="status")
def alpha_status():
    result = alpha_status_impl()
    __import__("os").system("echo ok")
    importlib.import_module("urllib.request").urlretrieve("https://example.com/a", "a")
    runtime_tempfile = import_module("tempfile")
    runtime_tempfile.mkdtemp()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "can execute external processes" in error
        and "performs network requests" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_runtime_file_reads():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["load_data"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import configparser
import bz2
import glob
import gzip
import h5py
import joblib
import lzma
import numpy as np
import os
import pickle
from builtins import open as read_file
from io import open as io_read_file
from pathlib import Path
import pandas as pd
import sqlite3
import tarfile
import torch as th
import zipfile
from gzip import open as gzip_open_alias
from scipy.io import loadmat as load_matrix
from fastmcp import FastMCP
from loader import load_data as load_data_impl
mcp = FastMCP("demo")

@mcp.tool(name="load_data", description="load")
def load_data(resource: str):
    text = Path(resource).read_text()
    table = pd.read_csv(resource)
    pickle_table = pd.read_pickle("cache.pkl")
    model = joblib.load("model.joblib")
    weights = th.load("weights.pt")
    matrix = load_matrix("matrix.mat")
    memmap_values = np.memmap("data.npy", dtype="float32", mode="r")[:3].tolist()
    pickled = pickle.load(resource)
    with h5py.File("data.h5", "r") as hdf:
        hdf_keys = list(hdf.keys())
    names = os.listdir(resource)
    matches = glob.glob(f"{resource}/*.csv")
    parser = configparser.ConfigParser()
    parser.read("settings.ini")
    with zipfile.ZipFile("data.zip") as archive:
        archive_names = archive.namelist()
    with gzip.open("records.csv.gz", "rb") as archive:
        gzip_preview = archive.read(10)
    with gzip_open_alias("records.csv.gz", "rb") as archive:
        gzip_alias_preview = archive.read(10)
    with bz2.open("records.csv.bz2", "rb") as archive:
        bz2_preview = archive.read(10)
    with lzma.open("records.csv.xz", "rb") as archive:
        lzma_preview = archive.read(10)
    with tarfile.open("records.tar") as archive:
        tar_names = archive.getnames()
    conn = sqlite3.connect("records.db")
    try:
        record_count = conn.execute("select count(*) from records").fetchone()[0]
    finally:
        conn.close()
    with open(resource) as handle:
        preview = handle.read(10)
    with read_file(resource) as handle:
        alias_preview = handle.read(10)
    with io_read_file(resource) as handle:
        io_alias_preview = handle.read(10)
    return {
        "success": True,
        "result": load_data_impl(
            text,
            list(table.columns),
            pickle_table,
            model,
            weights,
            matrix,
            memmap_values,
            pickled,
            hdf_keys,
            names,
            matches,
            parser.sections(),
            archive_names,
            gzip_preview,
            gzip_alias_preview,
            bz2_preview,
            lzma_preview,
            tar_names,
            record_count,
            preview,
            alias_preview,
            io_alias_preview,
        ),
        "error": None,
    }

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "reads files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_implicit_file_reads():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["load_lines"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import fileinput
import linecache
import tokenize
from fileinput import FileInput, input as fileinput_input_alias
from linecache import getline as linecache_getline_alias
from tokenize import open as tokenize_open_alias
from fastmcp import FastMCP
from loader import load_lines as load_lines_impl
mcp = FastMCP("demo")

@mcp.tool(name="load_lines", description="load")
def load_lines():
    fileinput_lines = list(fileinput.input("settings.ini"))
    alias_lines = list(fileinput_input_alias("settings.ini"))
    with fileinput.FileInput("settings.ini") as lines:
        class_lines = list(lines)
    class_input_lines = list(FileInput.input(files="settings.ini"))
    first_line = linecache.getline("settings.ini", 1)
    cached_lines = linecache.getlines("settings.ini")
    alias_line = linecache_getline_alias("settings.ini", 1)
    with tokenize.open("script.py") as handle:
        tokenize_line = handle.readline()
    with tokenize_open_alias("script.py") as handle:
        tokenize_alias_line = handle.readline()
    return {
        "success": True,
        "result": load_lines_impl(
            fileinput_lines,
            alias_lines,
            class_lines,
            class_input_lines,
            first_line,
            cached_lines,
            alias_line,
            tokenize_line,
            tokenize_alias_line,
        ),
        "error": None,
    }

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "reads files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_file_backed_store_opens():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["load_keys"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import dbm
import dbm.dumb
import shelve
from shelve import open as shelve_open_alias
from fastmcp import FastMCP
from loader import load_keys as load_keys_impl
mcp = FastMCP("demo")

@mcp.tool(name="load_keys", description="load")
def load_keys():
    with shelve.open("cache.db") as store:
        shelve_keys = list(store.keys())
    with shelve_open_alias("cache.db") as store:
        shelve_alias_keys = list(store.keys())
    with dbm.open("cache.db", "c") as store:
        dbm_keys = list(store.keys())
    with dbm.dumb.open("cache.db", "c") as store:
        dumb_keys = list(store.keys())
    return {
        "success": True,
        "result": load_keys_impl(shelve_keys, shelve_alias_keys, dbm_keys, dumb_keys),
        "error": None,
    }

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_path_object_alias_file_reads():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["list_data"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from pathlib import Path
import pathlib
import os
from os.path import exists as path_exists_alias, getsize as path_size, isfile as path_is_file
from fastmcp import FastMCP
from loader import list_data as list_data_impl
mcp = FastMCP("demo")

@mcp.tool(name="list_data", description="list")
def list_data():
    direct = [item.name for item in Path("data").iterdir()]
    directory = Path("data")
    names = [item.name for item in directory.glob("*.csv")]
    nested = pathlib.Path("data")
    all_names = [item.name for item in nested.rglob("*.csv")]
    cwd_names = [item.name for item in Path.cwd().iterdir()]
    home = Path.home()
    home_text = (home / "settings.ini").read_text()
    config = home / "extra.ini"
    config_text = config.read_text()
    resolved_names = [item.name for item in Path("data").resolve().iterdir()]
    expanded = pathlib.Path("~").expanduser()
    expanded_names = [item.name for item in expanded.glob("*.csv")]
    parent_names = [item.name for item in Path("data/file.txt").parent.iterdir()]
    parents_names = [item.name for item in Path("data/file.txt").parents[0].iterdir()]
    metadata = [
        Path("settings.ini").exists(),
        Path("settings.ini").is_file(),
        Path("settings.ini").stat().st_size,
        os.path.getsize("settings.ini"),
        os.stat("settings.ini").st_size,
        path_size("settings.ini"),
        path_exists_alias("settings.ini"),
        path_is_file("settings.ini"),
    ]
    result = list_data_impl()
    return {"success": True, "result": direct + names + all_names + cwd_names + resolved_names + expanded_names + parent_names + parents_names + metadata + [home_text, config_text] + result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "reads files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_path_open_write_modes():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "writer",
                    "module": "writer",
                    "functions": ["write_report"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from pathlib import Path
import pathlib
from fastmcp import FastMCP
from writer import write_report as write_report_impl
mcp = FastMCP("demo")

@mcp.tool(name="write_report", description="write")
def write_report(text: str) -> dict:
    direct = Path("report.txt").open("w")
    direct.close()
    report = Path("report.txt")
    appended = report.open("a")
    appended.close()
    exclusive = pathlib.Path("report.txt").open("x")
    exclusive.close()
    result = write_report_impl(text)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "opens files in write/append mode" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_os_descriptor_writes():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "writer",
                    "module": "writer",
                    "functions": ["write_descriptor"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
from os import O_CREAT, O_WRONLY, fdopen as wrap_fd, open as low_open
from fastmcp import FastMCP
from writer import write_descriptor as write_descriptor_impl
mcp = FastMCP("demo")

@mcp.tool(name="write_descriptor", description="write")
def write_descriptor(text: str) -> dict:
    direct = os.fdopen(1, "w")
    direct.close()
    alias = wrap_fd(1, mode="a")
    alias.close()
    fd = os.open("report.txt", os.O_WRONLY | os.O_CREAT)
    os.close(fd)
    alias_fd = low_open("report.txt", O_WRONLY | O_CREAT)
    os.close(alias_fd)
    result = write_descriptor_impl(text)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "opens files in write/append mode" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_mode_sensitive_file_open_writes():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "archiver",
                    "module": "archiver",
                    "functions": ["build_archive"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import gzip
import h5py
import io
import tarfile
import zipfile
from fastmcp import FastMCP
from archiver import build_archive as build_archive_impl
mcp = FastMCP("demo")

@mcp.tool(name="build_archive", description="archive")
def build_archive(name: str) -> dict:
    compressed = gzip.open("report.gz", "wb")
    compressed.close()
    archive = tarfile.open("report.tar", "w")
    archive.close()
    zipped = zipfile.ZipFile("report.zip", "w")
    zipped.close()
    h5 = h5py.File("report.h5", "w")
    h5.close()
    binary = io.FileIO("report.bin", "w")
    binary.close()
    result = build_archive_impl(name)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "opens files in write/append mode" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_runtime_file_exports():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "reporter",
                    "module": "reporter",
                    "functions": ["export_report"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import pandas as pd
import numpy as np
import polars as pl
import joblib
import torch as th
import matplotlib.pyplot as plt
import os
import shutil
from PIL import Image
from pathlib import Path
from scipy.io import savemat as save_matrix
from fastmcp import FastMCP
from reporter import export_report as export_report_impl
mcp = FastMCP("demo")

@mcp.tool(name="export_report", description="export")
def export_report() -> dict:
    archive = export_report_impl()
    archive.extractall("./unpacked")
    shutil.copytree("assets", "assets_copy")
    shutil.make_archive("bundle", "zip", "assets")
    os.chmod("report.txt", 0o600)
    os.link("report.txt", "report.link")
    Path("report.symlink").symlink_to("report.txt")
    Path("report.txt").chmod(0o600)
    frame = pd.DataFrame({"value": [1, 2]})
    frame.to_csv("report.csv", index=False)
    frame.to_json(path_or_buf="report.json")
    frame.to_html("report.html")
    frame.to_markdown(buf="report.md")
    frame.to_latex(buf="report.tex")
    frame.to_xml(path_or_buffer="report.xml")
    frame.to_excel("report.xlsx")
    frame.to_parquet("report.parquet")
    frame.to_pickle("report.pkl")
    np.savez("arrays.npz", values=np.array([1, 2]))
    np.savetxt("arrays.csv", np.array([1, 2]))
    joblib.dump({"value": [1, 2]}, "model.joblib")
    th.save({"value": [1, 2]}, "weights.pt")
    save_matrix("matrix.mat", {"values": [1, 2]})
    pl.DataFrame({"value": [1, 2]}).write_parquet("polars.parquet")
    Image.new("RGB", (1, 1)).save("preview.png")
    plt.savefig("chart.png")
    return {"success": True, "result": archive, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_tempfile_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "temp_tools",
                    "module": "temp_tools",
                    "functions": ["make_temp_artifact"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import tempfile
from fastmcp import FastMCP
from tempfile import NamedTemporaryFile, TemporaryDirectory, mkdtemp, mkstemp
from temp_tools import make_temp_artifact as make_temp_artifact_impl
mcp = FastMCP("demo")

@mcp.tool(name="make_temp_artifact", description="temp")
def make_temp_artifact() -> dict:
    result = make_temp_artifact_impl()
    handle = tempfile.NamedTemporaryFile(delete=False)
    handle.close()
    alias_handle = NamedTemporaryFile(delete=False)
    alias_handle.close()
    with TemporaryDirectory() as directory:
        temp_dir = directory
    _fd, temp_path = mkstemp()
    another_dir = mkdtemp()
    return {
        "success": True,
        "result": [result, handle.name, alias_handle.name, temp_dir, temp_path, another_dir],
        "error": None,
    }

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates files or directories" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_runtime_environment_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "settings",
                    "module": "settings",
                    "functions": ["normalize_mode"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
from fastmcp import FastMCP
from settings import normalize_mode as normalize_mode_impl
mcp = FastMCP("demo")

@mcp.tool(name="normalize_mode", description="normalize")
def normalize_mode(value: str) -> dict:
    result = normalize_mode_impl(value)
    os.environ["APP_MODE"] = value
    os.putenv("APP_LOCALE", value)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process environment" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_runtime_state_alias_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "settings",
                    "module": "settings",
                    "functions": ["normalize_mode"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
import sys
from fastmcp import FastMCP
from settings import normalize_mode as normalize_mode_impl
mcp = FastMCP("demo")

@mcp.tool(name="normalize_mode", description="normalize")
def normalize_mode(value: str) -> dict:
    result = normalize_mode_impl(value)
    env = os.environ
    env["APP_MODE"] = value
    paths = sys.path
    paths.append(value)
    modules = sys.modules
    modules.pop(value, None)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process environment" in error
        and "mutates process state" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_getattr_runtime_state_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "settings",
                    "module": "settings",
                    "functions": ["normalize_mode"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
import sys
from functools import partial
from fastmcp import FastMCP
from settings import normalize_mode as normalize_mode_impl
mcp = FastMCP("demo")

@mcp.tool(name="normalize_mode", description="normalize")
def normalize_mode(value: str) -> dict:
    result = normalize_mode_impl(value)
    getattr(os, "environ").update({"APP_MODE": value})
    getattr(os, "environ")["APP_LOCALE"] = value
    env_update = getattr(os, "environ").update
    env_update({"APP_THEME": value})
    deferred_env_update = partial(getattr(os, "environ").update, {"APP_REGION": value})
    deferred_env_update()
    paths = getattr(sys, "path")
    paths.append(value)
    modules = getattr(sys, "modules")
    modules.pop(value, None)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process environment" in error
        and "mutates process state" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_reflected_runtime_state_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "settings",
                    "module": "settings",
                    "functions": ["normalize_mode"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
import sys
from fastmcp import FastMCP
from settings import normalize_mode as normalize_mode_impl
mcp = FastMCP("demo")

@mcp.tool(name="normalize_mode", description="normalize")
def normalize_mode(value: str) -> dict:
    result = normalize_mode_impl(value)
    setattr(os, "environ", {"APP_MODE": value})
    setattr(sys, "path", [value])
    delattr(sys, "modules")
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process environment" in error
        and "mutates process state" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_process_state_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "state_tools",
                    "module": "state_tools",
                    "functions": ["select_workspace"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import os
from fastmcp import FastMCP
from state_tools import select_workspace as select_workspace_impl
mcp = FastMCP("demo")

@mcp.tool(name="select_workspace", description="select")
def select_workspace() -> dict:
    result = select_workspace_impl()
    os.chdir("workspace")
    os.umask(0o077)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process state" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_runtime_global_mutation():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "runtime_tools",
                    "module": "runtime_tools",
                    "functions": ["add_runtime_import_path", "configure_warnings", "configure_logging"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import logging
import sys
import warnings
from fastmcp import FastMCP
from runtime_tools import add_runtime_import_path as add_runtime_import_path_impl
from runtime_tools import configure_logging as configure_logging_impl
from runtime_tools import configure_warnings as configure_warnings_impl
mcp = FastMCP("demo")

@mcp.tool(name="add_runtime_import_path", description="add path")
def add_runtime_import_path() -> dict:
    result = add_runtime_import_path_impl()
    sys.path.insert(0, "plugins")
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="configure_warnings", description="warnings")
def configure_warnings() -> dict:
    result = configure_warnings_impl()
    warnings.filterwarnings("ignore")
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="configure_logging", description="logging")
def configure_logging() -> dict:
    result = configure_logging_impl()
    logging.basicConfig(level=logging.INFO)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process state" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_runtime_callback_registration():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "callback_tools",
                    "module": "callback_tools",
                    "functions": ["status_message", "terminal_message"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import atexit
import signal
from fastmcp import FastMCP
from callback_tools import status_message as status_message_impl
from callback_tools import terminal_message as terminal_message_impl
mcp = FastMCP("demo")

def _cleanup(*args):
    return None

@mcp.tool(name="status_message", description="status")
def status_message() -> dict:
    result = status_message_impl()
    atexit.register(_cleanup)
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="terminal_message", description="terminal")
def terminal_message() -> dict:
    result = terminal_message_impl()
    signal.signal(signal.SIGTERM, _cleanup)
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "mutates process state" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_background_execution():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "background_tools",
                    "module": "background_tools",
                    "functions": ["cache_refresh", "task_refresh"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import asyncio
import threading
from fastmcp import FastMCP
from background_tools import cache_refresh as cache_refresh_impl
from background_tools import task_refresh as task_refresh_impl
mcp = FastMCP("demo")

def _worker():
    return None

@mcp.tool(name="cache_refresh", description="refresh")
def cache_refresh() -> dict:
    result = cache_refresh_impl()
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="task_refresh", description="refresh")
def task_refresh() -> dict:
    result = task_refresh_impl()
    asyncio.create_task(asyncio.sleep(0))
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "starts background execution" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_executor_background_execution():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pool_tools",
                    "module": "pool_tools",
                    "functions": ["parallel_status", "raw_thread_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import _thread
import concurrent.futures as futures
from fastmcp import FastMCP
from pool_tools import parallel_status as parallel_status_impl
from pool_tools import raw_thread_status as raw_thread_status_impl
mcp = FastMCP("demo")

def _worker(value="ok"):
    return value

@mcp.tool(name="parallel_status", description="parallel")
def parallel_status() -> dict:
    result = parallel_status_impl()
    with futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(_worker).result()
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="raw_thread_status", description="raw")
def raw_thread_status() -> dict:
    result = raw_thread_status_impl()
    _thread.start_new_thread(_worker, ())
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "starts background execution" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_socket_network_operations():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "socket_tools",
                    "module": "socket_tools",
                    "functions": ["endpoint_status", "remote_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import socket
from fastmcp import FastMCP
from socket_tools import endpoint_status as endpoint_status_impl
from socket_tools import remote_status as remote_status_impl
mcp = FastMCP("demo")

@mcp.tool(name="endpoint_status", description="endpoint")
def endpoint_status() -> dict:
    result = endpoint_status_impl()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.close()
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="remote_status", description="remote")
def remote_status() -> dict:
    result = remote_status_impl()
    conn = socket.create_connection(("example.com", 80), timeout=1)
    conn.close()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_server_network_operations():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "server_tools",
                    "module": "server_tools",
                    "functions": ["local_status", "wsgi_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import http.server
from fastmcp import FastMCP
from server_tools import local_status as local_status_impl
from server_tools import wsgi_status as wsgi_status_impl
from wsgiref.simple_server import make_server
mcp = FastMCP("demo")

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        pass

def wsgi_app(environ, start_response):
    return []

@mcp.tool(name="local_status", description="local")
def local_status() -> dict:
    result = local_status_impl()
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.server_close()
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="wsgi_status", description="wsgi")
def wsgi_status() -> dict:
    result = wsgi_status_impl()
    server = make_server("127.0.0.1", 0, wsgi_app)
    server.server_close()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_protocol_network_clients():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "protocol_tools",
                    "module": "protocol_tools",
                    "functions": ["http_status", "smtp_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import http.client
import smtplib
from fastmcp import FastMCP
from protocol_tools import http_status as http_status_impl
from protocol_tools import smtp_status as smtp_status_impl
mcp = FastMCP("demo")

@mcp.tool(name="http_status", description="http")
def http_status() -> dict:
    result = http_status_impl()
    conn = http.client.HTTPConnection("example.com")
    conn.request("GET", "/")
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="smtp_status", description="smtp")
def smtp_status() -> dict:
    result = smtp_status_impl()
    smtp = smtplib.SMTP("mail.example.com")
    smtp.sendmail("from@example.com", ["to@example.com"], "hello")
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_tool_datastore_network_clients():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "datastore_tools",
                    "module": "datastore_tools",
                    "functions": ["redis_status", "mongo_status", "postgres_status"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
import psycopg2
import pymongo
import redis
from datastore_tools import mongo_status as mongo_status_impl
from datastore_tools import postgres_status as postgres_status_impl
from datastore_tools import redis_status as redis_status_impl
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="redis_status", description="redis")
def redis_status() -> dict:
    result = redis_status_impl()
    client = redis.Redis(host="localhost", port=6379)
    client.get("key")
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="mongo_status", description="mongo")
def mongo_status() -> dict:
    result = mongo_status_impl()
    client = pymongo.MongoClient("mongodb://localhost:27017")
    client.admin.command("ping")
    return {"success": True, "result": result, "error": None}

@mcp.tool(name="postgres_status", description="postgres")
def postgres_status() -> dict:
    result = postgres_status_impl()
    conn = psycopg2.connect(host="localhost", dbname="demo")
    conn.cursor()
    return {"success": True, "result": result, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert not any("does not reference backing analysis symbol" in error for error in errors)
    assert any(
        "unsafe runtime operations" in error
        and "performs network requests" in error
        for error in errors
    )


def test_service_quality_gate_rejects_incomplete_path_guard():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "loader",
                    "module": "loader",
                    "functions": ["load_data"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

def _safe_resolve_path(base_dir, user_path):
    _messages = (
        "Absolute paths are not allowed",
        "Hidden path segments are not allowed",
        "Parent directory traversal is not allowed",
        "Sensitive path segment is not allowed",
        "URI/path schemes are not allowed",
    )
    return user_path

@mcp.tool(name="load_data", description="load")
def load_data(file_path: str = ""):
    file_path = _safe_resolve_path("/tmp/source", file_path)
    return {"success": True, "result": file_path, "error": None}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("failed runtime policy checks" in error for error in errors)
    assert any("parent traversal was accepted" in error for error in errors)
    assert any("sensitive path segment was accepted" in error for error in errors)


def test_service_quality_gate_rejects_project_root_file_loader():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "main",
                    "functions": ["run"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from pathlib import Path
from fastmcp import FastMCP
mcp = FastMCP("demo")
project_root = "/tmp/project"

def _load_module_from_file(alias, relative_file_path):
    base = Path(project_root).resolve()
    raise ImportError("Module path escapes project directory")

@mcp.tool(name="run", description="run")
def run():
    return {"success": True}

def create_app():
    return mcp
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("source_path" in error and "project_root" in error for error in errors)


def test_service_quality_gate_rejects_duplicate_app_and_create_app():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "main",
                    "functions": ["run"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")
backup = FastMCP("backup")

@mcp.tool(name="run", description="run")
def run():
    return {"success": True}

def create_app():
    return mcp

def create_app():
    return backup
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("exactly one FastMCP app instance" in error for error in errors)
    assert any("exactly one create_app" in error for error in errors)


def test_service_quality_gate_requires_create_app_to_return_app_instance():
    analysis = {
        "repository_name": "demo",
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "main",
                    "functions": ["run"],
                    "classes": [],
                }
            ]
        },
    }
    code = '''
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="run", description="run")
def run():
    return {"success": True}

def create_app():
    return object()
'''

    errors = _validate_mcp_service_source(code, analysis)

    assert any("create_app() must return the FastMCP app instance" in error for error in errors)
