from pathlib import Path

import json

import src.nodes.analysis_node as analysis_module
from src.nodes.analysis_node import (
    _analyze_with_llm,
    _scan_common_import_packages,
    _scan_python_packages,
    _scan_source_symbols_with_signatures,
    _summarize_source_tree,
)


def test_ast_scan_excludes_generated_output(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "real_module.py").write_text("def real_tool(file_path):\n    return file_path\n", encoding="utf-8")
    generated = source / "mcp_output"
    generated.mkdir()
    (generated / "fake_module.py").write_text("def fake_tool():\n    return 1\n", encoding="utf-8")

    symbols = _scan_source_symbols_with_signatures(str(source))

    assert "real_module" in symbols
    assert "fake_module" not in symbols
    assert symbols["real_module"]["file_path"] == "real_module.py"


def test_ast_scan_preserves_posix_source_paths_for_nested_modules(tmp_path):
    source = tmp_path / "source"
    package = source / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "core.py").write_text(
        "def normalize_symbol(symbol: str) -> str:\n"
        "    return symbol.upper()\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))

    assert "pkg.core" in symbols
    assert symbols["pkg.core"]["file_path"] == "pkg/core.py"


def test_analysis_scans_exclude_cache_and_dependency_dirs(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "real_module.py").write_text(
        "import requests\n\n"
        "def real_tool(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (source / ".hidden_tool.py").write_text(
        "import pandas\n\n"
        "def hidden_tool():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    excluded_dirs = (
        ".tox",
        ".ruff_cache",
        "histories",
        "history",
        "node_modules",
        "generated",
        "sample",
        "samples",
        "site-packages",
        "tutorial",
        "tutorials",
    )
    for dirname in excluded_dirs:
        fake_dir = source / dirname
        fake_dir.mkdir()
        (fake_dir / "__init__.py").write_text("", encoding="utf-8")
        (fake_dir / "fake_module.py").write_text(
            "import pandas\n\n"
            "def fake_tool():\n"
            "    return 1\n",
            encoding="utf-8",
        )

    symbols = _scan_source_symbols_with_signatures(str(source))
    summary = _summarize_source_tree(str(source), "file:///tmp/local-project")
    packages = _scan_python_packages(str(source))
    import_packages = _scan_common_import_packages(str(source))

    assert list(symbols) == ["real_module"]
    assert "real_module.py" in summary["file_tree"]
    assert ".hidden_tool.py" not in summary["file_tree"]
    assert all(
        f"{dirname}/fake_module.py" not in summary["file_tree"]
        for dirname in excluded_dirs
    )
    assert packages == []
    assert import_packages == ["requests"]


def test_ast_scan_excludes_examples_tests_conftest_and_fixtures(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
    example_dir = source / "example"
    example_dir.mkdir()
    (example_dir / "demo.py").write_text("def fake_example():\n    return 1\n", encoding="utf-8")
    tests_dir = source / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_api.py").write_text("def fake_test():\n    return 1\n", encoding="utf-8")
    (source / "conftest.py").write_text("def fake_conftest():\n    return 1\n", encoding="utf-8")
    (source / "helpers.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef sample_fixture():\n    return 1\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    summary = _summarize_source_tree(str(source), "file:///tmp/local-project")

    assert list(symbols) == ["api"]
    assert "api.py" in summary["file_tree"]
    assert "example/demo.py" not in summary["file_tree"]
    assert "tests/test_api.py" not in summary["file_tree"]
    assert "conftest.py" not in summary["file_tree"]


def test_ast_scan_excludes_cli_script_directories(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
    bin_dir = source / "bin"
    bin_dir.mkdir()
    (bin_dir / "tool.py").write_text("def getParser():\n    return None\n", encoding="utf-8")
    scripts_dir = source / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "maintenance.py").write_text("def clean_cache():\n    return None\n", encoding="utf-8")

    symbols = _scan_source_symbols_with_signatures(str(source))
    summary = _summarize_source_tree(str(source), "file:///tmp/local-project")

    assert list(symbols) == ["api"]
    assert "api.py" in summary["file_tree"]
    assert "bin/tool.py" not in summary["file_tree"]
    assert "scripts/maintenance.py" not in summary["file_tree"]


def test_ast_scan_records_function_metadata_and_candidates(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
import torch

def load_data(file_path: str, limit: int = 10) -> dict:
    """Load user supplied data."""
    return {"file_path": file_path, "limit": limit}

def call_api(query: str, api_key: str | None = None) -> str:
    """Call a remote API."""
    return query

def ask_value():
    """Ask a value from stdin."""
    return input("value: ")

def test_helper(value):
    return value

class Processor:
    """Reusable processor."""

    def run(self, text: str) -> str:
        return text

class NeedsConfig:
    def __init__(self, config):
        self.config = config

class OptionalTokenClient:
    def __init__(self, auth_token: str | None = None):
        self.auth_token = auth_token

    def ping(self) -> str:
        return "pong"
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert module["functions"] == {"load_data": ["file_path", "limit"], "call_api": ["query", "api_key"], "ask_value": []}
    assert "test_helper" not in module["functions"]
    detail = module["function_details"]["load_data"]
    assert detail["return_annotation"] == "dict"
    assert detail["parameter_details"][0]["annotation"] == "str"
    assert detail["parameter_details"][1]["default"] == "10"
    assert "path_parameter_requires_guard" in detail["risk_reasons"]
    assert "external_resource_parameter" in detail["risk_reasons"]
    assert detail["wrapper_recommended"] is False
    assert module["function_details"]["call_api"]["wrapper_recommended"] is False
    assert "sensitive_parameter" in module["function_details"]["call_api"]["risk_reasons"]
    assert module["function_details"]["ask_value"]["wrapper_recommended"] is False
    assert "interactive_input" in module["function_details"]["ask_value"]["risk_reasons"]
    assert module["imports"] == ["torch"]
    assert module["class_details"]["Processor"]["public_methods"][0]["name"] == "run"
    assert module["class_details"]["Processor"]["public_methods"][0]["parameters"] == ["text"]
    assert module["class_details"]["Processor"]["constructor_requires_args"] is False
    assert module["class_details"]["NeedsConfig"]["constructor_parameters"] == ["config"]
    assert module["class_details"]["NeedsConfig"]["constructor_requires_args"] is True
    assert module["class_details"]["NeedsConfig"]["wrapper_recommended"] is False
    assert module["class_details"]["OptionalTokenClient"]["constructor_parameters"] == ["auth_token"]
    assert module["class_details"]["OptionalTokenClient"]["constructor_sensitive_parameters"] == ["auth_token"]
    assert module["class_details"]["OptionalTokenClient"]["wrapper_recommended"] is False
    assert "NeedsConfig" not in {item["name"] for item in module["wrapper_candidates"]}
    assert "OptionalTokenClient" not in {item["name"] for item in module["wrapper_candidates"]}
    assert "load_data" not in {item["name"] for item in module["wrapper_candidates"]}
    assert "call_api" not in {item["name"] for item in module["wrapper_candidates"]}
    assert "ask_value" not in {item["name"] for item in module["wrapper_candidates"]}
    assert module["wrapper_candidates"][0]["name"] == "Processor"
    assert module["wrapper_candidate_stats"]["public_functions"] == 3
    assert module["wrapper_candidate_stats"]["public_classes"] == 3
    assert module["wrapper_candidate_stats"]["recommended_functions"] == 0
    assert module["wrapper_candidate_stats"]["recommended_classes"] == 1
    assert module["wrapper_candidate_stats"]["candidate_count"] == 1


def test_ast_scan_rejects_plotting_output_and_remote_lookup_names(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
def plot_returns(values: list[float]) -> list[float]:
    """Build a plotting helper."""
    return values

def show_versions() -> str:
    """Show runtime package versions."""
    return "1.0"

def kegg_get(identifier: str) -> str:
    """Look up a remote biological database entry."""
    return identifier

def normalize_symbol(symbol: str) -> str:
    """Normalize a practical public value."""
    return symbol.lower()
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert "plotting_helper_name" in module["function_details"]["plot_returns"]["risk_reasons"]
    assert module["function_details"]["plot_returns"]["wrapper_recommended"] is False
    assert "output_only_name" in module["function_details"]["show_versions"]["risk_reasons"]
    assert module["function_details"]["show_versions"]["wrapper_recommended"] is False
    assert "remote_lookup_name" in module["function_details"]["kegg_get"]["risk_reasons"]
    assert module["function_details"]["kegg_get"]["wrapper_recommended"] is False
    assert module["function_details"]["normalize_symbol"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"normalize_symbol"}


def test_ast_scan_keeps_self_named_top_level_parameters(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "compare.py").write_text(
        '''
def compare(self, other):
    return self == other
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))

    assert symbols["compare"]["functions"]["compare"] == ["self", "other"]
    assert symbols["compare"]["function_details"]["compare"]["parameters"] == ["self", "other"]


def test_ast_scan_does_not_recommend_data_container_classes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "models.py").write_text(
        '''
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict

@dataclass
class Quote:
    symbol: str
    price: float

class Side(Enum):
    BUY = "buy"
    SELL = "sell"

class Payload(TypedDict):
    symbol: str

class Calculator:
    def add(self, left: int, right: int) -> int:
        return left + right
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["models"]

    assert module["class_details"]["Quote"]["wrapper_recommended"] is False
    assert "data_container_class" in module["class_details"]["Quote"]["risk_reasons"]
    assert module["class_details"]["Side"]["wrapper_recommended"] is False
    assert "enum_class" in module["class_details"]["Side"]["risk_reasons"]
    assert module["class_details"]["Payload"]["wrapper_recommended"] is False
    assert "typed_dict_class" in module["class_details"]["Payload"]["risk_reasons"]
    assert module["class_details"]["Calculator"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"Calculator"}


def test_ast_scan_rejects_classes_with_complex_runtime_constructors(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "wrappers.py").write_text(
        '''
class ClientTool:
    def __init__(self, client=None, config=None):
        self.client = client
        self.config = config

    def ping(self) -> str:
        return "pong"

class ModelRunner:
    def __init__(self, model=None, dataset=None):
        self.model = model
        self.dataset = dataset

    def count(self) -> int:
        return 1

class Formatter:
    def __init__(self, prefix: str = ""):
        self.prefix = prefix

    def format(self, text: str) -> str:
        return self.prefix + text
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["wrappers"]

    assert module["class_details"]["ClientTool"]["constructor_complex_parameters"] == ["client", "config"]
    assert "complex_constructor_parameter" in module["class_details"]["ClientTool"]["risk_reasons"]
    assert module["class_details"]["ClientTool"]["wrapper_recommended"] is False
    assert module["class_details"]["ModelRunner"]["constructor_complex_parameters"] == ["model", "dataset"]
    assert module["class_details"]["ModelRunner"]["wrapper_recommended"] is False
    assert module["class_details"]["Formatter"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"Formatter"}


def test_ast_scan_preserves_top_level_cls_and_rejects_opaque_runtime_params(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "helpers.py").write_text(
        """
def get_base_attr(cls, name):
    return getattr(cls, name)

def determine_num_ops(cls, num_ops, unop, binop, rbinop):
    return num_ops or 2

def product(sequence):
    return sequence

def max_degree(degrees):
    return degrees

def sorted_by_count(seq):
    return seq

def sorted_by_key(mapping):
    return sorted(mapping.items())

class Runner:
    def run(self, value):
        return value
""",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["helpers"]

    assert module["function_details"]["get_base_attr"]["parameters"] == ["cls", "name"]
    assert "opaque_runtime_parameter" in module["function_details"]["get_base_attr"]["risk_reasons"]
    assert module["function_details"]["get_base_attr"]["wrapper_recommended"] is False
    assert module["function_details"]["determine_num_ops"]["parameters"] == ["cls", "num_ops", "unop", "binop", "rbinop"]
    assert "opaque_runtime_parameter" in module["function_details"]["determine_num_ops"]["risk_reasons"]
    assert "opaque_runtime_parameter" in module["function_details"]["product"]["risk_reasons"]
    assert "opaque_runtime_parameter" in module["function_details"]["max_degree"]["risk_reasons"]
    assert "opaque_runtime_parameter" in module["function_details"]["sorted_by_count"]["risk_reasons"]
    assert "opaque_runtime_parameter" in module["function_details"]["sorted_by_key"]["risk_reasons"]
    assert module["class_details"]["Runner"]["public_methods"][0]["parameters"] == ["value"]
    candidates = {item["name"] for item in module["wrapper_candidates"]}
    assert "get_base_attr" not in candidates
    assert "determine_num_ops" not in candidates
    assert "product" not in candidates
    assert "max_degree" not in candidates
    assert "sorted_by_count" not in candidates
    assert "sorted_by_key" not in candidates


def test_ast_scan_rejects_complex_runtime_parameters_before_generation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pipeline.py").write_text(
        """
def train_model(model, dataset):
    return len(dataset)

def configure_client(client, config):
    return client

def slugify(text: str, separator: str = "-") -> str:
    return separator.join(text.lower().split())
""",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["pipeline"]

    assert "complex_runtime_parameter" in module["function_details"]["train_model"]["risk_reasons"]
    assert module["function_details"]["train_model"]["wrapper_recommended"] is False
    assert "complex_runtime_parameter" in module["function_details"]["configure_client"]["risk_reasons"]
    assert module["function_details"]["configure_client"]["wrapper_recommended"] is False
    assert module["function_details"]["slugify"]["wrapper_recommended"] is True
    candidates = {item["name"] for item in module["wrapper_candidates"]}
    assert candidates == {"slugify"}


def test_ast_scan_does_not_treat_import_paths_as_file_resources(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
def resolve_module(module_path: str, import_path: str) -> str:
    """Resolve a dotted import target."""
    return module_path or import_path

def read_file(file_path: str) -> str:
    """Read a user supplied file."""
    return file_path
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    import_risks = module["function_details"]["resolve_module"]["risk_reasons"]
    file_risks = module["function_details"]["read_file"]["risk_reasons"]
    assert "path_parameter_requires_guard" not in import_risks
    assert "path_parameter_requires_guard" in file_risks
    assert "external_resource_parameter" in file_risks
    assert module["function_details"]["resolve_module"]["wrapper_score"] == 100
    assert module["function_details"]["read_file"]["wrapper_score"] < 55
    assert {item["name"] for item in module["wrapper_candidates"]} == {"resolve_module"}


def test_ast_scan_allows_dynamic_signature_functions_with_explicit_params(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
def combine(value: int, *extras: int, **options: int) -> int:
    """Combine values with dynamic options."""
    return value + sum(extras) + int(options.get("offset", 0))

def compute_value(value: int) -> int:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]
    detail = module["function_details"]["combine"]

    assert detail["has_varargs"] is True
    assert detail["has_kwargs"] is True
    assert "dynamic_signature" in detail["risk_reasons"]
    assert "pure_dynamic_signature" not in detail["risk_reasons"]
    assert detail["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"combine", "compute_value"}


def test_ast_scan_does_not_recommend_pure_dynamic_signature_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
def combine(*extras: int, **options: int) -> int:
    """Combine values with dynamic options."""
    return sum(extras) + int(options.get("offset", 0))

def compute_value(value: int) -> int:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]
    detail = module["function_details"]["combine"]

    assert detail["has_varargs"] is True
    assert detail["has_kwargs"] is True
    assert "dynamic_signature" in detail["risk_reasons"]
    assert "pure_dynamic_signature" in detail["risk_reasons"]
    assert detail["wrapper_recommended"] is False
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value"}


def test_ast_scan_does_not_recommend_void_return_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
def update_cache(value: str) -> None:
    """Update internal cache."""
    return None

def normalize_in_place(value: str):
    """Normalize without returning a value."""
    cleaned = value.strip()

def clear_value(value: str):
    """Return no useful result."""
    return None

def todo_value(value: str):
    """Placeholder with a sentinel return."""
    return NotImplemented

def todo_raiser(value: str) -> str:
    """Placeholder with a typed return."""
    raise NotImplementedError

def outer_helper(value: str):
    """Nested returns do not make the outer function useful."""
    def inner():
        return value
    inner()

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert module["functions"]["update_cache"] == ["value"]
    assert module["function_details"]["update_cache"]["wrapper_recommended"] is False
    assert "void_return" in module["function_details"]["update_cache"]["risk_reasons"]
    assert module["function_details"]["update_cache"]["wrapper_score"] < 55
    assert module["function_details"]["normalize_in_place"]["wrapper_recommended"] is False
    assert "void_return" in module["function_details"]["normalize_in_place"]["risk_reasons"]
    assert module["function_details"]["clear_value"]["wrapper_recommended"] is False
    assert "void_return" in module["function_details"]["clear_value"]["risk_reasons"]
    assert module["function_details"]["todo_value"]["wrapper_recommended"] is False
    assert "unsupported_placeholder" in module["function_details"]["todo_value"]["risk_reasons"]
    assert module["function_details"]["todo_raiser"]["wrapper_recommended"] is False
    assert "unsupported_placeholder" in module["function_details"]["todo_raiser"]["risk_reasons"]
    assert module["function_details"]["outer_helper"]["wrapper_recommended"] is False
    assert "void_return" in module["function_details"]["outer_helper"]["risk_reasons"]
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value"}


def test_ast_scan_does_not_recommend_async_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
async def fetch_value(query: str) -> str:
    """Fetch a value asynchronously."""
    return query

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert module["functions"]["fetch_value"] == ["query"]
    assert module["function_details"]["fetch_value"]["is_async"] is True
    assert module["function_details"]["fetch_value"]["wrapper_recommended"] is False
    assert "async_function" in module["function_details"]["fetch_value"]["risk_reasons"]
    assert module["function_details"]["fetch_value"]["wrapper_score"] == 20
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value"}


def test_ast_scan_does_not_recommend_imported_global_state_calls(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
from framework.workflow import R

def list_recorders(experiment: str) -> dict:
    """List recorders from the framework's active experiment."""
    return R.get_exp(experiment_name=experiment).list_recorders()

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert module["functions"]["list_recorders"] == ["experiment"]
    assert module["function_details"]["list_recorders"]["wrapper_recommended"] is False
    assert "global_state_dependency" in module["function_details"]["list_recorders"]["risk_reasons"]
    assert module["function_details"]["list_recorders"]["wrapper_score"] == 40
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value"}


def _write_network_client_constructor_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import httpx
import requests as rq
import aiohttp
from aiohttp import ClientSession
from requests import Session

def make_aiohttp_session() -> str:
    """Create an aiohttp client session."""
    session = aiohttp.ClientSession()
    return str(session.closed)

def make_aiohttp_alias_session() -> str:
    """Create an aiohttp client session from an imported alias."""
    session = ClientSession()
    return str(session.closed)

def fetch_with_requests_session(url: str) -> dict:
    """Fetch JSON through a chained requests session."""
    return rq.Session().get(url).json()

def fetch_with_requests_session_alias(url: str) -> dict:
    """Fetch JSON through an imported requests session alias."""
    client = Session()
    return client.get(url).json()

def fetch_with_httpx_client(url: str) -> dict:
    """Fetch JSON through a context-managed HTTPX client."""
    with httpx.Client() as client:
        return client.get(url).json()

def fetch_with_httpx_chain(url: str) -> dict:
    """Post JSON through a chained HTTPX client."""
    return httpx.Client().post(url, json={}).json()

def echo_value(value: str) -> str:
    """Return the input string."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_network_client_constructor_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_network_client_constructor_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "make_aiohttp_session",
        "make_aiohttp_alias_session",
        "fetch_with_requests_session",
        "fetch_with_requests_session_alias",
        "fetch_with_httpx_client",
        "fetch_with_httpx_chain",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_value"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_value"}


def _write_direct_network_method_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import httpx
import aiohttp
import requests
import requests as rq
from aiohttp import request as aiohttp_request
from httpx import request as httpx_request
from requests import head as requests_head

def aiohttp_direct_request_status(url: str) -> str:
    """Create a top-level aiohttp request context."""
    request = aiohttp.request("GET", url)
    return str(request)

def aiohttp_alias_request_status(url: str) -> str:
    """Create an aiohttp request context through an imported alias."""
    request = aiohttp_request("POST", url, json={})
    return str(request)

def requests_head_status(url: str) -> int:
    """Fetch response headers through requests.head."""
    return requests.head(url).status_code

def requests_options_status(url: str) -> int:
    """Fetch options through an aliased requests module."""
    return rq.options(url).status_code

def requests_generic_request_status(url: str) -> int:
    """Fetch through requests.request."""
    return requests.request("GET", url).status_code

def requests_alias_head_status(url: str) -> int:
    """Fetch through an imported requests.head alias."""
    return requests_head(url).status_code

def httpx_head_status(url: str) -> int:
    """Fetch response headers through httpx.head."""
    return httpx.head(url).status_code

def httpx_options_status(url: str) -> int:
    """Fetch options through httpx.options."""
    return httpx.options(url).status_code

def httpx_generic_request_status(url: str) -> int:
    """Fetch through an imported httpx.request alias."""
    return httpx_request("GET", url).status_code

def httpx_stream_status(url: str) -> int:
    """Fetch through httpx.stream."""
    with httpx.stream("GET", url) as response:
        return response.status_code

def echo_value(value: str) -> str:
    """Return the input string."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_direct_network_request_methods(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_direct_network_method_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "aiohttp_direct_request_status",
        "aiohttp_alias_request_status",
        "requests_head_status",
        "requests_options_status",
        "requests_generic_request_status",
        "requests_alias_head_status",
        "httpx_head_status",
        "httpx_options_status",
        "httpx_generic_request_status",
        "httpx_stream_status",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_value"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_value"}


def _write_url_opener_network_client_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import urllib.request
import urllib3
from urllib.request import build_opener
from urllib3 import request as urllib3_request_alias

def fetch_with_urllib_opener(url: str) -> bytes:
    """Fetch bytes through a urllib opener."""
    opener = urllib.request.build_opener()
    return opener.open(url).read()

def fetch_with_urllib_opener_alias(url: str) -> bytes:
    """Fetch bytes through an imported urllib opener factory."""
    opener = build_opener()
    return opener.open(url).read()

def fetch_with_urllib3_pool(url: str) -> bytes:
    """Fetch bytes through a urllib3 pool manager."""
    manager = urllib3.PoolManager()
    return manager.request("GET", url).data

def fetch_with_urllib3_proxy(url: str) -> bytes:
    """Fetch bytes through a urllib3 proxy manager."""
    manager = urllib3.ProxyManager("http://proxy.example")
    return manager.request("GET", url).data

def fetch_with_urllib3_top_level(url: str) -> bytes:
    """Fetch bytes through urllib3 top-level request."""
    return urllib3.request("GET", url).data

def fetch_with_urllib3_top_level_alias(url: str) -> bytes:
    """Fetch bytes through an imported urllib3 request alias."""
    return urllib3_request_alias("POST", url).data

def echo_value(value: str) -> str:
    """Return the input string."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_url_opener_network_client_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_url_opener_network_client_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "fetch_with_urllib_opener",
        "fetch_with_urllib_opener_alias",
        "fetch_with_urllib3_pool",
        "fetch_with_urllib3_proxy",
        "fetch_with_urllib3_top_level",
        "fetch_with_urllib3_top_level_alias",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_value"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_value"}


def test_ast_scan_does_not_recommend_runtime_side_effect_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
import requests as rq
import urllib.request
import webbrowser
import configparser
import glob
import h5py
import joblib
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
from PIL import Image
import pickle
import polars as pl
import shutil
import sqlite3
import torch as th
import zipfile
from pathlib import Path
from scipy.io import loadmat as load_matrix, savemat as save_matrix
from subprocess import check_output as run_output, getoutput as shell_output

def run_command(command: str) -> str:
    """Run an external command."""
    return run_output(command)

def exec_command(command: str) -> None:
    """Replace this process with an external command."""
    os.execvp(command, [command])

def shell_command_text(command: str) -> str:
    """Run a shell command and return text output."""
    return shell_output(command)

def start_local_file(path: str) -> None:
    """Open a local file with the platform shell."""
    os.startfile(path)

def fetch_remote(url: str) -> dict:
    """Fetch remote JSON."""
    return rq.get(url).json()

def fetch_url(url: str) -> bytes:
    """Fetch remote bytes."""
    return urllib.request.urlopen(url).read()

def download_remote_file(url: str, filename: str) -> str:
    """Download a remote file."""
    return urllib.request.urlretrieve(url, filename)[0]

def open_browser(url: str) -> bool:
    """Open a URL in the system browser."""
    return webbrowser.open(url)

def save_report(text: str) -> str:
    """Save a local report."""
    with open("report.txt", "w") as handle:
        handle.write(text)
    return text

def normalize_mode(value: str) -> str:
    """Normalize a runtime mode string."""
    os.environ["APP_MODE"] = value
    return value.lower()

def apply_locale(value: str) -> str:
    """Apply a runtime locale string."""
    os.putenv("APP_LOCALE", value)
    return value

def select_workspace() -> str:
    """Select the default workspace."""
    os.chdir("workspace")
    return os.getcwd()

def restrict_creation_mask() -> int:
    """Restrict file creation permissions."""
    return os.umask(0o077)

def summarize_report(report_path: str) -> str:
    """Summarize a local report file."""
    return Path(report_path).read_text()[:20]

def table_columns(table_path: str) -> list:
    """Return columns from a local table file."""
    return list(pd.read_csv(table_path).columns)

def export_default_report() -> str:
    """Export a bundled report."""
    pd.DataFrame({"value": [1, 2]}).to_csv("report.csv", index=False)
    return "report.csv"

def export_default_json() -> str:
    """Export bundled JSON."""
    pd.DataFrame({"value": [1, 2]}).to_json("report.json")
    return "report.json"

def export_default_html() -> str:
    """Export bundled HTML."""
    pd.DataFrame({"value": [1, 2]}).to_html("report.html")
    return "report.html"

def export_default_markdown() -> str:
    """Export bundled Markdown."""
    pd.DataFrame({"value": [1, 2]}).to_markdown(buf="report.md")
    return "report.md"

def export_default_latex() -> str:
    """Export bundled LaTeX."""
    pd.DataFrame({"value": [1, 2]}).to_latex(buf="report.tex")
    return "report.tex"

def export_default_xml() -> str:
    """Export bundled XML."""
    pd.DataFrame({"value": [1, 2]}).to_xml(path_or_buffer="report.xml")
    return "report.xml"

def export_default_excel() -> str:
    """Export bundled Excel."""
    pd.DataFrame({"value": [1, 2]}).to_excel("report.xlsx")
    return "report.xlsx"

def export_default_parquet() -> str:
    """Export bundled Parquet."""
    pd.DataFrame({"value": [1, 2]}).to_parquet("report.parquet")
    return "report.parquet"

def export_default_pickle() -> str:
    """Export bundled pickle."""
    pd.DataFrame({"value": [1, 2]}).to_pickle("report.pkl")
    return "report.pkl"

def export_numpy_archive() -> str:
    """Export bundled array data."""
    np.savez("arrays.npz", values=np.array([1, 2]))
    return "arrays.npz"

def export_numpy_text() -> str:
    """Export bundled array text."""
    np.savetxt("arrays.csv", np.array([1, 2]))
    return "arrays.csv"

def export_default_model() -> str:
    """Export a bundled serialized model."""
    joblib.dump({"value": [1, 2]}, "model.joblib")
    return "model.joblib"

def export_default_weights() -> str:
    """Export bundled model weights."""
    th.save({"value": [1, 2]}, "weights.pt")
    return "weights.pt"

def export_default_matrix() -> str:
    """Export bundled matrix data."""
    save_matrix("matrix.mat", {"values": [1, 2]})
    return "matrix.mat"

def export_polars_parquet() -> str:
    """Export bundled Polars data."""
    pl.DataFrame({"value": [1, 2]}).write_parquet("polars.parquet")
    return "polars.parquet"

def unpack_archive_members(archive) -> str:
    """Unpack archive members into a local directory."""
    archive.extractall("./unpacked")
    return "./unpacked"

def extract_archive_member(archive) -> str:
    """Extract one archive member into a local directory."""
    archive.extract("payload.txt", "./unpacked")
    return "./unpacked/payload.txt"

def copy_default_tree() -> str:
    """Copy a bundled asset tree."""
    shutil.copytree("assets", "assets_copy")
    return "assets_copy"

def build_default_archive() -> str:
    """Build a bundled archive."""
    return shutil.make_archive("bundle", "zip", "assets")

def update_report_permissions() -> str:
    """Update local report permissions."""
    os.chmod("report.txt", 0o600)
    return "report.txt"

def link_report() -> str:
    """Create a local hard link."""
    os.link("report.txt", "report.link")
    return "report.link"

def symlink_report() -> str:
    """Create a local symlink."""
    Path("report.symlink").symlink_to("report.txt")
    return "report.symlink"

def chmod_report_path() -> str:
    """Change local report permissions via Path."""
    Path("report.txt").chmod(0o600)
    return "report.txt"

def export_default_image() -> str:
    """Export a bundled image."""
    image = Image.new("RGB", (1, 1))
    image.save("preview.png")
    return "preview.png"

def render_default_chart() -> str:
    """Render a bundled chart."""
    plt.savefig("chart.png")
    return "chart.png"

def render_csv_text() -> str:
    """Render a CSV string."""
    return pd.DataFrame({"value": [1, 2]}).to_csv(index=False)

def load_default_pickle_table() -> object:
    """Load a bundled pickle table."""
    return pd.read_pickle("cache.pkl")

def load_default_numbers() -> list:
    """Load numbers from a bundled data file."""
    return np.loadtxt("data.csv").tolist()

def load_default_memmap() -> list:
    """Load numbers from a bundled memory-mapped file."""
    return np.memmap("data.npy", dtype="float32", mode="r")[:3].tolist()

def load_default_model() -> object:
    """Load a bundled serialized model."""
    return joblib.load("model.joblib")

def load_default_weights() -> object:
    """Load bundled model weights."""
    return th.load("weights.pt")

def load_default_matrix() -> object:
    """Load a bundled Matlab matrix."""
    return load_matrix("matrix.mat")

def load_pickled_stream(stream) -> object:
    """Load a pickled stream."""
    return pickle.load(stream)

def inspect_hdf() -> object:
    """Inspect a bundled HDF5 file."""
    with h5py.File("data.h5", "r") as handle:
        return handle.keys()

def list_default_data() -> list:
    """List files from a bundled data directory."""
    return os.listdir("data")

def list_matching_files() -> list:
    """List matching files from a bundled data directory."""
    return glob.glob("data/*.csv")

def inspect_archive() -> list:
    """Inspect a bundled archive file."""
    with zipfile.ZipFile("data.zip") as archive:
        return archive.namelist()

def read_default_config() -> list:
    """Read bundled configuration defaults."""
    parser = configparser.ConfigParser()
    parser.read("settings.ini")
    return parser.sections()

def count_default_records() -> int:
    """Count records from a bundled sqlite database."""
    conn = sqlite3.connect("records.db")
    try:
        return conn.execute("select count(*) from records").fetchone()[0]
    finally:
        conn.close()

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert module["function_details"]["run_command"]["wrapper_recommended"] is False
    assert "process_execution" in module["function_details"]["run_command"]["risk_reasons"]
    assert module["function_details"]["exec_command"]["wrapper_recommended"] is False
    assert "process_execution" in module["function_details"]["exec_command"]["risk_reasons"]
    assert module["function_details"]["shell_command_text"]["wrapper_recommended"] is False
    assert "process_execution" in module["function_details"]["shell_command_text"]["risk_reasons"]
    assert module["function_details"]["start_local_file"]["wrapper_recommended"] is False
    assert "process_execution" in module["function_details"]["start_local_file"]["risk_reasons"]
    assert module["function_details"]["fetch_remote"]["wrapper_recommended"] is False
    assert "network_operation" in module["function_details"]["fetch_remote"]["risk_reasons"]
    assert module["function_details"]["fetch_url"]["wrapper_recommended"] is False
    assert "network_operation" in module["function_details"]["fetch_url"]["risk_reasons"]
    assert module["function_details"]["download_remote_file"]["wrapper_recommended"] is False
    assert "network_operation" in module["function_details"]["download_remote_file"]["risk_reasons"]
    assert module["function_details"]["open_browser"]["wrapper_recommended"] is False
    assert "process_execution" in module["function_details"]["open_browser"]["risk_reasons"]
    assert module["function_details"]["save_report"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["save_report"]["risk_reasons"]
    assert module["function_details"]["normalize_mode"]["wrapper_recommended"] is False
    assert "environment_mutation" in module["function_details"]["normalize_mode"]["risk_reasons"]
    assert module["function_details"]["apply_locale"]["wrapper_recommended"] is False
    assert "environment_mutation" in module["function_details"]["apply_locale"]["risk_reasons"]
    assert module["function_details"]["select_workspace"]["wrapper_recommended"] is False
    assert "process_state_mutation" in module["function_details"]["select_workspace"]["risk_reasons"]
    assert module["function_details"]["restrict_creation_mask"]["wrapper_recommended"] is False
    assert "process_state_mutation" in module["function_details"]["restrict_creation_mask"]["risk_reasons"]
    assert module["function_details"]["summarize_report"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["summarize_report"]["risk_reasons"]
    assert module["function_details"]["table_columns"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["table_columns"]["risk_reasons"]
    assert module["function_details"]["export_default_report"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_report"]["risk_reasons"]
    assert module["function_details"]["export_default_json"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_json"]["risk_reasons"]
    assert module["function_details"]["export_default_html"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_html"]["risk_reasons"]
    assert module["function_details"]["export_default_markdown"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_markdown"]["risk_reasons"]
    assert module["function_details"]["export_default_latex"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_latex"]["risk_reasons"]
    assert module["function_details"]["export_default_xml"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_xml"]["risk_reasons"]
    assert module["function_details"]["export_default_excel"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_excel"]["risk_reasons"]
    assert module["function_details"]["export_default_parquet"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_parquet"]["risk_reasons"]
    assert module["function_details"]["export_default_pickle"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_pickle"]["risk_reasons"]
    assert module["function_details"]["export_numpy_archive"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_numpy_archive"]["risk_reasons"]
    assert module["function_details"]["export_numpy_text"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_numpy_text"]["risk_reasons"]
    assert module["function_details"]["export_default_model"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_model"]["risk_reasons"]
    assert module["function_details"]["export_default_weights"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_weights"]["risk_reasons"]
    assert module["function_details"]["export_default_matrix"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_matrix"]["risk_reasons"]
    assert module["function_details"]["export_polars_parquet"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_polars_parquet"]["risk_reasons"]
    assert module["function_details"]["unpack_archive_members"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["unpack_archive_members"]["risk_reasons"]
    assert module["function_details"]["extract_archive_member"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["extract_archive_member"]["risk_reasons"]
    assert module["function_details"]["copy_default_tree"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["copy_default_tree"]["risk_reasons"]
    assert module["function_details"]["build_default_archive"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["build_default_archive"]["risk_reasons"]
    assert module["function_details"]["update_report_permissions"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["update_report_permissions"]["risk_reasons"]
    assert module["function_details"]["link_report"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["link_report"]["risk_reasons"]
    assert module["function_details"]["symlink_report"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["symlink_report"]["risk_reasons"]
    assert module["function_details"]["chmod_report_path"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["chmod_report_path"]["risk_reasons"]
    assert module["function_details"]["export_default_image"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["export_default_image"]["risk_reasons"]
    assert module["function_details"]["render_default_chart"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["render_default_chart"]["risk_reasons"]
    assert module["function_details"]["render_csv_text"]["wrapper_recommended"] is True
    assert module["function_details"]["load_default_pickle_table"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_default_pickle_table"]["risk_reasons"]
    assert module["function_details"]["load_default_numbers"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_default_numbers"]["risk_reasons"]
    assert module["function_details"]["load_default_memmap"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_default_memmap"]["risk_reasons"]
    assert module["function_details"]["load_default_model"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_default_model"]["risk_reasons"]
    assert module["function_details"]["load_default_weights"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_default_weights"]["risk_reasons"]
    assert module["function_details"]["load_default_matrix"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_default_matrix"]["risk_reasons"]
    assert module["function_details"]["load_pickled_stream"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["load_pickled_stream"]["risk_reasons"]
    assert module["function_details"]["inspect_hdf"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["inspect_hdf"]["risk_reasons"]
    assert module["function_details"]["list_default_data"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["list_default_data"]["risk_reasons"]
    assert module["function_details"]["list_matching_files"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["list_matching_files"]["risk_reasons"]
    assert module["function_details"]["inspect_archive"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["inspect_archive"]["risk_reasons"]
    assert module["function_details"]["read_default_config"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["read_default_config"]["risk_reasons"]
    assert module["function_details"]["count_default_records"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["count_default_records"]["risk_reasons"]
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value", "render_csv_text"}


def _write_tempfile_mutation_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import tempfile
from tempfile import NamedTemporaryFile, TemporaryDirectory, mkdtemp, mkstemp

def named_temp_status() -> str:
    """Return status after creating a named temporary file."""
    handle = tempfile.NamedTemporaryFile(delete=False)
    handle.close()
    return handle.name

def alias_temp_status() -> str:
    """Return status after creating a named temporary file through an alias."""
    handle = NamedTemporaryFile(delete=False)
    handle.close()
    return handle.name

def temp_dir_status() -> str:
    """Return status after creating a temporary directory."""
    with TemporaryDirectory() as directory:
        return directory

def mkstemp_status() -> str:
    """Return status after creating a low-level temporary file."""
    _fd, path = mkstemp()
    return path

def mkdtemp_status() -> str:
    """Return status after creating a temporary directory path."""
    return mkdtemp()

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_tempfile_mutation_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_tempfile_mutation_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("named_temp_status", "alias_temp_status", "temp_dir_status", "mkstemp_status", "mkdtemp_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_getattr_runtime_side_effect_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import os
import subprocess
import tempfile
import urllib.request as url_request

def status_code() -> str:
    """Run a hidden shell command."""
    getattr(os, "system")("echo ok")
    return "ok"

def job_status() -> str:
    """Run a hidden subprocess through a local alias."""
    runner = getattr(subprocess, "run")
    runner(["echo", "ok"], capture_output=True)
    return "ok"

def transfer_status() -> str:
    """Download a hidden remote resource."""
    getattr(url_request, "urlretrieve")("https://example.com/a", "a")
    return "ok"

def scratch_status() -> str:
    """Create a hidden temporary directory."""
    getattr(tempfile, "mkdtemp")()
    return "ok"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_getattr_runtime_side_effect_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_getattr_runtime_side_effect_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("status_code", "job_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_execution" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["transfer_status"]["wrapper_recommended"] is False
    assert "network_operation" in module["function_details"]["transfer_status"]["risk_reasons"]
    assert module["function_details"]["scratch_status"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["scratch_status"]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_partial_runtime_side_effect_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import functools
import os
import subprocess
import tempfile
import urllib.request as url_request
from functools import partial

def status_code() -> str:
    """Run a shell command through functools.partial."""
    functools.partial(os.system, "echo ok")()
    return "ok"

def job_status() -> str:
    """Run a subprocess through a local partial alias."""
    runner = partial(subprocess.run, ["echo", "ok"], capture_output=True)
    runner()
    return "ok"

def transfer_status() -> str:
    """Download a remote resource through functools.partial."""
    downloader = functools.partial(url_request.urlretrieve, "https://example.com/a", "a")
    downloader()
    return "ok"

def scratch_status() -> str:
    """Create a temporary directory through a partial alias."""
    maker = partial(tempfile.mkdtemp)
    maker()
    return "ok"

def getattr_partial_status() -> str:
    """Run a hidden getattr target through functools.partial."""
    runner = functools.partial(getattr(os, "system"), "echo ok")
    runner()
    return "ok"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_partial_runtime_side_effect_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_partial_runtime_side_effect_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("status_code", "job_status", "getattr_partial_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_execution" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["transfer_status"]["wrapper_recommended"] is False
    assert "network_operation" in module["function_details"]["transfer_status"]["risk_reasons"]
    assert module["function_details"]["scratch_status"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["scratch_status"]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_dynamic_code_execution_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import builtins
from builtins import compile as compile_source, eval as eval_expression, exec as exec_statement

def formula_value(expression: str) -> object:
    """Evaluate a formula expression."""
    return eval(expression)

def builtin_formula_value(expression: str) -> object:
    """Evaluate a formula expression through the builtins module."""
    return builtins.eval(expression)

def alias_formula_value(expression: str) -> object:
    """Evaluate a formula expression through an imported alias."""
    return eval_expression(expression)

def statement_status(source: str) -> str:
    """Execute a source string."""
    exec(source)
    return "ok"

def alias_statement_status(source: str) -> str:
    """Execute a source string through an imported alias."""
    exec_statement(source)
    return "ok"

def compiled_status(source: str) -> object:
    """Compile supplied source."""
    return compile(source, "<user>", "exec")

def alias_compiled_status(source: str) -> object:
    """Compile supplied source through an imported alias."""
    return compile_source(source, "<user>", "exec")

def echo_text(text: str) -> str:
    """Return the provided text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_dynamic_code_execution_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_dynamic_code_execution_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "formula_value",
        "builtin_formula_value",
        "alias_formula_value",
        "statement_status",
        "alias_statement_status",
        "compiled_status",
        "alias_compiled_status",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "dynamic_code_execution" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_dynamic_import_runtime_side_effect_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import importlib
from importlib import import_module

def alpha_status() -> str:
    """Return status after a dynamic os import."""
    __import__("os").system("echo ok")
    return "ok"

def beta_status() -> str:
    """Return status after an importlib os import."""
    importlib.import_module("os").system("echo ok")
    return "ok"

def gamma_status() -> str:
    """Return status after an import_module subprocess import."""
    import_module("subprocess").run(["echo", "ok"], capture_output=True)
    return "ok"

def delta_status() -> str:
    """Return status after an assigned dynamic os import."""
    runtime_os = importlib.import_module("os")
    runtime_os.system("echo ok")
    return "ok"

def epsilon_status() -> str:
    """Return status after a dynamic network import."""
    importlib.import_module("urllib.request").urlretrieve("https://example.com/a", "a")
    return "ok"

def zeta_status() -> str:
    """Return status after an assigned dynamic tempfile import."""
    runtime_tempfile = import_module("tempfile")
    runtime_tempfile.mkdtemp()
    return "ok"

def echo_text(text: str) -> str:
    """Return the provided text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_dynamic_import_runtime_side_effect_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_dynamic_import_runtime_side_effect_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("alpha_status", "beta_status", "gamma_status", "delta_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_execution" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["epsilon_status"]["wrapper_recommended"] is False
    assert "network_operation" in module["function_details"]["epsilon_status"]["risk_reasons"]
    assert module["function_details"]["zeta_status"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["zeta_status"]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_runtime_global_mutation_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import logging
import sys
import warnings

def add_runtime_import_path() -> str:
    """Mutate interpreter import search path."""
    sys.path.insert(0, "plugins")
    return "plugins"

def forget_cached_module(name: str) -> str:
    """Remove one module from the import cache."""
    sys.modules.pop(name, None)
    return name

def configure_warnings() -> str:
    """Change process warning filters."""
    warnings.filterwarnings("ignore")
    return "ignore"

def configure_logging() -> str:
    """Change process logging configuration."""
    logging.basicConfig(level=logging.INFO)
    return "logging"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_runtime_global_mutation_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_runtime_global_mutation_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "add_runtime_import_path",
        "forget_cached_module",
        "configure_warnings",
        "configure_logging",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_path_object_alias_file_read_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
from pathlib import Path
import pathlib

def direct_iterdir_names() -> list[str]:
    """List local data directory directly."""
    return [item.name for item in Path("data").iterdir()]

def alias_iterdir_names() -> list[str]:
    """List local data directory through a Path alias."""
    directory = Path("data")
    return [item.name for item in directory.iterdir()]

def alias_glob_names() -> list[str]:
    """Glob local data directory through a Path alias."""
    directory = Path("data")
    return [item.name for item in directory.glob("*.csv")]

def alias_rglob_names() -> list[str]:
    """Recursively glob local data directory through a Path alias."""
    directory = pathlib.Path("data")
    return [item.name for item in directory.rglob("*.csv")]

def cwd_iterdir_names() -> list[str]:
    """List current working directory through a Path factory method."""
    return [item.name for item in Path.cwd().iterdir()]

def alias_cwd_iterdir_names() -> list[str]:
    """List current working directory through a Path factory alias."""
    directory = Path.cwd()
    return [item.name for item in directory.iterdir()]

def home_glob_names() -> list[str]:
    """Glob the home directory through a Path factory method."""
    return [item.name for item in pathlib.Path.home().glob("*.csv")]

def alias_home_read_text() -> str:
    """Read a home file through a Path factory alias and join."""
    directory = Path.home()
    return (directory / "settings.ini").read_text()

def chained_alias_read_text() -> str:
    """Read a joined path through a second Path alias."""
    directory = Path.home()
    config = directory / "settings.ini"
    return config.read_text()

def chained_alias_iterdir_names() -> list[str]:
    """List a joined path through a second Path alias."""
    directory = Path.cwd()
    data_dir = directory / "data"
    return [item.name for item in data_dir.iterdir()]

def resolve_alias_iterdir_names() -> list[str]:
    """List a resolved Path alias."""
    directory = Path("data").resolve()
    return [item.name for item in directory.iterdir()]

def expanduser_alias_glob_names() -> list[str]:
    """Glob an expanded user Path alias."""
    directory = pathlib.Path("~").expanduser()
    return [item.name for item in directory.glob("*.csv")]

def parent_iterdir_names() -> list[str]:
    """List a parent Path property directly."""
    return [item.name for item in Path("data/file.txt").parent.iterdir()]

def alias_parent_glob_names() -> list[str]:
    """Glob a parent Path property alias."""
    directory = Path("data/file.txt").parent
    return [item.name for item in directory.glob("*.csv")]

def parents_index_iterdir_names() -> list[str]:
    """List a Path parents index directly."""
    return [item.name for item in Path("data/file.txt").parents[0].iterdir()]

def alias_read_text() -> str:
    """Read local file through a Path alias."""
    config = Path("settings.ini")
    return config.read_text()

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_path_object_alias_file_read_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_path_object_alias_file_read_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "direct_iterdir_names",
        "alias_iterdir_names",
        "alias_glob_names",
        "alias_rglob_names",
        "cwd_iterdir_names",
        "alias_cwd_iterdir_names",
        "home_glob_names",
        "alias_home_read_text",
        "chained_alias_read_text",
        "chained_alias_iterdir_names",
        "resolve_alias_iterdir_names",
        "expanduser_alias_glob_names",
        "parent_iterdir_names",
        "alias_parent_glob_names",
        "parents_index_iterdir_names",
        "alias_read_text",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_path_open_mode_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
from pathlib import Path
import pathlib

def path_open_write_mode() -> bool:
    """Open a local path in write mode."""
    handle = Path("report.txt").open("w")
    handle.close()
    return handle.closed

def alias_path_open_append_mode() -> bool:
    """Open a local path alias in append mode."""
    report = Path("report.txt")
    handle = report.open("a")
    handle.close()
    return handle.closed

def pathlib_open_exclusive_mode() -> bool:
    """Open a pathlib path in exclusive create mode."""
    handle = pathlib.Path("report.txt").open("x")
    handle.close()
    return handle.closed

def path_open_read_mode() -> str:
    """Open a local path with the default read mode."""
    with Path("report.txt").open() as handle:
        return handle.read()

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_path_open_write_mode_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_path_open_mode_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("path_open_write_mode", "alias_path_open_append_mode", "pathlib_open_exclusive_mode"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in module["function_details"][name]["risk_reasons"]
        assert "file_read" not in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["path_open_read_mode"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["path_open_read_mode"]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_file_metadata_read_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
from pathlib import Path
import os
from os.path import exists as path_exists_alias, getsize as path_size, isfile as path_is_file

def path_exists() -> bool:
    """Check whether a local config path exists."""
    return Path("settings.ini").exists()

def alias_is_file() -> bool:
    """Check whether an aliased path is a file."""
    path = Path("settings.ini")
    return path.is_file()

def path_stat_size() -> int:
    """Read a local file metadata size."""
    return Path("settings.ini").stat().st_size

def os_path_getsize() -> int:
    """Read local file size through os.path."""
    return os.path.getsize("settings.ini")

def os_stat_size() -> int:
    """Read local file metadata through os.stat."""
    return os.stat("settings.ini").st_size

def os_path_alias_getsize() -> int:
    """Read local file size through an os.path import alias."""
    return path_size("settings.ini")

def os_path_alias_exists() -> bool:
    """Check path existence through an os.path import alias."""
    return path_exists_alias("settings.ini")

def os_path_alias_isfile() -> bool:
    """Check file type through an os.path import alias."""
    return path_is_file("settings.ini")

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_file_metadata_read_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_file_metadata_read_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "path_exists",
        "alias_is_file",
        "path_stat_size",
        "os_path_getsize",
        "os_stat_size",
        "os_path_alias_getsize",
        "os_path_alias_exists",
        "os_path_alias_isfile",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_open_alias_file_read_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
from builtins import open as read_file
from io import open as io_read_file

def alias_builtin_open_read() -> str:
    """Read through a builtins.open alias."""
    with read_file("settings.ini") as handle:
        return handle.read()

def alias_builtin_open_write(text: str) -> int:
    """Write through a builtins.open alias."""
    with read_file("settings.ini", "w") as handle:
        return handle.write(text)

def alias_io_open_read() -> str:
    """Read through an io.open import alias."""
    with io_read_file("settings.ini") as handle:
        return handle.read()

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_open_alias_file_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_open_alias_file_read_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("alias_builtin_open_read", "alias_io_open_read"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["alias_builtin_open_write"]["wrapper_recommended"] is False
    assert "file_mutation" in module["function_details"]["alias_builtin_open_write"]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_os_descriptor_file_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import os
from os import O_CREAT, O_RDONLY, O_WRONLY, fdopen as wrap_fd, open as low_open

def fdopen_write_mode(fd: int) -> bool:
    """Wrap an existing descriptor in write mode."""
    handle = os.fdopen(fd, "w")
    handle.close()
    return handle.closed

def fdopen_alias_append_mode(fd: int) -> bool:
    """Wrap an existing descriptor alias in append mode."""
    handle = wrap_fd(fd, mode="a")
    handle.close()
    return handle.closed

def os_open_write_flags() -> int:
    """Open a local path through os.open with write flags."""
    fd = os.open("report.txt", os.O_WRONLY | os.O_CREAT)
    os.close(fd)
    return fd

def os_open_alias_write_flags() -> int:
    """Open a local path through an os.open alias with write flags."""
    fd = low_open("report.txt", O_WRONLY | O_CREAT)
    os.close(fd)
    return fd

def os_open_read_flags() -> int:
    """Open a local path through os.open with read-only flags."""
    fd = os.open("report.txt", O_RDONLY)
    os.close(fd)
    return fd

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_os_descriptor_file_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_os_descriptor_file_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("fdopen_write_mode", "fdopen_alias_append_mode", "os_open_write_flags", "os_open_alias_write_flags"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["os_open_read_flags"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["os_open_read_flags"]["risk_reasons"]
    assert "file_mutation" not in module["function_details"]["os_open_read_flags"]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_mode_sensitive_file_open_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import gzip
import h5py
import io
import tarfile
import zipfile
from gzip import open as gzip_open_alias
from zipfile import ZipFile as Archive

def gzip_open_write_mode() -> bool:
    """Open a gzip file in write mode."""
    handle = gzip.open("report.gz", "wb")
    handle.close()
    return handle.closed

def gzip_alias_append_mode() -> bool:
    """Open a gzip alias in append mode."""
    handle = gzip_open_alias("report.gz", mode="ab")
    handle.close()
    return handle.closed

def tarfile_open_write_mode() -> bool:
    """Open a tar archive in write mode."""
    archive = tarfile.open("report.tar", "w")
    archive.close()
    return True

def zipfile_open_write_mode() -> bool:
    """Open a zip archive in write mode."""
    archive = zipfile.ZipFile("report.zip", "w")
    archive.close()
    return True

def zipfile_alias_append_mode() -> bool:
    """Open a zip archive alias in append mode."""
    archive = Archive("report.zip", mode="a")
    archive.close()
    return True

def h5py_file_write_mode() -> bool:
    """Open an h5py file in write mode."""
    handle = h5py.File("report.h5", "w")
    handle.close()
    return True

def io_fileio_write_mode() -> bool:
    """Open a binary file through io.FileIO in write mode."""
    handle = io.FileIO("report.bin", "w")
    handle.close()
    return handle.closed

def io_fileio_read_mode() -> bool:
    """Open a binary file through io.FileIO in default read mode."""
    handle = io.FileIO("report.bin")
    handle.close()
    return handle.closed

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_mode_sensitive_file_open_writes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_mode_sensitive_file_open_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "gzip_open_write_mode",
        "gzip_alias_append_mode",
        "tarfile_open_write_mode",
        "zipfile_open_write_mode",
        "zipfile_alias_append_mode",
        "h5py_file_write_mode",
        "io_fileio_write_mode",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in module["function_details"][name]["risk_reasons"]
        assert "file_read" not in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["io_fileio_read_mode"]["wrapper_recommended"] is False
    assert "file_read" in module["function_details"]["io_fileio_read_mode"]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_compressed_archive_file_read_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import bz2
import gzip
import lzma
import tarfile
from gzip import open as gzip_open_alias

def gzip_open_read() -> bytes:
    """Read through gzip.open."""
    with gzip.open("records.csv.gz", "rb") as handle:
        return handle.read()

def gzip_alias_open_read() -> bytes:
    """Read through an imported gzip.open alias."""
    with gzip_open_alias("records.csv.gz", "rb") as handle:
        return handle.read()

def bz2_open_read() -> bytes:
    """Read through bz2.open."""
    with bz2.open("records.csv.bz2", "rb") as handle:
        return handle.read()

def lzma_open_read() -> bytes:
    """Read through lzma.open."""
    with lzma.open("records.csv.xz", "rb") as handle:
        return handle.read()

def tar_open_names() -> list[str]:
    """Read archive members through tarfile.open."""
    with tarfile.open("records.tar") as archive:
        return archive.getnames()

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_compressed_archive_file_read_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_compressed_archive_file_read_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("gzip_open_read", "gzip_alias_open_read", "bz2_open_read", "lzma_open_read", "tar_open_names"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_implicit_file_read_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import fileinput
import linecache
import tokenize
from fileinput import FileInput, input as fileinput_input_alias
from linecache import getline as linecache_getline_alias
from tokenize import open as tokenize_open_alias

def fileinput_input_read() -> list[str]:
    """Read through fileinput.input."""
    return list(fileinput.input("settings.ini"))

def fileinput_alias_read() -> list[str]:
    """Read through an imported fileinput.input alias."""
    return list(fileinput_input_alias("settings.ini"))

def fileinput_class_read() -> list[str]:
    """Read through fileinput.FileInput."""
    with fileinput.FileInput("settings.ini") as lines:
        return list(lines)

def fileinput_class_input_read() -> list[str]:
    """Read through an imported fileinput.FileInput method alias."""
    return list(FileInput.input(files="settings.ini"))

def linecache_getline_read() -> str:
    """Read one cached source line."""
    return linecache.getline("settings.ini", 1)

def linecache_getlines_read() -> list[str]:
    """Read cached source lines."""
    return linecache.getlines("settings.ini")

def linecache_alias_getline_read() -> str:
    """Read one cached source line through an imported alias."""
    return linecache_getline_alias("settings.ini", 1)

def tokenize_open_read() -> str:
    """Read through tokenize.open."""
    with tokenize.open("script.py") as handle:
        return handle.readline()

def tokenize_alias_open_read() -> str:
    """Read through an imported tokenize.open alias."""
    with tokenize_open_alias("script.py") as handle:
        return handle.readline()

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_implicit_file_read_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_implicit_file_read_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "fileinput_input_read",
        "fileinput_alias_read",
        "fileinput_class_read",
        "fileinput_class_input_read",
        "linecache_getline_read",
        "linecache_getlines_read",
        "linecache_alias_getline_read",
        "tokenize_open_read",
        "tokenize_alias_open_read",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_file_backed_store_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import dbm
import dbm.dumb
import shelve
from shelve import open as shelve_open_alias

def shelve_store_keys() -> list[str]:
    """Open a file-backed shelve store."""
    with shelve.open("cache.db") as store:
        return list(store.keys())

def shelve_alias_store_keys() -> list[str]:
    """Open a file-backed shelve store through an import alias."""
    with shelve_open_alias("cache.db") as store:
        return list(store.keys())

def dbm_store_keys() -> list[bytes]:
    """Open a dbm store."""
    with dbm.open("cache.db", "c") as store:
        return list(store.keys())

def dbm_dumb_store_keys() -> list[bytes]:
    """Open a dumb dbm store."""
    with dbm.dumb.open("cache.db", "c") as store:
        return list(store.keys())

def echo_text(text: str) -> str:
    """Return stripped text."""
    return text.strip()
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_file_backed_store_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_file_backed_store_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "shelve_store_keys",
        "shelve_alias_store_keys",
        "dbm_store_keys",
        "dbm_dumb_store_keys",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo_text"}


def _write_runtime_state_alias_mutation_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import os
import sys

def alias_env_status(value: str) -> str:
    """Mutate process environment through a local alias."""
    env = os.environ
    env["APP_MODE"] = value
    return value

def alias_env_update_status(value: str) -> str:
    """Update process environment through a local alias."""
    env = os.environ
    env.update({"APP_MODE": value})
    return value

def alias_path_status(path: str) -> str:
    """Mutate import paths through a local alias."""
    paths = sys.path
    paths.append(path)
    return path

def alias_modules_status(name: str) -> str:
    """Mutate import cache through a local alias."""
    modules = sys.modules
    modules.pop(name, None)
    return name

def read_env_value(key: str) -> str:
    """Read process environment through a local alias."""
    env = os.environ
    return env.get(key, "")

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_runtime_state_alias_mutation_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_runtime_state_alias_mutation_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("alias_env_status", "alias_env_update_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "environment_mutation" in module["function_details"][name]["risk_reasons"]
    for name in ("alias_path_status", "alias_modules_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["read_env_value"]["wrapper_recommended"] is True
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo", "read_env_value"}


def _write_getattr_runtime_state_mutation_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import os
import sys
from functools import partial

def direct_env_status(value: str) -> str:
    """Update process environment through a literal getattr result."""
    getattr(os, "environ").update({"APP_MODE": value})
    return value

def direct_env_item_status(value: str) -> str:
    """Mutate process environment item through a literal getattr result."""
    getattr(os, "environ")["APP_MODE"] = value
    return value

def alias_env_status(value: str) -> str:
    """Mutate process environment through a getattr alias."""
    env = getattr(os, "environ")
    env["APP_MODE"] = value
    return value

def alias_env_update_status(value: str) -> str:
    """Update process environment through a getattr alias."""
    env = getattr(os, "environ")
    env.update({"APP_MODE": value})
    return value

def method_alias_env_status(value: str) -> str:
    """Update process environment through a method alias from getattr."""
    update_env = getattr(os, "environ").update
    update_env({"APP_MODE": value})
    return value

def partial_env_status(value: str) -> str:
    """Update process environment through a partial method alias from getattr."""
    update_env = partial(getattr(os, "environ").update, {"APP_MODE": value})
    update_env()
    return value

def direct_path_status(path: str) -> str:
    """Mutate import paths through a literal getattr result."""
    getattr(sys, "path").append(path)
    return path

def direct_modules_status(name: str) -> str:
    """Mutate import cache through a literal getattr result."""
    getattr(sys, "modules").pop(name, None)
    return name

def alias_path_status(path: str) -> str:
    """Mutate import paths through a getattr alias."""
    paths = getattr(sys, "path")
    paths.append(path)
    return path

def alias_modules_status(name: str) -> str:
    """Mutate import cache through a getattr alias."""
    modules = getattr(sys, "modules")
    modules.pop(name, None)
    return name

def read_env_value(key: str) -> str:
    """Read process environment through a getattr alias."""
    env = getattr(os, "environ")
    return env.get(key, "")

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_getattr_runtime_state_mutation_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_getattr_runtime_state_mutation_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "direct_env_status",
        "direct_env_item_status",
        "alias_env_status",
        "alias_env_update_status",
        "method_alias_env_status",
        "partial_env_status",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "environment_mutation" in module["function_details"][name]["risk_reasons"]
    for name in ("direct_path_status", "direct_modules_status", "alias_path_status", "alias_modules_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["read_env_value"]["wrapper_recommended"] is True
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo", "read_env_value"}


def _write_reflected_runtime_state_mutation_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import os
import sys

def reflect_env_status(value: str) -> str:
    """Replace process environment through reflected assignment."""
    setattr(os, "environ", {"APP_MODE": value})
    return value

def reflect_env_delete_status() -> str:
    """Delete process environment through reflected assignment."""
    delattr(os, "environ")
    return "deleted"

def reflect_path_status(path: str) -> str:
    """Replace import paths through reflected assignment."""
    setattr(sys, "path", [path])
    return path

def reflect_modules_delete_status() -> str:
    """Delete import cache through reflected assignment."""
    delattr(sys, "modules")
    return "deleted"

def tag_text(value: str) -> str:
    """Attach a tag to a local object."""
    class Box:
        pass
    box = Box()
    setattr(box, "tag", value)
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_reflected_runtime_state_mutation_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_reflected_runtime_state_mutation_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("reflect_env_status", "reflect_env_delete_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "environment_mutation" in module["function_details"][name]["risk_reasons"]
    for name in ("reflect_path_status", "reflect_modules_delete_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["tag_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"tag_text"}


def _write_runtime_callback_registration_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import atexit
import signal
from atexit import register as add_exit_hook
from signal import signal as bind_signal

def _cleanup(*args) -> None:
    return None

def status_message() -> str:
    """Return status after preparing cleanup."""
    atexit.register(_cleanup)
    return "registered"

def terminal_message() -> str:
    """Return terminal status."""
    signal.signal(signal.SIGTERM, _cleanup)
    return "installed"

def alias_status() -> str:
    """Return status after preparing cleanup via alias."""
    add_exit_hook(_cleanup)
    return "registered"

def alias_terminal() -> str:
    """Return terminal status via alias."""
    bind_signal(signal.SIGINT, _cleanup)
    return "installed"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_runtime_callback_registration_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_runtime_callback_registration_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("status_message", "terminal_message", "alias_status", "alias_terminal"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_socket_network_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import socket
from socket import create_connection as dial

def endpoint_status() -> str:
    """Return endpoint status after opening a local listener."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.close()
    return "ready"

def remote_status() -> str:
    """Return remote status after opening a connection."""
    conn = socket.create_connection(("example.com", 80), timeout=1)
    conn.close()
    return "connected"

def alias_remote_status() -> str:
    """Return remote status after opening a connection via alias."""
    conn = dial(("example.com", 80), timeout=1)
    conn.close()
    return "connected"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_socket_network_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_socket_network_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("endpoint_status", "remote_status", "alias_remote_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_server_network_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import http.server
import socketserver
from http.server import HTTPServer
from wsgiref.simple_server import make_server

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        pass

class _TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        pass

def _wsgi_app(environ, start_response):
    return []

def local_status() -> str:
    """Return status after constructing a local HTTP server."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    server.server_close()
    return "ready"

def alias_status() -> str:
    """Return status after constructing a local HTTP server through an alias."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.handle_request()
    return "handled"

def tcp_status() -> str:
    """Return status after constructing a TCP server."""
    server = socketserver.TCPServer(("127.0.0.1", 0), _TCPHandler)
    server.server_close()
    return "ready"

def wsgi_status() -> str:
    """Return status after constructing a WSGI server."""
    server = make_server("127.0.0.1", 0, _wsgi_app)
    server.server_close()
    return "ready"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_server_network_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_server_network_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("local_status", "alias_status", "tcp_status", "wsgi_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_public_server_entrypoint_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import http.server
import socketserver

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        pass

class TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        pass

def wsgi_app(environ, start_response):
    return []

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_public_server_entrypoints(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_public_server_entrypoint_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("Handler", "TCPHandler"):
        assert module["class_details"][name]["wrapper_recommended"] is False
        assert "network_server_handler_class" in module["class_details"][name]["risk_reasons"]
    assert module["function_details"]["wsgi_app"]["wrapper_recommended"] is False
    assert "framework_entrypoint_signature" in module["function_details"]["wsgi_app"]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_protocol_network_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import ftplib
import http.client
import smtplib
import xmlrpc.client
from smtplib import SMTP as Mailer

def http_status() -> str:
    """Return status after making an HTTP request."""
    conn = http.client.HTTPConnection("example.com")
    conn.request("GET", "/")
    return "requested"

def smtp_status() -> str:
    """Return status after sending SMTP mail."""
    smtp = smtplib.SMTP("mail.example.com")
    smtp.sendmail("from@example.com", ["to@example.com"], "hello")
    return "sent"

def ftp_status() -> str:
    """Return status after opening FTP."""
    ftp = ftplib.FTP("ftp.example.com")
    ftp.login()
    return "logged-in"

def alias_mail_status() -> str:
    """Return status after opening SMTP through an alias."""
    smtp = Mailer("mail.example.com")
    smtp.send("hello")
    return "sent"

def rpc_status() -> str:
    """Return status after creating an XML-RPC client."""
    xmlrpc.client.ServerProxy("https://example.com/rpc")
    return "ready"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_protocol_network_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_protocol_network_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("http_status", "smtp_status", "ftp_status", "alias_mail_status", "rpc_status"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_datastore_network_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import mysql.connector
import psycopg
import psycopg2
import pymongo
import redis
from redis import Redis
from sqlalchemy import create_engine

def redis_status() -> str:
    """Return status after connecting to Redis."""
    client = redis.Redis(host="localhost", port=6379)
    client.get("key")
    return "ready"

def redis_alias_status() -> str:
    """Return status after connecting to Redis through an alias."""
    client = Redis(host="localhost", port=6379)
    client.set("key", "value")
    return "ready"

def mongo_status() -> str:
    """Return status after connecting to MongoDB."""
    client = pymongo.MongoClient("mongodb://localhost:27017")
    client.admin.command("ping")
    return "ready"

def postgres_status() -> str:
    """Return status after connecting to PostgreSQL."""
    conn = psycopg2.connect(host="localhost", dbname="demo")
    conn.cursor()
    return "ready"

def psycopg_status() -> str:
    """Return status after connecting through psycopg."""
    conn = psycopg.connect("postgresql://localhost/demo")
    conn.execute("select 1")
    return "ready"

def mysql_status() -> str:
    """Return status after connecting to MySQL."""
    conn = mysql.connector.connect(host="localhost", user="demo")
    conn.cursor()
    return "ready"

def sqlalchemy_status() -> str:
    """Return status after creating a database engine."""
    engine = create_engine("postgresql://localhost/demo")
    engine.connect()
    return "ready"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_datastore_network_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_datastore_network_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "redis_status",
        "redis_alias_status",
        "mongo_status",
        "postgres_status",
        "psycopg_status",
        "mysql_status",
        "sqlalchemy_status",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_background_execution_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import asyncio
import multiprocessing as mp
import threading

def _worker() -> None:
    return None

def cache_refresh() -> str:
    """Schedule a cache refresh in a background thread."""
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return "scheduled"

def timer_refresh() -> str:
    """Schedule a delayed refresh in a background timer."""
    timer = threading.Timer(1.0, _worker)
    timer.start()
    return "scheduled"

def process_refresh() -> str:
    """Schedule a refresh in a child process."""
    proc = mp.Process(target=_worker)
    proc.start()
    return "scheduled"

def task_refresh() -> str:
    """Schedule an asyncio task."""
    asyncio.create_task(asyncio.sleep(0))
    return "scheduled"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_background_execution_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_background_execution_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("cache_refresh", "timer_refresh", "process_refresh", "task_refresh"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "background_execution" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def _write_executor_background_module(source: Path) -> Path:
    file_path = source / "api.py"
    file_path.write_text(
        '''
import _thread
import concurrent.futures as futures
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor as PPE
from concurrent.futures import ThreadPoolExecutor as TPE
from multiprocessing import Pool

def _worker(value: str = "ok") -> str:
    return value

def parallel_status() -> str:
    """Return status after scheduling threaded work."""
    with futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_worker).result()

def process_status() -> str:
    """Return status after scheduling process work."""
    with futures.ProcessPoolExecutor(max_workers=1) as pool:
        return pool.submit(_worker).result()

def alias_parallel_status() -> str:
    """Return status after scheduling via imported thread executor."""
    with TPE(max_workers=1) as pool:
        return list(pool.map(_worker, ["ok"]))[0]

def alias_process_status() -> str:
    """Return status after scheduling via imported process executor."""
    with PPE(max_workers=1) as pool:
        return pool.submit(_worker).result()

def pool_status() -> str:
    """Return status after scheduling via multiprocessing pool."""
    with mp.Pool(1) as pool:
        return pool.apply_async(_worker).get()

def imported_pool_status() -> str:
    """Return status after scheduling via imported multiprocessing pool."""
    with Pool(1) as pool:
        return pool.map(_worker, ["ok"])[0]

def raw_thread_status() -> str:
    """Return status after starting a low-level thread."""
    _thread.start_new_thread(_worker, ())
    return "started"

def echo(value: str) -> str:
    """Return the provided value."""
    return value
''',
        encoding="utf-8",
    )
    return file_path


def test_ast_scan_rejects_executor_background_functions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_executor_background_module(source)

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "parallel_status",
        "process_status",
        "alias_parallel_status",
        "alias_process_status",
        "pool_status",
        "imported_pool_status",
        "raw_thread_status",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "background_execution" in module["function_details"][name]["risk_reasons"]
    assert module["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in module["wrapper_candidates"]} == {"echo"}


def test_ast_scan_does_not_recommend_operational_or_probe_names(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
def update_status(value: str) -> str:
    """Update cached status."""
    return value

def create_report(value: str) -> str:
    """Create a local report."""
    return value

def build_docs(value: str) -> str:
    """Build local docs."""
    return value

def ensure_cache(value: str) -> str:
    """Ensure cached data exists."""
    return value

def append_record(value: str) -> str:
    """Append a record."""
    return value

def attach_ufl_id(value: str) -> str:
    """Attach an identifier."""
    return value

def fit_model(value: str) -> str:
    """Fit a model."""
    return value

def patch_record(value: str) -> str:
    """Patch a record."""
    return value

def post_event(value: str) -> str:
    """Post an event."""
    return value

def rebuild_index(value: str) -> str:
    """Rebuild an internal index."""
    return value

def run_pipeline(value: str) -> str:
    """Run an internal pipeline."""
    return value

def get_config() -> str:
    """Return runtime configuration."""
    return "debug"

def has_gpu() -> bool:
    """Return whether a GPU is available."""
    return False

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in (
        "update_status",
        "append_record",
        "attach_ufl_id",
        "build_docs",
        "create_report",
        "ensure_cache",
        "fit_model",
        "patch_record",
        "post_event",
        "rebuild_index",
        "run_pipeline",
    ):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "operational_tool_name" in module["function_details"][name]["risk_reasons"]
    for name in ("get_config", "has_gpu"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "environment_probe_name" in module["function_details"][name]["risk_reasons"]
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value"}


def test_ast_scan_does_not_recommend_framework_entrypoint_decorators(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        '''
@router.get("/items")
def list_items(limit: int = 10) -> list:
    """HTTP route handler."""
    return []

@click.command()
def rebuild_index(force: bool = False) -> bool:
    """CLI command."""
    return force

@celery_app.task
def sync_orders(count: int = 1) -> int:
    """Background task."""
    return count

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    for name in ("list_items", "rebuild_index", "sync_orders"):
        assert module["function_details"][name]["wrapper_recommended"] is False
        assert "framework_entrypoint_decorator" in module["function_details"][name]["risk_reasons"]
    assert {item["name"] for item in module["wrapper_candidates"]} == {"compute_value"}


def test_external_ast_scan_does_not_treat_import_paths_as_file_resources(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
def resolve_module(module_path: str, import_path: str) -> str:
    """Resolve a dotted import target."""
    return module_path or import_path

def read_file(file_path: str) -> str:
    """Read a user supplied file."""
    return file_path
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    import_risks = parsed["function_details"]["resolve_module"]["risk_reasons"]
    file_risks = parsed["function_details"]["read_file"]["risk_reasons"]
    assert "path_parameter_requires_guard" not in import_risks
    assert "path_parameter_requires_guard" in file_risks
    assert "external_resource_parameter" in file_risks
    assert parsed["function_details"]["resolve_module"]["wrapper_score"] == 100
    assert parsed["function_details"]["read_file"]["wrapper_score"] < 55
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"resolve_module"}


def test_external_ast_scan_uses_temp_script_file_and_cleans_up(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text("def compute_value(value: str) -> str:\n    return value\n", encoding="utf-8")
    captured = {}

    class Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps({
            "functions": {"compute_value": ["value"]},
            "classes": [],
            "function_details": {},
            "class_details": {},
            "wrapper_candidates": [],
        })

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        script_path = Path(command[1])
        captured["script_path"] = script_path
        assert command[1] != "-c"
        assert script_path.is_file()
        assert command[2:] == [str(file_path), "api", "api.py"]
        return Proc()

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [(["python"], "test-python")])
    monkeypatch.setattr(analysis_module.subprocess, "run", fake_run)

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["parser"] == "external:test-python"
    assert captured["kwargs"]["shell"] is False
    assert not captured["script_path"].exists()


def test_external_ast_scan_does_not_recommend_void_return_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
def update_cache(value: str) -> None:
    """Update internal cache."""
    return None

def normalize_in_place(value: str):
    """Normalize without returning a value."""
    cleaned = value.strip()

def clear_value(value: str):
    """Return no useful result."""
    return None

def todo_value(value: str):
    """Placeholder with a sentinel return."""
    return NotImplemented

def todo_raiser(value: str) -> str:
    """Placeholder with a typed return."""
    raise NotImplementedError

def outer_helper(value: str):
    """Nested returns do not make the outer function useful."""
    def inner():
        return value
    inner()

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["functions"]["update_cache"] == ["value"]
    assert parsed["function_details"]["update_cache"]["wrapper_recommended"] is False
    assert "void_return" in parsed["function_details"]["update_cache"]["risk_reasons"]
    assert parsed["function_details"]["update_cache"]["wrapper_score"] < 55
    assert parsed["function_details"]["normalize_in_place"]["wrapper_recommended"] is False
    assert "void_return" in parsed["function_details"]["normalize_in_place"]["risk_reasons"]
    assert parsed["function_details"]["clear_value"]["wrapper_recommended"] is False
    assert "void_return" in parsed["function_details"]["clear_value"]["risk_reasons"]
    assert parsed["function_details"]["todo_value"]["wrapper_recommended"] is False
    assert "unsupported_placeholder" in parsed["function_details"]["todo_value"]["risk_reasons"]
    assert parsed["function_details"]["todo_raiser"]["wrapper_recommended"] is False
    assert "unsupported_placeholder" in parsed["function_details"]["todo_raiser"]["risk_reasons"]
    assert parsed["function_details"]["outer_helper"]["wrapper_recommended"] is False
    assert "void_return" in parsed["function_details"]["outer_helper"]["risk_reasons"]
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value"}


def test_external_ast_scan_allows_dynamic_signature_functions_with_explicit_params(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
def combine(value: int, *extras: int, **options: int) -> int:
    """Combine values with dynamic options."""
    return value + sum(extras) + int(options.get("offset", 0))

def compute_value(value: int) -> int:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    detail = parsed["function_details"]["combine"]
    assert detail["has_varargs"] is True
    assert detail["has_kwargs"] is True
    assert "dynamic_signature" in detail["risk_reasons"]
    assert "pure_dynamic_signature" not in detail["risk_reasons"]
    assert detail["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"combine", "compute_value"}


def test_external_ast_scan_does_not_recommend_pure_dynamic_signature_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
def combine(*extras: int, **options: int) -> int:
    """Combine values with dynamic options."""
    return sum(extras) + int(options.get("offset", 0))

def compute_value(value: int) -> int:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    detail = parsed["function_details"]["combine"]
    assert detail["has_varargs"] is True
    assert detail["has_kwargs"] is True
    assert "dynamic_signature" in detail["risk_reasons"]
    assert "pure_dynamic_signature" in detail["risk_reasons"]
    assert detail["wrapper_recommended"] is False
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value"}


def test_external_ast_scan_does_not_recommend_async_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
async def fetch_value(query: str) -> str:
    """Fetch a value asynchronously."""
    return query

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["functions"]["fetch_value"] == ["query"]
    assert parsed["function_details"]["fetch_value"]["is_async"] is True
    assert parsed["function_details"]["fetch_value"]["wrapper_recommended"] is False
    assert "async_function" in parsed["function_details"]["fetch_value"]["risk_reasons"]
    assert parsed["function_details"]["fetch_value"]["wrapper_score"] == 20
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value"}


def test_external_ast_scan_does_not_recommend_imported_global_state_calls(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
from framework.workflow import R

def list_recorders(experiment: str) -> dict:
    """List recorders from the framework's active experiment."""
    return R.get_exp(experiment_name=experiment).list_recorders()

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["functions"]["list_recorders"] == ["experiment"]
    assert parsed["function_details"]["list_recorders"]["wrapper_recommended"] is False
    assert "global_state_dependency" in parsed["function_details"]["list_recorders"]["risk_reasons"]
    assert parsed["function_details"]["list_recorders"]["wrapper_score"] == 40
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value"}


def test_external_ast_scan_rejects_network_client_constructor_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_network_client_constructor_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "make_aiohttp_session",
        "make_aiohttp_alias_session",
        "fetch_with_requests_session",
        "fetch_with_requests_session_alias",
        "fetch_with_httpx_client",
        "fetch_with_httpx_chain",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_value"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_value"}


def test_external_ast_scan_rejects_direct_network_request_methods(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_direct_network_method_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "aiohttp_direct_request_status",
        "aiohttp_alias_request_status",
        "requests_head_status",
        "requests_options_status",
        "requests_generic_request_status",
        "requests_alias_head_status",
        "httpx_head_status",
        "httpx_options_status",
        "httpx_generic_request_status",
        "httpx_stream_status",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_value"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_value"}


def test_external_ast_scan_rejects_url_opener_network_client_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_url_opener_network_client_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "fetch_with_urllib_opener",
        "fetch_with_urllib_opener_alias",
        "fetch_with_urllib3_pool",
        "fetch_with_urllib3_proxy",
        "fetch_with_urllib3_top_level",
        "fetch_with_urllib3_top_level_alias",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_value"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_value"}


def test_external_ast_scan_does_not_recommend_runtime_side_effect_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
import requests as rq
import urllib.request
import webbrowser
import configparser
import glob
import joblib
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
from PIL import Image
import polars as pl
import shutil
import sqlite3
import torch as th
import zipfile
from pathlib import Path
from scipy.io import savemat as save_matrix
from subprocess import check_output as run_output, getoutput as shell_output

def run_command(command: str) -> str:
    """Run an external command."""
    return run_output(command)

def exec_command(command: str) -> None:
    """Replace this process with an external command."""
    os.execvp(command, [command])

def shell_command_text(command: str) -> str:
    """Run a shell command and return text output."""
    return shell_output(command)

def start_local_file(path: str) -> None:
    """Open a local file with the platform shell."""
    os.startfile(path)

def fetch_remote(url: str) -> dict:
    """Fetch remote JSON."""
    return rq.get(url).json()

def fetch_url(url: str) -> bytes:
    """Fetch remote bytes."""
    return urllib.request.urlopen(url).read()

def download_remote_file(url: str, filename: str) -> str:
    """Download a remote file."""
    return urllib.request.urlretrieve(url, filename)[0]

def open_browser(url: str) -> bool:
    """Open a URL in the system browser."""
    return webbrowser.open(url)

def save_report(text: str) -> str:
    """Save a local report."""
    with open("report.txt", "w") as handle:
        handle.write(text)
    return text

def normalize_mode(value: str) -> str:
    """Normalize a runtime mode string."""
    os.environ["APP_MODE"] = value
    return value.lower()

def apply_locale(value: str) -> str:
    """Apply a runtime locale string."""
    os.putenv("APP_LOCALE", value)
    return value

def select_workspace() -> str:
    """Select the default workspace."""
    os.chdir("workspace")
    return os.getcwd()

def restrict_creation_mask() -> int:
    """Restrict file creation permissions."""
    return os.umask(0o077)

def summarize_report(report_path: str) -> str:
    """Summarize a local report file."""
    return Path(report_path).read_text()[:20]

def table_columns(table_path: str) -> list:
    """Return columns from a local table file."""
    return list(pd.read_csv(table_path).columns)

def export_default_report() -> str:
    """Export a bundled report."""
    pd.DataFrame({"value": [1, 2]}).to_csv("report.csv", index=False)
    return "report.csv"

def export_default_json() -> str:
    """Export bundled JSON."""
    pd.DataFrame({"value": [1, 2]}).to_json("report.json")
    return "report.json"

def export_default_html() -> str:
    """Export bundled HTML."""
    pd.DataFrame({"value": [1, 2]}).to_html("report.html")
    return "report.html"

def export_default_markdown() -> str:
    """Export bundled Markdown."""
    pd.DataFrame({"value": [1, 2]}).to_markdown(buf="report.md")
    return "report.md"

def export_default_latex() -> str:
    """Export bundled LaTeX."""
    pd.DataFrame({"value": [1, 2]}).to_latex(buf="report.tex")
    return "report.tex"

def export_default_xml() -> str:
    """Export bundled XML."""
    pd.DataFrame({"value": [1, 2]}).to_xml(path_or_buffer="report.xml")
    return "report.xml"

def export_default_excel() -> str:
    """Export bundled Excel."""
    pd.DataFrame({"value": [1, 2]}).to_excel("report.xlsx")
    return "report.xlsx"

def export_default_parquet() -> str:
    """Export bundled Parquet."""
    pd.DataFrame({"value": [1, 2]}).to_parquet("report.parquet")
    return "report.parquet"

def export_default_pickle() -> str:
    """Export bundled pickle."""
    pd.DataFrame({"value": [1, 2]}).to_pickle("report.pkl")
    return "report.pkl"

def export_numpy_archive() -> str:
    """Export bundled array data."""
    np.savez("arrays.npz", values=np.array([1, 2]))
    return "arrays.npz"

def export_numpy_text() -> str:
    """Export bundled array text."""
    np.savetxt("arrays.csv", np.array([1, 2]))
    return "arrays.csv"

def export_default_model() -> str:
    """Export a bundled serialized model."""
    joblib.dump({"value": [1, 2]}, "model.joblib")
    return "model.joblib"

def export_default_weights() -> str:
    """Export bundled model weights."""
    th.save({"value": [1, 2]}, "weights.pt")
    return "weights.pt"

def export_default_matrix() -> str:
    """Export bundled matrix data."""
    save_matrix("matrix.mat", {"values": [1, 2]})
    return "matrix.mat"

def export_polars_parquet() -> str:
    """Export bundled Polars data."""
    pl.DataFrame({"value": [1, 2]}).write_parquet("polars.parquet")
    return "polars.parquet"

def unpack_archive_members(archive) -> str:
    """Unpack archive members into a local directory."""
    archive.extractall("./unpacked")
    return "./unpacked"

def extract_archive_member(archive) -> str:
    """Extract one archive member into a local directory."""
    archive.extract("payload.txt", "./unpacked")
    return "./unpacked/payload.txt"

def copy_default_tree() -> str:
    """Copy a bundled asset tree."""
    shutil.copytree("assets", "assets_copy")
    return "assets_copy"

def build_default_archive() -> str:
    """Build a bundled archive."""
    return shutil.make_archive("bundle", "zip", "assets")

def update_report_permissions() -> str:
    """Update local report permissions."""
    os.chmod("report.txt", 0o600)
    return "report.txt"

def link_report() -> str:
    """Create a local hard link."""
    os.link("report.txt", "report.link")
    return "report.link"

def symlink_report() -> str:
    """Create a local symlink."""
    Path("report.symlink").symlink_to("report.txt")
    return "report.symlink"

def chmod_report_path() -> str:
    """Change local report permissions via Path."""
    Path("report.txt").chmod(0o600)
    return "report.txt"

def export_default_image() -> str:
    """Export a bundled image."""
    image = Image.new("RGB", (1, 1))
    image.save("preview.png")
    return "preview.png"

def render_default_chart() -> str:
    """Render a bundled chart."""
    plt.savefig("chart.png")
    return "chart.png"

def render_csv_text() -> str:
    """Render a CSV string."""
    return pd.DataFrame({"value": [1, 2]}).to_csv(index=False)

def load_default_numbers() -> list:
    """Load numbers from a bundled data file."""
    return np.loadtxt("data.csv").tolist()

def load_default_memmap() -> list:
    """Load numbers from a bundled memory-mapped file."""
    return np.memmap("data.npy", dtype="float32", mode="r")[:3].tolist()

def list_default_data() -> list:
    """List files from a bundled data directory."""
    return os.listdir("data")

def list_matching_files() -> list:
    """List matching files from a bundled data directory."""
    return glob.glob("data/*.csv")

def inspect_archive() -> list:
    """Inspect a bundled archive file."""
    with zipfile.ZipFile("data.zip") as archive:
        return archive.namelist()

def read_default_config() -> list:
    """Read bundled configuration defaults."""
    parser = configparser.ConfigParser()
    parser.read("settings.ini")
    return parser.sections()

def count_default_records() -> int:
    """Count records from a bundled sqlite database."""
    conn = sqlite3.connect("records.db")
    try:
        return conn.execute("select count(*) from records").fetchone()[0]
    finally:
        conn.close()

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["function_details"]["run_command"]["wrapper_recommended"] is False
    assert "process_execution" in parsed["function_details"]["run_command"]["risk_reasons"]
    assert parsed["function_details"]["exec_command"]["wrapper_recommended"] is False
    assert "process_execution" in parsed["function_details"]["exec_command"]["risk_reasons"]
    assert parsed["function_details"]["shell_command_text"]["wrapper_recommended"] is False
    assert "process_execution" in parsed["function_details"]["shell_command_text"]["risk_reasons"]
    assert parsed["function_details"]["start_local_file"]["wrapper_recommended"] is False
    assert "process_execution" in parsed["function_details"]["start_local_file"]["risk_reasons"]
    assert parsed["function_details"]["fetch_remote"]["wrapper_recommended"] is False
    assert "network_operation" in parsed["function_details"]["fetch_remote"]["risk_reasons"]
    assert parsed["function_details"]["fetch_url"]["wrapper_recommended"] is False
    assert "network_operation" in parsed["function_details"]["fetch_url"]["risk_reasons"]
    assert parsed["function_details"]["download_remote_file"]["wrapper_recommended"] is False
    assert "network_operation" in parsed["function_details"]["download_remote_file"]["risk_reasons"]
    assert parsed["function_details"]["open_browser"]["wrapper_recommended"] is False
    assert "process_execution" in parsed["function_details"]["open_browser"]["risk_reasons"]
    assert parsed["function_details"]["save_report"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["save_report"]["risk_reasons"]
    assert parsed["function_details"]["normalize_mode"]["wrapper_recommended"] is False
    assert "environment_mutation" in parsed["function_details"]["normalize_mode"]["risk_reasons"]
    assert parsed["function_details"]["apply_locale"]["wrapper_recommended"] is False
    assert "environment_mutation" in parsed["function_details"]["apply_locale"]["risk_reasons"]
    assert parsed["function_details"]["select_workspace"]["wrapper_recommended"] is False
    assert "process_state_mutation" in parsed["function_details"]["select_workspace"]["risk_reasons"]
    assert parsed["function_details"]["restrict_creation_mask"]["wrapper_recommended"] is False
    assert "process_state_mutation" in parsed["function_details"]["restrict_creation_mask"]["risk_reasons"]
    assert parsed["function_details"]["summarize_report"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["summarize_report"]["risk_reasons"]
    assert parsed["function_details"]["table_columns"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["table_columns"]["risk_reasons"]
    assert parsed["function_details"]["export_default_report"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_report"]["risk_reasons"]
    assert parsed["function_details"]["export_default_json"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_json"]["risk_reasons"]
    assert parsed["function_details"]["export_default_html"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_html"]["risk_reasons"]
    assert parsed["function_details"]["export_default_markdown"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_markdown"]["risk_reasons"]
    assert parsed["function_details"]["export_default_latex"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_latex"]["risk_reasons"]
    assert parsed["function_details"]["export_default_xml"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_xml"]["risk_reasons"]
    assert parsed["function_details"]["export_default_excel"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_excel"]["risk_reasons"]
    assert parsed["function_details"]["export_default_parquet"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_parquet"]["risk_reasons"]
    assert parsed["function_details"]["export_default_pickle"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_pickle"]["risk_reasons"]
    assert parsed["function_details"]["export_numpy_archive"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_numpy_archive"]["risk_reasons"]
    assert parsed["function_details"]["export_numpy_text"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_numpy_text"]["risk_reasons"]
    assert parsed["function_details"]["export_default_model"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_model"]["risk_reasons"]
    assert parsed["function_details"]["export_default_weights"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_weights"]["risk_reasons"]
    assert parsed["function_details"]["export_default_matrix"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_matrix"]["risk_reasons"]
    assert parsed["function_details"]["export_polars_parquet"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_polars_parquet"]["risk_reasons"]
    assert parsed["function_details"]["unpack_archive_members"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["unpack_archive_members"]["risk_reasons"]
    assert parsed["function_details"]["extract_archive_member"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["extract_archive_member"]["risk_reasons"]
    assert parsed["function_details"]["copy_default_tree"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["copy_default_tree"]["risk_reasons"]
    assert parsed["function_details"]["build_default_archive"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["build_default_archive"]["risk_reasons"]
    assert parsed["function_details"]["update_report_permissions"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["update_report_permissions"]["risk_reasons"]
    assert parsed["function_details"]["link_report"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["link_report"]["risk_reasons"]
    assert parsed["function_details"]["symlink_report"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["symlink_report"]["risk_reasons"]
    assert parsed["function_details"]["chmod_report_path"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["chmod_report_path"]["risk_reasons"]
    assert parsed["function_details"]["export_default_image"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["export_default_image"]["risk_reasons"]
    assert parsed["function_details"]["render_default_chart"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["render_default_chart"]["risk_reasons"]
    assert parsed["function_details"]["render_csv_text"]["wrapper_recommended"] is True
    assert parsed["function_details"]["load_default_numbers"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["load_default_numbers"]["risk_reasons"]
    assert parsed["function_details"]["load_default_memmap"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["load_default_memmap"]["risk_reasons"]
    assert parsed["function_details"]["list_default_data"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["list_default_data"]["risk_reasons"]
    assert parsed["function_details"]["list_matching_files"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["list_matching_files"]["risk_reasons"]
    assert parsed["function_details"]["inspect_archive"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["inspect_archive"]["risk_reasons"]
    assert parsed["function_details"]["read_default_config"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["read_default_config"]["risk_reasons"]
    assert parsed["function_details"]["count_default_records"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["count_default_records"]["risk_reasons"]
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value", "render_csv_text"}


def test_external_ast_scan_rejects_tempfile_mutation_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_tempfile_mutation_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("named_temp_status", "alias_temp_status", "temp_dir_status", "mkstemp_status", "mkdtemp_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_getattr_runtime_side_effect_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_getattr_runtime_side_effect_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("status_code", "job_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_execution" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["transfer_status"]["wrapper_recommended"] is False
    assert "network_operation" in parsed["function_details"]["transfer_status"]["risk_reasons"]
    assert parsed["function_details"]["scratch_status"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["scratch_status"]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_partial_runtime_side_effect_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_partial_runtime_side_effect_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("status_code", "job_status", "getattr_partial_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_execution" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["transfer_status"]["wrapper_recommended"] is False
    assert "network_operation" in parsed["function_details"]["transfer_status"]["risk_reasons"]
    assert parsed["function_details"]["scratch_status"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["scratch_status"]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_dynamic_code_execution_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_dynamic_code_execution_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "formula_value",
        "builtin_formula_value",
        "alias_formula_value",
        "statement_status",
        "alias_statement_status",
        "compiled_status",
        "alias_compiled_status",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "dynamic_code_execution" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_dynamic_import_runtime_side_effect_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_dynamic_import_runtime_side_effect_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("alpha_status", "beta_status", "gamma_status", "delta_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_execution" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["epsilon_status"]["wrapper_recommended"] is False
    assert "network_operation" in parsed["function_details"]["epsilon_status"]["risk_reasons"]
    assert parsed["function_details"]["zeta_status"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["zeta_status"]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_runtime_global_mutation_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_runtime_global_mutation_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "add_runtime_import_path",
        "forget_cached_module",
        "configure_warnings",
        "configure_logging",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_runtime_state_alias_mutation_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_runtime_state_alias_mutation_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("alias_env_status", "alias_env_update_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "environment_mutation" in parsed["function_details"][name]["risk_reasons"]
    for name in ("alias_path_status", "alias_modules_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["read_env_value"]["wrapper_recommended"] is True
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo", "read_env_value"}


def test_external_ast_scan_rejects_path_object_alias_file_read_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_path_object_alias_file_read_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "direct_iterdir_names",
        "alias_iterdir_names",
        "alias_glob_names",
        "alias_rglob_names",
        "cwd_iterdir_names",
        "alias_cwd_iterdir_names",
        "home_glob_names",
        "alias_home_read_text",
        "chained_alias_read_text",
        "chained_alias_iterdir_names",
        "resolve_alias_iterdir_names",
        "expanduser_alias_glob_names",
        "parent_iterdir_names",
        "alias_parent_glob_names",
        "parents_index_iterdir_names",
        "alias_read_text",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_path_open_write_mode_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_path_open_mode_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("path_open_write_mode", "alias_path_open_append_mode", "pathlib_open_exclusive_mode"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in parsed["function_details"][name]["risk_reasons"]
        assert "file_read" not in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["path_open_read_mode"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["path_open_read_mode"]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_file_metadata_read_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_file_metadata_read_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "path_exists",
        "alias_is_file",
        "path_stat_size",
        "os_path_getsize",
        "os_stat_size",
        "os_path_alias_getsize",
        "os_path_alias_exists",
        "os_path_alias_isfile",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_open_alias_file_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_open_alias_file_read_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("alias_builtin_open_read", "alias_io_open_read"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["alias_builtin_open_write"]["wrapper_recommended"] is False
    assert "file_mutation" in parsed["function_details"]["alias_builtin_open_write"]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_os_descriptor_file_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_os_descriptor_file_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("fdopen_write_mode", "fdopen_alias_append_mode", "os_open_write_flags", "os_open_alias_write_flags"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["os_open_read_flags"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["os_open_read_flags"]["risk_reasons"]
    assert "file_mutation" not in parsed["function_details"]["os_open_read_flags"]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_mode_sensitive_file_open_writes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_mode_sensitive_file_open_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "gzip_open_write_mode",
        "gzip_alias_append_mode",
        "tarfile_open_write_mode",
        "zipfile_open_write_mode",
        "zipfile_alias_append_mode",
        "h5py_file_write_mode",
        "io_fileio_write_mode",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in parsed["function_details"][name]["risk_reasons"]
        assert "file_read" not in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["io_fileio_read_mode"]["wrapper_recommended"] is False
    assert "file_read" in parsed["function_details"]["io_fileio_read_mode"]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_compressed_archive_file_read_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_compressed_archive_file_read_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("gzip_open_read", "gzip_alias_open_read", "bz2_open_read", "lzma_open_read", "tar_open_names"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_implicit_file_read_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_implicit_file_read_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "fileinput_input_read",
        "fileinput_alias_read",
        "fileinput_class_read",
        "fileinput_class_input_read",
        "linecache_getline_read",
        "linecache_getlines_read",
        "linecache_alias_getline_read",
        "tokenize_open_read",
        "tokenize_alias_open_read",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_read" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_file_backed_store_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_file_backed_store_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "shelve_store_keys",
        "shelve_alias_store_keys",
        "dbm_store_keys",
        "dbm_dumb_store_keys",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "file_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo_text"}


def test_external_ast_scan_rejects_getattr_runtime_state_mutation_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_getattr_runtime_state_mutation_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "direct_env_status",
        "direct_env_item_status",
        "alias_env_status",
        "alias_env_update_status",
        "method_alias_env_status",
        "partial_env_status",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "environment_mutation" in parsed["function_details"][name]["risk_reasons"]
    for name in ("direct_path_status", "direct_modules_status", "alias_path_status", "alias_modules_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["read_env_value"]["wrapper_recommended"] is True
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo", "read_env_value"}


def test_external_ast_scan_rejects_reflected_runtime_state_mutation_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_reflected_runtime_state_mutation_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("reflect_env_status", "reflect_env_delete_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "environment_mutation" in parsed["function_details"][name]["risk_reasons"]
    for name in ("reflect_path_status", "reflect_modules_delete_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["tag_text"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"tag_text"}


def test_external_ast_scan_rejects_runtime_callback_registration_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_runtime_callback_registration_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("status_message", "terminal_message", "alias_status", "alias_terminal"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "process_state_mutation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_socket_network_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_socket_network_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("endpoint_status", "remote_status", "alias_remote_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_server_network_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_server_network_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("local_status", "alias_status", "tcp_status", "wsgi_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_public_server_entrypoints(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_public_server_entrypoint_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("Handler", "TCPHandler"):
        assert parsed["class_details"][name]["wrapper_recommended"] is False
        assert "network_server_handler_class" in parsed["class_details"][name]["risk_reasons"]
    assert parsed["function_details"]["wsgi_app"]["wrapper_recommended"] is False
    assert "framework_entrypoint_signature" in parsed["function_details"]["wsgi_app"]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_protocol_network_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_protocol_network_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("http_status", "smtp_status", "ftp_status", "alias_mail_status", "rpc_status"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_datastore_network_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_datastore_network_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "redis_status",
        "redis_alias_status",
        "mongo_status",
        "postgres_status",
        "psycopg_status",
        "mysql_status",
        "sqlalchemy_status",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "network_operation" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_background_execution_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_background_execution_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("cache_refresh", "timer_refresh", "process_refresh", "task_refresh"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "background_execution" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_rejects_executor_background_functions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = _write_executor_background_module(source)

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "parallel_status",
        "process_status",
        "alias_parallel_status",
        "alias_process_status",
        "pool_status",
        "imported_pool_status",
        "raw_thread_status",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "background_execution" in parsed["function_details"][name]["risk_reasons"]
    assert parsed["function_details"]["echo"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"echo"}


def test_external_ast_scan_does_not_recommend_operational_or_probe_names(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
def update_status(value: str) -> str:
    """Update cached status."""
    return value

def create_report(value: str) -> str:
    """Create a local report."""
    return value

def build_docs(value: str) -> str:
    """Build local docs."""
    return value

def ensure_cache(value: str) -> str:
    """Ensure cached data exists."""
    return value

def append_record(value: str) -> str:
    """Append a record."""
    return value

def attach_ufl_id(value: str) -> str:
    """Attach an identifier."""
    return value

def fit_model(value: str) -> str:
    """Fit a model."""
    return value

def patch_record(value: str) -> str:
    """Patch a record."""
    return value

def post_event(value: str) -> str:
    """Post an event."""
    return value

def rebuild_index(value: str) -> str:
    """Rebuild an internal index."""
    return value

def run_pipeline(value: str) -> str:
    """Run an internal pipeline."""
    return value

def get_config() -> str:
    """Return runtime configuration."""
    return "debug"

def has_gpu() -> bool:
    """Return whether a GPU is available."""
    return False

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in (
        "update_status",
        "append_record",
        "attach_ufl_id",
        "build_docs",
        "create_report",
        "ensure_cache",
        "fit_model",
        "patch_record",
        "post_event",
        "rebuild_index",
        "run_pipeline",
    ):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "operational_tool_name" in parsed["function_details"][name]["risk_reasons"]
    for name in ("get_config", "has_gpu"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "environment_probe_name" in parsed["function_details"][name]["risk_reasons"]
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value"}


def test_external_ast_scan_does_not_recommend_framework_entrypoint_decorators(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
@router.get("/items")
def list_items(limit: int = 10) -> list:
    """HTTP route handler."""
    return []

@click.command()
def rebuild_index(force: bool = False) -> bool:
    """CLI command."""
    return force

@celery_app.task
def sync_orders(count: int = 1) -> int:
    """Background task."""
    return count

def compute_value(value: str) -> str:
    """Compute a user-facing value."""
    return value
''',
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    for name in ("list_items", "rebuild_index", "sync_orders"):
        assert parsed["function_details"][name]["wrapper_recommended"] is False
        assert "framework_entrypoint_decorator" in parsed["function_details"][name]["risk_reasons"]
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"compute_value"}


def test_ast_scan_marks_import_time_script_side_effects(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build_assets.py").write_text(
        "def clean(text):\n"
        "    return text.strip()\n\n"
        "rows = load_rows('input.txt')\n"
        "for row in rows:\n"
        "    print(clean(row))\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["build_assets"]

    assert module["import_side_effect_risk"] is True
    assert any(reason.startswith("top_level_assignment_call") for reason in module["import_side_effect_reasons"])
    assert any(reason.startswith("top_level_for") for reason in module["import_side_effect_reasons"])


def test_ast_scan_marks_inverted_main_guard_side_effects(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text(
        "def normalize(value):\n"
        "    return value\n\n"
        "if __name__ != '__main__':\n"
        "    initialize_runtime()\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["api"]

    assert module["import_side_effect_risk"] is True
    assert any(reason.startswith("top_level_if") for reason in module["import_side_effect_reasons"])


def test_external_ast_scan_marks_inverted_main_guard_side_effects(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        "def normalize(value):\n"
        "    return value\n\n"
        "if __name__ != '__main__':\n"
        "    initialize_runtime()\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["import_side_effect_risk"] is True
    assert any(reason.startswith("top_level_if") for reason in parsed["import_side_effect_reasons"])


def test_ast_scan_excludes_keyboard_listener_dependencies_from_candidates(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "listener.py").write_text(
        "from pynput import keyboard\n\n"
        "def log_word(word):\n"
        "    return str(word)\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    detail = symbols["listener"]["function_details"]["log_word"]

    assert detail["wrapper_recommended"] is False
    assert "keyboard_listener_dependency" in detail["risk_reasons"]
    assert symbols["listener"]["wrapper_candidates"] == []


def test_ast_scan_allows_type_checking_and_regex_initializers(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "text_utils.py").write_text(
        "import re\n"
        "import string\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Iterable\n\n"
        "PUNCTUATION_REGEX = re.compile(f'[{re.escape(string.punctuation)}]')\n\n"
        "def strip_punc(text: str):\n"
        "    return PUNCTUATION_REGEX.sub('', text)\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["text_utils"]

    assert module["import_side_effect_risk"] is False
    assert module["import_side_effect_reasons"] == []
    assert module["functions"] == {"strip_punc": ["text"]}


def test_ast_scan_allows_safe_logging_namedtuple_and_import_compat_blocks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "compat.py").write_text(
        "import collections\n"
        "import logging\n"
        "HAS_PY3 = True\n\n"
        "if HAS_PY3:\n"
        "    from urllib.parse import urlencode\n"
        "else:\n"
        "    from urllib import urlencode\n\n"
        "try:\n"
        "    import json\n"
        "    JSON_AVAILABLE = True\n"
        "except ImportError:\n"
        "    JSON_AVAILABLE = False\n\n"
        "logger = logging.getLogger(__name__)\n"
        "Record = collections.namedtuple('Record', ('code',))\n\n"
        "def encode_genotype(code: str):\n"
        "    return code.upper()\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["compat"]

    assert module["import_side_effect_risk"] is False
    assert module["import_side_effect_reasons"] == []
    assert module["functions"] == {"encode_genotype": ["code"]}
    assert module["wrapper_candidates"] == [{"name": "encode_genotype", "kind": "function", "score": 95}]


def test_ast_scan_allows_qualified_type_checking_guard(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "text_utils.py").write_text(
        "import typing as t\n\n"
        "if t.TYPE_CHECKING:\n"
        "    from collections.abc import Iterable\n\n"
        "def normalize(text: str):\n"
        "    return text.strip()\n",
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))
    module = symbols["text_utils"]

    assert module["import_side_effect_risk"] is False
    assert module["import_side_effect_reasons"] == []
    assert module["functions"] == {"normalize": ["text"]}


def test_external_ast_scan_allows_qualified_type_checking_guard(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "text_utils.py"
    file_path.write_text(
        "import typing\n\n"
        "if typing.TYPE_CHECKING:\n"
        "    from collections.abc import Iterable\n\n"
        "def normalize(text: str):\n"
        "    return text.strip()\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "text_utils", "text_utils.py")

    assert parsed is not None
    assert parsed["import_side_effect_risk"] is False
    assert parsed["import_side_effect_reasons"] == []
    assert parsed["functions"] == {"normalize": ["text"]}


def test_external_ast_scan_allows_safe_logging_namedtuple_and_import_compat_blocks(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "compat.py"
    file_path.write_text(
        "import collections\n"
        "import logging\n"
        "HAS_PY3 = True\n\n"
        "if HAS_PY3:\n"
        "    from urllib.parse import urlencode\n"
        "else:\n"
        "    from urllib import urlencode\n\n"
        "try:\n"
        "    import json\n"
        "    JSON_AVAILABLE = True\n"
        "except ImportError:\n"
        "    JSON_AVAILABLE = False\n\n"
        "logger = logging.getLogger(__name__)\n"
        "Record = collections.namedtuple('Record', ('code',))\n\n"
        "def encode_genotype(code: str):\n"
        "    return code.upper()\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "compat", "compat.py")

    assert parsed is not None
    assert parsed["import_side_effect_risk"] is False
    assert parsed["import_side_effect_reasons"] == []
    assert parsed["functions"] == {"encode_genotype": ["code"]}
    assert parsed["wrapper_candidates"] == [{"name": "encode_genotype", "kind": "function", "score": 95}]


def test_external_ast_scan_does_not_recommend_data_container_classes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "models.py"
    file_path.write_text(
        "from dataclasses import dataclass\n"
        "from enum import Enum\n"
        "from typing import TypedDict\n\n"
        "@dataclass\n"
        "class Quote:\n"
        "    symbol: str\n"
        "    price: float\n\n"
        "class Side(Enum):\n"
        "    BUY = 'buy'\n\n"
        "class Payload(TypedDict):\n"
        "    symbol: str\n\n"
        "class Calculator:\n"
        "    def add(self, left: int, right: int) -> int:\n"
        "        return left + right\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "models", "models.py")

    assert parsed is not None
    assert parsed["class_details"]["Quote"]["wrapper_recommended"] is False
    assert "data_container_class" in parsed["class_details"]["Quote"]["risk_reasons"]
    assert parsed["class_details"]["Side"]["wrapper_recommended"] is False
    assert "enum_class" in parsed["class_details"]["Side"]["risk_reasons"]
    assert parsed["class_details"]["Payload"]["wrapper_recommended"] is False
    assert "typed_dict_class" in parsed["class_details"]["Payload"]["risk_reasons"]
    assert parsed["class_details"]["Calculator"]["wrapper_recommended"] is True
    assert parsed["wrapper_candidates"] == [{"name": "Calculator", "kind": "class", "score": 75}]


def test_external_ast_scan_rejects_classes_with_complex_runtime_constructors(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "wrappers.py"
    file_path.write_text(
        "class ClientTool:\n"
        "    def __init__(self, client=None, config=None):\n"
        "        self.client = client\n"
        "        self.config = config\n\n"
        "    def ping(self) -> str:\n"
        "        return 'pong'\n\n"
        "class ModelRunner:\n"
        "    def __init__(self, model=None, dataset=None):\n"
        "        self.model = model\n"
        "        self.dataset = dataset\n\n"
        "    def count(self) -> int:\n"
        "        return 1\n\n"
        "class Formatter:\n"
        "    def __init__(self, prefix: str = ''):\n"
        "        self.prefix = prefix\n\n"
        "    def format(self, text: str) -> str:\n"
        "        return self.prefix + text\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "wrappers", "wrappers.py")

    assert parsed is not None
    assert parsed["class_details"]["ClientTool"]["constructor_complex_parameters"] == ["client", "config"]
    assert "complex_constructor_parameter" in parsed["class_details"]["ClientTool"]["risk_reasons"]
    assert parsed["class_details"]["ClientTool"]["wrapper_recommended"] is False
    assert parsed["class_details"]["ModelRunner"]["constructor_complex_parameters"] == ["model", "dataset"]
    assert parsed["class_details"]["ModelRunner"]["wrapper_recommended"] is False
    assert parsed["class_details"]["Formatter"]["wrapper_recommended"] is True
    assert parsed["wrapper_candidates"] == [{"name": "Formatter", "kind": "class", "score": 75}]


def test_external_ast_scan_skips_class_receivers_but_keeps_top_level_self(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        "def compare(self, other):\n"
        "    return self == other\n\n"
        "def get_base_attr(cls, name):\n"
        "    return getattr(cls, name)\n\n"
        "def assign_precedences(precedence_list):\n"
        "    return [item for item in precedence_list]\n\n"
        "def product(sequence):\n"
        "    return sequence\n\n"
        "def sorted_by_key(mapping):\n"
        "    return sorted(mapping.items())\n\n"
        "class Calculator:\n"
        "    def __init__(self, scale=1):\n"
        "        self.scale = scale\n\n"
        "    def add(self, left: int, right: int) -> int:\n"
        "        return left + right\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert parsed["functions"]["compare"] == ["self", "other"]
    assert "opaque_runtime_parameter" in parsed["function_details"]["compare"]["risk_reasons"]
    assert parsed["function_details"]["compare"]["wrapper_recommended"] is False
    assert parsed["functions"]["get_base_attr"] == ["cls", "name"]
    assert "opaque_runtime_parameter" in parsed["function_details"]["get_base_attr"]["risk_reasons"]
    assert parsed["function_details"]["get_base_attr"]["wrapper_recommended"] is False
    assert parsed["functions"]["assign_precedences"] == ["precedence_list"]
    assert "opaque_runtime_parameter" in parsed["function_details"]["assign_precedences"]["risk_reasons"]
    assert parsed["function_details"]["assign_precedences"]["wrapper_recommended"] is False
    assert parsed["functions"]["product"] == ["sequence"]
    assert "opaque_runtime_parameter" in parsed["function_details"]["product"]["risk_reasons"]
    assert parsed["function_details"]["product"]["wrapper_recommended"] is False
    assert parsed["functions"]["sorted_by_key"] == ["mapping"]
    assert "opaque_runtime_parameter" in parsed["function_details"]["sorted_by_key"]["risk_reasons"]
    assert parsed["function_details"]["sorted_by_key"]["wrapper_recommended"] is False
    calculator = parsed["class_details"]["Calculator"]
    assert calculator["constructor_parameters"] == ["scale"]
    assert calculator["public_methods"][0]["parameters"] == ["left", "right"]


def test_external_ast_scan_rejects_complex_runtime_parameters_before_generation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "pipeline.py"
    file_path.write_text(
        "def train_model(model, dataset):\n"
        "    return len(dataset)\n\n"
        "def configure_client(client, config):\n"
        "    return client\n\n"
        "def format_user(credentials):\n"
        "    return str(credentials)\n\n"
        "def summarize_patient(patient_id):\n"
        "    return patient_id\n\n"
        "def slugify(text: str, separator: str = '-') -> str:\n"
        "    return separator.join(text.lower().split())\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "pipeline", "pipeline.py")

    assert parsed is not None
    assert "complex_runtime_parameter" in parsed["function_details"]["train_model"]["risk_reasons"]
    assert parsed["function_details"]["train_model"]["wrapper_recommended"] is False
    assert "complex_runtime_parameter" in parsed["function_details"]["configure_client"]["risk_reasons"]
    assert parsed["function_details"]["configure_client"]["wrapper_recommended"] is False
    assert "sensitive_parameter" in parsed["function_details"]["format_user"]["risk_reasons"]
    assert parsed["function_details"]["format_user"]["wrapper_recommended"] is False
    assert "sensitive_parameter" in parsed["function_details"]["summarize_patient"]["risk_reasons"]
    assert parsed["function_details"]["summarize_patient"]["wrapper_recommended"] is False
    assert parsed["function_details"]["slugify"]["wrapper_recommended"] is True
    candidates = {item["name"] for item in parsed["wrapper_candidates"]}
    assert candidates == {"slugify"}


def test_external_ast_scan_rejects_plotting_output_and_remote_lookup_names(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    file_path = source / "api.py"
    file_path.write_text(
        '''
def plot_returns(values: list[float]) -> list[float]:
    """Build a plotting helper."""
    return values

def show_versions() -> str:
    """Show runtime package versions."""
    return "1.0"

def kegg_get(identifier: str) -> str:
    """Look up a remote biological database entry."""
    return identifier

def normalize_symbol(symbol: str) -> str:
    """Normalize a practical public value."""
    return symbol.lower()
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(analysis_module, "_analysis_python_candidates", lambda: [([analysis_module.sys.executable], "test-python")])

    parsed = analysis_module._scan_file_with_external_python(str(file_path), "api", "api.py")

    assert parsed is not None
    assert "plotting_helper_name" in parsed["function_details"]["plot_returns"]["risk_reasons"]
    assert parsed["function_details"]["plot_returns"]["wrapper_recommended"] is False
    assert "output_only_name" in parsed["function_details"]["show_versions"]["risk_reasons"]
    assert parsed["function_details"]["show_versions"]["wrapper_recommended"] is False
    assert "remote_lookup_name" in parsed["function_details"]["kegg_get"]["risk_reasons"]
    assert parsed["function_details"]["kegg_get"]["wrapper_recommended"] is False
    assert parsed["function_details"]["normalize_symbol"]["wrapper_recommended"] is True
    assert {item["name"] for item in parsed["wrapper_candidates"]} == {"normalize_symbol"}


def test_ast_scan_accepts_utf8_bom_python_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tools.py").write_text(
        '\ufeffdef slugify(text: str, separator: str = "-") -> str:\n    return separator.join(text.lower().split())\n',
        encoding="utf-8",
    )

    symbols = _scan_source_symbols_with_signatures(str(source))

    assert "tools" in symbols
    assert symbols["tools"]["functions"] == {"slugify": ["text", "separator"]}
    assert symbols["tools"]["function_details"]["slugify"]["parameter_details"][0]["annotation"] == "str"


def test_ast_scan_uses_external_python_fallback_on_parse_error(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "modern.py").write_text("def modern_tool(value):\n    return value\n", encoding="utf-8")

    def fail_parse(code, *args, **kwargs):
        raise SyntaxError("current parser cannot read this file")

    def fake_external(file_path, module_path, rel_path):
        return {
            "functions": {"modern_tool": ["value"]},
            "classes": set(),
            "file_path": rel_path,
            "function_details": {
                "modern_tool": {
                    "name": "modern_tool",
                    "parameters": ["value"],
                    "parameter_details": [{"name": "value", "kind": "positional", "annotation": "", "required": True, "default": ""}],
                    "return_annotation": "",
                    "docstring": "",
                    "line": 1,
                    "is_async": False,
                    "has_varargs": False,
                    "has_kwargs": False,
                    "wrapper_score": 95,
                    "wrapper_recommended": True,
                    "risk_reasons": ["missing_docstring"],
                }
            },
            "class_details": {},
            "wrapper_candidates": [{"name": "modern_tool", "kind": "function", "score": 95}],
            "parser": "external:Python 3.12",
        }

    monkeypatch.setattr(analysis_module.ast, "parse", fail_parse)
    monkeypatch.setattr(analysis_module, "_scan_file_with_external_python", fake_external)

    symbols = _scan_source_symbols_with_signatures(str(source))

    assert symbols["modern"]["functions"] == {"modern_tool": ["value"]}
    assert symbols["modern"]["parser"] == "external:Python 3.12"


def test_package_scan_excludes_generated_output(tmp_path):
    source = tmp_path / "source"
    real_pkg = source / "pkg"
    fake_pkg = source / "mcp_output" / "pkg"
    real_pkg.mkdir(parents=True)
    fake_pkg.mkdir(parents=True)
    (real_pkg / "__init__.py").write_text("", encoding="utf-8")
    (fake_pkg / "__init__.py").write_text("", encoding="utf-8")

    packages = _scan_python_packages(str(source))

    assert packages == ["pkg"]


def test_common_import_scan_detects_pynput_dependency(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "keyboard.py").write_text("from pynput import keyboard\n", encoding="utf-8")

    packages = _scan_common_import_packages(str(source))

    assert "pynput" in packages


def test_common_import_scan_detects_simpleitk_dependency(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "load.py").write_text("import SimpleITK as sitk\n", encoding="utf-8")

    packages = _scan_common_import_packages(str(source))

    assert "SimpleITK" in packages


def test_common_import_scan_detects_common_wheel_dependencies(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "stats.py").write_text(
        "import empyrical as ep\n"
        "import pytz\n"
        "from IPython.display import display\n"
        "from statsmodels.stats.multitest import multipletests\n"
        "from tqdm import tqdm\n"
        "from natsort import natsorted\n",
        encoding="utf-8",
    )

    packages = _scan_common_import_packages(str(source))

    assert "empyrical" in packages
    assert "ipython" in packages
    assert "pytz" in packages
    assert "statsmodels" in packages
    assert "tqdm" in packages
    assert "natsort" in packages


def test_common_import_scan_excludes_test_and_fixture_dependencies(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("import numpy as np\n", encoding="utf-8")
    (source / "test_api.py").write_text("import pandas as pd\nimport requests\n", encoding="utf-8")
    testdata = source / "testdata"
    testdata.mkdir()
    (testdata / "fixture.py").write_text("import scipy\n", encoding="utf-8")

    packages = _scan_common_import_packages(str(source))

    assert packages == ["numpy"]


def test_local_source_summary_excludes_generated_output(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tools.py").write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    generated = source / "mcp_output"
    generated.mkdir()
    (generated / "fake.py").write_text("def fake():\n    return 1\n", encoding="utf-8")

    summary = _summarize_source_tree(str(source), "file:///tmp/local-project")

    assert summary["success"] is True
    assert summary["processed_by"] == "local_source_scan"
    assert "tools.py" in summary["file_tree"]
    assert "tools.py" in summary["content"]
    assert "mcp_output/fake.py" not in summary["file_tree"]


def test_llm_analysis_prompt_includes_static_ast_evidence():
    captured = {}

    class FakeLLM:
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return json.dumps({
                "core_modules": [
                    {"package": "api", "module": "api", "functions": ["load_data"], "classes": []}
                ],
                "cli_commands": [],
                "import_strategy": {"primary": "import", "fallback": "cli", "confidence": 0.8},
                "dependencies": {"required": [], "optional": []},
                "risk_assessment": {"import_feasibility": 0.8, "intrusiveness_risk": "low", "complexity": "simple"},
            })

    static_modules = [
        {
            "package": "api",
            "module": "api",
            "functions": ["load_data"],
            "classes": [],
            "function_signatures": {"load_data": ["file_path"]},
            "file_path": "api.py",
            "wrapper_candidates": [{"name": "load_data", "kind": "function", "score": 90}],
        }
    ]

    result = _analyze_with_llm(
        FakeLLM(),
        "https://github.com/example/demo",
        {"summary": "demo"},
        ["api"],
        {"cli": []},
        {"status": "skipped"},
        static_modules,
    )

    assert "Static AST Source Evidence" in captured["prompt"]
    assert "api.py" in captured["prompt"]
    assert result["core_modules"][0]["functions"] == ["load_data"]


def test_basic_analysis_does_not_invent_main_without_static_symbols():
    result = analysis_module._basic_analysis(["demo_pkg"], {"cli": []})

    assert result["source_of_truth"] == "basic_no_symbol_evidence"
    assert result["core_modules"] == []
    assert result["import_strategy"]["primary"] == "blackbox"
    assert result["risk_assessment"]["import_feasibility"] == 0.2


def test_static_filter_drops_llm_modules_when_no_static_symbols():
    result = analysis_module._filter_core_modules_against_static(
        {
            "core_modules": [
                {"package": "demo", "module": "demo", "functions": ["invented"], "classes": []}
            ],
            "cli_commands": [],
            "import_strategy": {"primary": "import", "fallback": "cli", "confidence": 0.9},
            "risk_assessment": {"import_feasibility": "high", "intrusiveness_risk": "low"},
        },
        [],
    )

    assert result["source_of_truth"] == "no_static_symbol_evidence"
    assert result["core_modules"] == []
    assert result["import_strategy"]["primary"] == "blackbox"
    assert result["risk_assessment"]["import_feasibility"] == 0.2


def test_static_filter_does_not_match_missing_module_by_broad_package():
    static_modules = [
        {
            "package": "pkg",
            "module": "core",
            "functions": ["run"],
            "classes": [],
            "function_signatures": {"run": []},
            "file_path": "pkg/core.py",
        },
        {
            "package": "pkg",
            "module": "other",
            "functions": ["run"],
            "classes": [],
            "function_signatures": {"run": []},
            "file_path": "pkg/other.py",
        },
    ]

    result = analysis_module._filter_core_modules_against_static(
        {
            "core_modules": [
                {"package": "pkg", "module": "missing", "functions": ["run"], "classes": []}
            ],
            "cli_commands": [],
            "import_strategy": {"primary": "import", "fallback": "cli", "confidence": 0.9},
            "risk_assessment": {"import_feasibility": 0.8, "intrusiveness_risk": "low"},
        },
        static_modules,
    )

    assert result["core_modules"] == static_modules
    assert [module["file_path"] for module in result["core_modules"]] == ["pkg/core.py", "pkg/other.py"]


def test_analysis_node_outputs_static_evidence(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        'import pandas as pd\nimport numpy as np\n\n'
        'def load_data(file_path: str):\n    """Load data."""\n    return file_path\n',
        encoding="utf-8",
    )

    class FakeGitingestClient:
        def preprocess_repository_sync(self, repo_url):
            return {"files": ["source/api.py"]}

    monkeypatch.setattr(analysis_module, "GitingestClient", FakeGitingestClient)
    monkeypatch.setattr(
        analysis_module,
        "get_llm_service",
        lambda: (_ for _ in ()).throw(AssertionError("analysis LLM should be opt-in")),
    )
    monkeypatch.setattr(analysis_module, "fetch_deepwiki", lambda url: {"success": False})

    state = {
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {},
    }

    result = analysis_module.analysis_node(state)

    analysis = result["analysis"]
    assert analysis["static_analysis"]["module_count"] == 1
    assert analysis["static_analysis"]["function_count"] == 1
    core = analysis["llm_analysis"]["core_modules"][0]
    assert core["file_path"] == "api.py"
    assert core["function_signatures"] == {"load_data": ["file_path"]}
    assert core["function_details"]["load_data"]["parameter_details"][0]["annotation"] == "str"
    assert "external_resource_parameter" in core["function_details"]["load_data"]["risk_reasons"]
    assert analysis["dependencies"]["import_packages"] == ["numpy", "pandas"]
    assert analysis["dependencies"]["import_package_source"] == "ast_imports"
    assert analysis["static_analysis"]["wrapper_candidate_count"] == 0
    assert analysis["static_analysis"]["recommended_function_count"] == 0
    assert analysis["static_analysis"]["top_wrapper_candidates"] == []


def test_analysis_node_reuses_ast_imports_for_dependency_hints(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "import pandas as pd\n\n"
        "def summarize(values):\n"
        "    return len(values)\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        analysis_module,
        "_scan_common_import_packages",
        lambda _source_dir: (_ for _ in ()).throw(AssertionError("text import scan should not run")),
    )
    monkeypatch.setattr(analysis_module, "fetch_deepwiki", lambda url: {"success": False})

    state = {
        "repository": {
            "url": "https://github.com/example/reuse-imports",
            "name": "reuse-imports",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {},
    }

    result = analysis_module.analysis_node(state)

    assert result["analysis"]["dependencies"]["import_packages"] == ["pandas"]
    assert result["analysis"]["dependencies"]["import_package_source"] == "ast_imports"


def test_analysis_node_outputs_import_side_effect_risk(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "build_assets.py").write_text(
        "def clean(text):\n"
        "    return text.strip()\n\n"
        "rows = load_rows('missing.txt')\n"
        "for row in rows:\n"
        "    print(clean(row))\n",
        encoding="utf-8",
    )

    class FakeGitingestClient:
        def preprocess_repository_sync(self, repo_url):
            return {"success": False, "content": "", "processed_by": "fake"}

    monkeypatch.setattr(analysis_module, "GitingestClient", FakeGitingestClient)
    monkeypatch.setattr(analysis_module, "fetch_deepwiki", lambda url: {"success": False})

    result = analysis_module.analysis_node({
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {},
    })

    core = result["analysis"]["llm_analysis"]["core_modules"][0]
    assert core["import_side_effect_risk"] is True
    assert any(reason.startswith("top_level_assignment_call") for reason in core["import_side_effect_reasons"])


def test_analysis_node_respects_disable_deepwiki_for_jina_fetch(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text("def add(left: int, right: int) -> int:\n    return left + right\n", encoding="utf-8")

    class FakeGitingestClient:
        def preprocess_repository_sync(self, repo_url):
            return {"success": False, "content": "", "processed_by": "fake"}

    monkeypatch.setenv("DISABLE_DEEPWIKI", "true")
    monkeypatch.setattr(analysis_module, "GitingestClient", FakeGitingestClient)
    monkeypatch.setattr(
        analysis_module,
        "fetch_deepwiki",
        lambda url: (_ for _ in ()).throw(AssertionError("DeepWiki Jina fetch should be disabled")),
    )

    result = analysis_module.analysis_node({
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {"deepwiki_model": "fake-model"},
    })

    assert result["analysis"]["deepwiki_analysis"]["status"] == "skipped"
    assert result["analysis"]["deepwiki_analysis"]["reason"] == "disabled_by_env"


def test_analysis_node_skips_deepwiki_fetch_by_default(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text("def add(left: int, right: int) -> int:\n    return left + right\n", encoding="utf-8")

    monkeypatch.delenv("DISABLE_DEEPWIKI", raising=False)
    monkeypatch.delenv("CODE2MCP_ANALYSIS_USE_DEEPWIKI", raising=False)
    monkeypatch.setattr(
        analysis_module,
        "fetch_deepwiki",
        lambda url: (_ for _ in ()).throw(AssertionError("DeepWiki Jina fetch should be opt-in")),
    )

    result = analysis_module.analysis_node({
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {},
    })

    assert result["analysis"]["deepwiki_analysis"]["status"] == "skipped"
    assert result["analysis"]["deepwiki_analysis"]["reason"] == "disabled_by_default"
    assert result["analysis"]["deepwiki_options"]["enabled"] is False


def test_analysis_node_uses_jina_content_when_deepwiki_llm_is_skipped(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text("def add(left: int, right: int) -> int:\n    return left + right\n", encoding="utf-8")

    class FakeDeepWikiClient:
        def analyze_repository(self, repo_url, repo_name):
            return {
                "repo_url": repo_url,
                "repo_name": repo_name,
                "status": "skipped",
                "reason": "openai API key not set",
                "success": False,
            }

    monkeypatch.setenv("JINA_API_KEY", "jina_test")
    monkeypatch.delenv("DISABLE_DEEPWIKI", raising=False)
    monkeypatch.setattr(analysis_module, "get_deepwiki_client", lambda model: FakeDeepWikiClient())
    monkeypatch.setattr(
        analysis_module,
        "fetch_deepwiki",
        lambda url: {
            "success": True,
            "status": 200,
            "content": (
                "Title: example/demo | DeepWiki\n\n"
                "Loading...\n\n"
                "## Overview\n"
                "Repository example/demo exposes a small Python API with Functions and Dependencies.\n"
            ),
        },
    )

    result = analysis_module.analysis_node({
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {"deepwiki_model": "gpt-5.5"},
    })

    deepwiki = result["analysis"]["deepwiki_analysis"]
    assert deepwiki["status"] == "ok"
    assert deepwiki["success"] is True
    assert deepwiki["source"] == "jina_api"
    assert "reason" not in deepwiki
    assert "Loading..." not in deepwiki["content"]


def test_analysis_node_prefers_local_summary_without_gitingest_by_default(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text("def add(left: int, right: int) -> int:\n    return left + right\n", encoding="utf-8")

    class FailingGitingestClient:
        def preprocess_repository_sync(self, repo_url):
            raise AssertionError("gitingest should be opt-in when local source is available")

    monkeypatch.setattr(analysis_module, "GitingestClient", FailingGitingestClient)
    monkeypatch.setattr(analysis_module, "fetch_deepwiki", lambda url: {"success": False})

    result = analysis_module.analysis_node({
        "repository": {
            "url": "https://github.com/example/demo",
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {},
    })

    summary = result["analysis"]["summary"]
    assert summary["processed_by"] == "local_source_scan"
    assert summary["supplemental_sources"]["gitingest"]["status"] == "skipped"
    assert result["analysis"]["static_analysis"]["function_count"] == 1


def test_analysis_node_uses_local_summary_when_gitingest_fails(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "tools.py").write_text("def add(left: int, right: int) -> int:\n    return left + right\n", encoding="utf-8")

    class FakeGitingestClient:
        def preprocess_repository_sync(self, repo_url):
            return {
                "repository_url": repo_url,
                "summary": "Unable to preprocess repository",
                "file_tree": {},
                "content": {},
                "processed_by": "fallback",
                "success": False,
                "error": "non-github url",
            }

    class FakeLLM:
        def invoke(self, prompt):
            raise AssertionError("Static AST evidence should avoid LLM analysis for simple local repos")
            return json.dumps({
                "core_modules": [
                    {"package": "tools", "module": "tools", "functions": ["add"], "classes": []}
                ],
                "cli_commands": [],
                "import_strategy": {"primary": "import", "fallback": "cli", "confidence": 0.8},
                "dependencies": {"required": [], "optional": []},
                "risk_assessment": {"import_feasibility": 0.8, "intrusiveness_risk": "low", "complexity": "simple"},
            })

    monkeypatch.setattr(analysis_module, "GitingestClient", FakeGitingestClient)
    monkeypatch.setattr(analysis_module, "get_llm_service", lambda: FakeLLM())
    monkeypatch.setattr(analysis_module, "fetch_deepwiki", lambda url: {"success": False})

    result = analysis_module.analysis_node({
        "repository": {
            "url": source.parent.as_uri(),
            "name": "repo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "options": {"analysis_use_gitingest": True},
    })

    analysis = result["analysis"]
    assert analysis["summary"]["processed_by"] == "local_source_scan"
    assert analysis["summary"]["fallback_from"]["processed_by"] == "fallback"
    assert analysis["static_analysis"]["function_count"] == 1
    assert analysis["llm_analysis"]["source_of_truth"] == "ast"
    assert analysis["llm_analysis"]["core_modules"][0]["functions"] == ["add"]
