from __future__ import annotations

from src.security.tool_policy import (
    classify_auto_call_parameter,
    classify_auto_call_tool_name,
    classify_wrapper_parameter_name,
)


def test_auto_call_policy_rejects_sensitive_and_resource_params():
    decision = classify_auto_call_parameter(
        "api_key",
        schema_type="string",
        has_detailed_object_schema=False,
        sample_structured_param_names=set(),
        complex_param_names=set(),
        complex_param_parts=set(),
        signal_array_param_names=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "parameter 'api_key' looks sensitive"

    decision = classify_auto_call_parameter(
        "file_path",
        schema_type="string",
        has_detailed_object_schema=False,
        sample_structured_param_names=set(),
        complex_param_names=set(),
        complex_param_parts=set(),
        signal_array_param_names=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "parameter 'file_path' requires an external resource"


def test_auto_call_resource_policy_uses_tokens_not_raw_substrings():
    for param_name in ["profile", "profile_name", "transport", "user_profile", "viewport"]:
        decision = classify_auto_call_parameter(
            param_name,
            schema_type="string",
            has_detailed_object_schema=False,
            sample_structured_param_names=set(),
            complex_param_names=set(),
            complex_param_parts=set(),
            signal_array_param_names=set(),
        )
        assert decision.unsafe is False, param_name

    for param_name in ["modulePath", "module_path", "import_path"]:
        decision = classify_auto_call_parameter(
            param_name,
            schema_type="string",
            has_detailed_object_schema=False,
            sample_structured_param_names=set(),
            complex_param_names=set(),
            complex_param_parts=set(),
            signal_array_param_names=set(),
        )
        assert decision.unsafe is False, param_name

    for param_name in [
        "dataPath",
        "file_path",
        "filename",
        "inputFile",
        "fname_in",
        "output_dir",
        "host",
    ]:
        decision = classify_auto_call_parameter(
            param_name,
            schema_type="string",
            has_detailed_object_schema=False,
            sample_structured_param_names=set(),
            complex_param_names=set(),
            complex_param_parts=set(),
            signal_array_param_names=set(),
        )
        assert decision.unsafe is True, param_name
        assert decision.reason == f"parameter '{param_name}' requires an external resource"


def test_auto_call_sensitive_policy_handles_common_secret_spellings():
    for param_name in [
        "apiKey",
        "auth_token",
        "refreshToken",
        "openai_api_key",
        "db_password",
        "credentials",
        "client_creds",
        "patient_id",
        "patientName",
        "ssn",
        "dob",
        "mrn",
    ]:
        decision = classify_auto_call_parameter(
            param_name,
            schema_type="string",
            has_detailed_object_schema=False,
            sample_structured_param_names=set(),
            complex_param_names=set(),
            complex_param_parts=set(),
            signal_array_param_names=set(),
        )
        assert decision.unsafe is True, param_name
        assert decision.reason == f"parameter '{param_name}' looks sensitive"


def test_auto_call_policy_rejects_domain_objects():
    decision = classify_auto_call_parameter(
        "molecule_store",
        schema_type="string",
        has_detailed_object_schema=False,
        sample_structured_param_names=set(),
        complex_param_names={"molecule_store"},
        complex_param_parts=set(),
        signal_array_param_names=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "parameter 'molecule_store' appears to require a complex resource"


def test_auto_call_policy_allows_detailed_structured_samples():
    decision = classify_auto_call_parameter(
        "options",
        schema_type="object",
        has_detailed_object_schema=True,
        sample_structured_param_names=set(),
        complex_param_names=set(),
        complex_param_parts=set(),
        signal_array_param_names=set(),
    )

    assert decision.unsafe is False
    assert decision.reason == ""


def test_auto_call_tool_policy_rejects_non_user_facing_helpers():
    decision = classify_auto_call_tool_name("progress_bar", properties={})

    assert decision.unsafe is True
    assert decision.reason == "progress helper is not a user-facing tool"

    decision = classify_auto_call_tool_name("get_projection_from_crs", properties={"crs": {"type": "string"}})

    assert decision.unsafe is True
    assert decision.reason == "projection helper often requires optional geospatial runtime"


def test_auto_call_tool_policy_rejects_cli_and_remote_helpers():
    decision = classify_auto_call_tool_name("parse_args", properties={"argv": {"type": "array"}})

    assert decision.unsafe is True
    assert decision.reason == "tool name appears to parse command-line arguments"

    decision = classify_auto_call_tool_name("kegg_get", properties={"entry_id": {"type": "string"}})

    assert decision.unsafe is True
    assert decision.reason == "tool name appears to query a remote database or service"

    decision = classify_auto_call_tool_name("wsdl_retriever", properties={"service": {"type": "string"}})

    assert decision.unsafe is True
    assert decision.reason == "tool name appears to query a remote database or service"


def test_auto_call_tool_policy_rejects_operational_side_effect_names():
    for tool_name, token in [
        ("attach_ufl_id", "attach"),
        ("build_docs", "build"),
        ("create_report", "create"),
        ("fit_model", "fit"),
        ("rebuild_index", "rebuild"),
    ]:
        decision = classify_auto_call_tool_name(tool_name, properties={"value": {"type": "string"}})

        assert decision.unsafe is True, tool_name
        assert decision.reason == f"tool name contains '{token}'"


def test_wrapper_policy_rejects_complex_source_params():
    decision = classify_wrapper_parameter_name(
        "component",
        complex_param_names={"component"},
        complex_param_parts=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "appears to require a complex resource"

    decision = classify_wrapper_parameter_name(
        "df1",
        complex_param_names=set(),
        complex_param_parts=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "appears to require a complex dataframe"

    decision = classify_wrapper_parameter_name(
        "dfDict",
        complex_param_names=set(),
        complex_param_parts=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "appears to require a complex dataframe"

    decision = classify_wrapper_parameter_name(
        "df_dict",
        complex_param_names=set(),
        complex_param_parts=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "appears to require a complex dataframe"

    decision = classify_auto_call_parameter(
        "df_dict",
        schema_type="object",
        has_detailed_object_schema=False,
        sample_structured_param_names=set(),
        complex_param_names=set(),
        complex_param_parts=set(),
        signal_array_param_names=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "parameter 'df_dict' appears to require a complex dataframe"


def test_complex_part_policy_does_not_reject_distance_substrings():
    decision = classify_wrapper_parameter_name(
        "bond_distance",
        complex_param_names=set(),
        complex_param_parts={"dist"},
    )

    assert decision.unsafe is False

    decision = classify_auto_call_parameter(
        "bond_distance",
        schema_type="number",
        has_detailed_object_schema=False,
        sample_structured_param_names=set(),
        complex_param_names=set(),
        complex_param_parts={"dist"},
        signal_array_param_names=set(),
    )

    assert decision.unsafe is False

    decision = classify_wrapper_parameter_name(
        "dist",
        complex_param_names=set(),
        complex_param_parts={"dist"},
    )

    assert decision.unsafe is True
    assert decision.reason == "appears to require a complex resource"


def test_wrapper_policy_allows_iteration_count_params():
    for param_name in ["max_iter", "num_iter", "n_iter", "iterations"]:
        decision = classify_wrapper_parameter_name(
            param_name,
            complex_param_names={"iter"},
            complex_param_parts=set(),
        )

        assert decision.unsafe is False, param_name

    decision = classify_wrapper_parameter_name(
        "iter",
        complex_param_names={"iter"},
        complex_param_parts=set(),
    )

    assert decision.unsafe is True
    assert decision.reason == "appears to require a complex resource"


def test_wrapper_policy_rejects_sensitive_source_params():
    for param_name in [
        "api_key",
        "authToken",
        "db_password",
        "secret_key",
        "refresh_token",
        "credentials",
        "client_creds",
        "patient_id",
        "patientName",
        "ssn",
        "dob",
        "mrn",
    ]:
        decision = classify_wrapper_parameter_name(
            param_name,
            complex_param_names=set(),
            complex_param_parts=set(),
        )

        assert decision.unsafe is True, param_name
        assert decision.reason == "looks sensitive"
