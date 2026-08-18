from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Iterable


RESOURCE_PARAM_TOKENS = {
    "dir",
    "directory",
    "dirname",
    "file",
    "filename",
    "filepath",
    "files",
    "fname",
    "host",
    "hostname",
    "path",
    "paths",
    "port",
    "uri",
    "url",
}
RESOURCE_PARAM_EXACT_NAMES = {
    "directory",
    "dir",
    "dirname",
    "dir_name",
    "file",
    "filepath",
    "file_path",
    "filename",
    "file_name",
    "fname",
    "host",
    "hostname",
    "path",
    "port",
    "uri",
    "url",
}
RESOURCE_COMPACT_ENDINGS = {
    "configfile",
    "datafile",
    "directory",
    "dirname",
    "filepaths",
    "filepath",
    "fname",
    "inputdir",
    "inputfile",
    "inputpath",
    "jsonfile",
    "logfile",
    "modelfile",
    "modulepath",
    "outputdir",
    "outputfile",
    "outputpath",
    "relativepath",
    "rootpath",
    "sourcefile",
    "sourcepath",
    "targetfile",
    "targetpath",
    "txtfile",
    "uri",
    "url",
    "xmlfile",
}
NON_RESOURCE_PARAM_EXACT_NAMES = {
    "import_path",
    "importpath",
    "module_path",
    "modulepath",
}
SENSITIVE_PARAM_NAMES = {
    "access_token",
    "api_key",
    "api_token",
    "credential",
    "credentials",
    "creds",
    "dob",
    "medical_record_number",
    "mrn",
    "password",
    "patient",
    "patient_id",
    "patient_name",
    "phi",
    "pii",
    "secret_key",
    "ssn",
    "token",
    "username",
}
SENSITIVE_COMPACT_PARAM_NAMES = {
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
TOKEN_SECRET_QUALIFIERS = {"access", "api", "auth", "bearer", "github", "hf", "openai", "refresh", "secret", "session"}
KEY_SECRET_QUALIFIERS = {"access", "api", "auth", "private", "secret", "ssh"}
RISKY_TOOL_NAME_PARTS = {
    "activate",
    "append",
    "attach",
    "build",
    "create",
    "ensure",
    "deactivate",
    "delete",
    "fit",
    "remove",
    "rebuild",
    "write",
    "save",
    "upload",
    "download",
    "dummy",
    "send",
    "post",
    "run",
    "execute",
    "install",
    "config",
    "login",
    "auth",
    "connect",
    "connection",
    "database",
    "keyboard",
    "keylog",
    "keylogger",
    "calendar",
    "executor",
    "handler",
    "hook",
    "listener",
    "logger",
    "load",
    "monkey",
    "mongodb",
    "movorder",
    "patch",
    "pickle",
    "plot",
    "plotly",
    "proc",
    "processor",
    "on_press",
    "on_release",
    "rainbow",
    "redis",
    "simulator",
    "token",
    "transform",
    "unpickle",
}
OPTIONAL_PLOTTING_TOOL_TOKENS = {"matplotlib", "mpl"}
OUTPUT_ONLY_TOOL_TOKENS = {"display", "pprint", "print", "show"}
CLI_ARGUMENT_TOOL_TOKENS = {"args", "arguments"}
REMOTE_LOOKUP_TOOL_TOKENS = {
    "entrez",
    "expasy",
    "kegg",
    "ncbi",
    "prodoc",
    "prosite",
    "pubmed",
    "sprot",
    "swissprot",
    "uniprot",
    "vso",
    "wsdl",
}


@dataclass(frozen=True)
class ParameterPolicyDecision:
    unsafe: bool
    reason: str = ""


def name_tokens(name: str) -> set[str]:
    raw = str(name)
    camel_spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw)
    return set(re.findall(r"[a-z0-9]+", camel_spaced.lower()))


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _compact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _looks_dataframe_parameter(lowered: str, tokens: Collection[str]) -> bool:
    return bool(re.fullmatch(r"df\d*", lowered) or "df" in tokens)


def _matches_complex_name_part(lowered: str, tokens: set[str], part: str) -> bool:
    part = str(part).lower()
    if not part:
        return False
    if part == "dist":
        return "dist" in tokens
    return part in lowered


def _matches_complex_name(lowered: str, tokens: set[str], name: str) -> bool:
    name = str(name).lower()
    if not name:
        return False
    if lowered == name:
        return True
    if len(name) <= 4:
        return False
    return name in tokens


def _looks_sensitive_param(param_name: str, tokens: set[str]) -> bool:
    normalized = _normalized_name(param_name)
    compact = _compact_name(param_name)
    if normalized in SENSITIVE_PARAM_NAMES or compact in SENSITIVE_COMPACT_PARAM_NAMES:
        return True
    if "token" in tokens and tokens.intersection(TOKEN_SECRET_QUALIFIERS):
        return True
    if "key" in tokens and tokens.intersection(KEY_SECRET_QUALIFIERS):
        return True
    if tokens.intersection({"credential", "credentials", "creds", "dob", "mrn", "password", "passwd", "patient", "phi", "pii", "secret", "ssn"}):
        return True
    return False


def _looks_resource_param(param_name: str, tokens: set[str]) -> bool:
    normalized = _normalized_name(param_name)
    compact = _compact_name(param_name)
    if normalized in NON_RESOURCE_PARAM_EXACT_NAMES or compact in NON_RESOURCE_PARAM_EXACT_NAMES:
        return False
    if normalized in RESOURCE_PARAM_EXACT_NAMES or compact in RESOURCE_PARAM_EXACT_NAMES:
        return True
    if tokens.intersection(RESOURCE_PARAM_TOKENS):
        return True
    if normalized.endswith(
        (
            "_path",
            "_paths",
            "_file",
            "_files",
            "_fname",
            "_dir",
            "_directory",
            "_url",
            "_uri",
            "_host",
            "_port",
        )
    ):
        return True
    return any(compact.endswith(ending) for ending in RESOURCE_COMPACT_ENDINGS)


def looks_resource_parameter(param_name: str) -> bool:
    return _looks_resource_param(param_name, name_tokens(param_name))


def looks_sensitive_parameter(param_name: str) -> bool:
    return _looks_sensitive_param(param_name, name_tokens(param_name))


def _property_names(properties: Collection[str] | Mapping[str, object]) -> set[str]:
    if isinstance(properties, Mapping):
        return {str(name) for name in properties}
    return {str(name) for name in properties}


def classify_auto_call_tool_name(
    tool_name: str,
    *,
    properties: Collection[str] | Mapping[str, object],
) -> ParameterPolicyDecision:
    """Return why a generated MCP tool should not be auto-called with synthetic data."""
    lowered = str(tool_name).lower()
    tokens = name_tokens(tool_name)
    prop_names = _property_names(properties)

    if lowered.startswith("assert_"):
        return ParameterPolicyDecision(True, "assertion helper is not a user-facing tool")
    if lowered == "raises":
        return ParameterPolicyDecision(True, "test exception context helper is not a user-facing tool")
    if lowered in {"and", "not", "or", "variable"}:
        return ParameterPolicyDecision(True, "symbolic expression helper is not safe to auto-call")
    if lowered == "tstr":
        return ParameterPolicyDecision(True, "structured table formatter requires nested tuple input")
    if "expr" in tokens:
        return ParameterPolicyDecision(True, "expression helper requires domain-specific objects")
    if lowered == "if_delegate_has_method" or "delegate" in tokens:
        return ParameterPolicyDecision(True, "delegation decorator helper is not a user-facing tool")
    if "safe" in tokens and tokens.intersection({"class", "classes"}):
        return ParameterPolicyDecision(True, "safe-class whitelist helper mutates security policy")
    if lowered.startswith("set_"):
        return ParameterPolicyDecision(True, "state-changing setter is not a user-facing tool")
    if lowered.startswith("ingest_"):
        return ParameterPolicyDecision(True, "data ingestion helper is not safe to auto-call")
    if lowered.startswith("requires_") or lowered.endswith("_mark"):
        return ParameterPolicyDecision(True, "test requirement marker is not a user-facing tool")
    if not prop_names and lowered.startswith("get_") and lowered.endswith("_class"):
        return ParameterPolicyDecision(True, "class getter is not a user-facing tool")
    if "backend" in tokens:
        return ParameterPolicyDecision(True, "backend probe is not a user-facing tool")
    if "horizon" in tokens and "label" in prop_names:
        return ParameterPolicyDecision(True, "horizon inference requires initialized domain data")
    if "progress" in tokens or lowered.startswith("progress"):
        return ParameterPolicyDecision(True, "progress helper is not a user-facing tool")
    if "projection" in tokens:
        return ParameterPolicyDecision(True, "projection helper often requires optional geospatial runtime")
    if lowered.startswith("mne_"):
        return ParameterPolicyDecision(True, "optional MNE integration helper requires external runtime")
    if not prop_names and lowered.startswith("init_") and "session" in tokens:
        return ParameterPolicyDecision(True, "interactive session initializer is not a user-facing tool")
    if not prop_names and "ordering" in tokens and tokens.intersection({"halt", "restart"}):
        return ParameterPolicyDecision(True, "dispatch ordering control helper is not a user-facing tool")
    if not prop_names and lowered.endswith("_zero"):
        return ParameterPolicyDecision(True, "zero-value constructor returns an empty sentinel")
    if not prop_names and lowered.startswith(("has_", "is_")):
        return ParameterPolicyDecision(True, "zero-argument availability probe is not a user-facing tool")
    if "parse" in tokens and tokens.intersection(CLI_ARGUMENT_TOOL_TOKENS):
        return ParameterPolicyDecision(True, "tool name appears to parse command-line arguments")
    if "parse" in tokens:
        parser_param_tokens: set[str] = set()
        for prop_name in prop_names:
            parser_param_tokens.update(name_tokens(prop_name))
        if parser_param_tokens.intersection({"block", "blocks", "header", "headers", "line", "lines", "record", "records"}):
            return ParameterPolicyDecision(True, "parser helper requires domain-specific input text")
    for token in OPTIONAL_PLOTTING_TOOL_TOKENS:
        if token in tokens:
            return ParameterPolicyDecision(True, f"tool name contains '{token}'")
    for token in OUTPUT_ONLY_TOOL_TOKENS:
        if token in tokens:
            return ParameterPolicyDecision(True, f"tool name contains output-only verb '{token}'")
    for part in sorted(RISKY_TOOL_NAME_PARTS, key=len, reverse=True):
        if part in lowered:
            return ParameterPolicyDecision(True, f"tool name contains '{part}'")
    if tokens.intersection(REMOTE_LOOKUP_TOOL_TOKENS):
        return ParameterPolicyDecision(True, "tool name appears to query a remote database or service")

    if not prop_names and lowered.startswith("check_"):
        return ParameterPolicyDecision(True, "zero-argument check tool is likely an environment probe")
    if not prop_names and lowered.startswith("list_"):
        return ParameterPolicyDecision(True, "zero-argument list tool is likely an external resource probe")
    if lowered.startswith(("warn_", "warning_")):
        return ParameterPolicyDecision(True, "warning helper is not a user-facing tool")
    if "version" in tokens and tokens.intersection({"latest", "newest"}):
        return ParameterPolicyDecision(True, "version lookup is likely to require an external package registry")
    if "version" in tokens and "package" in prop_names:
        return ParameterPolicyDecision(True, "package version lookup is likely to require external metadata")
    if tokens.intersection({"extra", "extras"}) and prop_names.intersection({"groups", "exclude_extras"}):
        return ParameterPolicyDecision(True, "package extras metadata helper is not a user-facing tool")
    if "package" in prop_names and tokens.intersection({"dependencies", "dependency", "releases", "requirements"}):
        return ParameterPolicyDecision(True, "dependency metadata lookup is likely to require an external package registry")
    if lowered.startswith("get_") and prop_names == {"line"}:
        return ParameterPolicyDecision(True, "single-line record parser requires domain-specific input")

    return ParameterPolicyDecision(False)


def classify_auto_call_parameter(
    param_name: str,
    *,
    schema_type: str,
    has_detailed_object_schema: bool,
    sample_structured_param_names: Iterable[str],
    complex_param_names: Iterable[str],
    complex_param_parts: Iterable[str],
    signal_array_param_names: Iterable[str],
) -> ParameterPolicyDecision:
    """Return why a parameter should not receive synthetic validation input."""
    lowered = str(param_name).lower()
    tokens = name_tokens(param_name)
    structured_names = set(sample_structured_param_names)
    complex_names = set(complex_param_names)
    complex_parts = tuple(complex_param_parts)
    signal_names = set(signal_array_param_names)

    if looks_sensitive_parameter(param_name):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' looks sensitive")
    if looks_resource_parameter(param_name):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' requires an external resource")
    if _looks_dataframe_parameter(lowered, tokens):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a complex dataframe")
    if re.fullmatch(r"doc\d+", lowered):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a complex document")
    if re.fullmatch(r"h\d*", lowered):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a complex histogram")
    if lowered in {"a", "b", "e", "f1", "f2", "o", "r", "v", "w", "x", "y", "z"} and schema_type == "string":
        return ParameterPolicyDecision(True, f"parameter '{param_name}' is an untyped scientific parameter")
    if lowered in signal_names and schema_type in {"array", "object", "string"}:
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a signal-like array")
    if any(_matches_complex_name(lowered, tokens, name) for name in complex_names):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a complex resource")
    if any(_matches_complex_name_part(lowered, tokens, part) for part in complex_parts):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a complex resource")
    if schema_type == "string" and ("list" in tokens or lowered.endswith("_list")):
        return ParameterPolicyDecision(True, f"parameter '{param_name}' appears to require a list-like resource")
    if schema_type == "object" and not has_detailed_object_schema and lowered not in structured_names:
        return ParameterPolicyDecision(True, f"parameter '{param_name}' has an opaque object schema")
    return ParameterPolicyDecision(False)


def classify_wrapper_parameter_name(
    param_name: str,
    *,
    complex_param_names: Iterable[str],
    complex_param_parts: Iterable[str],
) -> ParameterPolicyDecision:
    """Return why a source function parameter is unsafe to expose as a simple MCP wrapper."""
    lowered = str(param_name).lower()
    tokens = name_tokens(param_name)
    complex_names = set(complex_param_names)
    complex_parts = tuple(complex_param_parts)

    if looks_sensitive_parameter(param_name):
        return ParameterPolicyDecision(True, "looks sensitive")
    if _looks_dataframe_parameter(lowered, tokens):
        return ParameterPolicyDecision(True, "appears to require a complex dataframe")
    if re.fullmatch(r"doc\d+", lowered):
        return ParameterPolicyDecision(True, "appears to require a complex document")
    if re.fullmatch(r"h\d*", lowered):
        return ParameterPolicyDecision(True, "appears to require a complex histogram")
    if any(_matches_complex_name(lowered, tokens, name) for name in complex_names):
        return ParameterPolicyDecision(True, "appears to require a complex resource")
    if any(_matches_complex_name_part(lowered, tokens, part) for part in complex_parts):
        return ParameterPolicyDecision(True, "appears to require a complex resource")
    return ParameterPolicyDecision(False)
