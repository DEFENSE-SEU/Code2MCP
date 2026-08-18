import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from src.dalle_mini.model.configuration import Configuration
from src.dalle_mini.model.modeling import Modeling
from src.dalle_mini.model.processor import Processor
from tools.train.train import train
from tools.inference.inference_pipeline import inference_pipeline

# Initialize FastMCP service
mcp = FastMCP("dalle_mini_service")

# Tool: Configuration Loader
@mcp.tool(name="load_configuration", description="Load model configuration.")
def load_configuration(config_path: str) -> dict:
    """
    Load the model configuration from a given path.

    Parameters:
        config_path (str): Path to the configuration file.

    Returns:
        dict: A dictionary containing success, result, or error fields.
    """
    try:
        config = Configuration.load(config_path)
        return {"success": True, "result": config.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Tool: Model Initialization
@mcp.tool(name="initialize_model", description="Initialize the DALL-E Mini model.")
def initialize_model(config_path: str) -> dict:
    """
    Initialize the DALL-E Mini model using a configuration file.

    Parameters:
        config_path (str): Path to the configuration file.

    Returns:
        dict: A dictionary containing success, result, or error fields.
    """
    try:
        config = Configuration.load(config_path)
        model = Modeling(config)
        return {"success": True, "result": "Model initialized successfully."}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Tool: Data Processing
@mcp.tool(name="process_data", description="Process input data for the model.")
def process_data(input_data: str) -> dict:
    """
    Process input data for the DALL-E Mini model.

    Parameters:
        input_data (str): Raw input data to be processed.

    Returns:
        dict: A dictionary containing success, result, or error fields.
    """
    try:
        processed_data = Processor.process(input_data)
        return {"success": True, "result": processed_data}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Tool: Model Training
@mcp.tool(name="train_model", description="Train the DALL-E Mini model.")
def train_model(config_path: str, dataset_path: str) -> dict:
    """
    Train the DALL-E Mini model using the specified configuration and dataset.

    Parameters:
        config_path (str): Path to the configuration file.
        dataset_path (str): Path to the training dataset.

    Returns:
        dict: A dictionary containing success, result, or error fields.
    """
    try:
        train(config_path=config_path, dataset_path=dataset_path)
        return {"success": True, "result": "Model training completed successfully."}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Tool: Model Inference
@mcp.tool(name="run_inference", description="Run inference using the DALL-E Mini model.")
def run_inference(input_data: str, model_path: str) -> dict:
    """
    Run inference on the DALL-E Mini model with the given input data.

    Parameters:
        input_data (str): Input data for inference.
        model_path (str): Path to the trained model.

    Returns:
        dict: A dictionary containing success, result, or error fields.
    """
    try:
        result = inference_pipeline(input_data=input_data, model_path=model_path)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Health Check Endpoint
@mcp.tool(name="health_check", description="Check the health of the service.")
def health_check() -> dict:
    """
    Perform a health check for the service.

    Returns:
        dict: A dictionary containing success and result fields.
    """
    return {"success": True, "result": "Service is healthy."}

# Version Information Endpoint
@mcp.tool(name="get_version", description="Get the version of the service.")
def get_version() -> dict:
    """
    Retrieve the version information of the service.

    Returns:
        dict: A dictionary containing success and result fields.
    """
    return {"success": True, "result": "DALL-E Mini Service v1.0.0"}

# Create App Function
def create_app() -> FastMCP:
    """
    Create and return the FastMCP application instance.

    Returns:
        FastMCP: The initialized FastMCP instance.
    """
    return mcp