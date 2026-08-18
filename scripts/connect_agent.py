from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.quick_connect import QuickConnectError, connect_agent, open_connection_guide
from src.utils import redact_sensitive_data, redact_sensitive_text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or install MCP client configuration for a generated Code2MCP service."
    )
    parser.add_argument("--repo-root", required=True, help="Generated workspace repository root, e.g. workspace/demo")
    parser.add_argument(
        "--client",
        default="generic",
        choices=[
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
        ],
    )
    parser.add_argument("--name", help="MCP server name shown in the agent client")
    parser.add_argument("--remote-url", help="Remote MCP base URL, e.g. https://user-space.hf.space")
    parser.add_argument("--python", dest="python_executable", help="Python executable for local stdio mode")
    parser.add_argument("--write", action="store_true", help="Write/install the client configuration")
    parser.add_argument("--open-guide", action="store_true", help="Open the generated HTML copy guide in a browser")
    parser.add_argument(
        "--allow-unvalidated",
        action="store_true",
        help="Allow writing config even when workflow_summary.json is not validated",
    )
    parser.add_argument("--remote", action="store_true", help="Use remote URL config for clients that support it")
    parser.add_argument(
        "--probe-remote",
        action="store_true",
        help="Verify --remote-url with a FastMCP client before marking remote payloads ready or writing remote config",
    )
    parser.add_argument(
        "--remote-probe-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for --probe-remote FastMCP client validation",
    )
    parser.add_argument("--config-path", help="Override client config path, currently supported for Cursor")
    args = parser.parse_args()

    try:
        result = connect_agent(
            args.repo_root,
            client=args.client,
            server_name=args.name,
            remote_url=args.remote_url,
            python_executable=args.python_executable,
            write=args.write,
            allow_unvalidated=args.allow_unvalidated,
            remote=args.remote,
            config_path=args.config_path,
            probe_remote=args.probe_remote,
            remote_probe_timeout=args.remote_probe_timeout,
        )
        if args.open_guide:
            result["opened_guide"] = open_connection_guide(args.repo_root)
    except QuickConnectError as exc:
        print(json.dumps({"success": False, "error": redact_sensitive_text(str(exc))}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(redact_sensitive_data(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
