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
                    os.environ[key] = value

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
    else:
        print(f"Environment file not found: {env_file}")
except ImportError:
    print("python-dotenv not installed, please set environment variables manually")

import logging
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

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

async def main():
    parser = argparse.ArgumentParser(description="Code2MCP: Automated Code Repository to MCP Service Conversion System")
    parser.add_argument("repo_url", help="Target code repository URL")
    parser.add_argument("--output", "-o", default="./output", help="Output directory")
    parser.add_argument("--provider", "-p", help="Specify LLM provider (openai/deepseek)")
    parser.add_argument("--config", "-c", help="Configuration file path")
    provider = os.getenv("MODEL_PROVIDER", "openai").lower()
    if provider == "deepseek":
        default_deepwiki_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v3")
    elif provider == "qwen":
        default_deepwiki_model = os.getenv("QWEN_MODEL", "qwen-3")
    elif provider == "claude":
        default_deepwiki_model = os.getenv("CLAUDE_MODEL", "claude-4-sonnet")
    else:
        default_deepwiki_model = os.getenv("OPENAI_MODEL", "gpt-5")
    
    parser.add_argument("--deepwiki-model", default=default_deepwiki_model, help=f"DeepWiki model to use (default: {default_deepwiki_model})")

    args = parser.parse_args()
    model_config = None
    if args.provider:
        try:
            console.print(f"[green]Using specified provider: {args.provider}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to configure specified provider: {e}[/red]")
            return

    from src.workflow import WorkflowOrchestrator as ClassicWorkflowOrchestrator

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = ClassicWorkflowOrchestrator(
        output_dir=str(output_dir), config=model_config
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running Code2MCP workflow...", total=None)
        try:
            workflow_options = {
                "deepwiki_model": args.deepwiki_model,
            }
            result = await orchestrator.run_workflow(args.repo_url, options=workflow_options)
            progress.update(task, completed=True)
            if result.get("success"):
                console.print("[bold green]Workflow executed successfully![/bold green]")
                return
            else:
                console.print("[bold red]Workflow execution failed![/bold red]")
                return
        except Exception as e:
            progress.update(task, completed=True)
            return

if __name__ == "__main__":
    asyncio.run(main()) 