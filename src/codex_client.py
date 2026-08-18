from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .codex_auth import CodexAuth


class CodexBackendError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Codex backend HTTP {status_code}: {detail}")

    @property
    def retryable(self) -> bool:
        return self.status_code == 429 or self.status_code >= 500


def _to_input_messages(system: str | None, prompt: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if (system or "").strip():
        messages.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": (system or "").strip()}],
            }
        )
    messages.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }
    )
    return messages


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if content.get("type") in {"output_text", "text"} and isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _iter_sse_data(response) -> list[str]:
    events: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="ignore").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            break
        if data:
            events.append(data)
    return events


def invoke_codex(prompt: str, system: str | None, *, auth: CodexAuth, model: str, base_url: str) -> str:
    url = base_url.rstrip("/") + "/responses"
    payload = {
        "model": model,
        "input": _to_input_messages(system=system, prompt=prompt),
        "instructions": "You are Codex, based on GPT-5. Return concise, correct results.",
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": {"summary": "auto"},
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Authorization", f"Bearer {auth.access_token}")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "text/event-stream")
    request.add_header("User-Agent", "mcp-repo-output")
    if auth.account_id:
        request.add_header("ChatGPT-Account-Id", auth.account_id)

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            events = _iter_sse_data(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:2000]
        raise CodexBackendError(exc.code, detail) from exc

    chunks: list[str] = []
    last_payload: dict[str, Any] = {}
    for event in events:
        try:
            payload_item = json.loads(event)
        except Exception:
            continue
        if not isinstance(payload_item, dict):
            continue
        last_payload = payload_item
        event_type = payload_item.get("type")
        if event_type == "response.output_text.delta" and isinstance(payload_item.get("delta"), str):
            chunks.append(payload_item["delta"])
            continue
        if event_type == "response.output_text.done" and isinstance(payload_item.get("text"), str) and not chunks:
            chunks.append(payload_item["text"])
            continue
        fallback = _extract_output_text(payload_item)
        if fallback and not chunks:
            chunks.append(fallback)

    text = "".join(chunks).strip()
    if text:
        return text
    raise RuntimeError(f"Codex backend returned no text. Response keys: {sorted(last_payload.keys())}")


def invoke_codex_json(prompt: str, system: str | None, *, auth: CodexAuth, model: str, base_url: str) -> dict[str, Any]:
    raw = invoke_codex(prompt, system, auth=auth, model=model, base_url=base_url).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw)
    if fenced:
        parsed = json.loads(fenced.group(1))
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    raise ValueError("Codex response was not valid JSON")
