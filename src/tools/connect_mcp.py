#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.quick_connect import QuickConnectError, connect_agent
from src.utils import redact_sensitive_data, redact_sensitive_text


CLIENT_CHOICES = [
    "generic",
    "cursor",
    "claude",
    "claude-code",
    "claude-desktop",
    "vscode",
    "windsurf",
    "cline",
    "gemini",
    "gemini-cli",
    "chatgpt",
    "gpt",
    "openai",
    "openai-api",
    "responses-api",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compatibility wrapper for generated MCP agent connection. "
            "Prefer scripts/connect_agent.py for new usage."
        )
    )
    parser.add_argument("--client", choices=CLIENT_CHOICES, required=True)
    parser.add_argument("--name", help="MCP server name shown in the agent client")
    parser.add_argument("--url", help="Remote MCP base URL, e.g. https://user-space.hf.space")
    parser.add_argument("--local", action="store_true", help="Use local stdio config")
    parser.add_argument("--project", required=True, help="Generated workspace repo root, e.g. workspace/demo")
    parser.add_argument("--python", dest="python_executable", help="Python executable for local stdio mode")
    parser.add_argument("--write", action="store_true", help="Write/install the client configuration")
    parser.add_argument("--allow-unvalidated", action="store_true", help="Allow writing unvalidated services")
    parser.add_argument(
        "--probe-remote",
        action="store_true",
        help="Verify --url with a FastMCP client before marking remote payloads ready or writing remote config",
    )
    parser.add_argument(
        "--remote-probe-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for --probe-remote FastMCP client validation",
    )
    parser.add_argument("--config-path", help="Override client config path, currently supported for Cursor")
    args = parser.parse_args()

    remote = bool(args.url and not args.local)
    if remote is False and args.client in {"chatgpt", "gpt", "openai", "openai-api", "responses-api"}:
        raise SystemExit("ChatGPT/OpenAI API clients require --url because they use remote HTTPS MCP.")

    try:
        result = connect_agent(
            args.project,
            client=args.client,
            server_name=args.name,
            remote_url=args.url,
            python_executable=args.python_executable,
            write=args.write,
            allow_unvalidated=args.allow_unvalidated,
            remote=remote,
            config_path=args.config_path,
            probe_remote=args.probe_remote,
            remote_probe_timeout=args.remote_probe_timeout,
        )
    except QuickConnectError as exc:
        print(json.dumps({"success": False, "error": redact_sensitive_text(str(exc))}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(redact_sensitive_data(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
