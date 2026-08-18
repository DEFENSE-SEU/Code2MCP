import os
import sys

source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from gui.qt4 import GLViewer, SerializableEditor, OpenGLManager
from gui.qt5 import GLViewer as GLViewerQt5, SerializableEditor as SerializableEditorQt5, OpenGLManager as OpenGLManagerQt5
from py.tests import core, engines, pbc, wrapper
from py.pack import _packObb, _packPredicates, _packSpheres
from py.geom import bodiesHandling, gridpfacet
from py.runtime import timing, system

mcp = FastMCP("yade_service")

@mcp.tool
def qt4_glviewer_display():
    """Tool for Qt4 GLViewer Display."""
    return GLViewer()

@mcp.tool
def qt4_serializable_editor():
    """Tool for Qt4 Serializable Editor."""
    return SerializableEditor()

@mcp.tool
def qt4_opengl_manager():
    """Tool for Qt4 OpenGL Manager."""
    return OpenGLManager()

@mcp.tool
def qt5_glviewer_display():
    """Tool for Qt5 GLViewer Display."""
    return GLViewerQt5()

@mcp.tool
def qt5_serializable_editor():
    """Tool for Qt5 Serializable Editor."""
    return SerializableEditorQt5()

@mcp.tool
def qt5_opengl_manager():
    """Tool for Qt5 OpenGL Manager."""
    return OpenGLManagerQt5()

@mcp.tool
def test_core():
    """Run core tests."""
    return core()

@mcp.tool
def test_engines():
    """Run engine tests."""
    return engines()

@mcp.tool
def test_pbc():
    """Run PBC tests."""
    return pbc()

@mcp.tool
def test_wrapper():
    """Run wrapper tests."""
    return wrapper()

@mcp.tool
def pack_obb():
    """Tool for packing OBB."""
    return _packObb()

@mcp.tool
def pack_predicates():
    """Tool for packing predicates."""
    return _packPredicates()

@mcp.tool
def pack_spheres():
    """Tool for packing spheres."""
    return _packSpheres()

@mcp.tool
def geom_bodies_handling():
    """Tool for handling bodies in geometry."""
    return bodiesHandling()

@mcp.tool
def geom_gridpfacet():
    """Tool for grid facet geometry."""
    return gridpfacet()

@mcp.tool
def runtime_timing():
    """Tool for runtime timing."""
    return timing()

@mcp.tool
def runtime_system():
    """Tool for runtime system management."""
    return system()

@mcp.tool
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

@mcp.tool
def version_info():
    """Version information endpoint."""
    return {"version": "1.0.0", "service": "yade_service"}

def create_app():
    """Create and return the FastMCP application instance."""
    return mcp