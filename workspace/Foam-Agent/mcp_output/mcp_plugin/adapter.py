# -*- coding: utf-8 -*-
"""
This module contains the Adapter class for the Foam-Agent MCP service.
It provides a bridge between the MCP service and the core functionalities of the Foam-Agent system.
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
    from src.nodes.architect_node import ArchitectNode
    from src.nodes.meshing_node import MeshingNode
    from src.nodes.input_writer_node import InputWriterNode
    from src.nodes.local_runner_node import LocalRunnerNode
    from src.nodes.reviewer_node import ReviewerNode
    from src.nodes.visualization_node import VisualizationNode
    from src.utils.router import Router
    from src.utils.aws_event_tracker import AWSEventTracker
    from src.utils.data_parser import DataParser
    from src.utils.input_validator import InputValidator
    from src.foam_gpt.data_loader import DataLoader
    from src.foam_gpt.data_saver import DataSaver
    from src.foam_gpt.foam_generator import FoamGenerator
    from src.foam_gpt.huggingface_integrator import HuggingFaceIntegrator
    from src.foam_gpt.openai_integrator import OpenAIIntegrator
    from src.foam_gpt.output_parser import OutputParser
    from src.faiss_scripts.run_index import FAISSIndexer
    from src.faiss_scripts.get_help import FAISSHelp
    from src.faiss_scripts.get_tutorial_details import FAISSTutorialDetails
    from src.faiss_scripts.get_tutorial_structure import FAISSTutorialStructure
    from src.faiss_scripts.parse_tutorial import TutorialParser
except ImportError as e:
    print(f"Module import failed: {e}. Please check the path settings or module existence.")

class Adapter:
    """
    MCP plugin Import mode adapter class.
    Provides encapsulation and adaptation for Foam-Agent system functionalities.
    """

    def __init__(self):
        self.mode = "import"

    # -------------------- Node Class Instantiation Methods --------------------

    def instantiate_architect_node(self) -> Dict[str, Any]:
        """Instantiates the ArchitectNode class"""
        try:
            ArchitectNode()
            return {"status": "success", "message": "ArchitectNode instantiated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"ArchitectNode instantiation failed: {e}"}

    def instantiate_meshing_node(self) -> Dict[str, Any]:
        """Instantiates the MeshingNode class"""
        try:
            MeshingNode()
            return {"status": "success", "message": "MeshingNode instantiated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"MeshingNode instantiation failed: {e}"}

    def instantiate_input_writer_node(self) -> Dict[str, Any]:
        """Instantiates the InputWriterNode class"""
        try:
            InputWriterNode()
            return {"status": "success", "message": "InputWriterNode instantiated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"InputWriterNode instantiation failed: {e}"}

    def instantiate_local_runner_node(self) -> Dict[str, Any]:
        """Instantiates the LocalRunnerNode class"""
        try:
            LocalRunnerNode()
            return {"status": "success", "message": "LocalRunnerNode instantiated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"LocalRunnerNode instantiation failed: {e}"}

    def instantiate_reviewer_node(self) -> Dict[str, Any]:
        """Instantiates the ReviewerNode class"""
        try:
            ReviewerNode()
            return {"status": "success", "message": "ReviewerNode instantiated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"ReviewerNode instantiation failed: {e}"}

    def instantiate_visualization_node(self) -> Dict[str, Any]:
        """Instantiates the VisualizationNode class"""
        try:
            VisualizationNode()
            return {"status": "success", "message": "VisualizationNode instantiated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"VisualizationNode instantiation failed: {e}"}

    # -------------------- Routing Logic Methods --------------------

    def route_task_to_agent(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Routes a task to a specified agent.
        :param task_data: Task data
        :return: Status dictionary
        """
        try:
            Router().route(task_data)
            return {"status": "success", "message": "Task routed successfully"}
        except Exception as e:
            return {"status": "error", "message": f"Task routing failed: {e}"}

    # -------------------- AWS Event Tracking Methods --------------------

    def track_aws_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tracks AWS-related events.
        :param event_data: Event data
        :return: Status dictionary
        """
        try:
            AWSEventTracker().track(event_data)
            return {"status": "success", "message": "AWS event tracked successfully"}
        except Exception as e:
            return {"status": "error", "message": f"AWS event tracking failed: {e}"}

    # -------------------- Utility Methods --------------------

    def parse_data(self, raw_data: Any) -> Dict[str, Any]:
        """Parses data.
        :param raw_data: Raw data
        :return: Status dictionary
        """
        try:
            parsed_data = DataParser().parse(raw_data)
            return {"status": "success", "data": parsed_data}
        except Exception as e:
            return {"status": "error", "message": f"Data parsing failed: {e}"}

    def validate_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validates input data.
        :param input_data: Input data
        :return: Status dictionary
        """
        try:
            InputValidator().validate(input_data)
            return {"status": "success", "message": "Input validated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"Input validation failed: {e}"}

    # -------------------- FoamGPT Related Methods --------------------

    def load_foam_gpt_data(self, file_path: str) -> Dict[str, Any]:
        """Loads FoamGPT data.
        :param file_path: File path
        :return: Status dictionary
        """
        try:
            data = DataLoader().load(file_path)
            return {"status": "success", "data": data}
        except Exception as e:
            return {"status": "error", "message": f"Failed to load FoamGPT data: {e}"}

    def save_foam_gpt_data(self, data: Any, file_path: str) -> Dict[str, Any]:
        """Saves FoamGPT data.
        :param data: Data
        :param file_path: File path
        :return: Status dictionary
        """
        try:
            DataSaver().save(data, file_path)
            return {"status": "success", "message": "FoamGPT data saved successfully"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to save FoamGPT data: {e}"}

    def generate_foam_output_with_gpt(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generates Foam-related output using GPT.
        :param input_data: Input data
        :return: Status dictionary
        """
        try:
            output = FoamGenerator().generate(input_data)
            return {"status": "success", "output": output}
        except Exception as e:
            return {"status": "error", "message": f"Failed to generate Foam output: {e}"}

    def integrate_huggingface_model(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        """Integrates a Hugging Face model.
        :param model_data: Model data
        :return: Status dictionary
        """
        try:
            HuggingFaceIntegrator().integrate(model_data)
            return {"status": "success", "message": "Hugging Face model integrated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"Hugging Face integration failed: {e}"}

    def integrate_openai_model(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        """Integrates an OpenAI GPT model.
        :param model_data: Model data
        :return: Status dictionary
        """
        try:
            OpenAIIntegrator().integrate(model_data)
            return {"status": "success", "message": "OpenAI model integrated successfully"}
        except Exception as e:
            return {"status": "error", "message": f"OpenAI integration failed: {e}"}

    def parse_foam_gpt_output(self, output_data: Any) -> Dict[str, Any]:
        """Parses FoamGPT generated output.
        :param output_data: Output data
        :return: Status dictionary
        """
        try:
            parsed_output = OutputParser().parse(output_data)
            return {"status": "success", "parsed_output": parsed_output}
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse Foam output: {e}"}

    # -------------------- FAISS Related Methods --------------------

    def run_faiss_script(self, index_data: Dict[str, Any]) -> Dict[str, Any]:
        """Runs FAISS index related scripts.
        :param index_data: Index data
        :return: Status dictionary
        """
        try:
            FAISSIndexer().run(index_data)
            return {"status": "success", "message": "FAISS index script ran successfully"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to run FAISS index script: {e}"}

    def get_faiss_help(self) -> Dict[str, Any]:
        """Gets help information for FAISS commands.
        :return: Status dictionary
        """
        try:
            help_info = FAISSHelp().get()
            return {"status": "success", "help": help_info}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get FAISS help information: {e}"}

    def get_faiss_tutorial_details(self, tutorial_id: str) -> Dict[str, Any]:
        """Gets detailed information for a FAISS tutorial.
        :param tutorial_id: Tutorial ID
        :return: Status dictionary
        """
        try:
            details = FAISSTutorialDetails().get(tutorial_id)
            return {"status": "success", "details": details}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get tutorial details: {e}"}

    def get_faiss_tutorial_structure(self, tutorial_id: str) -> Dict[str, Any]:
        """Gets structure information for a FAISS tutorial.
        :param tutorial_id: Tutorial ID
        :return: Status dictionary
        """
        try:
            structure = FAISSTutorialStructure().get(tutorial_id)
            return {"status": "success", "structure": structure}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get tutorial structure information: {e}"}

    def parse_faiss_tutorial_content(self, tutorial_data: Any) -> Dict[str, Any]:
        """Parses tutorial content.
        :param tutorial_data: Tutorial data
        :return: Status dictionary
        """
        try:
            parsed_content = TutorialParser().parse(tutorial_data)
            return {"status": "success", "parsed_content": parsed_content}
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse tutorial content: {e}"}

# -------------------- End of Adapter Class --------------------