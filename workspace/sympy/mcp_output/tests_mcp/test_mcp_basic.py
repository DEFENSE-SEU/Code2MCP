import sys
import os

# Add mcp_plugin directory to path to resolve adapter import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mcp_plugin')))

"""
MCP Service Basic Tests
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp_plugin_dir = os.path.join(project_root, "mcp_plugin")
if mcp_plugin_dir not in sys.path:
    sys.path.insert(0, mcp_plugin_dir)

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

   # ------------- Test MCP Service ---------------

def test_import_mcp_service():
    """Test that the MCP service can be imported correctly"""
    try:
        from ..mcp_plugin.mcp_service import create_app
        app = create_app()
        assert app is not None
        print("MCP service imported successfully")
        return True
    except Exception as e:
        print(f"Failed to import MCP service: {e}")
        return False

def test_adapter_init():
    """Test that the adapter can be initialized correctly"""
    try:
        from ..mcp_plugin.adapter import Adapter
        adapter = Adapter()
        assert adapter is not None
        print("Adapter initialized successfully")
        return True
    except Exception as e:
        print(f"Failed to initialize adapter: {e}")
        return False

if __name__ == "__main__":
    print("Running MCP service basic tests...")
    test1 = test_import_mcp_service()
    test2 = test_adapter_init()
    
    if test1 and test2:
        print("All basic tests passed")
        sys.exit(0)
    else:
        print("Some tests failed")
        sys.exit(1)