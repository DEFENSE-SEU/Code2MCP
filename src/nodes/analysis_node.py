# Analysis Node - Use gitingest, LLM, and DeepWiki to analyze repository structure
from __future__ import annotations
import ast
import os
import json
import re
import subprocess
import sys
import tempfile
from typing import Dict, Any, List
from ..utils import setup_logging, get_llm_service, write_file, fetch_deepwiki, clean_env_value, sanitize_deepwiki_content
from ..tools.gitingest_client import GitingestClient
from ..tools.deepwiki_client import get_deepwiki_client
from ..security.tool_policy import (
    OPTIONAL_PLOTTING_TOOL_TOKENS,
    OUTPUT_ONLY_TOOL_TOKENS,
    REMOTE_LOOKUP_TOOL_TOKENS,
    looks_resource_parameter,
    looks_sensitive_parameter,
)

logger = setup_logging()
_AST_FALLBACK_CANDIDATES: list[tuple[list[str], str]] | None = None

EXCLUDED_SOURCE_DIRS = {
    ".cache",
    ".eggs",
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "benchmark",
    "benchmarks",
    "bin",
    "build",
    "cli",
    "deployment",
    "dist",
    "doc",
    "docs",
    "env",
    "example",
    "examples",
    "generated",
    "histories",
    "history",
    "mcp_output",
    "node_modules",
    "sample",
    "samples",
    "script",
    "scripts",
    "site-packages",
    "test",
    "tests",
    "tutorial",
    "tutorials",
    ".venv",
    "venv",
}
EXCLUDED_SOURCE_FILES = {"conftest.py"}
EXCLUDED_NAME_PARTS = ("test", "example", "demo", "benchmark")
OPERATIONAL_WRAPPER_NAME_PARTS = set(
    "append attach build create delete download ensure fit install monkey patch post rebuild remove "
    "save send train update upload write".split()
)
EXECUTION_WRAPPER_NAME_PARTS = {"cmd", "command", "execute", "popen", "run", "shell", "subprocess", "system"}
STATEFUL_WRAPPER_NAME_PARTS = {"clear", "close", "kill", "launch", "reset", "shutdown", "start", "stop"}
CONNECTION_WRAPPER_NAME_PARTS = {"connect", "connection", "database", "handler", "hook", "logger", "mongodb", "redis"}
ENVIRONMENT_PROBE_WRAPPER_NAMES = set(
    "array_type data_path get_config get_include get_libraries get_library_dirs get_user_config_file "
    "get_versions has_c has_cpp has_cuda has_cxx has_fortran has_gpu list_engines package_path".split()
)
ENVIRONMENT_PROBE_WRAPPER_NAME_PARTS = {"availability", "backend", "compilation", "compiler"}
PLOTTING_WRAPPER_NAME_PARTS = {"plot", "plots", "plotly"} | OPTIONAL_PLOTTING_TOOL_TOKENS
OUTPUT_ONLY_WRAPPER_NAME_PARTS = OUTPUT_ONLY_TOOL_TOKENS
REMOTE_LOOKUP_WRAPPER_NAME_PARTS = REMOTE_LOOKUP_TOOL_TOKENS
COMMON_IMPORT_PACKAGE_MAP = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "empyrical": "empyrical",
    "igraph": "igraph",
    "IPython": "ipython",
    "matplotlib": "matplotlib",
    "networkx": "networkx",
    "natsort": "natsort",
    "numpy": "numpy",
    "pandas": "pandas",
    "PIL": "pillow",
    "pynput": "pynput",
    "pytz": "pytz",
    "requests": "requests",
    "scipy": "scipy",
    "SimpleITK": "SimpleITK",
    "statsmodels": "statsmodels",
    "sklearn": "scikit-learn",
    "tqdm": "tqdm",
    "yaml": "pyyaml",
}
LOCAL_SCAN_TEXT_EXTS = {
    ".cfg",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
DANGEROUS_INTERACTIVE_IMPORTS = {"keyboard", "pynput"}
UNSAFE_DYNAMIC_CODE_CALLS = {"builtins.compile", "builtins.eval", "builtins.exec", "compile", "eval", "exec"}
UNSAFE_PROCESS_CALLS = {
    "compile_run_strings",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.fork",
    "os.forkpty",
    "os.popen",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
    "os.startfile",
    "os.system",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "subprocess.popen",
    "subprocess.run",
    "webbrowser.open",
    "webbrowser.open_new",
    "webbrowser.open_new_tab",
}
UNSAFE_BACKGROUND_EXECUTION_CALLS = {
    "_thread.start_new_thread",
    "asyncio.create_task",
    "asyncio.ensure_future",
    "asyncio.run_coroutine_threadsafe",
    "thread.start_new_thread",
    "multiprocessing.process.start",
    "threading.thread.start",
    "threading.timer.start",
}
RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS = {
    "concurrent.futures.processpoolexecutor",
    "concurrent.futures.threadpoolexecutor",
    "multiprocessing.pool",
    "multiprocessing.process",
    "threading.thread",
    "threading.timer",
}
RUNTIME_BACKGROUND_EXECUTION_METHODS = {
    "apply",
    "apply_async",
    "imap",
    "imap_unordered",
    "map",
    "map_async",
    "starmap",
    "starmap_async",
    "start",
    "submit",
}
UNSAFE_PROCESS_STATE_MUTATION_CALLS = {
    "atexit.register",
    "atexit.unregister",
    "logging.basicconfig",
    "logging.config.dictconfig",
    "logging.config.fileconfig",
    "os.chdir",
    "os.chroot",
    "os.fchdir",
    "os.nice",
    "os.setegid",
    "os.seteuid",
    "os.setgid",
    "os.setgroups",
    "os.setpgid",
    "os.setpgrp",
    "os.setsid",
    "os.setuid",
    "os.umask",
    "signal.signal",
    "warnings.filterwarnings",
    "warnings.resetwarnings",
    "warnings.simplefilter",
}
RUNTIME_PROCESS_STATE_MUTATION_TARGETS = {
    "sys.meta_path",
    "sys.modules",
    "sys.path",
    "sys.path_hooks",
    "sys.path_importer_cache",
}
RUNTIME_PROCESS_STATE_MUTATION_METHODS = {
    "__delitem__",
    "__iadd__",
    "__ior__",
    "__setitem__",
    "append",
    "clear",
    "extend",
    "insert",
    "pop",
    "popitem",
    "remove",
    "reverse",
    "setdefault",
    "sort",
    "update",
}
UNSAFE_NETWORK_CALLS = {
    "aiohttp.request",
    "httpx.delete",
    "httpx.get",
    "httpx.head",
    "httpx.options",
    "httpx.patch",
    "httpx.post",
    "httpx.put",
    "httpx.request",
    "httpx.stream",
    "requests.delete",
    "requests.get",
    "requests.head",
    "requests.options",
    "requests.patch",
    "requests.post",
    "requests.put",
    "requests.request",
    "socket.create_connection",
    "socket.create_server",
    "urllib.request.urlretrieve",
    "urllib.request.urlopen",
    "urllib3.request",
}
RUNTIME_NETWORK_CLIENT_CONSTRUCTORS = {
    "aiohttp.clientsession",
    "ftplib.ftp",
    "ftplib.ftp_tls",
    "http.client.httpconnection",
    "http.client.httpsconnection",
    "httpx.asyncclient",
    "httpx.client",
    "imaplib.imap4",
    "imaplib.imap4_ssl",
    "mysql.connector.connect",
    "poplib.pop3",
    "poplib.pop3_ssl",
    "psycopg.connect",
    "psycopg2.connect",
    "pymongo.mongoclient",
    "redis.from_url",
    "redis.redis",
    "redis.strictredis",
    "requests.session",
    "requests.sessions.session",
    "smtplib.smtp",
    "smtplib.smtp_ssl",
    "sqlalchemy.create_engine",
    "sqlalchemy.engine.create_engine",
    "telnetlib.telnet",
    "urllib.request.build_opener",
    "urllib3.poolmanager",
    "urllib3.proxymanager",
    "xmlrpc.client.serverproxy",
}
RUNTIME_NETWORK_CLIENT_METHODS = {
    "command",
    "commit",
    "connect",
    "cursor",
    "delete_one",
    "execute",
    "executemany",
    "fetch",
    "find",
    "find_one",
    "get",
    "getresponse",
    "insert_one",
    "login",
    "open",
    "ping",
    "query",
    "request",
    "retrbinary",
    "rollback",
    "search",
    "send",
    "sendmail",
    "set",
    "storbinary",
    "update_one",
    "write",
}
RUNTIME_NETWORK_SOCKET_CONSTRUCTORS = {"socket.socket"}
RUNTIME_NETWORK_SOCKET_METHODS = {
    "accept",
    "bind",
    "connect",
    "connect_ex",
    "listen",
    "recv",
    "recv_into",
    "recvfrom",
    "recvfrom_into",
    "send",
    "sendall",
    "sendmsg",
    "sendto",
}
RUNTIME_NETWORK_SERVER_CONSTRUCTORS = {
    "http.server.httpserver",
    "http.server.threadinghttpserver",
    "socketserver.tcpserver",
    "socketserver.threadingtcpserver",
    "socketserver.threadingudpserver",
    "socketserver.udpserver",
    "wsgiref.simple_server.make_server",
}
RUNTIME_NETWORK_SERVER_METHODS = {
    "handle_request",
    "serve_forever",
    "server_activate",
    "server_bind",
}
UNSAFE_FILE_MUTATION_CALLS = {
    "dbm.dumb.open",
    "dbm.gnu.open",
    "dbm.ndbm.open",
    "dbm.open",
    "os.chmod",
    "os.chown",
    "os.link",
    "os.makedirs",
    "os.mkdir",
    "os.remove",
    "os.rename",
    "os.replace",
    "os.rmdir",
    "os.symlink",
    "os.unlink",
    "os.utime",
    "shutil.chown",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.copyfileobj",
    "shutil.copymode",
    "shutil.copystat",
    "shutil.copytree",
    "shutil.make_archive",
    "shutil.move",
    "shutil.rmtree",
    "shelve.open",
    "tempfile.mkdtemp",
    "tempfile.mkstemp",
    "tempfile.namedtemporaryfile",
    "tempfile.spooledtemporaryfile",
    "tempfile.temporarydirectory",
    "tempfile.temporaryfile",
}
UNSAFE_FILE_READ_CALLS = {
    "bz2.open",
    "configparser.configparser.read",
    "fileinput.fileinput",
    "fileinput.fileinput.input",
    "fileinput.input",
    "glob.glob",
    "glob.iglob",
    "gzip.open",
    "h5py.file",
    "joblib.load",
    "lzma.open",
    "numpy.load",
    "numpy.loadtxt",
    "numpy.genfromtxt",
    "numpy.fromfile",
    "numpy.memmap",
    "os.lstat",
    "os.listdir",
    "os.path.exists",
    "os.path.getatime",
    "os.path.getctime",
    "os.path.getmtime",
    "os.path.getsize",
    "os.path.isdir",
    "os.path.isfile",
    "os.path.islink",
    "os.path.ismount",
    "os.path.lexists",
    "os.path.samefile",
    "os.readlink",
    "os.scandir",
    "os.stat",
    "os.statvfs",
    "os.walk",
    "pandas.read_csv",
    "pandas.read_excel",
    "pandas.read_feather",
    "pandas.read_hdf",
    "pandas.read_json",
    "pandas.read_orc",
    "pandas.read_parquet",
    "pandas.read_pickle",
    "pandas.read_sas",
    "pandas.read_stata",
    "pathlib.path.read_bytes",
    "pathlib.path.read_text",
    "pathlib.path.exists",
    "pathlib.path.glob",
    "pathlib.path.group",
    "pathlib.path.is_block_device",
    "pathlib.path.is_char_device",
    "pathlib.path.is_dir",
    "pathlib.path.is_fifo",
    "pathlib.path.is_file",
    "pathlib.path.is_mount",
    "pathlib.path.is_socket",
    "pathlib.path.is_symlink",
    "pathlib.path.iterdir",
    "pathlib.path.lstat",
    "pathlib.path.owner",
    "pathlib.path.rglob",
    "pathlib.path.readlink",
    "pathlib.path.samefile",
    "pathlib.path.stat",
    "pathlib.path.walk",
    "pickle.load",
    "polars.read_csv",
    "polars.read_excel",
    "polars.read_ipc",
    "polars.read_json",
    "polars.read_parquet",
    "scipy.io.loadmat",
    "tarfile.open",
    "linecache.getline",
    "linecache.getlines",
    "tokenize.open",
    "torch.load",
    "zipfile.zipfile",
}
OS_OPEN_FILE_MUTATION_FLAGS = {
    "os.o_append",
    "os.o_creat",
    "os.o_excl",
    "os.o_rdwr",
    "os.o_trunc",
    "os.o_wronly",
}
OS_OPEN_FILE_MUTATION_FLAG_VALUES = tuple(
    value
    for value in (
        getattr(os, "O_APPEND", None),
        getattr(os, "O_CREAT", None),
        getattr(os, "O_EXCL", None),
        getattr(os, "O_RDWR", None),
        getattr(os, "O_TRUNC", None),
        getattr(os, "O_WRONLY", None),
    )
    if isinstance(value, int)
)
MODE_SENSITIVE_FILE_OPEN_CALLS = {
    "bz2.open",
    "builtins.open",
    "gzip.open",
    "h5py.file",
    "io.fileio",
    "io.open",
    "lzma.open",
    "open",
    "os.fdopen",
    "pathlib.path.open",
    "tarfile.open",
    "zipfile.zipfile",
}
RUNTIME_PATH_OBJECT_RETURNING_METHODS = {
    "absolute",
    "expanduser",
    "joinpath",
    "relative_to",
    "resolve",
    "with_name",
    "with_stem",
    "with_suffix",
}
RUNTIME_PATH_OBJECT_RETURNING_ATTRIBUTES = {"parent"}
RUNTIME_PATH_SEQUENCE_ATTRIBUTES = {"parents"}
RUNTIME_ALIAS_MODULES = {
    "_thread",
    "aiohttp",
    "atexit",
    "asyncio",
    "builtins",
    "bz2",
    "concurrent.futures",
    "configparser",
    "dbm",
    "dbm.dumb",
    "dbm.gnu",
    "dbm.ndbm",
    "fileinput",
    "functools",
    "glob",
    "gzip",
    "h5py",
    "ftplib",
    "http.client",
    "http.server",
    "httpx",
    "imaplib",
    "importlib",
    "io",
    "joblib",
    "linecache",
    "logging",
    "lzma",
    "multiprocessing",
    "mysql.connector",
    "numpy",
    "os",
    "os.path",
    "pandas",
    "pathlib",
    "pickle",
    "polars",
    "poplib",
    "psycopg",
    "psycopg2",
    "pymongo",
    "redis",
    "requests",
    "requests.sessions",
    "scipy.io",
    "shutil",
    "signal",
    "socket",
    "socketserver",
    "shelve",
    "smtplib",
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlite3",
    "subprocess",
    "sys",
    "tarfile",
    "telnetlib",
    "tempfile",
    "threading",
    "tokenize",
    "torch",
    "urllib.request",
    "urllib3",
    "warnings",
    "webbrowser",
    "wsgiref.simple_server",
    "xmlrpc.client",
    "zipfile",
}
RUNTIME_PATH_LITERAL_EXTENSIONS = {
    ".bz2",
    ".cfg",
    ".conf",
    ".csv",
    ".db",
    ".feather",
    ".gif",
    ".gz",
    ".htm",
    ".html",
    ".h5",
    ".hdf",
    ".hdf5",
    ".ini",
    ".joblib",
    ".json",
    ".jsonl",
    ".mat",
    ".md",
    ".npy",
    ".npz",
    ".parquet",
    ".pickle",
    ".pkl",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".svg",
    ".pt",
    ".pth",
    ".safetensors",
    ".tar",
    ".tex",
    ".tif",
    ".tiff",
    ".toml",
    ".tsv",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
    ".xz",
    ".yaml",
    ".yml",
    ".webp",
    ".zip",
}
OPAQUE_WRAPPER_PARAM_NAMES = {
    "self",
    "cls",
    "binop",
    "rbinop",
    "mapping",
    "mappings",
    "precedence_list",
    "degrees",
    "seq",
    "sequence",
}
COMPLEX_RUNTIME_WRAPPER_PARAM_NAMES = {
    "app",
    "callback",
    "callbacks",
    "client",
    "config",
    "configs",
    "connection",
    "context",
    "cursor",
    "dataframe",
    "dataset",
    "df",
    "executor",
    "handler",
    "model",
    "models",
    "namespace",
    "parser",
    "request",
    "response",
    "session",
    "tensor",
}


def _runtime_call_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                canonical = alias.name
                if canonical in RUNTIME_ALIAS_MODULES:
                    if alias.asname:
                        aliases[alias.asname.lower()] = canonical
                    elif "." not in canonical:
                        aliases[canonical.lower()] = canonical
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in RUNTIME_ALIAS_MODULES:
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[(alias.asname or alias.name).lower()] = f"{node.module}.{alias.name}"
    return aliases


def _resolve_runtime_call_name(call_name: str, aliases: dict[str, str] | None = None) -> str:
    call_lower = str(call_name or "").lower()
    aliases = aliases or {}
    if call_lower in aliases:
        return aliases[call_lower].lower()
    if "." not in call_lower:
        return call_lower
    root, rest = call_lower.split(".", 1)
    if root in aliases:
        alias_target = aliases[root].lower()
        first, _, tail = rest.partition(".")
        if "." in alias_target and alias_target.rsplit(".", 1)[-1] == first:
            return f"{alias_target}.{tail}" if tail else alias_target
        return f"{alias_target}.{rest}"
    return call_lower


def _literal_getattr_runtime_call_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(call, ast.Call) or _call_name(call.func) != "getattr" or len(call.args) < 2:
        return ""
    attr = call.args[1]
    if not isinstance(attr, ast.Constant) or not isinstance(attr.value, str) or not attr.value:
        return ""
    root = _call_name(call.args[0])
    if not root:
        return ""
    return _resolve_runtime_call_name(f"{root}.{attr.value}", runtime_call_aliases)


def _literal_getattr_attribute_runtime_call_name(
    func: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    attrs: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    base = _literal_getattr_runtime_call_name(node if isinstance(node, ast.Call) else None, runtime_call_aliases)
    if not base or not attrs:
        return ""
    return _resolve_runtime_call_name(".".join([base, *reversed(attrs)]), runtime_call_aliases)


def _literal_partial_runtime_call_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if (
        not isinstance(call, ast.Call)
        or _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases) != "functools.partial"
        or not call.args
    ):
        return ""
    target = call.args[0]
    return (
        _literal_getattr_attribute_runtime_call_name(target, runtime_call_aliases)
        or _literal_getattr_runtime_call_name(target if isinstance(target, ast.Call) else None, runtime_call_aliases)
        or _resolve_runtime_call_name(
            _call_name(target),
            runtime_call_aliases,
        )
    )


def _literal_dynamic_import_module_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(call, ast.Call) or not call.args:
        return ""
    call_lower = _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases)
    if call_lower not in {"__import__", "builtins.__import__", "importlib.import_module"}:
        return ""
    module_arg = call.args[0]
    if not isinstance(module_arg, ast.Constant) or not isinstance(module_arg.value, str):
        return ""
    module_name = module_arg.value.strip()
    if module_name not in RUNTIME_ALIAS_MODULES:
        return ""
    return module_name


def _literal_dynamic_import_runtime_call_name(
    func: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    attrs: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    module_name = _literal_dynamic_import_module_name(node if isinstance(node, ast.Call) else None, runtime_call_aliases)
    if not module_name or not attrs:
        return ""
    return _resolve_runtime_call_name(".".join([module_name, *reversed(attrs)]), runtime_call_aliases)


def _path_object_returning_call_name(
    call: ast.Call | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(call, ast.Call):
        return ""
    call_lower = _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases)
    if call_lower in {"pathlib.path", "pathlib.path.cwd", "pathlib.path.home"}:
        return "pathlib.path"
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr.lower() in RUNTIME_PATH_OBJECT_RETURNING_METHODS
        and _node_resolves_to_path_object(call.func.value, runtime_call_aliases)
    ):
        return "pathlib.path"
    return ""


def _node_resolves_to_path_object(
    node: ast.AST | None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> bool:
    if isinstance(node, ast.Name):
        return _resolve_runtime_call_name(node.id, runtime_call_aliases) == "pathlib.path"
    if isinstance(node, ast.Call):
        return bool(_path_object_returning_call_name(node, runtime_call_aliases))
    if (
        isinstance(node, ast.Attribute)
        and node.attr.lower() in RUNTIME_PATH_OBJECT_RETURNING_ATTRIBUTES
        and _node_resolves_to_path_object(node.value, runtime_call_aliases)
    ):
        return True
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr.lower() in RUNTIME_PATH_SEQUENCE_ATTRIBUTES
        and _node_resolves_to_path_object(node.value.value, runtime_call_aliases)
    ):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _node_resolves_to_path_object(node.left, runtime_call_aliases) or _node_resolves_to_path_object(
            node.right,
            runtime_call_aliases,
        )
    return False


def _path_object_runtime_call_name(
    func: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> str:
    if not isinstance(func, ast.Attribute) or not _node_resolves_to_path_object(func.value, runtime_call_aliases):
        return ""
    return _resolve_runtime_call_name(f"pathlib.path.{func.attr}", runtime_call_aliases)


def _literal_looks_like_runtime_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text or "\n" in text or "\r" in text:
        return False
    lowered = text.lower().rstrip("*?")
    if lowered.startswith(("http://", "https://")):
        return False
    if "://" in lowered or "/" in text or "\\" in text:
        return True
    if lowered.startswith((".", "~")):
        return True
    return os.path.splitext(lowered)[1] in RUNTIME_PATH_LITERAL_EXTENSIONS


def _node_contains_runtime_path_literal(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _literal_looks_like_runtime_path(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_node_contains_runtime_path_literal(item) for item in node.elts)
    return False


def _node_contains_runtime_database_path_literal(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip()
        lowered = text.lower()
        if lowered == ":memory:" or lowered.startswith("file::memory:"):
            return False
        if lowered.startswith("file:"):
            return True
        return _literal_looks_like_runtime_path(text)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_node_contains_runtime_database_path_literal(item) for item in node.elts)
    return False


def _call_reads_runtime_path_literal(call: ast.Call) -> bool:
    call_name = _call_name(call.func).lower()
    if not call_name.endswith(".read"):
        return False
    candidates: list[ast.AST] = list(call.args[:1])
    candidates.extend(
        keyword.value
        for keyword in call.keywords or []
        if keyword.arg in {"file", "filename", "filenames", "path", "source"}
    )
    return any(_node_contains_runtime_path_literal(candidate) for candidate in candidates)


def _call_connects_runtime_database_path(call: ast.Call, call_lower: str) -> bool:
    if call_lower != "sqlite3.connect":
        return False
    candidates: list[ast.AST] = list(call.args[:1])
    candidates.extend(keyword.value for keyword in call.keywords or [] if keyword.arg == "database")
    return any(_node_contains_runtime_database_path_literal(candidate) for candidate in candidates)


def _open_call_mode(call: ast.Call, call_lower: str) -> str:
    if call_lower == "pathlib.path.open":
        positional_mode_index = 0
    else:
        positional_mode_index = 1
    if len(call.args) > positional_mode_index and isinstance(call.args[positional_mode_index], ast.Constant):
        return str(call.args[positional_mode_index].value or "")
    for keyword_node in call.keywords or []:
        if keyword_node.arg == "mode" and isinstance(keyword_node.value, ast.Constant):
            return str(keyword_node.value.value or "")
    return ""


def _call_is_mode_sensitive_file_open(call_name: str, call_lower: str) -> bool:
    return call_lower in MODE_SENSITIVE_FILE_OPEN_CALLS or call_name.endswith(".open")


def _call_file_open_mode_writes(call: ast.Call, call_lower: str) -> bool:
    mode = _open_call_mode(call, call_lower)
    return bool(mode and any(flag in mode for flag in ("a", "w", "x", "+")))


def _node_int_bit_or_value(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _node_int_bit_or_value(node.left)
        right = _node_int_bit_or_value(node.right)
        if left is not None and right is not None:
            return left | right
    return None


def _node_contains_os_open_mutation_flag(
    node: ast.AST,
    runtime_call_aliases: dict[str, str] | None = None,
) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _node_contains_os_open_mutation_flag(
            node.left,
            runtime_call_aliases,
        ) or _node_contains_os_open_mutation_flag(node.right, runtime_call_aliases)
    flag_name = _resolve_runtime_call_name(_call_name(node), runtime_call_aliases)
    if flag_name in OS_OPEN_FILE_MUTATION_FLAGS:
        return True
    flag_value = _node_int_bit_or_value(node)
    return flag_value is not None and any(flag_value & value for value in OS_OPEN_FILE_MUTATION_FLAG_VALUES)


def _os_open_call_mutates_file(call: ast.Call, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    candidates: list[ast.AST] = list(call.args[1:2])
    candidates.extend(keyword.value for keyword in call.keywords or [] if keyword.arg == "flags")
    return any(_node_contains_os_open_mutation_flag(candidate, runtime_call_aliases) for candidate in candidates)


def _call_exports_runtime_path_literal(call: ast.Call, call_lower: str) -> bool:
    if not (
        call_lower in {
            "joblib.dump",
            "numpy.save",
            "numpy.savetxt",
            "numpy.savez",
            "numpy.savez_compressed",
            "scipy.io.savemat",
            "shutil.unpack_archive",
            "torch.save",
        }
        or call_lower.endswith(
            (
                ".extract",
                ".extractall",
                ".to_csv",
                ".to_excel",
                ".to_feather",
                ".to_hdf",
                ".to_html",
                ".to_json",
                ".to_latex",
                ".to_markdown",
                ".to_orc",
                ".to_parquet",
                ".to_pickle",
                ".to_stata",
                ".to_xml",
                ".save",
                ".savefig",
                ".write_csv",
                ".write_excel",
                ".write_ipc",
                ".write_json",
                ".write_parquet",
            )
        )
    ):
        return False
    candidates: list[ast.AST] = list(call.args[:2])
    candidates.extend(
        keyword.value
        for keyword in call.keywords or []
        if keyword.arg in {"buf", "file", "filename", "path", "path_or_buf", "path_or_buffer", "excel_writer"}
    )
    return any(_node_contains_runtime_path_literal(candidate) for candidate in candidates)


def _call_mutates_runtime_environment(call_lower: str) -> bool:
    if call_lower in {"os.putenv", "os.unsetenv"}:
        return True
    prefix = "os.environ."
    if call_lower.startswith(prefix):
        return call_lower[len(prefix) :] in {"__delitem__", "__ior__", "__setitem__", "clear", "pop", "popitem", "setdefault", "update"}
    return False


def _reflected_runtime_state_target(call: ast.Call, runtime_call_aliases: dict[str, str] | None = None) -> str:
    call_lower = _resolve_runtime_call_name(_call_name(call.func), runtime_call_aliases)
    if call_lower not in {"builtins.delattr", "builtins.setattr", "delattr", "setattr"} or len(call.args) < 2:
        return ""
    attr = call.args[1]
    if not isinstance(attr, ast.Constant) or not isinstance(attr.value, str) or not attr.value:
        return ""
    root = _call_name(call.args[0])
    if not root:
        return ""
    return _resolve_runtime_call_name(f"{root}.{attr.value}", runtime_call_aliases)


def _target_mutates_runtime_environment(target: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_mutates_runtime_environment(item, runtime_call_aliases) for item in target.elts)
    if isinstance(target, ast.Name):
        return False
    candidate = target.value if isinstance(target, ast.Subscript) else target
    name = _literal_getattr_runtime_call_name(
        candidate if isinstance(candidate, ast.Call) else None,
        runtime_call_aliases,
    ) or _resolve_runtime_call_name(_call_name(candidate), runtime_call_aliases)
    return name == "os.environ"


def _node_mutates_runtime_environment(node: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(node, ast.Call):
        return _reflected_runtime_state_target(node, runtime_call_aliases) == "os.environ"
    if isinstance(node, ast.Assign):
        return any(_target_mutates_runtime_environment(target, runtime_call_aliases) for target in node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return _target_mutates_runtime_environment(node.target, runtime_call_aliases)
    if isinstance(node, ast.Delete):
        return any(_target_mutates_runtime_environment(target, runtime_call_aliases) for target in node.targets)
    return False


def _call_mutates_runtime_process_state(call_lower: str) -> bool:
    if call_lower in UNSAFE_PROCESS_STATE_MUTATION_CALLS:
        return True
    for target in RUNTIME_PROCESS_STATE_MUTATION_TARGETS:
        prefix = f"{target}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_PROCESS_STATE_MUTATION_METHODS
    return False


def _target_mutates_runtime_process_state(target: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_mutates_runtime_process_state(item, runtime_call_aliases) for item in target.elts)
    if isinstance(target, ast.Name):
        return False
    candidate = target.value if isinstance(target, ast.Subscript) else target
    name = _literal_getattr_runtime_call_name(
        candidate if isinstance(candidate, ast.Call) else None,
        runtime_call_aliases,
    ) or _resolve_runtime_call_name(_call_name(candidate), runtime_call_aliases)
    return name in RUNTIME_PROCESS_STATE_MUTATION_TARGETS


def _node_mutates_runtime_process_state(node: ast.AST, runtime_call_aliases: dict[str, str] | None = None) -> bool:
    if isinstance(node, ast.Call):
        return _reflected_runtime_state_target(node, runtime_call_aliases) in RUNTIME_PROCESS_STATE_MUTATION_TARGETS
    if isinstance(node, ast.Assign):
        return any(_target_mutates_runtime_process_state(target, runtime_call_aliases) for target in node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return _target_mutates_runtime_process_state(node.target, runtime_call_aliases)
    if isinstance(node, ast.Delete):
        return any(_target_mutates_runtime_process_state(target, runtime_call_aliases) for target in node.targets)
    return False


def _call_performs_runtime_network_operation(call_lower: str) -> bool:
    if call_lower in UNSAFE_NETWORK_CALLS:
        return True
    if call_lower in RUNTIME_NETWORK_CLIENT_CONSTRUCTORS:
        return True
    if call_lower in RUNTIME_NETWORK_SERVER_CONSTRUCTORS:
        return True
    for constructor in RUNTIME_NETWORK_CLIENT_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_NETWORK_CLIENT_METHODS
    for constructor in RUNTIME_NETWORK_SOCKET_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_NETWORK_SOCKET_METHODS
    for constructor in RUNTIME_NETWORK_SERVER_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_NETWORK_SERVER_METHODS
    return False


def _assigned_call_target_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None,
    constructors: set[str],
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                value = item.context_expr
                if not isinstance(value, ast.Call):
                    continue
                call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
                if call_lower in constructors and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
            continue
        if not isinstance(value, ast.Call):
            continue
        call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
        if call_lower not in constructors:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _runtime_network_socket_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    return _assigned_call_target_names(node, runtime_call_aliases, RUNTIME_NETWORK_SOCKET_CONSTRUCTORS)


def _runtime_network_client_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    return _assigned_call_target_names(node, runtime_call_aliases, RUNTIME_NETWORK_CLIENT_CONSTRUCTORS)


def _runtime_network_server_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    return _assigned_call_target_names(node, runtime_call_aliases, RUNTIME_NETWORK_SERVER_CONSTRUCTORS)


def _call_starts_runtime_background_execution(call_lower: str) -> bool:
    if call_lower in UNSAFE_BACKGROUND_EXECUTION_CALLS:
        return True
    for constructor in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS:
        prefix = f"{constructor}."
        if call_lower.startswith(prefix):
            return call_lower[len(prefix) :] in RUNTIME_BACKGROUND_EXECUTION_METHODS
    return False


def _runtime_background_worker_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                value = item.context_expr
                if not isinstance(value, ast.Call):
                    continue
                call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
                if call_lower in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
            continue
        if not isinstance(value, ast.Call):
            continue
        call_lower = _resolve_runtime_call_name(_call_name(value.func), runtime_call_aliases)
        if call_lower not in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_excluded_source_rel_path(rel_path: str) -> bool:
    normalized = str(rel_path or "").replace("\\", "/").strip("/")
    if not normalized:
        return False
    parts = [part.lower() for part in normalized.split("/") if part]
    filename = parts[-1] if parts else ""
    if any(part.startswith(".") for part in parts):
        return True
    if filename in EXCLUDED_SOURCE_FILES or filename.startswith("test_") or filename.endswith("_test.py"):
        return True
    return any(part in EXCLUDED_SOURCE_DIRS or part.startswith("test") for part in parts[:-1])


def _analysis_llm_enabled(options: Dict[str, Any] | None = None) -> bool:
    options = options or {}
    if "analysis_llm" in options:
        return bool(options.get("analysis_llm"))
    return os.getenv("CODE2MCP_ANALYSIS_LLM", "false").strip().lower() in {"1", "true", "yes", "on"}


def _analysis_gitingest_enabled(options: Dict[str, Any] | None = None) -> bool:
    options = options or {}
    if "analysis_use_gitingest" in options:
        return bool(options.get("analysis_use_gitingest"))
    return os.getenv("CODE2MCP_ANALYSIS_USE_GITINGEST", "false").strip().lower() in {"1", "true", "yes", "on"}


def _analysis_deepwiki_enabled(options: Dict[str, Any] | None = None) -> bool:
    options = options or {}
    if "analysis_use_deepwiki" in options:
        return bool(options.get("analysis_use_deepwiki"))
    return os.getenv("CODE2MCP_ANALYSIS_USE_DEEPWIKI", "false").strip().lower() in {"1", "true", "yes", "on"}


def _static_llm_analysis(static_core_modules: List[Dict[str, Any]], entry_points: Dict[str, Any]) -> Dict[str, Any]:
    cli_commands = entry_points.get("cli", []) if isinstance(entry_points, dict) else []
    return {
        "source_of_truth": "ast",
        "core_modules": static_core_modules,
        "cli_commands": cli_commands,
        "import_strategy": {
            "primary": "import" if static_core_modules else "cli" if cli_commands else "blackbox",
            "fallback": "cli" if cli_commands else "blackbox",
            "confidence": 0.9 if static_core_modules else 0.4,
        },
        "dependencies": {"required": [], "optional": []},
        "risk_assessment": {
            "import_feasibility": 0.8 if static_core_modules else 0.3,
            "intrusiveness_risk": "low",
            "complexity": "medium" if len(static_core_modules) > 5 else "simple",
        },
    }


def _summarize_source_tree(source_dir: str, repo_url: str) -> Dict[str, Any]:
    if not source_dir or not os.path.isdir(source_dir):
        return {
            "repository_url": repo_url,
            "summary": f"Local source directory not found: {source_dir}",
            "file_tree": {},
            "content": {},
            "processed_by": "local_source_scan",
            "success": False,
        }

    max_content_files = int(os.getenv("ANALYSIS_LOCAL_SCAN_MAX_CONTENT_FILES", "50"))
    max_file_chars = int(os.getenv("ANALYSIS_LOCAL_SCAN_MAX_FILE_CHARS", "1000"))
    file_tree: Dict[str, Any] = {}
    content: Dict[str, str] = {}
    total_files = 0
    python_files = 0
    text_files = 0

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [
            d for d in dirs
            if d.lower() not in EXCLUDED_SOURCE_DIRS and not d.startswith(".") and not d.lower().startswith("test")
        ]
        for filename in files:
            if filename.startswith("."):
                continue
            path = os.path.join(root, filename)
            rel_path = os.path.relpath(path, source_dir).replace(os.sep, "/")
            if _is_excluded_source_rel_path(rel_path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            total_files += 1
            ext = os.path.splitext(filename)[1].lower()
            if ext == ".py":
                python_files += 1
            if ext in LOCAL_SCAN_TEXT_EXTS:
                text_files += 1
                if len(content) < max_content_files:
                    try:
                        text = open(path, "r", encoding="utf-8-sig", errors="ignore").read(max_file_chars + 1)
                        if len(text) > max_file_chars:
                            text = text[:max_file_chars] + "\n[File content truncated]"
                        content[rel_path] = text
                    except OSError:
                        pass
            file_tree[rel_path] = {"size": size}

    return {
        "repository_url": repo_url,
        "summary": (
            f"Local source scan completed: {total_files} files, "
            f"{python_files} Python files, {text_files} text-like files."
        ),
        "file_tree": file_tree,
        "content": content,
        "processed_by": "local_source_scan",
        "success": total_files > 0,
        "stats": {
            "total_files": total_files,
            "python_files": python_files,
            "text_files": text_files,
            "content_files": len(content),
        },
    }


def _is_valid_deepwiki_content(content: str) -> bool:
    content = sanitize_deepwiki_content(content)
    if not content or len(content.strip()) < 50:
        return False

    loading_indicators = ["Loading...", "loading", "Please wait", "Analyzing", "Processing"]
    if any(indicator in content for indicator in loading_indicators) and len(content.strip()) < 200:
        return False

    valid_indicators = ["Analysis", "Repository", "Functions", "Classes", "Dependencies", "Features", "Description", "Overview"]
    if any(indicator in content for indicator in valid_indicators):
        return True

    if len(content) > 200 and not content.strip().startswith("Warning:"):
        return True

    return False


def _annotation_to_str(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except Exception:
        return ""


def _literal_default(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        value = ast.literal_eval(node)
        return repr(value)
    except Exception:
        try:
            return ast.unparse(node)
        except Exception:
            return ""


def _scan_common_import_packages(source_dir: str) -> list[str]:
    found: set[str] = set()
    if not source_dir or not os.path.isdir(source_dir):
        return []

    pattern = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [
            d for d in dirs
            if d.lower() not in EXCLUDED_SOURCE_DIRS and not d.startswith(".") and not d.lower().startswith("test")
        ]
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            rel_path = os.path.relpath(path, source_dir)
            if _is_excluded_source_rel_path(rel_path):
                continue
            try:
                text = open(path, "r", encoding="utf-8-sig", errors="ignore").read()
            except OSError:
                continue
            for match in pattern.finditer(text):
                package = COMMON_IMPORT_PACKAGE_MAP.get(match.group(1))
                if package:
                    found.add(package)
    return sorted(found)


def _common_import_packages_from_symbols(source_symbols: Dict[str, Any]) -> list[str]:
    found: set[str] = set()
    for module in (source_symbols or {}).values():
        if not isinstance(module, dict):
            continue
        for root in module.get("imports", []) or []:
            package = COMMON_IMPORT_PACKAGE_MAP.get(str(root))
            if package:
                found.add(package)
    return sorted(found)


def _wrapper_candidate_stats(
    function_details: Dict[str, Dict[str, Any]],
    class_details: Dict[str, Dict[str, Any]],
    wrapper_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    recommended_functions = sum(1 for detail in function_details.values() if detail.get("wrapper_recommended"))
    recommended_classes = sum(1 for detail in class_details.values() if detail.get("wrapper_recommended"))
    top_score = max((int(item.get("score", 0) or 0) for item in wrapper_candidates), default=0)
    return {
        "public_functions": len(function_details),
        "public_classes": len(class_details),
        "recommended_functions": recommended_functions,
        "recommended_classes": recommended_classes,
        "candidate_count": len(wrapper_candidates),
        "rejected_symbols": max(0, len(function_details) + len(class_details) - len(wrapper_candidates)),
        "top_score": top_score,
    }


def _top_static_wrapper_candidates(static_core_modules: List[Dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for module in static_core_modules:
        label = ".".join(part for part in [str(module.get("package", "") or ""), str(module.get("module", "") or "")] if part)
        for item in module.get("wrapper_candidates", []) or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "module": label,
                "file_path": module.get("file_path", ""),
                "name": item.get("name", ""),
                "kind": item.get("kind", ""),
                "score": int(item.get("score", 0) or 0),
            })
    rows.sort(key=lambda item: (-int(item["score"]), str(item["module"]), str(item["name"])))
    return rows[:limit]


def _name_tokens(value: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return {part.lower() for part in re.findall(r"[A-Za-z0-9]+", spaced)}


def _signature_details(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    skip_implicit_receiver: bool = False,
) -> tuple[list[str], list[dict[str, Any]], bool, bool]:
    args = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
    raw_params: list[tuple[ast.arg, ast.AST | None, str]] = [
        (arg, default, "positional") for arg, default in zip(args, defaults)
    ]
    raw_params.extend(
        (arg, default, "keyword_only")
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
    )

    names: list[str] = []
    details: list[dict[str, Any]] = []
    for index, (arg, default, kind) in enumerate(raw_params):
        if skip_implicit_receiver and index == 0 and arg.arg in {"self", "cls"}:
            continue
        names.append(arg.arg)
        details.append({
            "name": arg.arg,
            "kind": kind,
            "annotation": _annotation_to_str(arg.annotation),
            "required": default is None,
            "default": _literal_default(default),
        })

    has_varargs = node.args.vararg is not None
    has_kwargs = node.args.kwarg is not None
    if node.args.vararg is not None:
        details.append({
            "name": node.args.vararg.arg,
            "kind": "vararg",
            "annotation": _annotation_to_str(node.args.vararg.annotation),
            "required": False,
            "default": "",
        })
    if node.args.kwarg is not None:
        details.append({
            "name": node.args.kwarg.arg,
            "kind": "kwarg",
            "annotation": _annotation_to_str(node.args.kwarg.annotation),
            "required": False,
            "default": "",
        })
    return names, details, has_varargs, has_kwargs


def _looks_framework_entrypoint_signature(name: str, params: list[str]) -> bool:
    normalized = [str(param or "").lower() for param in params]
    return len(normalized) >= 2 and normalized[:2] == ["environ", "start_response"]


def _wrapper_assessment(name: str, params: list[str], has_varargs: bool, has_kwargs: bool, docstring: str) -> dict[str, Any]:
    risk_reasons: list[str] = []
    score = 100
    lowered = name.lower()
    name_tokens = _name_tokens(name)
    sensitive_params = [param for param in params if looks_sensitive_parameter(param)]
    opaque_params = [param for param in params if param.lower() in OPAQUE_WRAPPER_PARAM_NAMES]
    complex_runtime_params = [param for param in params if param.lower() in COMPLEX_RUNTIME_WRAPPER_PARAM_NAMES]
    if lowered.startswith("_"):
        risk_reasons.append("private_name")
        score -= 50
    if any(part in lowered for part in EXCLUDED_NAME_PARTS):
        risk_reasons.append("test_or_example_name")
        score -= 35
    if lowered in ENVIRONMENT_PROBE_WRAPPER_NAMES or name_tokens.intersection(ENVIRONMENT_PROBE_WRAPPER_NAME_PARTS):
        risk_reasons.append("environment_probe_name")
        score -= 80
    if name_tokens.intersection(PLOTTING_WRAPPER_NAME_PARTS):
        risk_reasons.append("plotting_helper_name")
        score -= 80
    if name_tokens.intersection(OUTPUT_ONLY_WRAPPER_NAME_PARTS):
        risk_reasons.append("output_only_name")
        score -= 65
    if name_tokens.intersection(REMOTE_LOOKUP_WRAPPER_NAME_PARTS):
        risk_reasons.append("remote_lookup_name")
        score -= 80
    if name_tokens.intersection(
        OPERATIONAL_WRAPPER_NAME_PARTS
        | EXECUTION_WRAPPER_NAME_PARTS
        | STATEFUL_WRAPPER_NAME_PARTS
        | CONNECTION_WRAPPER_NAME_PARTS
    ):
        risk_reasons.append("operational_tool_name")
        score -= 80
    if _looks_framework_entrypoint_signature(name, params):
        risk_reasons.append("framework_entrypoint_signature")
        score -= 80
    if has_varargs or has_kwargs:
        risk_reasons.append("dynamic_signature")
        score -= 30
        if not params:
            risk_reasons.append("pure_dynamic_signature")
    if len(params) > 6:
        risk_reasons.append("many_parameters")
        score -= 20
    if not docstring:
        risk_reasons.append("missing_docstring")
        score -= 5
    if any(looks_resource_parameter(p) for p in params):
        risk_reasons.append("path_parameter_requires_guard")
        score -= 5
    if _looks_external_resource_wrapper(name, params, docstring):
        risk_reasons.append("external_resource_parameter")
        score -= 70
    if sensitive_params:
        risk_reasons.append("sensitive_parameter")
        score -= 60
    if opaque_params:
        risk_reasons.append("opaque_runtime_parameter")
        score -= 80
    if complex_runtime_params:
        risk_reasons.append("complex_runtime_parameter")
        score -= 65
    return {
        "score": max(score, 0),
        "recommended": score >= 55 and not {
            "private_name",
            "test_or_example_name",
            "environment_probe_name",
            "plotting_helper_name",
            "output_only_name",
            "remote_lookup_name",
            "operational_tool_name",
            "framework_entrypoint_signature",
            "pure_dynamic_signature",
            "external_resource_parameter",
            "sensitive_parameter",
            "opaque_runtime_parameter",
            "complex_runtime_parameter",
        }.intersection(risk_reasons),
        "risk_reasons": risk_reasons,
    }


def _looks_external_resource_wrapper(name: str, params: list[str], docstring: str) -> bool:
    resource_params = [param for param in params if looks_resource_parameter(param)]
    if not resource_params:
        return False
    lowered = str(name or "").lower()
    if lowered.startswith(("download_", "ingest_", "load_", "open_", "parse_", "read_", "save_", "upload_", "write_")):
        return True
    text = " ".join(str(docstring or "").lower().replace("_", " ").replace("-", " ").split())
    if not text:
        return False
    resource_words = {"directory", "file", "folder", "host", "path", "port", "uri", "url"}
    if resource_words.intersection(text.split()) and any(
        verb in text for verb in ("download", "ingest", "load", "open", "parse", "read", "save", "upload", "write")
    ):
        return True
    return any(
        str(param or "").lower().replace("_", " ") in text and resource_words.intersection(text.split())
        for param in resource_params
    )


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _root_name(node: ast.AST | None) -> str:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Call):
        return _root_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _looks_global_state_import(name: str) -> bool:
    return name.isupper() and 1 <= len(name) <= 3


def _imported_global_state_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                if _looks_global_state_import(local):
                    names.add(local)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                if _looks_global_state_import(local):
                    names.add(local)
    return names


def _runtime_getattr_call_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if value is None:
            continue
        call_lower = (
            _literal_getattr_attribute_runtime_call_name(value, runtime_call_aliases)
            or _literal_getattr_runtime_call_name(
                value if isinstance(value, ast.Call) else None,
                runtime_call_aliases,
            )
        )
        if not call_lower:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = call_lower
    return aliases


def _runtime_partial_call_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if not isinstance(value, ast.Call):
            continue
        call_lower = _literal_partial_runtime_call_name(value, runtime_call_aliases)
        if not call_lower:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = call_lower
    return aliases


def _runtime_dynamic_import_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if not isinstance(value, ast.Call):
            continue
        module_name = _literal_dynamic_import_module_name(value, runtime_call_aliases)
        if not module_name:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = module_name
    return aliases


def _runtime_path_object_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for child in ast.walk(node):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        combined_aliases = {**(runtime_call_aliases or {}), **aliases}
        if not _node_resolves_to_path_object(value, combined_aliases):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = "pathlib.path"
    return aliases


def _runtime_state_object_aliases(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    runtime_call_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    targets = {"os.environ", *RUNTIME_PROCESS_STATE_MUTATION_TARGETS}
    for child in ast.walk(node):
        assign_targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(child, ast.Assign):
            assign_targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            assign_targets = [child.target]
            value = child.value
        if value is None:
            continue
        target_name = _literal_getattr_runtime_call_name(
            value if isinstance(value, ast.Call) else None,
            runtime_call_aliases,
        ) or _resolve_runtime_call_name(_call_name(value), runtime_call_aliases)
        if target_name not in targets:
            continue
        for target in assign_targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = target_name
    return aliases


def _function_body_runtime_risk_reasons(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imported_global_state_names: set[str] | None = None,
    runtime_call_aliases: dict[str, str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    imported_global_state_names = imported_global_state_names or set()
    dynamic_import_aliases = _runtime_dynamic_import_aliases(node, runtime_call_aliases)
    state_object_aliases = _runtime_state_object_aliases(node, {**(runtime_call_aliases or {}), **dynamic_import_aliases})
    path_object_aliases = _runtime_path_object_aliases(node, {**(runtime_call_aliases or {}), **dynamic_import_aliases})
    combined_runtime_aliases = {
        **(runtime_call_aliases or {}),
        **dynamic_import_aliases,
        **state_object_aliases,
        **path_object_aliases,
    }
    network_client_names = _runtime_network_client_names(node, combined_runtime_aliases)
    network_server_names = _runtime_network_server_names(node, combined_runtime_aliases)
    network_socket_names = _runtime_network_socket_names(node, combined_runtime_aliases)
    background_worker_names = _runtime_background_worker_names(node, combined_runtime_aliases)
    getattr_call_aliases = _runtime_getattr_call_aliases(node, combined_runtime_aliases)
    partial_call_aliases = _runtime_partial_call_aliases(node, combined_runtime_aliases)
    for child in ast.walk(node):
        if _node_mutates_runtime_environment(child, combined_runtime_aliases):
            reasons.append("environment_mutation")
            continue
        if _node_mutates_runtime_process_state(child, combined_runtime_aliases):
            reasons.append("process_state_mutation")
            continue
        if not isinstance(child, ast.Call):
            continue
        call_name = _call_name(child.func)
        call_lower = (
            _literal_dynamic_import_runtime_call_name(child.func, combined_runtime_aliases)
            or _literal_getattr_attribute_runtime_call_name(child.func, combined_runtime_aliases)
            or _path_object_runtime_call_name(child.func, combined_runtime_aliases)
            or _literal_getattr_runtime_call_name(child.func, combined_runtime_aliases)
            or _literal_partial_runtime_call_name(child.func, combined_runtime_aliases)
            or _resolve_runtime_call_name(
                call_name,
                combined_runtime_aliases,
            )
        )
        call_lower = getattr_call_aliases.get(call_lower, call_lower)
        call_lower = partial_call_aliases.get(call_lower, call_lower)
        if call_lower in {"input", "builtins.input"}:
            reasons.append("interactive_input")
        if call_lower in UNSAFE_DYNAMIC_CODE_CALLS:
            reasons.append("dynamic_code_execution")
        if _call_mutates_runtime_environment(call_lower):
            reasons.append("environment_mutation")
        if _call_mutates_runtime_process_state(call_lower):
            reasons.append("process_state_mutation")
        if _call_starts_runtime_background_execution(call_lower) or (
            _root_name(child.func) in background_worker_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_BACKGROUND_EXECUTION_METHODS
        ):
            reasons.append("background_execution")
        if _root_name(child.func) in imported_global_state_names:
            reasons.append("global_state_dependency")
        if call_lower in UNSAFE_PROCESS_CALLS:
            reasons.append("process_execution")
        if _call_performs_runtime_network_operation(call_lower) or (
            _root_name(child.func) in network_socket_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_NETWORK_SOCKET_METHODS
        ) or (
            _root_name(child.func) in network_client_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_NETWORK_CLIENT_METHODS
        ) or (
            _root_name(child.func) in network_server_names
            and call_lower.rsplit(".", 1)[-1] in RUNTIME_NETWORK_SERVER_METHODS
        ):
            reasons.append("network_operation")
        if (
            (
                call_lower in UNSAFE_FILE_READ_CALLS
                or call_lower in MODE_SENSITIVE_FILE_OPEN_CALLS
            )
            and not _call_file_open_mode_writes(child, call_lower)
            or call_lower.endswith((".read_bytes", ".read_text"))
            or _call_reads_runtime_path_literal(child)
            or _call_connects_runtime_database_path(child, call_lower)
        ):
            reasons.append("file_read")
        if call_lower in UNSAFE_FILE_MUTATION_CALLS or call_lower.endswith(
            (
                ".chmod",
                ".hardlink_to",
                ".lchmod",
                ".mkdir",
                ".rename",
                ".replace",
                ".rmdir",
                ".symlink_to",
                ".touch",
                ".unlink",
                ".write_bytes",
                ".write_text",
            )
        ) or _call_exports_runtime_path_literal(child, call_lower) or (
            _call_is_mode_sensitive_file_open(call_name, call_lower)
            and _call_file_open_mode_writes(child, call_lower)
        ):
            reasons.append("file_mutation")
        if call_lower == "os.open":
            if _os_open_call_mutates_file(child, combined_runtime_aliases):
                reasons.append("file_mutation")
            else:
                reasons.append("file_read")
        elif _call_is_mode_sensitive_file_open(call_name, call_lower):
            if _call_file_open_mode_writes(child, call_lower):
                reasons.append("file_mutation")
            else:
                reasons.append("file_read")
        if call_name.endswith((".write", ".writelines")):
            reasons.append("file_mutation")
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and _root_name(child.value) in imported_global_state_names:
            reasons.append("global_state_dependency")
    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique[:8]


def _return_value_is_none(value: ast.AST | None) -> bool:
    if value is None:
        return True
    return isinstance(value, ast.Constant) and value.value is None


def _function_body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(getattr(node, "body", []) or [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _function_body_is_unsupported_placeholder(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _function_body_without_docstring(node)
    if not body:
        return True
    if all(
        isinstance(statement, ast.Pass)
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        )
        for statement in body
    ):
        return True
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Raise):
        exc_name = _call_name(statement.exc)
        return exc_name.endswith("NotImplementedError")
    if isinstance(statement, ast.Return):
        value = statement.value
        if _return_value_is_none(value):
            return True
        return isinstance(value, ast.Name) and value.id == "NotImplemented"
    return False


def _function_has_value_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    class ReturnVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is node:
                self.generic_visit(child)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is node:
                self.generic_visit(child)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return None

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return None

        def visit_Return(self, child: ast.Return) -> None:
            if not _return_value_is_none(child.value):
                self.found = True

    visitor = ReturnVisitor()
    visitor.visit(node)
    return visitor.found


def _function_detail(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imported_global_state_names: set[str] | None = None,
    runtime_call_aliases: dict[str, str] | None = None,
    *,
    skip_implicit_receiver: bool = False,
) -> dict[str, Any]:
    params, param_details, has_varargs, has_kwargs = _signature_details(node, skip_implicit_receiver=skip_implicit_receiver)
    docstring = ast.get_docstring(node) or ""
    assessment = _wrapper_assessment(node.name, params, has_varargs, has_kwargs, docstring)
    body_risks = _function_body_runtime_risk_reasons(node, imported_global_state_names, runtime_call_aliases)
    return_annotation = _annotation_to_str(node.returns)
    void_return = return_annotation.strip().lower() in {"none", "nonetype"} or not _function_has_value_return(node)
    unsupported_placeholder = _function_body_is_unsupported_placeholder(node)
    is_async = isinstance(node, ast.AsyncFunctionDef)
    risk_reasons = list(
        dict.fromkeys(
            [
                *assessment["risk_reasons"],
                *body_risks,
                *(["unsupported_placeholder"] if unsupported_placeholder else []),
                *(["void_return"] if void_return else []),
                *(["async_function"] if is_async else []),
            ]
        )
    )
    score = max(
        assessment["score"]
        - (60 if body_risks else 0)
        - (80 if unsupported_placeholder and not void_return else 0)
        - (80 if void_return else 0)
        - (80 if is_async else 0),
        0,
    )
    recommended = assessment["recommended"] and not body_risks and not unsupported_placeholder and not void_return and not is_async
    return {
        "name": node.name,
        "parameters": params,
        "parameter_details": param_details,
        "return_annotation": return_annotation,
        "docstring": docstring[:500],
        "line": getattr(node, "lineno", 0),
        "is_async": is_async,
        "has_varargs": has_varargs,
        "has_kwargs": has_kwargs,
        "wrapper_score": score,
        "wrapper_recommended": recommended,
        "risk_reasons": risk_reasons,
    }


def _module_import_roots(tree: ast.AST) -> list[str]:
    roots: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".")[0]
                if root:
                    roots.add(root)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root = node.module.split(".")[0]
            if root:
                roots.add(root)
    return sorted(roots)


def _apply_module_runtime_risks(function_details: Dict[str, Dict[str, Any]], module_imports: list[str]) -> None:
    imports = {str(item).split(".")[0].lower() for item in module_imports or []}
    if not imports.intersection(DANGEROUS_INTERACTIVE_IMPORTS):
        return
    for detail in function_details.values():
        reasons = list(detail.get("risk_reasons") or [])
        if "keyboard_listener_dependency" not in reasons:
            reasons.append("keyboard_listener_dependency")
        detail["risk_reasons"] = reasons
        detail["wrapper_score"] = max(int(detail.get("wrapper_score", 0) or 0) - 80, 0)
        detail["wrapper_recommended"] = False


SAFE_TOP_LEVEL_CALLS = {"collections.namedtuple", "dict", "frozenset", "list", "logging.getLogger", "re.compile", "re.escape", "set", "tuple"}


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    if not isinstance(left, ast.Name) or left.id != "__name__":
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    return isinstance(right, ast.Constant) and right.value == "__main__"


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _safe_call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _safe_call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _safe_top_level_value(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, (ast.Constant, ast.Name, ast.Attribute)):
        return True
    if isinstance(node, ast.JoinedStr):
        return all(_safe_top_level_value(item) for item in node.values)
    if isinstance(node, ast.FormattedValue):
        return _safe_top_level_value(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_safe_top_level_value(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(_safe_top_level_value(item) for item in list(node.keys) + list(node.values) if item is not None)
    if isinstance(node, ast.UnaryOp):
        return _safe_top_level_value(node.operand)
    if isinstance(node, ast.BinOp):
        return _safe_top_level_value(node.left) and _safe_top_level_value(node.right)
    if isinstance(node, ast.Compare):
        return _safe_top_level_value(node.left) and all(_safe_top_level_value(item) for item in node.comparators)
    if isinstance(node, ast.Call):
        if _safe_call_name(node.func) in SAFE_TOP_LEVEL_CALLS:
            return all(_safe_top_level_value(arg) for arg in node.args) and all(
                _safe_top_level_value(keyword.value) for keyword in node.keywords
            )
    return False


def _safe_top_level_statement(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Pass)):
        return True
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return True
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return _safe_top_level_value(node.value)
    if isinstance(node, ast.If) and (_is_type_checking_guard(node) or _safe_top_level_value(node.test)):
        return all(_safe_top_level_statement(item) for item in node.body + node.orelse)
    if isinstance(node, ast.Try):
        return (
            all(_safe_top_level_statement(item) for item in node.body)
            and all(_safe_top_level_statement(item) for handler in node.handlers for item in handler.body)
            and all(_safe_top_level_statement(item) for item in node.orelse)
            and all(_safe_top_level_statement(item) for item in node.finalbody)
        )
    return False


def _module_import_side_effect_reasons(tree: ast.AST) -> list[str]:
    reasons: list[str] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value if isinstance(node, ast.AnnAssign) else node.value
            if _safe_top_level_value(value):
                continue
            reasons.append(f"top_level_assignment_call:line_{getattr(node, 'lineno', 0)}")
            continue
        if isinstance(node, ast.If) and (_is_main_guard(node) or _is_type_checking_guard(node)):
            continue
        if isinstance(node, (ast.If, ast.Try)) and _safe_top_level_statement(node):
            continue
        reasons.append(f"top_level_{type(node).__name__.lower()}:line_{getattr(node, 'lineno', 0)}")
    return reasons[:8]


def _class_expr_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Subscript):
        return _class_expr_name(node.value)
    return _call_name(node)


def _class_risk_reasons(node: ast.ClassDef, methods: list[dict[str, Any]]) -> list[str]:
    data_model_bases = {"basemodel", "basesettings"}
    enum_bases = {
        "enum",
        "enum.enum",
        "enum.flag",
        "enum.intenum",
        "enum.intflag",
        "enum.strenum",
        "flag",
        "intenum",
        "intflag",
        "strenum",
    }
    network_server_handler_bases = {
        "basehttprequesthandler",
        "http.server.basehttprequesthandler",
        "baserequesthandler",
        "socketserver.baserequesthandler",
    }
    decorators = {
        _class_expr_name(decorator.func if isinstance(decorator, ast.Call) else decorator).lower()
        for decorator in getattr(node, "decorator_list", [])
    }
    bases = {_class_expr_name(base).lower() for base in getattr(node, "bases", [])}
    reasons: list[str] = []
    if any(name == "dataclass" or name.endswith(".dataclass") for name in decorators):
        reasons.append("data_container_class")
    if any(name in data_model_bases or name.endswith((".basemodel", ".basesettings")) for name in bases):
        reasons.append("data_model_class")
    if any(name in enum_bases for name in bases):
        reasons.append("enum_class")
    if any(name == "typeddict" or name.endswith(".typeddict") for name in bases):
        reasons.append("typed_dict_class")
    if any(name in {"tuple", "typing.tuple", "namedtuple"} or name.endswith(".namedtuple") for name in bases):
        reasons.append("tuple_container_class")
    if any(name in network_server_handler_bases for name in bases):
        reasons.append("network_server_handler_class")
    if not methods:
        reasons.append("no_public_methods")
    return reasons


def _class_detail(node: ast.ClassDef) -> dict[str, Any]:
    methods = []
    constructor = None
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__":
            constructor = _function_detail(child, skip_implicit_receiver=True)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
            methods.append(_function_detail(child, skip_implicit_receiver=True))
    required_constructor_params = [
        detail.get("name")
        for detail in (constructor or {}).get("parameter_details", [])
        if detail.get("kind") not in {"vararg", "kwarg"} and detail.get("required")
    ]
    sensitive_constructor_params = [
        detail.get("name")
        for detail in (constructor or {}).get("parameter_details", [])
        if detail.get("kind") not in {"vararg", "kwarg"} and looks_sensitive_parameter(str(detail.get("name", "")))
    ]
    complex_constructor_params = [
        detail.get("name")
        for detail in (constructor or {}).get("parameter_details", [])
        if detail.get("kind") not in {"vararg", "kwarg"}
        and str(detail.get("name", "")).lower() in COMPLEX_RUNTIME_WRAPPER_PARAM_NAMES
    ]
    constructor_safe = (
        not required_constructor_params
        and not sensitive_constructor_params
        and not complex_constructor_params
        and not (constructor or {}).get("has_varargs")
        and not (constructor or {}).get("has_kwargs")
    )
    risk_reasons = _class_risk_reasons(node, methods)
    if required_constructor_params:
        risk_reasons.append("constructor_requires_args")
    if sensitive_constructor_params:
        risk_reasons.append("sensitive_constructor_parameter")
    if complex_constructor_params:
        risk_reasons.append("complex_constructor_parameter")
    if (constructor or {}).get("has_varargs") or (constructor or {}).get("has_kwargs"):
        risk_reasons.append("dynamic_constructor_signature")
    wrapper_score = 75 if constructor_safe and methods else 55 if constructor_safe else 20
    non_wrapper_reasons = {
        "data_container_class",
        "data_model_class",
        "enum_class",
        "network_server_handler_class",
        "typed_dict_class",
        "tuple_container_class",
    }
    if any(reason in risk_reasons for reason in non_wrapper_reasons):
        wrapper_score = min(wrapper_score, 20)
    elif "no_public_methods" in risk_reasons:
        wrapper_score = min(wrapper_score, 35)
    return {
        "name": node.name,
        "docstring": (ast.get_docstring(node) or "")[:500],
        "line": getattr(node, "lineno", 0),
        "public_methods": methods[:12],
        "constructor_parameters": (constructor or {}).get("parameters", []),
        "constructor_parameter_details": (constructor or {}).get("parameter_details", []),
        "constructor_sensitive_parameters": sensitive_constructor_params,
        "constructor_complex_parameters": complex_constructor_params,
        "constructor_requires_args": bool(required_constructor_params),
        "constructor_has_varargs": bool((constructor or {}).get("has_varargs")),
        "constructor_has_kwargs": bool((constructor or {}).get("has_kwargs")),
        "wrapper_score": wrapper_score,
        "wrapper_recommended": constructor_safe and bool(methods) and wrapper_score >= 45,
        "risk_reasons": list(dict.fromkeys(risk_reasons)),
    }


def _decorator_name(decorator: ast.AST) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parent = _decorator_name(target.value)
        return f"{parent}.{target.attr}" if parent else target.attr
    return ""


def _has_pytest_fixture_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {_decorator_name(decorator) for decorator in getattr(node, "decorator_list", [])}
    return any(name == "fixture" or name.endswith(".fixture") for name in names)


def _has_framework_entrypoint_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {_decorator_name(decorator).lower() for decorator in getattr(node, "decorator_list", [])}
    for name in names:
        if name in {"click.command", "click.group", "typer.command", "typer.callback"}:
            return True
        if name.endswith((".api_route", ".command", ".delete", ".get", ".group", ".patch", ".post", ".put", ".route", ".task", ".websocket")):
            return True
    return False


def _apply_framework_entrypoint_risk(detail: dict[str, Any]) -> None:
    reasons = list(detail.get("risk_reasons") or [])
    if "framework_entrypoint_decorator" not in reasons:
        reasons.append("framework_entrypoint_decorator")
    detail["risk_reasons"] = reasons
    detail["wrapper_score"] = max(int(detail.get("wrapper_score", 0) or 0) - 80, 0)
    detail["wrapper_recommended"] = False


def _module_symbols_from_tree(module_path: str, rel_path: str, tree: ast.AST, parser: str = "current") -> dict[str, Any] | None:
    funcs: Dict[str, list] = {}
    function_details: Dict[str, Dict[str, Any]] = {}
    classes: set = set()
    class_details: Dict[str, Dict[str, Any]] = {}
    imported_global_state_names = _imported_global_state_names(tree)
    runtime_call_aliases = _runtime_call_aliases(tree)
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
            if _has_pytest_fixture_decorator(node):
                continue
            detail = _function_detail(node, imported_global_state_names, runtime_call_aliases)
            if _has_framework_entrypoint_decorator(node):
                _apply_framework_entrypoint_risk(detail)
            if any(part in node.name.lower() for part in EXCLUDED_NAME_PARTS):
                continue
            funcs[node.name] = detail["parameters"]
            function_details[node.name] = detail
        elif isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
            if any(part in node.name.lower() for part in EXCLUDED_NAME_PARTS):
                continue
            classes.add(node.name)
            class_details[node.name] = _class_detail(node)
    if not funcs and not classes:
        return None

    module_imports = _module_import_roots(tree)
    _apply_module_runtime_risks(function_details, module_imports)
    side_effect_reasons = _module_import_side_effect_reasons(tree)
    wrapper_candidates = sorted(
        [
            {"name": name, "kind": "function", "score": detail["wrapper_score"]}
            for name, detail in function_details.items()
            if detail.get("wrapper_recommended")
        ] + [
            {"name": name, "kind": "class", "score": detail["wrapper_score"]}
            for name, detail in class_details.items()
            if detail.get("wrapper_recommended")
        ],
        key=lambda item: (-item["score"], item["name"]),
    )
    wrapper_candidate_stats = _wrapper_candidate_stats(function_details, class_details, wrapper_candidates)
    return {
        'functions': funcs,
        'classes': classes,
        'file_path': rel_path,
        'imports': module_imports,
        'import_side_effect_risk': bool(side_effect_reasons),
        'import_side_effect_reasons': side_effect_reasons,
        'function_details': function_details,
        'class_details': class_details,
        'wrapper_candidates': wrapper_candidates[:12],
        'wrapper_candidate_stats': wrapper_candidate_stats,
        'parser': parser,
    }


def _analysis_python_candidates() -> list[tuple[list[str], str]]:
    global _AST_FALLBACK_CANDIDATES
    if _AST_FALLBACK_CANDIDATES is not None:
        return _AST_FALLBACK_CANDIDATES

    try:
        from .env_node import _candidate_python_commands, _python_version, _version_tuple

        current = _version_tuple(sys.version)
        candidates: list[tuple[tuple[int, int], list[str], str]] = []
        for command in _candidate_python_commands(["3.13", "3.12", "3.11", "3.10"]):
            version = _python_version(command)
            version_tuple = _version_tuple(version)
            if version_tuple >= (3, 10) and version_tuple > current:
                candidates.append((version_tuple, command, version))
        candidates.sort(key=lambda item: item[0], reverse=True)
        _AST_FALLBACK_CANDIDATES = [(command, version) for _, command, version in candidates]
    except Exception as exc:
        logger.debug(f"Failed to discover AST fallback Python interpreters: {exc}")
        _AST_FALLBACK_CANDIDATES = []
    return _AST_FALLBACK_CANDIDATES


def _scan_file_with_external_python(file_path: str, module_path: str, rel_path: str) -> dict[str, Any] | None:
    script = r'''
import ast
import json
import os
import re
import sys

EXCLUDED_NAME_PARTS = ("test", "example", "demo", "benchmark")
OPERATIONAL_WRAPPER_NAME_PARTS = set(
    "append attach build create delete download ensure fit install monkey patch post rebuild remove "
    "save send train update upload write".split()
)
EXECUTION_WRAPPER_NAME_PARTS = {"cmd", "command", "execute", "popen", "run", "shell", "subprocess", "system"}
STATEFUL_WRAPPER_NAME_PARTS = {"clear", "close", "kill", "launch", "reset", "shutdown", "start", "stop"}
CONNECTION_WRAPPER_NAME_PARTS = {"connect", "connection", "database", "handler", "hook", "logger", "mongodb", "redis"}
ENVIRONMENT_PROBE_WRAPPER_NAMES = set(
    "array_type data_path get_config get_include get_libraries get_library_dirs get_user_config_file "
    "get_versions has_c has_cpp has_cuda has_cxx has_fortran has_gpu list_engines package_path".split()
)
ENVIRONMENT_PROBE_WRAPPER_NAME_PARTS = {"availability", "backend", "compilation", "compiler"}
PLOTTING_WRAPPER_NAME_PARTS = {"matplotlib", "mpl", "plot", "plots", "plotly"}
OUTPUT_ONLY_WRAPPER_NAME_PARTS = {"display", "pprint", "print", "show"}
REMOTE_LOOKUP_WRAPPER_NAME_PARTS = {"entrez", "expasy", "kegg", "ncbi", "prodoc", "prosite", "pubmed", "sprot", "swissprot", "uniprot", "vso", "wsdl"}

def annotation_to_str(annotation):
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except Exception:
        return ""

def literal_default(node):
    if node is None:
        return ""
    try:
        return repr(ast.literal_eval(node))
    except Exception:
        try:
            return ast.unparse(node)
        except Exception:
            return ""

def signature_details(node, *, skip_implicit_receiver=False):
    args = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
    raw_params = [(arg, default, "positional") for arg, default in zip(args, defaults)]
    raw_params.extend((arg, default, "keyword_only") for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults))
    names = []
    details = []
    for index, (arg, default, kind) in enumerate(raw_params):
        if skip_implicit_receiver and index == 0 and arg.arg in {"self", "cls"}:
            continue
        names.append(arg.arg)
        details.append({
            "name": arg.arg,
            "kind": kind,
            "annotation": annotation_to_str(arg.annotation),
            "required": default is None,
            "default": literal_default(default),
        })
    has_varargs = node.args.vararg is not None
    has_kwargs = node.args.kwarg is not None
    if node.args.vararg is not None:
        details.append({
            "name": node.args.vararg.arg,
            "kind": "vararg",
            "annotation": annotation_to_str(node.args.vararg.annotation),
            "required": False,
            "default": "",
        })
    if node.args.kwarg is not None:
        details.append({
            "name": node.args.kwarg.arg,
            "kind": "kwarg",
            "annotation": annotation_to_str(node.args.kwarg.annotation),
            "required": False,
            "default": "",
        })
    return names, details, has_varargs, has_kwargs

def name_tokens(value):
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return {part.lower() for part in re.findall(r"[A-Za-z0-9]+", spaced)}

def compact_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

def normalized_name(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")

def looks_resource_parameter(param_name):
    normalized = normalized_name(param_name)
    compact = compact_name(param_name)
    if normalized in {"import_path", "module_path"} or compact in {"importpath", "modulepath"}:
        return False
    resource_exact = {"directory", "dir", "dirname", "dir_name", "file", "filepath", "file_path", "filename", "file_name", "fname", "host", "hostname", "path", "port", "uri", "url"}
    resource_tokens = {"dir", "directory", "dirname", "file", "filename", "filepath", "files", "fname", "host", "hostname", "path", "paths", "port", "uri", "url"}
    resource_endings = {"configfile", "datafile", "directory", "dirname", "filepaths", "filepath", "fname", "inputdir", "inputfile", "inputpath", "jsonfile", "logfile", "modelfile", "outputdir", "outputfile", "outputpath", "relativepath", "rootpath", "sourcefile", "sourcepath", "targetfile", "targetpath", "txtfile", "uri", "url", "xmlfile"}
    if normalized in resource_exact or compact in resource_exact:
        return True
    if name_tokens(param_name).intersection(resource_tokens):
        return True
    if normalized.endswith(("_path", "_paths", "_file", "_files", "_fname", "_dir", "_directory", "_url", "_uri", "_host", "_port")):
        return True
    return any(compact.endswith(ending) for ending in resource_endings)

def looks_sensitive_parameter(param_name):
    tokens = name_tokens(param_name)
    compact = compact_name(param_name)
    sensitive_exact = {
        "token", "access_token", "api_token", "api_key", "credential", "credentials", "creds",
        "dob", "medical_record_number", "mrn", "patient", "patient_id", "patient_name",
        "phi", "pii", "secret_key", "password", "ssn", "username"
    }
    sensitive_compact = {
        "accesstoken",
        "apikey",
        "apitoken",
        "authtoken",
        "bearertoken",
        "credential",
        "credentials",
        "creds",
        "dob",
        "githubtoken",
        "hftoken",
        "medicalrecordnumber",
        "mrn",
        "openaitoken",
        "password",
        "patient",
        "patientid",
        "patientname",
        "phi",
        "pii",
        "privatekey",
        "refreshtoken",
        "secret",
        "secretkey",
        "sessiontoken",
        "ssn",
        "username",
    }
    if str(param_name or "").lower() in sensitive_exact or compact in sensitive_compact:
        return True
    if "token" in tokens and tokens.intersection({"access", "api", "auth", "bearer", "github", "hf", "openai", "refresh", "secret", "session"}):
        return True
    if "key" in tokens and tokens.intersection({"access", "api", "auth", "private", "secret", "ssh"}):
        return True
    return bool(tokens.intersection({"credential", "credentials", "creds", "dob", "mrn", "password", "passwd", "patient", "phi", "pii", "secret", "ssn"}))

def looks_framework_entrypoint_signature(name, params):
    normalized = [str(param or "").lower() for param in params]
    return len(normalized) >= 2 and normalized[:2] == ["environ", "start_response"]

def wrapper_assessment(name, params, has_varargs, has_kwargs, docstring):
    risk_reasons = []
    score = 100
    lowered = name.lower()
    tokens = name_tokens(name)
    sensitive_params = [param for param in params if looks_sensitive_parameter(param)]
    opaque_params = [param for param in params if param.lower() in OPAQUE_WRAPPER_PARAM_NAMES]
    complex_runtime_params = [param for param in params if param.lower() in COMPLEX_RUNTIME_WRAPPER_PARAM_NAMES]
    if lowered.startswith("_"):
        risk_reasons.append("private_name")
        score -= 50
    if any(part in lowered for part in EXCLUDED_NAME_PARTS):
        risk_reasons.append("test_or_example_name")
        score -= 35
    if lowered in ENVIRONMENT_PROBE_WRAPPER_NAMES or tokens.intersection(ENVIRONMENT_PROBE_WRAPPER_NAME_PARTS):
        risk_reasons.append("environment_probe_name")
        score -= 80
    if tokens.intersection(PLOTTING_WRAPPER_NAME_PARTS):
        risk_reasons.append("plotting_helper_name")
        score -= 80
    if tokens.intersection(OUTPUT_ONLY_WRAPPER_NAME_PARTS):
        risk_reasons.append("output_only_name")
        score -= 65
    if tokens.intersection(REMOTE_LOOKUP_WRAPPER_NAME_PARTS):
        risk_reasons.append("remote_lookup_name")
        score -= 80
    if tokens.intersection(
        OPERATIONAL_WRAPPER_NAME_PARTS
        | EXECUTION_WRAPPER_NAME_PARTS
        | STATEFUL_WRAPPER_NAME_PARTS
        | CONNECTION_WRAPPER_NAME_PARTS
    ):
        risk_reasons.append("operational_tool_name")
        score -= 80
    if looks_framework_entrypoint_signature(name, params):
        risk_reasons.append("framework_entrypoint_signature")
        score -= 80
    if has_varargs or has_kwargs:
        risk_reasons.append("dynamic_signature")
        score -= 30
        if not params:
            risk_reasons.append("pure_dynamic_signature")
    if len(params) > 6:
        risk_reasons.append("many_parameters")
        score -= 20
    if not docstring:
        risk_reasons.append("missing_docstring")
        score -= 5
    if any(looks_resource_parameter(p) for p in params):
        risk_reasons.append("path_parameter_requires_guard")
        score -= 5
    if looks_external_resource_wrapper(name, params, docstring):
        risk_reasons.append("external_resource_parameter")
        score -= 70
    if sensitive_params:
        risk_reasons.append("sensitive_parameter")
        score -= 60
    if opaque_params:
        risk_reasons.append("opaque_runtime_parameter")
        score -= 80
    if complex_runtime_params:
        risk_reasons.append("complex_runtime_parameter")
        score -= 65
    return {
        "score": max(score, 0),
        "recommended": score >= 55
        and not {
            "private_name",
            "test_or_example_name",
            "environment_probe_name",
            "plotting_helper_name",
            "output_only_name",
            "remote_lookup_name",
            "operational_tool_name",
            "framework_entrypoint_signature",
            "pure_dynamic_signature",
            "external_resource_parameter",
            "sensitive_parameter",
            "opaque_runtime_parameter",
            "complex_runtime_parameter",
        }.intersection(risk_reasons),
        "risk_reasons": risk_reasons,
    }

def looks_external_resource_wrapper(name, params, docstring):
    resource_params = [param for param in params if looks_resource_parameter(param)]
    if not resource_params:
        return False
    lowered = str(name or "").lower()
    if lowered.startswith(("download_", "ingest_", "load_", "open_", "parse_", "read_", "save_", "upload_", "write_")):
        return True
    text = " ".join(str(docstring or "").lower().replace("_", " ").replace("-", " ").split())
    if not text:
        return False
    resource_words = {"directory", "file", "folder", "host", "path", "port", "uri", "url"}
    if resource_words.intersection(text.split()) and any(
        verb in text for verb in ("download", "ingest", "load", "open", "parse", "read", "save", "upload", "write")
    ):
        return True
    return any(
        str(param or "").lower().replace("_", " ") in text and resource_words.intersection(text.split())
        for param in resource_params
    )

def call_name(node):
    if isinstance(node, ast.Call):
        return call_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""

def root_name(node):
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Call):
        return root_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    return ""

def looks_global_state_import(name):
    return name.isupper() and 1 <= len(name) <= 3

def imported_global_state_names(tree):
    names = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                if looks_global_state_import(local):
                    names.add(local)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                if looks_global_state_import(local):
                    names.add(local)
    return names

def function_body_runtime_risk_reasons(node, imported_state_names=None, runtime_aliases=None):
    reasons = []
    imported_state_names = imported_state_names or set()
    dynamic_import_aliases = runtime_dynamic_import_aliases(node, runtime_aliases)
    state_object_aliases = runtime_state_object_aliases(node, {**(runtime_aliases or {}), **dynamic_import_aliases})
    path_object_aliases = runtime_path_object_aliases(node, {**(runtime_aliases or {}), **dynamic_import_aliases})
    combined_runtime_aliases = {
        **(runtime_aliases or {}),
        **dynamic_import_aliases,
        **state_object_aliases,
        **path_object_aliases,
    }
    network_client_names = runtime_network_client_names(node, combined_runtime_aliases)
    network_server_names = runtime_network_server_names(node, combined_runtime_aliases)
    network_socket_names = runtime_network_socket_names(node, combined_runtime_aliases)
    background_worker_names = runtime_background_worker_names(node, combined_runtime_aliases)
    getattr_call_aliases = runtime_getattr_call_aliases(node, combined_runtime_aliases)
    partial_call_aliases = runtime_partial_call_aliases(node, combined_runtime_aliases)
    for child in ast.walk(node):
        if node_mutates_runtime_environment(child, combined_runtime_aliases):
            reasons.append("environment_mutation")
            continue
        if node_mutates_runtime_process_state(child, combined_runtime_aliases):
            reasons.append("process_state_mutation")
            continue
        if not isinstance(child, ast.Call):
            continue
        name = call_name(child.func)
        lowered = (
            literal_dynamic_import_runtime_call_name(child.func, combined_runtime_aliases)
            or literal_getattr_attribute_runtime_call_name(child.func, combined_runtime_aliases)
            or path_object_runtime_call_name(child.func, combined_runtime_aliases)
            or literal_getattr_runtime_call_name(child.func, combined_runtime_aliases)
            or literal_partial_runtime_call_name(child.func, combined_runtime_aliases)
            or resolve_runtime_call_name(name, combined_runtime_aliases)
        )
        lowered = getattr_call_aliases.get(lowered, lowered)
        lowered = partial_call_aliases.get(lowered, lowered)
        if lowered in {"input", "builtins.input"}:
            reasons.append("interactive_input")
        if lowered in UNSAFE_DYNAMIC_CODE_CALLS:
            reasons.append("dynamic_code_execution")
        if call_mutates_runtime_environment(lowered):
            reasons.append("environment_mutation")
        if call_mutates_runtime_process_state(lowered):
            reasons.append("process_state_mutation")
        if call_starts_runtime_background_execution(lowered) or (
            root_name(child.func) in background_worker_names
            and lowered.rsplit(".", 1)[-1] in RUNTIME_BACKGROUND_EXECUTION_METHODS
        ):
            reasons.append("background_execution")
        if root_name(child.func) in imported_state_names:
            reasons.append("global_state_dependency")
        if lowered in UNSAFE_PROCESS_CALLS:
            reasons.append("process_execution")
        if call_performs_runtime_network_operation(lowered) or (
            root_name(child.func) in network_socket_names
            and lowered.rsplit(".", 1)[-1] in RUNTIME_NETWORK_SOCKET_METHODS
        ) or (
            root_name(child.func) in network_client_names
            and lowered.rsplit(".", 1)[-1] in RUNTIME_NETWORK_CLIENT_METHODS
        ) or (
            root_name(child.func) in network_server_names
            and lowered.rsplit(".", 1)[-1] in RUNTIME_NETWORK_SERVER_METHODS
        ):
            reasons.append("network_operation")
        if (
            (
                lowered in UNSAFE_FILE_READ_CALLS
                or lowered in MODE_SENSITIVE_FILE_OPEN_CALLS
            )
            and not call_file_open_mode_writes(child, lowered)
            or lowered.endswith((".read_bytes", ".read_text"))
            or call_reads_runtime_path_literal(child)
            or call_connects_runtime_database_path(child, lowered)
        ):
            reasons.append("file_read")
        if lowered in UNSAFE_FILE_MUTATION_CALLS or lowered.endswith(
            (
                ".chmod",
                ".hardlink_to",
                ".lchmod",
                ".mkdir",
                ".rename",
                ".replace",
                ".rmdir",
                ".symlink_to",
                ".touch",
                ".unlink",
                ".write_bytes",
                ".write_text",
            )
        ) or call_exports_runtime_path_literal(child, lowered) or (
            call_is_mode_sensitive_file_open(name, lowered)
            and call_file_open_mode_writes(child, lowered)
        ):
            reasons.append("file_mutation")
        if lowered == "os.open":
            if os_open_call_mutates_file(child, combined_runtime_aliases):
                reasons.append("file_mutation")
            else:
                reasons.append("file_read")
        elif call_is_mode_sensitive_file_open(name, lowered):
            if call_file_open_mode_writes(child, lowered):
                reasons.append("file_mutation")
            else:
                reasons.append("file_read")
        if name.endswith((".write", ".writelines")):
            reasons.append("file_mutation")
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and root_name(child.value) in imported_state_names:
            reasons.append("global_state_dependency")
    unique = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique[:8]

def return_value_is_none(value):
    if value is None:
        return True
    return isinstance(value, ast.Constant) and value.value is None

def function_body_without_docstring(node):
    body = list(getattr(node, "body", []) or [])
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body

def function_body_is_unsupported_placeholder(node):
    body = function_body_without_docstring(node)
    if not body:
        return True
    if all(
        isinstance(statement, ast.Pass)
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        )
        for statement in body
    ):
        return True
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Raise):
        exc_name = call_name(statement.exc)
        return exc_name.endswith("NotImplementedError")
    if isinstance(statement, ast.Return):
        value = statement.value
        if return_value_is_none(value):
            return True
        return isinstance(value, ast.Name) and value.id == "NotImplemented"
    return False

def function_has_value_return(node):
    class ReturnVisitor(ast.NodeVisitor):
        def __init__(self):
            self.found = False

        def visit_FunctionDef(self, child):
            if child is node:
                self.generic_visit(child)

        def visit_AsyncFunctionDef(self, child):
            if child is node:
                self.generic_visit(child)

        def visit_ClassDef(self, child):
            return None

        def visit_Lambda(self, child):
            return None

        def visit_Return(self, child):
            if not return_value_is_none(child.value):
                self.found = True

    visitor = ReturnVisitor()
    visitor.visit(node)
    return visitor.found

def function_detail(node, imported_state_names=None, runtime_aliases=None, *, skip_implicit_receiver=False):
    params, param_details, has_varargs, has_kwargs = signature_details(node, skip_implicit_receiver=skip_implicit_receiver)
    docstring = ast.get_docstring(node) or ""
    assessment = wrapper_assessment(node.name, params, has_varargs, has_kwargs, docstring)
    body_risks = function_body_runtime_risk_reasons(node, imported_state_names, runtime_aliases)
    return_annotation = annotation_to_str(node.returns)
    void_return = return_annotation.strip().lower() in {"none", "nonetype"} or not function_has_value_return(node)
    unsupported_placeholder = function_body_is_unsupported_placeholder(node)
    is_async = isinstance(node, ast.AsyncFunctionDef)
    risk_reasons = list(
        dict.fromkeys(
            [
                *assessment["risk_reasons"],
                *body_risks,
                *(["unsupported_placeholder"] if unsupported_placeholder else []),
                *(["void_return"] if void_return else []),
                *(["async_function"] if is_async else []),
            ]
        )
    )
    score = max(
        assessment["score"]
        - (60 if body_risks else 0)
        - (80 if unsupported_placeholder and not void_return else 0)
        - (80 if void_return else 0)
        - (80 if is_async else 0),
        0,
    )
    recommended = assessment["recommended"] and not body_risks and not unsupported_placeholder and not void_return and not is_async
    return {
        "name": node.name,
        "parameters": params,
        "parameter_details": param_details,
        "return_annotation": return_annotation,
        "docstring": docstring[:500],
        "line": getattr(node, "lineno", 0),
        "is_async": is_async,
        "has_varargs": has_varargs,
        "has_kwargs": has_kwargs,
        "wrapper_score": score,
        "wrapper_recommended": recommended,
        "risk_reasons": risk_reasons,
    }

def module_import_roots(tree):
    roots = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".")[0]
                if root:
                    roots.add(root)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root = node.module.split(".")[0]
            if root:
                roots.add(root)
    return sorted(roots)

DANGEROUS_INTERACTIVE_IMPORTS = {"keyboard", "pynput"}
UNSAFE_DYNAMIC_CODE_CALLS = {"builtins.compile", "builtins.eval", "builtins.exec", "compile", "eval", "exec"}
UNSAFE_PROCESS_CALLS = {
    "compile_run_strings",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.fork",
    "os.forkpty",
    "os.popen",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
    "os.startfile",
    "os.system",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "subprocess.popen",
    "subprocess.run",
    "webbrowser.open",
    "webbrowser.open_new",
    "webbrowser.open_new_tab",
}
UNSAFE_BACKGROUND_EXECUTION_CALLS = {
    "_thread.start_new_thread",
    "asyncio.create_task",
    "asyncio.ensure_future",
    "asyncio.run_coroutine_threadsafe",
    "thread.start_new_thread",
    "multiprocessing.process.start",
    "threading.thread.start",
    "threading.timer.start",
}
RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS = {
    "concurrent.futures.processpoolexecutor",
    "concurrent.futures.threadpoolexecutor",
    "multiprocessing.pool",
    "multiprocessing.process",
    "threading.thread",
    "threading.timer",
}
RUNTIME_BACKGROUND_EXECUTION_METHODS = {
    "apply",
    "apply_async",
    "imap",
    "imap_unordered",
    "map",
    "map_async",
    "starmap",
    "starmap_async",
    "start",
    "submit",
}
UNSAFE_PROCESS_STATE_MUTATION_CALLS = {
    "atexit.register",
    "atexit.unregister",
    "logging.basicconfig",
    "logging.config.dictconfig",
    "logging.config.fileconfig",
    "os.chdir",
    "os.chroot",
    "os.fchdir",
    "os.nice",
    "os.setegid",
    "os.seteuid",
    "os.setgid",
    "os.setgroups",
    "os.setpgid",
    "os.setpgrp",
    "os.setsid",
    "os.setuid",
    "os.umask",
    "signal.signal",
    "warnings.filterwarnings",
    "warnings.resetwarnings",
    "warnings.simplefilter",
}
RUNTIME_PROCESS_STATE_MUTATION_TARGETS = {
    "sys.meta_path",
    "sys.modules",
    "sys.path",
    "sys.path_hooks",
    "sys.path_importer_cache",
}
RUNTIME_PROCESS_STATE_MUTATION_METHODS = {
    "__delitem__",
    "__iadd__",
    "__ior__",
    "__setitem__",
    "append",
    "clear",
    "extend",
    "insert",
    "pop",
    "popitem",
    "remove",
    "reverse",
    "setdefault",
    "sort",
    "update",
}
UNSAFE_NETWORK_CALLS = {
    "aiohttp.request",
    "httpx.delete",
    "httpx.get",
    "httpx.head",
    "httpx.options",
    "httpx.patch",
    "httpx.post",
    "httpx.put",
    "httpx.request",
    "httpx.stream",
    "requests.delete",
    "requests.get",
    "requests.head",
    "requests.options",
    "requests.patch",
    "requests.post",
    "requests.put",
    "requests.request",
    "socket.create_connection",
    "socket.create_server",
    "urllib.request.urlretrieve",
    "urllib.request.urlopen",
    "urllib3.request",
}
RUNTIME_NETWORK_CLIENT_CONSTRUCTORS = {
    "aiohttp.clientsession",
    "ftplib.ftp",
    "ftplib.ftp_tls",
    "http.client.httpconnection",
    "http.client.httpsconnection",
    "httpx.asyncclient",
    "httpx.client",
    "imaplib.imap4",
    "imaplib.imap4_ssl",
    "mysql.connector.connect",
    "poplib.pop3",
    "poplib.pop3_ssl",
    "psycopg.connect",
    "psycopg2.connect",
    "pymongo.mongoclient",
    "redis.from_url",
    "redis.redis",
    "redis.strictredis",
    "requests.session",
    "requests.sessions.session",
    "smtplib.smtp",
    "smtplib.smtp_ssl",
    "sqlalchemy.create_engine",
    "sqlalchemy.engine.create_engine",
    "telnetlib.telnet",
    "urllib.request.build_opener",
    "urllib3.poolmanager",
    "urllib3.proxymanager",
    "xmlrpc.client.serverproxy",
}
RUNTIME_NETWORK_CLIENT_METHODS = {
    "command",
    "commit",
    "connect",
    "cursor",
    "delete_one",
    "execute",
    "executemany",
    "fetch",
    "find",
    "find_one",
    "get",
    "getresponse",
    "insert_one",
    "login",
    "open",
    "ping",
    "query",
    "request",
    "retrbinary",
    "rollback",
    "search",
    "send",
    "sendmail",
    "set",
    "storbinary",
    "update_one",
    "write",
}
RUNTIME_NETWORK_SOCKET_CONSTRUCTORS = {"socket.socket"}
RUNTIME_NETWORK_SOCKET_METHODS = {
    "accept",
    "bind",
    "connect",
    "connect_ex",
    "listen",
    "recv",
    "recv_into",
    "recvfrom",
    "recvfrom_into",
    "send",
    "sendall",
    "sendmsg",
    "sendto",
}
RUNTIME_NETWORK_SERVER_CONSTRUCTORS = {
    "http.server.httpserver",
    "http.server.threadinghttpserver",
    "socketserver.tcpserver",
    "socketserver.threadingtcpserver",
    "socketserver.threadingudpserver",
    "socketserver.udpserver",
    "wsgiref.simple_server.make_server",
}
RUNTIME_NETWORK_SERVER_METHODS = {
    "handle_request",
    "serve_forever",
    "server_activate",
    "server_bind",
}
UNSAFE_FILE_MUTATION_CALLS = {
    "dbm.dumb.open",
    "dbm.gnu.open",
    "dbm.ndbm.open",
    "dbm.open",
    "os.chmod",
    "os.chown",
    "os.link",
    "os.makedirs",
    "os.mkdir",
    "os.remove",
    "os.rename",
    "os.replace",
    "os.rmdir",
    "os.symlink",
    "os.unlink",
    "os.utime",
    "shutil.chown",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.copyfileobj",
    "shutil.copymode",
    "shutil.copystat",
    "shutil.copytree",
    "shutil.make_archive",
    "shutil.move",
    "shutil.rmtree",
    "shelve.open",
    "tempfile.mkdtemp",
    "tempfile.mkstemp",
    "tempfile.namedtemporaryfile",
    "tempfile.spooledtemporaryfile",
    "tempfile.temporarydirectory",
    "tempfile.temporaryfile",
}
UNSAFE_FILE_READ_CALLS = {
    "bz2.open",
    "configparser.configparser.read",
    "fileinput.fileinput",
    "fileinput.fileinput.input",
    "fileinput.input",
    "glob.glob",
    "glob.iglob",
    "gzip.open",
    "h5py.file",
    "joblib.load",
    "lzma.open",
    "numpy.load",
    "numpy.loadtxt",
    "numpy.genfromtxt",
    "numpy.fromfile",
    "numpy.memmap",
    "os.lstat",
    "os.listdir",
    "os.path.exists",
    "os.path.getatime",
    "os.path.getctime",
    "os.path.getmtime",
    "os.path.getsize",
    "os.path.isdir",
    "os.path.isfile",
    "os.path.islink",
    "os.path.ismount",
    "os.path.lexists",
    "os.path.samefile",
    "os.readlink",
    "os.scandir",
    "os.stat",
    "os.statvfs",
    "os.walk",
    "pandas.read_csv",
    "pandas.read_excel",
    "pandas.read_feather",
    "pandas.read_hdf",
    "pandas.read_json",
    "pandas.read_orc",
    "pandas.read_parquet",
    "pandas.read_pickle",
    "pandas.read_sas",
    "pandas.read_stata",
    "pathlib.path.read_bytes",
    "pathlib.path.read_text",
    "pathlib.path.exists",
    "pathlib.path.glob",
    "pathlib.path.group",
    "pathlib.path.is_block_device",
    "pathlib.path.is_char_device",
    "pathlib.path.is_dir",
    "pathlib.path.is_fifo",
    "pathlib.path.is_file",
    "pathlib.path.is_mount",
    "pathlib.path.is_socket",
    "pathlib.path.is_symlink",
    "pathlib.path.iterdir",
    "pathlib.path.lstat",
    "pathlib.path.owner",
    "pathlib.path.rglob",
    "pathlib.path.readlink",
    "pathlib.path.samefile",
    "pathlib.path.stat",
    "pathlib.path.walk",
    "pickle.load",
    "polars.read_csv",
    "polars.read_excel",
    "polars.read_ipc",
    "polars.read_json",
    "polars.read_parquet",
    "scipy.io.loadmat",
    "tarfile.open",
    "linecache.getline",
    "linecache.getlines",
    "tokenize.open",
    "torch.load",
    "zipfile.zipfile",
}
OS_OPEN_FILE_MUTATION_FLAGS = {
    "os.o_append",
    "os.o_creat",
    "os.o_excl",
    "os.o_rdwr",
    "os.o_trunc",
    "os.o_wronly",
}
OS_OPEN_FILE_MUTATION_FLAG_VALUES = tuple(
    value
    for value in (
        getattr(os, "O_APPEND", None),
        getattr(os, "O_CREAT", None),
        getattr(os, "O_EXCL", None),
        getattr(os, "O_RDWR", None),
        getattr(os, "O_TRUNC", None),
        getattr(os, "O_WRONLY", None),
    )
    if isinstance(value, int)
)
MODE_SENSITIVE_FILE_OPEN_CALLS = {
    "bz2.open",
    "builtins.open",
    "gzip.open",
    "h5py.file",
    "io.fileio",
    "io.open",
    "lzma.open",
    "open",
    "os.fdopen",
    "pathlib.path.open",
    "tarfile.open",
    "zipfile.zipfile",
}
RUNTIME_PATH_OBJECT_RETURNING_METHODS = {
    "absolute",
    "expanduser",
    "joinpath",
    "relative_to",
    "resolve",
    "with_name",
    "with_stem",
    "with_suffix",
}
RUNTIME_PATH_OBJECT_RETURNING_ATTRIBUTES = {"parent"}
RUNTIME_PATH_SEQUENCE_ATTRIBUTES = {"parents"}
RUNTIME_ALIAS_MODULES = {
    "_thread",
    "aiohttp",
    "atexit",
    "asyncio",
    "builtins",
    "bz2",
    "concurrent.futures",
    "configparser",
    "dbm",
    "dbm.dumb",
    "dbm.gnu",
    "dbm.ndbm",
    "fileinput",
    "functools",
    "glob",
    "gzip",
    "h5py",
    "ftplib",
    "http.client",
    "http.server",
    "httpx",
    "imaplib",
    "importlib",
    "io",
    "joblib",
    "linecache",
    "logging",
    "lzma",
    "multiprocessing",
    "mysql.connector",
    "numpy",
    "os",
    "os.path",
    "pandas",
    "pathlib",
    "pickle",
    "polars",
    "poplib",
    "psycopg",
    "psycopg2",
    "pymongo",
    "redis",
    "requests",
    "requests.sessions",
    "scipy.io",
    "shutil",
    "signal",
    "socket",
    "socketserver",
    "shelve",
    "smtplib",
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlite3",
    "subprocess",
    "sys",
    "tarfile",
    "telnetlib",
    "tempfile",
    "threading",
    "tokenize",
    "torch",
    "urllib.request",
    "urllib3",
    "warnings",
    "webbrowser",
    "wsgiref.simple_server",
    "xmlrpc.client",
    "zipfile",
}
RUNTIME_PATH_LITERAL_EXTENSIONS = {
    ".bz2",
    ".cfg",
    ".conf",
    ".csv",
    ".db",
    ".feather",
    ".gif",
    ".gz",
    ".htm",
    ".html",
    ".h5",
    ".hdf",
    ".hdf5",
    ".ini",
    ".joblib",
    ".json",
    ".jsonl",
    ".mat",
    ".md",
    ".npy",
    ".npz",
    ".parquet",
    ".pickle",
    ".pkl",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".svg",
    ".pt",
    ".pth",
    ".safetensors",
    ".tar",
    ".tex",
    ".tif",
    ".tiff",
    ".toml",
    ".tsv",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
    ".xz",
    ".yaml",
    ".yml",
    ".webp",
    ".zip",
}
OPAQUE_WRAPPER_PARAM_NAMES = {
    "self",
    "cls",
    "binop",
    "rbinop",
    "mapping",
    "mappings",
    "precedence_list",
    "degrees",
    "seq",
    "sequence",
}
COMPLEX_RUNTIME_WRAPPER_PARAM_NAMES = {
    "app",
    "callback",
    "callbacks",
    "client",
    "config",
    "configs",
    "connection",
    "context",
    "cursor",
    "dataframe",
    "dataset",
    "df",
    "executor",
    "handler",
    "model",
    "models",
    "namespace",
    "parser",
    "request",
    "response",
    "session",
    "tensor",
}

def runtime_call_aliases(tree):
    aliases = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                canonical = alias.name
                if canonical in RUNTIME_ALIAS_MODULES:
                    if alias.asname:
                        aliases[alias.asname.lower()] = canonical
                    elif "." not in canonical:
                        aliases[canonical.lower()] = canonical
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in RUNTIME_ALIAS_MODULES:
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[(alias.asname or alias.name).lower()] = f"{node.module}.{alias.name}"
    return aliases

def resolve_runtime_call_name(name, aliases=None):
    lowered = str(name or "").lower()
    aliases = aliases or {}
    if lowered in aliases:
        return aliases[lowered].lower()
    if "." not in lowered:
        return lowered
    root, rest = lowered.split(".", 1)
    if root in aliases:
        alias_target = aliases[root].lower()
        first, _, tail = rest.partition(".")
        if "." in alias_target and alias_target.rsplit(".", 1)[-1] == first:
            return f"{alias_target}.{tail}" if tail else alias_target
        return f"{alias_target}.{rest}"
    return lowered

def literal_getattr_runtime_call_name(call, runtime_aliases=None):
    if not isinstance(call, ast.Call) or call_name(call.func) != "getattr" or len(call.args) < 2:
        return ""
    attr = call.args[1]
    if not isinstance(attr, ast.Constant) or not isinstance(attr.value, str) or not attr.value:
        return ""
    root = call_name(call.args[0])
    if not root:
        return ""
    return resolve_runtime_call_name(f"{root}.{attr.value}", runtime_aliases)

def literal_getattr_attribute_runtime_call_name(func, runtime_aliases=None):
    attrs = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    base = literal_getattr_runtime_call_name(node if isinstance(node, ast.Call) else None, runtime_aliases)
    if not base or not attrs:
        return ""
    return resolve_runtime_call_name(".".join([base, *reversed(attrs)]), runtime_aliases)

def literal_partial_runtime_call_name(call, runtime_aliases=None):
    if (
        not isinstance(call, ast.Call)
        or resolve_runtime_call_name(call_name(call.func), runtime_aliases) != "functools.partial"
        or not call.args
    ):
        return ""
    target = call.args[0]
    return (
        literal_getattr_attribute_runtime_call_name(target, runtime_aliases)
        or literal_getattr_runtime_call_name(target if isinstance(target, ast.Call) else None, runtime_aliases)
        or resolve_runtime_call_name(call_name(target), runtime_aliases)
    )

def literal_dynamic_import_module_name(call, runtime_aliases=None):
    if not isinstance(call, ast.Call) or not call.args:
        return ""
    lowered = resolve_runtime_call_name(call_name(call.func), runtime_aliases)
    if lowered not in {"__import__", "builtins.__import__", "importlib.import_module"}:
        return ""
    module_arg = call.args[0]
    if not isinstance(module_arg, ast.Constant) or not isinstance(module_arg.value, str):
        return ""
    module_name = module_arg.value.strip()
    if module_name not in RUNTIME_ALIAS_MODULES:
        return ""
    return module_name

def literal_dynamic_import_runtime_call_name(func, runtime_aliases=None):
    attrs = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    module_name = literal_dynamic_import_module_name(node if isinstance(node, ast.Call) else None, runtime_aliases)
    if not module_name or not attrs:
        return ""
    return resolve_runtime_call_name(".".join([module_name] + list(reversed(attrs))), runtime_aliases)

def path_object_returning_call_name(call, runtime_aliases=None):
    if not isinstance(call, ast.Call):
        return ""
    lowered = resolve_runtime_call_name(call_name(call.func), runtime_aliases)
    if lowered in {"pathlib.path", "pathlib.path.cwd", "pathlib.path.home"}:
        return "pathlib.path"
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr.lower() in RUNTIME_PATH_OBJECT_RETURNING_METHODS
        and node_resolves_to_path_object(call.func.value, runtime_aliases)
    ):
        return "pathlib.path"
    return ""

def node_resolves_to_path_object(node, runtime_aliases=None):
    if isinstance(node, ast.Name):
        return resolve_runtime_call_name(node.id, runtime_aliases) == "pathlib.path"
    if isinstance(node, ast.Call):
        return bool(path_object_returning_call_name(node, runtime_aliases))
    if (
        isinstance(node, ast.Attribute)
        and node.attr.lower() in RUNTIME_PATH_OBJECT_RETURNING_ATTRIBUTES
        and node_resolves_to_path_object(node.value, runtime_aliases)
    ):
        return True
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr.lower() in RUNTIME_PATH_SEQUENCE_ATTRIBUTES
        and node_resolves_to_path_object(node.value.value, runtime_aliases)
    ):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return node_resolves_to_path_object(node.left, runtime_aliases) or node_resolves_to_path_object(
            node.right,
            runtime_aliases,
        )
    return False

def path_object_runtime_call_name(func, runtime_aliases=None):
    if not isinstance(func, ast.Attribute) or not node_resolves_to_path_object(func.value, runtime_aliases):
        return ""
    return resolve_runtime_call_name(f"pathlib.path.{func.attr}", runtime_aliases)

def literal_looks_like_runtime_path(value):
    text = str(value or "").strip()
    if not text or "\n" in text or "\r" in text:
        return False
    lowered = text.lower().rstrip("*?")
    if lowered.startswith(("http://", "https://")):
        return False
    if "://" in lowered or "/" in text or "\\" in text:
        return True
    if lowered.startswith((".", "~")):
        return True
    return os.path.splitext(lowered)[1] in RUNTIME_PATH_LITERAL_EXTENSIONS

def node_contains_runtime_path_literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return literal_looks_like_runtime_path(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(node_contains_runtime_path_literal(item) for item in node.elts)
    return False

def node_contains_runtime_database_path_literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip()
        lowered = text.lower()
        if lowered == ":memory:" or lowered.startswith("file::memory:"):
            return False
        if lowered.startswith("file:"):
            return True
        return literal_looks_like_runtime_path(text)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(node_contains_runtime_database_path_literal(item) for item in node.elts)
    return False

def call_reads_runtime_path_literal(call):
    name = call_name(call.func).lower()
    if not name.endswith(".read"):
        return False
    candidates = list(call.args[:1])
    candidates.extend(
        keyword.value
        for keyword in call.keywords or []
        if keyword.arg in {"file", "filename", "filenames", "path", "source"}
    )
    return any(node_contains_runtime_path_literal(candidate) for candidate in candidates)

def call_connects_runtime_database_path(call, lowered):
    if lowered != "sqlite3.connect":
        return False
    candidates = list(call.args[:1])
    candidates.extend(keyword.value for keyword in call.keywords or [] if keyword.arg == "database")
    return any(node_contains_runtime_database_path_literal(candidate) for candidate in candidates)

def open_call_mode(call, lowered):
    if lowered == "pathlib.path.open":
        positional_mode_index = 0
    else:
        positional_mode_index = 1
    if len(call.args) > positional_mode_index and isinstance(call.args[positional_mode_index], ast.Constant):
        return str(call.args[positional_mode_index].value or "")
    for keyword_node in call.keywords or []:
        if keyword_node.arg == "mode" and isinstance(keyword_node.value, ast.Constant):
            return str(keyword_node.value.value or "")
    return ""

def call_is_mode_sensitive_file_open(name, lowered):
    return lowered in MODE_SENSITIVE_FILE_OPEN_CALLS or name.endswith(".open")

def call_file_open_mode_writes(call, lowered):
    mode = open_call_mode(call, lowered)
    return bool(mode and any(flag in mode for flag in ("a", "w", "x", "+")))

def node_int_bit_or_value(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = node_int_bit_or_value(node.left)
        right = node_int_bit_or_value(node.right)
        if left is not None and right is not None:
            return left | right
    return None

def node_contains_os_open_mutation_flag(node, runtime_aliases=None):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return node_contains_os_open_mutation_flag(
            node.left,
            runtime_aliases,
        ) or node_contains_os_open_mutation_flag(node.right, runtime_aliases)
    flag_name = resolve_runtime_call_name(call_name(node), runtime_aliases)
    if flag_name in OS_OPEN_FILE_MUTATION_FLAGS:
        return True
    flag_value = node_int_bit_or_value(node)
    return flag_value is not None and any(flag_value & value for value in OS_OPEN_FILE_MUTATION_FLAG_VALUES)

def os_open_call_mutates_file(call, runtime_aliases=None):
    candidates = list(call.args[1:2])
    candidates.extend(keyword.value for keyword in call.keywords or [] if keyword.arg == "flags")
    return any(node_contains_os_open_mutation_flag(candidate, runtime_aliases) for candidate in candidates)

def call_exports_runtime_path_literal(call, lowered):
    if not (
        lowered in {
            "joblib.dump",
            "numpy.save",
            "numpy.savetxt",
            "numpy.savez",
            "numpy.savez_compressed",
            "scipy.io.savemat",
            "shutil.unpack_archive",
            "torch.save",
        }
        or lowered.endswith(
            (
                ".extract",
                ".extractall",
                ".to_csv",
                ".to_excel",
                ".to_feather",
                ".to_hdf",
                ".to_html",
                ".to_json",
                ".to_latex",
                ".to_markdown",
                ".to_orc",
                ".to_parquet",
                ".to_pickle",
                ".to_stata",
                ".to_xml",
                ".save",
                ".savefig",
                ".write_csv",
                ".write_excel",
                ".write_ipc",
                ".write_json",
                ".write_parquet",
            )
        )
    ):
        return False
    candidates = list(call.args[:2])
    candidates.extend(
        keyword.value
        for keyword in call.keywords or []
        if keyword.arg in {"buf", "file", "filename", "path", "path_or_buf", "path_or_buffer", "excel_writer"}
    )
    return any(node_contains_runtime_path_literal(candidate) for candidate in candidates)

def call_mutates_runtime_environment(lowered):
    if lowered in {"os.putenv", "os.unsetenv"}:
        return True
    prefix = "os.environ."
    if lowered.startswith(prefix):
        return lowered[len(prefix):] in {"__delitem__", "__ior__", "__setitem__", "clear", "pop", "popitem", "setdefault", "update"}
    return False

def reflected_runtime_state_target(call, runtime_aliases=None):
    lowered = resolve_runtime_call_name(call_name(call.func), runtime_aliases)
    if lowered not in {"builtins.delattr", "builtins.setattr", "delattr", "setattr"} or len(call.args) < 2:
        return ""
    attr = call.args[1]
    if not isinstance(attr, ast.Constant) or not isinstance(attr.value, str) or not attr.value:
        return ""
    root = call_name(call.args[0])
    if not root:
        return ""
    return resolve_runtime_call_name(f"{root}.{attr.value}", runtime_aliases)

def target_mutates_runtime_environment(target, runtime_aliases=None):
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(target_mutates_runtime_environment(item, runtime_aliases) for item in target.elts)
    if isinstance(target, ast.Name):
        return False
    candidate = target.value if isinstance(target, ast.Subscript) else target
    name = literal_getattr_runtime_call_name(
        candidate if isinstance(candidate, ast.Call) else None,
        runtime_aliases,
    ) or resolve_runtime_call_name(call_name(candidate), runtime_aliases)
    return name == "os.environ"

def node_mutates_runtime_environment(node, runtime_aliases=None):
    if isinstance(node, ast.Call):
        return reflected_runtime_state_target(node, runtime_aliases) == "os.environ"
    if isinstance(node, ast.Assign):
        return any(target_mutates_runtime_environment(target, runtime_aliases) for target in node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return target_mutates_runtime_environment(node.target, runtime_aliases)
    if isinstance(node, ast.Delete):
        return any(target_mutates_runtime_environment(target, runtime_aliases) for target in node.targets)
    return False

def call_mutates_runtime_process_state(lowered):
    if lowered in UNSAFE_PROCESS_STATE_MUTATION_CALLS:
        return True
    for target in RUNTIME_PROCESS_STATE_MUTATION_TARGETS:
        prefix = f"{target}."
        if lowered.startswith(prefix):
            return lowered[len(prefix):] in RUNTIME_PROCESS_STATE_MUTATION_METHODS
    return False

def target_mutates_runtime_process_state(target, runtime_aliases=None):
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(target_mutates_runtime_process_state(item, runtime_aliases) for item in target.elts)
    if isinstance(target, ast.Name):
        return False
    candidate = target.value if isinstance(target, ast.Subscript) else target
    name = literal_getattr_runtime_call_name(
        candidate if isinstance(candidate, ast.Call) else None,
        runtime_aliases,
    ) or resolve_runtime_call_name(call_name(candidate), runtime_aliases)
    return name in RUNTIME_PROCESS_STATE_MUTATION_TARGETS

def node_mutates_runtime_process_state(node, runtime_aliases=None):
    if isinstance(node, ast.Call):
        return reflected_runtime_state_target(node, runtime_aliases) in RUNTIME_PROCESS_STATE_MUTATION_TARGETS
    if isinstance(node, ast.Assign):
        return any(target_mutates_runtime_process_state(target, runtime_aliases) for target in node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return target_mutates_runtime_process_state(node.target, runtime_aliases)
    if isinstance(node, ast.Delete):
        return any(target_mutates_runtime_process_state(target, runtime_aliases) for target in node.targets)
    return False

def call_performs_runtime_network_operation(lowered):
    if lowered in UNSAFE_NETWORK_CALLS:
        return True
    if lowered in RUNTIME_NETWORK_CLIENT_CONSTRUCTORS:
        return True
    if lowered in RUNTIME_NETWORK_SERVER_CONSTRUCTORS:
        return True
    for constructor in RUNTIME_NETWORK_CLIENT_CONSTRUCTORS:
        prefix = f"{constructor}."
        if lowered.startswith(prefix):
            return lowered[len(prefix):] in RUNTIME_NETWORK_CLIENT_METHODS
    for constructor in RUNTIME_NETWORK_SOCKET_CONSTRUCTORS:
        prefix = f"{constructor}."
        if lowered.startswith(prefix):
            return lowered[len(prefix):] in RUNTIME_NETWORK_SOCKET_METHODS
    for constructor in RUNTIME_NETWORK_SERVER_CONSTRUCTORS:
        prefix = f"{constructor}."
        if lowered.startswith(prefix):
            return lowered[len(prefix):] in RUNTIME_NETWORK_SERVER_METHODS
    return False

def assigned_call_target_names(node, runtime_aliases, constructors):
    names = set()
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                value = item.context_expr
                if not isinstance(value, ast.Call):
                    continue
                lowered = resolve_runtime_call_name(call_name(value.func), runtime_aliases)
                if lowered in constructors and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
            continue
        if not isinstance(value, ast.Call):
            continue
        lowered = resolve_runtime_call_name(call_name(value.func), runtime_aliases)
        if lowered not in constructors:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names

def runtime_network_socket_names(node, runtime_aliases=None):
    return assigned_call_target_names(node, runtime_aliases, RUNTIME_NETWORK_SOCKET_CONSTRUCTORS)

def runtime_network_client_names(node, runtime_aliases=None):
    return assigned_call_target_names(node, runtime_aliases, RUNTIME_NETWORK_CLIENT_CONSTRUCTORS)

def runtime_network_server_names(node, runtime_aliases=None):
    return assigned_call_target_names(node, runtime_aliases, RUNTIME_NETWORK_SERVER_CONSTRUCTORS)

def call_starts_runtime_background_execution(lowered):
    if lowered in UNSAFE_BACKGROUND_EXECUTION_CALLS:
        return True
    for constructor in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS:
        prefix = f"{constructor}."
        if lowered.startswith(prefix):
            return lowered[len(prefix):] in RUNTIME_BACKGROUND_EXECUTION_METHODS
    return False

def runtime_background_worker_names(node, runtime_aliases=None):
    names = set()
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                value = item.context_expr
                if not isinstance(value, ast.Call):
                    continue
                lowered = resolve_runtime_call_name(call_name(value.func), runtime_aliases)
                if lowered in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
            continue
        if not isinstance(value, ast.Call):
            continue
        lowered = resolve_runtime_call_name(call_name(value.func), runtime_aliases)
        if lowered not in RUNTIME_BACKGROUND_EXECUTION_CONSTRUCTORS:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names

def runtime_getattr_call_aliases(node, runtime_aliases=None):
    aliases = {}
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if value is None:
            continue
        lowered = (
            literal_getattr_attribute_runtime_call_name(value, runtime_aliases)
            or literal_getattr_runtime_call_name(
                value if isinstance(value, ast.Call) else None,
                runtime_aliases,
            )
        )
        if not lowered:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = lowered
    return aliases

def runtime_partial_call_aliases(node, runtime_aliases=None):
    aliases = {}
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if not isinstance(value, ast.Call):
            continue
        lowered = literal_partial_runtime_call_name(value, runtime_aliases)
        if not lowered:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = lowered
    return aliases

def runtime_dynamic_import_aliases(node, runtime_aliases=None):
    aliases = {}
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if not isinstance(value, ast.Call):
            continue
        module_name = literal_dynamic_import_module_name(value, runtime_aliases)
        if not module_name:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = module_name
    return aliases

def runtime_path_object_aliases(node, runtime_aliases=None):
    aliases = {}
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        combined_aliases = {**(runtime_aliases or {}), **aliases}
        if not node_resolves_to_path_object(value, combined_aliases):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = "pathlib.path"
    return aliases

def runtime_state_object_aliases(node, runtime_aliases=None):
    aliases = {}
    mutation_targets = {"os.environ"} | RUNTIME_PROCESS_STATE_MUTATION_TARGETS
    for child in ast.walk(node):
        targets = []
        value = None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        if value is None:
            continue
        target_name = literal_getattr_runtime_call_name(
            value if isinstance(value, ast.Call) else None,
            runtime_aliases,
        ) or resolve_runtime_call_name(call_name(value), runtime_aliases)
        if target_name not in mutation_targets:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id.lower()] = target_name
    return aliases

def apply_module_runtime_risks(function_details, module_imports):
    imports = {str(item).split(".")[0].lower() for item in module_imports or []}
    if not imports.intersection(DANGEROUS_INTERACTIVE_IMPORTS):
        return
    for detail in function_details.values():
        reasons = list(detail.get("risk_reasons") or [])
        if "keyboard_listener_dependency" not in reasons:
            reasons.append("keyboard_listener_dependency")
        detail["risk_reasons"] = reasons
        detail["wrapper_score"] = max(int(detail.get("wrapper_score", 0) or 0) - 80, 0)
        detail["wrapper_recommended"] = False

SAFE_TOP_LEVEL_CALLS = {"collections.namedtuple", "dict", "frozenset", "list", "logging.getLogger", "re.compile", "re.escape", "set", "tuple"}

def is_main_guard(node):
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    if not isinstance(left, ast.Name) or left.id != "__name__":
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    return isinstance(right, ast.Constant) and right.value == "__main__"

def is_type_checking_guard(node):
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"

def safe_call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = safe_call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""

def safe_top_level_value(node):
    if node is None:
        return True
    if isinstance(node, (ast.Constant, ast.Name, ast.Attribute)):
        return True
    if isinstance(node, ast.JoinedStr):
        return all(safe_top_level_value(item) for item in node.values)
    if isinstance(node, ast.FormattedValue):
        return safe_top_level_value(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(safe_top_level_value(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(safe_top_level_value(item) for item in list(node.keys) + list(node.values) if item is not None)
    if isinstance(node, ast.UnaryOp):
        return safe_top_level_value(node.operand)
    if isinstance(node, ast.BinOp):
        return safe_top_level_value(node.left) and safe_top_level_value(node.right)
    if isinstance(node, ast.Compare):
        return safe_top_level_value(node.left) and all(safe_top_level_value(item) for item in node.comparators)
    if isinstance(node, ast.Call):
        if safe_call_name(node.func) in SAFE_TOP_LEVEL_CALLS:
            return all(safe_top_level_value(arg) for arg in node.args) and all(
                safe_top_level_value(keyword.value) for keyword in node.keywords
            )
    return False

def safe_top_level_statement(node):
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Pass)):
        return True
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return True
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return safe_top_level_value(node.value)
    if isinstance(node, ast.If) and (is_type_checking_guard(node) or safe_top_level_value(node.test)):
        return all(safe_top_level_statement(item) for item in node.body + node.orelse)
    if isinstance(node, ast.Try):
        return (
            all(safe_top_level_statement(item) for item in node.body)
            and all(safe_top_level_statement(item) for handler in node.handlers for item in handler.body)
            and all(safe_top_level_statement(item) for item in node.orelse)
            and all(safe_top_level_statement(item) for item in node.finalbody)
        )
    return False

def module_import_side_effect_reasons(tree):
    reasons = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if safe_top_level_value(node.value):
                continue
            reasons.append(f"top_level_assignment_call:line_{getattr(node, 'lineno', 0)}")
            continue
        if isinstance(node, ast.If) and (is_main_guard(node) or is_type_checking_guard(node)):
            continue
        if isinstance(node, (ast.If, ast.Try)) and safe_top_level_statement(node):
            continue
        reasons.append(f"top_level_{type(node).__name__.lower()}:line_{getattr(node, 'lineno', 0)}")
    return reasons[:8]

def class_expr_name(node):
    if isinstance(node, ast.Subscript):
        return class_expr_name(node.value)
    return call_name(node)

def class_risk_reasons(node, methods):
    data_model_bases = {"basemodel", "basesettings"}
    enum_bases = {
        "enum",
        "enum.enum",
        "enum.flag",
        "enum.intenum",
        "enum.intflag",
        "enum.strenum",
        "flag",
        "intenum",
        "intflag",
        "strenum",
    }
    network_server_handler_bases = {
        "basehttprequesthandler",
        "http.server.basehttprequesthandler",
        "baserequesthandler",
        "socketserver.baserequesthandler",
    }
    decorators = {
        class_expr_name(decorator.func if isinstance(decorator, ast.Call) else decorator).lower()
        for decorator in getattr(node, "decorator_list", [])
    }
    bases = {class_expr_name(base).lower() for base in getattr(node, "bases", [])}
    reasons = []
    if any(name == "dataclass" or name.endswith(".dataclass") for name in decorators):
        reasons.append("data_container_class")
    if any(name in data_model_bases or name.endswith((".basemodel", ".basesettings")) for name in bases):
        reasons.append("data_model_class")
    if any(name in enum_bases for name in bases):
        reasons.append("enum_class")
    if any(name == "typeddict" or name.endswith(".typeddict") for name in bases):
        reasons.append("typed_dict_class")
    if any(name in {"tuple", "typing.tuple", "namedtuple"} or name.endswith(".namedtuple") for name in bases):
        reasons.append("tuple_container_class")
    if any(name in network_server_handler_bases for name in bases):
        reasons.append("network_server_handler_class")
    if not methods:
        reasons.append("no_public_methods")
    return reasons

def class_detail(node):
    methods = []
    constructor = None
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__":
            constructor = function_detail(child, skip_implicit_receiver=True)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
            methods.append(function_detail(child, skip_implicit_receiver=True))
    required_constructor_params = [
        detail.get("name")
        for detail in (constructor or {}).get("parameter_details", [])
        if detail.get("kind") not in {"vararg", "kwarg"} and detail.get("required")
    ]
    sensitive_constructor_params = [
        detail.get("name")
        for detail in (constructor or {}).get("parameter_details", [])
        if detail.get("kind") not in {"vararg", "kwarg"} and looks_sensitive_parameter(detail.get("name", ""))
    ]
    complex_constructor_params = [
        detail.get("name")
        for detail in (constructor or {}).get("parameter_details", [])
        if detail.get("kind") not in {"vararg", "kwarg"}
        and str(detail.get("name", "")).lower() in COMPLEX_RUNTIME_WRAPPER_PARAM_NAMES
    ]
    constructor_safe = (
        not required_constructor_params
        and not sensitive_constructor_params
        and not complex_constructor_params
        and not (constructor or {}).get("has_varargs")
        and not (constructor or {}).get("has_kwargs")
    )
    risk_reasons = class_risk_reasons(node, methods)
    if required_constructor_params:
        risk_reasons.append("constructor_requires_args")
    if sensitive_constructor_params:
        risk_reasons.append("sensitive_constructor_parameter")
    if complex_constructor_params:
        risk_reasons.append("complex_constructor_parameter")
    if (constructor or {}).get("has_varargs") or (constructor or {}).get("has_kwargs"):
        risk_reasons.append("dynamic_constructor_signature")
    wrapper_score = 75 if constructor_safe and methods else 55 if constructor_safe else 20
    non_wrapper_reasons = {
        "data_container_class",
        "data_model_class",
        "enum_class",
        "network_server_handler_class",
        "typed_dict_class",
        "tuple_container_class",
    }
    if any(reason in risk_reasons for reason in non_wrapper_reasons):
        wrapper_score = min(wrapper_score, 20)
    elif "no_public_methods" in risk_reasons:
        wrapper_score = min(wrapper_score, 35)
    return {
        "name": node.name,
        "docstring": (ast.get_docstring(node) or "")[:500],
        "line": getattr(node, "lineno", 0),
        "public_methods": methods[:12],
        "constructor_parameters": (constructor or {}).get("parameters", []),
        "constructor_parameter_details": (constructor or {}).get("parameter_details", []),
        "constructor_sensitive_parameters": sensitive_constructor_params,
        "constructor_complex_parameters": complex_constructor_params,
        "constructor_requires_args": bool(required_constructor_params),
        "constructor_has_varargs": bool((constructor or {}).get("has_varargs")),
        "constructor_has_kwargs": bool((constructor or {}).get("has_kwargs")),
        "wrapper_score": wrapper_score,
        "wrapper_recommended": constructor_safe and bool(methods) and wrapper_score >= 45,
        "risk_reasons": list(dict.fromkeys(risk_reasons)),
    }

def decorator_name(decorator):
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parent = decorator_name(target.value)
        return f"{parent}.{target.attr}" if parent else target.attr
    return ""

def has_pytest_fixture_decorator(node):
    names = {decorator_name(decorator) for decorator in getattr(node, "decorator_list", [])}
    return any(name == "fixture" or name.endswith(".fixture") for name in names)

def has_framework_entrypoint_decorator(node):
    names = {decorator_name(decorator).lower() for decorator in getattr(node, "decorator_list", [])}
    for name in names:
        if name in {"click.command", "click.group", "typer.command", "typer.callback"}:
            return True
        if name.endswith((".api_route", ".command", ".delete", ".get", ".group", ".patch", ".post", ".put", ".route", ".task", ".websocket")):
            return True
    return False

def apply_framework_entrypoint_risk(detail):
    reasons = list(detail.get("risk_reasons") or [])
    if "framework_entrypoint_decorator" not in reasons:
        reasons.append("framework_entrypoint_decorator")
    detail["risk_reasons"] = reasons
    detail["wrapper_score"] = max(int(detail.get("wrapper_score", 0) or 0) - 80, 0)
    detail["wrapper_recommended"] = False

path, module_path, rel_path = sys.argv[1:4]
code = open(path, "r", encoding="utf-8-sig", errors="ignore").read()
tree = ast.parse(code or "")
funcs = {}
function_details = {}
classes = []
class_details = {}
imported_state_names = imported_global_state_names(tree)
runtime_aliases = runtime_call_aliases(tree)
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
        if has_pytest_fixture_decorator(node):
            continue
        if any(part in node.name.lower() for part in EXCLUDED_NAME_PARTS):
            continue
        detail = function_detail(node, imported_state_names, runtime_aliases)
        if has_framework_entrypoint_decorator(node):
            apply_framework_entrypoint_risk(detail)
        funcs[node.name] = detail["parameters"]
        function_details[node.name] = detail
    elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
        if any(part in node.name.lower() for part in EXCLUDED_NAME_PARTS):
            continue
        classes.append(node.name)
        class_details[node.name] = class_detail(node)
module_imports = module_import_roots(tree)
apply_module_runtime_risks(function_details, module_imports)
wrapper_candidates = sorted(
    [
        {"name": name, "kind": "function", "score": detail["wrapper_score"]}
        for name, detail in function_details.items()
        if detail.get("wrapper_recommended")
    ] + [
        {"name": name, "kind": "class", "score": detail["wrapper_score"]}
        for name, detail in class_details.items()
        if detail.get("wrapper_recommended")
    ],
    key=lambda item: (-item["score"], item["name"]),
)
print(json.dumps({
    "functions": funcs,
    "classes": classes,
    "file_path": rel_path,
    "imports": module_imports,
    "import_side_effect_risk": bool(module_import_side_effect_reasons(tree)),
    "import_side_effect_reasons": module_import_side_effect_reasons(tree),
    "function_details": function_details,
    "class_details": class_details,
    "wrapper_candidates": wrapper_candidates[:12],
}, ensure_ascii=False))
'''
    candidates = _analysis_python_candidates()
    if not candidates:
        return None
    script_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".py",
            prefix="code2mcp_ast_scan_",
            delete=False,
        ) as handle:
            handle.write(script)
            script_path = handle.name
        for command, version in candidates:
            try:
                proc = subprocess.run(
                    command + [script_path, file_path, module_path, rel_path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    shell=False,
                    check=False,
                )
            except Exception as exc:
                logger.debug(f"AST fallback parser failed to start with {' '.join(command)}: {exc}")
                continue
            if proc.returncode != 0:
                logger.debug(f"AST fallback parser failed with {version}: {(proc.stderr or proc.stdout)[-300:]}")
                continue
            try:
                parsed = json.loads(proc.stdout)
                if parsed.get("functions") or parsed.get("classes"):
                    parsed["classes"] = set(parsed.get("classes") or [])
                    parsed["parser"] = f"external:{version}"
                    return parsed
                return None
            except Exception as exc:
                logger.debug(f"AST fallback parser returned invalid JSON with {version}: {exc}")
        return None
    finally:
        if script_path:
            try:
                os.unlink(script_path)
            except OSError:
                pass


def _scan_source_symbols_with_signatures(source_dir: str) -> Dict[str, Any]:
    symbols: Dict[str, Any] = {}
    if not (source_dir and os.path.isdir(source_dir)):
        return symbols
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and not d.lower().startswith('test') and d.lower() not in EXCLUDED_SOURCE_DIRS
        ]
        for file in files:
            if not file.endswith('.py'):
                continue
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, source_dir).replace(os.sep, "/")
            if _is_excluded_source_rel_path(rel_path):
                continue
            module_path = rel_path.replace("/", '.').replace('.py', '')
            if module_path.endswith('.__init__'):
                module_path = module_path[:-9]
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    code = f.read()
                tree = ast.parse(code or '')
                module_symbols = _module_symbols_from_tree(module_path, rel_path, tree)
                if module_symbols:
                    symbols[module_path] = module_symbols
            except Exception as exc:
                fallback_symbols = _scan_file_with_external_python(file_path, module_path, rel_path)
                if fallback_symbols:
                    symbols[module_path] = fallback_symbols
                    logger.info(f"Parsed Python source with fallback interpreter: {file_path}")
                    continue
                logger.warning(f"Failed to parse Python source during AST scan: {file_path}: {exc}")
                continue
    return symbols

def _scan_python_packages(root_dir: str) -> List[str]:
    logger.info(f"Starting Python package scan, root directory: {root_dir}")
    packages: List[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in EXCLUDED_SOURCE_DIRS and not d.startswith(".") and not d.lower().startswith("test")
            ]
            rel = os.path.relpath(dirpath, root_dir)
            if _is_excluded_source_rel_path(rel):
                continue
            if rel.count(os.sep) > 2:
                continue
            if "__init__.py" in filenames:
                pkg = rel.replace(os.sep, ".") if rel != "." else ""
                if pkg:
                    packages.append(pkg)
        return sorted(list(set(packages)))
    except Exception as e:
        logger.error(f"Error occurred while scanning Python packages: {e}")
        import traceback
        logger.error(f"Detailed error information: {traceback.format_exc()}")
        return []


def _scan_entry_points(working_dir: str) -> Dict[str, Any]:
    entry_points = {"imports": [], "cli": [], "modules": []}
    
    setup_py = os.path.join(working_dir, "setup.py")
    if os.path.exists(setup_py):
        try:
            with open(setup_py, 'r', encoding='utf-8') as f:
                content = f.read()
            
            matches = re.findall(r'console_scripts.*?\[(.*?)\]', content, re.DOTALL)
            for match in matches:
                scripts = re.findall(r'["\']([^"\']+)=([^"\']+)["\']', match)
                for script_match in scripts:
                    if len(script_match) == 2:
                        script_name, module_path = script_match
                        entry_points["cli"].append({
                            "name": script_name,
                            "module": module_path,
                            "type": "console_script"
                        })
        except Exception as e:
            logger.error(f"Failed to parse setup.py: {e}")
    
    pyproject_toml = os.path.join(working_dir, "pyproject.toml")

    if os.path.exists(pyproject_toml):

        try:
            with open(pyproject_toml, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"pyproject.toml file size: {len(content)} characters")
            
            script_patterns = [
                r'\[project\.scripts\]\s*\n(.*?)(?=\n\[|\n$)', 
                r'\[tool\.poetry\.scripts\]\s*\n(.*?)(?=\n\[|\n$)'
            ]
            
            for pattern_idx, pattern in enumerate(script_patterns):
                matches = re.findall(pattern, content, re.DOTALL)
                
                for match_idx, match in enumerate(matches):
                    scripts = re.findall(r'([^=]+)\s*=\s*["\']([^"\']+)["\']', match)
                    
                    for script_idx, script_match in enumerate(scripts):
                        if len(script_match) == 2:
                            script_name, module_path = script_match
                        else:
                            continue
                        entry_points["cli"].append({
                            "name": script_name.strip(),
                            "module": module_path.strip(),
                            "type": "pyproject_script"
                        })
        except Exception as e:
            logger.error(f"Failed to parse pyproject.toml: {e}")
            import traceback
            logger.error(f"Detailed error information: {traceback.format_exc()}")
    
    return entry_points


def _filter_core_modules_against_static(llm_analysis: Dict[str, Any], static_core_modules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep only functions/classes that were discovered in real source files."""
    if not static_core_modules:
        out = dict(llm_analysis or {})
        cli_commands = out.get("cli_commands", [])
        out["core_modules"] = []
        out["source_of_truth"] = "no_static_symbol_evidence"
        out["import_strategy"] = {
            "primary": "cli" if cli_commands else "blackbox",
            "fallback": "cli" if cli_commands else "blackbox",
            "confidence": 0.25,
        }
        risk = dict(out.get("risk_assessment", {}) or {})
        try:
            import_feasibility = float(risk.get("import_feasibility", 0.2) or 0.2)
        except (TypeError, ValueError):
            import_feasibility = 0.2
        risk.update({
            "import_feasibility": min(import_feasibility, 0.2),
            "intrusiveness_risk": risk.get("intrusiveness_risk") or "medium",
        })
        out["risk_assessment"] = risk
        return out

    def norm(value: str) -> str:
        value = (value or "").strip()
        for prefix in ("source.", "src."):
            if value.startswith(prefix):
                value = value[len(prefix):]
        return value

    by_full_key: Dict[str, Dict[str, Any]] = {}
    by_package: Dict[str, List[Dict[str, Any]]] = {}
    by_module: Dict[str, List[Dict[str, Any]]] = {}
    for module in static_core_modules:
        package = norm(module.get("package", ""))
        mod = norm(module.get("module", ""))
        full = f"{package}.{mod}" if package and mod and not package.endswith(mod) else (package or mod)
        if full:
            by_full_key[full] = module
        if package:
            by_package.setdefault(package, []).append(module)
        if mod:
            by_module.setdefault(mod, []).append(module)

    def find_static_module(package: str, mod: str) -> Dict[str, Any] | None:
        candidates = []
        if package and mod and not package.endswith(mod):
            candidates.append(f"{package}.{mod}")
        if package and (not mod or package.endswith(mod) or package == mod):
            candidates.append(package)
        if mod:
            candidates.append(mod)

        for key in candidates:
            static = by_full_key.get(key)
            if static:
                return static

        if mod and len(by_module.get(mod, [])) == 1:
            return by_module[mod][0]
        if package and not mod and len(by_package.get(package, [])) == 1:
            return by_package[package][0]
        return None

    filtered: List[Dict[str, Any]] = []
    for module in (llm_analysis or {}).get("core_modules", []) or []:
        package = norm(module.get("package", ""))
        mod = norm(module.get("module", ""))
        static = find_static_module(package, mod)
        if not static:
            continue

        static_funcs = set(static.get("functions", []) or [])
        static_classes = set(static.get("classes", []) or [])
        funcs = [f for f in (module.get("functions", []) or []) if str(f).rstrip("*") in static_funcs]
        classes = [c for c in (module.get("classes", []) or []) if str(c).rstrip("*") in static_classes]
        if not funcs and not classes:
            continue

        merged = dict(module)
        merged["package"] = static.get("package", package)
        merged["module"] = static.get("module", mod)
        merged["functions"] = [str(f).rstrip("*") for f in funcs]
        merged["classes"] = [str(c).rstrip("*") for c in classes]
        merged["function_signatures"] = static.get("function_signatures", {})
        merged["file_path"] = static.get("file_path", "")
        merged["imports"] = static.get("imports", [])
        merged["function_details"] = {
            name: detail
            for name, detail in (static.get("function_details", {}) or {}).items()
            if name in merged["functions"]
        }
        merged["class_details"] = {
            name: detail
            for name, detail in (static.get("class_details", {}) or {}).items()
            if name in merged["classes"]
        }
        merged["wrapper_candidates"] = [
            item
            for item in (static.get("wrapper_candidates", []) or [])
            if item.get("name") in set(merged["functions"] + merged["classes"])
        ]
        filtered.append(merged)

    if not filtered:
        filtered = static_core_modules

    out = dict(llm_analysis or {})
    out["core_modules"] = filtered
    out["source_of_truth"] = "ast"
    return out


def _analyze_with_llm(
    llm_service,
    repo_url: str,
    summary: Dict[str, Any],
    packages: List[str],
    entry_points: Dict[str, Any],
    deepwiki_analysis: Dict[str, Any],
    static_core_modules: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    if not llm_service:
        logger.warning("LLM service not available, using basic analysis")
        return _basic_analysis(packages, entry_points)
    
    try:
        logger.info(f"Summary size: {len(json.dumps(summary, ensure_ascii=False))} characters")
        
        deepwiki_url = repo_url.replace("github.com", "deepwiki.com") if "github.com" in repo_url else repo_url
        
        deepwiki_info = ""
        if deepwiki_analysis.get("success") and deepwiki_analysis.get("content") and _is_valid_deepwiki_content(deepwiki_analysis.get("content", "")):
            deepwiki_info = f"""
DeepWiki Analysis Results:
{deepwiki_analysis.get("content", "")}
"""
        elif deepwiki_analysis.get("status") == "failed":
            deepwiki_info = f"""
DeepWiki Analysis Failed: {deepwiki_analysis.get("error", "Unknown error")}
"""
        else:
            deepwiki_info = """
DeepWiki Analysis: Skipped or not enabled
"""

        prompt = f"""
You are analyzing a repository for automatic FastMCP service generation.

Your job is NOT to imagine a useful service. Your job is to describe only what can be supported by the scanned source evidence below.

Hard rules:
- Treat the Python Package Structure and Identified Entry Points as the source of truth.
- Do not invent modules, functions, classes, tools, features, demos, monitoring endpoints, weather tools, sentiment tools, or external examples.
- If a function/class is not supported by scanned paths or entry points, omit it.
- Prefer public, importable functions/classes with stable explicit signatures.
- Prefer "import" only when the scanned package path supports it; otherwise choose "cli" or "blackbox".
- Return JSON only. No Markdown, no explanation outside JSON.

Original Repository URL: {repo_url}
DeepWiki Analysis URL: {deepwiki_url}

Gitingest Summary:
{json.dumps(summary, indent=2, ensure_ascii=False)}

Python Package Structure:
{json.dumps(packages, indent=2, ensure_ascii=False)}

Identified Entry Points:
{json.dumps(entry_points, indent=2, ensure_ascii=False)}

Static AST Source Evidence:
{json.dumps(static_core_modules or [], indent=2, ensure_ascii=False)}

{deepwiki_info}

Output schema:
{{
    "core_modules": [
        {{
            "package": "Full package path scanned",
            "module": "Specific module name", 
            "functions": ["Function1", "Function2"],
            "classes": ["Class1", "Class2"],
            "description": "Evidence-based description of this module"
        }}
    ],
    "cli_commands": [
        {{
            "name": "Command name",
            "module": "Module path",
            "description": "Function description"
        }}
    ],
    "import_strategy": {{
        "primary": "Primary import strategy (import/cli/blackbox)",
        "fallback": "Fallback strategy",
        "confidence": 0.8
    }},
    "dependencies": {{
        "required": ["Dependency1", "Dependency2"],
        "optional": ["Optional dependency1"]
    }},
    "risk_assessment": {{
        "import_feasibility": 0.8,
        "intrusiveness_risk": "low/medium/high",
        "complexity": "simple/medium/complex"
    }}
}}

Validation checklist before returning:
- Every package value must be copied from scanned package paths or entry point modules.
- Every listed function/class must correspond to actual scanned source evidence when available.
- Prefer modules with higher wrapper_candidates scores from Static AST Source Evidence.
- Preserve file_path and function_signatures from Static AST Source Evidence when selecting modules.
- Empty arrays are better than fabricated names.
- Descriptions may summarize purpose, but must not introduce tools that are absent from source.
"""
        
        response = llm_service.invoke(prompt)
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                analysis_result = json.loads(json_match.group())
                logger.info("LLM analysis completed")
                return analysis_result
            else:
                logger.warning("JSON format not found in LLM response")
                return _basic_analysis(packages, entry_points)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM response JSON parsing failed: {e}")
            return _basic_analysis(packages, entry_points)
            
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}")
        return _basic_analysis(packages, entry_points)


def _basic_analysis(packages: List[str], entry_points: Dict[str, Any]) -> Dict[str, Any]:
    cli_commands = entry_points.get("cli", []) if isinstance(entry_points, dict) else []
    return {
        "source_of_truth": "basic_no_symbol_evidence",
        "core_modules": [],
        "cli_commands": cli_commands,
        "import_strategy": {
            "primary": "cli" if cli_commands else "blackbox",
            "fallback": "cli" if cli_commands else "blackbox",
            "confidence": 0.25
        },
        "dependencies": {
            "required": [],
            "optional": []
        },
        "risk_assessment": {
            "import_feasibility": 0.2,
            "intrusiveness_risk": "medium",
            "complexity": "simple"
        }
    }

def analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:

    logger.info("=== Starting analysis node ===")
    
    repo = state.get("repository", {})
    repo_url = repo.get("url")
    repo_root = repo.get("local_paths", {}).get("repo_root")
    
    logger.info(f"Repository URL: {repo_url}")
    logger.info(f"Repository root directory: {repo_root}")
    
    if not (repo_url and repo_root and os.path.isdir(repo_root)):
        logger.error("Missing repo_url or repo_root path")
        state.setdefault("errors", []).append({
            "node": "AnalysisNode",
            "type": "InvalidInput",
            "message": "Missing repo_url or repo_root path",
            "action_taken": "abort"
        })
        state["status"] = "failed"
        state["workflow_status"] = "failed"
        return state

    source_dir = os.path.join(repo_root, "source")
    summary: Dict[str, Any] = {}
    local_summary = _summarize_source_tree(source_dir, repo_url)
    use_gitingest = _analysis_gitingest_enabled(state.get("options", {})) or not local_summary.get("success")

    if use_gitingest:
        try:
            logger.info("Starting gitingest client call...")
            client = GitingestClient()
            logger.info("gitingest client created successfully")

            summary = client.preprocess_repository_sync(repo_url)
            if summary is None:
                summary = {"status": "failed", "error": "gitingest preprocess returned None"}
                logger.warning("gitingest preprocess failed, returned None")
            logger.info("gitingest preprocess completed")
        except Exception as e:
            logger.error(f"gitingest preprocess failed: {e}")
            import traceback
            logger.error(f"Detailed error information: {traceback.format_exc()}")
            state.setdefault("warnings", []).append(f"gitingest preprocess failed: {e}")

        if (not summary.get("success") or not summary.get("content")) and local_summary.get("success"):
            if summary and not summary.get("success"):
                local_summary["fallback_from"] = {
                    "processed_by": summary.get("processed_by"),
                    "error": summary.get("error"),
                    "summary": summary.get("summary"),
                }
            summary = local_summary
            logger.info("Using local source scan summary for analysis")
    else:
        summary = local_summary
        summary["supplemental_sources"] = {
            "gitingest": {
                "status": "skipped",
                "reason": "local_source_scan_available",
                "enable_with": "CODE2MCP_ANALYSIS_USE_GITINGEST=true",
            }
        }
        logger.info("Using local source scan summary for analysis; gitingest skipped by default")

    packages = _scan_python_packages(source_dir)
    entry_points = _scan_entry_points(source_dir)
    # Static AST-driven source scan feeds both dependency hints and generation targets.
    source_symbols = _scan_source_symbols_with_signatures(source_dir)
    dependencies = {
        "has_environment_yml": (
            os.path.exists(os.path.join(repo_root, "environment.yml")) or
            os.path.exists(os.path.join(source_dir, "environment.yml"))
        ),
        "has_requirements_txt": (
            os.path.exists(os.path.join(repo_root, "requirements.txt")) or
            os.path.exists(os.path.join(source_dir, "requirements.txt"))
        ),
        "pyproject": (
            os.path.exists(os.path.join(repo_root, "pyproject.toml")) or
            os.path.exists(os.path.join(source_dir, "pyproject.toml"))
        ),
        "setup_cfg": (
            os.path.exists(os.path.join(repo_root, "setup.cfg")) or
            os.path.exists(os.path.join(source_dir, "setup.cfg"))
        ),
        "setup_py": (
            os.path.exists(os.path.join(repo_root, "setup.py")) or
            os.path.exists(os.path.join(source_dir, "setup.py"))
        ),
    }
    ast_import_packages = _common_import_packages_from_symbols(source_symbols)
    dependencies["import_packages"] = ast_import_packages or _scan_common_import_packages(source_dir)
    dependencies["import_package_source"] = "ast_imports" if ast_import_packages else "source_text_scan"
    logger.info(f"Dependency file check results: {dependencies}")

    options = state.get("options", {}) or {}
    deepwiki_analysis = {"status": "skipped"}
    deepwiki_model = options.get("deepwiki_model")
    deepwiki_enabled = _analysis_deepwiki_enabled(options) or bool(deepwiki_model)
    disable_deepwiki = os.getenv("DISABLE_DEEPWIKI", "false").strip().lower() in {"1", "true", "yes", "on"}
    if disable_deepwiki:
        deepwiki_analysis = {"status": "skipped", "reason": "disabled_by_env"}
        logger.info("DeepWiki analysis skipped (disabled by DISABLE_DEEPWIKI)")
    elif deepwiki_model:
        try:
            model = deepwiki_model
            deepwiki_client = get_deepwiki_client(model=model)
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            deepwiki_analysis = deepwiki_client.analyze_repository(repo_url, repo_name)
            logger.info("DeepWiki analysis completed")
        except Exception as e:
            deepwiki_analysis = {"status": "failed", "error": "DeepWiki analysis failed"}
    elif not deepwiki_enabled:
        deepwiki_analysis = {
            "status": "skipped",
            "reason": "disabled_by_default",
            "enable_with": "CODE2MCP_ANALYSIS_USE_DEEPWIKI=true",
        }
        logger.info("DeepWiki analysis skipped (disabled by default)")
    else:
        logger.info("DeepWiki analysis skipped (model not configured)")

    try:
        if repo_url and deepwiki_enabled and not disable_deepwiki:
            if clean_env_value(os.getenv("JINA_API_KEY")):
                dw_url = repo_url.replace("github.com", "deepwiki.com") if "github.com" in repo_url else repo_url
                r = fetch_deepwiki(dw_url)
                if r.get("success") and r.get("content"):
                    content = r.get("content")
                    if content and _is_valid_deepwiki_content(content):
                        deepwiki_analysis = deepwiki_analysis or {}
                        deepwiki_analysis["content"] = sanitize_deepwiki_content(content)
                        deepwiki_analysis["source"] = "jina_api"
                        deepwiki_analysis["status"] = "ok"
                        deepwiki_analysis["success"] = True
                        deepwiki_analysis.pop("reason", None)
                        logger.info("Jina fetch success - content updated")
                    else:
                        logger.warning(f"Jina content too short or empty, length: {len(content) if content else 0}")
                else:
                    logger.warning(f"Jina fetch did not return usable content: {r.get('error', 'unknown error')}")
            else:
                logger.info("Jina fetch skipped (JINA_API_KEY not configured)")
    except Exception as e:
        logger.error(f"Jina fetch failed: {e}")
    
    static_core_modules: List[Dict[str, Any]] = []
    for module_path, sym in source_symbols.items():
        pkg = module_path.rsplit('.', 1)[0] if '.' in module_path else module_path
        mod = module_path.split('.')[-1]
        static_core_modules.append({
            "package": pkg,
            "module": mod,
            "functions": sorted(list(sym.get('functions', {}).keys())),
            "classes": sorted(list(sym.get('classes', []))),
            "function_signatures": sym.get('functions', {}),
            "file_path": sym.get("file_path", ""),
            "imports": sym.get("imports", []),
            "import_side_effect_risk": bool(sym.get("import_side_effect_risk", False)),
            "import_side_effect_reasons": sym.get("import_side_effect_reasons", []),
            "function_details": sym.get("function_details", {}),
            "class_details": sym.get("class_details", {}),
            "wrapper_candidates": sym.get("wrapper_candidates", []),
            "wrapper_candidate_stats": sym.get("wrapper_candidate_stats", {}),
            "description": "Discovered via AST scan"
        })

    if _analysis_llm_enabled(state.get("options", {})):
        logger.info("Starting LLM service...")
        llm_service = get_llm_service()
        logger.info("LLM service obtained")
        logger.info("Starting LLM analysis...")
        llm_analysis = _analyze_with_llm(llm_service, repo_url, summary, packages, entry_points, deepwiki_analysis, static_core_modules)
        logger.info("LLM analysis completed")
    else:
        logger.info("LLM analysis skipped; using static AST source evidence")
        llm_analysis = _static_llm_analysis(static_core_modules, entry_points)

    llm_analysis = _filter_core_modules_against_static(llm_analysis, static_core_modules)
    if static_core_modules:
        llm_analysis["import_strategy"] = {
            "primary": "import",
            "fallback": (llm_analysis or {}).get("import_strategy", {}).get("fallback", "cli"),
            "confidence": 0.9,
        }

    analysis_result = {
        "summary": summary,
        "structure": {"packages": packages},
        "dependencies": dependencies,
        "entry_points": entry_points,
        "llm_analysis": llm_analysis,
        "static_analysis": {
            "source_dir": source_dir,
            "modules": static_core_modules,
            "module_count": len(static_core_modules),
            "function_count": sum(len(module.get("functions", [])) for module in static_core_modules),
            "class_count": sum(len(module.get("classes", [])) for module in static_core_modules),
            "wrapper_candidate_count": sum(
                len(module.get("wrapper_candidates", []) or []) for module in static_core_modules
            ),
            "recommended_function_count": sum(
                int((module.get("wrapper_candidate_stats", {}) or {}).get("recommended_functions", 0) or 0)
                for module in static_core_modules
            ),
            "recommended_class_count": sum(
                int((module.get("wrapper_candidate_stats", {}) or {}).get("recommended_classes", 0) or 0)
                for module in static_core_modules
            ),
            "top_wrapper_candidates": _top_static_wrapper_candidates(static_core_modules),
        },
        "deepwiki_analysis": deepwiki_analysis,
        "deepwiki_options": {
            "enabled": bool(deepwiki_enabled and not disable_deepwiki),
            "model": deepwiki_model,
        },
        "risk": llm_analysis.get("risk_assessment", {
            "import_feasibility": 0.5,
            "intrusiveness_risk": "low",
            "complexity": "simple"
        })
    }

    mcp_output_dir = os.path.join(repo_root, "mcp_output")
    os.makedirs(mcp_output_dir, exist_ok=True)
    
    analysis_json_path = os.path.join(mcp_output_dir, "analysis.json")
    try:
        write_file(analysis_json_path, json.dumps(analysis_result, ensure_ascii=False, indent=2))
        logger.info(f"Analysis results saved to: {analysis_json_path}")
    except Exception as e:
        logger.warning(f"Failed to save analysis.json: {e}")
        state.setdefault("warnings", []).append(f"Failed to save analysis.json: {e}")

    state["analysis"] = analysis_result
    state["status"] = "running"
    state["workflow_status"] = state.get("workflow_status", "running")
    return state
