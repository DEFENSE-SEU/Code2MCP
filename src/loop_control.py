from __future__ import annotations

import copy
import time
from typing import Any, Dict


def append_loop_event(state: Dict[str, Any], event: str, **details: Any) -> Dict[str, Any]:
    """Record a compact audit event for the run-review-fix loop."""
    repair_loop = state.setdefault("repair_loop", {})
    events = repair_loop.setdefault("events", [])
    entry = {
        "timestamp": time.time(),
        "event": event,
        **{key: value for key, value in details.items() if value is not None},
    }
    events.append(entry)
    return entry


def archive_failed_run_once(state: Dict[str, Any], reason: str = "") -> bool:
    """Archive the current failed run_result without duplicating the same attempt."""
    run_result = state.get("run_result")
    if not isinstance(run_result, dict) or run_result.get("success", False):
        return False

    previous = state.setdefault("previous_run_results", [])
    attempt = run_result.get("attempt")
    if attempt is not None:
        for item in previous:
            if isinstance(item, dict) and item.get("attempt") == attempt:
                return False

    archived = copy.deepcopy(run_result)
    if reason:
        archived["archived_reason"] = reason
    previous.append(archived)
    append_loop_event(
        state,
        "run_failure_archived",
        reason=reason,
        attempt=attempt,
        error_type=run_result.get("error_type"),
    )
    return True


def clear_runtime_validation(state: Dict[str, Any]) -> None:
    """Clear stale runtime validation before a new run or regeneration attempt."""
    state.pop("run_result", None)
    tests = state.get("tests")
    if isinstance(tests, dict):
        tests.pop("plugin", None)
        tests.pop("mcp_plugin", None)
