#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import argparse
from pathlib import Path
import platform


def get_cursor_config_path():
    base_dir = Path.home() / ".cursor"
    
    for config_name in ["mcp_settings.json", "mcp.json"]:
        config_path = base_dir / config_name
        if config_path.exists():
            return config_path
    
    return base_dir / "mcp_settings.json"


def connect_cursor_remote(mcp_name, remote_url):
    try:
        config_path = get_cursor_config_path()
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, PermissionError):
                config = {"mcpServers": {}}
        else:
            config = {"mcpServers": {}}
        
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        
        config["mcpServers"][mcp_name] = {
            "url": f"{remote_url.rstrip('/')}/mcp"
        }
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        return True
    except (PermissionError, OSError):
        return False


def connect_cursor_local(mcp_name, project_dir):
    try:
        project_path = Path(project_dir).resolve()
        start_mcp = project_path / "mcp_output" / "start_mcp.py"
        
        if not start_mcp.exists():
            return False
        
        venv_paths = [
            project_path / "mcp_output" / ".venv" / "bin" / "python",
            project_path / "mcp_output" / ".venv" / "Scripts" / "python.exe",
            project_path / ".venv" / "bin" / "python",
            project_path / ".venv" / "Scripts" / "python.exe",
        ]
        
        venv_python = "python"
        for venv_path in venv_paths:
            if venv_path.exists():
                venv_python = str(venv_path.resolve())
                break
        
        config_path = get_cursor_config_path()
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, PermissionError):
                config = {"mcpServers": {}}
        else:
            config = {"mcpServers": {}}
        
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        
        config["mcpServers"][mcp_name] = {
            "command": venv_python,
            "args": [str(start_mcp.resolve())]
        }
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        return True
    except (PermissionError, OSError):
        return False


def connect_claude_remote(mcp_name, remote_url):
    cmd = ["claude", "mcp", "add", "--transport", "http", mcp_name, f"{remote_url.rstrip('/')}/mcp"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def connect_claude_local(mcp_name, project_dir):
    project_path = Path(project_dir).resolve()
    start_mcp = project_path / "mcp_output" / "start_mcp.py"
    
    if not start_mcp.exists():
        return False
    
    venv_paths = [
        project_path / "mcp_output" / ".venv" / "bin" / "python",
        project_path / "mcp_output" / ".venv" / "Scripts" / "python.exe",
        project_path / ".venv" / "bin" / "python",
        project_path / ".venv" / "Scripts" / "python.exe",
    ]
    
    venv_python = "python"
    for venv_path in venv_paths:
        if venv_path.exists():
            venv_python = str(venv_path)
            break
    
    cmd = ["fastmcp", "install", "claude-code", str(start_mcp), "--python", venv_python]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Connect MCP service")
    parser.add_argument('--client', choices=['cursor', 'claude'], required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--url')
    parser.add_argument('--local', action='store_true')
    parser.add_argument('--project')
    
    args = parser.parse_args()
    
    if args.local:
        if not args.project:
            sys.exit(1)
        if args.client == 'cursor':
            success = connect_cursor_local(args.name, args.project)
        else:
            success = connect_claude_local(args.name, args.project)
    else:
        if not args.url:
            sys.exit(1)
        if args.client == 'cursor':
            success = connect_cursor_remote(args.name, args.url)
        else:
            success = connect_claude_remote(args.name, args.url)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

