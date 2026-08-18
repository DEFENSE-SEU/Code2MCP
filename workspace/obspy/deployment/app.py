from fastapi import FastAPI
import os
import sys

mcp_plugin_path = os.path.join(os.path.dirname(__file__), "obspy", "mcp_output", "mcp_plugin")
sys.path.insert(0, mcp_plugin_path)

app = FastAPI(
    title="Obspy MCP Service",
    description="Auto-generated MCP service for obspy",
    version="1.0.0"
)

@app.get("/")
def root():
    return {
        "service": "Obspy MCP Service",
        "version": "1.0.0",
        "status": "running",
        "transport": os.environ.get("MCP_TRANSPORT", "http")
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "obspy MCP"}

@app.get("/tools")
def list_tools():
    try:
        from mcp_service import create_app
        mcp_app = create_app()
        tools = []
        for tool_name, tool_func in mcp_app.tools.items():
            tools.append({
                "name": tool_name,
                "description": tool_func.__doc__ or "No description available"
            })
        return {"tools": tools}
    except Exception as e:
        return {"error": f"Failed to load tools: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
