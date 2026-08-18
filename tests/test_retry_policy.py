from src.utils import has_critical_errors, should_retry_generation


def test_empty_runtime_state_is_not_critical():
    state = {"errors": [], "generation_retry_count": 0}

    assert has_critical_errors(state) is False
    assert should_retry_generation(state, max_retries=3) is False


def test_failed_run_is_critical_and_regenerable():
    state = {
        "run_result": {"success": False, "error": "RuntimeError"},
        "generation_retry_count": 0,
    }

    assert has_critical_errors(state) is True
    assert should_retry_generation(state, max_retries=3) is True


def test_review_fail_action_blocks_regeneration():
    state = {
        "run_result": {"success": False, "error": "manual fix required"},
        "error_analysis": {"status": "FAIL", "next_action": "fail"},
        "errors": [{"severity": "high", "message": "manual fix required"}],
        "generation_retry_count": 0,
    }

    assert has_critical_errors(state) is False
    assert should_retry_generation(state, max_retries=3) is False


def test_review_regenerate_action_allows_retry_until_budget():
    state = {
        "error_analysis": {"status": "FAIL", "next_action": "regenerate"},
        "generation_retry_count": 2,
    }

    assert has_critical_errors(state) is True
    assert should_retry_generation(state, max_retries=3) is True

    state["generation_retry_count"] = 3
    assert should_retry_generation(state, max_retries=3) is False
