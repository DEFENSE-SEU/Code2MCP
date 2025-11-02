"""
MCP Service Auto-Wrapper - Auto-generated
"""
from mcp_service import create_app

def main():
    """Main entry point"""
    app = create_app()
    return app

if __name__ == "__main__":
    app = main()
    app.run()