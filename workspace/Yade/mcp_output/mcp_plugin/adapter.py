# -*- coding: utf-8 -*-
"""
This module contains the Adapter class for the Yade MCP service.
It provides a bridge between the MCP service and the core functionalities of the Yade system.
"""

import os
import sys
from typing import Dict, Any

# Set path
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
if source_path not in sys.path:
    sys.path.insert(0, source_path)

# Import modules
try:
    from yade import qt
    from yade.tests import test_pbc, test_wrapper, test_core, test_engines
    from yade.py_geometry import bodiesHandling, gridpfacet
    from yade.pack import _packObb, _packPredicates, _packSpheres
    from yade.runtime import timing, system
    IMPORT_SUCCESS = True
except ImportError as e:
    IMPORT_SUCCESS = False
    print(f"Module import failed: {e}, entering fallback mode.")

class Adapter:
    """
    MCP plugin Import mode adapter class.
    Provides encapsulation and adaptation for the classes and functions identified in the analysis results.
    """

    def __init__(self):
        """
        Initialize the adapter class.
        Set mode to "import" and initialize status.
        """
        self.mode = "import"
        if not IMPORT_SUCCESS:
            self.mode = "fallback"

    # -------------------- Qt4 Functionality Module --------------------

    def create_qt4_glviewer(self) -> Dict[str, Any]:
        """
        Create a Qt4 GLViewer instance.
        :return: A dictionary containing the status and instance.
        """
        try:
            instance = qt.GLViewer()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create GLViewer: {e}"}

    def create_qt4_serializable_editor(self) -> Dict[str, Any]:
        """
        Create a Qt4 SerializableEditor instance.
        :return: A dictionary containing the status and instance.
        """
        try:
            instance = qt.SerializableEditor()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create SerializableEditor: {e}"}

    def create_qt4_opengl_manager(self) -> Dict[str, Any]:
        """
        Create a Qt4 OpenGLManager instance.
        :return: A dictionary containing the status and instance.
        """
        try:
            instance = qt.OpenGLManager()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create OpenGLManager: {e}"}

    # -------------------- Qt5 Functionality Module --------------------

    def create_qt5_glviewer(self) -> Dict[str, Any]:
        """
        Create a Qt5 GLViewer instance.
        :return: A dictionary containing the status and instance.
        """
        try:
            instance = qt.GLViewer()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create GLViewer: {e}"}

    def create_qt5_serializable_editor(self) -> Dict[str, Any]:
        """
        Create a Qt5 SerializableEditor instance.
        :return: A dictionary containing the status and instance.
        """
        try:
            instance = qt.SerializableEditor()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create SerializableEditor: {e}"}

    def create_qt5_opengl_manager(self) -> Dict[str, Any]:
        """
        Create a Qt5 OpenGLManager instance.
        :return: A dictionary containing the status and instance.
        """
        try:
            instance = qt.OpenGLManager()
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create OpenGLManager: {e}"}

    # -------------------- Test Module Functionality --------------------

    def call_test_core(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the core function in the test module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = test_core.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call core function: {e}"}

    def call_test_engines(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the engines function in the test module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = test_engines.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call engines function: {e}"}

    def call_test_pbc(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the pbc function in the test module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = test_pbc.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call pbc function: {e}"}

    def call_test_wrapper(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the wrapper function in the test module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = test_wrapper.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call wrapper function: {e}"}

    # -------------------- Geometry Module Functionality --------------------

    def call_bodies_handling(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the bodiesHandling function in the geometry module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = bodiesHandling.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call bodiesHandling function: {e}"}

    def call_gridpfacet(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the gridpfacet function in the geometry module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = gridpfacet.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call gridpfacet function: {e}"}

    # -------------------- Packing Module Functionality --------------------

    def call_pack_obb(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the _packObb function in the packing module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = _packObb.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call _packObb function: {e}"}

    def call_pack_predicates(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the _packPredicates function in the packing module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = _packPredicates.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call _packPredicates function: {e}"}

    def call_pack_spheres(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the _packSpheres function in the packing module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = _packSpheres.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call _packSpheres function: {e}"}

    # -------------------- Runtime Module Functionality --------------------

    def call_timing(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the timing function in the runtime module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = timing.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call timing function: {e}"}

    def call_system(self, *args, **kwargs) -> Dict[str, Any]:
        """
        Call the system function in the runtime module.
        :param args: Positional arguments.
        :param kwargs: Keyword arguments.
        :return: A dictionary containing the status and result.
        """
        try:
            result = system.main(*args, **kwargs)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Failed to call system function: {e}"}

    # -------------------- Fallback Mode Prompt --------------------

    def fallback_mode_prompt(self) -> Dict[str, Any]:
        """
        Provide a friendly prompt for fallback mode.
        :return: A dictionary containing the status and prompt message.
        """
        return {"status": "warning", "message": "Some modules were not imported successfully, functionality may be limited."}