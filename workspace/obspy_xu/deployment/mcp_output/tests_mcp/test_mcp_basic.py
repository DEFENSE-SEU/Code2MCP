"""
MCP Service Basic Test
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp_plugin_dir = os.path.join(project_root, "mcp_plugin")
if mcp_plugin_dir not in sys.path:
    sys.path.insert(0, mcp_plugin_dir)

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

def test_import_mcp_service():
    """Test if MCP service can be imported normally"""
    try:
        from mcp_service import create_app
        app = create_app()
        assert app is not None
        print("MCP service imported successfully")
        return True
    except Exception as e:
        print("MCP service import failed: " + str(e))
        return False

def test_adapter_init():
    """Test if adapter can be initialized normally"""
    try:
        from adapter import Adapter
        adapter = Adapter()
        assert adapter is not None
        print("Adapter initialized successfully")
        return True
    except Exception as e:
        print("Adapter initialization failed: " + str(e))
        return False

if __name__ == "__main__":
    print("Running MCP service basic test...")
    test1 = test_import_mcp_service()
    test2 = test_adapter_init()
    
    if test1 and test2:
        print("All basic tests passed")
        sys.exit(0)
    else:
        print("Some tests failed")
        sys.exit(1)
