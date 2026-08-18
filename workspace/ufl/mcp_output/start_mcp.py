
"""
MCP Service Startup Entry Point
"""
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
mcp_plugin_dir = os.path.join(project_root, "mcp_plugin")
if mcp_plugin_dir not in sys.path:
    sys.path.insert(0, mcp_plugin_dir)

# Set path to point to source directory
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

from mcp_service import create_app

def main():
    """Start FastMCP Service"""
    app = create_app()
    # Use environment variable to configure port, default 8000
    port = int(os.environ.get("MCP_PORT", "8000"))
    
    # Select transport mode based on environment variable
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        app.run(transport="http", host="0.0.0.0", port=port)
    else:
        # Default to STDIO mode
        app.run()

if __name__ == "__main__":
    main()
