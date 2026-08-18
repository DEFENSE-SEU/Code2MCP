# -*- coding: utf-8 -*-
"""
This module provides an MCP (Model Context Protocol) service for the Foam-Agent system.
It exposes the core functionalities of Foam-Agent, such as node instantiation, task routing,
and data handling, through a standardized service interface.

This service is auto-generated and adapted from the source code of the Foam-Agent project.
"""

import os
import sys
from typing import Dict, Any

# Add project root to Python path to allow for module imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mcp_plugin_dir = os.path.join(project_root, "mcp_plugin")
if mcp_plugin_dir not in sys.path:
    sys.path.insert(0, mcp_plugin_dir)

# Set path to the source directory of the original project
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
if source_path not in sys.path:
    sys.path.insert(0, source_path)

from fastmcp import FastMCP
from adapter import Adapter

# Initialize FastMCP application and the adapter
mcp = FastMCP("FoamAgentService")
adapter = Adapter()

# -------------------- Core Agent and System Tools --------------------

@mcp.tool(name="route_task_to_agent", description="Routes a task to a specified agent for processing.")
def route_task_to_agent(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Routes a task to a specified agent based on the task data provided.

    :param task_data: A dictionary containing task details, including the target agent.
    :return: A dictionary with the status of the routing operation.
    """
    return adapter.route_task_to_agent(task_data)

@mcp.tool(name="track_aws_event", description="Tracks AWS-related events within the system.")
def track_aws_event(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tracks events related to AWS services, such as S3, EC2, etc.

    :param event_data: A dictionary containing event details.
    :return: A dictionary with the status of the event tracking.
    """
    return adapter.track_aws_event(event_data)

@mcp.tool(name="parse_data", description="Parses raw data into a structured format.")
def parse_data(raw_data: Any) -> Dict[str, Any]:
    """
    Parses raw input data into a structured format that can be used by the system.

    :param raw_data: The raw data to be parsed.
    :return: A dictionary with the parsed data or an error status.
    """
    return adapter.parse_data(raw_data)

@mcp.tool(name="validate_input", description="Validates the structure and content of input data.")
def validate_input(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates the input data to ensure it meets the required format and constraints.

    :param input_data: The input data to be validated.
    :return: A dictionary indicating whether the validation was successful.
    """
    return adapter.validate_input(input_data)

# -------------------- FoamGPT Data Pipeline Tools --------------------

@mcp.tool(name="load_foam_gpt_data", description="Loads data for the FoamGPT pipeline.")
def load_foam_gpt_data(file_path: str) -> Dict[str, Any]:
    """
    Loads data from a specified file path for use in the FoamGPT pipeline.

    :param file_path: The path to the data file.
    :return: A dictionary with the status of the data loading operation.
    """
    return adapter.load_foam_gpt_data(file_path)

@mcp.tool(name="save_foam_gpt_data", description="Saves data from the FoamGPT pipeline.")
def save_foam_gpt_data(data: Any, file_path: str) -> Dict[str, Any]:
    """
    Saves the provided data to a specified file path.

    :param data: The data to be saved.
    :param file_path: The path where the data will be saved.
    :return: A dictionary with the status of the save operation.
    """
    return adapter.save_foam_gpt_data(data, file_path)

@mcp.tool(name="generate_foam_output_with_gpt", description="Generates Foam-related output using a GPT model.")
def generate_foam_output_with_gpt(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses a GPT model to generate outputs related to Foam simulations or data.

    :param input_data: The input data to be used for generation.
    :return: A dictionary with the generated output or an error status.
    """
    return adapter.generate_foam_output_with_gpt(input_data)

@mcp.tool(name="integrate_huggingface_model", description="Integrates a Hugging Face model into the pipeline.")
def integrate_huggingface_model(model_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Integrates a model from the Hugging Face Hub into the FoamGPT pipeline.

    :param model_data: A dictionary containing model details.
    :return: A dictionary with the status of the integration.
    """
    return adapter.integrate_huggingface_model(model_data)

@mcp.tool(name="integrate_openai_model", description="Integrates an OpenAI GPT model into the pipeline.")
def integrate_openai_model(model_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Integrates an OpenAI GPT model for use in the FoamGPT pipeline.

    :param model_data: A dictionary containing model and API details.
    :return: A dictionary with the status of the integration.
    """
    return adapter.integrate_openai_model(model_data)

@mcp.tool(name="parse_foam_gpt_output", description="Parses the output generated by FoamGPT.")
def parse_foam_gpt_output(output_data: Any) -> Dict[str, Any]:
    """
    Parses the output from FoamGPT into a structured format.

    :param output_data: The output data from FoamGPT.
    :return: A dictionary with the parsed output or an error status.
    """
    return adapter.parse_foam_gpt_output(output_data)

# -------------------- FAISS Integration Tools --------------------

@mcp.tool(name="run_faiss_script", description="Runs a script related to FAISS indexing.")
def run_faiss_script(index_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs a script for FAISS, such as building or searching an index.

    :param index_data: Data required for the FAISS script.
    :return: A dictionary with the result of the script execution.
    """
    return adapter.run_faiss_script(index_data)

@mcp.tool(name="get_faiss_help", description="Gets help information for FAISS commands.")
def get_faiss_help() -> Dict[str, Any]:
    """
    Retrieves help information or documentation for FAISS-related commands.

    :return: A dictionary containing the help information.
    """
    return adapter.get_faiss_help()

@mcp.tool(name="get_faiss_tutorial_details", description="Gets details for a specific FAISS tutorial.")
def get_faiss_tutorial_details(tutorial_id: str) -> Dict[str, Any]:
    """
    Retrieves detailed information for a given FAISS tutorial ID.

    :param tutorial_id: The ID of the tutorial.
    :return: A dictionary with the tutorial details.
    """
    return adapter.get_faiss_tutorial_details(tutorial_id)

@mcp.tool(name="get_faiss_tutorial_structure", description="Gets the structure of a FAISS tutorial.")
def get_faiss_tutorial_structure(tutorial_id: str) -> Dict[str, Any]:
    """
    Retrieves the structural information of a FAISS tutorial.

    :param tutorial_id: The ID of the tutorial.
    :return: A dictionary with the tutorial structure.
    """
    return adapter.get_faiss_tutorial_structure(tutorial_id)

@mcp.tool(name="parse_faiss_tutorial_content", description="Parses the content of a FAISS tutorial.")
def parse_faiss_tutorial_content(tutorial_data: Any) -> Dict[str, Any]:
    """
    Parses the content of a FAISS tutorial into a structured format.

    :param tutorial_data: The raw content of the tutorial.
    :return: A dictionary with the parsed content.
    """
    return adapter.parse_faiss_tutorial_content(tutorial_data)


# -------------------- Additional Tools: Node Instantiation (Union with adapter.py) --------------------

@mcp.tool(name="instantiate_architect_node", description="Instantiates the ArchitectNode class.")
def instantiate_architect_node() -> Dict[str, Any]:
    """
    Instantiates the ArchitectNode class from the adapter.
    """
    return adapter.instantiate_architect_node()

@mcp.tool(name="instantiate_meshing_node", description="Instantiates the MeshingNode class.")
def instantiate_meshing_node() -> Dict[str, Any]:
    """
    Instantiates the MeshingNode class from the adapter.
    """
    return adapter.instantiate_meshing_node()

@mcp.tool(name="instantiate_input_writer_node", description="Instantiates the InputWriterNode class.")
def instantiate_input_writer_node() -> Dict[str, Any]:
    """
    Instantiates the InputWriterNode class from the adapter.
    """
    return adapter.instantiate_input_writer_node()

@mcp.tool(name="instantiate_local_runner_node", description="Instantiates the LocalRunnerNode class.")
def instantiate_local_runner_node() -> Dict[str, Any]:
    """
    Instantiates the LocalRunnerNode class from the adapter.
    """
    return adapter.instantiate_local_runner_node()

@mcp.tool(name="instantiate_reviewer_node", description="Instantiates the ReviewerNode class.")
def instantiate_reviewer_node() -> Dict[str, Any]:
    """
    Instantiates the ReviewerNode class from the adapter.
    """
    return adapter.instantiate_reviewer_node()

@mcp.tool(name="instantiate_visualization_node", description="Instantiates the VisualizationNode class.")
def instantiate_visualization_node() -> Dict[str, Any]:
    """
    Instantiates the VisualizationNode class from the adapter.
    """
    return adapter.instantiate_visualization_node()


def create_app():
    """
    Creates and returns the FastMCP application instance.

    This function is the entry point for the MCP service.
    """
    return mcp
