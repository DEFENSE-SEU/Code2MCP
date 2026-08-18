import os
import sys
import asyncio
import argparse
import warnings
import platform
from pathlib import Path
import logging
from loguru import logger

logging.getLogger("gitingest").setLevel(logging.CRITICAL)
logging.getLogger("gitingest.entrypoint").setLevel(logging.CRITICAL)
logging.getLogger("gitingest.clone").setLevel(logging.CRITICAL)
logging.getLogger("gitingest.ingestion").setLevel(logging.CRITICAL)
logger.remove()
logger.add(
    sys.stderr,
    level="DEBUG",
    filter=lambda record: not record["name"].startswith("gitingest")
)

def load_env_file():
    env_file = '.env'
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key, value)

load_env_file()

if platform.system() == 'Windows':
    import warnings
    warnings.simplefilter("ignore")
    if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    import logging
    logging.getLogger("asyncio").setLevel(logging.ERROR)
    logging.getLogger("asyncio.base_subprocess").setLevel(logging.ERROR)
    logging.getLogger("asyncio.proactor_events").setLevel(logging.ERROR)
    def _suppress_asyncio_warnings(*args, **kwargs): pass
    import asyncio.base_subprocess
    import asyncio.proactor_events
    if hasattr(asyncio.base_subprocess, '_warn'): asyncio.base_subprocess._warn = _suppress_asyncio_warnings
    if hasattr(asyncio.proactor_events, '_warn'): asyncio.proactor_events._warn = _suppress_asyncio_warnings

project_root = Path(__file__).parent
sys.path.append(str(project_root))

try:
    from dotenv import load_dotenv
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    env_file = project_root / ".env"
    if env_file.exists():
        print("python-dotenv not installed, please set environment variables manually")

import logging
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(legacy_windows=False)

GENERATE_ONLY_HELP = (
    "Generate MCP files and finalize as generated_unvalidated; still performs analysis/env/generate, "
    "but skips runtime validation and auto-fix review after generation"
)

def _connect_agent_from_workflow_result(result: dict, args: argparse.Namespace) -> int:
    try:
        from src.tools.quick_connect import connect_agent

        repo_root = (
            (result.get("state") or {})
            .get("repository", {})
            .get("local_paths", {})
            .get("repo_root")
        )
        if not repo_root:
            console.print("[yellow]Agent connection skipped: generated repo path was not found.[/yellow]")
            return 0
        connection = connect_agent(
            repo_root,
            client=args.connect_client,
            server_name=args.connect_name,
            write=args.connect_write,
            allow_unvalidated=args.allow_unvalidated_connect,
        )
        console.print_json(data={
            "agent_connection": connection.get("connection", {}),
            "files": connection.get("files", {}),
        })
        return 0
    except Exception as connect_error:
        from src.utils import redact_sensitive_text

        console.print(f"[bold red]Agent connection failed: {redact_sensitive_text(connect_error)}[/bold red]")
        return 1


def print_config_info(config_manager):
    try:
        providers = config_manager.list_available_providers()
        default_provider = config_manager.get_default_provider()
        table = Table(title="LLM Configuration Information")
        table.add_column("Configuration Item", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Available Providers", ", ".join(providers))
        table.add_row("Default Provider", default_provider)
        current_config = config_manager.get_model_config()
        table.add_row("Current Model", f"{current_config.provider} - {current_config.model_version}")
        table.add_row("API Base URL", current_config.base_url)
        table.add_row("Temperature", str(current_config.temperature))
        table.add_row("Max Tokens", str(current_config.max_tokens))
        console.print(table)
    except Exception as e:
        console.print(f"[red]Failed to get configuration information: {e}[/red]")

async def main() -> int:
    if sys.version_info < (3, 10):
        console.print("[red]Python 3.10 or newer is required. Please create the environment with Python 3.10+.[/red]")
        return 1

    parser = argparse.ArgumentParser(description="Code2MCP: Automated Code Repository to MCP Service Conversion System")
    parser.add_argument("repo_url", help="Target code repository URL")
    parser.add_argument("target", nargs="?", default="hf", choices=["local", "hf"], help="Deployment target: local or hf")
    parser.add_argument("--output", "-o", default="./output", help="Output directory")
    parser.add_argument("--provider", "-p", help="Specify LLM provider (openai/openai-codex/deepseek/qwen/claude)")
    parser.add_argument("--config", "-c", help="Configuration file path")
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help=GENERATE_ONLY_HELP,
    )
    parser.add_argument(
        "--connect-client",
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
        help="Prepare or install MCP agent client configuration after generation",
    )
    parser.add_argument("--connect-name", help="MCP server name shown in the agent client")
    parser.add_argument(
        "--connect-write",
        action="store_true",
        help="Write/install client configuration. Without this flag, Code2MCP only prints the config payload.",
    )
    parser.add_argument(
        "--allow-unvalidated-connect",
        action="store_true",
        help="Allow client configuration even if the generated MCP service is not validated",
    )
    provider = os.getenv("MODEL_PROVIDER", "openai").lower()
    if provider == "deepseek":
        default_deepwiki_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v3")
    elif provider == "qwen":
        default_deepwiki_model = os.getenv("QWEN_MODEL", "qwen-3")
    elif provider == "claude":
        default_deepwiki_model = os.getenv("CLAUDE_MODEL", "claude-4-sonnet")
    elif provider == "openai-codex":
        default_deepwiki_model = os.getenv("OPENAI_CODEX_MODEL", "gpt-5.5")
    else:
        default_deepwiki_model = os.getenv("OPENAI_MODEL", "gpt-5")

    parser.add_argument("--deepwiki-model", default=default_deepwiki_model, help=f"DeepWiki model to use (default: {default_deepwiki_model})")

    args = parser.parse_args()
    model_config = None
    if args.provider:
        os.environ["MODEL_PROVIDER"] = args.provider.lower()
        try:
            console.print(f"[green]Using specified provider: {args.provider}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to configure specified provider: {e}[/red]")
            return 2

    from src.workflow import WorkflowOrchestrator as ClassicWorkflowOrchestrator

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = ClassicWorkflowOrchestrator(
        output_dir=str(output_dir), config=model_config
    )

    console.print("Running Code2MCP workflow...")
    try:
        workflow_options = {
            "deepwiki_model": args.deepwiki_model,
            "deploy_target": args.target,
            "generate_only": args.generate_only or args.target == "hf",
        }
        result = await orchestrator.run_workflow(args.repo_url, options=workflow_options)
        workflow_status = result.get("workflow_status") or (result.get("state") or {}).get("workflow_status")
        if result.get("success"):
            console.print(f"[bold green]{result.get('message', 'Workflow completed')}[/bold green]")
            if args.connect_client:
                return _connect_agent_from_workflow_result(result, args)
            return 0
        if workflow_status == "generated" and result.get("completed"):
            console.print(f"[bold yellow]{result.get('message', 'MCP service generated without runtime validation')}[/bold yellow]")
            if args.connect_client:
                return _connect_agent_from_workflow_result(result, args)
            return 0
        console.print(f"[bold red]{result.get('message', 'Workflow execution failed')}[/bold red]")
        return 1
    except Exception as e:
        console.print(f"[bold red]Workflow exception: {e}[/bold red]")
        return 1

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
