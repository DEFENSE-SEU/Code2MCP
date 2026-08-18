import ast
import importlib.util
import json
import sys
from pathlib import Path

from src.nodes import generate_node as generate_module


def test_detect_project_type_prefers_python_metadata_over_makefile():
    analysis = {
        "repository_name": "python-with-makefile",
        "dependencies": {"pyproject": True, "setup_py": False, "setup_cfg": False},
        "structure": {"packages": ["demo"]},
        "llm_analysis": {"core_modules": []},
    }

    assert generate_module._detect_project_type(analysis) == "Python"


def test_detect_project_type_reports_swift_from_file_tree():
    analysis = {
        "repository_name": "SnapKit",
        "summary": {"file_tree": {"Package.swift": {"size": 100}, "Sources/Constraint.swift": {"size": 200}}},
        "dependencies": {},
        "structure": {"packages": []},
        "llm_analysis": {"core_modules": []},
    }

    assert generate_module._detect_project_type(analysis) == "Swift"

    details = generate_module._unsupported_generation_details(analysis, analysis, stage="pre_generation_target_selection")
    assert details["project_type"] == "Swift"
    assert details["likely_reason"] == "unsupported_project_type"


def test_generation_targets_respect_empty_wrapper_candidates():
    analysis = {
        "repository_name": "debug-only",
        "dependencies": {"pyproject": True},
        "structure": {"packages": ["pkg"]},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "debug",
                    "functions": ["debug_helper"],
                    "classes": [],
                    "wrapper_candidates": [],
                }
            ]
        },
    }

    assert generate_module._has_verified_generation_targets(analysis) is False


def test_index_like_parameters_infer_as_integers():
    assert generate_module._annotation_to_tool_type("", param_name="cur_index") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="current_index") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="i") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="idx") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="start_idx") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="end_idx") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="nx") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="ny") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="seed") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="virtual_offset") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="wsize") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="Kmax") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="angle") == "float"
    assert generate_module._annotation_to_tool_type("", param_name="radius") == "float"
    assert generate_module._annotation_to_tool_type("", param_name="sfreq") == "float"
    assert generate_module._annotation_to_tool_type("", param_name="half_nbw") == "float"
    assert generate_module._annotation_to_tool_type("", param_name="grant_contributions") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="values") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="numbers") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="counts") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="samples") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="ts_list") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="itemList") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="blacklist") == "str"
    assert generate_module._annotation_to_tool_type("", param_name="isEnabled") == "bool"
    assert generate_module._annotation_to_tool_type("", param_name="history") == "str"
    assert generate_module._annotation_to_tool_type("", param_name="geneMapping") == "dict"
    assert generate_module._annotation_to_tool_type("", param_name="startIndex") == "int"
    assert generate_module._annotation_to_tool_type("", param_name="ii") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="sh") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="strides") == "list"
    assert generate_module._annotation_to_tool_type("", param_name="contrib_dict") == "dict"
    assert generate_module._annotation_to_tool_type("", param_name="order", context_name="check_seasonal_order") == "list"


def test_radius_parameter_uses_float_signature():
    detail = {
        "parameters": ["radius"],
        "parameter_details": [{"name": "radius", "annotation": "", "required": True, "default": ""}],
        "docstring": "Compute circumference from a radius.",
    }

    signature, call_args, names = generate_module._tool_signature_and_call(
        ["radius"],
        detail["parameter_details"],
        "circumference",
        detail,
        [],
    )

    assert signature == "radius: float = 0.0"
    assert call_args == "radius"
    assert names == ["radius"]


def test_seasonal_order_parameter_uses_list_signature():
    detail = {
        "parameters": ["order"],
        "parameter_details": [{"name": "order", "annotation": "", "required": True, "default": ""}],
        "docstring": "Parameters\n----------\norder : tuple\n    The existing seasonal order",
    }

    signature, call_args, names = generate_module._tool_signature_and_call(
        ["order"],
        detail["parameter_details"],
        "check_seasonal_order",
        detail,
        [],
    )

    assert signature == "order: list = None"
    assert call_args == "order"
    assert names == ["order"]


def test_fname_variants_are_path_like_parameters():
    assert generate_module._is_path_like_param("fname") is True
    assert generate_module._is_path_like_param("fname_in") is True
    assert generate_module._is_path_like_param("fname_out") is True
    assert generate_module._is_path_like_param("mgz_fname") is True
    assert generate_module._is_path_like_param("dir_old") is True
    assert generate_module._is_path_like_param("dir_new") is True
    assert generate_module._is_path_like_param("src_dir") is True
    assert generate_module._is_path_like_param("subjects_dir") is True
    assert generate_module._is_path_like_param("output_directory") is True
    assert generate_module._is_path_like_param("module_path") is False
    assert generate_module._is_path_like_param("modulePath") is False
    assert generate_module._is_path_like_param("import_path") is False


def test_path_guard_lines_skip_dotted_import_parameters():
    guard_lines = generate_module._path_guard_lines(["file_path", "module_path", "importPath"])

    assert "_safe_resolve_path(source_path, file_path)" in guard_lines
    assert "module_path" not in guard_lines
    assert "importPath" not in guard_lines


def test_generator_functions_are_not_wrapped():
    tree = ast.parse(
        "def stream_items(items):\n"
        "    for item in items:\n"
        "        yield item\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert generate_module._function_body_returns_generator(functions["stream_items"]) is True
    assert generate_module._function_body_returns_generator(functions["echo"]) is False


def test_empty_default_factory_functions_are_not_wrapped():
    tree = ast.parse(
        "def index_list():\n"
        "    return defaultdict(list)\n"
        "\n"
        "def Enumerator(start=0):\n"
        "    return collections.defaultdict(itertools.count(start).__next__, ())\n"
        "\n"
        "def populated_defaultdict():\n"
        "    return defaultdict(list, {'name': ['ada']})\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert generate_module._function_body_returns_empty_default_factory(functions["index_list"]) is True
    assert generate_module._function_body_returns_empty_default_factory(functions["Enumerator"]) is True
    assert generate_module._function_body_returns_empty_default_factory(functions["populated_defaultdict"]) is False
    assert generate_module._function_body_returns_empty_default_factory(functions["echo"]) is False


def test_empty_literal_container_functions_are_not_wrapped():
    tree = ast.parse(
        "def empty_list():\n"
        "    return []\n"
        "\n"
        "def empty_dict_call():\n"
        "    return dict()\n"
        "\n"
        "def empty_counter():\n"
        "    return collections.Counter()\n"
        "\n"
        "def populated_mapping():\n"
        "    return {'name': 'ada'}\n"
        "\n"
        "def maybe_empty(flag):\n"
        "    if flag:\n"
        "        return []\n"
        "    return ['value']\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert generate_module._function_body_returns_empty_literal_container(functions["empty_list"]) is True
    assert generate_module._function_body_returns_empty_literal_container(functions["empty_dict_call"]) is True
    assert generate_module._function_body_returns_empty_literal_container(functions["empty_counter"]) is True
    assert generate_module._function_body_returns_empty_literal_container(functions["populated_mapping"]) is False
    assert generate_module._function_body_returns_empty_literal_container(functions["maybe_empty"]) is False
    assert generate_module._function_body_returns_empty_literal_container(functions["echo"]) is False


def test_interactive_input_functions_are_not_wrapped():
    tree = ast.parse(
        "def ask_value():\n"
        "    return input('value: ')\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    reasons = generate_module._function_body_unsafe_runtime_side_effect_reasons(functions["ask_value"])
    assert "requires interactive stdin input" in reasons
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["ask_value"]) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"]) is False


def test_network_and_file_mutation_functions_are_not_wrapped():
    tree = ast.parse(
        "import os\n"
        "import pathlib\n"
        "import requests as rq\n"
        "import urllib.request\n"
        "import webbrowser as browser\n"
        "from subprocess import getstatusoutput, run\n"
        "\n"
        "def fetch_json(endpoint):\n"
        "    return rq.get(endpoint).json()\n"
        "\n"
        "def fetch_url(endpoint):\n"
        "    return urllib.request.urlopen(endpoint).read()\n"
        "\n"
        "def download_file(endpoint, filename):\n"
        "    return urllib.request.urlretrieve(endpoint, filename)[0]\n"
        "\n"
        "def open_browser(endpoint):\n"
        "    return browser.open(endpoint)\n"
        "\n"
        "def run_command(command):\n"
        "    return run(command, capture_output=True).stdout\n"
        "\n"
        "def replace_process(command):\n"
        "    os.execvp(command, [command])\n"
        "\n"
        "def shell_status(command):\n"
        "    return getstatusoutput(command)\n"
        "\n"
        "def write_report(text):\n"
        "    pathlib.Path('report.txt').write_text(text)\n"
        "    return text\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["fetch_json"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["fetch_url"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["download_file"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["open_browser"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["run_command"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["replace_process"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["shell_status"],
        generate_module._runtime_call_aliases(tree),
    )
    assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["write_report"]
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["fetch_json"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["fetch_url"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["download_file"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["open_browser"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["run_command"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["replace_process"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["shell_status"],
        generate_module._runtime_call_aliases(tree),
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["write_report"]) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"]) is False


def test_network_client_constructor_functions_are_not_wrapped():
    tree = ast.parse(
        "import httpx\n"
        "import requests as rq\n"
        "import aiohttp\n"
        "from aiohttp import ClientSession\n"
        "from requests import Session\n"
        "\n"
        "def make_aiohttp_session():\n"
        "    session = aiohttp.ClientSession()\n"
        "    return str(session.closed)\n"
        "\n"
        "def make_aiohttp_alias_session():\n"
        "    session = ClientSession()\n"
        "    return str(session.closed)\n"
        "\n"
        "def fetch_with_requests_session(url):\n"
        "    return rq.Session().get(url).json()\n"
        "\n"
        "def fetch_with_requests_session_alias(url):\n"
        "    client = Session()\n"
        "    return client.get(url).json()\n"
        "\n"
        "def fetch_with_httpx_client(url):\n"
        "    with httpx.Client() as client:\n"
        "        return client.get(url).json()\n"
        "\n"
        "def fetch_with_httpx_chain(url):\n"
        "    return httpx.Client().post(url, json={}).json()\n"
        "\n"
        "def echo_value(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "make_aiohttp_session",
        "make_aiohttp_alias_session",
        "fetch_with_requests_session",
        "fetch_with_requests_session_alias",
        "fetch_with_httpx_client",
        "fetch_with_httpx_chain",
    ):
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_value"], aliases) is False


def test_direct_network_request_methods_are_not_wrapped():
    tree = ast.parse(
        "import httpx\n"
        "import aiohttp\n"
        "import requests\n"
        "import requests as rq\n"
        "from aiohttp import request as aiohttp_request\n"
        "from httpx import request as httpx_request\n"
        "from requests import head as requests_head\n"
        "\n"
        "def aiohttp_direct_request_status(url):\n"
        "    request = aiohttp.request('GET', url)\n"
        "    return str(request)\n"
        "\n"
        "def aiohttp_alias_request_status(url):\n"
        "    request = aiohttp_request('POST', url, json={})\n"
        "    return str(request)\n"
        "\n"
        "def requests_head_status(url):\n"
        "    return requests.head(url).status_code\n"
        "\n"
        "def requests_options_status(url):\n"
        "    return rq.options(url).status_code\n"
        "\n"
        "def requests_generic_request_status(url):\n"
        "    return requests.request('GET', url).status_code\n"
        "\n"
        "def requests_alias_head_status(url):\n"
        "    return requests_head(url).status_code\n"
        "\n"
        "def httpx_head_status(url):\n"
        "    return httpx.head(url).status_code\n"
        "\n"
        "def httpx_options_status(url):\n"
        "    return httpx.options(url).status_code\n"
        "\n"
        "def httpx_generic_request_status(url):\n"
        "    return httpx_request('GET', url).status_code\n"
        "\n"
        "def httpx_stream_status(url):\n"
        "    with httpx.stream('GET', url) as response:\n"
        "        return response.status_code\n"
        "\n"
        "def echo_value(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

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
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_value"], aliases) is False


def test_url_opener_network_client_functions_are_not_wrapped():
    tree = ast.parse(
        "import urllib.request\n"
        "import urllib3\n"
        "from urllib.request import build_opener\n"
        "from urllib3 import request as urllib3_request_alias\n"
        "\n"
        "def fetch_with_urllib_opener(url):\n"
        "    opener = urllib.request.build_opener()\n"
        "    return opener.open(url).read()\n"
        "\n"
        "def fetch_with_urllib_opener_alias(url):\n"
        "    opener = build_opener()\n"
        "    return opener.open(url).read()\n"
        "\n"
        "def fetch_with_urllib3_pool(url):\n"
        "    manager = urllib3.PoolManager()\n"
        "    return manager.request('GET', url).data\n"
        "\n"
        "def fetch_with_urllib3_proxy(url):\n"
        "    manager = urllib3.ProxyManager('http://proxy.example')\n"
        "    return manager.request('GET', url).data\n"
        "\n"
        "def fetch_with_urllib3_top_level(url):\n"
        "    return urllib3.request('GET', url).data\n"
        "\n"
        "def fetch_with_urllib3_top_level_alias(url):\n"
        "    return urllib3_request_alias('POST', url).data\n"
        "\n"
        "def echo_value(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "fetch_with_urllib_opener",
        "fetch_with_urllib_opener_alias",
        "fetch_with_urllib3_pool",
        "fetch_with_urllib3_proxy",
        "fetch_with_urllib3_top_level",
        "fetch_with_urllib3_top_level_alias",
    ):
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_value"], aliases) is False


def test_tempfile_mutation_functions_are_not_wrapped():
    tree = ast.parse(
        "import tempfile\n"
        "from tempfile import NamedTemporaryFile, TemporaryDirectory, mkdtemp, mkstemp\n"
        "\n"
        "def named_temp_status():\n"
        "    handle = tempfile.NamedTemporaryFile(delete=False)\n"
        "    handle.close()\n"
        "    return handle.name\n"
        "\n"
        "def alias_temp_status():\n"
        "    handle = NamedTemporaryFile(delete=False)\n"
        "    handle.close()\n"
        "    return handle.name\n"
        "\n"
        "def temp_dir_status():\n"
        "    with TemporaryDirectory() as directory:\n"
        "        return directory\n"
        "\n"
        "def mkstemp_status():\n"
        "    _fd, path = mkstemp()\n"
        "    return path\n"
        "\n"
        "def mkdtemp_status():\n"
        "    return mkdtemp()\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("named_temp_status", "alias_temp_status", "temp_dir_status", "mkstemp_status", "mkdtemp_status"):
        assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_socket_network_functions_are_not_wrapped():
    tree = ast.parse(
        "import socket\n"
        "from socket import create_connection as dial\n"
        "\n"
        "def endpoint_status():\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    sock.bind(('127.0.0.1', 0))\n"
        "    sock.listen(1)\n"
        "    sock.close()\n"
        "    return 'ready'\n"
        "\n"
        "def remote_status():\n"
        "    conn = socket.create_connection(('example.com', 80), timeout=1)\n"
        "    conn.close()\n"
        "    return 'connected'\n"
        "\n"
        "def alias_remote_status():\n"
        "    conn = dial(('example.com', 80), timeout=1)\n"
        "    conn.close()\n"
        "    return 'connected'\n"
        "\n"
        "def direct_socket_status():\n"
        "    socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('example.com', 80))\n"
        "    return 'connected'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("endpoint_status", "remote_status", "alias_remote_status", "direct_socket_status"):
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_server_network_functions_are_not_wrapped():
    tree = ast.parse(
        "import http.server\n"
        "import socketserver\n"
        "from http.server import HTTPServer\n"
        "from wsgiref.simple_server import make_server\n"
        "\n"
        "class Handler(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        pass\n"
        "\n"
        "class TCPHandler(socketserver.BaseRequestHandler):\n"
        "    def handle(self):\n"
        "        pass\n"
        "\n"
        "def wsgi_app(environ, start_response):\n"
        "    return []\n"
        "\n"
        "def local_status():\n"
        "    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)\n"
        "    server.server_close()\n"
        "    return 'ready'\n"
        "\n"
        "def alias_status():\n"
        "    server = HTTPServer(('127.0.0.1', 0), Handler)\n"
        "    server.handle_request()\n"
        "    return 'handled'\n"
        "\n"
        "def tcp_status():\n"
        "    server = socketserver.TCPServer(('127.0.0.1', 0), TCPHandler)\n"
        "    server.server_close()\n"
        "    return 'ready'\n"
        "\n"
        "def wsgi_status():\n"
        "    server = make_server('127.0.0.1', 0, wsgi_app)\n"
        "    server.server_close()\n"
        "    return 'ready'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("local_status", "alias_status", "tcp_status", "wsgi_status"):
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_protocol_network_clients_are_not_wrapped():
    tree = ast.parse(
        "import ftplib\n"
        "import http.client\n"
        "import smtplib\n"
        "import xmlrpc.client\n"
        "from smtplib import SMTP as Mailer\n"
        "\n"
        "def http_status():\n"
        "    conn = http.client.HTTPConnection('example.com')\n"
        "    conn.request('GET', '/')\n"
        "    return 'requested'\n"
        "\n"
        "def smtp_status():\n"
        "    smtp = smtplib.SMTP('mail.example.com')\n"
        "    smtp.sendmail('from@example.com', ['to@example.com'], 'hello')\n"
        "    return 'sent'\n"
        "\n"
        "def ftp_status():\n"
        "    ftp = ftplib.FTP('ftp.example.com')\n"
        "    ftp.login()\n"
        "    return 'logged-in'\n"
        "\n"
        "def alias_mail_status():\n"
        "    smtp = Mailer('mail.example.com')\n"
        "    smtp.send('hello')\n"
        "    return 'sent'\n"
        "\n"
        "def rpc_status():\n"
        "    xmlrpc.client.ServerProxy('https://example.com/rpc')\n"
        "    return 'ready'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("http_status", "smtp_status", "ftp_status", "alias_mail_status", "rpc_status"):
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_datastore_network_clients_are_not_wrapped():
    tree = ast.parse(
        "import mysql.connector\n"
        "import psycopg\n"
        "import psycopg2\n"
        "import pymongo\n"
        "import redis\n"
        "from redis import Redis\n"
        "from sqlalchemy import create_engine\n"
        "\n"
        "def redis_status():\n"
        "    client = redis.Redis(host='localhost', port=6379)\n"
        "    client.get('key')\n"
        "    return 'ready'\n"
        "\n"
        "def redis_alias_status():\n"
        "    client = Redis(host='localhost', port=6379)\n"
        "    client.set('key', 'value')\n"
        "    return 'ready'\n"
        "\n"
        "def mongo_status():\n"
        "    client = pymongo.MongoClient('mongodb://localhost:27017')\n"
        "    client.admin.command('ping')\n"
        "    return 'ready'\n"
        "\n"
        "def postgres_status():\n"
        "    conn = psycopg2.connect(host='localhost', dbname='demo')\n"
        "    conn.cursor()\n"
        "    return 'ready'\n"
        "\n"
        "def psycopg_status():\n"
        "    conn = psycopg.connect('postgresql://localhost/demo')\n"
        "    conn.execute('select 1')\n"
        "    return 'ready'\n"
        "\n"
        "def mysql_status():\n"
        "    conn = mysql.connector.connect(host='localhost', user='demo')\n"
        "    conn.cursor()\n"
        "    return 'ready'\n"
        "\n"
        "def sqlalchemy_status():\n"
        "    engine = create_engine('postgresql://localhost/demo')\n"
        "    engine.connect()\n"
        "    return 'ready'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "redis_status",
        "redis_alias_status",
        "mongo_status",
        "postgres_status",
        "psycopg_status",
        "mysql_status",
        "sqlalchemy_status",
    ):
        assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_runtime_global_mutation_functions_are_not_wrapped():
    tree = ast.parse(
        "import logging\n"
        "import sys as runtime_sys\n"
        "from warnings import filterwarnings\n"
        "\n"
        "def add_import_path():\n"
        "    runtime_sys.path.insert(0, 'plugins')\n"
        "    return 'plugins'\n"
        "\n"
        "def forget_cached_module(name):\n"
        "    runtime_sys.modules.pop(name, None)\n"
        "    return name\n"
        "\n"
        "def configure_warnings():\n"
        "    filterwarnings('ignore')\n"
        "    return 'ignore'\n"
        "\n"
        "def configure_logging():\n"
        "    logging.basicConfig(level=logging.INFO)\n"
        "    return 'logging'\n"
        "\n"
        "def replace_path(paths):\n"
        "    runtime_sys.path = list(paths)\n"
        "    return len(runtime_sys.path)\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "add_import_path",
        "forget_cached_module",
        "configure_warnings",
        "configure_logging",
        "replace_path",
    ):
        assert "mutates process state" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_runtime_state_alias_mutation_functions_are_not_wrapped():
    tree = ast.parse(
        "import os\n"
        "import sys\n"
        "\n"
        "def alias_env_status(value):\n"
        "    env = os.environ\n"
        "    env['APP_MODE'] = value\n"
        "    return value\n"
        "\n"
        "def alias_env_update_status(value):\n"
        "    env = os.environ\n"
        "    env.update({'APP_MODE': value})\n"
        "    return value\n"
        "\n"
        "def alias_path_status(path):\n"
        "    paths = sys.path\n"
        "    paths.append(path)\n"
        "    return path\n"
        "\n"
        "def alias_modules_status(name):\n"
        "    modules = sys.modules\n"
        "    modules.pop(name, None)\n"
        "    return name\n"
        "\n"
        "def read_env_value(key):\n"
        "    env = os.environ\n"
        "    return env.get(key, '')\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("alias_env_status", "alias_env_update_status"):
        assert "mutates process environment" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    for name in ("alias_path_status", "alias_modules_status"):
        assert "mutates process state" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["read_env_value"], aliases) is False
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_getattr_runtime_state_mutation_functions_are_not_wrapped():
    tree = ast.parse(
        "import os\n"
        "import sys\n"
        "from functools import partial\n"
        "\n"
        "def direct_env_status(value):\n"
        "    getattr(os, 'environ').update({'APP_MODE': value})\n"
        "    return value\n"
        "\n"
        "def direct_env_item_status(value):\n"
        "    getattr(os, 'environ')['APP_MODE'] = value\n"
        "    return value\n"
        "\n"
        "def alias_env_status(value):\n"
        "    env = getattr(os, 'environ')\n"
        "    env['APP_MODE'] = value\n"
        "    return value\n"
        "\n"
        "def alias_env_update_status(value):\n"
        "    env = getattr(os, 'environ')\n"
        "    env.update({'APP_MODE': value})\n"
        "    return value\n"
        "\n"
        "def method_alias_env_status(value):\n"
        "    update_env = getattr(os, 'environ').update\n"
        "    update_env({'APP_MODE': value})\n"
        "    return value\n"
        "\n"
        "def partial_env_status(value):\n"
        "    update_env = partial(getattr(os, 'environ').update, {'APP_MODE': value})\n"
        "    update_env()\n"
        "    return value\n"
        "\n"
        "def direct_path_status(path):\n"
        "    getattr(sys, 'path').append(path)\n"
        "    return path\n"
        "\n"
        "def direct_modules_status(name):\n"
        "    getattr(sys, 'modules').pop(name, None)\n"
        "    return name\n"
        "\n"
        "def alias_path_status(path):\n"
        "    paths = getattr(sys, 'path')\n"
        "    paths.append(path)\n"
        "    return path\n"
        "\n"
        "def alias_modules_status(name):\n"
        "    modules = getattr(sys, 'modules')\n"
        "    modules.pop(name, None)\n"
        "    return name\n"
        "\n"
        "def read_env_value(key):\n"
        "    env = getattr(os, 'environ')\n"
        "    return env.get(key, '')\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "direct_env_status",
        "direct_env_item_status",
        "alias_env_status",
        "alias_env_update_status",
        "method_alias_env_status",
        "partial_env_status",
    ):
        assert "mutates process environment" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    for name in ("direct_path_status", "direct_modules_status", "alias_path_status", "alias_modules_status"):
        assert "mutates process state" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["read_env_value"], aliases) is False
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_path_object_alias_file_read_functions_are_not_wrapped():
    tree = ast.parse(
        "from pathlib import Path\n"
        "import pathlib\n"
        "\n"
        "def direct_iterdir_names():\n"
        "    return [item.name for item in Path('data').iterdir()]\n"
        "\n"
        "def alias_iterdir_names():\n"
        "    directory = Path('data')\n"
        "    return [item.name for item in directory.iterdir()]\n"
        "\n"
        "def alias_glob_names():\n"
        "    directory = Path('data')\n"
        "    return [item.name for item in directory.glob('*.csv')]\n"
        "\n"
        "def alias_rglob_names():\n"
        "    directory = pathlib.Path('data')\n"
        "    return [item.name for item in directory.rglob('*.csv')]\n"
        "\n"
        "def cwd_iterdir_names():\n"
        "    return [item.name for item in Path.cwd().iterdir()]\n"
        "\n"
        "def alias_cwd_iterdir_names():\n"
        "    directory = Path.cwd()\n"
        "    return [item.name for item in directory.iterdir()]\n"
        "\n"
        "def home_glob_names():\n"
        "    return [item.name for item in pathlib.Path.home().glob('*.csv')]\n"
        "\n"
        "def alias_home_read_text():\n"
        "    directory = Path.home()\n"
        "    return (directory / 'settings.ini').read_text()\n"
        "\n"
        "def chained_alias_read_text():\n"
        "    directory = Path.home()\n"
        "    config = directory / 'settings.ini'\n"
        "    return config.read_text()\n"
        "\n"
        "def chained_alias_iterdir_names():\n"
        "    directory = Path.cwd()\n"
        "    data_dir = directory / 'data'\n"
        "    return [item.name for item in data_dir.iterdir()]\n"
        "\n"
        "def resolve_alias_iterdir_names():\n"
        "    directory = Path('data').resolve()\n"
        "    return [item.name for item in directory.iterdir()]\n"
        "\n"
        "def expanduser_alias_glob_names():\n"
        "    directory = pathlib.Path('~').expanduser()\n"
        "    return [item.name for item in directory.glob('*.csv')]\n"
        "\n"
        "def parent_iterdir_names():\n"
        "    return [item.name for item in Path('data/file.txt').parent.iterdir()]\n"
        "\n"
        "def alias_parent_glob_names():\n"
        "    directory = Path('data/file.txt').parent\n"
        "    return [item.name for item in directory.glob('*.csv')]\n"
        "\n"
        "def parents_index_iterdir_names():\n"
        "    return [item.name for item in Path('data/file.txt').parents[0].iterdir()]\n"
        "\n"
        "def alias_read_text():\n"
        "    config = Path('settings.ini')\n"
        "    return config.read_text()\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

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
        assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_path_open_write_mode_functions_are_not_wrapped():
    tree = ast.parse(
        "from pathlib import Path\n"
        "import pathlib\n"
        "\n"
        "def path_open_write_mode():\n"
        "    handle = Path('report.txt').open('w')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def alias_path_open_append_mode():\n"
        "    report = Path('report.txt')\n"
        "    handle = report.open('a')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def pathlib_open_exclusive_mode():\n"
        "    handle = pathlib.Path('report.txt').open('x')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def path_open_read_mode():\n"
        "    with Path('report.txt').open() as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("path_open_write_mode", "alias_path_open_append_mode", "pathlib_open_exclusive_mode"):
        reasons = generate_module._function_body_unsafe_runtime_side_effect_reasons(functions[name], aliases)
        assert "opens files in write/append mode" in reasons
        assert "reads files or directories" not in reasons
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["path_open_read_mode"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["path_open_read_mode"], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_file_metadata_read_functions_are_not_wrapped():
    tree = ast.parse(
        "from pathlib import Path\n"
        "import os\n"
        "from os.path import exists as path_exists_alias, getsize as path_size, isfile as path_is_file\n"
        "\n"
        "def path_exists():\n"
        "    return Path('settings.ini').exists()\n"
        "\n"
        "def alias_is_file():\n"
        "    path = Path('settings.ini')\n"
        "    return path.is_file()\n"
        "\n"
        "def path_stat_size():\n"
        "    return Path('settings.ini').stat().st_size\n"
        "\n"
        "def os_path_getsize():\n"
        "    return os.path.getsize('settings.ini')\n"
        "\n"
        "def os_stat_size():\n"
        "    return os.stat('settings.ini').st_size\n"
        "\n"
        "def os_path_alias_getsize():\n"
        "    return path_size('settings.ini')\n"
        "\n"
        "def os_path_alias_exists():\n"
        "    return path_exists_alias('settings.ini')\n"
        "\n"
        "def os_path_alias_isfile():\n"
        "    return path_is_file('settings.ini')\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

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
        assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_open_alias_file_functions_are_not_wrapped():
    tree = ast.parse(
        "from builtins import open as read_file\n"
        "from io import open as io_read_file\n"
        "\n"
        "def alias_builtin_open_read():\n"
        "    with read_file('settings.ini') as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def alias_builtin_open_write(text):\n"
        "    with read_file('settings.ini', 'w') as handle:\n"
        "        return handle.write(text)\n"
        "\n"
        "def alias_io_open_read():\n"
        "    with io_read_file('settings.ini') as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("alias_builtin_open_read", "alias_io_open_read"):
        assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert "opens files in write/append mode" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["alias_builtin_open_write"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(
        functions["alias_builtin_open_write"],
        aliases,
    ) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_os_descriptor_file_functions_are_not_wrapped():
    tree = ast.parse(
        "import os\n"
        "from os import O_CREAT, O_RDONLY, O_WRONLY, fdopen as wrap_fd, open as low_open\n"
        "\n"
        "def fdopen_write_mode(fd):\n"
        "    handle = os.fdopen(fd, 'w')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def fdopen_alias_append_mode(fd):\n"
        "    handle = wrap_fd(fd, mode='a')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def os_open_write_flags():\n"
        "    fd = os.open('report.txt', os.O_WRONLY | os.O_CREAT)\n"
        "    os.close(fd)\n"
        "    return fd\n"
        "\n"
        "def os_open_alias_write_flags():\n"
        "    fd = low_open('report.txt', O_WRONLY | O_CREAT)\n"
        "    os.close(fd)\n"
        "    return fd\n"
        "\n"
        "def os_open_read_flags():\n"
        "    fd = os.open('report.txt', O_RDONLY)\n"
        "    os.close(fd)\n"
        "    return fd\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("fdopen_write_mode", "fdopen_alias_append_mode"):
        assert "opens files in write/append mode" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    for name in ("os_open_write_flags", "os_open_alias_write_flags"):
        assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    reasons = generate_module._function_body_unsafe_runtime_side_effect_reasons(functions["os_open_read_flags"], aliases)
    assert "reads files or directories" in reasons
    assert "mutates files or directories" not in reasons
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["os_open_read_flags"], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_mode_sensitive_file_open_writes_are_not_wrapped():
    tree = ast.parse(
        "import gzip\n"
        "import h5py\n"
        "import io\n"
        "import tarfile\n"
        "import zipfile\n"
        "from gzip import open as gzip_open_alias\n"
        "from zipfile import ZipFile as Archive\n"
        "\n"
        "def gzip_open_write_mode():\n"
        "    handle = gzip.open('report.gz', 'wb')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def gzip_alias_append_mode():\n"
        "    handle = gzip_open_alias('report.gz', mode='ab')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def tarfile_open_write_mode():\n"
        "    archive = tarfile.open('report.tar', 'w')\n"
        "    archive.close()\n"
        "    return True\n"
        "\n"
        "def zipfile_open_write_mode():\n"
        "    archive = zipfile.ZipFile('report.zip', 'w')\n"
        "    archive.close()\n"
        "    return True\n"
        "\n"
        "def zipfile_alias_append_mode():\n"
        "    archive = Archive('report.zip', mode='a')\n"
        "    archive.close()\n"
        "    return True\n"
        "\n"
        "def h5py_file_write_mode():\n"
        "    handle = h5py.File('report.h5', 'w')\n"
        "    handle.close()\n"
        "    return True\n"
        "\n"
        "def io_fileio_write_mode():\n"
        "    handle = io.FileIO('report.bin', 'w')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def io_fileio_read_mode():\n"
        "    handle = io.FileIO('report.bin')\n"
        "    handle.close()\n"
        "    return handle.closed\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "gzip_open_write_mode",
        "gzip_alias_append_mode",
        "tarfile_open_write_mode",
        "zipfile_open_write_mode",
        "zipfile_alias_append_mode",
        "h5py_file_write_mode",
        "io_fileio_write_mode",
    ):
        reasons = generate_module._function_body_unsafe_runtime_side_effect_reasons(functions[name], aliases)
        assert "opens files in write/append mode" in reasons
        assert "reads files or directories" not in reasons
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["io_fileio_read_mode"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["io_fileio_read_mode"], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_compressed_archive_file_read_functions_are_not_wrapped():
    tree = ast.parse(
        "import bz2\n"
        "import gzip\n"
        "import lzma\n"
        "import tarfile\n"
        "from gzip import open as gzip_open_alias\n"
        "\n"
        "def gzip_open_read():\n"
        "    with gzip.open('records.csv.gz', 'rb') as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def gzip_alias_open_read():\n"
        "    with gzip_open_alias('records.csv.gz', 'rb') as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def bz2_open_read():\n"
        "    with bz2.open('records.csv.bz2', 'rb') as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def lzma_open_read():\n"
        "    with lzma.open('records.csv.xz', 'rb') as handle:\n"
        "        return handle.read()\n"
        "\n"
        "def tar_open_names():\n"
        "    with tarfile.open('records.tar') as archive:\n"
        "        return archive.getnames()\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("gzip_open_read", "gzip_alias_open_read", "bz2_open_read", "lzma_open_read", "tar_open_names"):
        assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_implicit_file_read_functions_are_not_wrapped():
    tree = ast.parse(
        "import fileinput\n"
        "import linecache\n"
        "import tokenize\n"
        "from fileinput import FileInput, input as fileinput_input_alias\n"
        "from linecache import getline as linecache_getline_alias\n"
        "from tokenize import open as tokenize_open_alias\n"
        "\n"
        "def fileinput_input_read():\n"
        "    return list(fileinput.input('settings.ini'))\n"
        "\n"
        "def fileinput_alias_read():\n"
        "    return list(fileinput_input_alias('settings.ini'))\n"
        "\n"
        "def fileinput_class_read():\n"
        "    with fileinput.FileInput('settings.ini') as lines:\n"
        "        return list(lines)\n"
        "\n"
        "def fileinput_class_input_read():\n"
        "    return list(FileInput.input(files='settings.ini'))\n"
        "\n"
        "def linecache_getline_read():\n"
        "    return linecache.getline('settings.ini', 1)\n"
        "\n"
        "def linecache_getlines_read():\n"
        "    return linecache.getlines('settings.ini')\n"
        "\n"
        "def linecache_alias_getline_read():\n"
        "    return linecache_getline_alias('settings.ini', 1)\n"
        "\n"
        "def tokenize_open_read():\n"
        "    with tokenize.open('script.py') as handle:\n"
        "        return handle.readline()\n"
        "\n"
        "def tokenize_alias_open_read():\n"
        "    with tokenize_open_alias('script.py') as handle:\n"
        "        return handle.readline()\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

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
        assert "reads files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_file_backed_store_functions_are_not_wrapped():
    tree = ast.parse(
        "import dbm\n"
        "import dbm.dumb\n"
        "import shelve\n"
        "from shelve import open as shelve_open_alias\n"
        "\n"
        "def shelve_store_keys():\n"
        "    with shelve.open('cache.db') as store:\n"
        "        return list(store.keys())\n"
        "\n"
        "def shelve_alias_store_keys():\n"
        "    with shelve_open_alias('cache.db') as store:\n"
        "        return list(store.keys())\n"
        "\n"
        "def dbm_store_keys():\n"
        "    with dbm.open('cache.db', 'c') as store:\n"
        "        return list(store.keys())\n"
        "\n"
        "def dbm_dumb_store_keys():\n"
        "    with dbm.dumb.open('cache.db', 'c') as store:\n"
        "        return list(store.keys())\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "shelve_store_keys",
        "shelve_alias_store_keys",
        "dbm_store_keys",
        "dbm_dumb_store_keys",
    ):
        assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_reflected_runtime_state_mutation_functions_are_not_wrapped():
    tree = ast.parse(
        "import os\n"
        "import sys\n"
        "\n"
        "def reflect_env_status(value):\n"
        "    setattr(os, 'environ', {'APP_MODE': value})\n"
        "    return value\n"
        "\n"
        "def reflect_env_delete_status():\n"
        "    delattr(os, 'environ')\n"
        "    return 'deleted'\n"
        "\n"
        "def reflect_path_status(path):\n"
        "    setattr(sys, 'path', [path])\n"
        "    return path\n"
        "\n"
        "def reflect_modules_delete_status():\n"
        "    delattr(sys, 'modules')\n"
        "    return 'deleted'\n"
        "\n"
        "def tag_text(value):\n"
        "    class Box:\n"
        "        pass\n"
        "    box = Box()\n"
        "    setattr(box, 'tag', value)\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("reflect_env_status", "reflect_env_delete_status"):
        assert "mutates process environment" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    for name in ("reflect_path_status", "reflect_modules_delete_status"):
        assert "mutates process state" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["tag_text"], aliases) is False


def test_getattr_runtime_side_effect_functions_are_not_wrapped():
    tree = ast.parse(
        "import os\n"
        "import subprocess\n"
        "import tempfile\n"
        "import urllib.request as url_request\n"
        "\n"
        "def status_code():\n"
        "    getattr(os, 'system')('echo ok')\n"
        "    return 'ok'\n"
        "\n"
        "def job_status():\n"
        "    runner = getattr(subprocess, 'run')\n"
        "    runner(['echo', 'ok'], capture_output=True)\n"
        "    return 'ok'\n"
        "\n"
        "def transfer_status():\n"
        "    getattr(url_request, 'urlretrieve')('https://example.com/a', 'a')\n"
        "    return 'ok'\n"
        "\n"
        "def scratch_status():\n"
        "    getattr(tempfile, 'mkdtemp')()\n"
        "    return 'ok'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("status_code", "job_status"):
        assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["transfer_status"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["transfer_status"], aliases) is True
    assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["scratch_status"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["scratch_status"], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_partial_runtime_side_effect_functions_are_not_wrapped():
    tree = ast.parse(
        "import functools\n"
        "import os\n"
        "import subprocess\n"
        "import tempfile\n"
        "import urllib.request as url_request\n"
        "from functools import partial\n"
        "\n"
        "def status_code():\n"
        "    functools.partial(os.system, 'echo ok')()\n"
        "    return 'ok'\n"
        "\n"
        "def job_status():\n"
        "    runner = partial(subprocess.run, ['echo', 'ok'], capture_output=True)\n"
        "    runner()\n"
        "    return 'ok'\n"
        "\n"
        "def transfer_status():\n"
        "    downloader = functools.partial(url_request.urlretrieve, 'https://example.com/a', 'a')\n"
        "    downloader()\n"
        "    return 'ok'\n"
        "\n"
        "def scratch_status():\n"
        "    maker = partial(tempfile.mkdtemp)\n"
        "    maker()\n"
        "    return 'ok'\n"
        "\n"
        "def getattr_partial_status():\n"
        "    runner = functools.partial(getattr(os, 'system'), 'echo ok')\n"
        "    runner()\n"
        "    return 'ok'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("status_code", "job_status", "getattr_partial_status"):
        assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["transfer_status"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["transfer_status"], aliases) is True
    assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["scratch_status"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["scratch_status"], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_dynamic_code_execution_functions_are_not_wrapped():
    tree = ast.parse(
        "import builtins\n"
        "from builtins import compile as compile_source, eval as eval_expression, exec as exec_statement\n"
        "\n"
        "def formula_value(expression):\n"
        "    return eval(expression)\n"
        "\n"
        "def builtin_formula_value(expression):\n"
        "    return builtins.eval(expression)\n"
        "\n"
        "def alias_formula_value(expression):\n"
        "    return eval_expression(expression)\n"
        "\n"
        "def statement_status(source):\n"
        "    exec(source)\n"
        "    return 'ok'\n"
        "\n"
        "def alias_statement_status(source):\n"
        "    exec_statement(source)\n"
        "    return 'ok'\n"
        "\n"
        "def compiled_status(source):\n"
        "    return compile(source, '<user>', 'exec')\n"
        "\n"
        "def alias_compiled_status(source):\n"
        "    return compile_source(source, '<user>', 'exec')\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "formula_value",
        "builtin_formula_value",
        "alias_formula_value",
        "statement_status",
        "alias_statement_status",
        "compiled_status",
        "alias_compiled_status",
    ):
        assert "can execute dynamic code" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_dynamic_import_runtime_side_effect_functions_are_not_wrapped():
    tree = ast.parse(
        "import importlib\n"
        "from importlib import import_module\n"
        "\n"
        "def alpha_status():\n"
        "    __import__('os').system('echo ok')\n"
        "    return 'ok'\n"
        "\n"
        "def beta_status():\n"
        "    importlib.import_module('os').system('echo ok')\n"
        "    return 'ok'\n"
        "\n"
        "def gamma_status():\n"
        "    import_module('subprocess').run(['echo', 'ok'], capture_output=True)\n"
        "    return 'ok'\n"
        "\n"
        "def delta_status():\n"
        "    runtime_os = importlib.import_module('os')\n"
        "    runtime_os.system('echo ok')\n"
        "    return 'ok'\n"
        "\n"
        "def epsilon_status():\n"
        "    importlib.import_module('urllib.request').urlretrieve('https://example.com/a', 'a')\n"
        "    return 'ok'\n"
        "\n"
        "def zeta_status():\n"
        "    runtime_tempfile = import_module('tempfile')\n"
        "    runtime_tempfile.mkdtemp()\n"
        "    return 'ok'\n"
        "\n"
        "def echo_text(text):\n"
        "    return text.strip()\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("alpha_status", "beta_status", "gamma_status", "delta_status"):
        assert "can execute external processes" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert "performs network requests" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["epsilon_status"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["epsilon_status"], aliases) is True
    assert "mutates files or directories" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
        functions["zeta_status"],
        aliases,
    )
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["zeta_status"], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo_text"], aliases) is False


def test_runtime_callback_registration_functions_are_not_wrapped():
    tree = ast.parse(
        "import atexit\n"
        "import signal\n"
        "from atexit import register as add_exit_hook\n"
        "from signal import signal as bind_signal\n"
        "\n"
        "def _cleanup(*args):\n"
        "    return None\n"
        "\n"
        "def status_message():\n"
        "    atexit.register(_cleanup)\n"
        "    return 'registered'\n"
        "\n"
        "def terminal_message():\n"
        "    signal.signal(signal.SIGTERM, _cleanup)\n"
        "    return 'installed'\n"
        "\n"
        "def alias_status():\n"
        "    add_exit_hook(_cleanup)\n"
        "    return 'registered'\n"
        "\n"
        "def alias_terminal():\n"
        "    bind_signal(signal.SIGINT, _cleanup)\n"
        "    return 'installed'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in ("status_message", "terminal_message", "alias_status", "alias_terminal"):
        assert "mutates process state" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_background_execution_functions_are_not_wrapped():
    tree = ast.parse(
        "import asyncio\n"
        "import multiprocessing as mp\n"
        "import threading\n"
        "\n"
        "def _worker():\n"
        "    return None\n"
        "\n"
        "def cache_refresh():\n"
        "    thread = threading.Thread(target=_worker, daemon=True)\n"
        "    thread.start()\n"
        "    return 'scheduled'\n"
        "\n"
        "def timer_refresh():\n"
        "    timer = threading.Timer(1.0, _worker)\n"
        "    timer.start()\n"
        "    return 'scheduled'\n"
        "\n"
        "def process_refresh():\n"
        "    proc = mp.Process(target=_worker)\n"
        "    proc.start()\n"
        "    return 'scheduled'\n"
        "\n"
        "def task_refresh():\n"
        "    asyncio.create_task(asyncio.sleep(0))\n"
        "    return 'scheduled'\n"
        "\n"
        "def direct_thread_refresh():\n"
        "    threading.Thread(target=_worker, daemon=True).start()\n"
        "    return 'scheduled'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "cache_refresh",
        "timer_refresh",
        "process_refresh",
        "task_refresh",
        "direct_thread_refresh",
    ):
        assert "starts background execution" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_executor_background_functions_are_not_wrapped():
    tree = ast.parse(
        "import _thread\n"
        "import concurrent.futures as futures\n"
        "import multiprocessing as mp\n"
        "from concurrent.futures import ProcessPoolExecutor as PPE\n"
        "from concurrent.futures import ThreadPoolExecutor as TPE\n"
        "from multiprocessing import Pool\n"
        "\n"
        "def _worker(value='ok'):\n"
        "    return value\n"
        "\n"
        "def parallel_status():\n"
        "    with futures.ThreadPoolExecutor(max_workers=1) as pool:\n"
        "        return pool.submit(_worker).result()\n"
        "\n"
        "def process_status():\n"
        "    with futures.ProcessPoolExecutor(max_workers=1) as pool:\n"
        "        return pool.submit(_worker).result()\n"
        "\n"
        "def alias_parallel_status():\n"
        "    with TPE(max_workers=1) as pool:\n"
        "        return list(pool.map(_worker, ['ok']))[0]\n"
        "\n"
        "def alias_process_status():\n"
        "    with PPE(max_workers=1) as pool:\n"
        "        return pool.submit(_worker).result()\n"
        "\n"
        "def pool_status():\n"
        "    with mp.Pool(1) as pool:\n"
        "        return pool.apply_async(_worker).get()\n"
        "\n"
        "def imported_pool_status():\n"
        "    with Pool(1) as pool:\n"
        "        return pool.map(_worker, ['ok'])[0]\n"
        "\n"
        "def direct_executor_status():\n"
        "    return futures.ThreadPoolExecutor(max_workers=1).submit(_worker).result()\n"
        "\n"
        "def raw_thread_status():\n"
        "    _thread.start_new_thread(_worker, ())\n"
        "    return 'started'\n"
        "\n"
        "def echo(value):\n"
        "    return value\n"
    )
    aliases = generate_module._runtime_call_aliases(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    for name in (
        "parallel_status",
        "process_status",
        "alias_parallel_status",
        "alias_process_status",
        "pool_status",
        "imported_pool_status",
        "direct_executor_status",
        "raw_thread_status",
    ):
        assert "starts background execution" in generate_module._function_body_unsafe_runtime_side_effect_reasons(
            functions[name],
            aliases,
        )
        assert generate_module._function_body_has_unsafe_runtime_side_effect(functions[name], aliases) is True
    assert generate_module._function_body_has_unsafe_runtime_side_effect(functions["echo"], aliases) is False


def test_quality_gate_rejects_success_true_in_tool_exception_handler():
    source = """
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool(name="solve", description="solve")
def solve(value: int = 0):
    try:
        raise RuntimeError("boom")
    except Exception:
        return {"success": True, "result": None, "error": None}

def create_app():
    return mcp
"""
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "demo.core",
                    "module": "core",
                    "functions": ["solve"],
                    "classes": [],
                }
            ]
        }
    }

    errors = generate_module._validate_mcp_service_source(source, analysis)

    assert any("broad exception handler returns success=True" in error for error in errors)


def test_generate_node_preserves_signatures_after_prune(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "loader.py").write_text(
        "def load_file(file_path, limit):\n    return file_path\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(generate_module, "_generate_readme_mcp", lambda analysis, loop_summary=None: "# demo\n")

    state = {
        "repository": {
            "name": "demo",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "analysis": {
            "repository_name": "demo",
            "dependencies": {"pyproject": False},
            "structure": {"packages": []},
            "llm_analysis": {
                "import_strategy": {"primary": "blackbox"},
                "core_modules": [
                    {
                        "package": "loader",
                        "module": "loader",
                        "functions": ["load_file"],
                        "classes": [],
                        "function_signatures": {"load_file": ["file_path", "limit"]},
                        "file_path": "loader.py",
                    }
                ],
            },
        },
        "run_result": {"success": False, "attempt": 4},
        "tests": {"plugin": {"passed": False, "attempt": 4}},
        "review_decision": "regenerate",
        "fix_applied": True,
    }

    result = generate_module.generate_node(state)

    assert result["workflow_status"] == "running"
    assert "run_result" not in result
    assert "plugin" not in result["tests"]
    assert "review_decision" not in result
    assert "fix_applied" not in result
    assert result["repair_loop"]["events"][-1]["event"] == "generation_started"
    service_path = Path(result["plugin"]["files"]["mcp_output/mcp_plugin/mcp_service.py"])
    service = service_path.read_text(encoding="utf-8")
    assert 'def load_file(file_path: str = "", limit: int = 0)' in service
    assert "_safe_resolve_path(source_path, file_path)" in service
    assert "import contextlib" in service
    assert "import io" in service
    assert "def _call_quietly" in service
    assert "result = _call_quietly(_code2mcp_target, [file_path, limit], {})" in service
    assert "except SystemExit as e:" in service
    assert 'f"SystemExit: {e}"' in service
    assert result["plugin"]["endpoints"] == ["load_file"]


def test_generate_node_fails_without_supported_targets(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "README.md").write_text("not a Python API repo\n", encoding="utf-8")
    stale_service = repo_root / "mcp_output" / "mcp_plugin" / "mcp_service.py"
    stale_service.parent.mkdir(parents=True)
    stale_service.write_text("# stale\n", encoding="utf-8")
    stale_summary = repo_root / "mcp_output" / "workflow_summary.json"
    stale_summary.write_text(
        json.dumps({"workflow_status": "validated", "validation_status": "validated", "verified": True}),
        encoding="utf-8",
    )
    state = {
        "repository": {
            "name": "empty",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "analysis": {
            "repository_name": "empty",
            "dependencies": {"pyproject": False},
            "structure": {"packages": []},
            "llm_analysis": {
                "import_strategy": {"primary": "blackbox"},
                "core_modules": [],
            },
        },
        "tests": {},
    }

    result = generate_module.generate_node(state)

    assert result["workflow_status"] == "failed"
    assert result["errors"][-1]["type"] == "UnsupportedRepository"
    assert result["errors"][-1]["details"]["stage"] == "pre_generation_target_selection"
    assert result["errors"][-1]["details"]["likely_reason"] == "no_supported_python_api_targets"
    assert result["errors"][-1]["details"]["original_core_module_count"] == 0
    assert result["errors"][-1]["details"]["filtered_core_module_count"] == 0
    assert result["plugin"]["endpoints"] == []
    error_path = repo_root / "mcp_output" / "generation_error.json"
    summary_path = repo_root / "mcp_output" / "workflow_summary.json"
    assert result["plugin"]["files"] == {
        "mcp_output/generation_error.json": str(error_path),
        "mcp_output/workflow_summary.json": str(summary_path),
    }
    assert error_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["workflow_status"] == "failed"
    assert summary["validation_status"] == "unsupported_audited"
    assert summary["verified"] is False
    assert summary["tests"]["mcp_plugin"]["passed"] is False
    assert not (source / "__init__.py").exists()
    assert not stale_service.exists()


def test_generate_node_fails_when_safety_filter_leaves_no_endpoints(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "decorators.py").write_text(
        "def describe_class(description):\n"
        "    def decorator(cls):\n"
        "        return cls\n"
        "    return decorator\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_module, "_has_verified_generation_targets", lambda _analysis: True)
    monkeypatch.setattr(generate_module, "_validate_mcp_service_source", lambda _content, _analysis: [])
    monkeypatch.setattr(
        generate_module,
        "_generate_mcp_service",
        lambda _analysis, _retry_info=None, _loop_summary=None: "from fastmcp import FastMCP\nmcp = FastMCP('demo')\ndef create_app():\n    return mcp\n",
    )
    monkeypatch.setattr(generate_module, "_generate_adapter_import", lambda _analysis, _loop_summary=None: "class Adapter:\n    pass\n")
    monkeypatch.setattr(generate_module, "_generate_readme_mcp", lambda _analysis, loop_summary=None: "# demo\n")

    state = {
        "repository": {
            "name": "decorator-only",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "analysis": {
            "repository_name": "decorator-only",
            "dependencies": {"pyproject": False},
            "structure": {"packages": []},
            "llm_analysis": {
                "import_strategy": {"primary": "import"},
                "core_modules": [
                    {
                        "package": "decorators",
                        "module": "decorators",
                        "functions": ["describe_class"],
                        "classes": [],
                        "function_signatures": {"describe_class": ["description"]},
                        "file_path": "decorators.py",
                    }
                ],
            },
        },
        "workflow_status": "running",
    }

    result = generate_module.generate_node(state)

    assert result["workflow_status"] == "failed"
    assert result["errors"][-1]["type"] == "UnsupportedRepository"
    assert result["errors"][-1]["details"]["stage"] == "post_generation_safety_validation"
    assert result["errors"][-1]["details"]["likely_reason"] == "candidate_targets_rejected_by_generation_safety_filters"
    assert result["errors"][-1]["details"]["original_function_count"] == 1
    assert result["errors"][-1]["details"]["filtered_function_count"] == 0
    assert result["plugin"]["endpoints"] == []
    assert (repo_root / "mcp_output" / "generation_error.json").exists()


def test_generate_node_reports_candidates_rejected_by_safety_filters(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "callbacks.py").write_text(
        "def on_press(key):\n"
        "    with open('wordlog.txt', 'a') as log_file:\n"
        "        log_file.write(str(key))\n",
        encoding="utf-8",
    )
    state = {
        "repository": {
            "name": "callback-only",
            "local_paths": {"repo_root": str(repo_root)},
        },
        "analysis": {
            "repository_name": "callback-only",
            "dependencies": {"pyproject": False},
            "structure": {"packages": ["pkg"]},
            "llm_analysis": {
                "import_strategy": {"primary": "import"},
                "core_modules": [
                    {
                        "package": "pkg",
                        "module": "callbacks",
                        "functions": ["on_press"],
                        "classes": [],
                        "function_signatures": {"on_press": ["key"]},
                        "function_details": {
                            "on_press": {
                                "parameters": ["key"],
                                "parameter_details": [{"name": "key", "annotation": "", "required": True}],
                            }
                        },
                        "wrapper_candidates": [{"name": "on_press", "kind": "function", "score": 95}],
                        "file_path": "pkg/callbacks.py",
                    }
                ],
            },
        },
        "tests": {},
    }

    result = generate_module.generate_node(state)

    details = result["errors"][-1]["details"]
    assert result["workflow_status"] == "failed"
    assert details["likely_reason"] == "candidate_targets_rejected_by_generation_safety_filters"
    assert details["original_core_module_count"] == 1
    assert details["original_function_count"] == 1
    assert details["filtered_core_module_count"] == 0
    assert details["filtered_function_count"] == 0
    assert details["rejected_target_count"] == 1
    assert details["rejected_targets"][0]["name"] == "on_press"
    reasons = details["rejected_targets"][0]["reasons"]
    assert "event handler/callback function name" in reasons
    assert "opens files in write/append mode" in reasons
    assert "writes files or streams" in reasons


def test_unsupported_generation_details_do_not_report_kept_starred_targets(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "tools.py").write_text("def echo(text):\n    return text\n", encoding="utf-8")
    original = {
        "repository_name": "starred",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["echo*"],
                    "classes": [],
                    "function_signatures": {"echo": ["text"]},
                    "file_path": "pkg/tools.py",
                }
            ]
        },
    }
    filtered = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["echo*"],
                    "classes": [],
                    "function_signatures": {"echo": ["text"]},
                    "file_path": "pkg/tools.py",
                }
            ]
        }
    }

    details = generate_module._unsupported_generation_details(
        original,
        filtered,
        stage="diagnostic",
        repo_root=str(repo_root),
    )

    assert "rejected_targets" not in details


def test_unsupported_generation_details_reports_wrapper_policy_rejection(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "querying.py").write_text(
        "def query(original_query: str, max_iter: int = 3):\n"
        "    return original_query\n",
        encoding="utf-8",
    )
    original = {
        "repository_name": "querying",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "querying",
                    "functions": ["query"],
                    "classes": [],
                    "function_signatures": {"query": ["original_query", "max_iter"]},
                    "function_details": {
                        "query": {
                            "parameters": ["original_query", "max_iter"],
                            "parameter_details": [
                                {"name": "original_query", "annotation": "str", "required": True},
                                {"name": "max_iter", "annotation": "int", "required": False, "default": "3"},
                            ],
                        }
                    },
                    "file_path": "pkg/querying.py",
                }
            ]
        },
    }

    details = generate_module._unsupported_generation_details(
        original,
        {"llm_analysis": {"core_modules": []}},
        stage="diagnostic",
        repo_root=str(repo_root),
    )

    assert details["rejected_targets"][0]["name"] == "query"
    assert details["rejected_targets"][0]["reasons"] == ["not selected by callable wrapper policy"]


def test_unsupported_generation_details_reports_analysis_runtime_file_read_risk():
    original = {
        "repository_name": "config-reader",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "config",
                    "functions": ["load_config"],
                    "classes": [],
                    "function_signatures": {"load_config": ["path"]},
                    "function_details": {
                        "load_config": {
                            "parameters": ["path"],
                            "parameter_details": [{"name": "path", "annotation": "str", "required": True}],
                            "risk_reasons": ["file_read"],
                        }
                    },
                    "file_path": "pkg/config.py",
                }
            ]
        },
    }

    details = generate_module._unsupported_generation_details(
        original,
        {"llm_analysis": {"core_modules": []}},
        stage="diagnostic",
    )

    assert details["rejected_targets"][0]["name"] == "load_config"
    assert "reads files or directories" in details["rejected_targets"][0]["reasons"]


def test_unsupported_generation_details_reports_empty_factory_rejection(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "factory.py").write_text(
        "from collections import defaultdict\n\n"
        "def index_list():\n"
        "    return defaultdict(list)\n",
        encoding="utf-8",
    )
    original = {
        "repository_name": "factory-demo",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "factory",
                    "functions": ["index_list"],
                    "classes": [],
                    "function_signatures": {"index_list": []},
                    "function_details": {"index_list": {"parameters": [], "parameter_details": []}},
                    "file_path": "pkg/factory.py",
                }
            ]
        },
    }

    details = generate_module._unsupported_generation_details(
        original,
        {"llm_analysis": {"core_modules": []}},
        stage="diagnostic",
        repo_root=str(repo_root),
    )

    assert details["rejected_targets"][0]["name"] == "index_list"
    assert details["rejected_targets"][0]["reasons"] == ["returns empty default-factory container"]


def test_prune_skips_empty_literal_container_functions(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "factory.py").write_text(
        "def empty_options():\n"
        "    return []\n\n"
        "def echo(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    analysis = {
        "repository_name": "literal-demo",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "factory",
                    "functions": ["empty_options", "echo"],
                    "classes": [],
                    "function_signatures": {"empty_options": [], "echo": ["value"]},
                    "function_details": {
                        "empty_options": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                        "echo": {
                            "parameters": ["value"],
                            "parameter_details": [{"name": "value", "annotation": "str", "required": True}],
                            "wrapper_score": 100,
                        },
                    },
                    "wrapper_candidates": [
                        {"name": "empty_options", "kind": "function", "score": 100},
                        {"name": "echo", "kind": "function", "score": 100},
                    ],
                    "file_path": "pkg/factory.py",
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root))

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["echo"]


def test_unsupported_generation_details_reports_empty_literal_container_rejection(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "factory.py").write_text(
        "def empty_options():\n"
        "    return []\n",
        encoding="utf-8",
    )
    original = {
        "repository_name": "literal-demo",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "factory",
                    "functions": ["empty_options"],
                    "classes": [],
                    "function_signatures": {"empty_options": []},
                    "function_details": {"empty_options": {"parameters": [], "parameter_details": []}},
                    "file_path": "pkg/factory.py",
                }
            ]
        },
    }

    details = generate_module._unsupported_generation_details(
        original,
        {"llm_analysis": {"core_modules": []}},
        stage="diagnostic",
        repo_root=str(repo_root),
    )

    assert details["rejected_targets"][0]["name"] == "empty_options"
    assert details["rejected_targets"][0]["reasons"] == ["returns empty literal container"]


def test_unsupported_generation_details_reports_module_import_side_effect_rejection(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "molecule.py").write_text(
        "def water():\n"
        "    return 'H2O'\n\n"
        "WATER = water()\n",
        encoding="utf-8",
    )
    original = {
        "repository_name": "molecule-demo",
        "dependencies": {"pyproject": False},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "molecule",
                    "functions": ["water"],
                    "classes": [],
                    "function_signatures": {"water": []},
                    "function_details": {"water": {"parameters": [], "parameter_details": []}},
                    "file_path": "pkg/molecule.py",
                    "import_side_effect_risk": True,
                    "import_side_effect_reasons": ["top_level_assignment_call:line_4"],
                }
            ]
        },
    }

    details = generate_module._unsupported_generation_details(
        original,
        {"llm_analysis": {"core_modules": []}},
        stage="diagnostic",
        repo_root=str(repo_root),
    )

    assert details["rejected_targets"][0]["name"] == "water"
    assert details["rejected_targets"][0]["reasons"] == [
        "module has import-time side effects: top_level_assignment_call:line_4"
    ]


def test_prune_uses_src_layout_submodule_file(tmp_path):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "source" / "src" / "humanize"
    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "filesize.py").write_text(
        "def naturalsize(value, binary=False):\n    return str(value)\n",
        encoding="utf-8",
    )

    analysis = {
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
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root))

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["naturalsize"]
    assert core_modules[0]["function_signatures"] == {"naturalsize": ["value", "binary"]}


def test_prune_accepts_utf8_bom_flat_modules(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        '\ufeffdef slugify(text: str, separator: str = "-") -> str:\n    return separator.join(text.lower().split())\n',
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "tools",
                    "module": "tools",
                    "functions": ["slugify"],
                    "classes": [],
                    "function_signatures": {"slugify": ["text", "separator"]},
                    "file_path": "tools.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root))

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["slugify"]
    assert core_modules[0]["function_signatures"] == {"slugify": ["text", "separator"]}


def test_local_import_roots_include_file_stems_for_sibling_imports():
    module = {
        "package": "bad-package",
        "module": "tools",
        "file_path": "bad-package/tools.py",
        "imports": ["helper", "missing_dep"],
    }
    helper = {
        "package": "bad-package",
        "module": "helper",
        "file_path": "bad-package/helper.py",
        "imports": [],
    }

    local_roots = generate_module._local_import_roots([module, helper])
    missing = generate_module._module_missing_runtime_imports(module, set(), local_roots)

    assert "helper" in local_roots
    assert missing == ["missing_dep"]


def test_runtime_precheck_loads_file_path_module_with_sibling_import(tmp_path):
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "source" / "bad-package"
    package_dir.mkdir(parents=True)
    (package_dir / "helper.py").write_text("def helper_value():\n    return 'ok'\n", encoding="utf-8")
    (package_dir / "tools.py").write_text(
        "from helper import helper_value\n\n"
        "def read_value():\n"
        "    return helper_value()\n",
        encoding="utf-8",
    )
    analysis = {"_runtime": {"env": {"exec_prefix": [sys.executable]}}}
    module = {
        "package": "bad-package",
        "module": "tools",
        "file_path": "bad-package/tools.py",
    }

    ok, reason = generate_module._module_runtime_symbols_available(
        analysis,
        str(repo_root),
        module,
        ["read_value"],
    )

    assert ok, reason


def test_runtime_precheck_loads_selected_function_despite_optional_top_level_import(tmp_path):
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "source" / "bad-package"
    package_dir.mkdir(parents=True)
    (package_dir / "tools.py").write_text(
        "import missing_optional_dependency\n\n"
        "def safe_value():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    analysis = {"_runtime": {"env": {"exec_prefix": [sys.executable]}}}
    module = {
        "package": "bad-package",
        "module": "tools",
        "file_path": "bad-package/tools.py",
    }

    ok, reason = generate_module._module_runtime_symbols_available(
        analysis,
        str(repo_root),
        module,
        ["safe_value"],
    )

    assert ok, reason


def test_prune_keeps_file_backed_function_with_unused_optional_import(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "bad-package"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        "import missing_optional_dependency\n\n"
        "def safe_value():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    analysis = {
        "_runtime": {
            "env": {
                "exec_prefix": [sys.executable],
                "dependency_installation": {"strategy": "import_packages", "installed": []},
            }
        },
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "bad-package",
                    "module": "tools",
                    "functions": ["safe_value"],
                    "classes": [],
                    "function_signatures": {"safe_value": []},
                    "function_details": {"safe_value": {"parameters": [], "parameter_details": []}},
                    "wrapper_candidates": [{"name": "safe_value", "kind": "function", "score": 100}],
                    "file_path": "bad-package/tools.py",
                    "imports": ["missing_optional_dependency"],
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root))

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["safe_value"]


def test_prune_prefers_wrapper_candidates_over_noisy_function_list(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        "def safe_value():\n"
        "    return 'ok'\n\n"
        "def debug_helper():\n"
        "    return 'debug'\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["safe_value", "debug_helper"],
                    "classes": [],
                    "function_signatures": {"safe_value": [], "debug_helper": []},
                    "function_details": {
                        "safe_value": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                        "debug_helper": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                    },
                    "wrapper_candidates": [{"name": "safe_value", "kind": "function", "score": 100}],
                    "file_path": "pkg/tools.py",
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["safe_value"]
    selection = pruned["llm_analysis"]["generation_selection"]
    assert selection["candidate_count"] == 1
    assert selection["selected_count"] == 1


def test_prune_respects_empty_wrapper_candidates(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        "def debug_helper():\n"
        "    return 'debug'\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["debug_helper"],
                    "classes": [],
                    "function_signatures": {"debug_helper": []},
                    "function_details": {
                        "debug_helper": {"parameters": [], "parameter_details": [], "wrapper_score": 100}
                    },
                    "wrapper_candidates": [],
                    "file_path": "pkg/tools.py",
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    assert pruned["llm_analysis"]["core_modules"] == []
    selection = pruned["llm_analysis"]["generation_selection"]
    assert selection["candidate_count"] == 0
    assert selection["selected_count"] == 0


def test_prune_skips_only_unavailable_symbol_in_mixed_module(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "bad-package"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        "import missing_optional_dependency\n\n"
        "def safe_value():\n"
        "    return 'ok'\n\n"
        "def broken_value():\n"
        "    return missing_optional_dependency.value\n",
        encoding="utf-8",
    )
    analysis = {
        "_runtime": {
            "env": {
                "exec_prefix": [sys.executable],
                "dependency_installation": {"strategy": "import_packages", "installed": []},
            }
        },
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "bad-package",
                    "module": "tools",
                    "functions": ["safe_value", "broken_value"],
                    "classes": [],
                    "function_signatures": {"safe_value": [], "broken_value": []},
                    "function_details": {
                        "safe_value": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                        "broken_value": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                    },
                    "wrapper_candidates": [
                        {"name": "safe_value", "kind": "function", "score": 100},
                        {"name": "broken_value", "kind": "function", "score": 100},
                    ],
                    "file_path": "bad-package/tools.py",
                    "imports": ["missing_optional_dependency"],
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["safe_value"]
    selection = pruned["llm_analysis"]["generation_selection"]
    assert selection["candidate_count"] == 2
    assert selection["selected_count"] == 1
    assert selection["runtime_skipped_count"] == 1
    assert selection["runtime_skipped_candidates"][0]["name"] == "broken_value"


def test_prune_batches_runtime_precheck_for_available_module(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        "def first_value():\n"
        "    return 'first'\n\n"
        "def second_value():\n"
        "    return 'second'\n",
        encoding="utf-8",
    )
    calls = []

    def fake_runtime_available(_analysis, _repo_root, _module, symbols):
        calls.append(tuple(symbols))
        return True, "ok"

    monkeypatch.setattr(generate_module, "_module_runtime_symbols_available", fake_runtime_available)
    analysis = {
        "_runtime": {
            "env": {
                "exec_prefix": [sys.executable],
                "dependency_installation": {"strategy": "import_packages", "installed": []},
            }
        },
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["first_value", "second_value"],
                    "classes": [],
                    "function_signatures": {"first_value": [], "second_value": []},
                    "function_details": {
                        "first_value": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                        "second_value": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                    },
                    "wrapper_candidates": [
                        {"name": "first_value", "kind": "function", "score": 100},
                        {"name": "second_value", "kind": "function", "score": 100},
                    ],
                    "file_path": "pkg/tools.py",
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["first_value", "second_value"]
    selection = pruned["llm_analysis"]["generation_selection"]
    assert selection["selected_count"] == 2
    assert selection["runtime_precheck_count"] == 1
    assert calls == [("first_value", "second_value")]


def test_prune_prefers_globally_callable_tools_over_early_complex_modules(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "heavy.py").write_text(
        "def main(sample_dir, ref_dir):\n    return None\n\n"
        "class NeedsConfig:\n"
        "    def __init__(self, config):\n"
        "        self.config = config\n",
        encoding="utf-8",
    )
    (source / "safe.py").write_text(
        "def get_rank():\n    return 0\n\n"
        "def echo(text):\n    return text\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "heavy",
                    "module": "heavy",
                    "functions": ["main"],
                    "classes": ["NeedsConfig"],
                    "function_signatures": {"main": ["sample_dir", "ref_dir"]},
                    "function_details": {
                        "main": {
                            "parameters": ["sample_dir", "ref_dir"],
                            "parameter_details": [
                                {"name": "sample_dir", "kind": "positional", "annotation": "str", "required": True, "default": ""},
                                {"name": "ref_dir", "kind": "positional", "annotation": "str", "required": True, "default": ""},
                            ],
                            "wrapper_score": 95,
                            "wrapper_recommended": True,
                        }
                    },
                    "class_details": {
                        "NeedsConfig": {
                            "constructor_requires_args": True,
                            "constructor_has_varargs": False,
                            "constructor_has_kwargs": False,
                            "wrapper_score": 20,
                            "wrapper_recommended": False,
                        }
                    },
                    "wrapper_candidates": [
                        {"name": "main", "kind": "function", "score": 95},
                        {"name": "NeedsConfig", "kind": "class", "score": 20},
                    ],
                    "file_path": "heavy.py",
                    "imports": ["torch"],
                },
                {
                    "package": "safe",
                    "module": "safe",
                    "functions": ["get_rank", "echo"],
                    "classes": [],
                    "function_signatures": {"get_rank": [], "echo": ["text"]},
                    "function_details": {
                        "get_rank": {
                            "parameters": [],
                            "parameter_details": [],
                            "wrapper_score": 95,
                            "wrapper_recommended": True,
                        },
                        "echo": {
                            "parameters": ["text"],
                            "parameter_details": [
                                {"name": "text", "kind": "positional", "annotation": "str", "required": True, "default": ""},
                            ],
                            "wrapper_score": 95,
                            "wrapper_recommended": True,
                        },
                    },
                    "wrapper_candidates": [
                        {"name": "get_rank", "kind": "function", "score": 95},
                        {"name": "echo", "kind": "function", "score": 95},
                    ],
                    "file_path": "safe.py",
                    "imports": [],
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["package"] == "safe"
    assert core_modules[0]["functions"] == ["get_rank", "echo"]
    assert core_modules[0]["classes"] == []


def test_prune_skips_example_modules_even_when_scored_high(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    example_dir = source / "example" / "offline"
    example_dir.mkdir(parents=True)
    (example_dir / "collector.py").write_text(
        "class Collector:\n    pass\n",
        encoding="utf-8",
    )
    samples_dir = source / "samples"
    samples_dir.mkdir(parents=True)
    (samples_dir / "sample_tool.py").write_text(
        "def sample_tool():\n    return 'sample'\n",
        encoding="utf-8",
    )
    tutorial_dir = source / "tutorials"
    tutorial_dir.mkdir(parents=True)
    (tutorial_dir / "walkthrough.py").write_text(
        "def tutorial_tool():\n    return 'tutorial'\n",
        encoding="utf-8",
    )
    (source / "core.py").write_text(
        "def ping():\n    return 'pong'\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "example.offline",
                    "module": "collector",
                    "functions": [],
                    "classes": ["Collector"],
                    "class_details": {"Collector": {"wrapper_score": 100}},
                    "wrapper_candidates": [{"name": "Collector", "kind": "class", "score": 100}],
                    "file_path": "example/offline/collector.py",
                },
                {
                    "package": "samples",
                    "module": "sample_tool",
                    "functions": ["sample_tool"],
                    "classes": [],
                    "function_signatures": {"sample_tool": []},
                    "function_details": {"sample_tool": {"wrapper_score": 100}},
                    "wrapper_candidates": [{"name": "sample_tool", "kind": "function", "score": 100}],
                    "file_path": "samples/sample_tool.py",
                },
                {
                    "package": "tutorials",
                    "module": "walkthrough",
                    "functions": ["tutorial_tool"],
                    "classes": [],
                    "function_signatures": {"tutorial_tool": []},
                    "function_details": {"tutorial_tool": {"wrapper_score": 100}},
                    "wrapper_candidates": [{"name": "tutorial_tool", "kind": "function", "score": 100}],
                    "file_path": "tutorials/walkthrough.py",
                },
                {
                    "package": "core",
                    "module": "core",
                    "functions": ["ping"],
                    "classes": [],
                    "function_signatures": {"ping": []},
                    "file_path": "core.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root))

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["package"] == "core"
    assert core_modules[0]["functions"] == ["ping"]


def test_function_wrapper_score_rejects_entrypoint_names():
    assert generate_module._function_wrapper_score("main", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("run", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("run_command_if_main", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("t_run", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("execute_shell", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("close_all_3d_figures", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("getParser", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("create_argparser", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_optparser", ["cmdpath"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("parse_args", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("parse_lst20_args", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("append_to_file", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_redis_connection", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("experiment_exception_hook", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("raises", ["exception"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("raise_bad_deps_messages", ["bad_messages"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("if_delegate_has_method", ["attr"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("add_safe_class", ["module", "name"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_safe_classes", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("assert_dig_allclose", ["info_py", "info_bin"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("requires_openmeeg_mark", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("has_freesurfer", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_browser_backend", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_brain_class", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("set_cuda_device", ["device_id", "verbose"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("ingest_historical_data", ["path"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("count_annotations", ["annotations"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("label_sign_flip", ["label", "src"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("match_channel_orders", ["insts", "copy"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("find_stim_steps", ["raw", "merge"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("concatenate_raws", ["raws", "preload"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("complete_surface_info", ["surf", "copy"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("grand_average", ["all_inst"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("read_raw_fil", ["binfile", "precision"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_screen_visual_angle", ["calibration"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_observer_meta", ["observer"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("array_type", ["mod"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("mod_version", ["mod"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("netcdf_and_hdf5_versions", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_extensions", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_resource_mappings", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("guess_engine", ["store_spec"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("season_to_month_tuple", ["seasons"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("inds_to_season_string", ["asints"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("stftfreq", ["wsize", "sfreq"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("get_fill_colors", ["cols", "n_fill"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_current_comp", ["info"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("channel_type", ["info", "idx"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("embed_neighbors", ["embedding"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("getCentroid", ["attribute_variants", "comparator"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("backends_dict_from_pkg", ["entrypoints"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score(
        "union_unordered_categorical_and_scalar",
        ["categorical_dtypes", "scalars"],
        {"wrapper_score": 100},
        100,
    ) is None
    assert generate_module._function_wrapper_score("TensorConstant", ["domain", "count"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("attach_ufl_id", ["cls"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("attach_metadata", ["item"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("update_global_expr_attributes", ["cls"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("determine_num_ops", ["num_ops", "unop", "binop", "rbinop"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("sort_precedence", ["precedence_list"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("jump", ["v", "n"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("is_cellwise_constant", ["expr"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("as_ufl", ["expression"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("as_vector", ["expressions", "index"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("expr_equals", ["self", "other"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("energy_norm", ["form", "coefficient"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("lhs", ["form"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("And", ["left", "right"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("atan2", ["f1", "f2"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("Not", ["condition"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("variable", ["e"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("unwrap_list_tensor", ["lt"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("extract_sub_elements", ["elements"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("sort_elements", ["elements"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("grad_to_reference_grad", ["o", "K"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("compute_integrand_scaling_factor", ["integral"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("strip_coordinate_derivatives", ["integrals"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("interpret_ufl_namespace", ["namespace"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("read_lines_decoded", ["fn"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("tstr", ["t", "colsize"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("shape_to_strides", ["sh"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("flatten_multiindex", ["ii", "strides"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("set_global_logger_level", ["level"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_beta", ["r", "b"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_calendar_day", ["freq"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("guess_plotly_rangebreaks", ["dt_index"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("build_processor", ["processor"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("transform_stock", ["stock"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_daily_bin_group", ["bench_values", "stock_values"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("check_transform_proc", ["proc_l"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("load", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("load_msft", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("load_data", ["json_file"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("show_versions", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("monkey_patch_cat_dtype", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("mpl_hist_arg", ["value"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("plot_acorr_with_error", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("rainbow", ["n"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("randintw", ["w", "size"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("progress_bar", ["it", "prefix", "size", "verbose"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("mne_templateMRI", ["verbose"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("init_python_session", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("halt_ordering", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("sdm_zero", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("epochs_to_array", ["epochs"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("fig2img", ["fig"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("spawn_random_state", ["rng", "n_children"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score(
        "check_random_state_children",
        ["random_state_parent", "random_state_children", "n_children"],
        {"wrapper_score": 100},
        100,
    ) is None
    assert generate_module._function_wrapper_score("check_random_state", ["seed"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("eog_features", ["eog_cleaned", "peaks", "sampling_rate"], {"wrapper_score": 100}, 100, ["numpy"]) is None
    assert generate_module._function_wrapper_score("rsp_rav", ["amplitude", "peaks", "troughs"], {"wrapper_score": 100}, 100, ["numpy"]) is None
    assert generate_module._function_wrapper_score("signal_synchrony", ["signal1", "signal2"], {"wrapper_score": 100}, 100, ["numpy"]) is None
    assert generate_module._function_wrapper_score(
        "today",
        ["tzinfo"],
        {
            "parameters": ["tzinfo"],
            "parameter_details": [{"name": "tzinfo", "annotation": "", "default": "None"}],
            "wrapper_score": 100,
        },
        100,
    ) is None
    assert generate_module._function_wrapper_score(
        "within_delta",
        ["dt1", "dt2", "delta"],
        {
            "parameters": ["dt1", "dt2", "delta"],
            "parameter_details": [
                {"name": "dt1", "annotation": "", "default": ""},
                {"name": "dt2", "annotation": "", "default": ""},
                {"name": "delta", "annotation": "", "default": ""},
            ],
            "wrapper_score": 100,
        },
        100,
    ) is None
    assert generate_module._function_wrapper_score(
        "easter",
        ["year", "method"],
        {
            "parameters": ["year", "method"],
            "parameter_details": [
                {"name": "year", "annotation": "", "default": ""},
                {"name": "method", "annotation": "", "default": "EASTER_WESTERN"},
            ],
            "wrapper_score": 100,
        },
        100,
    ) is None
    assert generate_module._function_wrapper_score("deduplicate_results", ["results"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_docs_to_chunks", ["documents"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("mixture_rvs", ["prob", "size", "dist"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("handle_data_class_factory", ["endog", "exog"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("check_internet", ["url"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("load_pickle", ["fname"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("table_extend", ["tables"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("Gf", ["T", "ff"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("corr2cov", ["corr", "std"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("corr_ar", ["k_vars", "ar"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("corr_equi", ["k_vars", "rho"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("getbranches", ["tree"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("convertlabels", ["ys", "indices"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("groupstatsbin", ["factors", "values"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("anovadict", ["res"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("data2groupcont", ["x1", "x2"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("dropname", ["ss", "li"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("dummy_limits", ["d"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("breaks_cusumolsresid", ["resid", "ddof"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("log_word", ["word"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("on_press", ["key"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("on_release", ["key"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("has_cxx", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("compile_availability", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("check_jieba", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("list_depparse", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("to_text", ["sentence"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("fix_sentence", ["sentence"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("random_select", ["doc", "size", "seed"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("chuliu_edmonds_one_root", ["scores"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("count_edges", ["edges_counted"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("relabel_graph", ["edge_list", "many_to_one"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_outer_boundary", ["outer_face"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("prepare_scores", ["scores"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("add_peft_args", ["parser"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("find_constituent_end", ["gold_sequence", "cur_index"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("find_subtree_end", ["gold_sequence", "current_index"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_trees", ["all_lines", "splits"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_lines", ["lines"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_lines", ["file_lines"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_lines", ["input_lines"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_lines", ["text_lines"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("compare_signature_and_declarations", ["arg_list", "decls"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("extract_multiline_signature", ["block"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("extract_declarations_by_args", ["block", "start_idx", "arg_names"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_pyx_arg", ["arg_list", "decl_map"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_meta_data", ["header", "supplementary_lines"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("parse_lat_col", ["column", "latitude_column"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("format_comments_and_history", ["input_header"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("all_coordinates_from_map", ["smap"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("contains_coordinate", ["smap", "coordinates"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_heliocentric_angle", ["coordinate_on_solar_disk"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_rectangle_coordinates", ["bottom_left", "width"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("setup", ["app"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_keys_list", ["dictionary"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("dict_keys_same", ["list_of_dicts"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("read_struct_skeleton", ["xdrdata"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("from_helioviewer_project", ["meta"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("source_stretch", ["meta", "fits_stretch"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("warn_deprecated", ["msg", "stacklevel"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_node_text", ["node"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("node_to_dict", ["node"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("fix_duplicate_notes", ["notes_to_add", "docstring"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("find_newest_version", ["package", "threshold"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_min_version", ["requirement"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_package_releases", ["package"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("iter_sort_response", ["response"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("resolve_requirement_versions", ["package_versions"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_extra_groups", ["groups", "exclude_extras"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("process_dependencies", ["package", "threshold"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("output_version_bumps", ["package", "threshold"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("is_version_old", ["package", "version_str", "threshold"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("call_api", ["query", "api_key"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("login_user", ["username", "password"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("refresh_session", ["refreshToken"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("kegg_get", ["dbentries", "option"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_sprot_raw", ["id"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_prosite_entry", ["id"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_online_vso_url", [], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("wsdl_retriever", ["service"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("parse", ["source"], {"wrapper_score": 100}, 100) is None
    assert (
        generate_module._function_wrapper_score(
            "get_indiv",
            ["line"],
            {"wrapper_score": 100, "docstring": "Extract the details of the individual information on the line."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "echo_sentence",
            ["sentence"],
            {
                "wrapper_score": 100,
                "parameter_details": [{"name": "sentence", "annotation": "str", "required": True}],
            },
            100,
        )
        is not None
    )
    assert (
        generate_module._function_wrapper_score(
            "build_spec",
            ["spec"],
            {"wrapper_score": 100, "docstring": "spec : mapping\n    Declarative build settings."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "apply_adapter",
            ["adapter"],
            {"wrapper_score": 100, "docstring": "adapter : callable\n    Hook used to adapt each value."},
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score(
        "apply_on_element",
        ["f", "args", "kwargs", "n"],
        {"wrapper_score": 100},
        100,
    ) is None
    assert generate_module._function_wrapper_score(
        "sequenceOfFloats",
        ["string"],
        {
            "wrapper_score": 100,
            "docstring": "A custom type for the argparse commandline parser. >>> parser.add_argument('argname')",
        },
        100,
    ) is None
    assert generate_module._function_wrapper_score(
        "get_scoring_metric",
        ["metric"],
        {
            "wrapper_score": 100,
            "docstring": "Get a scoring metric by name, or passthrough a callable. return metric",
        },
        100,
    ) is None
    assert generate_module._function_wrapper_score("linrec", ["coeffs", "init", "n"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("linrec_coeffs", ["c", "n"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("contrast", ["image", "mask"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("apply_dics", ["evoked", "filters", "verbose"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("apply_dics_csd", ["csd", "filters", "verbose"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("cosine_score", ["stc_true", "stc_est"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("template_ellipsoid", ["shape"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_offset", ["hdr"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("chebyshev", ["h1", "h2"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("discretize_cmap", ["cmap", "N"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("devectorize_axes", ["ax", "dpi"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("uniform_sphere", ["RAlim", "DEClim", "size"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("convert_to_stdev", ["logL"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("url_content_length", ["fhandle"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("BgzfBlocks", ["handle"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("parse", ["handle"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("read", ["handle"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_prosite_raw", ["id", "cgi"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("read_char", ["fid", "count"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("split_virtual_offset", ["virtual_offset"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("setup_text_plots", ["fontsize", "usetex"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_m_b", ["beta"], {"wrapper_score": 100}, 100, ["matplotlib", "numpy"]) is None
    assert generate_module._function_wrapper_score(
        "immerkaer",
        ["input"],
        {
            "wrapper_score": 100,
            "docstring": "Estimate noise.\n\nParameters\n----------\ninput : array_like\n    Array to process.",
        },
        100,
    ) is None
    assert generate_module._function_wrapper_score(
        "immerkaer",
        ["input"],
        {
            "wrapper_score": 100,
            "docstring": "Estimate the global noise. The input image is assumed to have Gaussian noise.",
        },
        100,
        ["numpy", "scipy"],
    ) is None
    assert generate_module._function_wrapper_score(
        "mutual_information",
        ["i1", "i2", "bins"],
        {
            "wrapper_score": 100,
            "docstring": "Computes mutual information between two images.",
        },
        100,
        ["numpy"],
    ) is None
    assert generate_module._function_wrapper_score(
        "complexity_hjorth",
        ["signal"],
        {"wrapper_score": 100, "docstring": "Compute signal complexity."},
        100,
        ["numpy"],
    ) is None
    assert generate_module._function_wrapper_score(
        "fractal_linelength",
        ["signal"],
        {"wrapper_score": 100, "docstring": "Compute fractal line length."},
        100,
        ["numpy"],
    ) is None
    assert generate_module._function_wrapper_score(
        "find_closest",
        ["closest_to", "list_to_search_in"],
        {
            "wrapper_score": 100,
            "docstring": "Parameters\n----------\nclosest_to : float\nlist_to_search_in : list\n    Values to search.",
        },
        100,
        ["numpy"],
    ) is None
    assert generate_module._function_wrapper_score(
        "compare_xml_strings",
        ["doc1", "doc2"],
        {"wrapper_score": 100},
        100,
    ) is None
    assert generate_module._function_wrapper_score(
        "echo_input",
        ["input"],
        {
            "wrapper_score": 100,
            "docstring": "Echo text.\n\nParameters\n----------\ninput : str\n    Text to echo.",
        },
        100,
    ) is not None
    assert generate_module._function_wrapper_score("check_m", ["m", "seasonal"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("check_cv", ["cv"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("guess_horizon", ["label"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("retrieve_ensembl2symbol_data", ["filename", "organism"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("next_pow_2", ["i"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("az2baz2az", ["angle"], {"wrapper_score": 100}, 100) is not None
    assert (
        generate_module._function_wrapper_score(
            "describe_class",
            ["description"],
            {"wrapper_score": 100, "docstring": "Decorator function. Returns a decorator function."},
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score("contrast_all_one", ["nm"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score(
        "add",
        ["a", "b"],
        {
            "wrapper_score": 100,
            "parameter_details": [
                {"name": "a", "annotation": "int"},
                {"name": "b", "annotation": "float"},
            ],
        },
        100,
    ) is not None
    signature, call_args, names = generate_module._tool_signature_and_call(["n"], [{"name": "n", "annotation": "", "default": ""}])
    assert signature == "n: int = 0"
    assert call_args == "n"
    assert names == ["n"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["ra", "dec"],
        [
            {"name": "ra", "annotation": "", "default": ""},
            {"name": "dec", "annotation": "", "default": ""},
        ],
        "ra_dec_to_xyz",
    )
    assert signature == "ra: float = 0.0, dec: float = 0.0"
    assert call_args == "ra, dec"
    assert names == ["ra", "dec"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["nbytes"],
        [{"name": "nbytes", "annotation": "", "default": ""}],
        "bytes_to_string",
    )
    assert signature == "nbytes: int = 0"
    assert call_args == "nbytes"
    assert names == ["nbytes"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["m", "seasonal"],
        [
            {"name": "m", "annotation": "", "default": ""},
            {"name": "seasonal", "annotation": "", "default": ""},
        ],
        "check_m",
    )
    assert signature == "m: int = 0, seasonal: bool = False"
    assert call_args == "m, seasonal"
    assert names == ["m", "seasonal"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["d"],
        [{"name": "d", "annotation": "", "default": ""}],
        "next_odd",
    )
    assert signature == "d: int = 0"
    assert call_args == "d"
    assert names == ["d"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["theta"],
        [{"name": "theta", "annotation": "", "default": ""}],
        "tau_frank",
    )
    assert signature == "theta: float = 0.0"
    assert call_args == "theta"
    assert names == ["theta"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["nm"],
        [{"name": "nm", "annotation": "", "default": ""}],
        "contrast_all_one",
    )
    assert signature == "nm: int = 3"
    assert call_args == "nm"
    assert names == ["nm"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["N", "half_nbw", "Kmax"],
        [
            {"name": "N", "annotation": "", "default": ""},
            {"name": "half_nbw", "annotation": "", "default": ""},
            {"name": "Kmax", "annotation": "", "default": ""},
        ],
        "dpss_windows",
    )
    assert signature == "N: int = 0, half_nbw: float = 2.5, Kmax: int = 3"
    assert call_args == "N, half_nbw, Kmax"
    assert names == ["N", "half_nbw", "Kmax"]
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["n"],
        [{"name": "n", "annotation": "SupportsIndex", "default": ""}],
        "binomial_coefficients",
    )
    assert signature == "n: int = 0"
    assert call_args == "n"
    assert names == ["n"]


def test_class_wrapper_score_rejects_sensitive_constructor_params(monkeypatch):
    monkeypatch.setenv("CODE2MCP_ENABLE_CLASS_WRAPPERS", "true")

    assert (
        generate_module._class_wrapper_score(
            "Client",
            {
                "wrapper_score": 100,
                "public_methods": [{"name": "ping"}],
                "constructor_parameter_details": [
                    {"name": "api_key", "annotation": "str", "required": False, "default": "None"}
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._class_wrapper_score(
            "AuthClient",
            {
                "wrapper_score": 100,
                "public_methods": [{"name": "ping"}],
                "constructor_parameter_details": [],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._class_wrapper_score(
            "Formatter",
            {
                "wrapper_score": 100,
                "public_methods": [{"name": "format"}],
                "constructor_parameter_details": [],
            },
            100,
        )
        is not None
    )


def test_class_wrapper_score_rejects_complex_runtime_constructor_params(monkeypatch):
    monkeypatch.setenv("CODE2MCP_ENABLE_CLASS_WRAPPERS", "true")

    assert (
        generate_module._class_wrapper_score(
            "ClientTool",
            {
                "wrapper_score": 100,
                "public_methods": [{"name": "ping"}],
                "constructor_parameter_details": [
                    {"name": "client", "annotation": "", "required": False, "default": "None"},
                    {"name": "config", "annotation": "", "required": False, "default": "None"},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._class_wrapper_score(
            "Formatter",
            {
                "wrapper_score": 100,
                "public_methods": [{"name": "format"}],
                "constructor_parameter_details": [
                    {"name": "prefix", "annotation": "str", "required": False, "default": "''"}
                ],
            },
            100,
        )
        is not None
    )


def test_class_wrapper_score_rejects_data_container_details(monkeypatch):
    monkeypatch.setenv("CODE2MCP_ENABLE_CLASS_WRAPPERS", "true")

    assert generate_module._class_wrapper_score("Quote", {}, 100) is None
    assert (
        generate_module._class_wrapper_score(
            "Quote",
            {
                "wrapper_score": 100,
                "public_methods": [{"name": "model_dump"}],
                "constructor_parameter_details": [],
                "risk_reasons": ["data_container_class"],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._class_wrapper_score(
            "Payload",
            {
                "wrapper_score": 100,
                "public_methods": [],
                "constructor_parameter_details": [],
                "risk_reasons": ["typed_dict_class", "no_public_methods"],
            },
            100,
        )
        is None
    )


def test_prune_skips_data_container_class_when_class_wrappers_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CODE2MCP_ENABLE_CLASS_WRAPPERS", "true")
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "models.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Quote:\n"
        "    symbol: str\n\n"
        "def summarize(symbol: str) -> str:\n"
        "    return symbol.upper()\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "models",
                    "module": "models",
                    "functions": ["summarize"],
                    "classes": ["Quote"],
                    "function_signatures": {"summarize": ["symbol"]},
                    "function_details": {
                        "summarize": {
                            "parameters": ["symbol"],
                            "parameter_details": [
                                {"name": "symbol", "annotation": "str", "required": True},
                            ],
                            "wrapper_score": 95,
                            "wrapper_recommended": True,
                        }
                    },
                    "class_details": {
                        "Quote": {
                            "wrapper_score": 100,
                            "public_methods": [],
                            "constructor_parameter_details": [],
                            "risk_reasons": ["data_container_class", "no_public_methods"],
                        }
                    },
                    "wrapper_candidates": [
                        {"name": "Quote", "kind": "class", "score": 100},
                        {"name": "summarize", "kind": "function", "score": 95},
                    ],
                    "file_path": "models.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["summarize"]
    assert core_modules[0]["classes"] == []


def test_prune_prefers_callable_small_functions_over_complex_wrappers(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "tools.py").write_text(
        "def ping():\n    return 'pong'\n\n"
        "def train_model(model, dataset):\n    return model\n\n"
        "class Runner:\n"
        "    def __init__(self, config):\n"
        "        self.config = config\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "tools",
                    "module": "tools",
                    "functions": ["ping", "train_model"],
                    "classes": ["Runner"],
                    "function_signatures": {
                        "ping": [],
                        "train_model": ["model", "dataset"],
                    },
                    "function_details": {
                        "ping": {"parameters": [], "parameter_details": []},
                        "train_model": {
                            "parameters": ["model", "dataset"],
                            "parameter_details": [
                                {"name": "model", "annotation": "Any", "required": True},
                                {"name": "dataset", "annotation": "Any", "required": True},
                            ],
                        },
                    },
                    "class_details": {
                        "Runner": {
                            "constructor_requires_args": True,
                            "constructor_parameter_details": [
                                {"name": "config", "annotation": "dict", "required": True}
                            ],
                        }
                    },
                    "file_path": "tools.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root))

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["ping"]
    assert core_modules[0]["classes"] == []


def test_function_wrapper_score_rejects_numbered_dataframe_params():
    assert (
        generate_module._function_wrapper_score(
            "combine_and_sort_dataframes",
            ["df1", "df2"],
            {
                "wrapper_score": 100,
                "parameters": ["df1", "df2"],
                "parameter_details": [
                    {"name": "df1", "annotation": "Any", "required": True},
                    {"name": "df2", "annotation": "Any", "required": True},
                ],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_rejects_dataframe_dict_params():
    assert (
        generate_module._function_wrapper_score(
            "align_index",
            ["df_dict", "join"],
            {
                "wrapper_score": 95,
                "parameters": ["df_dict", "join"],
                "parameter_details": [
                    {"name": "df_dict", "annotation": "", "required": True, "default": ""},
                    {"name": "join", "annotation": "", "required": True, "default": ""},
                ],
            },
            95,
            ["pandas"],
        )
        is None
    )


def test_function_wrapper_score_rejects_file_reader_path_params():
    assert generate_module._function_wrapper_score("read_video", ["filename"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("open_video", ["filename"], {"wrapper_score": 100}, 100) is None
    assert (
        generate_module._function_wrapper_score(
            "read_acqknowledge",
            ["filename", "sampling_rate"],
            {"wrapper_score": 100},
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score("read_file", ["file_path"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("read_value", ["value"], {"wrapper_score": 100}, 100) is not None
    assert generate_module._function_wrapper_score("open_value", ["value"], {"wrapper_score": 100}, 100) is not None


def test_function_wrapper_score_rejects_external_file_resource_helpers():
    assert (
        generate_module._function_wrapper_score(
            "hash_file",
            ["path"],
            {
                "wrapper_score": 100,
                "docstring": "Returns the SHA-256 hash of a file.\n\npath : str\n    The path of the file to be hashed.",
            },
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score("replacement_filename", ["path"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("is_dir", ["path"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("is_file", ["path"], {"wrapper_score": 100}, 100) is None
    assert (
        generate_module._function_wrapper_score(
            "compare_subroutines",
            ["dir_old", "dir_new"],
            {"wrapper_score": 100},
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score("make_output_index", ["dir_name"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_c_def", ["src_dir"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("get_pyx_def", ["src_dir"], {"wrapper_score": 100}, 100) is None
    assert (
        generate_module._function_wrapper_score(
            "read_srs",
            ["filepath"],
            {"wrapper_score": 100, "docstring": "Parse a SRS table.\n\nfilepath : str\n    The full path to a SRS table."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "get_header",
            ["filename", "debug"],
            {"wrapper_score": 100, "docstring": "filename : str\n    Name of file to be read."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "parse_observing_summary_dbase_file",
            ["filename"],
            {"wrapper_score": 100, "docstring": "filename : str\n    The filename of the obssumm dbase file."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "load_catalog",
            ["source_file"],
            {"wrapper_score": 100, "docstring": "Load a catalog from the source file containing records."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "load_forms",
            ["filename"],
            {
                "wrapper_score": 100,
                "parameters": ["filename"],
                "docstring": "Return a list of all forms in a file.",
                "parameter_details": [{"name": "filename", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "load_ufl_file",
            ["filename"],
            {
                "wrapper_score": 100,
                "parameters": ["filename"],
                "docstring": "Load a UFL file with elements, coefficients, expressions and forms.",
                "parameter_details": [{"name": "filename", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "read_ufl_file",
            ["filename"],
            {
                "wrapper_score": 100,
                "parameters": ["filename"],
                "docstring": "Read a UFL file.",
                "parameter_details": [{"name": "filename", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "read_config",
            ["config_file"],
            {"wrapper_score": 100, "docstring": "Read settings from the path to the config file."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "get_subjects_dir",
            ["subjects_dir", "raise_error"],
            {"wrapper_score": 100, "docstring": "subjects_dir : path-like | None\n    Return the SUBJECTS_DIR config."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "estimate_head_mri_t",
            ["subject", "subjects_dir"],
            {"wrapper_score": 100, "docstring": "A subject's fiducials can be estimated given a Freesurfer recon-all."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "read_tri",
            ["fname_in", "swap"],
            {"wrapper_score": 100, "docstring": "fname_in : path-like\n    Path to surface ASCII file."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "fiff_open",
            ["fname", "preload"],
            {"wrapper_score": 100, "docstring": "Open a FIF file.\n\nfname : path-like | fid\n    Name of the fif file."},
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score("what", ["fname"], {"wrapper_score": 100}, 100) is None
    assert generate_module._function_wrapper_score("expand_fsspec_open_file", ["open_file"], {"wrapper_score": 100}, 100) is None
    assert (
        generate_module._function_wrapper_score(
            "normalize_path",
            ["path"],
            {"wrapper_score": 100, "docstring": "Normalize a path string without touching the filesystem."},
            100,
        )
        is not None
    )


def test_function_wrapper_score_rejects_domain_runtime_object_params():
    assert (
        generate_module._function_wrapper_score(
            "get_coef",
            ["estimator", "attr"],
            {
                "wrapper_score": 100,
                "parameters": ["estimator", "attr"],
                "docstring": "estimator : object | None\n    An estimator from scikit-learn.",
                "parameter_details": [
                    {"name": "estimator", "annotation": "", "required": True, "default": ""},
                    {"name": "attr", "annotation": "str", "required": False, "default": "'filters_'"},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "convert_forward_solution",
            ["fwd", "surf_ori", "copy"],
            {
                "wrapper_score": 100,
                "parameters": ["fwd", "surf_ori", "copy"],
                "docstring": "fwd : Forward\n    The forward solution to modify.",
                "parameter_details": [
                    {"name": "fwd", "annotation": "", "required": True, "default": ""},
                    {"name": "surf_ori", "annotation": "bool", "required": False, "default": "False"},
                    {"name": "copy", "annotation": "bool", "required": False, "default": "True"},
                ],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_rejects_domain_pair_index_params():
    assert (
        generate_module._function_wrapper_score(
            "condensedDistance",
            ["dupes"],
            {
                "wrapper_score": 100,
                "parameters": ["dupes"],
                "parameter_details": [{"name": "dupes", "annotation": "Scores", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "union_find",
            ["scored_pairs"],
            {
                "wrapper_score": 100,
                "parameters": ["scored_pairs"],
                "parameter_details": [{"name": "scored_pairs", "annotation": "Scores", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "extractIndices",
            ["index_fields"],
            {
                "wrapper_score": 100,
                "parameters": ["index_fields"],
                "parameter_details": [{"name": "index_fields", "annotation": "IndexList", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "summarize_pairs",
            ["pairs"],
            {
                "wrapper_score": 100,
                "parameters": ["pairs"],
                "parameter_details": [{"name": "pairs", "annotation": "Scores", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "scale_score",
            ["score"],
            {
                "wrapper_score": 100,
                "parameters": ["score"],
                "parameter_details": [{"name": "score", "annotation": "float", "required": True}],
            },
            100,
        )
        is not None
    )


def test_function_wrapper_score_rejects_graph_edge_mapping_and_callable_params():
    assert (
        generate_module._function_wrapper_score(
            "combinatorial_embedding_to_pos",
            ["embedding", "fully_triangulate"],
            {
                "wrapper_score": 100,
                "parameters": ["embedding", "fully_triangulate"],
                "docstring": "embedding : nx.PlanarEmbedding\n    The embedding to draw.",
                "parameter_details": [
                    {"name": "embedding", "annotation": "", "required": True},
                    {"name": "fully_triangulate", "annotation": "bool", "required": False, "default": "False"},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "edges_equal",
            ["edges1", "edges2", "directed"],
            {
                "wrapper_score": 100,
                "parameters": ["edges1", "edges2", "directed"],
                "docstring": "edges1, edges2 : iterables of tuples\n    Edge containers to compare.",
                "parameter_details": [
                    {"name": "edges1", "annotation": "", "required": True},
                    {"name": "edges2", "annotation": "", "required": True},
                    {"name": "directed", "annotation": "bool", "required": False, "default": "False"},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "groups",
            ["many_to_one"],
            {
                "wrapper_score": 100,
                "parameters": ["many_to_one"],
                "docstring": "many_to_one : dict\n    A mapping from many keys to one value.",
                "parameter_details": [{"name": "many_to_one", "annotation": "", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "make_partition",
            ["items", "test", "check"],
            {
                "wrapper_score": 100,
                "parameters": ["items", "test", "check"],
                "docstring": "test : collections.abc.Callable[[object, object], bool]\n    Similarity predicate.",
                "parameter_details": [
                    {"name": "items", "annotation": "", "required": True},
                    {"name": "test", "annotation": "", "required": True},
                    {"name": "check", "annotation": "bool", "required": False, "default": "True"},
                ],
            },
            100,
        )
        is None
    )
    assert generate_module._function_wrapper_score("attach", ["module_name"], {"wrapper_score": 100}, 100) is None


def test_function_wrapper_score_rejects_biostructure_tree_and_parser_helpers():
    assert (
        generate_module._function_wrapper_score(
            "deduplicate",
            ["points"],
            {
                "wrapper_score": 100,
                "parameters": ["points"],
                "docstring": "Arguments:\n - points - list of points [x1, y1, x2, y2,...]",
                "parameter_details": [{"name": "points", "annotation": "", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "calculate_pseudocounts",
            ["motif"],
            {
                "wrapper_score": 100,
                "parameters": ["motif"],
                "docstring": "Calculate pseudocounts for a motif object.",
                "parameter_details": [{"name": "motif", "annotation": "", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "psea",
            ["pname"],
            {"wrapper_score": 100, "parameters": ["pname"], "docstring": "Parse PSEA output file."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "psea2HEC",
            ["pseq"],
            {"wrapper_score": 100, "parameters": ["pseq"], "docstring": "Translate PSEA secondary structure string."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "residue_depth",
            ["residue", "surface"],
            {
                "wrapper_score": 100,
                "parameters": ["residue", "surface"],
                "docstring": "Residue depth as average depth of all its atoms.",
                "parameter_details": [
                    {"name": "residue", "annotation": "", "required": True},
                    {"name": "surface", "annotation": "", "required": True},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "min_dist",
            ["coord", "surface"],
            {
                "wrapper_score": 100,
                "parameters": ["coord", "surface"],
                "docstring": "Return minimum distance between coord and surface.",
                "parameter_details": [
                    {"name": "coord", "annotation": "", "required": True},
                    {"name": "surface", "annotation": "", "required": True},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "get_unique_parents",
            ["entity_list"],
            {"wrapper_score": 100, "parameters": ["entity_list"], "docstring": "Translate a list of entities."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "strict_consensus",
            ["trees"],
            {
                "wrapper_score": 100,
                "parameters": ["trees"],
                "docstring": ":Parameters:\n    trees : iterable\n        iterable of trees to produce consensus tree.",
                "parameter_details": [{"name": "trees", "annotation": "", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "parse_siteclass_proportions",
            ["line_floats"],
            {"wrapper_score": 100, "parameters": ["line_floats"]},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "process_asa_data",
            ["rsa_data"],
            {"wrapper_score": 100, "parameters": ["rsa_data"], "docstring": "Process .asa output data."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "ss_to_index",
            ["ss"],
            {"wrapper_score": 100, "parameters": ["ss"], "docstring": "Secondary structure symbol to index."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "version",
            ["version_string"],
            {"wrapper_score": 100, "parameters": ["version_string"], "docstring": "Parse semantic version scheme."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "parse_vulgar_comp",
            ["hsp", "vulgar_comp"],
            {"wrapper_score": 100, "parameters": ["hsp", "vulgar_comp"], "docstring": "Parse hsp dictionary components."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "record_has",
            ["inrec", "fieldvals"],
            {"wrapper_score": 100, "parameters": ["inrec", "fieldvals"], "docstring": "Accept a record and dictionary of field values."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "qcp",
            ["coords1", "coords2", "natoms"],
            {"wrapper_score": 100, "parameters": ["coords1", "coords2", "natoms"], "docstring": "Input coordinate arrays have shape Nx3."},
            100,
            ["numpy"],
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "bootstrap_consensus",
            ["alignment", "times", "tree_constructor", "consensus"],
            {
                "wrapper_score": 100,
                "parameters": ["alignment", "times", "tree_constructor", "consensus"],
                "docstring": "alignment : Alignment object\nconsensus : function\n    Consensus method.",
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "search",
            ["query", "fields", "batch_size"],
            {"wrapper_score": 100, "parameters": ["query", "fields", "batch_size"], "docstring": "Search the API at https://example.test."},
            100,
            ["urllib"],
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "make_dssp_dict",
            ["filename"],
            {"wrapper_score": 100, "parameters": ["filename"], "docstring": "Return data from a DSSP output file."},
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "replace_entry",
            ["line", "fieldn", "newentry"],
            {"wrapper_score": 100, "parameters": ["line", "fieldn", "newentry"]},
            100,
        )
        is not None
    )
    assert (
        generate_module._function_wrapper_score(
            "pdb_date",
            ["datestr"],
            {
                "wrapper_score": 100,
                "parameters": ["datestr"],
                "parameter_details": [{"name": "datestr", "annotation": "str", "required": True}],
            },
            100,
        )
        is not None
    )
    assert (
        generate_module._function_wrapper_score(
            "angle2trig",
            ["theta"],
            {
                "wrapper_score": 100,
                "parameters": ["theta"],
                "parameter_details": [{"name": "theta", "annotation": "float", "required": True}],
            },
            100,
        )
        is not None
    )


def test_function_wrapper_score_allows_supported_numeric_sequence_params():
    detail = {
        "wrapper_score": 100,
        "parameters": ["returns", "starting_value"],
        "docstring": "Parameters\n----------\nreturns : pd.Series\n    Daily noncumulative returns.\nstarting_value : float\n    Starting value.",
        "parameter_details": [
            {"name": "returns", "annotation": "", "required": True, "default": ""},
            {"name": "starting_value", "annotation": "float", "required": False, "default": "0"},
        ],
    }

    assert (
        generate_module._function_wrapper_score(
            "cum_returns",
            ["returns", "starting_value"],
            detail,
            100,
            ["pandas", "numpy", "empyrical"],
        )
        is not None
    )


def test_runtime_precheck_timeout_defaults_to_scientific_import_budget(monkeypatch):
    monkeypatch.delenv("CODE2MCP_RUNTIME_PRECHECK_TIMEOUT", raising=False)
    assert generate_module._runtime_precheck_timeout() == 30

    monkeypatch.setenv("CODE2MCP_RUNTIME_PRECHECK_TIMEOUT", "999")
    assert generate_module._runtime_precheck_timeout() == 120


def test_function_wrapper_score_still_rejects_complex_dataframe_params():
    detail = {
        "wrapper_score": 100,
        "parameters": ["positions"],
        "docstring": "Parameters\n----------\npositions : pd.DataFrame\n    Portfolio positions.",
        "parameter_details": [{"name": "positions", "annotation": "", "required": True, "default": ""}],
    }

    assert generate_module._function_wrapper_score("gross_lev", ["positions"], detail, 100, ["pandas"]) is None


def test_tool_signature_adapts_supported_numeric_sequence_params():
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["returns", "starting_value"],
        [
            {"name": "returns", "annotation": "", "required": True, "default": ""},
            {"name": "starting_value", "annotation": "float", "required": False, "default": "0"},
        ],
        "cum_returns",
        {
            "docstring": "Parameters\n----------\nreturns : pd.Series\n    Daily noncumulative returns.",
        },
        ["pandas", "numpy"],
    )

    assert signature == "returns: list = None, starting_value: float = 0"
    assert call_args == "_coerce_numeric_sequence(returns, 'returns'), starting_value"
    assert names == ["returns", "starting_value"]


def test_tool_signature_adapts_scientific_array_params_as_lists():
    detail = {
        "docstring": "Parameters\n----------\nsignal : NDArray[float]\n    Input signal values.",
        "parameter_details": [{"name": "signal", "annotation": "NDArray[float]", "required": True, "default": ""}],
    }

    assert generate_module._function_wrapper_score("signal_mean", ["signal"], detail, 100, ["numpy"]) is not None
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["signal"],
        detail["parameter_details"],
        "signal_mean",
        detail,
        ["numpy"],
    )

    assert signature == "signal: list = None"
    assert call_args == "_coerce_numeric_list(signal, 'signal')"
    assert names == ["signal"]


def test_scientific_array_alias_params_require_type_evidence():
    array_detail = {
        "docstring": "Parameters\n----------\narray : np.ndarray\n    Numeric values to normalize.",
        "parameter_details": [{"name": "array", "annotation": "np.ndarray", "required": True, "default": ""}],
    }
    data_detail = {
        "docstring": "Parameters\n----------\ndata : np.ndarray\n    Numeric samples to transform.",
        "parameter_details": [{"name": "data", "annotation": "np.ndarray", "required": True, "default": ""}],
    }
    dataframe_detail = {
        "docstring": "Parameters\n----------\ndata : pandas.DataFrame\n    Tabular data to transform.",
        "parameter_details": [{"name": "data", "annotation": "pandas.DataFrame", "required": True, "default": ""}],
    }
    values_detail = {
        "docstring": "Parameters\n----------\nvalues : Sequence[float]\n    Numeric values to summarize.",
        "parameter_details": [{"name": "values", "annotation": "Sequence[float]", "required": True, "default": ""}],
    }
    untyped_detail = {
        "docstring": "Parameters\n----------\narray : array_like\n    Arbitrary input.",
        "parameter_details": [{"name": "array", "annotation": "", "required": True, "default": ""}],
    }

    assert generate_module._function_wrapper_score("normalize", ["array"], array_detail, 100, ["numpy"]) is not None
    assert generate_module._function_wrapper_score("summarize_data", ["data"], data_detail, 100, ["numpy"]) is not None
    assert generate_module._function_wrapper_score("summarize_data", ["data"], dataframe_detail, 100, ["pandas"]) is None
    assert generate_module._function_wrapper_score("summarize", ["values"], values_detail, 100, ["numpy"]) is not None
    assert generate_module._function_wrapper_score("normalize", ["array"], untyped_detail, 100, ["numpy"]) is None

    signature, call_args, names = generate_module._tool_signature_and_call(
        ["array", "data", "values"],
        array_detail["parameter_details"] + data_detail["parameter_details"] + values_detail["parameter_details"],
        "normalize",
        {"docstring": array_detail["docstring"] + "\n" + data_detail["docstring"] + "\n" + values_detail["docstring"]},
        ["numpy"],
    )

    assert signature == "array: list = None, data: list = None, values: list = None"
    assert call_args == (
        "_coerce_numeric_list(array, 'array'), _coerce_numeric_list(data, 'data'), "
        "_coerce_numeric_list(values, 'values')"
    )
    assert names == ["array", "data", "values"]


def test_scientific_array_axis_param_uses_integer_evidence():
    typed_detail = {
        "docstring": (
            "Parameters\n----------\n"
            "data : np.ndarray\n    Numeric samples to summarize.\n"
            "axis : int\n    Axis to reduce."
        ),
        "parameter_details": [
            {"name": "data", "annotation": "np.ndarray", "required": True, "default": ""},
            {"name": "axis", "annotation": "int", "required": False, "default": "0"},
        ],
    }
    untyped_axis_detail = {
        "docstring": "Parameters\n----------\ndata : np.ndarray\n    Numeric samples to summarize.",
        "parameter_details": [
            {"name": "data", "annotation": "np.ndarray", "required": True, "default": ""},
            {"name": "axis", "annotation": "", "required": True, "default": ""},
        ],
    }

    assert generate_module._function_wrapper_score("mean_data", ["data", "axis"], typed_detail, 100, ["numpy"]) is not None
    assert (
        generate_module._function_wrapper_score("mean_data", ["data", "axis"], untyped_axis_detail, 100, ["numpy"])
        is None
    )

    signature, call_args, names = generate_module._tool_signature_and_call(
        ["data", "axis"],
        typed_detail["parameter_details"],
        "mean_data",
        typed_detail,
        ["numpy"],
    )

    assert signature == "data: list = None, axis: int = 0"
    assert call_args == "_coerce_numeric_list(data, 'data'), axis"
    assert names == ["data", "axis"]


def test_runtime_value_helper_rejects_non_finite_sequences_and_jsonifies_results():
    namespace = {"json": __import__("json")}

    exec(generate_module._runtime_value_helper_source(), namespace)

    assert namespace["_coerce_numeric_list"](None, "signal") == [0.01, -0.02, 0.015, 0.005, 0.012]

    try:
        namespace["_coerce_numeric_sequence"]([1.0, float("nan")], "returns")
    except ValueError as exc:
        assert "non-finite" in str(exc)
    else:
        raise AssertionError("Expected non-finite sequence values to be rejected")

    assert namespace["_to_jsonable_result"]({"ok": float("inf"), "values": [1.0, float("nan")]}) == {
        "ok": None,
        "values": [1.0, None],
    }


def test_prune_skips_unsupported_placeholder_functions(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "def todo():\n"
        "    raise NotImplementedError\n\n"
        "def empty_pass():\n"
        "    pass\n\n"
        "def empty_ellipsis():\n"
        "    ...\n\n"
        "def doc_only():\n"
        "    \"\"\"Describe future behavior.\"\"\"\n\n"
        "def bare_return():\n"
        "    return\n\n"
        "def empty_return():\n"
        "    return None\n\n"
        "def ok():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["todo", "empty_pass", "empty_ellipsis", "doc_only", "bare_return", "empty_return", "ok"],
                    "classes": [],
                    "function_signatures": {
                        "todo": [],
                        "empty_pass": [],
                        "empty_ellipsis": [],
                        "doc_only": [],
                        "bare_return": [],
                        "empty_return": [],
                        "ok": [],
                    },
                    "wrapper_candidates": [
                        {"name": "todo", "kind": "function", "score": 100},
                        {"name": "empty_pass", "kind": "function", "score": 100},
                        {"name": "empty_ellipsis", "kind": "function", "score": 100},
                        {"name": "doc_only", "kind": "function", "score": 100},
                        {"name": "bare_return", "kind": "function", "score": 100},
                        {"name": "empty_return", "kind": "function", "score": 100},
                        {"name": "ok", "kind": "function", "score": 90},
                    ],
                    "file_path": "api.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["ok"]


def test_prune_skips_empty_default_factory_functions(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "import collections\n"
        "\n"
        "def index_list():\n"
        "    return collections.defaultdict(list)\n"
        "\n"
        "def Enumerator(start=0):\n"
        "    return collections.defaultdict(itertools.count(start).__next__, ())\n"
        "\n"
        "def whole_field(field):\n"
        "    return {field}\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["index_list", "Enumerator", "whole_field"],
                    "classes": [],
                    "function_signatures": {
                        "index_list": [],
                        "Enumerator": ["start"],
                        "whole_field": ["field"],
                    },
                    "function_details": {
                        "index_list": {"parameters": [], "parameter_details": [], "wrapper_score": 100},
                        "Enumerator": {
                            "parameters": ["start"],
                            "parameter_details": [
                                {"name": "start", "annotation": "int", "required": False, "default": "0"}
                            ],
                            "wrapper_score": 100,
                        },
                        "whole_field": {
                            "parameters": ["field"],
                            "parameter_details": [{"name": "field", "annotation": "str", "required": True}],
                            "wrapper_score": 90,
                        },
                    },
                    "wrapper_candidates": [
                        {"name": "index_list", "kind": "function", "score": 100},
                        {"name": "Enumerator", "kind": "function", "score": 100},
                        {"name": "whole_field", "kind": "function", "score": 90},
                    ],
                    "file_path": "api.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=3)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["whole_field"]


def test_function_wrapper_score_rejects_explicit_none_return_annotation():
    assert (
        generate_module._function_wrapper_score(
            "check_file_exist",
            ["filename"],
            {
                "wrapper_score": 100,
                "parameters": ["filename"],
                "return_annotation": "None",
                "parameter_details": [{"name": "filename", "annotation": "str", "required": True}],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_rejects_async_function_details():
    assert (
        generate_module._function_wrapper_score(
            "fetch_value",
            ["query"],
            {
                "wrapper_score": 100,
                "parameters": ["query"],
                "return_annotation": "str",
                "is_async": True,
                "parameter_details": [{"name": "query", "annotation": "str", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "fetch_value",
            ["query"],
            {
                "wrapper_score": 100,
                "parameters": ["query"],
                "return_annotation": "str",
                "risk_reasons": ["async_function"],
                "parameter_details": [{"name": "query", "annotation": "str", "required": True}],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_allows_explicit_params_with_variadic_details():
    detail = {
        "wrapper_score": 80,
        "parameters": ["value"],
        "return_annotation": "int",
        "has_varargs": True,
        "has_kwargs": True,
        "parameter_details": [
            {"name": "value", "kind": "positional", "annotation": "int", "required": True},
            {"name": "args", "kind": "vararg", "annotation": "", "required": False},
            {"name": "kwargs", "kind": "kwarg", "annotation": "", "required": False},
        ],
    }

    assert generate_module._function_wrapper_score("combine", ["value", "args", "kwargs"], detail, 80) is not None


def test_function_wrapper_score_rejects_pure_variadic_details():
    detail = {
        "wrapper_score": 80,
        "parameters": [],
        "return_annotation": "int",
        "has_varargs": True,
        "has_kwargs": True,
        "parameter_details": [
            {"name": "args", "kind": "vararg", "annotation": "", "required": False},
            {"name": "kwargs", "kind": "kwarg", "annotation": "", "required": False},
        ],
    }

    assert generate_module._function_wrapper_score("combine", ["args", "kwargs"], detail, 80) is None


def test_function_wrapper_score_rejects_global_state_dependency():
    assert (
        generate_module._function_wrapper_score(
            "list_recorders",
            ["experiment"],
            {
                "wrapper_score": 100,
                "parameters": ["experiment"],
                "return_annotation": "dict",
                "risk_reasons": ["global_state_dependency"],
                "parameter_details": [{"name": "experiment", "annotation": "str", "required": True}],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_rejects_update_side_effect_names():
    assert (
        generate_module._function_wrapper_score(
            "updateChol",
            ["R_I", "n", "N", "R", "explicitA", "activeSet", "newIndex", "zeroTol"],
            {"wrapper_score": 100},
            100,
            ["numpy", "pandas", "scipy"],
        )
        is None
    )


def test_function_wrapper_score_rejects_analysis_runtime_side_effect_risks():
    for reason in (
        "background_execution",
        "process_execution",
        "network_operation",
        "file_read",
        "file_mutation",
        "framework_entrypoint_decorator",
        "environment_probe_name",
        "operational_tool_name",
    ):
        assert (
            generate_module._function_wrapper_score(
                "load_status",
                ["endpoint"],
                {
                    "wrapper_score": 100,
                    "parameters": ["endpoint"],
                    "parameter_details": [{"name": "endpoint", "annotation": "str", "required": True}],
                    "risk_reasons": [reason],
                },
                100,
            )
            is None
        )


def test_function_wrapper_score_rejects_untyped_opaque_single_letter_params():
    assert (
        generate_module._function_wrapper_score(
            "reduce_list",
            ["L"],
            {
                "wrapper_score": 100,
                "parameters": ["L"],
                "parameter_details": [{"name": "L", "annotation": "", "required": True}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "energy_of_hydrogen_orbital",
            ["n"],
            {
                "wrapper_score": 100,
                "parameters": ["n"],
                "parameter_details": [{"name": "n", "annotation": "", "required": True}],
            },
            100,
        )
        is not None
    )


def test_function_wrapper_score_rejects_opaque_runtime_parameters():
    assert (
        generate_module._function_wrapper_score(
            "get_base_attr",
            ["cls", "name"],
            {
                "wrapper_score": 100,
                "parameters": ["cls", "name"],
                "parameter_details": [
                    {"name": "cls", "annotation": "", "required": True, "default": ""},
                    {"name": "name", "annotation": "", "required": True, "default": ""},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "determine_num_ops",
            ["num_ops", "unop", "binop", "rbinop"],
            {
                "wrapper_score": 100,
                "parameters": ["num_ops", "unop", "binop", "rbinop"],
                "parameter_details": [
                    {"name": "num_ops", "annotation": "", "required": True, "default": ""},
                    {"name": "unop", "annotation": "", "required": True, "default": ""},
                    {"name": "binop", "annotation": "", "required": True, "default": ""},
                    {"name": "rbinop", "annotation": "", "required": True, "default": ""},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "assign_precedences",
            ["precedence_list"],
            {
                "wrapper_score": 100,
                "parameters": ["precedence_list"],
                "parameter_details": [{"name": "precedence_list", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "product",
            ["sequence"],
            {
                "wrapper_score": 100,
                "parameters": ["sequence"],
                "parameter_details": [{"name": "sequence", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "max_degree",
            ["degrees"],
            {
                "wrapper_score": 100,
                "parameters": ["degrees"],
                "parameter_details": [{"name": "degrees", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "sorted_by_count",
            ["seq"],
            {
                "wrapper_score": 100,
                "parameters": ["seq"],
                "parameter_details": [{"name": "seq", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "sorted_by_key",
            ["mapping"],
            {
                "wrapper_score": 100,
                "parameters": ["mapping"],
                "parameter_details": [{"name": "mapping", "annotation": "", "required": True, "default": ""}],
            },
            100,
        )
        is None
    )


def test_financial_series_single_letter_params_use_numeric_adapter():
    detail = {
        "wrapper_score": 100,
        "parameters": ["r", "b"],
        "docstring": "Parameters\n----------\nr : pandas.Series\n    daily return series\nb : pandas.Series\n    baseline return series",
        "parameter_details": [
            {"name": "r", "annotation": "", "required": True, "default": ""},
            {"name": "b", "annotation": "", "required": True, "default": ""},
        ],
    }

    assert generate_module._function_wrapper_score("get_beta", ["r", "b"], detail, 100, ["pandas", "numpy"]) is not None
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["r", "b"],
        detail["parameter_details"],
        "get_beta",
        detail,
        ["pandas", "numpy"],
    )

    assert signature == "r: list = None, b: list = None"
    assert call_args == "_coerce_numeric_sequence(r, 'r'), _coerce_numeric_sequence(b, 'b')"
    assert names == ["r", "b"]


def test_radius_single_letter_param_uses_scalar_signature():
    detail = {
        "wrapper_score": 100,
        "parameters": ["r", "n"],
        "docstring": "compute the n-volume of a sphere of radius r in n dimensions",
        "parameter_details": [
            {"name": "r", "annotation": "", "required": True, "default": ""},
            {"name": "n", "annotation": "", "required": True, "default": ""},
        ],
    }

    assert generate_module._function_wrapper_score("n_volume", ["r", "n"], detail, 100, ["numpy", "scipy"]) is not None
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["r", "n"],
        detail["parameter_details"],
        "n_volume",
        detail,
        ["numpy", "scipy"],
    )

    assert signature == "r: float = 0.0, n: int = 0"
    assert call_args == "r, n"
    assert names == ["r", "n"]


def test_default_radius_single_letter_param_does_not_use_sequence_adapter():
    detail = {
        "wrapper_score": 100,
        "parameters": ["D", "r"],
        "docstring": "convert angular distances to euclidean distances",
        "parameter_details": [
            {"name": "D", "annotation": "", "required": True, "default": ""},
            {"name": "r", "annotation": "", "required": False, "default": "1"},
        ],
    }

    assert (
        generate_module._function_wrapper_score(
            "angular_dist_to_euclidean_dist",
            ["D", "r"],
            detail,
            100,
            ["numpy"],
        )
        is not None
    )
    signature, call_args, names = generate_module._tool_signature_and_call(
        ["D", "r"],
        detail["parameter_details"],
        "angular_dist_to_euclidean_dist",
        detail,
        ["numpy"],
    )

    assert signature == "D: int = 0, r: float = 1"
    assert call_args == "D, r"
    assert names == ["D", "r"]


def test_prune_skips_callable_factory_functions(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "def describe_class(description):\n"
        "    def decorator(cls):\n"
        "        cls.__description__ = description\n"
        "        return cls\n"
        "    return decorator\n\n"
        "def ping():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["describe_class", "ping"],
                    "classes": [],
                    "function_signatures": {"describe_class": ["description"], "ping": []},
                    "wrapper_candidates": [
                        {"name": "describe_class", "kind": "function", "score": 100},
                        {"name": "ping", "kind": "function", "score": 90},
                    ],
                    "file_path": "api.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["ping"]


def test_prune_skips_file_write_and_event_handler_functions(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "keylog.py").write_text(
        "from urllib.request import urlopen\n\n"
        "def log_word(word):\n"
        "    with open('wordlog.txt', 'a') as handle:\n"
        "        handle.write(word)\n\n"
        "def load_status(endpoint):\n"
        "    return urlopen(endpoint).read().decode()\n\n"
        "def on_press(key):\n"
        "    global current_word\n"
        "    current_word = str(key)\n\n"
        "def ping():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "keylog",
                    "module": "keylog",
                    "functions": ["log_word", "load_status", "on_press", "ping"],
                    "classes": [],
                    "function_signatures": {
                        "log_word": ["word"],
                        "load_status": ["endpoint"],
                        "on_press": ["key"],
                        "ping": [],
                    },
                    "wrapper_candidates": [
                        {"name": "log_word", "kind": "function", "score": 100},
                        {"name": "load_status", "kind": "function", "score": 98},
                        {"name": "on_press", "kind": "function", "score": 95},
                        {"name": "ping", "kind": "function", "score": 90},
                    ],
                    "file_path": "keylog.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=3)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["ping"]


def test_prune_skips_framework_entrypoint_decorated_functions(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "@router.post('/items')\n"
        "def create_item(name: str):\n"
        "    return {'name': name}\n\n"
        "def slugify(text: str):\n"
        "    return '-'.join(text.lower().split())\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["create_item", "slugify"],
                    "classes": [],
                    "function_signatures": {"create_item": ["name"], "slugify": ["text"]},
                    "wrapper_candidates": [
                        {"name": "create_item", "kind": "function", "score": 100},
                        {"name": "slugify", "kind": "function", "score": 90},
                    ],
                    "file_path": "api.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["slugify"]


def test_prune_skips_release_and_ci_modules(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    (source / "release").mkdir(parents=True)
    (source / ".ci").mkdir(parents=True)
    (source / "pkg").mkdir(parents=True)
    (source / "release" / "authors.py").write_text("def blue(text):\n    return text\n", encoding="utf-8")
    (source / ".ci" / "parse.py").write_text("def slow_function(name):\n    return name\n", encoding="utf-8")
    (source / "pkg" / "maths.py").write_text("def add(a: int, b: int):\n    return a + b\n", encoding="utf-8")

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "release",
                    "module": "authors",
                    "functions": ["blue"],
                    "classes": [],
                    "function_signatures": {"blue": ["text"]},
                    "file_path": "release/authors.py",
                    "wrapper_candidates": [{"name": "blue", "kind": "function", "score": 100}],
                },
                {
                    "package": ".ci",
                    "module": "parse",
                    "functions": ["slow_function"],
                    "classes": [],
                    "function_signatures": {"slow_function": ["name"]},
                    "file_path": ".ci/parse.py",
                    "wrapper_candidates": [{"name": "slow_function", "kind": "function", "score": 100}],
                },
                {
                    "package": "pkg",
                    "module": "maths",
                    "functions": ["add"],
                    "classes": [],
                    "function_signatures": {"add": ["a", "b"]},
                    "function_details": {
                        "add": {
                            "parameters": ["a", "b"],
                            "parameter_details": [
                                {"name": "a", "annotation": "int"},
                                {"name": "b", "annotation": "int"},
                            ],
                        }
                    },
                    "file_path": "pkg/maths.py",
                    "wrapper_candidates": [{"name": "add", "kind": "function", "score": 90}],
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=3)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["package"] == "pkg"
    assert core_modules[0]["functions"] == ["add"]


def test_prune_skips_compilation_probe_modules(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    (source / "pkg" / "_compilation").mkdir(parents=True)
    (source / "pkg").mkdir(parents=True, exist_ok=True)
    (source / "pkg" / "_compilation" / "availability.py").write_text(
        "def has_cxx():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (source / "pkg" / "maths.py").write_text("def add(a: int, b: int):\n    return a + b\n", encoding="utf-8")

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg._compilation",
                    "module": "availability",
                    "functions": ["has_cxx"],
                    "classes": [],
                    "function_signatures": {"has_cxx": []},
                    "file_path": "pkg/_compilation/availability.py",
                    "wrapper_candidates": [{"name": "has_cxx", "kind": "function", "score": 100}],
                },
                {
                    "package": "pkg",
                    "module": "maths",
                    "functions": ["add"],
                    "classes": [],
                    "function_signatures": {"add": ["a", "b"]},
                    "function_details": {
                        "add": {
                            "parameters": ["a", "b"],
                            "parameter_details": [
                                {"name": "a", "annotation": "int"},
                                {"name": "b", "annotation": "int"},
                            ],
                        }
                    },
                    "file_path": "pkg/maths.py",
                    "wrapper_candidates": [{"name": "add", "kind": "function", "score": 90}],
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=3)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["package"] == "pkg"
    assert core_modules[0]["functions"] == ["add"]


def test_prune_orders_modules_by_global_wrapper_rank(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "lookup.py").write_text(
        "def lookup(address):\n    return address\n",
        encoding="utf-8",
    )
    (source / "dates.py").write_text(
        "def next_full_moon(date):\n    return date\n\n"
        "def next_new_moon(date):\n    return date\n",
        encoding="utf-8",
    )

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "lookup",
                    "module": "lookup",
                    "functions": ["lookup"],
                    "classes": [],
                    "function_signatures": {"lookup": ["address"]},
                    "wrapper_candidates": [{"name": "lookup", "kind": "function", "score": 100}],
                    "file_path": "lookup.py",
                },
                {
                    "package": "dates",
                    "module": "dates",
                    "functions": ["next_full_moon", "next_new_moon"],
                    "classes": [],
                    "function_signatures": {"next_full_moon": ["date"], "next_new_moon": ["date"]},
                    "wrapper_candidates": [
                        {"name": "next_full_moon", "kind": "function", "score": 100},
                        {"name": "next_new_moon", "kind": "function", "score": 100},
                    ],
                    "file_path": "dates.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=3)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["package"] for module in core_modules] == ["dates", "lookup"]
    assert core_modules[0]["functions"] == ["next_full_moon", "next_new_moon"]


def test_prune_deduplicates_selected_tool_names(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "first.py").write_text("def normalize(text):\n    return text\n", encoding="utf-8")
    (source / "second.py").write_text("def normalize(text):\n    return text.lower()\n", encoding="utf-8")

    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "first",
                    "module": "first",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["text"]},
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                    "file_path": "first.py",
                },
                {
                    "package": "second",
                    "module": "second",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["text"]},
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 95}],
                    "file_path": "second.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["package"] == "first"
    assert core_modules[0]["functions"] == ["normalize"]


def test_prune_skips_test_support_modules_from_stale_analysis(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "conftest.py").write_text(
        "def azure_windows():\n    return None\n",
        encoding="utf-8",
    )
    (source / "core.py").write_text(
        "def get_status():\n    return 'ok'\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "conftest",
                    "functions": ["azure_windows"],
                    "classes": [],
                    "function_signatures": {"azure_windows": []},
                    "wrapper_candidates": [{"name": "azure_windows", "kind": "function", "score": 200}],
                    "file_path": "pkg/conftest.py",
                },
                {
                    "package": "pkg",
                    "module": "core",
                    "functions": ["get_status"],
                    "classes": [],
                    "function_signatures": {"get_status": []},
                    "wrapper_candidates": [{"name": "get_status", "kind": "function", "score": 80}],
                    "file_path": "pkg/core.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["core"]
    assert core_modules[0]["functions"] == ["get_status"]


def test_prune_skips_cli_script_modules_from_stale_analysis(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    (source / "bin").mkdir(parents=True)
    (source / "bin" / "tool.py").write_text(
        "def getParser():\n    return None\n",
        encoding="utf-8",
    )
    (source / "api.py").write_text(
        "def get_status():\n    return 'ok'\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "bin",
                    "module": "tool",
                    "functions": ["getParser"],
                    "classes": [],
                    "function_signatures": {"getParser": []},
                    "wrapper_candidates": [{"name": "getParser", "kind": "function", "score": 200}],
                    "file_path": "bin/tool.py",
                },
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["get_status"],
                    "classes": [],
                    "function_signatures": {"get_status": []},
                    "wrapper_candidates": [{"name": "get_status", "kind": "function", "score": 80}],
                    "file_path": "api.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["api"]
    assert core_modules[0]["functions"] == ["get_status"]


def test_prune_skips_generated_artifact_modules_from_stale_analysis(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "def get_status():\n    return 'ok'\n",
        encoding="utf-8",
    )
    artifact_dirs = (
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "deployment",
        "dist",
        "env",
        "histories",
        "history",
        "mcp_output",
        "node_modules",
        "site-packages",
        "venv",
    )
    modules = []
    for index, dirname in enumerate(artifact_dirs):
        artifact_dir = source / dirname
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "fake_module.py").write_text(
            "def fake_tool():\n    return 'generated'\n",
            encoding="utf-8",
        )
        modules.append(
            {
                "package": dirname,
                "module": "fake_module",
                "functions": ["fake_tool"],
                "classes": [],
                "function_signatures": {"fake_tool": []},
                "wrapper_candidates": [{"name": "fake_tool", "kind": "function", "score": 200 - index}],
                "file_path": f"{dirname}/fake_module.py",
            }
        )
    for dirname in ("history", "mcp_output"):
        (source / dirname / "package_only.py").write_text(
            "def package_only_tool():\n    return 'generated'\n",
            encoding="utf-8",
        )
        modules.append(
            {
                "package": dirname,
                "module": "package_only",
                "functions": ["package_only_tool"],
                "classes": [],
                "function_signatures": {"package_only_tool": []},
                "wrapper_candidates": [{"name": "package_only_tool", "kind": "function", "score": 220}],
                "file_path": "",
            }
        )
    modules.append(
        {
            "package": "api",
            "module": "api",
            "functions": ["get_status"],
            "classes": [],
            "function_signatures": {"get_status": []},
            "wrapper_candidates": [{"name": "get_status", "kind": "function", "score": 80}],
            "file_path": "api.py",
        }
    )
    analysis = {"llm_analysis": {"core_modules": modules}}

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=4)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["api"]
    assert core_modules[0]["functions"] == ["get_status"]


def test_prune_skips_modules_with_import_time_side_effects(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    helpers = source / "additional_resources"
    helpers.mkdir(parents=True)
    (helpers / "build_assets.py").write_text(
        "def squeeze_whitespace(text):\n"
        "    return text.strip()\n\n"
        "rows = get_list_from_file('missing.txt')\n"
        "for row in rows:\n"
        "    print(row)\n",
        encoding="utf-8",
    )
    (source / "core.py").write_text(
        "def normalize(score, alpha=15):\n"
        "    return score / alpha\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "additional_resources",
                    "module": "build_assets",
                    "functions": ["squeeze_whitespace"],
                    "classes": [],
                    "function_signatures": {"squeeze_whitespace": ["text"]},
                    "wrapper_candidates": [{"name": "squeeze_whitespace", "kind": "function", "score": 100}],
                    "file_path": "additional_resources/build_assets.py",
                },
                {
                    "package": "core",
                    "module": "core",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["score", "alpha"]},
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                    "file_path": "core.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["core"]
    assert core_modules[0]["functions"] == ["normalize"]


def test_prune_skips_inverted_main_guard_side_effect_modules(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text(
        "def normalize(value):\n"
        "    return value\n\n"
        "if __name__ != '__main__':\n"
        "    initialize_runtime()\n",
        encoding="utf-8",
    )
    (source / "core.py").write_text(
        "def slugify(text):\n"
        "    return '-'.join(text.lower().split())\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["value"]},
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                    "file_path": "api.py",
                },
                {
                    "package": "core",
                    "module": "core",
                    "functions": ["slugify"],
                    "classes": [],
                    "function_signatures": {"slugify": ["text"]},
                    "wrapper_candidates": [{"name": "slugify", "kind": "function", "score": 90}],
                    "file_path": "core.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["module"] == "core"
    assert core_modules[0]["functions"] == ["slugify"]


def test_prune_allows_type_checking_and_regex_initializers(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
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
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "text_utils",
                    "module": "text_utils",
                    "functions": ["strip_punc"],
                    "classes": [],
                    "function_signatures": {"strip_punc": ["text"]},
                    "function_details": {
                        "strip_punc": {
                            "parameters": ["text"],
                            "parameter_details": [{"name": "text", "annotation": "str", "required": True}],
                        }
                    },
                    "wrapper_candidates": [{"name": "strip_punc", "kind": "function", "score": 100}],
                    "file_path": "text_utils.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["text_utils"]
    assert core_modules[0]["functions"] == ["strip_punc"]


def test_prune_allows_qualified_type_checking_guard(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "text_utils.py").write_text(
        "import typing as t\n\n"
        "if t.TYPE_CHECKING:\n"
        "    TypeAlias = build_type_only_alias()\n\n"
        "def normalize(text: str):\n"
        "    return text.strip()\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "text_utils",
                    "module": "text_utils",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["text"]},
                    "function_details": {
                        "normalize": {
                            "parameters": ["text"],
                            "parameter_details": [{"name": "text", "annotation": "str", "required": True}],
                        }
                    },
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                    "file_path": "text_utils.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["text_utils"]
    assert core_modules[0]["functions"] == ["normalize"]


def test_prune_allows_safe_import_compatibility_blocks(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "compat.py").write_text(
        "import logging\n"
        "HAS_PY3 = True\n"
        "if HAS_PY3:\n"
        "    from urllib.parse import urlencode\n"
        "else:\n"
        "    from urllib import urlencode\n\n"
        "try:\n"
        "    import json\n"
        "    AVAILABLE = True\n"
        "except ImportError:\n"
        "    AVAILABLE = False\n\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def annuity(rate: float, years: int):\n"
        "    return rate / (1 - 1 / (1 + rate) ** years)\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "compat",
                    "module": "compat",
                    "functions": ["annuity"],
                    "classes": [],
                    "imports": ["logging", "urllib", "json"],
                    "function_signatures": {"annuity": ["rate", "years"]},
                    "function_details": {
                        "annuity": {
                            "parameters": ["rate", "years"],
                            "parameter_details": [
                                {"name": "rate", "annotation": "float", "required": True},
                                {"name": "years", "annotation": "int", "required": True},
                            ],
                        }
                    },
                    "wrapper_candidates": [{"name": "annuity", "kind": "function", "score": 100}],
                    "file_path": "compat.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["annuity"]


def test_prune_rejects_try_blocks_with_runtime_calls(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "unsafe.py").write_text(
        "try:\n"
        "    DATA = load_remote_data()\n"
        "except Exception:\n"
        "    DATA = []\n\n"
        "def normalize(text: str):\n"
        "    return text.strip()\n",
        encoding="utf-8",
    )
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "unsafe",
                    "module": "unsafe",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["text"]},
                    "function_details": {
                        "normalize": {
                            "parameters": ["text"],
                            "parameter_details": [{"name": "text", "annotation": "str", "required": True}],
                        }
                    },
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                    "file_path": "unsafe.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    assert pruned["llm_analysis"]["core_modules"] == []


def test_module_missing_runtime_imports_ignores_stdlib_on_python39():
    module = {"imports": ["__future__", "collections", "json", "os", "typing", "external_pkg"]}

    missing = generate_module._module_missing_runtime_imports(
        module,
        installed_packages=set(),
        local_roots=set(),
    )

    assert missing == ["external_pkg"]


def test_prune_allows_namedtuple_initializers_with_stdlib_import_filter(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "pileup_like.py").write_text(
        "import collections\n\n"
        "Record = collections.namedtuple('Record', ('code',))\n\n"
        "def encode_genotype(code: str):\n"
        "    return code.upper()\n",
        encoding="utf-8",
    )
    analysis = {
        "_runtime": {
            "env": {
                "dependency_installation": {
                    "strategy": "import_packages",
                    "installed": [],
                }
            }
        },
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pileup_like",
                    "module": "pileup_like",
                    "functions": ["encode_genotype"],
                    "classes": [],
                    "imports": ["collections"],
                    "function_signatures": {"encode_genotype": ["code"]},
                    "function_details": {
                        "encode_genotype": {
                            "parameters": ["code"],
                            "parameter_details": [{"name": "code", "annotation": "str", "required": True}],
                        }
                    },
                    "wrapper_candidates": [{"name": "encode_genotype", "kind": "function", "score": 100}],
                    "file_path": "pileup_like.py",
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["encode_genotype"]


def test_prune_trusts_current_ast_over_stale_side_effect_flags(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "api.py").write_text("def normalize(text: str):\n    return text.strip()\n", encoding="utf-8")
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["normalize"],
                    "classes": [],
                    "import_side_effect_risk": True,
                    "import_side_effect_reasons": ["stale_top_level_assignment_call:line_1"],
                    "function_signatures": {"normalize": ["text"]},
                    "function_details": {
                        "normalize": {
                            "parameters": ["text"],
                            "parameter_details": [{"name": "text", "annotation": "str", "required": True}],
                        }
                    },
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 100}],
                    "file_path": "api.py",
                }
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert len(core_modules) == 1
    assert core_modules[0]["functions"] == ["normalize"]


def test_prune_skips_packaging_helper_files(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "versioneer.py").write_text("def get_version():\n    return '1.0'\n", encoding="utf-8")
    (source / "_version.py").write_text("def get_versions():\n    return {'version': '1.0'}\n", encoding="utf-8")
    (source / "setup.py").write_text("def get_include():\n    return 'include'\n", encoding="utf-8")
    (source / "api.py").write_text("def normalize(text: str):\n    return text.strip()\n", encoding="utf-8")
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "versioneer",
                    "module": "versioneer",
                    "functions": ["get_version"],
                    "classes": [],
                    "function_signatures": {"get_version": []},
                    "wrapper_candidates": [{"name": "get_version", "kind": "function", "score": 200}],
                    "file_path": "versioneer.py",
                },
                {
                    "package": "_version",
                    "module": "_version",
                    "functions": ["get_versions"],
                    "classes": [],
                    "function_signatures": {"get_versions": []},
                    "wrapper_candidates": [{"name": "get_versions", "kind": "function", "score": 190}],
                    "file_path": "_version.py",
                },
                {
                    "package": "setup",
                    "module": "setup",
                    "functions": ["get_include"],
                    "classes": [],
                    "function_signatures": {"get_include": []},
                    "wrapper_candidates": [{"name": "get_include", "kind": "function", "score": 180}],
                    "file_path": "setup.py",
                },
                {
                    "package": "api",
                    "module": "api",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": ["text"]},
                    "function_details": {
                        "normalize": {
                            "parameters": ["text"],
                            "parameter_details": [{"name": "text", "annotation": "str", "required": True}],
                        }
                    },
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 80}],
                    "file_path": "api.py",
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=4)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["api"]
    assert core_modules[0]["functions"] == ["normalize"]


def test_function_wrapper_score_rejects_network_object_params():
    assert (
        generate_module._function_wrapper_score(
            "get_bus_counts",
            ["n"],
            {
                "wrapper_score": 100,
                "parameters": ["n"],
                "docstring": "Parameters\n----------\nn : Network\n    The network to analyze.",
                "parameter_details": [
                    {"name": "n", "annotation": "Network", "required": True},
                ],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_allows_numeric_distance_params():
    assert (
        generate_module._function_wrapper_score(
            "h_chain",
            ["n_h", "bond_distance", "charge"],
            {
                "wrapper_score": 100,
                "parameters": ["n_h", "bond_distance", "charge"],
                "parameter_details": [
                    {"name": "n_h", "annotation": "", "required": False, "default": "4"},
                    {"name": "bond_distance", "annotation": "", "required": False, "default": "0.8"},
                    {"name": "charge", "annotation": "", "required": False, "default": "0"},
                ],
            },
            100,
        )
        is not None
    )

    assert (
        generate_module._function_wrapper_score(
            "mixture_rvs",
            ["prob", "size", "dist"],
            {"wrapper_score": 100},
            100,
        )
        is None
    )


def test_function_wrapper_score_allows_iteration_count_params():
    detail = {
        "wrapper_score": 100,
        "parameters": ["original_query", "max_iter"],
        "parameter_details": [
            {"name": "original_query", "annotation": "str", "required": True},
            {"name": "max_iter", "annotation": "int", "required": False, "default": "3"},
        ],
    }

    assert (
        generate_module._function_wrapper_score(
            "query",
            ["original_query", "max_iter"],
            detail,
            100,
            [],
        )
        is not None
    )

    assert (
        generate_module._function_wrapper_score(
            "iterate",
            ["iter"],
            {
                "wrapper_score": 100,
                "parameters": ["iter"],
                "parameter_details": [{"name": "iter", "annotation": "", "required": True}],
            },
            100,
            [],
        )
        is None
    )


def test_function_wrapper_score_rejects_stream_object_params():
    assert (
        generate_module._function_wrapper_score(
            "merge_previews",
            ["stream"],
            {
                "wrapper_score": 100,
                "parameters": ["stream"],
                "docstring": ":param stream: Stream object to be merged",
                "parameter_details": [
                    {"name": "stream", "annotation": "", "required": True},
                ],
            },
            100,
        )
        is None
    )


def test_allowed_tool_names_preserve_trailing_underscore_functions():
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "checks",
                    "functions": ["check_dtypes_"],
                    "classes": [],
                }
            ]
        }
    }

    allowed = generate_module._allowed_tool_names_from_analysis(analysis)

    assert "check_dtypes_" in allowed
    assert "check_dtypes" in allowed


def test_allowed_tool_names_prefer_wrapper_candidates_when_available():
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["safe_value", "debug_helper"],
                    "classes": ["Usable", "Internal"],
                    "wrapper_candidates": [
                        {"name": "safe_value", "kind": "function", "score": 100},
                        {"name": "Usable", "kind": "class", "score": 90},
                    ],
                }
            ]
        }
    }

    allowed = generate_module._allowed_tool_names_from_analysis(analysis)

    assert "safe_value" in allowed
    assert "usable" in allowed
    assert "debug_helper" not in allowed
    assert "internal" not in allowed


def test_allowed_tool_names_respect_empty_wrapper_candidates():
    analysis = {
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "tools",
                    "functions": ["debug_helper"],
                    "classes": ["Internal"],
                    "wrapper_candidates": [],
                }
            ]
        }
    }

    allowed = generate_module._allowed_tool_names_from_analysis(analysis)

    assert allowed == {"core"}


def test_function_wrapper_score_rejects_component_object_params():
    assert (
        generate_module._function_wrapper_score(
            "check_cost_consistency",
            ["component", "strict"],
            {
                "wrapper_score": 100,
                "parameters": ["component", "strict"],
                "docstring": "component : pypsa.Component\n    The component to check.",
                "parameter_details": [
                    {"name": "component", "annotation": "Components", "required": True},
                    {"name": "strict", "annotation": "bool", "required": False, "default": "False"},
                ],
            },
            100,
        )
        is None
    )


def test_function_wrapper_score_rejects_molecule_object_params():
    assert (
        generate_module._function_wrapper_score(
            "serialize_action",
            ["action", "molecule_store"],
            {
                "wrapper_score": 100,
                "parameters": ["action", "molecule_store"],
                "parameter_details": [
                    {"name": "action", "annotation": "RetroReaction", "required": True},
                    {"name": "molecule_store", "annotation": "MoleculeSerializer", "required": True},
                ],
            },
            100,
        )
        is None
    )
    assert (
        generate_module._function_wrapper_score(
            "describe_molecule",
            ["molecule"],
            {
                "wrapper_score": 100,
                "parameters": ["molecule"],
                "parameter_details": [{"name": "molecule", "annotation": "Molecule", "required": True}],
            },
            100,
        )
        is None
    )


def test_fallback_import_uses_source_when_installed_module_lacks_symbols(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    plugin_dir = repo_root / "mcp_output" / "mcp_plugin"
    source_pkg = repo_root / "source" / "demo_pkg"
    fake_site_pkg = tmp_path / "fake_site" / "demo_pkg"
    plugin_dir.mkdir(parents=True)
    source_pkg.mkdir(parents=True)
    fake_site_pkg.mkdir(parents=True)
    (source_pkg / "__init__.py").write_text("", encoding="utf-8")
    (source_pkg / "api.py").write_text("def wanted():\n    return 'source-version'\n", encoding="utf-8")
    (fake_site_pkg / "__init__.py").write_text("", encoding="utf-8")
    (fake_site_pkg / "api.py").write_text("def other():\n    return 'installed-version'\n", encoding="utf-8")
    (fake_site_pkg / "other.py").write_text("def other():\n    return 'installed-version'\n", encoding="utf-8")
    (tmp_path / "fake_site" / "fastmcp.py").write_text(
        "class FastMCP:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def tool(self, **kwargs):\n"
        "        def decorate(func):\n"
        "            return func\n"
        "        return decorate\n",
        encoding="utf-8",
    )

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
        "llm_analysis": {
            "import_strategy": {"primary": "blackbox"},
            "core_modules": [
                {
                    "package": "demo_pkg",
                    "module": "api",
                    "functions": ["wanted"],
                    "classes": [],
                    "function_signatures": {"wanted": []},
                    "file_path": "demo_pkg/api.py",
                },
                {
                    "package": "demo_pkg",
                    "module": "other",
                    "functions": ["other"],
                    "classes": [],
                    "function_signatures": {"other": []},
                    "file_path": "demo_pkg/other.py",
                },
            ],
        },
    }
    service_path = plugin_dir / "mcp_service.py"
    service_path.write_text(generate_module._generate_mcp_service_fallback(analysis), encoding="utf-8")

    monkeypatch.syspath_prepend(str(tmp_path / "fake_site"))
    for module_name in ["demo_pkg", "demo_pkg.api", "mcp_service"]:
        sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location("mcp_service", service_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_service"] = module
    spec.loader.exec_module(module)

    assert module.wanted() == {"success": True, "result": "source-version", "error": None}
    assert module.other() == {"success": True, "result": "installed-version", "error": None}


def test_prune_skips_runtime_unavailable_modules(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "broken.py").write_text(
        "from missing_runtime_dependency import value\n\n"
        "def usable():\n"
        "    return value\n",
        encoding="utf-8",
    )
    (source / "safe.py").write_text(
        "def available():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    analysis = {
        "_runtime": {"env": {"exec_prefix": [sys.executable]}},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "broken",
                    "functions": ["usable"],
                    "classes": [],
                    "function_signatures": {"usable": []},
                    "wrapper_candidates": [{"name": "usable", "kind": "function", "score": 200}],
                    "file_path": "pkg/broken.py",
                },
                {
                    "package": "pkg",
                    "module": "safe",
                    "functions": ["available"],
                    "classes": [],
                    "function_signatures": {"available": []},
                    "wrapper_candidates": [{"name": "available", "kind": "function", "score": 80}],
                    "file_path": "pkg/safe.py",
                },
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["safe"]
    assert core_modules[0]["functions"] == ["available"]


def test_prune_skips_modules_with_missing_runtime_import_packages(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source" / "pkg"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "requires_cobra.py").write_text(
        "def compute_gene_score():\n    return 1\n",
        encoding="utf-8",
    )
    (source / "safe_math.py").write_text(
        "def normalize_vector():\n    return 1\n",
        encoding="utf-8",
    )
    analysis = {
        "_runtime": {
            "env": {
                "dependency_installation": {
                    "strategy": "import_packages",
                    "installed": ["numpy", "pandas"],
                }
            }
        },
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "pkg",
                    "module": "requires_cobra",
                    "functions": ["compute_gene_score"],
                    "classes": [],
                    "function_signatures": {"compute_gene_score": []},
                    "wrapper_candidates": [{"name": "compute_gene_score", "kind": "function", "score": 200}],
                    "file_path": "pkg/requires_cobra.py",
                    "imports": ["cobra", "numpy"],
                },
                {
                    "package": "pkg",
                    "module": "safe_math",
                    "functions": ["normalize_vector"],
                    "classes": [],
                    "function_signatures": {"normalize_vector": []},
                    "wrapper_candidates": [{"name": "normalize_vector", "kind": "function", "score": 80}],
                    "file_path": "pkg/safe_math.py",
                    "imports": ["numpy"],
                },
            ]
        }
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["safe_math"]
    assert core_modules[0]["functions"] == ["normalize_vector"]


def test_runtime_precheck_handles_package_init_parent_paths(tmp_path):
    repo_root = tmp_path / "repo"
    dateutil_pkg = repo_root / "source" / "src" / "dateutil"
    zoneinfo_pkg = dateutil_pkg / "zoneinfo"
    tz_pkg = dateutil_pkg / "tz"
    zoneinfo_pkg.mkdir(parents=True)
    tz_pkg.mkdir(parents=True)
    (dateutil_pkg / "__init__.py").write_text("", encoding="utf-8")
    (tz_pkg / "__init__.py").write_text("TZ_VALUE = 'ok'\n", encoding="utf-8")
    (zoneinfo_pkg / "__init__.py").write_text(
        "from dateutil.tz import TZ_VALUE\n\n"
        "def get_zonefile_instance(new_instance=False):\n"
        "    return TZ_VALUE\n",
        encoding="utf-8",
    )
    analysis = {
        "_runtime": {"env": {"exec_prefix": [sys.executable]}},
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "src.dateutil",
                    "module": "zoneinfo",
                    "functions": ["get_zonefile_instance"],
                    "classes": [],
                    "function_signatures": {"get_zonefile_instance": ["new_instance"]},
                    "function_details": {
                        "get_zonefile_instance": {
                            "parameters": ["new_instance"],
                            "parameter_details": [
                                {"name": "new_instance", "kind": "positional", "annotation": "", "required": False, "default": "False"}
                            ],
                            "wrapper_score": 100,
                        }
                    },
                    "wrapper_candidates": [{"name": "get_zonefile_instance", "kind": "function", "score": 100}],
                    "file_path": "src/dateutil/zoneinfo/__init__.py",
                }
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["zoneinfo"]
    assert core_modules[0]["functions"] == ["get_zonefile_instance"]


def test_prune_skips_runtime_rejected_tools_on_regeneration(tmp_path):
    repo_root = tmp_path / "repo"
    source = repo_root / "source"
    source.mkdir(parents=True)
    (source / "bad.py").write_text("def normalize():\n    return 'bad'\n", encoding="utf-8")
    (source / "good.py").write_text("def slugify(text):\n    return text.lower()\n", encoding="utf-8")
    analysis = {
        "_runtime_rejected_tools": [{"name": "normalize", "reason": "semantic failure"}],
        "llm_analysis": {
            "core_modules": [
                {
                    "package": "bad",
                    "module": "bad",
                    "functions": ["normalize"],
                    "classes": [],
                    "function_signatures": {"normalize": []},
                    "wrapper_candidates": [{"name": "normalize", "kind": "function", "score": 200}],
                    "file_path": "bad.py",
                },
                {
                    "package": "good",
                    "module": "good",
                    "functions": ["slugify"],
                    "classes": [],
                    "function_signatures": {"slugify": ["text"]},
                    "wrapper_candidates": [{"name": "slugify", "kind": "function", "score": 80}],
                    "file_path": "good.py",
                },
            ]
        },
    }

    pruned = generate_module._prune_analysis_for_generation(analysis, str(repo_root), max_total=2)

    core_modules = pruned["llm_analysis"]["core_modules"]
    assert [module["module"] for module in core_modules] == ["good"]
    assert core_modules[0]["functions"] == ["slugify"]
